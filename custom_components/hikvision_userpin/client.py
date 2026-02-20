"""Hikvision ISAPI client for access control operations."""

from __future__ import annotations

import base64
import logging
import secrets
import string
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional, Set

import qrcode
import requests
from requests.auth import HTTPDigestAuth

from .const import DEFAULT_ALLOWED_EVENTS, EVENT_LABELS

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def parse_date(date_str: str) -> datetime:
    """Parse a date string in YYYY-MM-DD or DD.MM.YYYY format."""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unbekanntes Datumsformat: {date_str}")


def iso_date(date_str: str, end_of_day: bool = False) -> str:
    """Convert a date string to ISO format for Hikvision API."""
    base = parse_date(date_str)
    if end_of_day:
        base = base.replace(hour=23, minute=59, second=59)
    else:
        base = base.replace(hour=0, minute=0, second=0)
    return base.strftime("%Y-%m-%dT%H:%M:%S")


def add_months(base: datetime, months: int) -> datetime:
    """Add months to a date, clamping the day to the last day of the target month."""
    month = base.month - 1 + months
    year = base.year + month // 12
    month = month % 12 + 1
    days_in_month = [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
    ][month - 1]
    day = min(base.day, days_in_month)
    return datetime(year, month, day)


def compute_end_date(
    start: datetime, dur: str, custom_end: Optional[str] = None
) -> datetime:
    """Compute the end date from a start date and duration code."""
    if dur == "custom" and custom_end:
        try:
            return parse_date(custom_end)
        except ValueError:
            pass
    # End date is inclusive (endTime gets 23:59:59), so "1d" = same day as start.
    mapping = {
        "1d": timedelta(days=0),
        "7d": timedelta(days=6),
        "14d": timedelta(days=13),
        "4w": timedelta(days=27),
    }
    if dur in mapping:
        return start + mapping[dur]
    if dur == "3m":
        return add_months(start, 3) - timedelta(days=1)
    if dur == "12m":
        return add_months(start, 12) - timedelta(days=1)
    if dur == "forever":
        return datetime(2099, 12, 31)
    return start + timedelta(days=6)


