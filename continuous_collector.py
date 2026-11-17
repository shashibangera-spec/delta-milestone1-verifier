#!/usr/bin/env python3
"""Continuous Delta BTCUSD 30m collector for the isolated Neon amt_research branch."""
import json
import os
import signal
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

REST_URL = "https://api.india.delta.exchange/v2/history/candles"
PRICE_SYMBOL = "BTCUSD"
OI_SYMBOL = "OI:BTCUSD"
RESOLUTION = "30m"
SLOT_SECONDS = 1800
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
FINALIZATION_GRACE_SECONDS = int(os.getenv("FINALIZATION_GRACE_SECONDS", "15"))
LOOKBACK_SECONDS = 3 * 24 * 3600
DATABASE_URL = os.getenv("DATABASE_URL", "")
EXPECTED_PRICE_ROWS = 8641
EXPECTED_OI_ROWS = 8641
EXPECTED_FEATURE_ROWS = 1800
STOP = False

def log(event, **fields):
    print(json.dumps({"event": event, "utc": datetime.now(timezone.utc).isoformat(), **fields}, sort_keys=True, default=str), flush=True)

def stop_handler(signum, frame):
    global STOP
    STOP = True
    log("shutdown_signal", signal=signum)

signal.signal(signal.SIGTERM, stop_handler)
signal.signal(signal.SIGINT, stop_handler)

