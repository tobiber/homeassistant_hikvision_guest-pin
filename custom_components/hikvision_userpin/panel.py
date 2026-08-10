"""Authenticated HTTP API views for the Hikvision User & PIN Control cards.

Only the endpoints consumed by the Lovelace cards live here, and they all
require authentication. The cards call them through ``hass.callApi()``, which
attaches the user's bearer token automatically, so requiring auth does not
break them. All user-management *mutations* go through the integration's
services (``hikvision_userpin.create_user`` etc.), which are already
authenticated by Home Assistant.

The previous unauthenticated iframe sidebar panel (and its /panel, /add,
/delete and /extend form endpoints) has been removed: an iframe cannot send an
auth token, so those endpoints could only exist without authentication, which
exposed user creation/deletion to anyone who could reach Home Assistant.
"""

from __future__ import annotations

import logging
from datetime import datetime

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .client import qr_base64, to_set
from .const import CONF_PROTECTED_EMPLOYEE_NOS, DOMAIN
from .coordinator import HikvisionCoordinator

_LOGGER = logging.getLogger(__name__)

API_BASE = "/api/hikvision_userpin"


def _get_entries(hass: HomeAssistant) -> dict[str, dict]:
    """Return all configured entry data dicts."""
    return hass.data.get(DOMAIN, {})


def _get_entry(
    hass: HomeAssistant, entry_id: str | None = None
) -> tuple[str, dict] | None:
    """Return a specific or the first available entry."""
    entries = _get_entries(hass)
    if not entries:
        return None
    if entry_id and entry_id in entries:
        return entry_id, entries[entry_id]
    first_id = next(iter(entries))
    return first_id, entries[first_id]


class HikvisionDataApiView(HomeAssistantView):
    """JSON API returning users, events, and config for the Lovelace card."""

    url = f"{API_BASE}/data"
    name = "api:hikvision_userpin:data"
    # requires_auth defaults to True; the card authenticates via hass.callApi.

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
        for eid in _get_entries(hass):
            cfg_entry = hass.config_entries.async_get_entry(eid)
            entries[eid] = cfg_entry.title if cfg_entry else eid

        cfg_entry = hass.config_entries.async_get_entry(active_entry_id)
        protected = list(
            to_set(
                (cfg_entry.options or {}).get(CONF_PROTECTED_EMPLOYEE_NOS, "")
                if cfg_entry
                else ""
            )
        )

        resp = self.json(
            {
                "entry_id": active_entry_id,
                "entries": entries,
                "users": device_users,
                "events": device_events,
                "protected": protected,
                "today": today,
            }
        )
        resp.headers["Cache-Control"] = "no-store"
        return resp


class HikvisionQrBase64View(HomeAssistantView):
    """Return a QR code as base64-encoded PNG JSON."""

    url = f"{API_BASE}/qr/base64/{{value}}"
    name = "api:hikvision_userpin:qr_base64"

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
    """Register the authenticated HTTP API views (called from async_setup)."""
    for view_cls in _VIEWS:
        hass.http.register_view(view_cls())
