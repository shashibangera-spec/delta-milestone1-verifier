#!/usr/bin/env python3
"""Read-only BTC Playbook V1.3 HH/HL research slice."""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import psycopg
from psycopg.rows import dict_row
from amt_engine.playbook_v13 import build_signal, evaluate_exit

PROJECT="old-surf-34279165"
TARGET_BRANCH="br-snowy-water-aog0ilqw"
SOURCE_BRANCH="br-lingering-grass-ao07mgrx"
TARGET_HOST="ep-morning-mountain-aopl02wv.c-2.ap-southeast-1.aws.neon.tech"
SOURCE_HOST="ep-sparkling-queen-aoqgp0mw.c-2.ap-southeast-1.aws.neon.tech"
DB="amt_research"; ROLE="amt_dashboard_ro"; SOURCE="delta_india"
SYMBOL="BTCUSD"; METHOD="AMT_ENGINE_V1.7"
START=date(2026,5,21); END=date(2026,11,26); EXCLUDED={date(2026,11,20)}
IST=ZoneInfo("Asia/Kolkata"); BAR=timedelta(minutes=30)
TAKER=0.0005; MAKER=0.0002; GST=1.18

class ResearchError(RuntimeError): pass

def session_start(d):
    return datetime.combine(d,time(5,30),tzinfo=IST).astimezone(timezone.utc)

def connect_ro(url,host,label):
    u=urlparse(url or "")
    if u.scheme not in ("postgres","postgresql") or u.hostname!=host:
        raise ResearchError(f"{label}: URL host does not match pinned branch")
    c=psycopg.connect(url,sslmode="require",row_factory=dict_row)
    try:
        with c.cursor() as q:
            q.execute("SET TRANSACTION READ ONLY")
            q.execute("SELECT current_database() db,current_user usr,session_user su")
            r=q.fetchone()
        if (r["db"],r["usr"],r["su"])!=(DB,ROLE,ROLE):
            raise ResearchError(f"{label}: expected amt_research / amt_dashboard_ro")
        return c
    except Exception:
        c.close()
        raise

def read_profiles(c):
    with c.cursor() as q:
        q.execute("""SELECT session_date,profile_id,profile_status,is_complete,
          expected_bars,observed_bars,vah_upper,val_lower
          FROM amt_engine_v17.session_profiles
          WHERE method_version=%s AND source=%s AND symbol=%s
          AND session_date BETWEEN %s AND %s ORDER BY session_date""",
          (METHOD,SOURCE,SYMBOL,START,END))
        rows=q.fetchall()
    out={}
    for r in rows:
        d=r["session_date"]
        if d in EXCLUDED: continue
        if not r["is_complete"] or r["profile_status"]!="COMPLETE" or r["expected_bars"]!=48 or r["observed_bars"]!=48:
            raise ResearchError(f"{d}: V1.7 profile is not a complete 48-bar profile")
        if r["vah_upper"] is None or r["val_lower"] is None or r["vah_upper"]<=r["val_lower"]:
            raise ResearchError(f"{d}: invalid V1.7 value boundaries")
        out[d]={"profile_id":str(r["profile_id"]),"vah":float(r["vah_upper"]),"val":float(r["val_lower"])}
    expected=[START+timedelta(days=i) for i in range((END-START).days+1) if START+timedelta(days=i) not in EXCLUDED]
    if sorted(out)!=expected or len(out)!=189:
        raise ResearchError(f"Expected 189 complete profiles, found {len(out)}")
    return out

def read_candles(c):
    begin=session_start(START-timedelta(days=2)); finish=session_start(END+timedelta(days=1))
    with c.cursor() as q:
        q.execute("""SELECT candle_time,open_value,high_value,low_value,close_value
          FROM research.delta_candles WHERE source=%s AND series_type='PRICE'
          AND symbol=%s AND resolution='30m' AND candle_time >= %s AND candle_time < %s
          ORDER BY candle_time""",(SOURCE,SYMBOL,begin,finish))
        rows=q.fetchall()
    out=defaultdict(list)
    for r in rows:
        ts=r["candle_time"].astimezone(timezone.utc)
        if any(r[k] is None for k in ("open_value","high_value","low_value","close_value")):
            raise ResearchError(f"{ts}: null OHLC")
        out[ts.date()].append({"timestamp":ts,"open":float(r["open_value"]),
          "high":float(r["high_value"]),"low":float(r["low_value"]),"close":float(r["close_value"])})
    # Pre-window warm-up dates are optional context only. If either is absent,
    # the first in-scope session is classified MIXED and any unavailable
    # prior-session comparison is reported as N/A; the research run continues.
    # The excluded 20 Nov candle rows, if present, remain available only as
    # forward exit data and are not required for sample inclusion.

    # Enforce exact 48-bar completeness only on the 189 approved sessions.
    approved_days=[START+timedelta(days=i) for i in range((END-START).days+1)
                   if START+timedelta(days=i) not in EXCLUDED]
    if len(approved_days)!=189:
        raise ResearchError(f"Internal scope error: expected 189 approved session dates, found {len(approved_days)}")
    for d in approved_days:
        bars=out.get(d,[])
        if len(bars)!=48 or [x["timestamp"] for x in bars]!=[session_start(d)+BAR*i for i in range(48)]:
            raise ResearchError(f"{d}: approved-session PRICE series is not exactly 48 ordered 30m bars")
    return dict(out)

