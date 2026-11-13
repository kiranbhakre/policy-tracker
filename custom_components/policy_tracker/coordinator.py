"""DataUpdateCoordinator for the Policy Tracker integration.

One config entry = one account (see config_flow.py), so this
coordinator's data is a single AccountResult, not a dict of them.
scrape_all()/merge_results() in scraper.py are still dict-shaped
(shared, already-tested helpers) - this just always calls them with
a one-element list/dict and unwraps the single result.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_CREDENTIALS, CONF_PROFILE_DIR, CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
from .scraper import AccountResult, ConfigError, TrackerAccount, merge_results, parse_account, scrape_all

_LOGGER = logging.getLogger(__name__)


class PolicyTrackerCoordinator(DataUpdateCoordinator[AccountResult]):
    """Polls this entry's one account and holds its latest result."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.account: TrackerAccount = parse_account({**entry.data, "id": entry.entry_id})
        self.profile_dir: str = entry.data[CONF_PROFILE_DIR]
        self.credentials: dict[str, str] = entry.data.get(CONF_CREDENTIALS, {})
        hours = entry.data.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS)
        super().__init__(
            hass,
            _LOGGER,
            name=f"policy_tracker_{entry.entry_id}",
            update_interval=timedelta(hours=hours),
        )

    async def _async_update_data(self) -> AccountResult:
        try:
            new_results = await self.hass.async_add_executor_job(
                scrape_all, [self.account], self.profile_dir, {self.account.id: self.credentials}
            )
        except ConfigError as exc:
            raise UpdateFailed(str(exc)) from exc

        previous = {self.account.id: self.data} if self.data is not None else {}
        merged = merge_results(previous, new_results)
        return merged[self.account.id]
