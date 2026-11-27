"""Read-only NIFTY Pattern A research slice over Yahoo 15m candles.

This module never writes to Neon. It opens an explicit READ ONLY transaction,
compares Yahoo-derived 13-bracket profiles with completed V1.7 session rows,
then replays the unchanged Playbook v1.3 build_signal/evaluate_exit functions.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg
import yfinance as yf

from amt_engine.nifty_v17 import (
    EXPECTED_HOST, IST, SYMBOL, aggregate_session, calculate_profile, normalize_yahoo,
)
from amt_engine.playbook_v13 import build_signal, evaluate_exit

DATABASE = "amt_research"
READ_ONLY_ROLE = "amt_dashboard_ro"
ROUND_TRIP_COSTS = (2.0, 3.0)
WINDOWS = (
    ("Morning Open / IB (09:15–11:15 IST)", time(9, 15), time(11, 15)),
    ("Midday (11:15–13:45 IST)", time(11, 15), time(13, 45)),
    ("Afternoon Close (13:45–15:30 IST)", time(13, 45), time(15, 30)),
)
SCENARIOS = (
    ("Raw Pattern A", 0.0, False),
    ("Max 1 trade/day + min stop >= 25 pts", 25.0, True),
    ("Max 1 trade/day + min stop >= 30 pts", 30.0, True),
)


def validate_readonly_url(url: str):
    from urllib.parse import urlparse
    parsed = urlparse(url or "")
    if parsed.scheme not in ("postgres", "postgresql") or parsed.hostname != EXPECTED_HOST:
        raise RuntimeError("Database URL must target the pinned NIFTY production Neon host")
    if parsed.path.lstrip("/") != DATABASE or parsed.username != READ_ONLY_ROLE:
        raise RuntimeError("Database URL must use amt_dashboard_ro on amt_research")
    return parsed


def load_completed_profiles(database_url: str) -> list[dict]:
    """Read profiles inside a transaction explicitly marked READ ONLY."""
    validate_readonly_url(database_url)
    with psycopg.connect(database_url, sslmode="require", autocommit=False) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            identity = conn.execute(
                "SELECT current_database() AS db, current_user AS usr, session_user AS su"
            ).fetchone()
            if tuple(identity) != (DATABASE, READ_ONLY_ROLE, READ_ONLY_ROLE):
                raise RuntimeError("Connected database identity is not the pinned read-only role")
            rows = conn.execute(
                """SELECT session_date, symbol, method_version, row_size,
                          value_area_fraction, expected_brackets, observed_brackets,
                          is_complete, vah, poc, val
                   FROM amt_nifty_v17.sessions
                   WHERE session_date <= DATE '2026-11-27'
                     AND is_complete = TRUE
                   ORDER BY session_date"""
            ).fetchall()
            columns = ("session_date", "symbol", "method_version", "row_size",
                       "value_area_fraction", "expected_brackets", "observed_brackets",
                       "is_complete", "vah", "poc", "val")
            return [dict(zip(columns, row)) for row in rows]


def fetch_yahoo_15m(now: datetime | None = None) -> pd.DataFrame:
    """Fetch Yahoo's currently available 60-day 15m history; no silent fallback."""
    now = (now or datetime.now(IST)).astimezone(IST)
    raw = yf.Ticker(SYMBOL).history(period="60d", interval="15m", auto_adjust=False)
    frame = normalize_yahoo(raw)
    frame = frame[
        frame.timestamp.map(lambda ts: ts.to_pydatetime() + timedelta(minutes=15) <= now)
    ].copy()
    frame = frame[frame.timestamp.map(lambda ts: time(9, 15) <= ts.time() <= time(15, 15))].copy()
    frame["session_date"] = frame.timestamp.dt.date
    return frame.reset_index(drop=True)


