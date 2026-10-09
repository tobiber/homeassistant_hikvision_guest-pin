"""Authenticated HTTP API views and sidebar panel registration."""

from __future__ import annotations

import logging
from datetime import datetime

from aiohttp import web

from homeassistant.components import panel_custom
from homeassistant.components.frontend import async_remove_panel
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .client import qr_base64, to_set
from .const import CONF_PROTECTED_EMPLOYEE_NOS, DOMAIN
from .coordinator import HikvisionCoordinator

_LOGGER = logging.getLogger(__name__)

PANEL_URL = "/api/hikvision_userpin"
PANEL_JS_URL = f"/{DOMAIN}/hikvision-userpin-panel.js"


def _get_entries(hass: HomeAssistant) -> dict[str, dict]:
    """Return all configured entry data dicts."""
    return hass.data.get(DOMAIN, {})


def _get_entry(hass: HomeAssistant, entry_id: str | None = None) -> tuple[str, dict] | None:
    """Return a specific or the first available entry."""
    entries = _get_entries(hass)
    if not entries:
        return None
    if entry_id and entry_id in entries:
        return entry_id, entries[entry_id]
    # Default to first entry
    first_id = next(iter(entries))
    return first_id, entries[first_id]


class HikvisionDataApiView(HomeAssistantView):
    """JSON API returning users, events, and config for the Lovelace card."""

    url = f"{PANEL_URL}/data"
    name = "api:hikvision_userpin:data"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry_id = request.query.get("entry_id")
        entry_info = _get_entry(hass, entry_id)
        if not entry_info:
            return self.json({"error": "No device configured"}, status_code=404)

        active_entry_id, entry_data = entry_info
        coordinator: HikvisionCoordinator = entry_data["coordinator"]

        if request.query.get("refresh") == "1":
            await coordinator.async_refresh()

        data = coordinator.data or {}
        device_users = data.get("users", [])
        device_events = data.get("events", [])
        today = datetime.today().date().isoformat()

        entries = {}
        for eid, ed in _get_entries(hass).items():
            cfg_entry = hass.config_entries.async_get_entry(eid)
            entries[eid] = cfg_entry.title if cfg_entry else eid

        protected = list(to_set(
            (hass.config_entries.async_get_entry(active_entry_id).options or {}).get(
                CONF_PROTECTED_EMPLOYEE_NOS, ""
            )
            if hass.config_entries.async_get_entry(active_entry_id)
            else ""
        ))

        resp = self.json({
            "entry_id": active_entry_id,
            "entries": entries,
            "users": device_users,
            "events": device_events,
            "protected": protected,
            "today": today,
        })
        resp.headers["Cache-Control"] = "no-store"
        return resp


class HikvisionQrBase64View(HomeAssistantView):
    """Return a QR code as base64-encoded PNG JSON."""

    url = f"{PANEL_URL}/qr/base64/{{value}}"
    name = "api:hikvision_userpin:qr_base64"
    requires_auth = True

    async def get(self, request: web.Request, value: str) -> web.Response:
        try:
            hass: HomeAssistant = request.app["hass"]
            qr_b64 = await hass.async_add_executor_job(qr_base64, value)
            return self.json({"qr_data": qr_b64})
        except Exception:
            _LOGGER.exception("QR base64 view failed for value=%s", value)
            return self.json({"error": "QR generation failed"}, status_code=500)


_VIEWS = [
    HikvisionDataApiView,
    HikvisionQrBase64View,
]


def async_register_views(hass: HomeAssistant) -> None:
    """Register all HTTP API views (called early in async_setup)."""
    for view_cls in _VIEWS:
        hass.http.register_view(view_cls())


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register the native sidebar panel (called from async_setup_entry)."""
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path="hikvision-userpin",
        webcomponent_name="hikvision-userpin-panel",
        sidebar_title="Hikvision UserPin",
        sidebar_icon="mdi:door-closed-lock",
        module_url=PANEL_JS_URL,
        embed_iframe=False,
        require_admin=False,
    )


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel."""
    async_remove_panel(hass, "hikvision-userpin")
