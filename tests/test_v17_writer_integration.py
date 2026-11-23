from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from amt_engine.v17_writer import (
    BRANCH_ID,
    DATABASE_NAME,
    PROJECT_ID,
    persist_session,
    validate_target_environment,
)
from test_v17_writer import _payload


@pytest.fixture(scope="module")
def writer_connection():
    url = os.environ.get("V17_DEV_DATABASE_URL")
    if not url:
        pytest.skip("V17_DEV_DATABASE_URL secret is not configured")
    validate_target_environment({
        "NEON_PROJECT_ID": os.environ.get("NEON_PROJECT_ID", ""),
        "NEON_BRANCH_ID": os.environ.get("NEON_BRANCH_ID", ""),
        "NEON_DATABASE_NAME": os.environ.get("NEON_DATABASE_NAME", ""),
        "DATABASE_URL": url,
    })
    with psycopg.connect(url, sslmode="require", row_factory=dict_row) as conn:
        yield conn


def _now():
    return datetime(2026, 11, 24, 0, 0, tzinfo=timezone.utc)


def _shift_first_receipt(payload):
    from datetime import timedelta
    for key in ("source_available_at", "ingested_at"):
        dt = datetime.fromisoformat(payload["price_records"][0][key])
        payload["price_records"][0][key] = (dt + timedelta(seconds=1)).isoformat()


def test_first_write_replay_conflict_digest_and_rollback(writer_connection):
    suffix = uuid4().hex[:10].upper()
    symbol = f"TEST_BTCUSD_V17_{suffix}"

    # First write.
    original = _payload(symbol)
    first = persist_session(writer_connection, original, now=_now(), test_mode=True)
    assert first["status"] == "PERSISTED"
    assert first["oi_units_verified"] is True
    assert first["identity"]["identity_verified"] is True

    # Exact replay returns the same profile, and the V2 writer verifies the
    # stored input fingerprint and persisted-row SHA-256 before returning.
    replay = persist_session(writer_connection, original, now=_now(), test_mode=True)
    assert replay["profile_id"] == first["profile_id"]

    with writer_connection.cursor() as cur:
        cur.execute(
            "SELECT amt_engine_v17.calculate_persisted_session_sha256_v1(%s::uuid) AS digest",
            (first["profile_id"],),
        )
        digest = cur.fetchone()["digest"]
    assert len(digest) == 64
    writer_connection.commit()

    # A changed receipt is a changed complete bundle, not an exact replay.
    conflicting = _payload(symbol)
    _shift_first_receipt(conflicting)
    with pytest.raises(psycopg.Error, match="CONFLICTING_REPLAY"):
        persist_session(writer_connection, conflicting, now=_now(), test_mode=True)
    writer_connection.rollback()

    # Roll back a valid first write. A subsequent changed bundle must be
    # accepted as a first write; if the first transaction leaked, it conflicts.
    rollback_symbol = f"TEST_BTCUSD_V17_ROLLBACK_{suffix}"
    rollback_payload = _payload(rollback_symbol)
    try:
        with writer_connection.transaction():
            rolled_back = persist_session(
                writer_connection, rollback_payload, now=_now(), test_mode=True
            )
            raise RuntimeError("intentional test rollback")
    except RuntimeError as exc:
        assert str(exc) == "intentional test rollback"

    after_rollback = _payload(rollback_symbol)
    _shift_first_receipt(after_rollback)
    recovered = persist_session(
        writer_connection, after_rollback, now=_now(), test_mode=True
    )
    assert recovered["profile_id"] != rolled_back["profile_id"]
