"""Config flow for the Policy Tracker integration.

Two steps: "user" collects the accounts file/profile dir/scan
interval and validates the file loads. "credentials" then appears
only if the loaded accounts actually reference any value_credential
in their login_steps - it's built dynamically, one username/password
(or whatever the YAML names) field per credential each account needs.
Accounts whose login_steps use value_env/value instead skip it
entirely, so this never forces env-var users into the UI.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import (
    CONF_ACCOUNTS_FILE,
    CONF_CREDENTIALS,
    CONF_PROFILE_DIR,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_PROFILE_DIR,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
)
from .scraper import ConfigError, TrackerAccount, credentials_needed, load_accounts

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCOUNTS_FILE): str,
        vol.Optional(CONF_PROFILE_DIR, default=DEFAULT_PROFILE_DIR): str,
        vol.Optional(CONF_SCAN_INTERVAL_HOURS, default=DEFAULT_SCAN_INTERVAL_HOURS): int,
    }
)

# Separates an account id from a credential name in a credentials-step
# field key, e.g. "lg_pension__password". Only used to build the key -
# never parsed back out, so it doesn't need to be unambiguous.
_FIELD_SEP = "__"


def _credential_field_key(account_id: str, name: str) -> str:
    return f"{account_id}{_FIELD_SEP}{name}"


def _credentials_schema(needed: dict[str, list[str]]) -> vol.Schema:
    fields: dict[Any, Any] = {}
    for account_id, names in needed.items():
        for name in names:
            is_secret = any(word in name.lower() for word in ("password", "secret", "pin"))
            selector_type = TextSelectorType.PASSWORD if is_secret else TextSelectorType.TEXT
            key = vol.Required(_credential_field_key(account_id, name))
            fields[key] = TextSelector(TextSelectorConfig(type=selector_type))
    return vol.Schema(fields)


async def _validate_accounts_file(hass: HomeAssistant, accounts_file: str) -> list[TrackerAccount]:
    """Load the accounts file in the executor, so this flow never blocks."""
    return await hass.async_add_executor_job(load_accounts, accounts_file)


class PolicyTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Policy Tracker."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_data: dict[str, Any] = {}
        self._accounts: list[TrackerAccount] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._accounts = await _validate_accounts_file(self.hass, user_input[CONF_ACCOUNTS_FILE])
            except ConfigError:
                errors["base"] = "invalid_accounts_file"
            except OSError:
                errors["base"] = "accounts_file_not_found"
            else:
                self._user_data = user_input
                if not credentials_needed(self._accounts):
                    return self.async_create_entry(title="Policy Tracker", data=self._user_data)
                return await self.async_step_credentials()

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        needed = credentials_needed(self._accounts)
        account_names = {account.id: account.name for account in self._accounts}

        if user_input is not None:
            credentials: dict[str, dict[str, str]] = {
                account_id: {name: user_input[_credential_field_key(account_id, name)] for name in names}
                for account_id, names in needed.items()
            }
            data = {**self._user_data, CONF_CREDENTIALS: credentials}
            return self.async_create_entry(title="Policy Tracker", data=data)

        return self.async_show_form(
            step_id="credentials",
            data_schema=_credentials_schema(needed),
            description_placeholders={
                "accounts": ", ".join(account_names[account_id] for account_id in needed)
            },
        )
