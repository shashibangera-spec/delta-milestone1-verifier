"""Delta BTC options OI snapshots and descriptive event context.

This module is independent of the PRICE/OI candle transaction and contains
no signal, recommendation, or execution logic.
"""
from __future__ import annotations

import json
import math
import re
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

TICKERS_URL = (
    "https://api.india.delta.exchange/v2/tickers"
    "?contract_types=call_options,put_options&underlying_asset_symbols=BTC"
)
SYMBOL_RE = re.compile(r"^(?P<kind>[CP])-BTC-(?P<strike>\d+)-(?P<expiry>\d{6})$")
MAX_ROWS = 52


def parse_option_symbol(symbol: str) -> dict[str, Any]:
    """Parse Delta option symbol; expiry settles at 12:00 UTC on DDMMYY."""
    match = SYMBOL_RE.fullmatch(str(symbol or ""))
    if not match:
        raise ValueError(f"Invalid BTC option symbol: {symbol!r}")
    expiry = datetime.strptime(match.group("expiry"), "%d%m%y").date()
    kind = "call_options" if match.group("kind") == "C" else "put_options"
    return {"contract_type": kind, "strike_price": float(match.group("strike")),
            "expiry_date": expiry,
            "expiry_ts": datetime.combine(expiry, time(12, 0), tzinfo=timezone.utc)}


def _number(value: Any, field: str, *, required: bool = False) -> float | None:
    if value is None or value == "":
        if required:
            raise ValueError(f"Missing numeric field {field}")
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Non-finite numeric field {field}")
    return result