def fetch_candles(symbol, start_ts, end_ts):
    query = urllib.parse.urlencode({"resolution": RESOLUTION, "symbol": symbol, "start": int(start_ts), "end": int(end_ts)})
    request = urllib.request.Request(REST_URL + "?" + query, headers={"User-Agent": "delta-amt-research-collector/2.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode())
    if not payload.get("success", False):
        raise RuntimeError(f"Delta REST success=false for {symbol}: {str(payload)[:500]}")
    rows = payload.get("result", [])
    if not isinstance(rows, list):
        raise RuntimeError(f"Delta REST result is not a list for {symbol}")
    normalized = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("time") is None:
            continue
        ts = int(row["time"])
        if ts % SLOT_SECONDS:
            raise RuntimeError(f"Off-grid candle timestamp {ts} from {symbol}")
        def num(*keys):
            for key in keys:
                if row.get(key) is not None:
                    return row[key]
            return None
        normalized[ts] = {"time": ts, "open": num("open","o"), "high": num("high","h"), "low": num("low","l"), "close": num("close","c"), "volume": num("volume","v"), "raw": row}
    return normalized

def create_provisional_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research.delta_candles_provisional (
            source text NOT NULL DEFAULT 'delta_india',
            symbol text NOT NULL,
            series_type text NOT NULL CHECK (series_type IN ('PRICE','OI')),
            resolution text NOT NULL DEFAULT '30m',
            candle_time timestamptz NOT NULL,
            open_value numeric NULL, high_value numeric NULL, low_value numeric NULL,
            close_value numeric NULL, volume numeric NULL, raw_payload jsonb NOT NULL,
            status text NOT NULL DEFAULT 'PROVISIONAL_INCOMPLETE' CHECK (status = 'PROVISIONAL_INCOMPLETE'),
            observed_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (source,symbol,series_type,resolution,candle_time)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS delta_candles_provisional_time_idx ON research.delta_candles_provisional (candle_time)")
    conn.commit()

def baseline_snapshot(conn):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT series_type, COUNT(*)::bigint AS row_count, MIN(candle_time) AS first_time,
                   MAX(candle_time) AS last_time,
                   md5(COALESCE(string_agg(concat_ws('|',id::text,source,symbol,series_type,resolution,
                     candle_time::text,open_value::text,high_value::text,low_value::text,close_value::text,
                     volume::text,raw_payload::text), E'\\n' ORDER BY candle_time,id),'')) AS checksum
            FROM research.delta_candles GROUP BY series_type
        """)
        candles = {row["series_type"]: row for row in cur.fetchall()}
        cur.execute("""
            SELECT COUNT(*)::bigint AS row_count, MIN(candle_time) AS first_time, MAX(candle_time) AS last_time,
                   md5(COALESCE(string_agg(concat_ws('|',source,symbol,resolution,candle_time::text,
                     session_date::text,cycle_bar::text,cycle_status,price_open::text,price_high::text,
                     price_low::text,price_close::text,feature_payload::text), E'\\n' ORDER BY candle_time),'')) AS checksum
            FROM research.amt_30m_features
        """)
        features = cur.fetchone()
    if candles.get("PRICE",{}).get("row_count") != EXPECTED_PRICE_ROWS: raise RuntimeError(f"PRICE baseline count mismatch: {candles.get('PRICE')}")
    if candles.get("OI",{}).get("row_count") != EXPECTED_OI_ROWS: raise RuntimeError(f"OI baseline count mismatch: {candles.get('OI')}")
    if features["row_count"] != EXPECTED_FEATURE_ROWS: raise RuntimeError(f"AMT feature baseline count mismatch: {features}")
    if candles["PRICE"]["last_time"] != candles["OI"]["last_time"]: raise RuntimeError("PRICE/OI baseline latest timestamps differ")
    return {"candles":candles,"features":features,"baseline_max":candles["PRICE"]["last_time"]}

def verify_baseline_unchanged(conn, baseline):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT series_type, COUNT(*)::bigint AS row_count,
                   md5(COALESCE(string_agg(concat_ws('|',id::text,source,symbol,series_type,resolution,
                     candle_time::text,open_value::text,high_value::text,low_value::text,close_value::text,
                     volume::text,raw_payload::text), E'\\n' ORDER BY candle_time,id),'')) AS checksum
            FROM research.delta_candles WHERE candle_time <= %s GROUP BY series_type
        """,(baseline["baseline_max"],))
        candle_rows={r["series_type"]:r for r in cur.fetchall()}
        cur.execute("""
            SELECT COUNT(*)::bigint AS row_count,
                   md5(COALESCE(string_agg(concat_ws('|',source,symbol,resolution,candle_time::text,
                     session_date::text,cycle_bar::text,cycle_status,price_open::text,price_high::text,
                     price_low::text,price_close::text,feature_payload::text), E'\\n' ORDER BY candle_time),'')) AS checksum
            FROM research.amt_30m_features
        """)
        feature_row=cur.fetchone()
        cur.execute("""
            SELECT series_type,COUNT(*)::bigint AS total_rows,
                   COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM candle_time)::bigint % 1800 <> 0)::bigint AS off_grid,
                   MAX(candle_time) AS last_time
            FROM research.delta_candles GROUP BY series_type
        """)
        totals={r["series_type"]:r for r in cur.fetchall()}
    for series in ("PRICE","OI"):
        before,after=baseline["candles"][series],candle_rows.get(series)
        if not after or after["row_count"]!=before["row_count"] or after["checksum"]!=before["checksum"]:
            raise RuntimeError(f"Historical {series} rows changed: before={before}, after={after}")
        if totals[series]["off_grid"]!=0: raise RuntimeError(f"Off-grid {series} rows detected after first write")
    if feature_row["row_count"]!=baseline["features"]["row_count"] or feature_row["checksum"]!=baseline["features"]["checksum"]:
        raise RuntimeError("Existing amt_30m_features history changed")
    return {"historical_price_rows_preserved":EXPECTED_PRICE_ROWS,"historical_oi_rows_preserved":EXPECTED_OI_ROWS,
            "amt_30m_features_preserved":EXPECTED_FEATURE_ROWS,"price_total_rows":totals["PRICE"]["total_rows"],
            "oi_total_rows":totals["OI"]["total_rows"],"price_off_grid":totals["PRICE"]["off_grid"],
            "oi_off_grid":totals["OI"]["off_grid"],"price_last_time":totals["PRICE"]["last_time"],
            "oi_last_time":totals["OI"]["last_time"],"historical_checksums_unchanged":True}

def existing_latest(conn):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT series_type,MAX(candle_time) AS last_time FROM research.delta_candles GROUP BY series_type")
        return {r["series_type"]:r["last_time"] for r in cur.fetchall()}

def upsert_row(conn,symbol,series_type,candle,provisional=False):
    candle_time=datetime.fromtimestamp(candle["time"],timezone.utc)
    payload=json.dumps(candle["raw"],separators=(",",":"),sort_keys=True)
    if provisional:
        conn.execute("""
            INSERT INTO research.delta_candles_provisional
              (source,symbol,series_type,resolution,candle_time,open_value,high_value,low_value,close_value,volume,raw_payload,status,observed_at)
            VALUES ('delta_india',%s,%s,'30m',%s,%s,%s,%s,%s,%s,%s::jsonb,'PROVISIONAL_INCOMPLETE',now())
            ON CONFLICT (source,symbol,series_type,resolution,candle_time)
            DO UPDATE SET open_value=EXCLUDED.open_value,high_value=EXCLUDED.high_value,low_value=EXCLUDED.low_value,
              close_value=EXCLUDED.close_value,volume=EXCLUDED.volume,raw_payload=EXCLUDED.raw_payload,
              status='PROVISIONAL_INCOMPLETE',observed_at=now()
        """,(symbol,series_type,candle_time,candle["open"],candle["high"],candle["low"],candle["close"],candle["volume"],payload))
    else:
        conn.execute("""
            INSERT INTO research.delta_candles
              (id,source,symbol,series_type,resolution,candle_time,open_value,high_value,low_value,close_value,volume,raw_payload,retrieved_at)
            VALUES (nextval('research.delta_candles_id_seq'),'delta_india',%s,%s,'30m',%s,%s,%s,%s,%s,%s,%s::jsonb,now())
            ON CONFLICT (source,symbol,series_type,resolution,candle_time)
            DO UPDATE SET open_value=EXCLUDED.open_value,high_value=EXCLUDED.high_value,low_value=EXCLUDED.low_value,
              close_value=EXCLUDED.close_value,volume=EXCLUDED.volume,raw_payload=EXCLUDED.raw_payload,retrieved_at=now()
            WHERE (research.delta_candles.open_value,research.delta_candles.high_value,research.delta_candles.low_value,
                   research.delta_candles.close_value,research.delta_candles.volume,research.delta_candles.raw_payload)
              IS DISTINCT FROM (EXCLUDED.open_value,EXCLUDED.high_value,EXCLUDED.low_value,EXCLUDED.close_value,
                                EXCLUDED.volume,EXCLUDED.raw_payload)
        """,(symbol,series_type,candle_time,candle["open"],candle["high"],candle["low"],candle["close"],candle["volume"],payload))

def process_cycle(conn,baseline,first_write_verified):
    now=time.time()
    start=int(now-LOOKBACK_SECONDS)
    prices=fetch_candles(PRICE_SYMBOL,start,int(now))
    oi=fetch_candles(OI_SYMBOL,start,int(now))
    paired=sorted(set(prices).intersection(oi))
    if not paired:
        log("cycle_no_paired_candles",price_rows=len(prices),oi_rows=len(oi))
        return first_write_verified
    confirmed=[]; provisional=[]
    baseline_epoch=int(baseline["baseline_max"].timestamp())
    for slot in paired:
        if slot<=baseline_epoch: continue
        if slot+SLOT_SECONDS<=now-FINALIZATION_GRACE_SECONDS: confirmed.append(slot)
        else: provisional.append(slot)
    latest=existing_latest(conn)
    max_price=int(latest["PRICE"].timestamp())
    max_oi=int(latest["OI"].timestamp())
    saved=[]
    conn.commit()
    conn.execute("BEGIN")
    try:
        for slot in provisional:
            for symbol,series_type,candle in ((PRICE_SYMBOL,"PRICE",prices[slot]),(OI_SYMBOL,"OI",oi[slot])):
                upsert_row(conn,symbol,series_type,candle,provisional=True)
        for slot in confirmed:
            if slot<=max_price and slot<=max_oi: continue
            if slot%SLOT_SECONDS or slot<baseline_epoch+SLOT_SECONDS: raise RuntimeError(f"Invalid confirmed grid slot {slot}")
            upsert_row(conn,PRICE_SYMBOL,"PRICE",prices[slot])
            upsert_row(conn,OI_SYMBOL,"OI",oi[slot])
            conn.execute("DELETE FROM research.delta_candles_provisional WHERE candle_time=%s AND resolution='30m'",
                         (datetime.fromtimestamp(slot,timezone.utc),))
            saved.append(slot)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if saved:
        log("confirmed_candle_pair_saved",count=len(saved),
            first_slot_utc=datetime.fromtimestamp(saved[0],timezone.utc).isoformat(),
            last_slot_utc=datetime.fromtimestamp(saved[-1],timezone.utc).isoformat(),
            provisional_slots=len(provisional))
        if not first_write_verified:
            result=verify_baseline_unchanged(conn,baseline)
            log("post_first_write_verification",**result)
            first_write_verified=True
    else:
        log("cycle_completed",paired_slots=len(paired),provisional_slots=len(provisional),confirmed_slots_seen=len(confirmed))
    return first_write_verified

def main():
    if not DATABASE_URL.startswith(("postgresql://","postgres://")): raise RuntimeError("DATABASE_URL must be PostgreSQL URL")
    with psycopg.connect(DATABASE_URL,connect_timeout=20,row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database() AS db,current_schema() AS schema")
            identity=cur.fetchone()
        if identity["db"]!="amt_research": raise RuntimeError(f"Refusing writes: unexpected database {identity['db']}")
        create_provisional_table(conn)
        baseline=baseline_snapshot(conn)
        log("collector_started",database=identity["db"],neon_branch_id=os.getenv("NEON_BRANCH_ID"),
            expected_baseline={"PRICE":EXPECTED_PRICE_ROWS,"OI":EXPECTED_OI_ROWS,"amt_30m_features":EXPECTED_FEATURE_ROWS},
            baseline_max_utc=baseline["baseline_max"],poll_seconds=POLL_SECONDS)
        first_write_verified=False
        while not STOP:
            started=time.time()
            try:
                first_write_verified=process_cycle(conn,baseline,first_write_verified)
            except Exception as exc:
                conn.rollback()
                log("cycle_error",error=str(exc)[:1000])
            sleep_for=max(1,POLL_SECONDS-(time.time()-started))
            for _ in range(int(sleep_for)):
                if STOP: break
                time.sleep(1)
        log("collector_stopped",first_write_verified=first_write_verified)

if __name__=="__main__":
    main()
