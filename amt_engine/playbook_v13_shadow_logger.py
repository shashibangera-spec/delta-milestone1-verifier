"""Incremental Playbook v1.3 shadow logger. Research-only; no order routing."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from amt_engine.playbook_v13 import (
    build_signal, classify_discovery, classify_oi, deterministic_trade_key,
    evaluate_exit, session_end_exit,
)
from amt_engine.v17_writer import (
    BRANCH_ID, BRANCH_HOSTS, DATABASE_NAME, DATABASE_ROLE, PROJECT_ID,
    validate_target_environment, verify_database_identity,
)

SOURCE_BRANCH = "br-lingering-grass-ao07mgrx"
SOURCE_HOST = "ep-sparkling-queen-aoqgp0mw.c-2.ap-southeast-1.aws.neon.tech"
TARGET_HOST = next(iter(BRANCH_HOSTS[BRANCH_ID])) if len(BRANCH_HOSTS.get(BRANCH_ID, set())) == 1 else None
METHOD = "AMT_ENGINE_V1.7"
CANDLE = timedelta(minutes=30)


class ShadowLoggerError(RuntimeError):
    pass


def _connect_ro(url: str, expected_host: str, label: str):
    parsed = urlparse(url or "")
    if parsed.scheme not in ("postgres", "postgresql") or parsed.hostname != expected_host:
        raise ShadowLoggerError(f"{label} URL is not pinned to its approved Neon branch")
    conn = psycopg.connect(url, sslmode="require", row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SELECT current_database(),current_user,session_user")
            db, user, session_user = cur.fetchone()
        if (db, user, session_user) != (DATABASE_NAME, "amt_dashboard_ro", "amt_dashboard_ro"):
            raise ShadowLoggerError(f"{label} read-only database identity mismatch")
        return conn
    except Exception:
        conn.close()
        raise


def _iso(value):
    return value.astimezone(timezone.utc).isoformat() if value else None


def _load_state(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT shadow_started_at,last_processed_candle_open,starting_realized_r
                       FROM amt_engine_v17.playbook_v13_shadow_state WHERE singleton=true""")
        row = cur.fetchone()
    if not row:
        raise ShadowLoggerError("Playbook v1.3 shadow state is not initialized; apply its migration first")
    if float(row["starting_realized_r"]) != 0.0:
        raise ShadowLoggerError("Shadow ledger must start at exactly 0.0R")
    return row


def _load_price_rows(conn, from_time, now):
    with conn.cursor() as cur:
        cur.execute("""SELECT candle_time,open_value,high_value,low_value,close_value,retrieved_at
                       FROM research.delta_candles
                       WHERE source='delta_india' AND series_type='PRICE' AND symbol='BTCUSD'
                         AND resolution='30m' AND candle_time >= %s
                         AND candle_time + interval '30 minutes' <= %s
                       ORDER BY candle_time""", (from_time, now))
        return cur.fetchall()


def _load_oi_rows(conn, from_time, now):
    with conn.cursor() as cur:
        cur.execute("""SELECT candle_time,open_value,close_value,retrieved_at
                       FROM research.delta_candles
                       WHERE source='delta_india' AND series_type='OI' AND symbol='OI:BTCUSD'
                         AND resolution='30m' AND candle_time >= %s
                         AND candle_time + interval '30 minutes' <= %s
                       ORDER BY candle_time""", (from_time, now))
        return cur.fetchall()


def _prior_profile(conn, session_date):
    with conn.cursor() as cur:
        cur.execute("""SELECT profile_id,session_date,vah_upper,val_lower
                       FROM amt_engine_v17.session_profiles
                       WHERE source='delta_india' AND symbol='BTCUSD'
                         AND method_version=%s AND profile_status='COMPLETE'
                         AND is_complete=true AND session_date < %s
                       ORDER BY session_date DESC LIMIT 1""", (METHOD, session_date))
        return cur.fetchone()