def normalize_ticker(row: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_option_symbol(row.get("symbol"))
    if row.get("contract_type") not in ("call_options", "put_options"):
        raise ValueError("Unexpected contract_type")
    if row["contract_type"] != parsed["contract_type"]:
        raise ValueError("contract_type does not match option symbol")
    product_id = int(row["product_id"])
    if product_id <= 0:
        raise ValueError("product_id must be positive")
    quotes, greeks = row.get("quotes") or {}, row.get("greeks") or {}
    return {
        "product_id": product_id, "symbol": row["symbol"], **parsed,
        "oi_btc": _number(row.get("oi"), "oi", required=True),
        "oi_usd": _number(row.get("oi_value_usd"), "oi_value_usd"),
        "oi_change_6h_usd": _number(row.get("oi_change_usd_6h"), "oi_change_usd_6h"),
        "mark_iv": _number(quotes.get("mark_iv"), "quotes.mark_iv"),
        "delta": _number(greeks.get("delta"), "greeks.delta"),
        "gamma": _number(greeks.get("gamma"), "greeks.gamma"),
        "volume_btc": _number(row.get("volume"), "volume"),
    }


def select_chain_rows(rows: list[dict[str, Any]], spot_price: float,
                      snapshot_ts: datetime) -> list[dict[str, Any]]:
    """Select nearest two future expiries and ATM +/- six listed strikes.

    Dynamic cap: 13 strikes x two option types x two expiries = 52 rows.
    Missing listings naturally produce fewer rows.
    """
    if not math.isfinite(float(spot_price)) or float(spot_price) <= 0:
        raise ValueError("spot_price must be finite and positive")
    snapshot_ts = snapshot_ts.astimezone(timezone.utc)
    normalized = [normalize_ticker(row) for row in rows]
    expiries = sorted({r["expiry_ts"] for r in normalized if r["expiry_ts"] > snapshot_ts})[:2]
    selected = []
    for expiry_ts in expiries:
        expiry_rows = [r for r in normalized if r["expiry_ts"] == expiry_ts]
        strikes = sorted({r["strike_price"] for r in expiry_rows})
        if not strikes:
            continue
        atm = min(range(len(strikes)), key=lambda i: (abs(strikes[i] - spot_price), strikes[i]))
        allowed = set(strikes[max(0, atm - 6):atm + 7])
        selected.extend(r for r in expiry_rows if r["strike_price"] in allowed)
    selected.sort(key=lambda r: (r["expiry_ts"], r["strike_price"], r["contract_type"], r["product_id"]))
    if len(selected) > MAX_ROWS:
        raise ValueError(f"Selected chain exceeded expected dynamic cap: {len(selected)}")
    return selected


def parse_api_payload(payload: dict[str, Any]) -> tuple[datetime, float, list[dict[str, Any]]]:
    if not payload.get("success"):
        raise ValueError("Delta options ticker API returned success=false")
    rows = payload.get("result")
    if not isinstance(rows, list):
        raise ValueError("Delta options ticker result must be a list")
    # Delta's ticker endpoint may put timestamp and spot_price on each
    # contract row rather than at the response envelope.
    timestamps = [int(row.get("timestamp") or 0) for row in rows
                  if isinstance(row, dict) and int(row.get("timestamp") or 0) > 0]
    timestamp_us = int(payload.get("timestamp") or (max(timestamps) if timestamps else 0))
    if timestamp_us <= 0:
        raise ValueError("Delta options payload timestamp is missing")
    snapshot_ts = datetime.fromtimestamp(timestamp_us / 1_000_000, tz=timezone.utc)
    spot_value = payload.get("spot_price")
    if spot_value is None and rows:
        spot_value = next((row.get("spot_price") for row in rows
                           if isinstance(row, dict) and row.get("spot_price") is not None), None)
    spot = _number(spot_value, "spot_price", required=True)
    return snapshot_ts, float(spot), rows


def fetch_options_payload(timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(TICKERS_URL, headers={
        "User-Agent": "delta-btc-options-oi-observer/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Delta options response must be a JSON object")
    return payload


def purge_expired_rows(conn, snapshot_ts: datetime) -> None:
    """Retain each contract until 24 hours after its 12:00 UTC settlement."""
    conn.execute(
        "DELETE FROM options_oi.btc_chain_snapshots WHERE expiry_ts < %s - interval '24 hours'",
        (snapshot_ts.astimezone(timezone.utc),),
    )


def save_snapshot(conn, snapshot_ts: datetime, spot_price: float,
                  selected_rows: list[dict[str, Any]]) -> int:
    """Persist in a transaction independent from PRICE/OI candle writes."""
    try:
        conn.execute("BEGIN")
        purge_expired_rows(conn, snapshot_ts)
        for row in selected_rows:
            conn.execute(
                """INSERT INTO options_oi.btc_chain_snapshots
                   (snapshot_ts,product_id,symbol,expiry_date,expiry_ts,contract_type,
                    strike_price,oi_btc,oi_usd,oi_change_6h_usd,mark_iv,delta,gamma,
                    volume_btc,spot_price)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (snapshot_ts,product_id) DO UPDATE SET
                     symbol=EXCLUDED.symbol,expiry_date=EXCLUDED.expiry_date,
                     expiry_ts=EXCLUDED.expiry_ts,contract_type=EXCLUDED.contract_type,
                     strike_price=EXCLUDED.strike_price,oi_btc=EXCLUDED.oi_btc,
                     oi_usd=EXCLUDED.oi_usd,oi_change_6h_usd=EXCLUDED.oi_change_6h_usd,
                     mark_iv=EXCLUDED.mark_iv,delta=EXCLUDED.delta,gamma=EXCLUDED.gamma,
                     volume_btc=EXCLUDED.volume_btc,spot_price=EXCLUDED.spot_price""",
                (snapshot_ts, row["product_id"], row["symbol"], row["expiry_date"],
                 row["expiry_ts"], row["contract_type"], row["strike_price"],
                 row["oi_btc"], row["oi_usd"], row["oi_change_6h_usd"], row["mark_iv"],
                 row["delta"], row["gamma"], row["volume_btc"], spot_price))
        conn.commit()
        return len(selected_rows)
    except Exception:
        conn.rollback()
        raise


def collect_options_snapshot(database_url: str, *, fetcher=fetch_options_payload,
                             connector=None) -> dict[str, Any]:
    """Fetch/filter/persist using a dedicated database connection."""
    import psycopg
    from psycopg.rows import dict_row
    payload = fetcher()
    snapshot_ts, spot, raw_rows = parse_api_payload(payload)
    selected = select_chain_rows(raw_rows, spot, snapshot_ts)
    connect = connector or psycopg.connect
    with connect(database_url, connect_timeout=20, row_factory=dict_row) as conn:
        count = save_snapshot(conn, snapshot_ts, spot, selected)
    return {"snapshot_ts": snapshot_ts.isoformat(), "spot_price": spot, "rows_saved": count}


def _pcr(rows: list[dict[str, Any]]) -> dict[str, Any]:
    calls = sum(float(r["oi_btc"] or 0) for r in rows if r["contract_type"] == "call_options")
    puts = sum(float(r["oi_btc"] or 0) for r in rows if r["contract_type"] == "put_options")
    return {"call_oi_btc": calls, "put_oi_btc": puts,
            "put_call_ratio": puts / calls if calls else None}


def build_options_context(current: list[dict[str, Any]],
                          baselines: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Build descriptive expiry PCR, OI walls and strike changes for each baseline."""
    expiries = []
    for expiry in sorted({r["expiry_date"] for r in current})[:2]:
        subset = [r for r in current if r["expiry_date"] == expiry]
        calls = sorted((r for r in subset if r["contract_type"] == "call_options"),
                       key=lambda r: float(r["oi_btc"] or 0), reverse=True)
        puts = sorted((r for r in subset if r["contract_type"] == "put_options"),
                      key=lambda r: float(r["oi_btc"] or 0), reverse=True)
        expiries.append({"expiry_date": expiry.isoformat() if isinstance(expiry, date) else str(expiry),
                         "pcr": _pcr(subset), "top_call_walls": calls[:3], "top_put_walls": puts[:3]})
    events = []
    for baseline_name in ("30m", "1h", "session_open"):
        previous_by_product = {
            int(r["product_id"]): r for r in (baselines.get(baseline_name) or [])
        }
        for row in current:
            previous = previous_by_product.get(int(row["product_id"]))
            if not previous:
                continue
            old, new = float(previous["oi_btc"] or 0), float(row["oi_btc"] or 0)
            if old > 0 and (old - new) / old >= 0.40:
                kind = "UNWIND"
            elif new - old >= 15 or (old > 0 and (new - old) / old >= 0.50):
                kind = "REBUILD"
            else:
                continue
            events.append({"baseline": baseline_name, "symbol": row["symbol"],
                           "strike_price": row["strike_price"],
                           "contract_type": row["contract_type"], "kind": kind,
                           "change_btc": new - old,
                           "change_pct": ((new - old) / old * 100) if old else None})
    return {"expiries": expiries, "events": events,
            "baselines_available": {key: bool(value) for key, value in baselines.items()}}
