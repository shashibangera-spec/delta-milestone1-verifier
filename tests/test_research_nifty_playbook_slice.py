from datetime import date, time
import pandas as pd
import pytest

from scripts.research_nifty_playbook_slice import (
    build_report, replay_pattern_a, select_scenario_trades, summarize,
    validate_readonly_url, validate_and_match_sessions,
)
from amt_engine.nifty_v17 import EXPECTED_HOST


def test_readonly_database_url_requires_pinned_reader_role_and_database():
    good=f"postgresql://amt_dashboard_ro:secret@{EXPECTED_HOST}/amt_research"
    assert validate_readonly_url(good).hostname == EXPECTED_HOST
    with pytest.raises(RuntimeError, match="read-only"):
        validate_readonly_url(f"postgresql://amt_nifty_writer_login:secret@{EXPECTED_HOST}/amt_research")


def test_session_matching_requires_all_13_brackets_and_exact_v17_profile():
    day=date(2026, 11, 27)
    rows=[]
    for i in range(25):
        ts=pd.Timestamp(f"2026-11-27 09:15",tz="Asia/Kolkata")+pd.Timedelta(minutes=15*i)
        rows.append({"timestamp":ts,"open":25000,"high":25020,"low":24990,"close":25010,"session_date":day})
    frame=pd.DataFrame(rows)
    from amt_engine.nifty_v17 import aggregate_session, calculate_profile
    bars,_=aggregate_session(frame,day); profile=calculate_profile(bars)
    stored={"session_date":day,"symbol":"^NSEI","method_version":"AMT_NIFTY_V1.7",
            "row_size":10,"value_area_fraction":.70,"expected_brackets":13,
            "observed_brackets":13,"is_complete":True,**profile}
    matched,excluded=validate_and_match_sessions(frame,[stored])
    assert len(matched)==1 and not excluded
    matched,excluded=validate_and_match_sessions(frame.iloc[:-1],[stored])
    assert not matched and excluded[0]["reason"]=="INCOMPLETE_13_BRACKET_SESSION"


def test_one_trade_per_day_keeps_first_eligible_signal_and_minimum_risk():
    trades=[
        {"date":"2026-11-02","entry_time":"10:00","entry_bracket":2,"risk_points":24,"realized_r":2,"window":"Morning"},
        {"date":"2026-11-02","entry_time":"10:30","entry_bracket":3,"risk_points":31,"realized_r":-1,"window":"Morning"},
        {"date":"2026-11-03","entry_time":"11:00","entry_bracket":4,"risk_points":30,"realized_r":2,"window":"Morning"},
    ]
    chosen=select_scenario_trades(trades,25,True)
    assert [t["entry_time"] for t in chosen]==["10:30","11:00"]
    assert len(select_scenario_trades(trades,30,True))==2


def test_summary_reports_gross_and_both_cost_scenarios_separately():
    result=summarize([
        {"realized_r":2.0,"risk_points":50},
        {"realized_r":-1.0,"risk_points":25},
    ])
    assert result["trades"]==2
    assert result["total_gross_r"]==1.0
    assert result["costs"]["2.0"]["total_cost_r"]==pytest.approx(.12)
    assert result["costs"]["3.0"]["total_cost_r"]==pytest.approx(.18)
