"""DataUpdateCoordinator for Hikvision User & PIN Control."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Set

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import HikvisionClient, describe_event
from .const import (
    CONF_ALLOWED_EVENTS,
    CONF_PROTECTED_EMPLOYEE_NOS,
    CONF_SCAN_INTERVAL,
    DEFAULT_ALLOWED_EVENTS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .client import parse_event_codes, to_set

_LOGGER = logging.getLogger(__name__)


class HikvisionCoordinator(DataUpdateCoordinator):
    """Coordinator that polls users and events from a Hikvision device."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: HikvisionClient,
        entry_options: dict,
        scan_interval: int | None = None,
    ) -> None:
        self.client = client
        self._entry_options = entry_options
        interval = scan_interval or entry_options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )

    def _get_protected_nos(self) -> Set[str]:
        raw = self._entry_options.get(CONF_PROTECTED_EMPLOYEE_NOS, "")
        return to_set(raw)

    def _get_allowed_events(self) -> Set[tuple]:
        raw = self._entry_options.get(CONF_ALLOWED_EVENTS, "")
        return parse_event_codes(raw, DEFAULT_ALLOWED_EVENTS)

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch users and events from the device."""
        try:
            users = await self.hass.async_add_executor_job(
                self.client.search_users
            )
            events = await self.hass.async_add_executor_job(
                self._fetch_filtered_events
            )
        except Exception as err:
            raise UpdateFailed(f"Error communicating with device: {err}") from err
        return {"users": users, "events": events}

    def _fetch_filtered_events(self, days: int = 7) -> List[Dict[str, Any]]:
        """Fetch and filter device events (runs in executor)."""
        end = datetime.now()
        start = end - timedelta(days=days)
        events = self.client.search_events(start, end)

        if events:
            majors = sorted(
                {f"{ev.get('major')}/{ev.get('minor')}" for ev in events}
            )
            _LOGGER.debug(
                "AcsEvent raw: %s events; types: %s",
                len(events), ", ".join(majors),
            )
        else:
            _LOGGER.debug(
                "AcsEvent raw: no events in range %s to %s",
                start.isoformat(), end.isoformat(),
            )

        protected = self._get_protected_nos()
        allowed = self._get_allowed_events()
        filtered: List[Dict[str, Any]] = []

        for ev in events:
            emp = ev.get("employeeNoString") or ev.get("employeeNo") or ""
            if emp and emp in protected:
                continue
            major = ev.get("major")
            minor = ev.get("minor")
            if isinstance(major, str) and major.isdigit():
                major = int(major)
            if isinstance(minor, str) and minor.isdigit():
                minor = int(minor)
            if (major, minor) not in allowed:
                continue
            ev["code"] = f"{major}/{minor}"
            ev["description"] = describe_event(major, minor)
            filtered.append(ev)

        def sort_key(ev: Dict[str, Any]):
            t = ev.get("time") or ev.get("Time") or ""
            try:
                return datetime.fromisoformat(t)
            except Exception:
                return datetime.min

        return sorted(filtered, key=sort_key, reverse=True)

    def update_options(self, options: dict) -> None:
        """Update options and recalculate interval."""
        self._entry_options = options
        interval = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self.update_interval = timedelta(seconds=interval)
