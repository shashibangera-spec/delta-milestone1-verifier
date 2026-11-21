"""Read-only historical parity checker. Never writes to either Neon branch."""
from __future__ import annotations
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import psycopg
from psycopg.rows import dict_row
from amt_engine.daily import SOURCE, SYMBOL, RESOLUTION, validate_session, calculate_profile

LIVE_URL = os.environ.get('LIVE_DATABASE_URL')
REFERENCE_URL = os.environ.get('REFERENCE_DATABASE_URL')


def _connect_readonly(url):
    if not url:
        raise RuntimeError('Both LIVE_DATABASE_URL and REFERENCE_DATABASE_URL are required')
    return psycopg.connect(url, options='-c default_transaction_read_only=on', row_factory=dict_row)


def run_parity():
    mismatches = []
    with _connect_readonly(LIVE_URL) as live, _connect_readonly(REFERENCE_URL) as reference:
        with reference.cursor() as cur:
            cur.execute('SELECT * FROM amt_engine.session_profiles WHERE is_complete = true ORDER BY session_date')
            profiles = cur.fetchall()
            cur.execute('SELECT * FROM amt_engine.tpo_rows ORDER BY session_date,row_lower')
            ref_rows = cur.fetchall()
        if len(profiles) != 183 or len(ref_rows) != 8113:
            raise RuntimeError(f'Reference inventory mismatch: profiles={len(profiles)}, rows={len(ref_rows)}')
        rows_by_date = {}
        for row in ref_rows:
            rows_by_date.setdefault(row['session_date'], []).append(row)
        calculated_profiles = 0
        calculated_rows = 0
        for ref in profiles:
            day = ref['session_date']
            start_utc = datetime.combine(day, time.min, tzinfo=timezone.utc)
            end_utc = start_utc + timedelta(days=1)
            with live.cursor() as cur:
                cur.execute('''SELECT candle_time,open_value,high_value,low_value,close_value
                  FROM research.delta_candles
                  WHERE source=%s AND symbol=%s AND series_type='PRICE' AND resolution=%s
                    AND candle_time >= %s AND candle_time < %s
                  ORDER BY candle_time''', (SOURCE,SYMBOL,RESOLUTION,start_utc,end_utc))
                raw = cur.fetchall()
                cur.execute('''SELECT candle_time FROM research.delta_candles_provisional
                  WHERE source=%s AND symbol=%s AND series_type='PRICE' AND resolution=%s
                    AND candle_time >= %s AND candle_time < %s''',
                    (SOURCE,SYMBOL,RESOLUTION,start_utc,end_utc))
                provisional = [r['candle_time'] for r in cur.fetchall()]
            validated = validate_session(day, raw, provisional)
            if not validated.valid:
                mismatches.append({'session_date':str(day),'kind':'INPUT_INVALID','report':validated.report})
                continue
            calc, calc_rows = calculate_profile(day, validated.candles)
            calculated_profiles += 1
            fields = ('expected_bars','observed_bars','is_complete','missing_candle_count','first_candle','last_candle','total_tpos',
                      'poc_lower','poc_upper','poc_tpo_count','vah_lower','vah_upper','val_lower','val_upper','value_area_tpos')
            calculated = {'expected_bars':calc.expected_bars,'observed_bars':calc.observed_bars,
                'is_complete':calc.is_complete,'missing_candle_count':calc.missing_candle_count,
                'first_candle':calc.first_candle,'last_candle':calc.last_candle,'total_tpos':calc.total_tpos,'poc_lower':calc.poc_lower,'poc_upper':calc.poc_upper,
                'poc_tpo_count':calc.poc_tpo_count,'vah_lower':calc.vah_lower,'vah_upper':calc.vah_upper,
                'val_lower':calc.val_lower,'val_upper':calc.val_upper,'value_area_tpos':calc.value_area_tpos}
            for field in fields:
                if calculated[field] != ref[field]:
                    mismatches.append({'session_date':str(day),'kind':'PROFILE_FIELD','field':field,
                                       'expected':str(ref[field]),'actual':str(calculated[field])})
            expected_rows = rows_by_date.get(day, [])
            actual_rows = {(r.row_lower):r for r in calc_rows}
            calculated_rows += len(calc_rows)
            expected_map = {r['row_lower']:r for r in expected_rows}
            if set(actual_rows) != set(expected_map):
                mismatches.append({'session_date':str(day),'kind':'TPO_ROW_KEYS',
                                   'expected_count':len(expected_map),'actual_count':len(actual_rows)})
            for key in sorted(set(actual_rows) & set(expected_map)):
                a,e=actual_rows[key],expected_map[key]
                for field,actual in (('row_upper',a.row_upper),('tpo_count',a.tpo_count),('is_poc',a.is_poc),('is_value_area',a.is_value_area)):
                    if actual != e[field]:
                        mismatches.append({'session_date':str(day),'kind':'TPO_FIELD','row_lower':str(key),
                                           'field':field,'expected':str(e[field]),'actual':str(actual)})
        print({'reference_profiles':len(profiles),'reference_tpo_rows':len(ref_rows),
               'calculated_profiles':calculated_profiles,'calculated_tpo_rows':calculated_rows,
               'mismatch_count':len(mismatches),'mismatches':mismatches[:100],
               'historical_session_assignment':'CONDITIONAL — parity does not independently prove source session assignment',
               'reference_branch_write_count':0,'live_branch_write_count':0})
        return 1 if mismatches else 0


if __name__ == '__main__':
    raise SystemExit(run_parity())
