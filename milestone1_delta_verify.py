#!/usr/bin/env python3
"""Read-only Delta India BTCUSD Milestone 1 feed verifier. No database clients or writes."""
import json, math, os, statistics, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from collections import Counter

import websocket

SYMBOL = "BTCUSD"
WS_URL = "wss://public-socket.india.delta.exchange"
REST_URL = "https://api.india.delta.exchange/v2/history/candles"
DURATION = int(os.getenv("OBSERVATION_SECONDS", "3900"))  # 65 minutes
OUT = lambda x: print(json.dumps(x, sort_keys=True, default=str), flush=True)

def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()

def get_rest_candles(start, end):
    q = urllib.parse.urlencode({"resolution":"30m","symbol":SYMBOL,"start":int(start),"end":int(end)})
    req = urllib.request.Request(REST_URL + "?" + q, headers={"User-Agent":"delta-milestone1-verifier/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.loads(r.read().decode())
    if not payload.get("success", False):
        raise RuntimeError("REST candles response success=false")
    rows = payload.get("result", [])
    return rows

start_wall = time.time()
start_utc = datetime.now(timezone.utc)
deadline = start_wall + DURATION
tickers, candles, errors = [], [], []
connected = False
last_msg_wall = None
reconnects = 0

OUT({"event":"worker_started","symbol":SYMBOL,"start_utc":start_utc.isoformat(),
     "start_ist":datetime.now(timezone.utc).astimezone().isoformat(),
     "observation_seconds":DURATION,"neon_connection":False,"neon_writes":0})

def on_open(ws):
    global connected
    connected = True
    ws.send(json.dumps({"type":"enable_heartbeat"}))
    ws.send(json.dumps({"type":"subscribe","payload":{"channels":[
        {"name":"candlestick_30m","symbols":[SYMBOL]},
        {"name":"ticker","symbols":[SYMBOL]}
    ]}}))
    OUT({"event":"websocket_connected","utc":datetime.now(timezone.utc).isoformat(),"subscriptions":["candlestick_30m","ticker"]})

def on_message(ws, raw):
    global last_msg_wall
    now = time.time()
    last_msg_wall = now
    try:
        m = json.loads(raw)
    except Exception:
        errors.append("invalid_json")
        return
    typ = m.get("type")
    if typ == "ticker":
        ts = m.get("ts")
        d = m.get("d") or []
        item = next((x for x in d if x.get("s") == SYMBOL), d[0] if d else {})
        oi = item.get("oi")
        tickers.append({"recv":now,"ts":ts,"oi0":oi[0] if isinstance(oi,list) and len(oi)>0 else None,
                        "oi1":oi[1] if isinstance(oi,list) and len(oi)>1 else None})
    elif typ == "candlestick_30m":
        ts = m.get("ts")
        candles.append({"recv":now,"ts":ts,"o":m.get("o"),"h":m.get("h"),"l":m.get("l"),"c":m.get("c"),"v":m.get("v")})
    elif typ in ("error","subscription_error"):
        errors.append(str(m)[:500])

def on_error(ws, err):
    errors.append("ws_error:" + str(err)[:300])
    OUT({"event":"websocket_error","error":str(err)[:300],"utc":datetime.now(timezone.utc).isoformat()})

def on_close(ws, code, msg):
    global connected
    connected = False
    OUT({"event":"websocket_closed","code":code,"message":str(msg)[:200],"utc":datetime.now(timezone.utc).isoformat()})

app = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
# Run WS in a daemon thread so the observation deadline is enforced independently.
import threading
thread = threading.Thread(target=lambda: app.run_forever(ping_interval=20, ping_timeout=10), daemon=True)
thread.start()

while time.time() < deadline:
    time.sleep(10)
    if not thread.is_alive():
        reconnects += 1
        # A single reconnect attempt is made; any outage is recorded.
        app = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
        thread = threading.Thread(target=lambda: app.run_forever(ping_interval=20, ping_timeout=10), daemon=True)
        thread.start()

end_wall = time.time()
end_utc = datetime.now(timezone.utc)
try:
    app.close()
except Exception:
    pass

# REST alignment check over a window containing the observation and surrounding UTC day boundaries.
rest_start = int((start_wall // 86400 - 1) * 86400)
rest_end = int((end_wall // 86400 + 2) * 86400)
rest_error = None
rest_rows = []
try:
    rest_rows = get_rest_candles(rest_start, rest_end)
except Exception as e:
    rest_error = str(e)

rest_times = sorted({int(x["time"]) for x in rest_rows if isinstance(x,dict) and x.get("time") is not None})
grid_bad = [t for t in rest_times if t % 1800 != 0]
anchors = [t for t in rest_times if t % 86400 == 0]
def slot_from_ts(ts):
    if ts is None: return None
    # Delta WS ts is message/update time in microseconds, not candle-open time.
    sec = float(ts) / 1_000_000 if float(ts) > 10**12 else float(ts)
    return int(sec // 1800) * 1800

ticker_slots = sorted({slot_from_ts(x["ts"]) for x in tickers if x["ts"] is not None})
candle_slots = sorted({slot_from_ts(x["ts"]) for x in candles if x["ts"] is not None})
common_slots = sorted(set(ticker_slots) & set(candle_slots))
intervals = [(tickers[i]["recv"]-tickers[i-1]["recv"]) for i in range(1,len(tickers))]
valid_oi0 = [x["oi0"] for x in tickers if isinstance(x["oi0"],(int,float))]
valid_oi1 = [x["oi1"] for x in tickers if isinstance(x["oi1"],(int,float))]
oi_by_slot = {}
for x in tickers:
    slot = slot_from_ts(x["ts"])
    if slot is not None and isinstance(x["oi0"],(int,float)):
        oi_by_slot.setdefault(slot,[]).append(x["oi0"])
oi_window_summary = []
for slot, vals in sorted(oi_by_slot.items()):
    oi_window_summary.append({"slot_utc":iso(slot),"slot_ist":datetime.fromtimestamp(slot,timezone.utc).astimezone().isoformat(),
                              "samples":len(vals),"first":vals[0],"max":max(vals),"min":min(vals),"last":vals[-1]})
summary = {
 "event":"milestone1_verification_report",
 "observation":{"start_utc":start_utc.isoformat(),"end_utc":end_utc.isoformat(),
                "start_ist":start_utc.astimezone().isoformat(),"end_ist":end_utc.astimezone().isoformat(),
                "duration_seconds":round(end_wall-start_wall,1)},
 "rest_30m":{"success":rest_error is None,"error":rest_error,"rows":len(rest_rows),
             "timestamps_on_1800s_grid":len(grid_bad)==0,"off_grid_count":len(grid_bad),
             "daily_00utc_0530ist_anchors":[{"utc":iso(t),"ist":datetime.fromtimestamp(t,timezone.utc).astimezone().isoformat()} for t in anchors]},
 "websocket":{"ticker_messages":len(tickers),"candle_update_messages":len(candles),"reconnects":reconnects,
              "errors":errors[:30],"ticker_interval_seconds":{"median":statistics.median(intervals) if intervals else None,
              "mean":statistics.mean(intervals) if intervals else None,"max":max(intervals) if intervals else None},
              "ticker_missing_oi0":sum(x["oi0"] is None for x in tickers),
              "ticker_missing_oi1":sum(x["oi1"] is None for x in tickers),
              "oi0_contracts_min":min(valid_oi0) if valid_oi0 else None,"oi0_contracts_max":max(valid_oi0) if valid_oi0 else None,
              "oi1_change_values_min":min(valid_oi1) if valid_oi1 else None,"oi1_change_values_max":max(valid_oi1) if valid_oi1 else None,
              "ticker_slots_utc":[iso(x) for x in ticker_slots],
              "candle_message_slots_utc":[iso(x) for x in candle_slots],
              "shared_observed_slots_utc":[iso(x) for x in common_slots]},
 "oi_30m_candidate_aggregation":{"per_slot_first_max_min_last":oi_window_summary,
                                  "validated":False,
                                  "note":"Candidate OHLC aggregation from ticker oi[0] samples only; this observation does not establish Delta's official historical OI candle semantics."},
 "interpretation":{"ticker_oi0":"Open interest in contracts (level)","ticker_oi1":"6-hour change in OI value in settling symbol; not the OI level",
                   "websocket_candle_ts":"Message/update timestamp; not assumed to be candle-open time",
                   "rest_candle_time":"Used as reference for 30-minute candle-open alignment"},
 "safety":{"neon_connection":False,"neon_credentials_used":False,"neon_writes":0,"database_clients_in_worker":False}
}
OUT(summary)
