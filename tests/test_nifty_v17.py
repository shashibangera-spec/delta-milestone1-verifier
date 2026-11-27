from datetime import date,datetime,time,timedelta
import pandas as pd
import pytest
from amt_engine.nifty_v17 import EXPECTED_DATES,EXPECTED_HOST,WRITER_ROLE,aggregate_session,calculate_profile,canonical_sha,classify_session,profile_rows,validate_54_sessions,validate_writer_url

def synthetic(days):
 rows=[]
 for d in days:
  start=datetime.combine(d,time(9,15))
  for i in range(25):
   t=start+timedelta(minutes=15*i); base=25000+(i%5)*10
   rows.append({"timestamp":pd.Timestamp(t,tz="Asia/Kolkata"),"open":base,"high":base+19,"low":base-9,"close":base+5})
 f=pd.DataFrame(rows); f["session_date"]=f.timestamp.dt.date; return f

def test_13_brackets_and_13_developing_snapshots():
 d=date(2026,11,26); f=synthetic([d]); bars,diag=aggregate_session(f,d)
 assert len(bars)==13 and diag["received_15m"]==25 and not diag["missing_brackets"]
 s,snaps,_=profile_rows(f,d); assert s["is_complete"] and len(snaps)==13
 assert snaps[0]["completed_brackets"]==1 and snaps[-1]["completed_brackets"]==13

def test_missing_final_15m_candle_is_not_a_complete_session():
 d=date(2026,11,26); f=synthetic([d]).iloc[:-1]; bars,diag=aggregate_session(f,d)
 assert len(bars)==12 and 13 in diag["missing_brackets"]
 with pytest.raises(ValueError,match="expected 25"): profile_rows(f,d)

def test_54_session_yahoo_gate_checks_exact_date_set_and_sha256():
 result=validate_54_sessions(synthetic(EXPECTED_DATES))
 assert result["expected_sessions"]==result["observed_sessions"]==54
 assert result["first_session"]=="2026-09-07" and result["last_session"]=="2026-11-26"
 assert len(result["dataset_sha256"])==64

def test_54_session_gate_fails_closed_when_a_session_is_missing():
 with pytest.raises(ValueError,match="54-session Yahoo validation failed"): validate_54_sessions(synthetic(EXPECTED_DATES[:-1]))

def test_sha256_is_order_independent_for_mapping_keys():
 assert canonical_sha({"a":1,"b":2})==canonical_sha({"b":2,"a":1})
 assert canonical_sha({"a":1})!=canonical_sha({"a":2})

def test_profile_has_10_point_inclusive_rows_and_poc_midpoint():
 p=calculate_profile([{"low":100,"high":120},{"low":100,"high":120}])
 assert p["poc"]==105 and p["val"]==100 and p["vah"]>=110

def test_first_session_close_location_is_still_classified():
 r=classify_session({"session_close":105,"vah":100,"val":90},None)
 assert r["close_location"]=="ABOVE VAH" and r["value_migration"]=="FIRST SESSION"

def test_mixed_value_does_not_get_false_migration_label():
 prior={"vah":110,"poc":100,"val":90,"session_high":120,"session_low":80}
 cur={"vah":111,"poc":101,"val":89,"session_close":100,"session_high":121,"session_low":81}
 r=classify_session(cur,prior); assert r["value_migration"]=="VALUE OVERLAP / MIXED" and r["range_structure"]=="HH/HL"

def test_writer_url_is_pinned_to_role_branch_and_database():
 good=f"postgresql://{WRITER_ROLE}:secret@{EXPECTED_HOST}/amt_research?sslmode=require"
 assert validate_writer_url(good).hostname==EXPECTED_HOST
 with pytest.raises(RuntimeError,match="host"): validate_writer_url(f"postgresql://{WRITER_ROLE}:secret@wrong.neon.tech/amt_research")
 with pytest.raises(RuntimeError,match="must use"): validate_writer_url(f"postgresql://other:secret@{EXPECTED_HOST}/amt_research")


def test_dashboard_adds_nifty_tab_without_changing_default_btc_view():
    from browser_dashboard.main import HTML, app
    assert "BTCUSD" in HTML and "NIFTY 50 SPOT" in HTML
    assert "let activeMarket='btc'" in HTML
    assert 'id="btc-view"' in HTML and 'id="nifty-view"' in HTML
    assert any(route.path == "/api/nifty-overview" for route in app.routes)