def _open_trade(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT trade_key,side,entry_price,stop_price,target_price,risk_points
                       FROM amt_engine_v17.playbook_v13_shadow_trades
                       WHERE status='OPEN' ORDER BY signal_candle_close LIMIT 2""")
        rows = cur.fetchall()
    if len(rows) > 1:
        raise ShadowLoggerError("More than one open shadow trade exists; refusing to continue")
    return rows[0] if rows else None


def _record(writer, trade_key, event_type, event_at, payload):
    with writer.cursor() as cur:
        cur.execute(
            "SELECT amt_engine_v17.record_playbook_v13_shadow_event(%s,%s,%s,%s::jsonb)",
            (trade_key, event_type, event_at, json.dumps(payload, sort_keys=True)),
        )


def _advance_cursor(writer, candle_open):
    with writer.cursor() as cur:
        cur.execute("SELECT amt_engine_v17.advance_playbook_v13_shadow_cursor(%s)", (candle_open,))


def run_shadow(now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    env = dict(os.environ)
    if env.get("NEON_PROJECT_ID") != PROJECT_ID or env.get("NEON_BRANCH_ID") != BRANCH_ID:
        raise ShadowLoggerError("Production Neon project/branch environment mismatch")
    if env.get("V17_SOURCE_BRANCH_ID") != SOURCE_BRANCH:
        raise ShadowLoggerError("Live collector source branch mismatch")
    if env.get("V17_TARGET_READ_BRANCH_ID") != BRANCH_ID:
        raise ShadowLoggerError("Production target read branch mismatch")
    if TARGET_HOST is None:
        raise ShadowLoggerError("No unique pinned host exists for the configured target branch")

    validate_target_environment(env)
    with _connect_ro(env.get("V17_SOURCE_DATABASE_URL"), SOURCE_HOST, "Live collector source") as source, \
         _connect_ro(env.get("V17_TARGET_READONLY_DATABASE_URL"), TARGET_HOST, "Production target") as target:
        state = _load_state(target)
        start = state["shadow_started_at"].astimezone(timezone.utc)
        cursor = state["last_processed_candle_open"]
        query_from = (cursor.astimezone(timezone.utc) - CANDLE) if cursor else (start - 2 * CANDLE)
        price_rows = _load_price_rows(source, query_from, now)
        oi_rows = _load_oi_rows(source, query_from, now)

        # Seed previous candle context, but process only candles after the durable cursor
        # and strictly after the approved fresh 0.0R shadow start.
        oi_by_open = {r["candle_time"]: r for r in oi_rows}
        processed = 0
        entries = 0
        exits = 0
        previous_by_session = {}
        closes_by_session = {}
        opening_oi_by_session = {}

        with psycopg.connect(env["DATABASE_URL"], sslmode="require", row_factory=dict_row) as writer:
            identity = verify_database_identity(writer)
            if identity["branch_id"] != BRANCH_ID or identity["current_user"] != DATABASE_ROLE:
                raise ShadowLoggerError("Production writer identity mismatch")

            for row in price_rows:
                candle_open = row["candle_time"].astimezone(timezone.utc)
                candle_close = candle_open + CANDLE
                session_date = candle_open.date()
                session_key = session_date.isoformat()
                previous = previous_by_session.get(session_key)

                # Keep the last source candle as causal context, even when it is not
                # eligible for processing because it predates the shadow start/cursor.
                should_process = candle_close > start and (cursor is None or candle_open > cursor)
                if not should_process:
                    previous_by_session[session_key] = row
                    closes_by_session.setdefault(session_key, []).append(float(row["close_value"]))
                    continue

                if previous is None:
                    # Recover the immediately preceding same-session candle if the query
                    # began at the first eligible bar; otherwise do not invent a setup.
                    previous_by_session[session_key] = row
                    closes_by_session.setdefault(session_key, []).append(float(row["close_value"]))
                    with writer.transaction():
                        _advance_cursor(writer, candle_open)
                    cursor = candle_open
                    processed += 1
                    continue

                previous_open = previous["candle_time"].astimezone(timezone.utc)
                contiguous = candle_open - previous_open == CANDLE
                current = {
                    "open": float(row["open_value"]), "high": float(row["high_value"]),
                    "low": float(row["low_value"]), "close": float(row["close_value"]),
                }
                closes = closes_by_session.setdefault(session_key, [])
                closes.append(current["close"])
                oi_row = oi_by_open.get(row["candle_time"])
                oi_opening = opening_oi_by_session.get(session_key)
                if session_key not in opening_oi_by_session:
                    # First OI opening value of this UTC/05:30 IST session.
                    with source.cursor() as cur:
                        cur.execute("""SELECT open_value FROM research.delta_candles
                                       WHERE source='delta_india' AND series_type='OI'
                                         AND symbol='OI:BTCUSD' AND resolution='30m'
                                         AND candle_time=%s LIMIT 1""",
                                    (datetime.combine(session_date, datetime.min.time(), tzinfo=timezone.utc),))
                        first_oi = cur.fetchone()
                    opening_oi_by_session[session_key] = first_oi["open_value"] if first_oi else None
                    oi_opening = opening_oi_by_session[session_key]
                oi_entry = oi_row["close_value"] if oi_row else None
                oi_context = classify_oi(oi_opening, oi_entry)
                discovery = "UNKNOWN"
                profile = _prior_profile(target, session_date)
                if profile:
                    discovery = classify_discovery(closes[-2:], float(profile["vah_upper"]), float(profile["val_lower"]))

                open_trade = _open_trade(target)
                exited_this_bar = False
                with writer.transaction():
                    if open_trade:
                        if not contiguous:
                            raise ShadowLoggerError(
                                f"DATA_GAP while a shadow trade is open: {previous_open.isoformat()} -> {candle_open.isoformat()}"
                            )
                        exit_result = evaluate_exit(open_trade, current)
                        if exit_result is None and candle_open.hour == 23 and candle_open.minute == 30:
                            exit_result = session_end_exit(open_trade, current)
                        if exit_result:
                            exit_payload = {
                                **exit_result,
                                "exit_candle_open": _iso(candle_open),
                                "exit_candle_close": _iso(candle_close),
                                "price_retrieved_at": _iso(row["retrieved_at"]),
                                "cutoff_at": _iso(candle_close),
                                "observation_candle": current,
                            }
                            _record(writer, open_trade["trade_key"], "EXIT", candle_close, exit_payload)
                            exits += 1
                            exited_this_bar = True
                    elif contiguous and profile:
                        signal = build_signal(
                            {"close": float(previous["close_value"])}, current,
                            float(profile["vah_upper"]), float(profile["val_lower"]),
                        )
                        if signal:
                            close_key = _iso(candle_close)
                            trade_key = deterministic_trade_key(signal, "BTCUSD", close_key)
                            entry_payload = {
                                "session_date": session_key, "symbol": "BTCUSD",
                                "pattern": signal.pattern, "side": signal.side,
                                "signal_candle_open": _iso(candle_open),
                                "signal_candle_close": close_key,
                                "entry_price": signal.entry_price, "stop_price": signal.stop_price,
                                "target_price": signal.target_price, "risk_points": signal.risk_points,
                                "buffer_points": signal.buffer_points,
                                "prior_profile_id": str(profile["profile_id"]),
                                "prior_vah_upper": signal.prior_vah_upper,
                                "prior_val_lower": signal.prior_val_lower,
                                "discovery_state": discovery,
                                **oi_context,
                                "price_retrieved_at": _iso(row["retrieved_at"]),
                                "oi_retrieved_at": _iso(oi_row["retrieved_at"]) if oi_row else None,
                                "entry_cutoff_at": close_key,
                                "observation_candle_open": _iso(candle_open),
                                "observation_candle_close": close_key,
                                "oi_units": "BTC" if oi_row else None,
                                "oi_observation_cutoff": close_key,
                            }
                            _record(writer, trade_key, "ENTRY", candle_close, entry_payload)
                            entries += 1

                    _advance_cursor(writer, candle_open)
                cursor = candle_open
                processed += 1
                previous_by_session[session_key] = row

        return {
            "status": "OK", "mode": "SHADOW_ONLY", "strategy_version": "BTC_PLAYBOOK_V1.3",
            "shadow_start": _iso(start), "starting_realized_r": float(state["starting_realized_r"]),
            "source_branch": SOURCE_BRANCH, "target_branch": BRANCH_ID,
            "processed_candles": processed, "entries": entries, "exits": exits,
            "last_processed_candle_open": _iso(cursor), "writer_identity": identity,
        }


if __name__ == "__main__":
    print(json.dumps(run_shadow(), sort_keys=True, default=str))