def prior_structure(d,ranges):
    a=ranges.get(d-timedelta(days=1)); b=ranges.get(d-timedelta(days=2))
    if a is None or b is None: return "MIXED"
    if a["high"]>b["high"] and a["low"]>b["low"]: return "HH/HL"
    if a["high"]<b["high"] and a["low"]<b["low"]: return "LL/LH"
    return "MIXED"

def pivot_status(bars,i,trend):
    """2A: strict 2-left/2-right pivots; confirmation bar must close before entry."""
    if trend not in ("HH/HL","LL/LH"): return "N/A"
    known=bars[:i]  # excludes entry candle; pivot's two right bars are already closed
    lows=[]; highs=[]
    for j in range(2,len(known)-2):
        if all(known[j]["low"]<known[k]["low"] for k in (j-2,j-1,j+1,j+2)):
            lows.append((j,known[j]["low"]))
        if all(known[j]["high"]>known[k]["high"] for k in (j-2,j-1,j+1,j+2)):
            highs.append((j,known[j]["high"]))
    if trend=="HH/HL":
        higher_lows=[(cur_idx,cur_val) for (_,prev_val),(cur_idx,cur_val) in zip(lows,lows[1:]) if cur_val>prev_val]
        if not higher_lows: return "INTACT"
        pivot_idx,support=higher_lows[-1]; confirmed_at=pivot_idx+2
        broken=any(bars[k]["close"]<support for k in range(confirmed_at,i+1))
    else:
        lower_highs=[(cur_idx,cur_val) for (_,prev_val),(cur_idx,cur_val) in zip(highs,highs[1:]) if cur_val<prev_val]
        if not lower_highs: return "INTACT"
        pivot_idx,resistance=lower_highs[-1]; confirmed_at=pivot_idx+2
        broken=any(bars[k]["close"]>resistance for k in range(confirmed_at,i+1))
    return "BROKEN" if broken else "INTACT"

def dashboard_status(bars,i,trend,prior_high,prior_low):
    """2B: strictly pre-entry candle extremes against prior completed session range."""
    if trend not in ("HH/HL","LL/LH") or prior_high is None or prior_low is None: return "N/A"
    earlier=bars[:i]
    if trend=="HH/HL": return "BROKEN" if any(x["low"]<prior_low for x in earlier) else "INTACT"
    return "BROKEN" if any(x["high"]>prior_high for x in earlier) else "INTACT"

def fee_r(entry,exit_price,risk,entry_rate):
    if risk<=0: raise ResearchError("non-positive risk in fee calculation")
    return ((entry*entry_rate+exit_price*TAKER)*GST)/risk

def metrics(ts):
    if not ts: return (0,0.0,0.0,0.0,0.0,0.0)
    gross=[t["gross"] for t in ts]; net=[t["gross"]-t["fee_tt"] for t in ts]
    eq=peak=dd=0.0
    for x in net:
        eq+=x; peak=max(peak,eq); dd=max(dd,peak-eq)
    return (len(ts),100*sum(x>0 for x in gross)/len(gross),sum(gross)/len(gross),
            sum(net),sum(t["gross"]-t["fee_mt"] for t in ts),dd)

def print_table(title,groups):
    print("\n"+title)
    print(f"{'Bucket':<37} {'Trades':>6} {'Win %':>8} {'Avg Gross R':>11} {'Net R T/T':>11} {'Net R M/T':>11} {'Max DD R':>10}")
    print("-"*101)
    for label,ts in groups:
        n,w,a,tt,mt,dd=metrics(ts)
        print(f"{label:<37} {n:>6d} {w:>8.2f} {a:>11.3f} {tt:>11.3f} {mt:>11.3f} {dd:>10.3f}")

def self_test():
    b=[{"low":101.,"high":110.,"close":105.},{"low":99.,"high":111.,"close":104.}]
    assert dashboard_status(b,1,"HH/HL",120.,100.)=="INTACT"
    assert dashboard_status(b,2,"HH/HL",120.,100.)=="BROKEN"
    assert dashboard_status(b,2,"LL/LH",110.,90.)=="BROKEN"
    assert fee_r(100,110,10,TAKER)>fee_r(100,110,10,MAKER)
    assert metrics([])[0]==0
    print("OFFLINE SELF-TEST PASS")

