"""Config flow for the Policy Tracker integration.

No file involved - one config entry is built entirely through this
wizard and represents exactly one account. Add the integration again
for each additional pension/policy.

Steps: "user" (account basics + schedule) -> "login_step" (repeated
once per step in the login flow) -> "field" (repeated once per value
to read) -> "credentials" (only if any login step needs one, built
from exactly what's needed) -> entry created.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import (
    ACCOUNT_TYPES,
    ACTIONS,
    CONF_CREDENTIALS,
    CONF_PROFILE_DIR,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_PROFILE_DIR,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    FIELD_EXTRACTION_METHODS,
    FILL_VALUE_SOURCES,
)
from .scraper import ConfigError, credentials_needed, parse_account

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Required("provider"): str,
        vol.Optional("type", default="pension"): vol.In(ACCOUNT_TYPES),
        vol.Required("login_url"): str,
        vol.Optional("values_url", default=""): str,
        vol.Required("logged_in_selector"): str,
        vol.Optional("otp_selector", default=""): str,
        vol.Optional(CONF_PROFILE_DIR, default=DEFAULT_PROFILE_DIR): str,
        vol.Optional(CONF_SCAN_INTERVAL_HOURS, default=DEFAULT_SCAN_INTERVAL_HOURS): int,
    }
)

STEP_LOGIN_STEP_SCHEMA = vol.Schema(
    {
        vol.Required("action"): vol.In(ACTIONS),
        vol.Optional("selector", default=""): str,
        vol.Optional("value_source", default=""): vol.In(("", *FILL_VALUE_SOURCES)),
        vol.Optional("credential_name", default=""): str,
        vol.Optional("literal_value", default=""): str,
        vol.Optional("env_var_name", default=""): str,
        vol.Optional("wait_ms", default=1000): int,
        vol.Optional("add_another", default=True): bool,
    }
)

STEP_FIELD_SCHEMA = vol.Schema(
    {
        vol.Required("field_id"): str,
        vol.Required("extraction_method"): vol.In(FIELD_EXTRACTION_METHODS),
        vol.Optional("label", default=""): str,
        vol.Optional("selector", default=""): str,
        vol.Optional("add_another", default=True): bool,
    }
)


def _login_step_from_input(user_input: dict[str, Any]) -> dict[str, Any] | None:
    """Build one login_steps dict from the form, or None if invalid (sets no error itself)."""
    action = user_input["action"]
    selector = user_input["selector"].strip()

    if action in ("fill", "click") and not selector:
        return None

    if action == "wait":
        if selector:
            return {"action": "wait", "selector": selector}
        return {"action": "wait", "wait_ms": user_input["wait_ms"]}

    if action == "click":
        return {"action": "click", "selector": selector}

    # action == "fill"
    source = user_input["value_source"]
    if source == "credential":
        name = user_input["credential_name"].strip()
        return {"action": "fill", "selector": selector, "value_credential": name} if name else None
    if source == "env":
        name = user_input["env_var_name"].strip()
        return {"action": "fill", "selector": selector, "value_env": name} if name else None
    if source == "literal":
        value = user_input["literal_value"]
        return {"action": "fill", "selector": selector, "value": value} if value else None
    return None


def _field_from_input(user_input: dict[str, Any]) -> dict[str, Any] | None:
    """Build one fields dict from the form, or None if invalid."""
    method = user_input["extraction_method"]
    if method == "label":
        label = user_input["label"].strip()
        return {"id": user_input["field_id"], "label": label} if label else None
    selector = user_input["selector"].strip()
    return {"id": user_input["field_id"], "selector": selector} if selector else None


def _credentials_schema(names: list[str]) -> vol.Schema:
    fields: dict[Any, Any] = {}
    for name in names:
        is_secret = any(word in name.lower() for word in ("password", "secret", "pin"))
        selector_type = TextSelectorType.PASSWORD if is_secret else TextSelectorType.TEXT
        fields[vol.Required(name)] = TextSelector(TextSelectorConfig(type=selector_type))
    return vol.Schema(fields)


class PolicyTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Policy Tracker - one account per entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._credential_names: list[str] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data = {
                **user_input,
                "values_url": user_input["values_url"] or None,
                "otp_selector": user_input["otp_selector"] or None,
                "login_steps": [],
                "fields": [],
            }
            return await self.async_step_login_step()

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

    async def async_step_login_step(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            step = _login_step_from_input(user_input)
            if step is None:
                errors["base"] = "incomplete_login_step"
            else:
                self._data["login_steps"].append(step)
                if user_input["add_another"]:
                    return await self.async_step_login_step()
                return await self.async_step_field()

        return self.async_show_form(step_id="login_step", data_schema=STEP_LOGIN_STEP_SCHEMA, errors=errors)

    async def async_step_field(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            tracker_field = _field_from_input(user_input)
            if tracker_field is None:
                errors["base"] = "incomplete_field"
            else:
                self._data["fields"].append(tracker_field)
                if user_input["add_another"]:
                    return await self.async_step_field()
                return await self._finish_account()

        return self.async_show_form(step_id="field", data_schema=STEP_FIELD_SCHEMA, errors=errors)

    async def _finish_account(self) -> FlowResult:
        try:
            account = parse_account({**self._data, "id": "pending"})
        except ConfigError as exc:
            # Shouldn't happen - every login step/field the earlier
            # steps accept is already validated on the way in - but
            # never crash the flow over it.
            _LOGGER.error("unexpected invalid account after guided setup: %s", exc)
            return self.async_abort(reason="unknown")

        needed = credentials_needed([account])
        if not needed:
            return self.async_create_entry(title=self._data["name"], data=self._data)

        self._credential_names = needed[account.id]
        return await self.async_step_credentials()

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            data = {**self._data, CONF_CREDENTIALS: dict(user_input)}
            return self.async_create_entry(title=self._data["name"], data=data)

        return self.async_show_form(
            step_id="credentials",
            data_schema=_credentials_schema(self._credential_names),
        )
