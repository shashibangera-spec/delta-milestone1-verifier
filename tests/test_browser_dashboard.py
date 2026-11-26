from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from browser_dashboard.main import EXPECTED_HOST, _connect, _discovery, _json, _validated_database_url, require_dashboard_auth


def rows(*closes):
    start = datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc)
    return [
        {"candle_time": start + timedelta(minutes=30 * i), "close_value": close}
        for i, close in enumerate(closes)
    ]


def test_dashboard_discovery_starts_on_first_close_outside_value():
    assert _discovery(rows(60500), 60000, 59000) == "DISCOVERY_ABOVE"
    assert _discovery(rows(58000), 60000, 59000) == "DISCOVERY_BELOW"


def test_dashboard_discovery_terminates_after_two_strict_inside_closes():
    assert _discovery(rows(60500, 59500), 60000, 59000) == "DISCOVERY_ABOVE"
    assert _discovery(rows(60500, 59500, 59600), 60000, 59000) == "IN_VALUE"


def test_dashboard_discovery_opposite_boundary_breach_switches_state():
    assert _discovery(rows(60500, 58900), 60000, 59000) == "DISCOVERY_BELOW"


def test_dashboard_discovery_requires_contiguous_session_history():
    candles = rows(60500, 59500, 59600)
    candles[2]["candle_time"] += timedelta(minutes=30)
    assert _discovery(candles, 60000, 59000) == "UNKNOWN"


def test_dashboard_refuses_non_production_host_before_connecting(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://amt_dashboard_ro:secret@ep-old-bar-aoau4qop.c-2.ap-southeast-1.aws.neon.tech/amt_research",
    )
    with pytest.raises(RuntimeError, match="approved amt_dashboard_ro"):
        _connect()


def test_dashboard_accepts_approved_neon_pooler_host(monkeypatch):
    url = (
        "postgresql://amt_dashboard_ro:secret@"
        "ep-morning-mountain-aopl02wv-pooler.c-2.ap-southeast-1.aws.neon.tech/"
        "amt_research"
    )
    monkeypatch.setenv("DATABASE_URL", url)
    assert _validated_database_url("DATABASE_URL", EXPECTED_HOST) == url


def test_dashboard_rejects_wrong_branch_host(monkeypatch):
    monkeypatch.setenv(
        "SOURCE_DATABASE_URL",
        "postgresql://amt_dashboard_ro:secret@ep-wrong-branch.c-2.ap-southeast-1.aws.neon.tech/amt_research",
    )
    with pytest.raises(RuntimeError, match="approved amt_dashboard_ro"):
        _validated_database_url(
            "SOURCE_DATABASE_URL",
            "ep-sparkling-queen-aoqgp0mw.c-2.ap-southeast-1.aws.neon.tech",
        )


def test_dashboard_requires_configured_basic_auth(monkeypatch):
    monkeypatch.delenv("DASHBOARD_USERNAME", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_dashboard_auth(HTTPBasicCredentials(username="user", password="pass"))
    assert exc.value.status_code == 503


def test_dashboard_basic_auth_accepts_only_matching_credentials(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "observer")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "correct-horse-battery")
    assert require_dashboard_auth(
        HTTPBasicCredentials(username="observer", password="correct-horse-battery")
    ) == "observer"
    with pytest.raises(HTTPException) as exc:
        require_dashboard_auth(HTTPBasicCredentials(username="observer", password="wrong"))
    assert exc.value.status_code == 401


def test_dashboard_json_serializes_uuid_and_date_values():
    from uuid import UUID
    value = {
        "profile_id": UUID("12345678-1234-5678-1234-567812345678"),
        "session_date": date(2026, 11, 26),
    }
    assert _json(value) == {
        "profile_id": "12345678-1234-5678-1234-567812345678",
        "session_date": "2026-11-26",
    }