def run():
    tu=os.environ.get("V17_TARGET_READONLY_DATABASE_URL")
    su=os.environ.get("V17_SOURCE_DATABASE_URL")
    if not tu or not su: raise ResearchError("Missing read-only target/source secrets")
    with connect_ro(tu,TARGET_HOST,"V1.7 production") as t, connect_ro(su,SOURCE_HOST,"historical source") as s:
        profiles=read_profiles(t); candles=read_candles(s)
    ranges={d:{"high":max(x["high"] for x in b),"low":min(x["low"] for x in b)} for d,b in candles.items()}
    flat=[x for d in sorted(candles) for x in candles[d]]
    index={x["timestamp"]:i for i,x in enumerate(flat)}
    trades=[]; unresolved=0
    for d,p in sorted(profiles.items()):
        bars=candles[d]; trend=prior_structure(d,ranges)
        prior_range=ranges.get(d-timedelta(days=1))
        prior_high=prior_range["high"] if prior_range else None
        prior_low=prior_range["low"] if prior_range else None
        for i,cur in enumerate(bars):
            if i:
                prev=bars[i-1]
            else:
                prior_bars=candles.get(d-timedelta(days=1),[])
                if not prior_bars: continue  # no causal previous candle for first bar
                prev={"close":prior_bars[-1]["close"]}
            sig=build_signal(prev,cur,p["vah"],p["val"])
            if sig is None: continue
            outcome=None
            for future in flat[index[cur["timestamp"]]+1:]:
                outcome=evaluate_exit({"side":sig.side,"stop_price":sig.stop_price,"target_price":sig.target_price},future)
                if outcome is not None: break
            if outcome is None: unresolved+=1; continue
            xp=float(outcome["exit_price"]); gross=float(outcome["realized_r"])
            trades.append({"date":d,"pattern":sig.pattern,"side":sig.side,"trend":trend,
              "gross":gross,"fee_tt":fee_r(sig.entry_price,xp,sig.risk_points,TAKER),
              "fee_mt":fee_r(sig.entry_price,xp,sig.risk_points,MAKER),
              "2a":pivot_status(bars,i,trend),
              "2b":dashboard_status(bars,i,trend,prior_high,prior_low)})
    print("BTCUSD | Playbook V1.3 | 30m | 05:30 IST | 21 May–26 Nov 2026")
    print("V1.7 profiles: 189 complete; 20 Nov incomplete excluded; active 27 Nov excluded.")
    print("Fees: Delta India BTCUSD taker 0.05%, maker 0.02%; 18% GST on both legs.")
    print("Signals are evaluated independently with exact V1.3 build_signal/evaluate_exit; stop-first ambiguity retained.")
    print("No time-based exit is invented: unresolved trades are excluded from completed-trade metrics.")
    print("Max DD uses chronological cumulative Taker/Taker + GST net R.")
    print("2A: without two confirmed swing lows/highs establishing HL/LH, status remains INTACT until a confirmed break.")
    cats=[("Long HH/HL","LONG","HH/HL"),("Long LL/LH","LONG","LL/LH"),("Long Mixed","LONG","MIXED"),
          ("Short LL/LH","SHORT","LL/LH"),("Short HH/HL","SHORT","HH/HL"),("Short Mixed","SHORT","MIXED")]
    print_table("TABLE 1 — PRIOR COMPLETED SESSION RANGE STRUCTURE",
      [(label,[x for x in trades if x["side"]==side and x["trend"]==trend]) for label,side,trend in cats])
    print("\nTABLE 2 — CAUSAL LIVE INTRADAY STRUCTURE AT ENTRY (2A vs 2B SIDE BY SIDE)")
    print(f"{'Bucket':<25} {'2A N':>5} {'Win%':>6} {'AvgR':>7} {'NetTT':>8} {'NetMT':>8} {'DD':>7} | {'2B N':>5} {'Win%':>6} {'AvgR':>7} {'NetTT':>8} {'NetMT':>8} {'DD':>7}")
    print("-"*120)
    for pattern in ("A","B"):
        for status in ("INTACT","BROKEN"):
            label=f"Pattern {pattern} — {status}"
            n1=metrics([x for x in trades if x["pattern"]==pattern and x["2a"]==status])
            n2=metrics([x for x in trades if x["pattern"]==pattern and x["2b"]==status])
            print(f"{label:<25} {n1[0]:>5d} {n1[1]:>6.2f} {n1[2]:>7.3f} {n1[3]:>8.3f} {n1[4]:>8.3f} {n1[5]:>7.3f} | {n2[0]:>5d} {n2[1]:>6.2f} {n2[2]:>7.3f} {n2[3]:>8.3f} {n2[4]:>8.3f} {n2[5]:>7.3f}")
    mixed1=metrics([x for x in trades if x["trend"]=="MIXED" and x["2a"]=="N/A"])
    mixed2=metrics([x for x in trades if x["trend"]=="MIXED" and x["2b"]=="N/A"])
    print(f"{'Mixed prior — N/A':<25} {mixed1[0]:>5d} {mixed1[1]:>6.2f} {mixed1[2]:>7.3f} {mixed1[3]:>8.3f} {mixed1[4]:>8.3f} {mixed1[5]:>7.3f} | {mixed2[0]:>5d} {mixed2[1]:>6.2f} {mixed2[2]:>7.3f} {mixed2[3]:>8.3f} {mixed2[4]:>8.3f} {mixed2[5]:>7.3f}")
    print(f"\nCompleted trades: {len(trades)} | Unresolved signals excluded: {unresolved}")

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    try: self_test() if a.self_test else run(); return 0
    except Exception as e: print(f"Research stopped safely: {e}",file=sys.stderr); return 1

if __name__=="__main__": raise SystemExit(main())
