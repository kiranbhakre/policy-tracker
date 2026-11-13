"""policy-tracker: scrape pension/policy values and publish them to Home Assistant.

None of the providers this talks to offer a public API, so each
account's current value is read from its customer web portal using
Playwright and the user's own login, driven by a config-driven set of
login steps. Results are published to Home Assistant over MQTT
discovery via ha_mqtt.py.

Usage:
    python3 tracker.py                        headless run over every account in config.yaml
    python3 tracker.py --config path.yaml     use a different config file
    python3 tracker.py --interactive ACCOUNT  open a visible browser to log in (handles an OTP) and save the session
    python3 tracker.py --discover ACCOUNT     log in and print every line with a GBP amount, to help pick field labels

Credentials are read only from environment variables (see .env.example)
and are never written to the config file or logged.

Automated logins may conflict with some providers' terms of use -
check each provider's terms before relying on this for an account.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Optional

import yaml
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from ha_mqtt import AccountConfig as HaAccountConfig
from ha_mqtt import AccountResult, FieldSpec, connect_client, publish_account

LOG = logging.getLogger("policy_tracker.tracker")

DEFAULT_CONFIG_PATH = "config.yaml"
DEFAULT_PROFILE_DIR = "./profiles"

# Matches a GBP amount such as "£12,345.67" or "GBP 500". Requiring a
# currency marker (rather than any number) avoids picking up unrelated
# figures like dates or account numbers on the same page.
GBP_AMOUNT_RE = re.compile(r"(?:£|GBP\s?)\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)")


class ConfigError(Exception):
    """Raised when an account's configuration is invalid."""


class FieldExtractionError(Exception):
    """Raised when a configured field's value could not be found on the page."""


# --- Amount parsing -------------------------------------------------------


def parse_amount(text: str) -> Optional[Decimal]:
    """Return the first GBP amount found in text, or None if there isn't one."""
    match = GBP_AMOUNT_RE.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def find_gbp_amount_after_label(full_text: str, label: str) -> Optional[Decimal]:
    """Find the first GBP amount occurring anywhere after `label` in full_text.

    Label matching is case-insensitive, since provider portals are
    inconsistent about capitalisation. Use a selector instead of a
    label when exact targeting matters.
    """
    idx = full_text.lower().find(label.lower())
    if idx == -1:
        return None
    return parse_amount(full_text[idx + len(label):])


def lines_with_gbp_amounts(full_text: str) -> list[tuple[str, str]]:
    """Pairs of (previous_line, line) for every line containing a GBP amount.

    Used by --discover so the user can see context around each amount
    and choose a label that will reliably precede it.
    """
    lines = full_text.splitlines()
    pairs = []
    for i, line in enumerate(lines):
        if GBP_AMOUNT_RE.search(line):
            prev_line = lines[i - 1].strip() if i > 0 else ""
            pairs.append((prev_line, line.strip()))
    return pairs


# --- Config models ---------------------------------------------------------


@dataclass(frozen=True)
class LoginStep:
    """One step of a login flow: fill a field, click something, or wait."""

    action: str  # "fill", "click", or "wait"
    selector: Optional[str] = None
    value: Optional[str] = None
    value_env: Optional[str] = None  # env var holding the value, for fill steps
    timeout_ms: Optional[int] = None  # for wait steps with a selector
    wait_ms: Optional[int] = None  # for wait steps with a fixed delay


@dataclass(frozen=True)
class TrackerField:
    """One monetary field to read, by selector or by its preceding label."""

    id: str
    label: Optional[str] = None
    selector: Optional[str] = None


@dataclass(frozen=True)
class TrackerAccount:
    """Full config-driven description of one account to scrape."""

    id: str
    name: str
    provider: str
    type: str  # "pension" or "policy"
    login_url: str
    logged_in_selector: str
    login_steps: tuple[LoginStep, ...] = ()
    values_url: Optional[str] = None
    otp_selector: Optional[str] = None
    fields: tuple[TrackerField, ...] = ()


def _require(raw: dict, key: str, account_id: str) -> object:
    if key not in raw:
        raise ConfigError(f"account {account_id!r} is missing required key {key!r}")
    return raw[key]


def parse_account(raw: dict) -> TrackerAccount:
    """Build a TrackerAccount from one entry of the accounts config list."""
    account_id = raw.get("id", "<unknown>")

    fields = []
    for raw_field in raw.get("fields", []):
        tf = TrackerField(
            id=raw_field["id"],
            label=raw_field.get("label"),
            selector=raw_field.get("selector"),
        )
        if not tf.label and not tf.selector:
            raise ConfigError(f"account {account_id!r} field {tf.id!r} needs a label or selector")
        fields.append(tf)
    if not fields:
        raise ConfigError(f"account {account_id!r} has no fields configured")

    try:
        steps = tuple(LoginStep(**step) for step in raw.get("login_steps", []))
    except TypeError as exc:
        raise ConfigError(f"account {account_id!r} has an invalid login step: {exc}") from exc

    return TrackerAccount(
        id=account_id,
        name=str(_require(raw, "name", account_id)),
        provider=str(_require(raw, "provider", account_id)),
        type=str(_require(raw, "type", account_id)),
        login_url=str(_require(raw, "login_url", account_id)),
        logged_in_selector=str(_require(raw, "logged_in_selector", account_id)),
        login_steps=steps,
        values_url=raw.get("values_url"),
        otp_selector=raw.get("otp_selector"),
        fields=tuple(fields),
    )


