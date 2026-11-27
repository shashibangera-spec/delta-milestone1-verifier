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
NSE_TOKEN = "26000"
LOOKBACK_DAYS = 55
YAHOO_PERIOD = "55d"
ROW_SIZE = 10.0
VALUE_AREA_FRACTION = 0.70
EXPECTED_SESSION_BARS = [
    (datetime.strptime("09:15", "%H:%M") + timedelta(minutes=15 * i)).time()
    for i in range(25)
]


class NSEAccessDenied(RuntimeError):
    """NSE rejected the read-only request, commonly due to cloud-IP restrictions."""


def normalize_frame(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise RuntimeError(f"{source}: returned no rows")
    df = frame.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()].copy()
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
        ts = ts.dt.tz_localize(IST)
    else:
        ts = ts.dt.tz_convert(IST)
    df["timestamp"] = ts
    for col in required:
        col_data = df[col].iloc[:, 0] if isinstance(df[col], pd.DataFrame) else df[col]
        df[col] = pd.to_numeric(col_data, errors="coerce")
    df = df.dropna(subset=["timestamp"] + required).copy()

    # OpenChart commonly labels a 15m candle by its final second (e.g. 09:29:59).
    adjusted = []
    for stamp in df["timestamp"]:
        if stamp.second >= 50 and stamp.minute in (14, 29, 44, 59):
            stamp = stamp - pd.Timedelta(minutes=15)
        adjusted.append(stamp.floor("min"))
    df["timestamp"] = adjusted
    df["timestamp"] = df["timestamp"].dt.floor("15min")
    df = df.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")
    return df[["timestamp", "open", "high", "low", "close"]].reset_index(drop=True)


def fetch_yahoo(start: datetime, end: datetime) -> pd.DataFrame:
    print(f"Yahoo request: symbol={SYMBOL} interval=15m period={YAHOO_PERIOD}")
    raw = yf.Ticker(SYMBOL).history(
        period="55d",
        interval="15m",
        auto_adjust=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"Yahoo returned no rows for {SYMBOL} 15m period={YAHOO_PERIOD}")
    # Newer yfinance releases may still return a MultiIndex for a single ticker.
    # Flatten before reset_index so every OHLC selection is a one-dimensional Series.
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.reset_index()
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    frame = normalize_frame(raw, "Yahoo")
    print(
        "Yahoo exact candle timestamp span (IST): "
        f"oldest={frame.timestamp.min().isoformat()} | "
        f"newest={frame.timestamp.max().isoformat()} | rows={len(frame)}"
    )
    return frame


