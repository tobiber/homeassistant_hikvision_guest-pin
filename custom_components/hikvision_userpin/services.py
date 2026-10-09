"""Service handlers for Hikvision User & PIN Control."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .client import (
    HikvisionClient,
    compute_end_date,
    deactivation_window,
    generate_card_id,
    parse_date,
)
from .const import DOMAIN
from .coordinator import HikvisionCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_CREATE_USER = "create_user"
SERVICE_DELETE_USER = "delete_user"
SERVICE_EXTEND_USER = "extend_user"
SERVICE_DEACTIVATE_USER = "deactivate_user"

CREATE_USER_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required("name"): cv.string,
        vol.Required("start_date"): cv.string,
        vol.Optional("duration", default="7d"): cv.string,
        vol.Optional("end_date"): cv.string,
    }
)

DELETE_USER_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required("employee_no"): cv.string,
    }
)

EXTEND_USER_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required("employee_no"): cv.string,
        vol.Optional("duration", default="7d"): cv.string,
        vol.Required("begin_date"): cv.string,
        vol.Required("current_end"): cv.string,
    }
)


DEACTIVATE_USER_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required("employee_no"): cv.string,
        vol.Optional("begin_date"): cv.string,
    }
)


def _get_entry_data(hass: HomeAssistant, entry_id: str) -> dict:
    """Get client and coordinator for a config entry."""
    if DOMAIN not in hass.data or entry_id not in hass.data[DOMAIN]:
        raise ValueError(f"Config entry {entry_id} not found")
    return hass.data[DOMAIN][entry_id]


async def async_handle_create_user(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the create_user service call."""
    data = call.data
    entry_data = _get_entry_data(hass, data["config_entry_id"])
    client: HikvisionClient = entry_data["client"]
    coordinator: HikvisionCoordinator = entry_data["coordinator"]

    name = data["name"]
    start_date = data["start_date"]
    duration = data.get("duration", "7d")
    custom_end = data.get("end_date")

    start_dt = parse_date(start_date)
    end_dt = compute_end_date(start_dt, duration, custom_end)
    end_date = end_dt.strftime("%Y-%m-%d")

    card_id = generate_card_id()
    employee_no = card_id

    result = await hass.async_add_executor_job(
        client.create_user_with_card,
        employee_no,
        name,
        start_date,
        end_date,
        card_id,
    )

    if not result["user_created"]:
        _LOGGER.error(
            "Failed to create user %s on device: %s",
            name, result.get("create_detail"),
        )
        raise HomeAssistantError(
            f"Benutzer {name} konnte nicht angelegt werden "
            f"({result.get('create_detail')})"
        )
    if not result["card_bound"]:
        _LOGGER.warning(
            "User %s created but card binding failed: %s",
            name, result.get("card_detail"),
        )
        await coordinator.async_request_refresh()
        raise HomeAssistantError(
            f"Benutzer {name} angelegt, aber Karte konnte nicht gebunden "
            f"werden ({result.get('card_detail')})"
        )

    _LOGGER.info(
        "User %s created with card %s, valid %s to %s",
        name, card_id, start_date, end_date,
    )
    await coordinator.async_request_refresh()


async def async_handle_delete_user(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the delete_user service call."""
    data = call.data
    entry_data = _get_entry_data(hass, data["config_entry_id"])
    client: HikvisionClient = entry_data["client"]
    coordinator: HikvisionCoordinator = entry_data["coordinator"]

    employee_no = data["employee_no"]

    success, detail = await hass.async_add_executor_job(
        client.delete_user, employee_no
    )
    if not success:
        raise HomeAssistantError(
            f"Benutzer {employee_no} konnte nicht gelöscht werden ({detail})"
        )

    _LOGGER.info("Deleted user %s from device", employee_no)
    await coordinator.async_request_refresh()


async def async_handle_extend_user(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the extend_user service call."""
    data = call.data
    entry_data = _get_entry_data(hass, data["config_entry_id"])
    client: HikvisionClient = entry_data["client"]
    coordinator: HikvisionCoordinator = entry_data["coordinator"]

    employee_no = data["employee_no"]
    duration = data.get("duration", "7d")
    begin_date = data["begin_date"]
    current_end = data["current_end"]

    current_end_dt = parse_date(current_end)
    new_end_dt = compute_end_date(current_end_dt, duration)
    new_end_str = new_end_dt.strftime("%Y-%m-%d")

    success, detail = await hass.async_add_executor_job(
        client.update_validity, employee_no, begin_date, new_end_str,
    )
    if not success:
        raise HomeAssistantError(
            f"Benutzer {employee_no} konnte nicht verlängert werden ({detail})"
        )

    _LOGGER.info("Extended user %s validity to %s", employee_no, new_end_str)
    await coordinator.async_request_refresh()


async def async_handle_deactivate_user(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the deactivate_user service call."""
    data = call.data
    entry_data = _get_entry_data(hass, data["config_entry_id"])
    client: HikvisionClient = entry_data["client"]
    coordinator: HikvisionCoordinator = entry_data["coordinator"]

    employee_no = data["employee_no"]
    begin, end = deactivation_window(data.get("begin_date"))

    success, detail = await hass.async_add_executor_job(
        client.update_validity, employee_no, begin, end,
    )
    if not success:
        raise HomeAssistantError(
            f"Benutzer {employee_no} konnte nicht deaktiviert werden ({detail})"
        )

    _LOGGER.info(
        "Deactivated user %s (validity set to %s - %s)", employee_no, begin, end,
    )
    await coordinator.async_request_refresh()


def async_register_services(hass: HomeAssistant) -> None:
    """Register all integration services."""

    async def _handle_create(call: ServiceCall) -> None:
        await async_handle_create_user(hass, call)

    async def _handle_delete(call: ServiceCall) -> None:
        await async_handle_delete_user(hass, call)

    async def _handle_extend(call: ServiceCall) -> None:
        await async_handle_extend_user(hass, call)

    async def _handle_deactivate(call: ServiceCall) -> None:
        await async_handle_deactivate_user(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_CREATE_USER, _handle_create, schema=CREATE_USER_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_USER, _handle_delete, schema=DELETE_USER_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_EXTEND_USER, _handle_extend, schema=EXTEND_USER_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DEACTIVATE_USER, _handle_deactivate, schema=DEACTIVATE_USER_SCHEMA,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister all integration services."""
    hass.services.async_remove(DOMAIN, SERVICE_CREATE_USER)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_USER)
    hass.services.async_remove(DOMAIN, SERVICE_EXTEND_USER)
    hass.services.async_remove(DOMAIN, SERVICE_DEACTIVATE_USER)