def load_config(path: str) -> tuple[str, list[dict]]:
    """Load the config file and return (profile_dir, raw account dicts).

    Accounts are returned raw (not yet validated) so that one account
    with a typo in its config does not prevent the others from being
    parsed and run - see run_all().
    """
    with open(path, encoding="utf-8") as config_file:
        raw = yaml.safe_load(config_file) or {}
    profile_dir = raw.get("profile_dir", DEFAULT_PROFILE_DIR)
    accounts = raw.get("accounts", [])
    if not accounts:
        raise ConfigError(f"{path} defines no accounts")
    return profile_dir, accounts


def find_raw_account(raw_accounts: list[dict], account_id: str) -> dict:
    for raw in raw_accounts:
        if raw.get("id") == account_id:
            return raw
    raise ConfigError(f"no account with id {account_id!r} in config")


def to_ha_account(account: TrackerAccount) -> HaAccountConfig:
    """Translate a TrackerAccount into the shape ha_mqtt.py publishes."""
    return HaAccountConfig(
        id=account.id,
        name=account.name,
        provider=account.provider,
        type=account.type,
        fields=tuple(FieldSpec(f.id, f.label or f.id) for f in account.fields),
    )


# --- Browser automation ------------------------------------------------


@contextmanager
def account_page(account: TrackerAccount, profile_dir: str, headless: bool) -> Iterator[Page]:
    """Open a page in a persistent Chromium profile dedicated to this account.

    Reusing a profile per account lets cookies survive between runs, so
    a login that only sometimes asks for a one-time code does not have
    to provide one every time.
    """
    account_profile = Path(profile_dir) / account.id
    account_profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(account_profile), headless=headless
        )
        try:
            page = context.new_page()
            yield page
        finally:
            context.close()


def require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ConfigError(f"environment variable {var_name!r} is not set")
    return value


def run_login_steps(page: Page, steps: tuple[LoginStep, ...]) -> None:
    for step in steps:
        if step.action == "fill":
            value = require_env(step.value_env) if step.value_env else (step.value or "")
            page.fill(step.selector, value)
        elif step.action == "click":
            page.click(step.selector)
        elif step.action == "wait":
            if step.selector:
                page.wait_for_selector(step.selector, timeout=step.timeout_ms or 15000)
            else:
                page.wait_for_timeout(step.wait_ms or 1000)
        else:
            raise ConfigError(f"unknown login step action: {step.action!r}")


def otp_requested(page: Page, otp_selector: Optional[str], timeout_ms: int = 3000) -> bool:
    """True if the OTP selector became visible after the login steps ran."""
    if not otp_selector:
        return False
    try:
        page.wait_for_selector(otp_selector, timeout=timeout_ms, state="visible")
        return True
    except PlaywrightTimeoutError:
        return False


def wait_logged_in(page: Page, logged_in_selector: str, timeout_ms: int = 20000) -> bool:
    try:
        page.wait_for_selector(logged_in_selector, timeout=timeout_ms, state="visible")
        return True
    except PlaywrightTimeoutError:
        return False


def extract_field(page: Page, tracker_field: TrackerField) -> Decimal:
    if tracker_field.selector:
        text = page.locator(tracker_field.selector).first.inner_text()
        amount = parse_amount(text)
    else:
        body_text = page.inner_text("body")
        amount = find_gbp_amount_after_label(body_text, tracker_field.label)
    if amount is None:
        where = tracker_field.selector or f"label {tracker_field.label!r}"
        raise FieldExtractionError(f"field {tracker_field.id!r}: no GBP amount found via {where}")
    return amount


def extract_all_fields(page: Page, account: TrackerAccount) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    errors: list[str] = []
    for tracker_field in account.fields:
        try:
            values[tracker_field.id] = extract_field(page, tracker_field)
        except FieldExtractionError as exc:
            errors.append(str(exc))
    if errors:
        raise FieldExtractionError("; ".join(errors))
    return values


# --- Run modes --------------------------------------------------------


def run_account_headless(account: TrackerAccount, profile_dir: str) -> AccountResult:
    """Run one account's full scrape in a headless browser.

    Never attempts to answer a one-time code prompt - if one appears,
    the account is reported as otp_required and left for --interactive.
    """
    with account_page(account, profile_dir, headless=True) as page:
        page.goto(account.login_url)
        run_login_steps(page, account.login_steps)

        if otp_requested(page, account.otp_selector):
            return AccountResult(status="otp_required")
        if not wait_logged_in(page, account.logged_in_selector):
            return AccountResult(status="error", error_message="login did not complete")

        if account.values_url:
            page.goto(account.values_url)
        values = extract_all_fields(page, account)
        return AccountResult(status="ok", values=values, last_updated=datetime.now(timezone.utc))


