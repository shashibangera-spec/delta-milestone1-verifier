"""Isolated BTC AMT Engine V1.7 session writer.

Consumes a validated-session JSON envelope and persists only through the
least-privilege V2 idempotent SECURITY DEFINER writer. No direct table DML.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

PROJECT_ID = "old-surf-34279165"
BRANCH_ID = "br-crimson-tooth-ao7oq469"
DATABASE_NAME = "amt_research"
DATABASE_ROLE = "amt_v17_writer_login"
SCHEMA = "amt_engine_v17"
SOURCE = "delta_india"
SYMBOL = "BTCUSD"
RESOLUTION = "30m"
TIMESTAMP_CONVENTION = "OPEN"
OI_UNITS = "BTC"
IST = ZoneInfo("Asia/Kolkata")
ALLOWED_HOSTS = {
    "ep-old-bar-aoau4qop.c-2.ap-southeast-1.aws.neon.tech",
    "ep-old-bar-aoau4qop-cqp.c-2.ap-southeast-1.aws.neon.tech",
}


class IdentityError(RuntimeError):
    """Fail-closed target or database identity mismatch."""


def session_bounds_utc(session_date: date) -> tuple[datetime, datetime]:
    """A 05:30 IST session is 00:00 UTC through next 00:00 UTC."""
    local_start = datetime.combine(session_date, time(5, 30), tzinfo=IST)
    start = local_start.astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def validate_target_environment(env: dict[str, str]) -> None:
    if env.get("NEON_PROJECT_ID") != PROJECT_ID:
        raise IdentityError("NEON_PROJECT_ID does not match the approved development project")
    if env.get("NEON_BRANCH_ID") != BRANCH_ID:
        raise IdentityError("NEON_BRANCH_ID does not match the approved development branch")
    if env.get("NEON_DATABASE_NAME") != DATABASE_NAME:
        raise IdentityError("NEON_DATABASE_NAME does not match the approved database")
    url = env.get("DATABASE_URL", "")
    if not url:
        raise IdentityError("DATABASE_URL is required")
    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql") or parsed.hostname not in ALLOWED_HOSTS:
        raise IdentityError("DATABASE_URL host does not match the isolated development endpoint")
    if parsed.path.lstrip("/") != DATABASE_NAME:
        raise IdentityError("DATABASE_URL database path does not match amt_research")


def verify_database_identity(conn) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT current_database() AS database_name, "
            "current_user AS current_user, session_user AS session_user"
        )
        row = cur.fetchone()
    if (
        not row
        or row["database_name"] != DATABASE_NAME
        or row["current_user"] != DATABASE_ROLE
        or row["session_user"] != DATABASE_ROLE
    ):
        raise IdentityError(
            "Connected PostgreSQL identity is not amt_v17_writer_login on amt_research"
        )
    return {
        "project_id": PROJECT_ID,
        "branch_id": BRANCH_ID,
        "database_name": row["database_name"],
        "current_user": row["current_user"],
        "session_user": row["session_user"],
        "identity_verified": True,
    }


def _parse_aware(value: str, field: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _source_audit(records: list[dict], series_type: str) -> list[dict]:
    audit = []
    for record in records:
        ts = _parse_aware(record["timestamp"], f"{series_type}.timestamp")
        available = _parse_aware(record["source_available_at"], f"{series_type}.source_available_at")
        ingested = _parse_aware(record["ingested_at"], f"{series_type}.ingested_at")
        audit.append({
            "candle_id": record.get("candle_id") or f"{series_type}|{ts:%Y%m%d%H%M%S}",
            "source": SOURCE,
            "symbol": SYMBOL,
            "series_type": series_type,
            "resolution": RESOLUTION,
            "timestamp_convention": TIMESTAMP_CONVENTION,
            "source_candle_time": ts.isoformat(),
            "canonical_open_time": ts.isoformat(),
            "source_available_at": available.isoformat(),
            "ingested_at": ingested.isoformat(),
            "validation_status": "VALID",
        })
    return audit


def validate_envelope(payload: dict, now: datetime | None = None) -> tuple[date, datetime, list, list, list, list]:
    if payload.get("source") != SOURCE or payload.get("symbol") != SYMBOL:
        raise ValueError("Only Delta India BTCUSD inputs are accepted by this runner")
    if payload.get("resolution") != RESOLUTION:
        raise ValueError("Only 30m inputs are accepted")
    if payload.get("timestamp_convention") != TIMESTAMP_CONVENTION:
        raise ValueError("Input timestamps must be candle OPEN timestamps")
    if payload.get("price_units") != "USD":
        raise ValueError("PRICE input unit must be USD")
    session_date = date.fromisoformat(payload["session_date"])
    start, end = session_bounds_utc(session_date)
    cutoff = _parse_aware(payload["cutoff_at"], "cutoff_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if cutoff < end:
        raise ValueError("Session cutoff precedes the 05:30 IST / 00:00 UTC session boundary")
    if cutoff > current:
        raise ValueError("Session cutoff cannot be in the future")
    if current < end:
        raise ValueError("Session is not closed; refusing to calculate or persist")

    price = payload.get("price_records")
    oi = payload.get("oi_records", [])
    prior = payload.get("prior_profiles", [])
    if not isinstance(price, list) or len(price) != 48:
        raise ValueError("Exactly 48 PRICE candle records are required")
    if not isinstance(oi, list) or len(oi) not in (0, 48):
        raise ValueError("OI must be absent or contain exactly 48 records")
    if not isinstance(prior, list):
        raise ValueError("prior_profiles must be a JSON array")
    if oi and (payload.get("oi_units") != OI_UNITS or payload.get("oi_units_verified") is not True):
        raise ValueError("OI requires verified Delta India BTC base units (oi_units=BTC)")
    if not oi and payload.get("oi_units_verified") is True:
        raise ValueError("Do not mark OI units verified when no OI records are supplied")

    expected = [start + timedelta(minutes=30 * i) for i in range(48)]
    for label, records in (("PRICE", price), ("OI", oi)):
        seen = []
        for rec in records:
            ts = _parse_aware(rec["timestamp"], f"{label}.timestamp")
            if ts not in expected:
                raise ValueError(f"{label} timestamp is not one of the 48 exact OPEN slots")
            available = _parse_aware(rec["source_available_at"], f"{label}.source_available_at")
            ingested = _parse_aware(rec["ingested_at"], f"{label}.ingested_at")
            if available > cutoff or ingested > cutoff:
                raise ValueError(f"{label} record arrived after the session cutoff")
            seen.append(ts)
        if len(set(seen)) != len(seen):
            raise ValueError(f"{label} contains duplicate candle OPEN timestamps")
        if records and set(seen) != set(expected):
            raise ValueError(f"{label} does not cover all 48 session OPEN timestamps")
    if oi and {r["timestamp"] for r in oi} != {r["timestamp"] for r in price}:
        raise ValueError("PRICE and OI candle OPEN timestamps are not paired")

    audit = _source_audit(price, "PRICE") + _source_audit(oi, "OI")
    return session_date, cutoff, price, oi, prior, audit


def persist_session(conn, payload: dict, now: datetime | None = None) -> dict:
    identity = verify_database_identity(conn)
    session_date, cutoff, price, oi, prior, audit = validate_envelope(payload, now)
    oi_verified = bool(oi) and payload.get("oi_units_verified") is True

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {SCHEMA}.build_audited_dual_series_calculation_fixture_v2("
            "%s::date,%s::jsonb,%s::jsonb,%s::jsonb,%s::timestamptz,%s) AS calculation",
            (
                session_date,
                json.dumps(price),
                json.dumps(oi),
                json.dumps(prior),
                cutoff,
                oi_verified,
            ),
        )
        calculation = cur.fetchone()[0]
        cur.execute(
            f"SELECT {SCHEMA}.adapt_dual_series_session_calculation_fixture_v5("
            "%s::jsonb,%s,%s,%s::jsonb) AS bundle",
            (json.dumps(calculation), SYMBOL, SOURCE, json.dumps(audit)),
        )
        bundle = cur.fetchone()[0]
        # Defense in depth: verify the calculation explicitly preserved verified BTC OI.
        oi_context = calculation.get("oi_context") or {}
        if oi_verified and oi_context.get("units_verified") is not True:
            raise RuntimeError("Calculation did not preserve verified BTC OI units")
        cur.execute(
            f"SELECT {SCHEMA}.persist_idempotent_dual_series_bundle_fixture_v2("
            "%s::jsonb,false) AS profile_id",
            (json.dumps(bundle),),
        )
        profile_id = cur.fetchone()["profile_id"]
    conn.commit()
    return {
        "status": "PERSISTED",
        "profile_id": str(profile_id),
        "session_date": session_date.isoformat(),
        "identity": identity,
        "oi_context_available": bool((calculation.get("live_input_validation") or {}).get("oi_context_available")),
        "oi_units_verified": oi_verified,
        "timestamp_convention": TIMESTAMP_CONVENTION,
        "session_start_utc": session_bounds_utc(session_date)[0].isoformat(),
        "session_end_utc": session_bounds_utc(session_date)[1].isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="JSON session envelope file")
    args = parser.parse_args()
    env = dict(os.environ)
    validate_target_environment(env)
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    with psycopg.connect(env["DATABASE_URL"], sslmode="require", row_factory=dict_row) as conn:
        result = persist_session(conn, payload)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
