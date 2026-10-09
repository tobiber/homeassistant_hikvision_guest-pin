"""Unit tests for the Hikvision ISAPI client's pure logic.

These tests intentionally avoid importing Home Assistant so they run in a
plain Python environment (``pip install requests qrcode pytest``). They focus
on the behaviour that caused the reported "users not created/deleted" bug:
the device answers HTTP 200 even for failed operations, so the outcome must be
read from the ISAPI ``statusCode`` body.
"""

import json
import threading
from datetime import datetime
from unittest.mock import MagicMock

import requests

import pytest

from hikvision_userpin.client import (  # noqa: E402
    HikvisionClient,
    compute_end_date,
    deactivation_window,
    parse_date,
    parse_event_codes,
)


def _resp(status_code=200, body=None, text=None):
    """Build a fake requests.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    if body is not None:
        resp.text = json.dumps(body)
        resp.json.return_value = body
    else:
        resp.text = text or ""
        resp.json.side_effect = ValueError("no json")
    return resp


# ---------------------------------------------------------------------------
# _parse_status — the core of the fix
# ---------------------------------------------------------------------------

def test_parse_status_ok():
    ok, detail = HikvisionClient._parse_status(
        _resp(body={"statusCode": 1, "statusString": "OK", "subStatusCode": "ok"})
    )
    assert ok is True


def test_parse_status_failure_is_detected_on_http_200():
    """HTTP 200 with statusCode != 1 must be treated as a failure."""
    ok, detail = HikvisionClient._parse_status(
        _resp(
            body={
                "statusCode": 6,
                "statusString": "Invalid Operation",
                "subStatusCode": "notSupport",
                "errorMsg": "notSupport",
            }
        )
    )
    assert ok is False
    assert "notSupport" in detail


def test_parse_status_benign_substatus_is_success():
    """An already-existing/already-gone user is an acceptable end state."""
    ok, _ = HikvisionClient._parse_status(
        _resp(body={"statusCode": 6, "subStatusCode": "employeeNoAlreadyExist"})
    )
    assert ok is True


def test_parse_status_non_json_2xx_is_success():
    ok, _ = HikvisionClient._parse_status(_resp(text="<xml>ok</xml>"))
    assert ok is True


def test_parse_status_no_envelope_is_success():
    ok, _ = HikvisionClient._parse_status(_resp(body={"UserInfo": []}))
    assert ok is True


# ---------------------------------------------------------------------------
# create_user / delete_user go through _parse_status
# ---------------------------------------------------------------------------

def _client(*sessions):
    """Build a client without __init__, optionally queueing session mocks.

    The first mock is the active session; each ``_reset_session`` hands out
    the next one, which lets a test observe that the digest session was
    actually rebuilt.
    """
    c = HikvisionClient.__new__(HikvisionClient)
    c.base_url = "http://device"
    c.timeout = 8.0
    c.verify = False
    c._username = "admin"
    c._password = "secret"
    c._lock = threading.Lock()
    queue = list(sessions) or [MagicMock()]
    c._session = queue.pop(0)
    c._new_session = MagicMock(side_effect=lambda: queue.pop(0))
    return c


def test_create_user_reports_device_rejection():
    c = _client()
    c._session.request.return_value = _resp(
        body={"statusCode": 6, "subStatusCode": "riskPassword", "errorMsg": "bad"}
    )
    ok, detail = c.create_user("EMP1", "Max", "2026-01-01", "2026-01-08")
    assert ok is False
    assert "riskPassword" in detail


def test_delete_user_success_on_put():
    c = _client()
    c._session.request.return_value = _resp(body={"statusCode": 1})
    ok, _ = c.delete_user("EMP1")
    assert ok is True
    assert c._session.request.call_args[0][0] == "put"


def test_delete_user_reports_failure_body():
    c = _client()
    c._session.request.return_value = _resp(
        body={"statusCode": 4, "subStatusCode": "invalidContent"}
    )
    ok, detail = c.delete_user("EMP1")
    assert ok is False
    assert "invalidContent" in detail


# ---------------------------------------------------------------------------
# Digest session reset — the device invalidates its nonce after a while and
# then answers every request with 401 + invalidOperation until reconnected.
# ---------------------------------------------------------------------------

AUTH_REJECTED = {
    "statusCode": 4,
    "statusString": "Invalid Operation",
    "subStatusCode": "invalidOperation",
    "errorCode": 1073741830,
}


def test_stale_nonce_401_is_retried_on_a_fresh_session():
    stale, fresh = MagicMock(), MagicMock()
    stale.request.return_value = _resp(401, body=AUTH_REJECTED)
    fresh.request.return_value = _resp(body={"statusCode": 1})
    c = _client(stale, fresh)

    ok, _ = c.delete_user("EMP1")

    assert ok is True
    assert c._new_session.call_count == 1
    assert c._session is fresh
    assert stale.close.called
    assert stale.request.call_count == 1
    assert fresh.request.call_count == 1


def test_persistent_401_fails_after_exactly_one_retry():
    stale, fresh = MagicMock(), MagicMock()
    stale.request.return_value = _resp(401, body=AUTH_REJECTED)
    fresh.request.return_value = _resp(401, body=AUTH_REJECTED)
    c = _client(stale, fresh)

    ok, detail = c.delete_user("EMP1")

    assert ok is False
    assert "401" in detail
    # One request per session, no endless retry and no PUT/POST fallthrough.
    assert stale.request.call_count == 1
    assert fresh.request.call_count == 1
    assert c._new_session.call_count == 1


def test_connection_error_is_retried_on_a_fresh_session():
    dropped, fresh = MagicMock(), MagicMock()
    dropped.request.side_effect = requests.ConnectionError("connection aborted")
    fresh.request.return_value = _resp(body={"statusCode": 1})
    c = _client(dropped, fresh)

    ok, _ = c.delete_user("EMP1")

    assert ok is True
    assert c._new_session.call_count == 1
    assert c._session is fresh


def test_successful_request_keeps_the_session():
    c = _client()
    c._session.request.return_value = _resp(body={"statusCode": 1})

    ok, _ = c.delete_user("EMP1")

    assert ok is True
    assert c._new_session.call_count == 0


def test_test_connection_recovers_from_stale_nonce():
    stale, fresh = MagicMock(), MagicMock()
    stale.request.return_value = _resp(401, body=AUTH_REJECTED)
    fresh.request.return_value = _resp(body={"statusCode": 1})
    c = _client(stale, fresh)

    assert c.test_connection() == "ok"


def test_test_connection_reports_auth_failed_on_real_bad_credentials():
    stale, fresh = MagicMock(), MagicMock()
    stale.request.return_value = _resp(401, text="unauthorized")
    fresh.request.return_value = _resp(401, text="unauthorized")
    c = _client(stale, fresh)

    assert c.test_connection() == "auth_failed"


# ---------------------------------------------------------------------------
# Duration / date helpers (regression guard)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "dur,expected_days",
    [("1d", 0), ("7d", 6), ("14d", 13), ("4w", 27)],
)
def test_compute_end_date_inclusive(dur, expected_days):
    start = datetime(2026, 1, 1)
    end = compute_end_date(start, dur)
    assert (end - start).days == expected_days


# ---------------------------------------------------------------------------
# Deactivation window — the end must never fall before the begin, or the
# device rejects the Modify for anyone whose validity starts today or later.
# ---------------------------------------------------------------------------

TODAY = datetime(2026, 10, 9)


def test_deactivation_window_keeps_a_past_begin():
    begin, end = deactivation_window("2026-10-01", today=TODAY)
    assert (begin, end) == ("2026-10-01", "2026-10-08")


def test_deactivation_window_clamps_a_begin_in_the_future():
    """A guest created today must not end up with end < begin."""
    begin, end = deactivation_window("2026-10-20", today=TODAY)
    assert (begin, end) == ("2026-10-08", "2026-10-08")


def test_deactivation_window_clamps_a_begin_of_today():
    begin, end = deactivation_window("2026-10-09", today=TODAY)
    assert begin == end == "2026-10-08"


@pytest.mark.parametrize("value", [None, "", "not-a-date"])
def test_deactivation_window_without_usable_begin(value):
    begin, end = deactivation_window(value, today=TODAY)
    assert begin == end == "2026-10-08"


def test_deactivation_window_never_ends_before_it_begins():
    for value in ("2020-01-01", "2026-10-08", "2026-10-09", "2099-12-31", None):
        begin, end = deactivation_window(value, today=TODAY)
        assert parse_date(begin) <= parse_date(end)
        assert parse_date(end) < TODAY


def test_parse_date_formats():
    assert parse_date("2026-01-01") == datetime(2026, 1, 1)
    assert parse_date("01.01.2026") == datetime(2026, 1, 1)


def test_parse_event_codes():
    assert parse_event_codes("5/75,5-38") == {(5, 75), (5, 38)}
