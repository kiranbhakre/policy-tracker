"""Sensor platform for the Policy Tracker integration.

One config entry = one account = one device, with a monetary sensor
per configured field, a diagnostic status sensor (ok/otp_required/
error), and a diagnostic last-updated timestamp sensor.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, STATUS_ERROR, STATUS_OK, STATUS_OTP_REQUIRED
from .coordinator import PolicyTrackerCoordinator
from .scraper import TrackerAccount, TrackerField


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PolicyTrackerCoordinator = hass.data[DOMAIN][entry.entry_id]
    account = coordinator.account

    entities: list[SensorEntity] = [
        PolicyTrackerStatusSensor(coordinator, account),
        PolicyTrackerLastUpdatedSensor(coordinator, account),
    ]
    entities.extend(PolicyTrackerFieldSensor(coordinator, account, f) for f in account.fields)

    async_add_entities(entities)


class _PolicyTrackerEntity(CoordinatorEntity[PolicyTrackerCoordinator], SensorEntity):
    """Shared device info for every entity belonging to one account."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PolicyTrackerCoordinator, account: TrackerAccount) -> None:
        super().__init__(coordinator)
        self._account = account
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account.id)},
            name=account.name,
            manufacturer=account.provider,
            model=account.type,
        )

    @property
    def _result(self):
        return self.coordinator.data


class PolicyTrackerFieldSensor(_PolicyTrackerEntity):
    """One monetary field (e.g. fund value) for one account."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "GBP"

    def __init__(
        self, coordinator: PolicyTrackerCoordinator, account: TrackerAccount, tracker_field: TrackerField
    ) -> None:
        super().__init__(coordinator, account)
        self._field = tracker_field
        self._attr_unique_id = f"{account.id}_{tracker_field.id}"
        self._attr_name = tracker_field.label or tracker_field.id

    @property
    def native_value(self):
        result = self._result
        return result.values.get(self._field.id) if result else None

    @property
    def available(self) -> bool:
        # A failed run should keep showing the last good value rather
        # than going unavailable - only unavailable if we've never
        # had a value for this field at all.
        return super().available and bool(self._result) and self._field.id in self._result.values


class PolicyTrackerStatusSensor(_PolicyTrackerEntity):
    """ok / otp_required / error for one account's most recent run."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_OK, STATUS_OTP_REQUIRED, STATUS_ERROR]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-alert"

    def __init__(self, coordinator: PolicyTrackerCoordinator, account: TrackerAccount) -> None:
        super().__init__(coordinator, account)
        self._attr_unique_id = f"{account.id}_status"
        self._attr_name = "Status"

    @property
    def native_value(self):
        result = self._result
        return result.status if result else None


class PolicyTrackerLastUpdatedSensor(_PolicyTrackerEntity):
    """When this account's values were last successfully refreshed."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PolicyTrackerCoordinator, account: TrackerAccount) -> None:
        super().__init__(coordinator, account)
        self._attr_unique_id = f"{account.id}_last_updated"
        self._attr_name = "Last updated"

    @property
    def native_value(self):
        result = self._result
        return result.last_updated if result else None