def validate_and_match_sessions(frame: pd.DataFrame, profiles: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep only complete 13-bracket sessions whose TPO levels match V1.7."""
    profile_by_date = {r["session_date"]: r for r in profiles}
    matched, excluded = [], []
    for day in sorted(set(frame.session_date)):
        stored = profile_by_date.get(day)
        if stored is None:
            excluded.append({"date": day.isoformat(), "reason": "NO_COMPLETED_V1_7_PROFILE"})
            continue
        if (stored["symbol"] != SYMBOL or stored["method_version"] != "AMT_NIFTY_V1.7"
                or float(stored["row_size"]) != 10.0
                or float(stored["value_area_fraction"]) != 0.70
                or int(stored["expected_brackets"]) != 13
                or int(stored["observed_brackets"]) != 13
                or not stored["is_complete"]):
            excluded.append({"date": day.isoformat(), "reason": "V1_7_PROFILE_METADATA_MISMATCH"})
            continue
        bars, diag = aggregate_session(frame, day)
        if len(bars) != 13 or diag["received_15m"] != 25 or diag["missing_brackets"]:
            excluded.append({"date": day.isoformat(), "reason": "INCOMPLETE_13_BRACKET_SESSION", "diagnostics": diag})
            continue
        calculated = calculate_profile(bars)
        levels = ("vah", "poc", "val")
        if any(not math.isclose(float(calculated[k]), float(stored[k]), abs_tol=1e-8) for k in levels):
            excluded.append({
                "date": day.isoformat(), "reason": "YAHOO_PROFILE_DOES_NOT_MATCH_V1_7",
                "yahoo": {k: calculated[k] for k in levels},
                "stored": {k: float(stored[k]) for k in levels},
            })
            continue
        matched.append({
            "date": day, "bars": bars, "prior_vah": float(stored["vah"]),
            "prior_val": float(stored["val"]), "profile": stored,
        })
    return matched, excluded


def _window_for_entry(entry_close: time) -> str | None:
    for label, start, end in WINDOWS:
        if start < entry_close <= end:
            return label
    return None


def replay_pattern_a(sessions: list[dict]) -> list[dict]:
    """Generate every Pattern A entry, then resolve subsequent OHLC exits."""
    trades = []
    ordered = sorted(sessions, key=lambda x: x["date"])
    for index, session in enumerate(ordered):
        previous_profile = next(
            (x["profile"] for x in reversed(ordered[:index])
             if x["date"] < session["date"]), None
        )
        # Prior completed session can be outside the Yahoo 60-day candle window.
        # It is therefore supplied by the full read-only session profile list.
        prior = session.get("prior_profile") or previous_profile
        if not prior:
            continue
        bars = session["bars"]
        day = session["date"]
        for i in range(1, len(bars)):
            signal = build_signal(bars[i - 1], bars[i], float(prior["vah"]), float(prior["val"]))
            if signal is None or signal.pattern != "A":
                continue
            entry_close = (datetime.combine(day, time(9, 15)) +
                           timedelta(minutes=30 * i + (15 if i == 12 else 30))).time()
            window = _window_for_entry(entry_close)
            if window is None:
                continue
            trade = {
                "date": day.isoformat(), "window": window, "side": signal.side,
                "entry": signal.entry_price, "stop": signal.stop_price,
                "target": signal.target_price, "risk_points": signal.risk_points,
                "entry_bracket": i + 1, "entry_time": entry_close.isoformat(),
            }
            exit_result = None
            for candle in bars[i + 1:]:
                exit_result = evaluate_exit(trade, candle)
                if exit_result:
                    break
            if exit_result is None:
                close = float(bars[-1]["close"])
                pnl_points = (close - signal.entry_price) if signal.side == "LONG" else (signal.entry_price - close)
                exit_result = {
                    "exit_reason": "SESSION_FLAT_15_30",
                    "exit_price": close,
                    "realized_r": pnl_points / signal.risk_points,
                }
            trades.append({**trade, **exit_result})
    return trades


def select_scenario_trades(trades: list[dict], min_stop: float, one_per_day: bool) -> list[dict]:
    eligible = [t for t in trades if t["risk_points"] >= min_stop]
    eligible.sort(key=lambda t: (t["date"], t["entry_time"], t["entry_bracket"]))
    if not one_per_day:
        return eligible
    seen, selected = set(), []
    for trade in eligible:
        if trade["date"] not in seen:
            selected.append(trade)
            seen.add(trade["date"])
    return selected


def summarize(trades: list[dict]) -> dict:
    gross = [float(t["realized_r"]) for t in trades]
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for value in gross:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "trades": len(trades),
        "win_pct": (100.0 * sum(x > 0 for x in gross) / len(gross)) if gross else 0.0,
        "avg_gross_r": (sum(gross) / len(gross)) if gross else 0.0,
        "total_gross_r": sum(gross),
        "max_dd_r": max_dd,
        "costs": {
            str(cost): {
                "total_net_r": sum(float(t["realized_r"]) - cost / float(t["risk_points"]) for t in trades),
                "avg_net_r": (sum(float(t["realized_r"]) - cost / float(t["risk_points"]) for t in trades) / len(trades)) if trades else 0.0,
                "total_cost_r": sum(cost / float(t["risk_points"]) for t in trades),
            } for cost in ROUND_TRIP_COSTS
        },
    }


def build_report(sessions: list[dict], trades: list[dict], excluded: list[dict]) -> dict:
    rows = []
    for scenario_name, min_stop, one_per_day in SCENARIOS:
        selected = select_scenario_trades(trades, min_stop, one_per_day)
        for window, _, _ in WINDOWS:
            slice_trades = [t for t in selected if t["window"] == window]
            rows.append({"scenario": scenario_name, "window": window, **summarize(slice_trades)})
        rows.append({"scenario": scenario_name, "window": "ALL WINDOWS", **summarize(selected)})
    dates = [s["date"] for s in sessions]
    return {
        "source": SYMBOL, "period_requested_through": "2026-11-27",
        "included_session_count": len(sessions),
        "first_included_session": dates[0].isoformat() if dates else None,
        "last_included_session": dates[-1].isoformat() if dates else None,
        "excluded_session_count": len(excluded), "excluded_sessions": excluded,
        "method": {
            "signal": "amt_engine.playbook_v13.build_signal; Pattern A only",
            "buffer": "5% of prior completed session VA width",
            "target": "2R", "entry": "completed bracket close",
            "ambiguity": "stop-first via evaluate_exit",
            "session_flat": "15:30 IST close",
            "scenarios": list(SCENARIOS),
            "round_trip_cost_points": list(ROUND_TRIP_COSTS),
            "cost_note": "Fixed point costs are applied per trade as cost_points / initial stop risk points; not a broker-specific fee quote.",
        },
        "results": rows,
    }


def run_research(database_url: str, frame: pd.DataFrame | None = None) -> dict:
    profiles = load_completed_profiles(database_url)
    frame = frame if frame is not None else fetch_yahoo_15m()
    matched, excluded = validate_and_match_sessions(frame, profiles)
    if not matched:
        raise RuntimeError("No Yahoo sessions passed exact 13-bracket and V1.7 profile matching")
    profile_by_date = {r["session_date"]: r for r in profiles}
    for session in matched:
        prior = [r for r in profiles if r["session_date"] < session["date"] and r["is_complete"]]
        session["prior_profile"] = prior[-1] if prior else None
    trades = replay_pattern_a(matched)
    return build_report(matched, trades, excluded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("NIFTY_V17_READONLY_DATABASE_URL"))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("Set NIFTY_V17_READONLY_DATABASE_URL to the amt_dashboard_ro connection string")
    report = run_research(args.database_url)
    rendered = json.dumps(report, indent=2, default=str)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")


if __name__ == "__main__":
    main()
