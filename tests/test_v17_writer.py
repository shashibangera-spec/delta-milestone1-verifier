from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from amt_engine.v17_writer import (
    BRANCH_ID,
    DATABASE_NAME,
    DATABASE_ROLE,
    PROJECT_ID,
    IdentityError,
    session_bounds_utc,
    validate_envelope,
    validate_target_environment,
    verify_database_identity,
)


def _records(session_date: date, series: str) -> list[dict]:
    start, _ = session_bounds_utc(session_date)
    out = []
    for i in range(48):
        ts = start + timedelta(minutes=30 * i)
        base = 60000 + i * 5 if series == "PRICE" else 654 + i * 0.01
        out.append({
            "candle_id": f"{series}|{ts:%Y%m%d%H%M}",
            "timestamp": ts.isoformat(),
            "open": base,
            "high": base + (20 if series == "PRICE" else 1),
            "low": base - (20 if series == "PRICE" else 1),
            "close": base + (10 if series == "PRICE" else 0.5),
            "source_available_at": (ts + timedelta(minutes=30)).isoformat(),
            "ingested_at": (ts + timedelta(minutes=30)).isoformat(),
        })
    return out


def _payload(symbol: str = "BTCUSD") -> dict:
    d = date(2026, 11, 22)
    _, end = session_bounds_utc(d)
    return {
        "session_date": d.isoformat(),
        "source": "delta_india",
        "symbol": symbol,
        "resolution": "30m",
        "timestamp_convention": "OPEN",
        "price_units": "USD",
        "oi_units": "BTC",
        "oi_units_verified": True,
        "cutoff_at": end.isoformat(),
        "price_records": _records(d, "PRICE"),
        "oi_records": _records(d, "OI"),
        "prior_profiles": [],
    }


def test_session_boundary_is_0530_ist_and_0000_utc():
    start, end = session_bounds_utc(date(2026, 11, 22))
    assert start == datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc)


def test_target_environment_requires_exact_isolated_branch():
    env = {
        "NEON_PROJECT_ID": PROJECT_ID,
        "NEON_BRANCH_ID": BRANCH_ID,
        "NEON_DATABASE_NAME": DATABASE_NAME,
        "DATABASE_URL": "postgresql://amt_v17_writer_login:secret@ep-old-bar-aoau4qop-pooler.c-2.ap-southeast-1.aws.neon.tech/amt_research",
    }
    validate_target_environment(env)
    env["NEON_BRANCH_ID"] = "br-snowy-water-aog0ilqw"
    with pytest.raises(IdentityError):
        validate_target_environment(env)


def test_wrong_database_role_is_rejected():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = {
        "database_name": DATABASE_NAME,
        "current_user": "neon_service",
        "session_user": "neon_service",
    }
    conn.cursor.return_value.__enter__.return_value = cursor
    with pytest.raises(IdentityError):
        verify_database_identity(conn)


def test_production_envelope_requires_verified_btc_oi():
    payload = _payload()
    payload["oi_units_verified"] = False
    with pytest.raises(ValueError, match="verified Delta India BTC base units"):
        validate_envelope(payload, datetime(2026, 11, 24, tzinfo=timezone.utc))


def test_production_envelope_rejects_non_open_timestamps():
    payload = _payload()
    payload["timestamp_convention"] = "CLOSE"
    with pytest.raises(ValueError, match="candle OPEN"):
        validate_envelope(payload, datetime(2026, 11, 24, tzinfo=timezone.utc))
