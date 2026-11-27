#!/usr/bin/env python3
"""Read-only causal sub-session journey slice for BTC Playbook V1.3."""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import math
import os
import sys
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amt_engine.playbook_v13 import build_signal, evaluate_exit

PROJECT = "old-surf-34279165"
TARGET_BRANCH = "br-snowy-water-aog0ilqw"
SOURCE_BRANCH = "br-lingering-grass-ao07mgrx"
TARGET_HOST = "ep-morning-mountain-aopl02wv.c-2.ap-southeast-1.aws.neon.tech"
SOURCE_HOST = "ep-sparkling-queen-aoqgp0mw.c-2.ap-southeast-1.aws.neon.tech"
DB = "amt_research"
ROLE = "amt_dashboard_ro"
SOURCE = "delta_india"
SYMBOL = "BTCUSD"
METHOD = "AMT_ENGINE_V1.7"
START = date(2026, 5, 21)
END = date(2026, 11, 26)
EXCLUDED = {date(2026, 11, 20)}
IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
BAR = timedelta(minutes=30)
ROW_SIZE = 50.0
VALUE_PCT = 0.70
TAKER = 0.0005
MAKER = 0.0002
GST = 1.18


class ResearchError(RuntimeError):
    pass


def session_start(d: date) -> datetime:
    return datetime.combine(d, time(5, 30), tzinfo=IST).astimezone(UTC)


def approved_dates() -> list[date]:
    return [START + timedelta(days=i) for i in range((END - START).days + 1)
            if START + timedelta(days=i) not in EXCLUDED]


