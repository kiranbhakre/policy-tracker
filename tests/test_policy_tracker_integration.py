"""Unit tests for the custom_components/policy_tracker integration's vendored scraper.

These mirror tests/test_tracker.py, since scraper.py is a vendored
copy of tracker.py's non-CLI engine (a Home Assistant custom
integration must be self-contained in its own folder). They also
cover merge_results(), which is specific to the coordinator's
"keep the last good value on failure" behaviour.
"""

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "policy_tracker"
sys.path.insert(0, str(INTEGRATION_DIR.parent.parent))
sys.path.insert(0, str(INTEGRATION_DIR))

from scraper import (  # noqa: E402
    AccountResult,
    ConfigError,
    LoginStep,
    TrackerAccount,
    credentials_needed,
    find_gbp_amount_after_label,
    merge_results,
    parse_account,
    parse_amount,
)
from scraper import _resolve_fill_value  # noqa: E402


# --- manifest.json sanity ------------------------------------------------


def test_manifest_has_required_keys():
    manifest = json.loads((INTEGRATION_DIR / "manifest.json").read_text())
    assert manifest["domain"] == "policy_tracker"
    assert manifest["config_flow"] is True
    assert "playwright" in " ".join(manifest["requirements"])


def test_strings_and_translations_match():
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    translations = json.loads((INTEGRATION_DIR / "translations" / "en.json").read_text())
    assert strings == translations


# --- parse_amount / find_gbp_amount_after_label (parity with tracker.py) -


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Fund value: £12,345.67", Decimal("12345.67")),
        ("£500", Decimal("500")),
        ("GBP 1,000.50", Decimal("1000.50")),
        ("no amount here", None),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_find_gbp_amount_after_label_matches_case_insensitively():
    text = "TOTAL FUND VALUE\n£12,345.67\n"
    assert find_gbp_amount_after_label(text, "total fund value") == Decimal("12345.67")


# --- parse_account ---------------------------------------------------


def _valid_raw_account(**overrides) -> dict:
    raw = {
        "id": "lg_pension",
        "name": "L&G Workplace Pension",
        "provider": "Legal & General",
        "type": "pension",
        "login_url": "https://example.invalid/login",
        "logged_in_selector": "#summary",
        "fields": [{"id": "fund_value", "label": "Fund value"}],
    }
    raw.update(overrides)
    return raw


def test_parse_account_builds_expected_account():
    account = parse_account(_valid_raw_account())
    assert account.id == "lg_pension"
    assert account.fields[0].label == "Fund value"


def test_parse_account_rejects_field_with_no_label_or_selector():
    raw = _valid_raw_account(fields=[{"id": "fund_value"}])
    with pytest.raises(ConfigError, match="fund_value"):
        parse_account(raw)


# --- merge_results: the "keep the last good value on failure" rule -------


def test_merge_results_replaces_values_on_a_fresh_success():
    previous = {"acc1": AccountResult(status="ok", values={"fund_value": Decimal("100")})}
    new = {"acc1": AccountResult(status="ok", values={"fund_value": Decimal("200")})}
    merged = merge_results(previous, new)
    assert merged["acc1"].values == {"fund_value": Decimal("200")}


def test_merge_results_keeps_previous_values_on_otp_required():
    last_updated = datetime(2026, 1, 1, tzinfo=timezone.utc)
    previous = {
        "acc1": AccountResult(status="ok", values={"fund_value": Decimal("100")}, last_updated=last_updated)
    }
    new = {"acc1": AccountResult(status="otp_required")}
    merged = merge_results(previous, new)
    assert merged["acc1"].status == "otp_required"
    assert merged["acc1"].values == {"fund_value": Decimal("100")}
    assert merged["acc1"].last_updated == last_updated


def test_merge_results_keeps_previous_values_on_error():
    previous = {"acc1": AccountResult(status="ok", values={"fund_value": Decimal("100")})}
    new = {"acc1": AccountResult(status="error", error_message="boom")}
    merged = merge_results(previous, new)
    assert merged["acc1"].status == "error"
    assert merged["acc1"].error_message == "boom"
    assert merged["acc1"].values == {"fund_value": Decimal("100")}


def test_merge_results_has_nothing_to_fall_back_to_on_first_run():
    merged = merge_results({}, {"acc1": AccountResult(status="error", error_message="boom")})
    assert merged["acc1"].status == "error"
    assert merged["acc1"].values == {}


# --- credentials_needed: drives the config flow's dynamic credentials step


def _account_with_steps(account_id: str, *steps: LoginStep) -> TrackerAccount:
    return TrackerAccount(
        id=account_id,
        name=account_id,
        provider="Provider",
        type="pension",
        login_url="https://example.invalid/login",
        logged_in_selector="#summary",
        login_steps=tuple(steps),
    )


def test_credentials_needed_collects_value_credential_fields_per_account():
    accounts = [
        _account_with_steps(
            "lg_pension",
            LoginStep(action="fill", selector="#user", value_credential="username"),
            LoginStep(action="fill", selector="#pass", value_credential="password"),
        )
    ]
    assert credentials_needed(accounts) == {"lg_pension": ["password", "username"]}


def test_credentials_needed_ignores_accounts_using_value_env_only():
    accounts = [_account_with_steps("acc1", LoginStep(action="fill", selector="#user", value_env="ACC1_USER"))]
    assert credentials_needed(accounts) == {}


def test_credentials_needed_deduplicates_repeated_names():
    accounts = [
        _account_with_steps(
            "acc1",
            LoginStep(action="fill", selector="#user", value_credential="username"),
            LoginStep(action="fill", selector="#user2", value_credential="username"),
        )
    ]
    assert credentials_needed(accounts) == {"acc1": ["username"]}


def test_credentials_needed_handles_multiple_accounts_independently():
    accounts = [
        _account_with_steps("acc1", LoginStep(action="fill", selector="#user", value_credential="username")),
        _account_with_steps("acc2", LoginStep(action="fill", selector="#user", value_env="ACC2_USER")),
    ]
    assert credentials_needed(accounts) == {"acc1": ["username"]}


# --- _resolve_fill_value: value_credential / value_env / value priority


def test_resolve_fill_value_prefers_value_credential():
    step = LoginStep(action="fill", selector="#x", value_credential="password")
    assert _resolve_fill_value(step, {"password": "s3cret"}) == "s3cret"


def test_resolve_fill_value_raises_when_credential_missing():
    step = LoginStep(action="fill", selector="#x", value_credential="password")
    with pytest.raises(ConfigError, match="password"):
        _resolve_fill_value(step, {})


def test_resolve_fill_value_falls_back_to_literal_value():
    step = LoginStep(action="fill", selector="#x", value="literal")
    assert _resolve_fill_value(step, {}) == "literal"


def test_resolve_fill_value_defaults_to_empty_string():
    step = LoginStep(action="fill", selector="#x")
    assert _resolve_fill_value(step, {}) == ""


def test_resolve_fill_value_falls_back_to_value_env(monkeypatch):
    monkeypatch.setenv("TEST_ACCOUNT_USERNAME", "from-env")
    step = LoginStep(action="fill", selector="#x", value_env="TEST_ACCOUNT_USERNAME")
    assert _resolve_fill_value(step, {}) == "from-env"
