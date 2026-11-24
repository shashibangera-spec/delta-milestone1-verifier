"""Fail-closed V1.7 historical backfill and daily runner. Dry-run unless --apply."""
from __future__ import annotations
import argparse, json, os, sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse
import psycopg
from psycopg.rows import dict_row
from amt_engine.v17_writer import (
    BRANCH_ID, DATABASE_NAME, DATABASE_ROLE, PROJECT_ID, SOURCE, SYMBOL,
    RESOLUTION, CANDLE_INTERVAL, persist_session, session_bounds_utc,
    validate_envelope, validate_target_environment,
)

SOURCE_BRANCH = "br-lingering-grass-ao07mgrx"
SOURCE_HOST = "ep-sparkling-queen-aoqgp0mw.c-2.ap-southeast-1.aws.neon.tech"
TARGET_HOST = "ep-old-bar-aoau4qop.c-2.ap-southeast-1.aws.neon.tech"
METHOD = "AMT_ENGINE_V1.7"

class PipelineError(RuntimeError): pass

def _connect_ro(url, host, role, label):
    parsed = urlparse(url or "")
    if parsed.scheme not in ("postgres", "postgresql") or parsed.hostname != host:
        raise PipelineError(f"{label} URL host does not match its pinned Neon branch")
    conn = psycopg.connect(url, sslmode="require", row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SELECT current_database() db,current_user usr,session_user su")
            who = cur.fetchone()
        if (who["db"], who["usr"], who["su"]) != (DATABASE_NAME, role, role):
            raise PipelineError(f"{label} database/login identity mismatch")
        return conn
    except Exception:
        conn.close()
        raise

def _source_conn(env):
    if env.get("V17_SOURCE_BRANCH_ID") != SOURCE_BRANCH:
        raise PipelineError("V17_SOURCE_BRANCH_ID mismatch")
    return _connect_ro(env.get("V17_SOURCE_DATABASE_URL"), SOURCE_HOST, "amt_dashboard_ro", "Source")

def _target_ro_conn(env):
    if env.get("V17_TARGET_READ_BRANCH_ID") != BRANCH_ID:
        raise PipelineError("V17_TARGET_READ_BRANCH_ID mismatch")
    return _connect_ro(env.get("V17_TARGET_READONLY_DATABASE_URL"), TARGET_HOST, "amt_dashboard_ro", "Target read-only")

def _records(conn, d, series, symbol):
    start, end = session_bounds_utc(d)
    with conn.cursor() as cur:
        cur.execute("""SELECT candle_time,open_value,high_value,low_value,close_value,retrieved_at
          FROM research.delta_candles WHERE source=%s AND series_type=%s AND symbol=%s
          AND resolution=%s AND candle_time >= %s AND candle_time < %s ORDER BY candle_time""",
          (SOURCE,series,symbol,RESOLUTION,start,end))
        rows=cur.fetchall()
    expected=[start+CANDLE_INTERVAL*i for i in range(48)]
    actual=[r["candle_time"].astimezone(timezone.utc) for r in rows]
    if len(rows)!=48 or actual!=expected:
        raise PipelineError(f"{d} {series}: expected 48 ordered candle OPEN slots, got {len(rows)}")
    out=[]
    for r in rows:
        if any(r[k] is None for k in ("open_value","high_value","low_value","close_value","retrieved_at")):
            raise PipelineError(f"{d} {series}: missing OHLC or retrieved_at")
        t=r["candle_time"].astimezone(timezone.utc)
        out.append({
          "candle_id":f"{series}|{t:%Y%m%d%H%M%S}","timestamp":t.isoformat(),
          "open":str(r["open_value"]),"high":str(r["high_value"]),
          "low":str(r["low_value"]),"close":str(r["close_value"]),
          # Source DB records retrieved_at, not independent source availability.
          "source_available_at":(t+CANDLE_INTERVAL).isoformat(),
          "ingested_at":r["retrieved_at"].astimezone(timezone.utc).isoformat()
        })
    return out

def _prior(conn,d):
    with conn.cursor() as cur:
        cur.execute("""SELECT session_date,profile_id,profile_status,is_complete
          FROM amt_engine_v17.session_profiles
          WHERE source=%s AND symbol=%s AND method_version=%s AND session_date<%s
          ORDER BY session_date""",(SOURCE,SYMBOL,METHOD,d))
        rows=cur.fetchall()
    return [{"session_date":r["session_date"].isoformat(),
      "profile_id":str(r["profile_id"]) if r["profile_id"] else None,
      "profile_status":r["profile_status"],"is_complete":r["is_complete"]} for r in rows]

def _existing(conn,d):
    with conn.cursor() as cur:
        cur.execute("""SELECT p.profile_id,p.profile_status,p.is_complete,
          f.bundle_sha256,f.persisted_sha256 FROM amt_engine_v17.session_profiles p
          LEFT JOIN amt_engine_v17.session_write_fingerprints f ON f.profile_id=p.profile_id
          WHERE p.session_date=%s AND p.source=%s AND p.symbol=%s AND p.method_version=%s""",
          (d,SOURCE,SYMBOL,METHOD))
        rows=cur.fetchall()
    if len(rows)>1: raise PipelineError(f"{d}: duplicate destination profiles")
    if not rows: return "MISSING"
    r=rows[0]
    if r["profile_status"]=="COMPLETE" and r["is_complete"] and r["bundle_sha256"] and r["persisted_sha256"]:
        return "SKIP_COMPLETE"
    raise PipelineError(f"{d}: existing incomplete/unfingerprinted profile; manual reconciliation required")

def _payload(src,dst,d,now):
    _,cutoff=session_bounds_utc(d)
    if cutoff>now: raise PipelineError(f"{d}: session is not closed")
    payload={"session_date":d.isoformat(),"source":SOURCE,"symbol":SYMBOL,
      "resolution":RESOLUTION,"timestamp_convention":"OPEN","price_units":"USD",
      "oi_units":"BTC","oi_units_verified":True,"cutoff_at":cutoff.isoformat(),
      "price_records":_records(src,d,"PRICE","BTCUSD"),
      "oi_records":_records(src,d,"OI","OI:BTCUSD"),"prior_profiles":_prior(dst,d),
      "source_available_at_basis":"CANDLE_CLOSE_DERIVED","source_branch_id":SOURCE_BRANCH}
    validate_envelope(payload,now=now,test_mode=False)
    return payload

def _verify(conn,d):
    with conn.cursor() as cur:
        cur.execute("""SELECT profile_id,profile_status,is_complete,expected_bars,observed_bars,
          distinct_slots,missing_slots,duplicate_slots,invalid_slots,out_of_session_count
          FROM amt_engine_v17.session_profiles WHERE session_date=%s AND source=%s
          AND symbol=%s AND method_version=%s""",(d,SOURCE,SYMBOL,METHOD))
        p=cur.fetchall()
        if len(p)!=1: raise PipelineError(f"{d}: profile count after write is not one")
        p=p[0]
        cur.execute("SELECT count(*) n,count(DISTINCT expected_interval_open) slots FROM amt_engine_v17.developing_snapshots WHERE profile_id=%s",(p["profile_id"],))
        s=cur.fetchone()
        cur.execute("SELECT units_verified FROM amt_engine_v17.session_oi_context WHERE profile_id=%s",(p["profile_id"],))
        o=cur.fetchone()
        cur.execute("SELECT bundle_sha256,persisted_sha256 FROM amt_engine_v17.session_write_fingerprints WHERE profile_id=%s",(p["profile_id"],))
        f=cur.fetchone()
    if not (p["profile_status"]=="COMPLETE" and p["is_complete"] is True
      and p["expected_bars"]==p["observed_bars"]==p["distinct_slots"]==48
      and p["missing_slots"]==p["duplicate_slots"]==p["invalid_slots"]==p["out_of_session_count"]==0
      and s["n"]==s["slots"]==48 and o and o["units_verified"] is True
      and f and f["bundle_sha256"] and f["persisted_sha256"]):
        raise PipelineError(f"{d}: post-write integrity verification failed")
    return {"profile_id":str(p["profile_id"]),"snapshot_count":s["n"],
      "oi_units_verified":o["units_verified"],"bundle_sha256":f["bundle_sha256"].strip(),
      "persisted_sha256":f["persisted_sha256"].strip()}

def _execute(dates,apply,env):
    now=datetime.now(timezone.utc)
    with _source_conn(env) as src,_target_ro_conn(env) as dst:
        # Preflight every requested date before the first write. Do not cache
        # prior-profile payloads: each applied session must see earlier writes
        # from this same chronological batch as valid reference candidates.
        preflight=[]
        for d in dates:
            status=_existing(dst,d)
            if status=="SKIP_COMPLETE":
                preflight.append((d,status))
            else:
                _records(src,d,"PRICE","BTCUSD")
                _records(src,d,"OI","OI:BTCUSD")
                _,cutoff=session_bounds_utc(d)
                if cutoff>now:
                    raise PipelineError(f"{d}: session is not closed")
                preflight.append((d,"PERSIST"))
        summary={"mode":"APPLY" if apply else "DRY_RUN","source_branch":SOURCE_BRANCH,
          "target_branch":BRANCH_ID,"sessions":[{"date":d.isoformat(),"action":s} for d,s in preflight]}
        if not apply: return summary
        validate_target_environment(env)
        results=[]
        with psycopg.connect(env["DATABASE_URL"],sslmode="require",row_factory=dict_row) as writer:
            for d,status in preflight:
                if status=="SKIP_COMPLETE":
                    results.append({"date":d.isoformat(),"status":"SKIPPED_COMPLETE"})
                    continue
                # Re-check identity immediately before write; fail closed if a
                # competing process has created or altered this session.
                current=_existing(dst,d)
                if current=="SKIP_COMPLETE":
                    results.append({"date":d.isoformat(),"status":"SKIPPED_COMPLETE"})
                    continue
                payload=_payload(src,dst,d,now)
                with writer.transaction():
                    result=persist_session(writer,payload,now=now,test_mode=False)
                results.append({"date":d.isoformat(),**result,**_verify(dst,d)})
        summary["results"]=results
        return summary

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    b=sub.add_parser("backfill"); b.add_argument("--from-date",required=True,type=date.fromisoformat)
    b.add_argument("--through-date",required=True,type=date.fromisoformat); b.add_argument("--apply",action="store_true")
    d=sub.add_parser("daily"); d.add_argument("--session-date",type=date.fromisoformat); d.add_argument("--apply",action="store_true")
    a=p.parse_args(argv)
    if a.command=="backfill":
        if a.through_date<a.from_date: p.error("--through-date precedes --from-date")
        dates=[a.from_date+timedelta(days=i) for i in range((a.through_date-a.from_date).days+1)]
    else: dates=[a.session_date or (datetime.now(timezone.utc).date()-timedelta(days=1))]
    try:
        print(json.dumps(_execute(dates,a.apply,dict(os.environ)),sort_keys=True,default=str))
        return 0
    except Exception as e:
        print(f"V1.7 pipeline stopped safely: {e}",file=sys.stderr); return 1

if __name__=="__main__": raise SystemExit(main())
