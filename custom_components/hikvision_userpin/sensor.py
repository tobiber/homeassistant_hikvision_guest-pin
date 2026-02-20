"""Sensor platform for Hikvision User & PIN Control."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BASE_URL, DOMAIN
from .coordinator import HikvisionCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hikvision sensors from a config entry."""
    coordinator: HikvisionCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    async_add_entities(
        [
            HikvisionUserCountSensor(coordinator, entry),
            HikvisionLastEventSensor(coordinator, entry),
        ]
    )


class HikvisionBaseSensor(CoordinatorEntity[HikvisionCoordinator], SensorEntity):
    """Base class for Hikvision sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HikvisionCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._base_url = entry.data[CONF_BASE_URL]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"Hikvision {self._base_url}",
            manufacturer="Hikvision",
            model="Access Controller",
            configuration_url=self._base_url,
        )


class HikvisionUserCountSensor(HikvisionBaseSensor):
    """Sensor showing the number of users on the device."""

    _attr_icon = "mdi:account-group"
    _attr_native_unit_of_measurement = "users"

    def __init__(
        self,
        coordinator: HikvisionCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_user_count"
        self._attr_translation_key = "user_count"
        self._attr_name = "User Count"

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        if self.coordinator.data:
            return len(self.coordinator.data.get("users", []))
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        users = self.coordinator.data.get("users", [])
        return {
            "usernames": [u.get("name", "") for u in users],
            "employee_numbers": [u.get("employeeNo", "") for u in users],
        }


class HikvisionLastEventSensor(HikvisionBaseSensor):
    """Sensor showing the last access event."""

    _attr_icon = "mdi:door-open"

    def __init__(
        self,
        coordinator: HikvisionCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_event"
        self._attr_translation_key = "last_event"
        self._attr_name = "Last Event"

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        events = self.coordinator.data.get("events", [])
        if not events:
            return None
        return events[0].get("description", "Unknown")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        events = self.coordinator.data.get("events", [])
        if not events:
            return {}
        last = events[0]
        return {
            "time": last.get("time") or last.get("Time", ""),
            "employee": (
                last.get("employeeNoString")
                or last.get("employeeNo", "")
            ),
            "code": last.get("code", ""),
        }
