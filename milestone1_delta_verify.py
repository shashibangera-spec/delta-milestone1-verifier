#!/usr/bin/env python3
"""Read-only Delta India BTCUSD ticker/OI verifier. No database clients or writes."""
import json
import os
import statistics
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict

import websocket
from oi_metrics import CONTRACT_VALUE_BTC, contracts_to_btc, candle_validation_status

SYMBOL = "BTCUSD"
OI_SYMBOL = f"OI:{SYMBOL}"
WS_URL = "wss://public-socket.india.delta.exchange"
REST_URL = "https://api.india.delta.exchange/v2/history/candles"
DURATION = int(os.getenv("OBSERVATION_SECONDS", "600"))
IST = ZoneInfo("Asia/Kolkata")


def out(payload):
    print(json.dumps(payload, sort_keys=True, default=str), flush=True)


def as_number(value):
    """Delta v2/ticker encodes oi array values as numeric strings."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


def iso_utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def iso_ist(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(IST).isoformat()


def slot_from_ts(ts):
    if ts is None:
        return None
    value = float(ts)
    # WebSocket timestamps are microseconds; REST candle timestamps are seconds.
    seconds = value / 1_000_000 if value > 10**12 else value
    return int(seconds // 1800) * 1800


def get_rest_candles(symbol, start, end):
    query = urllib.parse.urlencode({
        "resolution": "30m",
        "symbol": symbol,
        "start": int(start),
        "end": int(end),
    })
    request = urllib.request.Request(
        REST_URL + "?" + query,
        headers={"User-Agent": "delta-milestone1-verifier/1.1", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode())
    if not payload.get("success", False):
        raise RuntimeError(f"REST candles success=false for {symbol}: {payload}")
    rows = payload.get("result", [])
    if not isinstance(rows, list):
        raise RuntimeError(f"REST candles result is not a list for {symbol}")
    return rows


start_wall = time.time()
start_utc = datetime.now(timezone.utc)
deadline = start_wall + DURATION
tickers, price_candles, errors = [], [], []
reconnects = 0

out({
    "event": "worker_started",
    "symbol": SYMBOL,
    "oi_rest_symbol": OI_SYMBOL,
    "start_utc": start_utc.isoformat(),
    "start_ist": start_utc.astimezone(IST).isoformat(),
    "observation_seconds": DURATION,
    "neon_connection": False,
    "neon_credentials_used": False,
    "neon_writes": 0,
})


def on_open(ws):
    ws.send(json.dumps({"type": "enable_heartbeat"}))
    ws.send(json.dumps({
        "type": "subscribe",
        "payload": {"channels": [
            {"name": "ticker", "symbols": [SYMBOL]},
            {"name": "candlestick_30m", "symbols": [SYMBOL]},
        ]},
    }))
    out({
        "event": "websocket_connected",
        "utc": datetime.now(timezone.utc).isoformat(),
        "subscriptions": ["ticker", "candlestick_30m"],
    })


def on_message(ws, raw):
    received = time.time()
    try:
        message = json.loads(raw)
    except Exception:
        errors.append("invalid_json")
        return

    message_type = message.get("type")
    if message_type == "ticker":
        # Official v2/ticker shape: {"type":"ticker","sy":"BTCUSD","ts":...,"d":[{"s":"BTCUSD","oi":["...","..."]}]}
        data = message.get("d")
        data = data if isinstance(data, list) else []
        item = next((entry for entry in data if entry.get("s") == SYMBOL), None)
        if item is None and message.get("sy") == SYMBOL and data:
            item = data[0]
        if item is None:
            errors.append("ticker_message_missing_BTCUSD_item")
            return
        oi = item.get("oi")
        if not isinstance(oi, (list, tuple)):
            errors.append("ticker_message_missing_oi_array")
            return
        tickers.append({
            "recv": received,
            "ts": message.get("ts"),
            "oi0": as_number(oi[0]) if len(oi) > 0 else None,
            "oi1": as_number(oi[1]) if len(oi) > 1 else None,
            "symbol": item.get("s"),
        })
    elif message_type == "candlestick_30m":
        price_candles.append({
            "recv": received,
            "ts": message.get("ts"),
            "o": as_number(message.get("o")),
            "h": as_number(message.get("h")),
            "l": as_number(message.get("l")),
            "c": as_number(message.get("c")),
        })
    elif message_type in ("error", "subscription_error"):
        errors.append(str(message)[:500])


def on_error(ws, error):
    errors.append("ws_error:" + str(error)[:300])
    out({"event": "websocket_error", "error": str(error)[:300],
         "utc": datetime.now(timezone.utc).isoformat()})


def on_close(ws, code, message):
    out({"event": "websocket_closed", "code": code, "message": str(message)[:200],
         "utc": datetime.now(timezone.utc).isoformat()})


app = websocket.WebSocketApp(
    WS_URL, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close
)
thread = threading.Thread(
    target=lambda: app.run_forever(ping_interval=20, ping_timeout=10), daemon=True
)
thread.start()

while time.time() < deadline:
    time.sleep(min(5, max(0.1, deadline - time.time())))
    if not thread.is_alive() and time.time() < deadline:
        reconnects += 1
        time.sleep(2)
        app = websocket.WebSocketApp(
            WS_URL, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close
        )
        thread = threading.Thread(
            target=lambda: app.run_forever(ping_interval=20, ping_timeout=10), daemon=True
        )
        thread.start()

end_wall = time.time()
end_utc = datetime.now(timezone.utc)
try:
    app.close()
except Exception:
    pass

# Include the containing 30m candle and adjacent slots. REST candle times are UTC seconds.
first_slot = int(start_wall // 1800) * 1800
last_slot = int(end_wall // 1800) * 1800
rest_start = first_slot - 1800
rest_end = last_slot + 3600

price_rows, oi_rows = [], []
price_error, oi_error = None, None
try:
    price_rows = get_rest_candles(SYMBOL, rest_start, rest_end)
except Exception as exc:
    price_error = str(exc)
try:
    oi_rows = get_rest_candles(OI_SYMBOL, rest_start, rest_end)
except Exception as exc:
    oi_error = str(exc)

price_times = sorted({
    int(row["time"]) for row in price_rows
    if isinstance(row, dict) and row.get("time") is not None
})
oi_by_slot = {}
for row in oi_rows:
    if not isinstance(row, dict) or row.get("time") is None:
        continue
    slot = int(row["time"])
    oi_by_slot[slot] = {
        "time": slot,
        "open": as_number(row.get("open", row.get("o"))),
        "high": as_number(row.get("high", row.get("h"))),
        "low": as_number(row.get("low", row.get("l"))),
        "close": as_number(row.get("close", row.get("c"))),
    }

samples_by_slot = defaultdict(list)
for sample in tickers:
    slot = slot_from_ts(sample["ts"])
    if slot is not None and sample["oi0"] is not None:
        samples_by_slot[slot].append(sample)

comparisons = []
for slot, samples in sorted(samples_by_slot.items()):
    values = [sample["oi0"] for sample in samples]
    rest = oi_by_slot.get(slot)
    stream_min, stream_max, stream_last = min(values), max(values), values[-1]
    stream_min_btc = contracts_to_btc(stream_min)
    stream_max_btc = contracts_to_btc(stream_max)
    stream_last_btc = contracts_to_btc(stream_last)
    candle_status = candle_validation_status(start_wall, end_wall, slot, 1800)
    comparison = {
        "slot_open_utc": iso_utc(slot),
        "slot_open_ist": iso_ist(slot),
        "slot_end_utc": iso_utc(slot + 1800),
        "slot_end_ist": iso_ist(slot + 1800),
        "ticker_samples": len(values),
        "stream_oi_min": stream_min,
        "stream_oi_max": stream_max,
        "stream_oi_last": stream_last,
        "contract_value_btc": CONTRACT_VALUE_BTC,
        "stream_oi_btc_min": stream_min_btc,
        "stream_oi_btc_max": stream_max_btc,
        "stream_oi_btc_last": stream_last_btc,
        "rest_oi_candle": rest,
        "candle_validation_status": candle_status,
        "rest_candle_found": rest is not None,
        "stream_min_inside_rest_low_high": (
            stream_min_btc >= rest["low"] and stream_min_btc <= rest["high"]
            if rest and rest["low"] is not None and rest["high"] is not None else None
        ),
        "stream_max_inside_rest_low_high": (
            stream_max_btc >= rest["low"] and stream_max_btc <= rest["high"]
            if rest and rest["low"] is not None and rest["high"] is not None else None
        ),
        "stream_last_vs_rest_close_difference": (
            stream_last_btc - rest["close"] if rest and rest["close"] is not None else None
        ),
        "full_30m_slot_observed": candle_status == "COMPLETE_30M_OBSERVATION",
        "close_comparison_is_final": end_wall >= slot + 1800,
    }
    comparisons.append(comparison)

ticker_intervals = [
    tickers[index]["recv"] - tickers[index - 1]["recv"]
    for index in range(1, len(tickers))
]
valid_oi0 = [sample["oi0"] for sample in tickers if sample["oi0"] is not None]
valid_oi1 = [sample["oi1"] for sample in tickers if sample["oi1"] is not None]
price_grid_bad = [timestamp for timestamp in price_times if timestamp % 1800 != 0]
oi_grid_bad = [timestamp for timestamp in oi_by_slot if timestamp % 1800 != 0]

summary = {
    "event": "milestone1_oi_10m_verification_report",
    "observation": {
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "start_ist": start_utc.astimezone(IST).isoformat(),
        "end_ist": end_utc.astimezone(IST).isoformat(),
        "duration_seconds": round(end_wall - start_wall, 1),
        "timezone": "Asia/Kolkata",
    },
    "websocket": {
        "ticker_channel": "ticker (Delta's current public v2 ticker channel)",
        "ticker_messages": len(tickers),
        "ticker_missing_oi0": sum(sample["oi0"] is None for sample in tickers),
        "ticker_missing_oi1": sum(sample["oi1"] is None for sample in tickers),
        "oi0_contracts_min": min(valid_oi0) if valid_oi0 else None,
        "oi0_contracts_max": max(valid_oi0) if valid_oi0 else None,
        "oi0_contracts_last": valid_oi0[-1] if valid_oi0 else None,
        "contract_value_btc": CONTRACT_VALUE_BTC,
        "oi0_btc_min": contracts_to_btc(min(valid_oi0)) if valid_oi0 else None,
        "oi0_btc_max": contracts_to_btc(max(valid_oi0)) if valid_oi0 else None,
        "oi0_btc_last": contracts_to_btc(valid_oi0[-1]) if valid_oi0 else None,
        "oi1_change_values_min": min(valid_oi1) if valid_oi1 else None,
        "oi1_change_values_max": max(valid_oi1) if valid_oi1 else None,
        "ticker_interval_seconds": {
            "median": statistics.median(ticker_intervals) if ticker_intervals else None,
            "mean": statistics.mean(ticker_intervals) if ticker_intervals else None,
            "max": max(ticker_intervals) if ticker_intervals else None,
        },
        "price_candle_update_messages": len(price_candles),
        "reconnects": reconnects,
        "errors": errors[:30],
    },
    "rest_price_30m": {
        "success": price_error is None,
        "error": price_error,
        "rows": len(price_rows),
        "off_grid_count": len(price_grid_bad),
    },
    "rest_oi_30m": {
        "symbol": OI_SYMBOL,
        "success": oi_error is None,
        "error": oi_error,
        "rows": len(oi_rows),
        "off_grid_count": len(oi_grid_bad),
        "candles": [
            {
                **candle,
                "time_ist": datetime.fromtimestamp(
                    candle["time"], timezone.utc
                ).astimezone(IST).isoformat(),
                "time_utc": iso_utc(candle["time"]),
            }
            for candle in oi_by_slot.values()
        ],
    },
    "stream_vs_rest_oi_comparison": comparisons,
    "validation_limits": {
        "full_30m_ohlc_confirmed": any(item["full_30m_slot_observed"] for item in comparisons),
        "note": (
            "A 10-minute sample cannot establish the complete high/low/close of a 30-minute candle. "
            "This run checks that observed ticker OI samples are present, aggregates their observed "
            "min/max/last, and compares them with the matching REST OI candle range/close. "
            "A complete 30-minute observation is still required to validate full 30-minute OI OHLC."
        ),
    },
    "interpretation": {
        "ticker_oi0": "oi[0], parsed from Delta's numeric-string field: open interest contracts level",
        "ticker_oi1": "oi[1]: six-hour change in OI value in settling symbol, not the OI level",
        "rest_oi": "GET /v2/history/candles with symbol=OI:BTCUSD and resolution=30m",
        "timestamps": "REST candle time is UTC Unix seconds; WebSocket ts is UTC microseconds",
    },
    "safety": {
        "database_clients_in_worker": False,
        "neon_connection": False,
        "neon_credentials_used": False,
        "neon_writes": 0,
        "supabase_connection": False,
        "supabase_writes": 0,
    },
}
out(summary)