def publish_result(account: TrackerAccount, result: AccountResult) -> None:
    client = connect_client()
    client.loop_start()
    try:
        publish_account(client, to_ha_account(account), result)
    finally:
        client.loop_stop()
        client.disconnect()


def run_all(config_path: str) -> int:
    """Run every account in the config, publishing each result independently.

    One account failing - a bad config entry, a login error, a missing
    field - never stops the others. Returns a process exit code: 0 only
    if every account ended up with status "ok".
    """
    profile_dir, raw_accounts = load_config(config_path)
    any_failed = False

    client = connect_client()
    client.loop_start()
    try:
        for raw in raw_accounts:
            account_id = raw.get("id", "<unknown>")
            try:
                account = parse_account(raw)
            except ConfigError as exc:
                LOG.error("account=%s invalid config: %s", account_id, exc)
                any_failed = True
                continue

            try:
                result = run_account_headless(account, profile_dir)
            except Exception as exc:  # noqa: BLE001 - one bad account must not abort the run
                LOG.error("account=%s run failed: %s", account.id, exc)
                result = AccountResult(status="error", error_message=str(exc))

            if result.status != "ok":
                any_failed = True
                LOG.warning("account=%s status=%s", account.id, result.status)
            else:
                LOG.info("account=%s status=ok fields=%d", account.id, len(result.values))

            publish_account(client, to_ha_account(account), result)
    finally:
        client.loop_stop()
        client.disconnect()

    return 1 if any_failed else 0


def run_interactive(account: TrackerAccount, profile_dir: str) -> None:
    """Open a visible browser so the user can type a one-time code once.

    The session is saved in the account's persistent Chromium profile,
    so later headless runs can reuse it without asking again.
    """
    with account_page(account, profile_dir, headless=False) as page:
        page.goto(account.login_url)
        run_login_steps(page, account.login_steps)

        if otp_requested(page, account.otp_selector):
            print("A one-time code was requested. Enter it in the browser window,")
            print("then press Enter here once the portal has logged you in.")
            input()

        if not wait_logged_in(page, account.logged_in_selector, timeout_ms=60000):
            print("Could not confirm login (logged_in_selector not found).")
            print("The session may not have been saved correctly.")
            return

        print("Logged in. This session is now saved for future headless runs.")

        if account.values_url:
            page.goto(account.values_url)
        try:
            values = extract_all_fields(page, account)
        except FieldExtractionError as exc:
            print(f"Logged in, but some fields could not be read: {exc}")
            return

        result = AccountResult(status="ok", values=values, last_updated=datetime.now(timezone.utc))
        publish_result(account, result)
        print(f"Published {len(values)} field(s) to Home Assistant.")


def run_discover(account: TrackerAccount, profile_dir: str) -> None:
    """Log in and print every line containing a GBP amount, with context.

    Requires an already-established session (run --interactive first if
    this account needs a one-time code) since this runs headless.
    """
    with account_page(account, profile_dir, headless=True) as page:
        page.goto(account.login_url)
        run_login_steps(page, account.login_steps)

        if otp_requested(page, account.otp_selector):
            print("A one-time code was requested. Run --interactive for this account first.")
            return
        if not wait_logged_in(page, account.logged_in_selector, timeout_ms=30000):
            print("Could not confirm login.")
            return

        if account.values_url:
            page.goto(account.values_url)

        body_text = page.inner_text("body")
        pairs = lines_with_gbp_amounts(body_text)
        if not pairs:
            print("No GBP amounts found on this page.")
            return
        for prev_line, line in pairs:
            print(f"{prev_line!r} -> {line!r}")


# --- CLI ----------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="path to the accounts config file")
    parser.add_argument("--interactive", metavar="ACCOUNT_ID", help="log in visibly for one account (handles an OTP)")
    parser.add_argument("--discover", metavar="ACCOUNT_ID", help="print GBP amounts on the page, to help pick labels")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        if args.interactive:
            profile_dir, raw_accounts = load_config(args.config)
            account = parse_account(find_raw_account(raw_accounts, args.interactive))
            run_interactive(account, profile_dir)
            return 0

        if args.discover:
            profile_dir, raw_accounts = load_config(args.config)
            account = parse_account(find_raw_account(raw_accounts, args.discover))
            run_discover(account, profile_dir)
            return 0

        return run_all(args.config)
    except (ConfigError, RuntimeError) as exc:
        # Config and setup problems (bad YAML, a missing env var, no
        # MQTT_HOST) get a clean one-line message instead of a
        # traceback. Anything else is unexpected and should surface
        # with its full traceback for debugging.
        LOG.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
