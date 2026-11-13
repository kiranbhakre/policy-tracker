"""DataUpdateCoordinator for the Policy Tracker integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ACCOUNTS_FILE,
    CONF_PROFILE_DIR,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_SCAN_INTERVAL_HOURS,
)
from .scraper import AccountResult, ConfigError, TrackerAccount, load_accounts, merge_results, scrape_all

_LOGGER = logging.getLogger(__name__)


class PolicyTrackerCoordinator(DataUpdateCoordinator[dict[str, AccountResult]]):
    """Polls every configured account's portal and holds the latest results."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.accounts: list[TrackerAccount] = load_accounts(entry.data[CONF_ACCOUNTS_FILE])
        self.profile_dir: str = entry.data[CONF_PROFILE_DIR]
        hours = entry.data.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS)
        super().__init__(
            hass,
            _LOGGER,
            name="policy_tracker",
            update_interval=timedelta(hours=hours),
        )

    async def _async_update_data(self) -> dict[str, AccountResult]:
        try:
            new_results = await self.hass.async_add_executor_job(scrape_all, self.accounts, self.profile_dir)
        except ConfigError as exc:
            raise UpdateFailed(str(exc)) from exc

        # self.data is None on the very first refresh - merge_results
        # treats "no previous result for this account" the same as a
        # fresh (non-"ok") result: nothing to fall back to yet.
        return merge_results(self.data or {}, new_results)
