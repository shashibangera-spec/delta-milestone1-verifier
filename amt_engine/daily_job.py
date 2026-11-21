"""One-session Neon writer. Requires the separately approved migration and writer role."""
from __future__ import annotations
import argparse
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
import psycopg
from psycopg.rows import dict_row
from amt_engine.daily import (METHOD_VERSION, SOURCE, SYMBOL, RESOLUTION, validate_session,
    calculate_profile, assign_revision_attempt)


def process_session(conn, session_date: date):
    run_id = uuid.uuid4()
    with conn.cursor(row_factory=dict_row) as cur:
        # Serialize writers for one session/method without locking raw collector tables.
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{session_date}:{METHOD_VERSION}:{SOURCE}:{SYMBOL}",))
        start = datetime.combine(session_date, datetime.min.time(), tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        cur.execute("""SELECT candle_time,open_value,high_value,low_value,close_value
          FROM research.delta_candles
          WHERE source=%s AND symbol=%s AND series_type='PRICE' AND resolution=%s
            AND candle_time >= %s AND candle_time < %s ORDER BY candle_time""",
          (SOURCE,SYMBOL,RESOLUTION,start,end))
        raw = cur.fetchall()
        cur.execute("""SELECT candle_time FROM research.delta_candles_provisional
          WHERE source=%s AND symbol=%s AND series_type='PRICE' AND resolution=%s
            AND candle_time >= %s AND candle_time < %s ORDER BY candle_time""",
          (SOURCE,SYMBOL,RESOLUTION,start,end))
        provisional = [r['candle_time'] for r in cur.fetchall()]
        validation = validate_session(session_date, raw, provisional)
        cur.execute("""SELECT revision_number,input_fingerprint,run_id FROM amt_engine.calculation_runs
          WHERE session_date=%s AND method_version=%s AND source=%s AND symbol=%s
            AND execution_status='SUCCEEDED' ORDER BY revision_number DESC,attempt_number DESC LIMIT 1""",
          (session_date,METHOD_VERSION,SOURCE,SYMBOL))
        latest_success = cur.fetchone()
        cur.execute("""SELECT revision_number,attempt_number FROM amt_engine.calculation_runs
          WHERE session_date=%s AND method_version=%s AND source=%s AND symbol=%s
          ORDER BY revision_number,attempt_number""",
          (session_date,METHOD_VERSION,SOURCE,SYMBOL))
        prior = cur.fetchall()
        revision, attempt = assign_revision_attempt(latest_success, prior, validation.input_fingerprint)
        if latest_success is None:
            run_type = 'INITIAL' if attempt == 1 else 'RETRY'
        elif revision > latest_success['revision_number']:
            run_type = 'RESTATEMENT'
        else:
            run_type = 'RETRY'
        first = min((r['candle_time'] for r in raw), default=None)
        last = max((r['candle_time'] for r in raw), default=None)
        report = validation.report
        observed = len({r['candle_time'] for r in raw})
        cur.execute("""INSERT INTO amt_engine.calculation_runs
          (run_id,session_date,method_version,source,symbol,resolution,revision_number,attempt_number,
           run_type,supersedes_run_id,expected_candles,observed_candles,missing_candles,duplicate_candles,
           invalid_ohlc_candles,provisional_candles,input_first_candle,input_last_candle,input_fingerprint,
           input_coverage,validation_report,execution_status)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,48,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)""",
          (run_id,session_date,METHOD_VERSION,SOURCE,SYMBOL,RESOLUTION,revision,attempt,run_type,
           latest_success['run_id'] if run_type=='RESTATEMENT' else None,observed,
           len(report['missing_timestamps']),len(report['duplicate_timestamps']),len(report['invalid_ohlc']),
           len(report['provisional_timestamps']),first,last,validation.input_fingerprint,
           json.dumps({'expected':48,'observed_distinct':observed,'valid_observed':len(validation.candles)}),
           json.dumps(report), 'VALIDATING'))
    conn.commit()

    if not validation.valid:
        with conn.cursor() as cur:
            cur.execute("UPDATE amt_engine.calculation_runs SET execution_status='REJECTED',calculated_at=now(),validation_report=%s::jsonb WHERE run_id=%s",
                        (json.dumps(report),run_id))
        conn.commit()
        return {'run_id':str(run_id),'status':'REJECTED','revision':revision,'attempt':attempt,'report':report}

    try:
        profile, rows = calculate_profile(session_date, validation.candles)
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO amt_engine.daily_profiles
                  (run_id,session_date,method_version,source,symbol,expected_bars,observed_bars,is_complete,
                   missing_candle_count,first_candle,last_candle,total_tpos,poc_lower,poc_upper,poc_tpo_count,
                   vah_lower,vah_upper,val_lower,val_upper,value_area_tpos,session_open,session_high,session_low,session_close)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  (run_id,profile.session_date,METHOD_VERSION,SOURCE,SYMBOL,profile.expected_bars,profile.observed_bars,
                   profile.is_complete,profile.missing_candle_count,profile.first_candle,profile.last_candle,
                   profile.total_tpos,profile.poc_lower,profile.poc_upper,profile.poc_tpo_count,profile.vah_lower,
                   profile.vah_upper,profile.val_lower,profile.val_upper,profile.value_area_tpos,profile.session_open,
                   profile.session_high,profile.session_low,profile.session_close))
                cur.executemany("""INSERT INTO amt_engine.daily_tpo_rows
                  (run_id,row_lower,row_upper,tpo_count,is_poc,is_value_area) VALUES (%s,%s,%s,%s,%s,%s)""",
                  [(run_id,r.row_lower,r.row_upper,r.tpo_count,r.is_poc,r.is_value_area) for r in rows])
                cur.execute("UPDATE amt_engine.calculation_runs SET execution_status='SUCCEEDED',calculated_at=now() WHERE run_id=%s",
                            (run_id,))
        return {'run_id':str(run_id),'status':'SUCCEEDED','revision':revision,'attempt':attempt,
                'profile_rows':1,'tpo_rows':len(rows),'zero_count_rows':sum(r.tpo_count==0 for r in rows)}
    except Exception as exc:
        with conn.cursor() as cur:
            cur.execute("UPDATE amt_engine.calculation_runs SET execution_status='FAILED',calculated_at=now(),validation_report=validation_report || %s::jsonb WHERE run_id=%s",
                        (json.dumps({'calculation_error':str(exc)[:1000]}),run_id))
        conn.commit()
        raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--session-date', help='UTC session date YYYY-MM-DD; defaults to the last fully closed UTC session')
    args=parser.parse_args()
    day=date.fromisoformat(args.session_date) if args.session_date else datetime.now(timezone.utc).date()-timedelta(days=1)
    url=os.environ.get('DATABASE_URL')
    if not url: raise RuntimeError('DATABASE_URL is required')
    with psycopg.connect(url,row_factory=dict_row) as conn:
        result=process_session(conn,day)
    print(json.dumps(result,default=str,sort_keys=True))
    if result['status']!='SUCCEEDED': raise SystemExit(2)

if __name__=='__main__':
    main()
