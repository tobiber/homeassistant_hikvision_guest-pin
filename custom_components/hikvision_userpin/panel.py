"""HTTP views and panel registration for Hikvision User & PIN Control."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any
from urllib.parse import quote

from aiohttp import web
import jinja2

from homeassistant.components.frontend import async_register_built_in_panel, async_remove_panel
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .client import (
    HikvisionClient,
    compute_end_date,
    create_qr_image,
    generate_card_id,
    parse_date,
    qr_base64,
)
from .const import CONF_PROTECTED_EMPLOYEE_NOS, DOMAIN
from .coordinator import HikvisionCoordinator
from .client import to_set

_LOGGER = logging.getLogger(__name__)

PANEL_URL = "/api/hikvision_userpin"

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    autoescape=True,
)


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


class HikvisionPanelView(HomeAssistantView):
    """Main panel view showing users, events, and the create form."""

    url = f"{PANEL_URL}/panel"
    name = "api:hikvision_userpin:panel"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry_id = request.query.get("entry_id")
        entry_info = _get_entry(hass, entry_id)
        if not entry_info:
            return web.Response(text="No device configured", status=404)

        active_entry_id, entry_data = entry_info
        coordinator: HikvisionCoordinator = entry_data["coordinator"]

        data = coordinator.data or {}
        device_users = data.get("users", [])
        device_events = data.get("events", [])
        today = datetime.today().date().isoformat()

        options = {}
        for eid, ed in _get_entries(hass).items():
            cfg_entry = hass.config_entries.async_get_entry(eid)
            options[eid] = cfg_entry.title if cfg_entry else eid

        protected = to_set(
            (hass.config_entries.async_get_entry(active_entry_id).options or {}).get(
                CONF_PROTECTED_EMPLOYEE_NOS, ""
            )
            if hass.config_entries.async_get_entry(active_entry_id)
            else ""
        )

        template = _JINJA_ENV.get_template("index.html")
        html = template.render(
            device_users=device_users,
            device_events=device_events,
            protected=protected,
            today=today,
            panel_url=PANEL_URL,
            entry_id=active_entry_id,
            entries=options,
            multi_device=len(options) > 1,
        )
        return web.Response(text=html, content_type="text/html")


class HikvisionAddUserView(HomeAssistantView):
    """Handle user creation from the panel form."""

    url = f"{PANEL_URL}/add"
    name = "api:hikvision_userpin:add"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        form = await request.post()

        entry_id = form.get("entry_id")
        entry_info = _get_entry(hass, entry_id)
        if not entry_info:
            return web.Response(text="No device configured", status=404)

        active_entry_id, entry_data = entry_info
        client: HikvisionClient = entry_data["client"]
        coordinator: HikvisionCoordinator = entry_data["coordinator"]

        name = (form.get("name") or "").strip()
        start_date = (form.get("start_date") or "").strip()
        duration = (form.get("duration") or "7d").strip()
        custom_end = (form.get("end_date") or "").strip()

        if not name or not start_date:
            raise web.HTTPFound(f"{PANEL_URL}/panel?entry_id={active_entry_id}")

        try:
            start_dt = parse_date(start_date)
        except ValueError:
            raise web.HTTPFound(f"{PANEL_URL}/panel?entry_id={active_entry_id}")

        end_dt = compute_end_date(start_dt, duration, custom_end or None)
        end_date = end_dt.strftime("%Y-%m-%d")

        card_id = generate_card_id()
        employee_no = card_id

        result = await hass.async_add_executor_job(
            client.create_user_with_card,
            employee_no, name, start_date, end_date, card_id,
        )
        if not result["user_created"]:
            _LOGGER.error(
                "Panel: failed to create user %s: %s",
                name, result.get("create_detail"),
            )
        elif not result["card_bound"]:
            _LOGGER.warning(
                "Panel: user %s created but card binding failed: %s",
                name, result.get("card_detail"),
            )

        await coordinator.async_request_refresh()
        raise web.HTTPFound(f"{PANEL_URL}/panel?entry_id={active_entry_id}")


class HikvisionDeleteUserView(HomeAssistantView):
    """Handle user deletion."""

    url = f"{PANEL_URL}/delete/{{employee_no}}"
    name = "api:hikvision_userpin:delete"
    requires_auth = False

    async def post(self, request: web.Request, employee_no: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        form = await request.post()
        entry_id = form.get("entry_id")

        entry_info = _get_entry(hass, entry_id)
        if not entry_info:
            return web.Response(text="No device configured", status=404)

        active_entry_id, entry_data = entry_info
        client: HikvisionClient = entry_data["client"]
        coordinator: HikvisionCoordinator = entry_data["coordinator"]

        # Check protected
        protected = to_set(
            (hass.config_entries.async_get_entry(active_entry_id).options or {}).get(
                CONF_PROTECTED_EMPLOYEE_NOS, ""
            )
            if hass.config_entries.async_get_entry(active_entry_id)
            else ""
        )
        if employee_no in protected:
            raise web.HTTPFound(f"{PANEL_URL}/panel?entry_id={active_entry_id}")

        success, detail = await hass.async_add_executor_job(
            client.delete_user, employee_no
        )
        if not success:
            _LOGGER.error(
                "Panel: failed to delete user %s: %s", employee_no, detail
            )
        await coordinator.async_request_refresh()
        raise web.HTTPFound(f"{PANEL_URL}/panel?entry_id={active_entry_id}")


class HikvisionQrDownloadView(HomeAssistantView):
    """Serve a QR code PNG image."""

    url = f"{PANEL_URL}/qr/{{value}}"
    name = "api:hikvision_userpin:qr"
    requires_auth = False

    async def get(self, request: web.Request, value: str) -> web.Response:
        buf = await request.app["hass"].async_add_executor_job(
            create_qr_image, value,
        )
        return web.Response(
            body=buf.getvalue(),
            content_type="image/png",
            headers={
                "Content-Disposition": f'attachment; filename="card_{value}.png"',
            },
        )


class HikvisionQrPageView(HomeAssistantView):
    """Render the QR code sharing page."""

    url = f"{PANEL_URL}/qr/view/{{value}}"
    name = "api:hikvision_userpin:qr_view"
    requires_auth = False

    async def get(self, request: web.Request, value: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        name = request.query.get("name", "")
        entry_id = request.query.get("entry_id", "")

        qr_b64 = await hass.async_add_executor_job(qr_base64, value)
        download_link = f"{PANEL_URL}/qr/{value}"

        subject = quote("Zugang AZB10")
        body = quote(f"Name: {name}\nCard ID: {value}\nQR: {download_link}")
        mailto_link = f"mailto:?subject={subject}&cc=tobias@berndes.org&body={body}"
        wa_text = quote(f"Zugang AZB10 - Name: {name} - Card ID: {value}\nQR: {download_link}")
        wa_link = f"https://wa.me/?text={wa_text}"

        template = _JINJA_ENV.get_template("qr.html")
        html = template.render(
            value=value,
            name=name,
            qr_data=qr_b64,
            mailto=mailto_link,
            wa=wa_link,
            download_link=download_link,
            panel_url=PANEL_URL,
            entry_id=entry_id,
        )
        return web.Response(text=html, content_type="text/html")


class HikvisionExtendPageView(HomeAssistantView):
    """Render the extend validity form."""

    url = f"{PANEL_URL}/extend/view/{{employee_no}}"
    name = "api:hikvision_userpin:extend_view"
    requires_auth = False

    async def get(self, request: web.Request, employee_no: str) -> web.Response:
        name = request.query.get("name", "")
        begin_date = request.query.get("begin", "")
        current_end = request.query.get("end", "")
        entry_id = request.query.get("entry_id", "")

        template = _JINJA_ENV.get_template("extend.html")
        html = template.render(
            employee_no=employee_no,
            name=name,
            begin_date=begin_date,
            current_end=current_end,
            panel_url=PANEL_URL,
            entry_id=entry_id,
        )
        return web.Response(text=html, content_type="text/html")


class HikvisionExtendUserView(HomeAssistantView):
    """Handle the extend validity form submission."""

    url = f"{PANEL_URL}/extend/{{employee_no}}"
    name = "api:hikvision_userpin:extend"
    requires_auth = False

    async def post(self, request: web.Request, employee_no: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        form = await request.post()

        entry_id = form.get("entry_id")
        entry_info = _get_entry(hass, entry_id)
        if not entry_info:
            return web.Response(text="No device configured", status=404)

        active_entry_id, entry_data = entry_info
        client: HikvisionClient = entry_data["client"]
        coordinator: HikvisionCoordinator = entry_data["coordinator"]

        duration = (form.get("duration") or "7d").strip()
        begin_date = (form.get("begin_date") or "").strip()
        current_end = (form.get("current_end") or "").strip()

        try:
            current_end_dt = parse_date(current_end)
        except ValueError:
            raise web.HTTPFound(f"{PANEL_URL}/panel?entry_id={active_entry_id}")

        new_end_dt = compute_end_date(current_end_dt, duration)
        new_end_str = new_end_dt.strftime("%Y-%m-%d")

        success, detail = await hass.async_add_executor_job(
            client.update_validity, employee_no, begin_date, new_end_str,
        )
        if not success:
            _LOGGER.error(
                "Panel: failed to extend user %s: %s", employee_no, detail
            )
        await coordinator.async_request_refresh()
        raise web.HTTPFound(f"{PANEL_URL}/panel?entry_id={active_entry_id}")


class HikvisionDataApiView(HomeAssistantView):
    """JSON API returning users, events, and config for the Lovelace card."""

    url = f"{PANEL_URL}/data"
    name = "api:hikvision_userpin:data"
    requires_auth = False

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
    requires_auth = False

    async def get(self, request: web.Request, value: str) -> web.Response:
        try:
            hass: HomeAssistant = request.app["hass"]
            qr_b64 = await hass.async_add_executor_job(qr_base64, value)
            return self.json({"qr_data": qr_b64})
        except Exception:
            _LOGGER.exception("QR base64 view failed for value=%s", value)
            return self.json({"error": "QR generation failed"}, status_code=500)


_VIEWS = [
    HikvisionPanelView,
    HikvisionAddUserView,
    HikvisionDeleteUserView,
    HikvisionQrDownloadView,
    HikvisionQrPageView,
    HikvisionExtendPageView,
    HikvisionExtendUserView,
    HikvisionDataApiView,
    HikvisionQrBase64View,
]


def async_register_views(hass: HomeAssistant) -> None:
    """Register all HTTP API views (called early in async_setup)."""
    for view_cls in _VIEWS:
        hass.http.register_view(view_cls())


def async_register_panel(hass: HomeAssistant) -> None:
    """Register the sidebar panel (called from async_setup_entry)."""
    async_register_built_in_panel(
        hass,
        component_name="iframe",
        sidebar_title="Hikvision UserPin",
        sidebar_icon="mdi:door-closed-lock",
        frontend_url_path="hikvision-userpin",
        config={"url": f"{PANEL_URL}/panel"},
        require_admin=False,
    )


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel."""
    async_remove_panel(hass, "hikvision-userpin")
