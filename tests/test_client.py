"""Unit tests for the Hikvision ISAPI client's pure logic.

These tests intentionally avoid importing Home Assistant so they run in a
plain Python environment (``pip install requests qrcode pytest``). They focus
on the behaviour that caused the reported "users not created/deleted" bug:
the device answers HTTP 200 even for failed operations, so the outcome must be
read from the ISAPI ``statusCode`` body.
"""

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from hikvision_userpin.client import (  # noqa: E402
    HikvisionClient,
    compute_end_date,
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

def _client():
    c = HikvisionClient.__new__(HikvisionClient)
    c.base_url = "http://device"
    c.timeout = 8.0
    c._session = MagicMock()
    return c


def test_create_user_reports_device_rejection():
    c = _client()
    c._session.post.return_value = _resp(
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


def test_parse_date_formats():
    assert parse_date("2026-01-01") == datetime(2026, 1, 1)
    assert parse_date("01.01.2026") == datetime(2026, 1, 1)


def test_parse_event_codes():
    assert parse_event_codes("5/75,5-38") == {(5, 75), (5, 38)}
