from datetime import datetime, timedelta, timezone

import pytest

from browser_dashboard.main import _connect, _discovery


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
    with pytest.raises(RuntimeError, match="production amt_dashboard_ro"):
        _connect()
