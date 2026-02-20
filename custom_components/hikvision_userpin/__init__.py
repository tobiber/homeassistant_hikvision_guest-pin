"""Hikvision User & PIN Control integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .client import HikvisionClient
from .const import (
    CONF_BASE_URL,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_TIMEOUT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import HikvisionCoordinator
from .panel import async_register_panel, async_unregister_panel
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hikvision User & PIN Control from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Build client from config entry data + options
    data = entry.data
    options = entry.options
    client = HikvisionClient(
        data[CONF_BASE_URL],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        verify=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        timeout=options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
    )

    # Create coordinator
    coordinator = HikvisionCoordinator(hass, client, dict(options))
    await coordinator.async_config_entry_first_refresh()

    # Store references
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once, on first entry)
    if len(hass.data[DOMAIN]) == 1:
        async_register_services(hass)
        async_register_panel(hass)

    # Listen for option updates
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id)
    if entry_data:
        coordinator: HikvisionCoordinator = entry_data["coordinator"]
        coordinator.update_options(dict(entry.options))

        # Update client timeout
        client: HikvisionClient = entry_data["client"]
        client.timeout = entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    # Unregister services and panel when last entry is removed
    if not hass.data[DOMAIN]:
        async_unregister_services(hass)
        async_unregister_panel(hass)
        hass.data.pop(DOMAIN)

    return unload_ok