def fetch_nse(start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch NIFTY 50 15m bars using an explicit NSE homepage cookie handshake."""
    from openchart import NSEData

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Referer": "https://www.nseindia.com/",
    })

    print("NSE cookie handshake: GET https://www.nseindia.com/")
    try:
        handshake = session.get("https://www.nseindia.com/", timeout=20)
        print(
            f"NSE homepage handshake HTTP status={handshake.status_code}; "
            f"cookies_received={len(session.cookies)}"
        )
        if handshake.status_code == 403:
            raise NSEAccessDenied("NSE homepage cookie handshake returned HTTP 403")
        handshake.raise_for_status()
    except NSEAccessDenied:
        raise
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        print(f"NSE homepage handshake failed: HTTP status={status!r}; error={exc}")
        if status == 403:
            raise NSEAccessDenied("NSE homepage cookie handshake returned HTTP 403") from exc
        raise RuntimeError(f"NSE homepage cookie handshake failed (HTTP {status}): {exc}") from exc

    chart_statuses: list[tuple[str, int]] = []

    def log_chart_response(response, *args, **kwargs):
        if "symbolHistoricalData" in response.url or "symbolsDynamic" in response.url:
            chart_statuses.append((response.url, response.status_code))
            print(f"NSE chart API response: HTTP {response.status_code} {response.url}")
        return response

    session.hooks["response"].append(log_chart_response)

    # Reuse the exact session that received the homepage cookies. OpenChart's
    # own _ensure_cookies() is marked complete so it does not replace this session.
    client = NSEData()
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://charting.nseindia.com",
        "Referer": "https://charting.nseindia.com/",
    })
    client.session = session
    client._cookies_set = True

    try:
        raw = client.historical(
            NSE_SYMBOL, "IDX", start=start, end=end, interval="15m"
        )
    except requests.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        print(f"NSE historical chart request failed: HTTP status={status!r}; error={exc}")
        if status == 403:
            raise NSEAccessDenied("NSE historical chart endpoint returned HTTP 403") from exc
        raise
    if raw is None or raw.empty:
        last_status = chart_statuses[-1][1] if chart_statuses else None
        raise RuntimeError(
            "NSE chart API/OpenChart returned no NIFTY 50 15m rows; "
            f"last chart API HTTP status={last_status!r}"
        )
    raw = raw.reset_index()
    if "Timestamp" in raw.columns:
        raw = raw.rename(columns={"Timestamp": "timestamp"})
    elif "timestamp" not in [str(c).lower() for c in raw.columns]:
        raw = raw.rename(columns={raw.columns[0]: "timestamp"})
    frame = normalize_frame(raw, "NSE chart API")
    print(
        "NSE exact candle timestamp span (IST): "
        f"oldest={frame.timestamp.min().isoformat()} | "
        f"newest={frame.timestamp.max().isoformat()} | rows={len(frame)}"
    )
    return frame


def aggregate_13_brackets(df: pd.DataFrame) -> tuple[dict, dict]:
    """Aggregate 15m candles into 12x30m + final 15m exchange brackets."""
    work = df.copy()
    work["session_date"] = work["timestamp"].dt.date
    sessions: dict = {}
    diagnostics: dict = {}
    today = datetime.now(IST).date()
    for day, group in work.groupby("session_date"):
        if day >= today:
            continue
        by_start = {row.timestamp.time(): row for row in group.itertuples(index=False)}
        bars = []
        missing_brackets = []
        missing_candle_starts = []
        for i in range(13):
            start_min = 9 * 60 + 15 + i * 30
            end_min = min(start_min + 30, 15 * 60 + 30)
            t0 = (datetime.combine(day, datetime.min.time()) + timedelta(minutes=start_min)).time()
            t1 = (datetime.combine(day, datetime.min.time()) + timedelta(minutes=start_min + 15)).time()
            needed = [t0] if i == 12 else [t0, t1]
            absent = [t for t in needed if t not in by_start]
            if absent:
                label = (
                    f"{t0.strftime('%H:%M')}-"
                    f"{(datetime.combine(day, datetime.min.time()) + timedelta(minutes=end_min)).strftime('%H:%M')}"
                )
                missing_brackets.append(label)
                missing_candle_starts.extend(t.strftime("%H:%M") for t in absent)
                continue
            rows = [by_start[t] for t in needed]
            bars.append({
                "date": day, "bracket": i + 1, "start": t0.strftime("%H:%M"),
                "open": float(rows[0].open),
                "high": max(float(r.high) for r in rows),
                "low": min(float(r.low) for r in rows),
                "close": float(rows[-1].close),
            })
        diagnostics[day] = {
            "received_15m": len(group),
            "brackets": len(bars),
            "missing_brackets": missing_brackets,
            "missing_candle_starts": missing_candle_starts,
        }
        if len(bars) == 13 and not missing_brackets:
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
    poc = max(counts, key=lambda k: (counts[k], -k))
    target = sum(counts.values()) * VALUE_AREA_FRACTION
    included = {poc}
    covered = counts[poc]
    low, high = poc, poc
    while covered < target:
        below, above = low - 1, high + 1
        cb, ca = counts.get(below, 0), counts.get(above, 0)
        if cb == 0 and ca == 0:
            break
        if cb >= ca and cb > 0:
            included.add(below)
            low = below
            covered += cb
        elif ca > 0:
            included.add(above)
            high = above
            covered += ca
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
    for row in rows:
        print(" | ".join(str(row[c]).ljust(widths[c]) for c in cols))


def print_diagnostics(name: str, diagnostics: dict) -> None:
    print(f"{name} per-session bracket diagnostics:")
    if not diagnostics:
        print("  No dated 15m rows to inspect.")
        return
    for day in sorted(diagnostics):
        item = diagnostics[day]
        status = "COMPLETE" if item["brackets"] == 13 else "INCOMPLETE"
        print(
            f"  {day}: {status}; received_15m={item['received_15m']}; "
            f"complete_brackets={item['brackets']}/13; "
            f"missing_brackets={item['missing_brackets'] or 'none'}; "
            f"missing_15m_starts={item['missing_candle_starts'] or 'none'}"
        )


def main() -> int:
    now = datetime.now(IST)
    start = now - timedelta(days=LOOKBACK_DAYS)
    print("NIFTY 50 SPOT — READ-ONLY SOURCE PROBE")
    print(
        f"Run time: {now.isoformat()} | Yahoo period={YAHOO_PERIOD} "
        f"(calendar lookback={LOOKBACK_DAYS} days; {start.isoformat()} to {now.isoformat()}) | interval: 15m"
    )
    print("Aggregation: 09:15 IST anchored; 12 x 30m + final 15m (15:15–15:30)")
    print("TPO: 10-point rows; each bracket contributes one TPO to every inclusive floor(low/10)..floor(high/10) row; VA=70%.")
    results = {}
    for name, fetch in (("Yahoo ^NSEI", fetch_yahoo), ("NSE chart API / OpenChart", fetch_nse)):
        print(f"\n=== {name} ===")
        try:
            frame = fetch(start, now)
            sessions, diagnostics = aggregate_13_brackets(frame)
            results[name] = sessions
            print(f"Raw 15m rows: {len(frame)}")
            print_diagnostics(name, diagnostics)
            print(f"Complete 13-bracket sessions: {len(sessions)}")
            rows = classify_rows(dict(sorted(sessions.items())[-10:]))
            print_table("Last 10 complete sessions — " + name, rows)
        except NSEAccessDenied as exc:
            print(f"SOURCE SKIP (non-fatal): {exc}")
            results[name] = None
        except Exception as exc:
            print(f"SOURCE ERROR: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            results[name] = None

    yahoo = results.get("Yahoo ^NSEI")
    nse = results.get("NSE chart API / OpenChart")
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
                            examples.append(
                                f"{day} {a.iloc[i]['start']} {col}: "
                                f"Yahoo={a.iloc[i][col]:.2f} NSE={b.iloc[i][col]:.2f} Δ={delta:.2f}"
                            )
        print(
            f"Common complete sessions: {len(common)} | bracket comparisons: {compared} | "
            f"field discrepancies > ₹0.01: {discrepancies}"
        )
        print("Max absolute difference (₹): " + ", ".join(f"{k}={v:.2f}" for k, v in max_abs.items()))
        if examples:
            print("First discrepancies:")
            for example in examples:
                print("  " + example)
        else:
            print("No OHLC field differences above ₹0.01 in compared brackets.")

    total_complete = sum(len(v) for v in results.values() if v is not None)
    failed_sources = [name for name, value in results.items() if value is None]
    print(
        f"\nProbe summary: failed_sources={failed_sources or 'none'}; "
        f"total_source_complete_sessions={total_complete}"
    )
    print("No database, repository data, or production service writes were performed.")
    # Yahoo is the required source for this probe. NSE is a secondary cross-check:
    # its 403 response from GitHub-hosted runners must not invalidate Yahoo profiles.
    if yahoo is not None and len(yahoo) > 0:
        print("SUCCESS: Yahoo ^NSEI produced complete 13-bracket sessions; NSE cross-check is optional.")
        if nse is None:
            print("NSE was unavailable/skipped; retaining Yahoo-only profile output.")
        return 0
    if len(failed_sources) == 2:
        print("FATAL: both data sources failed; returning exit status 1.")
        return 1
    if total_complete == 0:
        print("FATAL: zero complete 13-bracket sessions; returning exit status 1.")
        return 1
    if failed_sources:
        print("WARNING: Yahoo produced no complete sessions; only secondary-source data is available.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
