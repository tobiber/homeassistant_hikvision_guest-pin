"""Hikvision User & PIN Control integration for Home Assistant."""

from __future__ import annotations

import logging
import os
from typing import Any

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
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
from .panel import async_register_panel, async_register_views, async_unregister_panel
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

CARD_JS_URL = f"/{DOMAIN}/hikvision-userpin-card.js"
PANEL_JS_URL = f"/{DOMAIN}/hikvision-userpin-panel.js"


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register the Lovelace card JS resource (runs before config entries)."""
    www_dir = os.path.join(os.path.dirname(__file__), "www")
    card_js_path = os.path.join(www_dir, "hikvision-userpin-card.js")
    panel_js_path = os.path.join(www_dir, "hikvision-userpin-panel.js")

    if not os.path.isfile(card_js_path):
        _LOGGER.error(
            "Lovelace card JS not found at %s – "
            "make sure the www/ directory is deployed",
            card_js_path,
        )
        return True

    static_paths = [StaticPathConfig(CARD_JS_URL, card_js_path, False)]
    if os.path.isfile(panel_js_path):
        static_paths.append(StaticPathConfig(PANEL_JS_URL, panel_js_path, False))
    else:
        _LOGGER.error(
            "Sidebar panel JS not found at %s – "
            "make sure the www/ directory is deployed",
            panel_js_path,
        )

    await hass.http.async_register_static_paths(static_paths)
    add_extra_js_url(hass, CARD_JS_URL)
    _LOGGER.info(
        "Registered Hikvision UserPin card JS: %s -> %s",
        CARD_JS_URL,
        card_js_path,
    )

    # Register HTTP views early so they are always available
    # (even if device is temporarily unreachable)
    async_register_views(hass)

    # Also register as a Lovelace dashboard resource (belt-and-suspenders)
    await _register_lovelace_resource(hass)

    return True


async def _register_lovelace_resource(hass: HomeAssistant) -> None:
    """Add card JS to Lovelace resources if not already present."""
    try:
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )

        ll_data = hass.data.get("lovelace")
        if ll_data is None:
            return
        resources = getattr(ll_data, "resources", None) if not isinstance(ll_data, dict) else ll_data.get("resources")
        if not isinstance(resources, ResourceStorageCollection):
            return

        for item in resources.async_items():
            if item.get("url") == CARD_JS_URL:
                _LOGGER.debug("Lovelace resource already registered: %s", CARD_JS_URL)
                return

        await resources.async_create_item(
            {"url": CARD_JS_URL, "res_type": "module"}
        )
        _LOGGER.info("Added Lovelace resource: %s", CARD_JS_URL)
    except Exception:
        _LOGGER.debug(
            "Could not auto-register Lovelace resource. "
            "Add manually: Settings > Dashboards > Resources > "
            "URL: %s  Type: JavaScript Module",
            CARD_JS_URL,
        )


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

    # Create coordinator – first refresh may fail if device is unreachable;
    # we continue setup so views/services/panel stay available.
    coordinator = HikvisionCoordinator(hass, client, dict(options))
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.warning(
            "Initial device refresh failed (%s) – "
            "continuing setup; data will appear after next successful poll",
            err,
        )

    # Store references
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services and sidebar panel (only once, on first entry)
    if len(hass.data[DOMAIN]) == 1:
        async_register_services(hass)
        await async_register_panel(hass)

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