def connect_ro(url: str | None, expected_host: str, label: str):
    import psycopg
    from psycopg.rows import dict_row
    parsed = urlparse(url or "")
    if parsed.scheme not in ("postgres", "postgresql") or parsed.hostname != expected_host:
        raise ResearchError(f"{label}: connection URL does not match the pinned read-only branch host")
    conn = psycopg.connect(url, sslmode="require", row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SELECT current_database() AS db, current_user AS usr, session_user AS su")
            identity = cur.fetchone()
        if (identity["db"], identity["usr"], identity["su"]) != (DB, ROLE, ROLE):
            raise ResearchError(f"{label}: expected database={DB}, current_user=session_user={ROLE}")
        return conn
    except Exception:
        conn.close()
        raise


def read_candles(conn) -> dict[datetime, dict]:
    # Includes the approved 189 sessions and Nov 20 raw bars for exit/context
    # continuity. No May 20 warm-up rows exist in this source branch.
    begin = session_start(START - timedelta(days=1))
    finish = session_start(END + timedelta(days=1))
    with conn.cursor() as cur:
        cur.execute(
            """SELECT candle_time, open_value, high_value, low_value, close_value
                 FROM research.delta_candles
                WHERE source=%s AND series_type='PRICE' AND symbol=%s
                  AND resolution='30m' AND candle_time >= %s AND candle_time < %s
                ORDER BY candle_time""",
            (SOURCE, SYMBOL, begin, finish),
        )
        rows = cur.fetchall()
    candles = {}
    for row in rows:
        ts = row["candle_time"].astimezone(UTC)
        vals = (row["open_value"], row["high_value"], row["low_value"], row["close_value"])
        if any(v is None for v in vals):
            raise ResearchError(f"{ts}: source candle has a null OHLC field")
        if ts in candles:
            raise ResearchError(f"{ts}: duplicate candle timestamp")
        o, h, l, c = map(float, vals)
        if h < max(o, c, l) or l > min(o, c, h):
            raise ResearchError(f"{ts}: invalid OHLC ordering")
        candles[ts] = {"timestamp": ts, "open": o, "high": h, "low": l, "close": c}

    expected_count = 189 * 48
    in_scope = [ts for ts in candles if START <= ts.date() <= END and ts.date() not in EXCLUDED]
    if len(in_scope) != expected_count:
        raise ResearchError(f"Expected 9,072 in-scope 30m candles; found {len(in_scope)}")
    for d in approved_dates():
        expected = [session_start(d) + BAR * i for i in range(48)]
        if any(ts not in candles for ts in expected):
            missing = next(ts for ts in expected if ts not in candles)
            raise ResearchError(f"{d}: missing approved-session candle {missing.isoformat()}")
    return candles


def calculate_tpo(bars: list[dict]) -> tuple[float, float, float] | None:
    """Exact btc_live_dashboard.py calculate_tpo(): $50 rows, 70% value area."""
    if not bars:
        return None
    high = max(x["high"] for x in bars)
    low = min(x["low"] for x in bars)
    if high - low <= 0:
        return None
    base_bucket = math.floor(low / ROW_SIZE)
    num_buckets = math.floor(high / ROW_SIZE) - base_bucket + 1
    tpo = [0] * num_buckets
    for bar in bars:
        lo_idx = max(0, math.floor(bar["low"] / ROW_SIZE) - base_bucket)
        hi_idx = min(num_buckets - 1, math.floor(bar["high"] / ROW_SIZE) - base_bucket)
        for idx in range(lo_idx, hi_idx + 1):
            tpo[idx] += 1
    max_val = max(tpo)
    tied = [i for i, v in enumerate(tpo) if v == max_val]
    if len(tied) > 1:
        midpoint = (num_buckets - 1) / 2.0
        poc_idx = min(tied, key=lambda i: abs(i - midpoint))
    else:
        poc_idx = tied[0]
    target = math.ceil(sum(tpo) * VALUE_PCT)
    covered = tpo[poc_idx]
    up = dn = poc_idx
    while covered < target:
        can_down, can_up = dn > 0, up < num_buckets - 1
        if not can_down and not can_up:
            break
        down_count = tpo[dn - 1] if can_down else -1
        up_count = tpo[up + 1] if can_up else -1
        if up_count > down_count:
            up += 1
            covered += up_count
        elif down_count > up_count:
            dn -= 1
            covered += down_count
        else:
            if can_down:
                dn -= 1
                covered += down_count
            if covered < target and can_up:
                up += 1
                covered += up_count
    vah = (base_bucket + up) * ROW_SIZE + ROW_SIZE / 2
    val = (base_bucket + dn) * ROW_SIZE + ROW_SIZE / 2
    poc = (base_bucket + poc_idx) * ROW_SIZE + ROW_SIZE / 2
    return vah, val, poc


def macro_bias(close: float, high: float, low: float, ref_value: tuple[float, float] | None) -> str:
    if ref_value is None:
        return "N/A"
    ref_vah, ref_val = ref_value
    if close > ref_vah:
        return "Bullish"
    if close < ref_val:
        return "Bearish"
    if high > ref_vah and close < ref_vah:
        return "Mixed"  # dashboard Bull Trap
    if low < ref_val and close > ref_val:
        return "Mixed"  # dashboard Bear Trap
    return "Balanced"


def micro_bias(close: float, value: tuple[float, float, float] | None) -> str:
    if value is None:
        return "N/A"
    vah, val, _ = value
    if close > vah:
        return "Bullish"  # dashboard Strong Close
    if close < val:
        return "Bearish"  # dashboard Weak Close
    return "Balanced"  # dashboard Balanced (Inside Value)


def session_window(ts_open: datetime) -> tuple[str, datetime, datetime]:
    local = ts_open.astimezone(IST)
    d = local.date()
    t = local.time().replace(tzinfo=None)
    if time(1, 30) <= t < time(5, 30):
        start = datetime.combine(d, time(1, 30), IST)
        end = datetime.combine(d, time(5, 30), IST)
        return "Prior US Overnight", start.astimezone(UTC), end.astimezone(UTC)
    if time(5, 30) <= t < time(13, 30):
        start = datetime.combine(d, time(5, 30), IST)
        end = datetime.combine(d, time(13, 30), IST)
        return "Asia", start.astimezone(UTC), end.astimezone(UTC)
    if time(13, 30) <= t < time(17, 30):
        start = datetime.combine(d, time(13, 30), IST)
        end = datetime.combine(d, time(17, 30), IST)
        return "Europe", start.astimezone(UTC), end.astimezone(UTC)
    start_date = d if t >= time(17, 30) else d - timedelta(days=1)
    start = datetime.combine(start_date, time(17, 30), IST)
    end = start + timedelta(hours=8)
    return "US Cash", start.astimezone(UTC), end.astimezone(UTC)


def make_session_context(candles: dict[datetime, dict]) -> dict[tuple[str, datetime], dict]:
    """Build fully completed session summaries and their causal dashboard biases."""
    ordered = sorted(candles)
    first = ordered[0]
    last = ordered[-1]
    first_local = first.astimezone(IST).date() - timedelta(days=1)
    last_local = last.astimezone(IST).date() + timedelta(days=1)
    summaries = {}
    for day_offset in range((last_local - first_local).days + 1):
        d = first_local + timedelta(days=day_offset)
        specs = [
            ("Prior US Overnight", datetime.combine(d, time(1, 30), IST), datetime.combine(d, time(5, 30), IST)),
            ("Asia", datetime.combine(d, time(5, 30), IST), datetime.combine(d, time(13, 30), IST)),
            ("Europe", datetime.combine(d, time(13, 30), IST), datetime.combine(d, time(17, 30), IST)),
            ("US Cash", datetime.combine(d, time(17, 30), IST), datetime.combine(d + timedelta(days=1), time(1, 30), IST)),
        ]
        for name, start_local, end_local in specs:
            start, end = start_local.astimezone(UTC), end_local.astimezone(UTC)
            bars = [candles[ts] for ts in ordered if start <= ts < end]
            if not bars:
                continue
            expected_n = int((end - start) / BAR)
            if len(bars) != expected_n or [x["timestamp"] for x in bars] != [start + BAR * i for i in range(expected_n)]:
                continue
            value = calculate_tpo(bars)
            if value is None:
                continue
            close = bars[-1]["close"]
            high = max(x["high"] for x in bars)
            low = min(x["low"] for x in bars)
            # Ordinary sessions use the previous complete AMT-cycle TPO value.
            # The overnight special case uses the cycle two dates earlier,
            # matching calculate_session_journey()'s 48h/24h reference window.
            ref_day = d - timedelta(days=2) if name == "Prior US Overnight" else d - timedelta(days=1)
            ref_start = session_start(ref_day)
            ref_bars = [candles.get(ref_start + BAR * i) for i in range(48)]
            ref_value = None
            if all(x is not None for x in ref_bars):
                ref_value = calculate_tpo(ref_bars)
                if ref_value is not None:
                    ref_value = (ref_value[0], ref_value[1])
            summaries[(name, start)] = {
                "name": name, "start": start, "end": end,
                "vah": value[0], "val": value[1], "poc": value[2],
                "macro": macro_bias(close, high, low, ref_value),
                "micro": micro_bias(close, value),
            }
    return summaries


def latest_completed_context(ts_open: datetime, summaries: dict) -> dict | None:
    # Only sessions ending at or before the entry candle OPEN are admissible.
    eligible = [s for s in summaries.values() if s["end"] <= ts_open]
    return max(eligible, key=lambda s: s["end"]) if eligible else None


def fee_r(entry: float, exit_price: float, risk: float, entry_rate: float) -> float:
    if risk <= 0:
        raise ResearchError("Non-positive risk encountered in fee calculation")
    return ((entry * entry_rate + exit_price * TAKER) * GST) / risk


def drawdown(net_returns: list[float]) -> float:
    equity = peak = max_dd = 0.0
    for value in net_returns:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def metrics(trades: list[dict]) -> tuple[int, float, float, float, float, float]:
    ordered = sorted(trades, key=lambda t: t["entry_time"])
    if not ordered:
        return 0, 0.0, 0.0, 0.0, 0.0, 0.0
    gross = [t["gross_r"] for t in ordered]
    net_tt = [t["gross_r"] - t["fee_tt"] for t in ordered]
    net_mt = [t["gross_r"] - t["fee_mt"] for t in ordered]
    return (len(ordered), 100.0 * sum(x > 0 for x in gross) / len(ordered),
            sum(gross) / len(gross), sum(net_tt), sum(net_mt), drawdown(net_tt))


def print_table(title: str, groups: list[tuple[str, list[dict]]]) -> None:
    print("\n" + title)
    print(f"{'Slice':<39} {'Trades':>6} {'Win %':>8} {'Avg Gross R':>11} {'Net R T/T':>11} {'Net R M/T':>11} {'Max DD R':>10}")
    print("-" * 103)
    for label, rows in groups:
        n, win, avg, tt, mt, dd = metrics(rows)
        print(f"{label:<39} {n:>6d} {win:>8.2f} {avg:>11.3f} {tt:>11.3f} {mt:>11.3f} {dd:>10.3f}")


def replay_trades(profiles: dict, candles: dict, summaries: dict) -> tuple[list[dict], int, int]:
    ordered_times = sorted(candles)
    ordered_bars = [candles[t] for t in ordered_times]
    index_by_time = {ts: i for i, ts in enumerate(ordered_times)}
    trades = []
    unresolved = 0
    no_context = 0
    for d in sorted(profiles):
        start = session_start(d)
        day_bars = [candles[start + BAR * i] for i in range(48)]
        for i, current in enumerate(day_bars):
            current_ts = current["timestamp"]
            if i:
                previous = day_bars[i - 1]
            else:
                previous = candles.get(current_ts - BAR)
                if previous is None:
                    continue
            # V1.3 entries retain the approved V1.7 prior-session VAH/VAL.
            vah = profiles[d]["vah"]
            val = profiles[d]["val"]
            signal = build_signal(previous, current, vah, val)
            if signal is None:
                continue
            window, _, _ = session_window(current_ts)
            context = latest_completed_context(current_ts, summaries)
            outcome = None
            for future in ordered_bars[index_by_time[current_ts] + 1:]:
                outcome = evaluate_exit({"side": signal.side, "stop_price": signal.stop_price,
                                         "target_price": signal.target_price}, future)
                if outcome is not None:
                    break
            if outcome is None:
                unresolved += 1
                continue
            if context is None:
                no_context += 1
            exit_price = float(outcome["exit_price"])
            trades.append({
                "entry_time": current_ts + BAR, "window": window, "pattern": signal.pattern,
                "side": signal.side, "gross_r": float(outcome["realized_r"]),
                "fee_tt": fee_r(signal.entry_price, exit_price, signal.risk_points, TAKER),
                "fee_mt": fee_r(signal.entry_price, exit_price, signal.risk_points, MAKER),
                "context_session": context["name"] if context else "N/A",
                "macro": context["macro"] if context else "N/A",
                "micro": context["micro"] if context else "N/A",
                "context_vah": context["vah"] if context else None,
                "context_val": context["val"] if context else None,
                "context_poc": context["poc"] if context else None,
            })
    return trades, unresolved, no_context


def read_profiles_with_value(conn) -> dict[date, dict]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT session_date, profile_id, profile_status, is_complete,
                      expected_bars, observed_bars, vah_upper, val_lower
                 FROM amt_engine_v17.session_profiles
                WHERE method_version=%s AND source=%s AND symbol=%s
                  AND session_date BETWEEN %s AND %s
                ORDER BY session_date""",
            (METHOD, SOURCE, SYMBOL, START, END),
        )
        rows = cur.fetchall()
    profiles = {}
    for row in rows:
        d = row["session_date"]
        if d in EXCLUDED:
            continue
        if (not row["is_complete"] or row["profile_status"] != "COMPLETE"
                or row["expected_bars"] != 48 or row["observed_bars"] != 48):
            raise ResearchError(f"{d}: V1.7 profile is not a complete 48-candle session")
        if row["vah_upper"] is None or row["val_lower"] is None or row["vah_upper"] <= row["val_lower"]:
            raise ResearchError(f"{d}: invalid V1.7 prior value boundaries")
        profiles[d] = {"profile_id": str(row["profile_id"]),
                       "vah": float(row["vah_upper"]), "val": float(row["val_lower"])}
    if sorted(profiles) != approved_dates() or len(profiles) != 189:
        raise ResearchError(f"Expected exactly 189 approved V1.7 profiles; found {len(profiles)}")
    return profiles


def self_test() -> None:
    bars = [
        {"open": 100.0, "high": 149.0, "low": 101.0, "close": 120.0},
        {"open": 120.0, "high": 199.0, "low": 101.0, "close": 180.0},
        {"open": 180.0, "high": 249.0, "low": 151.0, "close": 220.0},
    ]
    assert calculate_tpo(bars) == (175.0, 125.0, 175.0)
    assert macro_bias(151, 160, 90, (150, 100)) == "Bullish"
    assert macro_bias(99, 120, 80, (150, 100)) == "Bearish"
    assert macro_bias(120, 155, 110, (150, 100)) == "Mixed"
    assert macro_bias(125, 140, 105, (150, 100)) == "Balanced"
    assert micro_bias(151, (150, 100, 125)) == "Bullish"
    assert micro_bias(99, (150, 100, 125)) == "Bearish"
    assert micro_bias(125, (150, 100, 125)) == "Balanced"
    t0 = datetime(2026, 5, 21, 0, 0, tzinfo=UTC)
    done = {"name": "Asia", "end": t0, "macro": "Bullish", "micro": "Balanced"}
    developing = {"name": "Europe", "end": t0 + BAR, "macro": "Bearish", "micro": "Bearish"}
    assert latest_completed_context(t0, {("Asia", t0): done, ("Europe", t0 + BAR): developing}) is done
    assert session_window(datetime(2026, 5, 21, 20, 0, tzinfo=UTC))[0] == "Prior US Overnight"
    assert session_window(datetime(2026, 5, 21, 0, 0, tzinfo=UTC))[0] == "Asia"
    assert session_window(datetime(2026, 5, 21, 8, 0, tzinfo=UTC))[0] == "Europe"
    assert session_window(datetime(2026, 5, 21, 12, 0, tzinfo=UTC))[0] == "US Cash"
    assert fee_r(100, 110, 10, TAKER) > fee_r(100, 110, 10, MAKER)
    assert metrics([])[0] == 0
    print("OFFLINE SESSION-JOURNEY SELF-TEST PASS")


def run() -> None:
    target_url = os.environ.get("V17_TARGET_READONLY_DATABASE_URL")
    source_url = os.environ.get("V17_SOURCE_READONLY_DATABASE_URL")
    if not target_url or not source_url:
        raise ResearchError("Missing read-only Neon connection secrets")
    with connect_ro(target_url, TARGET_HOST, "V1.7 profile branch") as target, \
            connect_ro(source_url, SOURCE_HOST, "30m candle source branch") as source:
        profiles = read_profiles_with_value(target)
        candles = read_candles(source)

    summaries = make_session_context(candles)
    trades, unresolved, no_context = replay_trades(profiles, candles, summaries)
    print("BTCUSD | Playbook V1.3 | Dashboard Session Journey | 30m | IST")
    print("Approved sample: 21 May–26 Nov 2026; 20 Nov excluded; 189 complete V1.7 sessions.")
    print("In-scope candles: 9,072 (189 × 48). No May 20 warm-up is present; missing first-window context is N/A.")
    print("Nov 20 is excluded from trade entries; its complete raw candles may inform later causal sub-session context and forward exits.")
    print("Session TPO: exact dashboard algorithm, $50 rows, 70% value area, dashboard POC tie-break.")
    print("Causal rule: use the latest complete sub-session whose end is <= the entry candle OPEN.")
    print("Macro: previous complete AMT-cycle value; Bull/Bear traps grouped as Mixed. Micro: close vs completed sub-session VA.")
    print("Entries/exits: exact amt_engine.playbook_v13 build_signal/evaluate_exit; completed candle; stop-first ambiguity.")
    print("Fees: Delta India BTCUSD taker 0.05%, maker 0.02%, 18% GST on both legs.")
    print("Win % is positive gross-R trades; Max DD is chronological cumulative Taker/Taker + GST net R.")

    for pattern in ("A", "B"):
        print_table(f"PATTERN {pattern} — MACRO BIAS AT ENTRY (LATEST COMPLETED SUB-SESSION)", [
            (label, [t for t in trades if t["pattern"] == pattern and t["macro"] == key])
            for label, key in (("Bullish", "Bullish"), ("Bearish", "Bearish"),
                               ("Balanced", "Balanced"), ("Mixed / Trap", "Mixed"), ("N/A", "N/A"))
        ])
        print_table(f"PATTERN {pattern} — MICRO BIAS AT ENTRY (LATEST COMPLETED SUB-SESSION)", [
            (label, [t for t in trades if t["pattern"] == pattern and t["micro"] == key])
            for label, key in (("Bullish", "Bullish"), ("Bearish", "Bearish"),
                               ("Balanced / Inside Value", "Balanced"), ("N/A", "N/A"))
        ])
        print_table(f"PATTERN {pattern} — TRADE SUB-SESSION WINDOW", [
            (label, [t for t in trades if t["pattern"] == pattern and t["window"] == key])
            for label, key in (("Asia", "Asia"), ("Europe", "Europe"),
                               ("US Cash", "US Cash"), ("Prior US Overnight", "Prior US Overnight"))
        ])

    print_table("ALL PATTERNS — COMBINED CHECK", [("All completed trades", trades)])
    print(f"\nCompleted trades: {len(trades)} | Unresolved signals excluded: {unresolved} | No prior completed sub-session context: {no_context}")
    if len(trades) != 1218:
        raise ResearchError(f"Trade parity guard failed: expected the known 1,218 V1.3 completed trades; found {len(trades)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run offline tests without Neon connections")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        else:
            run()
        return 0
    except Exception as exc:
        print(f"Research stopped safely: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
