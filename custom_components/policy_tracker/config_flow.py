"""Config flow for the Policy Tracker integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ACCOUNTS_FILE,
    CONF_PROFILE_DIR,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_PROFILE_DIR,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
)
from .scraper import ConfigError, load_accounts

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCOUNTS_FILE): str,
        vol.Optional(CONF_PROFILE_DIR, default=DEFAULT_PROFILE_DIR): str,
        vol.Optional(CONF_SCAN_INTERVAL_HOURS, default=DEFAULT_SCAN_INTERVAL_HOURS): int,
    }
)


async def _validate_accounts_file(hass: HomeAssistant, accounts_file: str) -> None:
    """Load the accounts file in the executor, so this flow never blocks."""
    await hass.async_add_executor_job(load_accounts, accounts_file)


class PolicyTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Policy Tracker."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate_accounts_file(self.hass, user_input[CONF_ACCOUNTS_FILE])
            except ConfigError:
                errors["base"] = "invalid_accounts_file"
            except OSError:
                errors["base"] = "accounts_file_not_found"
            else:
                return self.async_create_entry(title="Policy Tracker", data=user_input)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)
