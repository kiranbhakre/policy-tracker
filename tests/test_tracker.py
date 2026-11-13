"""Unit tests for tracker.py's amount parsing, label extraction, and config loading."""

import sys
import textwrap
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker import (
    ConfigError,
    filter_logout_candidates,
    find_gbp_amount_after_label,
    find_raw_account,
    lines_with_gbp_amounts,
    load_config,
    parse_account,
    parse_amount,
    to_ha_account,
)


# --- parse_amount -----------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Fund value: £12,345.67", Decimal("12345.67")),
        ("£500", Decimal("500")),
        ("GBP 1,000.50", Decimal("1000.50")),
        ("GBP500", Decimal("500")),
        ("no amount here", None),
        ("just a number 12345", None),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_parse_amount_returns_first_match_only():
    assert parse_amount("£100 and also £200") == Decimal("100")


# --- find_gbp_amount_after_label --------------------------------------


def test_find_gbp_amount_after_label_matches_case_insensitively():
    text = "TOTAL FUND VALUE\n£12,345.67\n"
    assert find_gbp_amount_after_label(text, "total fund value") == Decimal("12345.67")


def test_find_gbp_amount_after_label_ignores_amounts_before_the_label():
    text = "£999.99\nTransfer value\n£11,000.00"
    assert find_gbp_amount_after_label(text, "Transfer value") == Decimal("11000.00")


def test_find_gbp_amount_after_label_returns_none_when_label_missing():
    assert find_gbp_amount_after_label("£100 somewhere", "Surrender value") is None


def test_find_gbp_amount_after_label_returns_none_when_no_amount_follows():
    assert find_gbp_amount_after_label("Transfer value\nno amount on this page", "Transfer value") is None


# --- lines_with_gbp_amounts -------------------------------------------


def test_lines_with_gbp_amounts_pairs_each_match_with_its_previous_line():
    text = "Total fund value\n£12,345.67\nSome other line\nTransfer value\n£11,000.00"
    pairs = lines_with_gbp_amounts(text)
    assert pairs == [
        ("Total fund value", "£12,345.67"),
        ("Transfer value", "£11,000.00"),
    ]


def test_lines_with_gbp_amounts_handles_a_match_on_the_first_line():
    pairs = lines_with_gbp_amounts("£50.00\nnext line")
    assert pairs == [("", "£50.00")]


def test_lines_with_gbp_amounts_returns_empty_list_when_nothing_matches():
    assert lines_with_gbp_amounts("nothing to see here") == []


# --- parse_account / config validation --------------------------------


def _valid_raw_account(**overrides) -> dict:
    raw = {
        "id": "lg_pension",
        "name": "L&G Workplace Pension",
        "provider": "Legal & General",
        "type": "pension",
        "login_url": "https://example.invalid/login",
        "logged_in_selector": "#summary",
        "login_steps": [
            {"action": "fill", "selector": "#user", "value_env": "LG_PENSION_USERNAME"},
            {"action": "click", "selector": "#submit"},
        ],
        "fields": [{"id": "fund_value", "label": "Fund value"}],
    }
    raw.update(overrides)
    return raw


def test_parse_account_builds_expected_account():
    account = parse_account(_valid_raw_account())
    assert account.id == "lg_pension"
    assert account.login_steps[0].value_env == "LG_PENSION_USERNAME"
    assert account.fields[0].label == "Fund value"


def test_parse_account_rejects_missing_required_key():
    raw = _valid_raw_account()
    del raw["login_url"]
    with pytest.raises(ConfigError, match="login_url"):
        parse_account(raw)


def test_parse_account_rejects_field_with_no_label_or_selector():
    raw = _valid_raw_account(fields=[{"id": "fund_value"}])
    with pytest.raises(ConfigError, match="fund_value"):
        parse_account(raw)


def test_parse_account_rejects_account_with_no_fields():
    raw = _valid_raw_account(fields=[])
    with pytest.raises(ConfigError, match="no fields"):
        parse_account(raw)


def test_parse_account_rejects_unknown_login_step_key():
    raw = _valid_raw_account(login_steps=[{"action": "fill", "not_a_real_key": "x"}])
    with pytest.raises(ConfigError, match="invalid login step"):
        parse_account(raw)


def test_to_ha_account_falls_back_to_field_id_when_no_label():
    raw = _valid_raw_account(fields=[{"id": "surrender_value", "selector": ".amount"}])
    account = parse_account(raw)
    ha_account = to_ha_account(account)
    assert ha_account.fields[0].label == "surrender_value"


# --- load_config / find_raw_account ------------------------------------


def test_load_config_reads_profile_dir_and_accounts(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            profile_dir: "./custom_profiles"
            accounts:
              - id: acc1
                name: Account One
            """
        )
    )
    profile_dir, accounts = load_config(str(config_path))
    assert profile_dir == "./custom_profiles"
    assert accounts == [{"id": "acc1", "name": "Account One"}]


def test_load_config_defaults_profile_dir_when_absent(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("accounts:\n  - id: acc1\n")
    profile_dir, _ = load_config(str(config_path))
    assert profile_dir == "./profiles"


def test_load_config_rejects_file_with_no_accounts(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("profile_dir: './profiles'\n")
    with pytest.raises(ConfigError, match="no accounts"):
        load_config(str(config_path))


def test_find_raw_account_returns_matching_entry():
    raw_accounts = [{"id": "a"}, {"id": "b"}]
    assert find_raw_account(raw_accounts, "b") == {"id": "b"}


def test_find_raw_account_raises_for_unknown_id():
    with pytest.raises(ConfigError, match="unknown_id"):
        find_raw_account([{"id": "a"}], "unknown_id")


# --- filter_logout_candidates -------------------------------------------


def test_filter_logout_candidates_matches_on_testid():
    elements = [
        {"testid": "logout-nav-link", "tag": "button", "text": "Sign out"},
        {"testid": "product__name", "tag": "h3", "text": "Workplace Pension"},
    ]
    assert filter_logout_candidates(elements) == [elements[0]]


def test_filter_logout_candidates_matches_on_text_when_testid_is_generic():
    elements = [{"testid": "nav-item-7", "tag": "a", "text": "Log out"}]
    assert filter_logout_candidates(elements) == elements


def test_filter_logout_candidates_matches_case_insensitively():
    elements = [{"testid": "LOGOUT-BUTTON", "tag": "button", "text": ""}]
    assert filter_logout_candidates(elements) == elements


def test_filter_logout_candidates_returns_empty_when_nothing_matches():
    elements = [{"testid": "product__name", "tag": "h3", "text": "Workplace Pension"}]
    assert filter_logout_candidates(elements) == []
