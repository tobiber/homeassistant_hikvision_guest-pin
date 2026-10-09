"""Hikvision ISAPI client for access control operations."""

from __future__ import annotations

import base64
import logging
import secrets
import string
import threading
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional, Set

import qrcode
import requests
from requests.auth import HTTPDigestAuth

from .const import DEFAULT_ALLOWED_EVENTS, EVENT_LABELS

_LOGGER = logging.getLogger(__name__)

# Hikvision ISAPI returns statusCode == 1 ("OK") on success. Any other value
# is a failure, even though the HTTP status is 200. See the ResponseStatus
# envelope documented at tpp.hikvision.com.
ISAPI_STATUS_OK = 1

# subStatusCodes that we treat as success because the desired end state is
# already reached (idempotent create/delete).
BENIGN_SUB_STATUS = {
    "employeeNoAlreadyExist",
    "deviceUserAlreadyExist",
    "userAlreadyExist",
    "cardNoAlreadyExist",
    "employeeNoNotExist",
    "userNotExist",
    "deviceUserNotExist",
}


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


def deactivation_window(
    begin_date: Optional[str] = None, today: Optional[datetime] = None
) -> tuple[str, str]:
    """Return a (begin, end) date pair that marks a user as expired.

    The end is yesterday, so the validity window lies completely in the past.
    The begin must never be *after* the end: the device rejects such a Modify,
    which would hit every user whose validity starts today or later (e.g. a
    guest created the same day). We therefore clamp the original begin to the
    end date and keep it otherwise, so the original start stays visible in the
    user list. An unknown or unparseable begin falls back to the end date.
    """
    ref = today or datetime.today()
    end = (ref - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    begin = end
    if begin_date:
        try:
            parsed = parse_date(begin_date)
        except ValueError:
            _LOGGER.warning(
                "Unparseable begin date %r for deactivation, using %s",
                begin_date, end.date(),
            )
        else:
            begin = min(parsed, end)

    return begin.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


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
        self._username = username
        self._password = password
        # Client methods run via hass.async_add_executor_job, so the
        # coordinator poll and a service call can hit the session from two
        # threads at once. The lock keeps a session reset from racing a
        # request that is already in flight.
        self._lock = threading.Lock()
        self._session = self._new_session()

    def _new_session(self) -> requests.Session:
        """Build a fresh session with a clean digest handshake."""
        session = requests.Session()
        session.auth = HTTPDigestAuth(self._username, self._password)
        session.verify = self.verify
        session.headers.update({"Content-Type": "application/json"})
        return session

    def _reset_session(self) -> None:
        """Drop the current session and start over with a new one."""
        self._session.close()
        self._session = self._new_session()

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
            resp = self._send("post", url, payload)
            if 200 <= resp.status_code < 300:
                return "ok"
            if resp.status_code == 401:
                return "auth_failed"
            return "cannot_connect"
        except requests.RequestException:
            return "cannot_connect"

    # -- Low-level helpers --------------------------------------------------

    def _send(
        self, method: str, url: str, payload: Optional[Dict] = None
    ) -> requests.Response:
        """Send one ISAPI request, renewing the digest session when needed.

        The device stops accepting the digest nonce it handed out earlier and
        then answers *every* request — Search, AcsEvent, Record, Delete,
        Modify — with HTTP 401 and an ``invalidOperation`` body. ``requests``
        keeps replaying the stale nonce, so the client stays broken until the
        config entry is reloaded. Dropping the session and retrying once
        forces a fresh handshake and recovers without a reload.

        The same retry covers ``ConnectionError``, because the device readily
        closes keep-alive sockets it considers idle.
        """
        with self._lock:
            try:
                resp = self._session.request(
                    method, url, json=payload, timeout=self.timeout,
                )
            except requests.ConnectionError as exc:
                _LOGGER.debug(
                    "Hikvision connection dropped (%s), resetting session", exc,
                )
                self._reset_session()
                return self._session.request(
                    method, url, json=payload, timeout=self.timeout,
                )

            if resp.status_code != 401:
                return resp

            _LOGGER.debug("Hikvision auth rejected, resetting digest session")
            self._reset_session()
            return self._session.request(
                method, url, json=payload, timeout=self.timeout,
            )

    @staticmethod
    def _parse_status(resp: requests.Response) -> tuple[bool, str]:
        """Inspect an ISAPI response body and decide if the op truly succeeded.

        Hikvision returns HTTP 200 even for failed access-control operations,
        carrying the real outcome in a ``ResponseStatus`` JSON envelope
        (``statusCode`` / ``subStatusCode`` / ``errorMsg``). ``statusCode == 1``
        means OK; anything else is a failure we must surface.

        Returns ``(ok, detail)`` where ``detail`` is a short human-readable
        reason on failure (or the benign sub-status on success).
        """
        text = resp.text or ""
        try:
            data = resp.json()
        except ValueError:
            # Non-JSON body (some endpoints answer with XML or empty on 2xx).
            # We already know the HTTP status is 2xx, so treat it as success.
            return True, text[:200]

        if not isinstance(data, dict):
            return True, str(data)[:200]

        status_code = data.get("statusCode")
        if status_code is None:
            # No ResponseStatus envelope (e.g. a data payload) — the 2xx HTTP
            # status is authoritative.
            return True, ""

        sub = str(data.get("subStatusCode", "") or "")
        if status_code == ISAPI_STATUS_OK:
            return True, sub or "ok"
        if sub in BENIGN_SUB_STATUS:
            return True, sub
        detail = (
            f"statusCode={status_code} subStatusCode={sub or '-'} "
            f"errorMsg={data.get('errorMsg') or data.get('statusString') or '-'}"
        )
        return False, detail

    def _post_raw(self, path: str, payload: Dict) -> Optional[requests.Response]:
        """POST and return the response on HTTP 2xx (read operations)."""
        url = f"{self.base_url}{path}"
        try:
            resp = self._send("post", url, payload)
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

    def _post_status(self, path: str, payload: Dict) -> tuple[bool, str]:
        """POST a state-changing op and verify both HTTP and ISAPI status."""
        url = f"{self.base_url}{path}"
        try:
            resp = self._send("post", url, payload)
        except requests.RequestException as exc:
            _LOGGER.error("Hikvision POST %s errored: %s", url, exc)
            return False, f"connection error: {exc}"
        if not 200 <= resp.status_code < 300:
            if resp.status_code == 401:
                _LOGGER.error(
                    "Hikvision POST %s: authentication rejected by device "
                    "after session reset – check username/password",
                    url,
                )
            else:
                _LOGGER.error(
                    "Hikvision POST %s failed (HTTP %s): %s",
                    url, resp.status_code, resp.text,
                )
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        ok, detail = self._parse_status(resp)
        if not ok:
            _LOGGER.error("Hikvision POST %s rejected by device: %s", url, detail)
        return ok, detail

    def _request(
        self, method_order: tuple, url: str, payload: Dict
    ) -> tuple[bool, str]:
        """Try PUT then POST (or vice versa) for delete/modify ops.

        Verifies both the HTTP status and the ISAPI ``statusCode`` body.
        Returns ``(ok, detail)``.
        """
        last_detail = "no response"
        for method in method_order:
            try:
                resp = self._send(method, url, payload)
            except requests.RequestException as exc:
                _LOGGER.error(
                    "Hikvision %s %s errored: %s", method.upper(), url, exc,
                )
                last_detail = f"connection error: {exc}"
                break
            if 200 <= resp.status_code < 300:
                ok, detail = self._parse_status(resp)
                if ok:
                    return True, detail
                _LOGGER.error(
                    "Hikvision %s %s rejected by device: %s",
                    method.upper(), url, detail,
                )
                # Device answered 2xx but rejected the body. Some firmware
                # routes delete/modify to a different verb, so fall through
                # and try the next one (both ops are idempotent).
                last_detail = detail
                continue
            if resp.status_code == 401:
                # _send already retried with a fresh digest handshake, so this
                # is a real credential problem, not the stale-nonce case.
                # Trying the other verb cannot help here.
                _LOGGER.error(
                    "Hikvision %s %s: authentication rejected by device after "
                    "session reset – check username/password",
                    method.upper(), url,
                )
                return False, f"HTTP 401: {resp.text[:200]}"
            _LOGGER.error(
                "Hikvision %s %s failed (HTTP %s): %s",
                method.upper(), url, resp.status_code, resp.text,
            )
            last_detail = f"HTTP {resp.status_code}: {resp.text[:200]}"
            # 400/405 => wrong verb for this firmware, try the next one.
            if resp.status_code not in (400, 405):
                break
        return False, last_detail

    # -- ISAPI operations ---------------------------------------------------

    def create_user(
        self, employee_no: str, name: str, start_date: str, end_date: str
    ) -> tuple[bool, str]:
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
                    # timeType=local keeps the device from interpreting the
                    # window as UTC, which would shift validity by the TZ
                    # offset and make a "successfully created" user unusable.
                    "timeType": "local",
                    "beginTime": iso_date(start_date),
                    "endTime": iso_date(end_date, end_of_day=True),
                },
                "doorRight": "1",
                "rightPlan": [{"doorNo": 1, "planTemplateNo": "1"}],
            }
        }
        return self._post_status(
            "/ISAPI/AccessControl/UserInfo/Record?format=json", payload,
        )

    def bind_card(
        self, employee_no: str, card_id: str, start_date: str, end_date: str
    ) -> tuple[bool, str]:
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
        return self._post_status(
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
        created, create_detail = self.create_user(
            employee_no, name, start_date, end_date
        )
        card_bound = False
        card_detail = ""
        if created:
            card_bound, card_detail = self.bind_card(
                employee_no, card_id, start_date, end_date,
            )
        return {
            "user_created": created,
            "card_bound": card_bound,
            "create_detail": create_detail,
            "card_detail": card_detail,
        }

    def delete_user(self, employee_no: str) -> tuple[bool, str]:
        payload = {
            "UserInfoDelCond": {
                "EmployeeNoList": [{"employeeNo": employee_no}],
            }
        }
        url = f"{self.base_url}/ISAPI/AccessControl/UserInfo/Delete?format=json"
        return self._request(("put", "post"), url, payload)

    def update_validity(
        self, employee_no: str, begin_date: str, end_date: str
    ) -> tuple[bool, str]:
        payload = {
            "UserInfo": {
                "employeeNo": employee_no,
                "Valid": {
                    "enable": True,
                    "timeType": "local",
                    "beginTime": iso_date(begin_date),
                    "endTime": iso_date(end_date, end_of_day=True),
                },
            }
        }
        url = f"{self.base_url}/ISAPI/AccessControl/UserInfo/Modify?format=json"
        return self._request(("put", "post"), url, payload)
