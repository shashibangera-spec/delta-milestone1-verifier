from datetime import datetime, date, timezone, timedelta

from amt_engine.playbook_v14 import build_signal, classify_sub_session, evaluate_exit
from amt_engine.playbook_v14_shadow_logger import _count_open_events, _is_contiguous_30m


def candle(open_, high, low, close):
    return {"open": open_, "high": high, "low": low, "close": close}


def test_pattern_a_long_uses_five_percent_prior_value_width_and_two_r_target():
    s=build_signal(candle(1150,1200,1100,1150),candle(1150,1200,1000,1150),2000,1000)
    assert s is not None and (s.pattern,s.side)==("A","LONG")
    assert s.buffer_points==50.0 and s.stop_price==950.0
    assert s.risk_points==200.0 and s.target_price==1550.0


def test_minimum_stop_width_rejects_199_and_accepts_200():
    accepted=build_signal(candle(1149,1200,1100,1149),candle(1149,1200,1000,1149),2000,1000)
    exact=build_signal(candle(1150,1200,1100,1150),candle(1150,1200,1000,1150),2000,1000)
    assert accepted is None
    assert exact is not None and exact.risk_points==200.0


def test_pattern_b_is_disabled_even_when_old_v13_pattern_b_would_trigger():
    assert build_signal(candle(2010,2020,2000,2015),candle(2015,2025,1990,2010),2000,1000) is None


def test_pattern_a_short_and_upper_side_priority_are_preserved():
    s=build_signal(candle(1500,1550,1490,1500),candle(1500,2650,950,1500),2000,1000)
    assert s is not None and (s.pattern,s.side)==("A","SHORT")


def test_subsession_half_open_utc_boundaries():
    def at(h,m=0): return datetime(2026,11,27,h,m,tzinfo=timezone.utc)
    assert classify_sub_session(at(0))=="Asia"
    assert classify_sub_session(at(7,59))=="Asia"
    assert classify_sub_session(at(8))=="Europe"
    assert classify_sub_session(at(13,29))=="Europe"
    assert classify_sub_session(at(13,30)) is None
    assert classify_sub_session(at(23,59)) is None


def test_exit_remains_stop_first_and_target_two_r():
    t={"side":"LONG","stop_price":950,"target_price":1550,"risk_points":200}
    assert evaluate_exit(t,candle(1500,1950,900,1200))=={
        "exit_reason":"STOP_FIRST_AMBIGUOUS","exit_price":1300.0,"realized_r":-1.0}
    assert evaluate_exit(t,candle(1500,1600,1000,1500))=={
        "exit_reason":"TARGET_2R","exit_price":1900.0,"realized_r":2.0}


class FakeCursor:
    def __init__(self, count): self.count=count; self.query=None; self.params=None
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self, query, params): self.query=query; self.params=params
    def fetchone(self): return {"entry_count":self.count}


class FakeConn:
    def __init__(self,count): self.cur=FakeCursor(count)
    def cursor(self): return self.cur


def test_durable_open_event_cap_survives_exit_and_restart():
    # The event count remains one even though the associated trade is now CLOSED.
    # Re-instantiating the connection simulates a logger process restart.
    c1=FakeConn(1)
    assert _count_open_events(c1,date(2026,11,27),"Asia")==1
    c2=FakeConn(1)
    assert _count_open_events(c2,date(2026,11,27),"Asia")==1
    assert "event_type='OPEN'" in c2.cur.query
    assert "playbook_v14_shadow_events" in c2.cur.query
    assert c2.cur.params[0]=="2026-11-27"
    assert c2.cur.params[1]=="Asia"
    assert c2.cur.params[2]==datetime(2026,11,27,0,0,tzinfo=timezone.utc)
    assert c2.cur.params[3]==datetime(2026,11,27,8,0,tzinfo=timezone.utc)


def test_asia_and_europe_caps_are_independent():
    asia=FakeConn(1)
    europe=FakeConn(0)
    assert _count_open_events(asia,date(2026,11,27),"Asia")==1
    assert _count_open_events(europe,date(2026,11,27),"Europe")==0
    assert europe.cur.params[0]=="2026-11-27"
    assert europe.cur.params[1]=="Europe"
    assert europe.cur.params[2]==datetime(2026,11,27,8,0,tzinfo=timezone.utc)
    assert europe.cur.params[3]==datetime(2026,11,27,13,30,tzinfo=timezone.utc)


def test_shadow_identity_is_v14_and_no_order_execution_imports():
    from pathlib import Path
    source=Path("amt_engine/playbook_v14_shadow_logger.py").read_text()
    assert '"SHADOW_V1_4"' in source
    assert "exchange.create_order" not in source
    assert "create_order(" not in source


def test_midnight_candle_continuity_and_gap_guard_are_preserved():
    previous={"candle_time":datetime(2026,11,26,23,30,tzinfo=timezone.utc)}
    midnight=datetime(2026,11,27,0,0,tzinfo=timezone.utc)
    assert _is_contiguous_30m(previous,midnight)
    gap={"candle_time":datetime(2026,11,26,23,0,tzinfo=timezone.utc)}
    assert not _is_contiguous_30m(gap,midnight)


def test_logger_reads_only_completed_candles_and_is_shadow_only():
    from pathlib import Path
    source=Path("amt_engine/playbook_v14_shadow_logger.py").read_text()
    assert "candle_time + interval '30 minutes' <= %s" in source
    assert '"SHADOW_V1_4"' in source
    assert 'record_playbook_v14_shadow_event(%s,%s,%s,%s::jsonb)' in source
    assert "create_order(" not in source