def generate_card_id(length: int = 12) -> str:
    """Generate a random alphanumeric card ID."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_qr_image(data: str) -> BytesIO:
    """Create a QR code PNG image in memory."""
    img = qrcode.make(data)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def qr_base64(data: str) -> str:
    """Return a QR code as a base64-encoded PNG string."""
    buf = create_qr_image(data)
    return base64.b64encode(buf.getvalue()).decode()


def describe_event(major: Any, minor: Any) -> str:
    """Return a human-readable label for an event code pair."""
    try:
        m, n = int(major), int(minor)
    except (TypeError, ValueError):
        return f"Event {major}/{minor}"
    return EVENT_LABELS.get((m, n), f"Event {m}/{n}")


def to_set(value: Optional[str]) -> Set[str]:
    """Split a comma-separated string into a set of stripped tokens."""
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def parse_event_codes(
    value: Optional[str], default: Set[tuple] | None = None
) -> Set[tuple]:
    """Parse strings like '5/75,5/38' into {(5,75),(5,38)}."""
    if default is None:
        default = DEFAULT_ALLOWED_EVENTS
    if not value:
        return set(default)
    codes: Set[tuple] = set()
    for item in to_set(value):
        cleaned = item.replace("-", "/")
        parts = [p.strip() for p in cleaned.split("/") if p.strip()]
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            continue
        codes.add((int(parts[0]), int(parts[1])))
    return codes or set(default)


# ---------------------------------------------------------------------------
# Hikvision ISAPI Client
# ---------------------------------------------------------------------------

class HikvisionClient:
    """Client for Hikvision access control ISAPI endpoints."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        verify: bool = False,
        timeout: float = 8.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.verify = verify
        self.timeout = timeout
        self._session = requests.Session()
        self._session.auth = HTTPDigestAuth(username, password)
        self._session.verify = verify
        self._session.headers.update({"Content-Type": "application/json"})

    # -- Connection test ----------------------------------------------------

    def test_connection(self) -> str:
        """Test the connection and credentials. Returns 'ok', 'auth_failed', or 'cannot_connect'."""
        url = f"{self.base_url}/ISAPI/AccessControl/UserInfo/Search?format=json"
        payload = {
            "UserInfoSearchCond": {
                "searchID": "1",
                "maxResults": 1,
                "searchResultPosition": 0,
            }
        }
        try:
            resp = self._session.post(
                url, json=payload, timeout=self.timeout,
            )
            if 200 <= resp.status_code < 300:
                return "ok"
            if resp.status_code == 401:
                return "auth_failed"
            return "cannot_connect"
        except requests.RequestException:
            return "cannot_connect"

    # -- Low-level helpers --------------------------------------------------

    def _post_raw(self, path: str, payload: Dict) -> Optional[requests.Response]:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.post(
                url, json=payload, timeout=self.timeout,
            )
            if 200 <= resp.status_code < 300:
                return resp
            _LOGGER.error(
                "Hikvision POST %s failed (%s): %s",
                url, resp.status_code, resp.text,
            )
            return None
        except requests.RequestException as exc:
            _LOGGER.exception("Hikvision POST %s errored: %s", url, exc)
            return None

    def _post_ok(self, path: str, payload: Dict) -> bool:
        return self._post_raw(path, payload) is not None

    def _request(self, method_order: tuple, url: str, payload: Dict) -> bool:
        """Try PUT then POST (or vice versa) — DRY helper for delete/modify."""
        for method in method_order:
            try:
                resp = self._session.request(
                    method, url, json=payload, timeout=self.timeout,
                )
                if 200 <= resp.status_code < 300:
                    return True
                _LOGGER.error(
                    "Hikvision %s %s failed (%s): %s",
                    method.upper(), url, resp.status_code, resp.text,
                )
                if resp.status_code not in (400, 405):
                    break
            except requests.RequestException as exc:
                _LOGGER.exception(
                    "Hikvision %s %s errored: %s", method.upper(), url, exc,
                )
                break
        return False

    # -- ISAPI operations ---------------------------------------------------

    def create_user(
        self, employee_no: str, name: str, start_date: str, end_date: str
    ) -> bool:
        payload = {
            "UserInfo": {
                "employeeNo": employee_no,
                "name": name,
                "userType": "normal",
                "authenticationType": "custom",
                "authenticationMode": ["card"],
                "userVerifyMode": "card",
                "Valid": {
                    "enable": True,
                    "beginTime": iso_date(start_date),
                    "endTime": iso_date(end_date, end_of_day=True),
                },
                "doorRight": "1",
                "rightPlan": [{"doorNo": 1, "planTemplateNo": "1"}],
            }
        }
        return self._post_ok(
            "/ISAPI/AccessControl/UserInfo/Record?format=json", payload,
        )

    def bind_card(
        self, employee_no: str, card_id: str, start_date: str, end_date: str
    ) -> bool:
        payload = {
            "CardInfo": {
                "employeeNo": employee_no,
                "cardNo": card_id,
                "cardType": "normalCard",
                "useTimes": 0,
                "status": "valid",
                "startDate": iso_date(start_date),
                "endDate": iso_date(end_date, end_of_day=True),
            }
        }
        return self._post_ok(
            "/ISAPI/AccessControl/CardInfo/Record?format=json", payload,
        )

    def search_users(self, max_results: int = 200) -> List[Dict[str, Any]]:
        payload = {
            "UserInfoSearchCond": {
                "searchID": "1",
                "maxResults": max_results,
                "searchResultPosition": 0,
            }
        }
        resp = self._post_raw(
            "/ISAPI/AccessControl/UserInfo/Search?format=json", payload,
        )
        if not resp:
            raise ConnectionError("Device unreachable or returned error for user search")
        try:
            data = resp.json()
            return data.get("UserInfoSearch", {}).get("UserInfo", []) or []
        except ValueError:
            raise ConnectionError(f"Invalid JSON from device: {resp.text[:200]}")

    def search_events(
        self,
        start: datetime,
        end: datetime,
        max_results: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        def fmt(dt: datetime) -> str:
            return dt.astimezone().isoformat(timespec="seconds")

        def extract_events(obj: Any) -> List[Dict[str, Any]]:
            found: List[Dict[str, Any]] = []
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k.lower() == "event" and isinstance(v, list):
                        found.extend(v)
                    else:
                        found.extend(extract_events(v))
            elif isinstance(obj, list):
                for item in obj:
                    found.extend(extract_events(item))
            return found

        payload = {
            "AcsEventCond": {
                "searchID": "1",
                "searchResultPosition": 0,
                "maxResults": max_results or 200,
                "major": 0,
                "minor": 0,
                "startTime": fmt(start),
                "endTime": fmt(end),
                "employeeNoString": "",
                "cardNo": "",
            }
        }

        results: List[Dict[str, Any]] = []
        position = 0
        first_request = True
        while True:
            payload["AcsEventCond"]["searchResultPosition"] = position
            resp = self._post_raw(
                "/ISAPI/AccessControl/AcsEvent?format=json", payload,
            )
            if not resp:
                if first_request:
                    raise ConnectionError("Device unreachable or returned error for event search")
                break
            first_request = False
            try:
                data = resp.json()
            except ValueError:
                _LOGGER.error("Hikvision event parse failed: %s", resp.text)
                break

            acs_block = (
                data.get("AcsEvent") or data.get("AcsEventSearchResult") or {}
            )
            page_events: List[Dict[str, Any]] = []
            if isinstance(acs_block, dict):
                if isinstance(acs_block.get("InfoList"), list):
                    page_events.extend(acs_block["InfoList"])
                if isinstance(acs_block.get("Event"), list):
                    page_events.extend(acs_block["Event"])
            if not page_events:
                page_events = extract_events(data)
            if not page_events:
                _LOGGER.info(
                    "Hikvision events empty, response: %s", resp.text[:1000],
                )
                break

            results.extend(page_events)

            status = ""
            num = None
            if isinstance(acs_block, dict):
                status = str(
                    acs_block.get("responseStatusStrg", "")
                ).upper()
                num = acs_block.get("numOfMatches")
            if status != "MORE":
                break
            if num is None or not isinstance(num, int) or num <= 0:
                break
            position += num

        return results

    def create_user_with_card(
        self,
        employee_no: str,
        name: str,
        start_date: str,
        end_date: str,
        card_id: str,
    ) -> Dict[str, Any]:
        created = self.create_user(employee_no, name, start_date, end_date)
        card_bound = False
        if created:
            card_bound = self.bind_card(
                employee_no, card_id, start_date, end_date,
            )
        return {"user_created": created, "card_bound": card_bound}

    def delete_user(self, employee_no: str) -> bool:
        payload = {
            "UserInfoDelCond": {
                "EmployeeNoList": [{"employeeNo": employee_no}],
            }
        }
        url = f"{self.base_url}/ISAPI/AccessControl/UserInfo/Delete?format=json"
        return self._request(("put", "post"), url, payload)

    def update_validity(
        self, employee_no: str, begin_date: str, end_date: str
    ) -> bool:
        payload = {
            "UserInfo": {
                "employeeNo": employee_no,
                "Valid": {
                    "enable": True,
                    "beginTime": iso_date(begin_date),
                    "endTime": iso_date(end_date, end_of_day=True),
                },
            }
        }
        url = f"{self.base_url}/ISAPI/AccessControl/UserInfo/Modify?format=json"
        return self._request(("put", "post"), url, payload)
