"""Scraping engine for the Policy Tracker Home Assistant integration.

Vendored rather than imported from the project's standalone tracker.py
because a Home Assistant custom integration must be self-contained
inside its own custom_components/<domain> folder - it cannot import
modules from outside that tree. Keep this in sync with tracker.py's
equivalent functions if the scraping behaviour changes in one place.

Every function here is synchronous (Playwright's sync API). Call
scrape_account/scrape_all only from a Home Assistant executor job
(hass.async_add_executor_job), never directly on the event loop.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Optional

import yaml
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

_LOGGER = logging.getLogger(__name__)

# Matches a GBP amount such as "£12,345.67" or "GBP 500". Requiring a
# currency marker avoids picking up unrelated figures on the page.
GBP_AMOUNT_RE = re.compile(r"(?:£|GBP\s?)\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)")

VALID_STATUSES = ("ok", "otp_required", "error")


class ConfigError(Exception):
    """Raised when an account's configuration is invalid."""


class FieldExtractionError(Exception):
    """Raised when a configured field's value could not be found on the page."""


# --- Amount parsing --------------------------------------------------


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
    """Find the first GBP amount occurring anywhere after `label` in full_text."""
    idx = full_text.lower().find(label.lower())
    if idx == -1:
        return None
    return parse_amount(full_text[idx + len(label):])


# --- Config models -----------------------------------------------------


@dataclass(frozen=True)
class LoginStep:
    """One step of a login flow: fill a field, click something, or wait."""

    action: str  # "fill", "click", or "wait"
    selector: Optional[str] = None
    value: Optional[str] = None
    value_env: Optional[str] = None
    timeout_ms: Optional[int] = None
    wait_ms: Optional[int] = None


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
    type: str
    login_url: str
    logged_in_selector: str
    login_steps: tuple[LoginStep, ...] = ()
    values_url: Optional[str] = None
    otp_selector: Optional[str] = None
    fields: tuple[TrackerField, ...] = ()


@dataclass(frozen=True)
class AccountResult:
    """Outcome of one scrape run for an account."""

    status: str
    values: dict[str, Decimal] = field(default_factory=dict)
    last_updated: Optional[datetime] = None
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {self.status!r}")


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


def load_accounts(accounts_file: str) -> list[TrackerAccount]:
    """Load and validate every account from the accounts YAML file.

    Uses the same file format as the standalone tracker.py's
    config.yaml. Raises ConfigError on the first invalid account -
    this runs once during config flow setup, where failing fast with
    a clear message is more useful than silently skipping an account.
    """
    with open(accounts_file, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    raw_accounts = raw.get("accounts", [])
    if not raw_accounts:
        raise ConfigError(f"{accounts_file} defines no accounts")
    return [parse_account(entry) for entry in raw_accounts]


# --- Browser automation ------------------------------------------------


@contextmanager
def _account_page(account: TrackerAccount, profile_dir: str, headless: bool) -> Iterator[Page]:
    """Open a page in a persistent Chromium profile dedicated to this account."""
    account_profile = Path(profile_dir) / account.id
    account_profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(account_profile), headless=headless
        )
        try:
            yield context.new_page()
        finally:
            context.close()


def _require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise ConfigError(f"environment variable {var_name!r} is not set")
    return value


def _run_login_steps(page: Page, steps: tuple[LoginStep, ...]) -> None:
    for step in steps:
        if step.action == "fill":
            value = _require_env(step.value_env) if step.value_env else (step.value or "")
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


def _otp_requested(page: Page, otp_selector: Optional[str], timeout_ms: int = 3000) -> bool:
    if not otp_selector:
        return False
    try:
        page.wait_for_selector(otp_selector, timeout=timeout_ms, state="visible")
        return True
    except PlaywrightTimeoutError:
        return False


def _wait_logged_in(page: Page, logged_in_selector: str, timeout_ms: int = 20000) -> bool:
    try:
        page.wait_for_selector(logged_in_selector, timeout=timeout_ms, state="visible")
        return True
    except PlaywrightTimeoutError:
        return False


def _extract_field(page: Page, tracker_field: TrackerField) -> Decimal:
    if tracker_field.selector:
        text = page.locator(tracker_field.selector).first.inner_text()
        amount = parse_amount(text)
    else:
        amount = find_gbp_amount_after_label(page.inner_text("body"), tracker_field.label)
    if amount is None:
        where = tracker_field.selector or f"label {tracker_field.label!r}"
        raise FieldExtractionError(f"field {tracker_field.id!r}: no GBP amount found via {where}")
    return amount


def scrape_account(account: TrackerAccount, profile_dir: str) -> AccountResult:
    """Run one account's full scrape in a headless browser.

    Never attempts to answer a one-time code prompt - if one appears,
    the result is otp_required. Recovering from that still requires
    running the standalone tracker.py's --interactive mode once,
    pointed at this same profile_dir, since Home Assistant has no way
    to show the user a visible browser to type a code into.
    """
    try:
        with _account_page(account, profile_dir, headless=True) as page:
            page.goto(account.login_url)
            _run_login_steps(page, account.login_steps)

            if _otp_requested(page, account.otp_selector):
                return AccountResult(status="otp_required")
            if not _wait_logged_in(page, account.logged_in_selector):
                return AccountResult(status="error", error_message="login did not complete")

            if account.values_url:
                page.goto(account.values_url)

            values: dict[str, Decimal] = {}
            errors: list[str] = []
            for tracker_field in account.fields:
                try:
                    values[tracker_field.id] = _extract_field(page, tracker_field)
                except FieldExtractionError as exc:
                    errors.append(str(exc))
            if errors:
                return AccountResult(status="error", error_message="; ".join(errors))
            return AccountResult(status="ok", values=values, last_updated=datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 - one bad account must not abort the coordinator update
        _LOGGER.error("account=%s scrape failed: %s", account.id, exc)
        return AccountResult(status="error", error_message=str(exc))


def scrape_all(accounts: list[TrackerAccount], profile_dir: str) -> dict[str, AccountResult]:
    """Scrape every account independently; one failing never skips the rest."""
    return {account.id: scrape_account(account, profile_dir) for account in accounts}


def merge_results(
    previous: dict[str, AccountResult], new: dict[str, AccountResult]
) -> dict[str, AccountResult]:
    """Combine a fresh scrape with the previous one, account by account.

    A successful account's fresh values replace the old ones. A failed
    account (otp_required/error) keeps its previous values and
    last_updated - only its status (and error message) change - so a
    bad run never blanks out the last good reading.
    """
    merged: dict[str, AccountResult] = {}
    for account_id, new_result in new.items():
        if new_result.status == "ok" or account_id not in previous:
            merged[account_id] = new_result
            continue
        old_result = previous[account_id]
        merged[account_id] = AccountResult(
            status=new_result.status,
            values=old_result.values,
            last_updated=old_result.last_updated,
            error_message=new_result.error_message,
        )
    return merged
