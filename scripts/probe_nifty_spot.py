#!/usr/bin/env python3
"""Read-only NIFTY 50 spot intraday source probe. No database or service writes."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

IST = ZoneInfo("Asia/Kolkata")
SYMBOL = "^NSEI"
NSE_SYMBOL = "NIFTY 50"
NSE_TOKEN = "26000"  # NSE index token used by the public charting feed
LOOKBACK_DAYS = 60
ROW_SIZE = 10.0
VALUE_AREA_FRACTION = 0.70
BAR_STARTS = [datetime.strptime("09:15", "%H:%M").time()]
BAR_STARTS += [
    (datetime.strptime("09:15", "%H:%M") + timedelta(minutes=15 * i)).time()
    for i in range(1, 25)
]
EXPECTED_15M = [datetime.strptime("09:15", "%H:%M").time()]
EXPECTED_15M += [
    (datetime.strptime("09:15", "%H:%M") + timedelta(minutes=15 * i)).time()
    for i in range(1, 25)
]


def normalize_frame(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise RuntimeError(f"{source}: returned no rows")
    df = frame.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    aliases = {"adj_close": "close", "datetime": "timestamp", "date": "timestamp"}
    df = df.rename(columns=aliases)
    if "timestamp" not in df.columns:
        df = df.reset_index()
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
        df = df.rename(columns=aliases)
        if "timestamp" not in df.columns:
            df = df.rename(columns={df.columns[0]: "timestamp"})
    required = ["open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"{source}: missing OHLC columns {missing}; got {list(df.columns)}")
    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    if getattr(ts.dt, "tz", None) is None:
        # Yahoo returns UTC-aware timestamps; OpenChart may return local-naive timestamps.
        ts = ts.dt.tz_localize(IST)
    else:
        ts = ts.dt.tz_convert(IST)
    df["timestamp"] = ts
    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["timestamp"] + required).copy()

    # OpenChart examples use end labels such as 15:14:59. Convert those to
    # their 15-minute interval start; Yahoo normally uses interval-start labels.
    adjusted = []
    for ts in df["timestamp"]:
        if ts.second >= 50 and ts.minute in (14, 29, 44, 59):
            ts = ts - pd.Timedelta(minutes=15)
        adjusted.append(ts.floor("min"))
    df["timestamp"] = adjusted
    df["timestamp"] = df["timestamp"].dt.floor("15min")
    df = df.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")
    return df[["timestamp", "open", "high", "low", "close"]].reset_index(drop=True)


def fetch_yahoo(start: datetime, end: datetime) -> pd.DataFrame:
    raw = yf.download(
        SYMBOL, start=start.date().isoformat(), end=(end.date() + timedelta(days=1)).isoformat(),
        interval="15m", auto_adjust=False, prepost=False, progress=False, threads=False
    )
    if raw is None or raw.empty:
        raise RuntimeError("Yahoo returned no rows for ^NSEI 15m")
    raw = raw.reset_index()
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    return normalize_frame(raw, "Yahoo")


def fetch_nse(start: datetime, end: datetime) -> pd.DataFrame:
    # OpenChart wraps NSE's publicly accessible charting endpoints; it does not
    # represent an official NSE-supported API or imply an availability SLA.
    from openchart import NSEData
    client = NSEData()
    raw = client.historical(
        NSE_SYMBOL, "IDX",
        start=start, end=end, interval="15m"
    )
    if raw is None or raw.empty:
        raise RuntimeError("NSE chart API/OpenChart returned no rows for NIFTY 50 15m")
    raw = raw.reset_index()
    if "Timestamp" in raw.columns:
        raw = raw.rename(columns={"Timestamp": "timestamp"})
    elif "timestamp" not in [str(c).lower() for c in raw.columns]:
        raw = raw.rename(columns={raw.columns[0]: "timestamp"})
    return normalize_frame(raw, "NSE chart API")


def aggregate_13_brackets(df: pd.DataFrame) -> tuple[dict, dict]:
    """Aggregate 15m candles into 12x30m + final 15m exchange brackets."""
    work = df.copy()
    work["session_date"] = work["timestamp"].dt.date
    sessions: dict = {}
    diagnostics: dict = {}
    today = datetime.now(IST).date()
    for day, group in work.groupby("session_date"):
        # Only completed exchange sessions; never include today's developing session.
        if day >= today:
            continue
        by_start = {row.timestamp.time(): row for row in group.itertuples(index=False)}
        bars = []
        missing = []
        for i in range(13):
            start_min = 9 * 60 + 15 + i * 30
            end_min = min(start_min + 30, 15 * 60 + 30)
            t0 = (datetime.combine(day, datetime.min.time()) + timedelta(minutes=start_min)).time()
            t1 = (datetime.combine(day, datetime.min.time()) + timedelta(minutes=(start_min + 15))).time()
            needed = [t0] if i == 12 else [t0, t1]
            rows = [by_start.get(t) for t in needed]
            if any(r is None for r in rows):
                missing.append(f"{t0.strftime('%H:%M')}-{(datetime.combine(day, datetime.min.time()) + timedelta(minutes=end_min)).strftime('%H:%M')}")
                continue
            bars.append({
                "date": day, "bracket": i + 1,
                "start": t0.strftime("%H:%M"),
                "open": float(rows[0].open),
                "high": max(float(r.high) for r in rows),
                "low": min(float(r.low) for r in rows),
                "close": float(rows[-1].close),
            })
        diagnostics[day] = {"received_15m": len(group), "brackets": len(bars), "missing": missing}
        if len(bars) == 13 and not missing:
            sessions[day] = pd.DataFrame(bars)
    return sessions, diagnostics


def profile(bars: pd.DataFrame) -> dict:
    counts: dict[int, int] = {}
    for row in bars.itertuples(index=False):
        lo = int(float(row.low) // ROW_SIZE)
        hi = int(float(row.high) // ROW_SIZE)
        for level in range(lo, hi + 1):
            counts[level] = counts.get(level, 0) + 1
    if not counts:
        raise RuntimeError("Cannot calculate profile with no TPO rows")
    poc = max(counts, key=lambda k: (counts[k], -k))  # lower row wins a POC tie
    total = sum(counts.values())
    target = total * VALUE_AREA_FRACTION
    included = {poc}
    covered = counts[poc]
    low, high = poc, poc
    while covered < target:
        below, above = low - 1, high + 1
        cb, ca = counts.get(below, 0), counts.get(above, 0)
        if cb == 0 and ca == 0:
            break
        # Expand toward the larger adjacent TPO count; tie resolves downward.
        if cb >= ca and cb > 0:
            included.add(below); low = below; covered += cb
        elif ca > 0:
            included.add(above); high = above; covered += ca
    return {
        "VAH": (max(included) + 1) * ROW_SIZE,
        "POC": (poc + 0.5) * ROW_SIZE,
        "VAL": min(included) * ROW_SIZE,
        "high": float(bars["high"].max()),
        "low": float(bars["low"].min()),
        "close": float(bars.iloc[-1]["close"]),
        "bars": len(bars),
    }


def classify_rows(sessions: dict) -> list[dict]:
    dates = sorted(sessions)
    profiles = {d: profile(sessions[d]) for d in dates}
    out = []
    for i, day in enumerate(dates):
        p = profiles[day]
        close_loc = "ABOVE VAH" if p["close"] > p["VAH"] else (
            "BELOW VAL" if p["close"] < p["VAL"] else "INSIDE VALUE"
        )
        migration = "FIRST SESSION"
        swing = "FIRST SESSION"
        if i:
            prev = profiles[dates[i - 1]]
            if p["VAH"] > prev["VAH"] and p["POC"] > prev["POC"] and p["VAL"] > prev["VAL"]:
                migration = "VALUE UP"
            elif p["VAH"] < prev["VAH"] and p["POC"] < prev["POC"] and p["VAL"] < prev["VAL"]:
                migration = "VALUE DOWN"
            else:
                migration = "VALUE OVERLAP / MIXED"
            hi = "HH" if p["high"] > prev["high"] else ("LH" if p["high"] < prev["high"] else "EQH")
            lo = "HL" if p["low"] > prev["low"] else ("LL" if p["low"] < prev["low"] else "EQL")
            swing = f"{hi}/{lo}"
        out.append({
            "Session Date": day.isoformat(), "Bars": p["bars"],
            "VAH": f'{p["VAH"]:.0f}', "POC": f'{p["POC"]:.0f}', "VAL": f'{p["VAL"]:.0f}',
            "Close Location": close_loc, "Value Migration": migration,
            "Swing Structure HH/HL vs LL/LH": swing,
        })
    return out


def print_table(title: str, rows: list[dict]) -> None:
    print(f"\n{title}")
    if not rows:
        print("(no complete sessions)")
        return
    cols = list(rows[0])
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print(" | ".join(c.ljust(widths[c]) for c in cols))
    print("-+-".join("-" * widths[c] for c in cols))
    for r in rows:
        print(" | ".join(str(r[c]).ljust(widths[c]) for c in cols))


def main() -> int:
    now = datetime.now(IST)
    start = now - timedelta(days=LOOKBACK_DAYS)
    print("NIFTY 50 SPOT — READ-ONLY SOURCE PROBE")
    print(f"Run time: {now.isoformat()} | Window: {start.date()} to {now.date()} | interval: 15m")
    print("Aggregation: 09:15 IST anchored; 12 x 30m + final 15m (15:15–15:30)")
    print("TPO: 10-point rows; each aggregated bracket contributes one TPO to every inclusive floor(low/10)..floor(high/10) row; VA=70%.")
    results = {}
    for name, fetch in (("Yahoo ^NSEI", fetch_yahoo), ("NSE chart API / OpenChart", fetch_nse)):
        print(f"\n=== {name} ===")
        try:
            frame = fetch(start, now)
            sessions, diag = aggregate_13_brackets(frame)
            results[name] = sessions
            print(f"Raw 15m rows: {len(frame)} | raw date span: {frame.timestamp.min()} .. {frame.timestamp.max()}")
            print(f"Trading dates received: {len(diag)} | complete 13-bracket sessions: {len(sessions)}")
            for d in sorted(diag)[-10:]:
                x = diag[d]
                if x["brackets"] != 13:
                    print(f"INCOMPLETE {d}: 15m_rows={x['received_15m']} complete_brackets={x['brackets']} missing={','.join(x['missing'])}")
            rows = classify_rows(dict(sorted(sessions.items())[-10:]))
            print_table("Last 10 complete sessions — " + name, rows)
        except Exception as exc:
            print(f"SOURCE ERROR: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            results[name] = None

    yahoo, nse = results.get("Yahoo ^NSEI"), results.get("NSE chart API / OpenChart")
    print("\n=== CROSS-SOURCE OHLC COMPARISON ===")
    if yahoo is None or nse is None:
        print("Comparison unavailable: at least one source failed.")
    else:
        common = sorted(set(yahoo) & set(nse))
        compared = discrepancies = 0
        max_abs = {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0}
        examples = []
        for day in common:
            a, b = yahoo[day], nse[day]
            for i in range(13):
                compared += 1
                for col in ("open", "high", "low", "close"):
                    delta = abs(float(a.iloc[i][col]) - float(b.iloc[i][col]))
                    max_abs[col] = max(max_abs[col], delta)
                    if delta > 0.01:
                        discrepancies += 1
                        if len(examples) < 20:
                            examples.append(f"{day} {a.iloc[i]['start']} {col}: Yahoo={a.iloc[i][col]:.2f} NSE={b.iloc[i][col]:.2f} Δ={delta:.2f}")
        print(f"Common complete sessions: {len(common)} | bracket comparisons: {compared} | field discrepancies > ₹0.01: {discrepancies}")
        print("Max absolute difference (₹): " + ", ".join(f"{k}={v:.2f}" for k, v in max_abs.items()))
        if examples:
            print("First discrepancies:")
            for x in examples:
                print("  " + x)
        else:
            print("No OHLC field differences above ₹0.01 in compared brackets.")
    print("\nProbe completed. No database, repository data, or production service writes were performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
