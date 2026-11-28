#!/usr/bin/env python3
"""Read-only 189-session BTC sub-session regime audit (Playbook v1.4 + Test B)."""
from __future__ import annotations
import argparse, json, os, sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from urllib.parse import urlparse

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from amt_engine.daily import validate_session, calculate_profile
from amt_engine.playbook_v14 import build_signal, classify_discovery, evaluate_exit

PROJECT="old-surf-34279165"; TARGET_BRANCH="br-snowy-water-aog0ilqw"; SOURCE_BRANCH="br-lingering-grass-ao07mgrx"
TARGET_HOST="ep-morning-mountain-aopl02wv.c-2.ap-southeast-1.aws.neon.tech"
SOURCE_HOST="ep-sparkling-queen-aoqgp0mw.c-2.ap-southeast-1.aws.neon.tech"
DB="amt_research"; ROLE="amt_dashboard_ro"; SOURCE="delta_india"; SYMBOL="BTCUSD"
START=date(2026,5,21); END=date(2026,11,25); EXPECTED_SESSIONS=189; BAR=timedelta(minutes=30); UTC=timezone.utc
ROW=Decimal("50"); VA=Decimal("0.70"); TAKER=0.0005; MAKER=0.0002; GST=1.18
WINDOWS=(("Prior US Overnight",-4,0,8),("Asia",0,8,16),("Europe",8,13.5,11),("US Cash",13.5,24,21))

class AuditError(RuntimeError): pass

def session_start(d): return datetime.combine(d,time.min,tzinfo=UTC)
def session_dates(): return [START+timedelta(days=i) for i in range((END-START).days+1)]

def connect_ro(url, host, label):
    import psycopg
    from psycopg.rows import dict_row
    p=urlparse(url or "")
    if p.scheme not in ("postgres","postgresql") or p.hostname!=host: raise AuditError(f"{label}: URL does not match pinned branch host")
    c=psycopg.connect(url,sslmode="require",row_factory=dict_row,options="-c default_transaction_read_only=on")
    try:
        with c.cursor() as q:
            q.execute("SELECT current_database() db,current_user usr,session_user su,current_setting('transaction_read_only') ro")
            x=q.fetchone()
        if (x["db"],x["usr"],x["su"],x["ro"])!=(DB,ROLE,ROLE,"on"): raise AuditError(f"{label}: read-only identity check failed: {x}")
        return c
    except Exception: c.close(); raise

def read_candles(conn):
    begin=session_start(START)-timedelta(hours=4); end=session_start(END+timedelta(days=1))
    with conn.cursor() as q:
        q.execute("""SELECT candle_time,open_value,high_value,low_value,close_value FROM research.delta_candles
          WHERE source=%s AND series_type='PRICE' AND symbol=%s AND resolution='30m' AND candle_time >= %s AND candle_time < %s ORDER BY candle_time""",(SOURCE,SYMBOL,begin,end))
        rows=q.fetchall()
    out={}
    for r in rows:
        ts=r["candle_time"].astimezone(UTC); vals=[r[k] for k in ("open_value","high_value","low_value","close_value")]
        if any(v is None for v in vals) or ts in out: raise AuditError(f"Null OHLC or duplicate at {ts}")
        o,h,l,c=map(float,vals)
        if h<max(o,c,l) or l>min(o,c,h): raise AuditError(f"Invalid OHLC at {ts}")
        out[ts]={"candle_time":ts,"open":o,"high":h,"low":l,"close":c}
    in_scope=sum(1 for ts in out if START <= ts.date() <= END)
    if in_scope!=EXPECTED_SESSIONS*48: raise AuditError(f"Expected {EXPECTED_SESSIONS*48} in-scope candles, found {in_scope}")
    warmup=session_start(START)-timedelta(hours=4)
    if any(warmup+BAR*i not in out for i in range(8)): raise AuditError("Missing prior US overnight warm-up candles for first session")
    for d in session_dates():
        expected=[session_start(d)+BAR*i for i in range(48)]
        if any(t not in out for t in expected): raise AuditError(f"{d}: missing 30m slot")
    return out

def read_profiles(conn):
    with conn.cursor() as q:
        q.execute("""SELECT session_date,profile_status,is_complete,expected_bars,observed_bars,vah_upper,val_lower FROM amt_engine_v17.session_profiles
          WHERE method_version='AMT_ENGINE_V1.7' AND source=%s AND symbol=%s AND session_date BETWEEN %s AND %s ORDER BY session_date""",(SOURCE,SYMBOL,START,END))
        rows=q.fetchall()
    bydate={r["session_date"]:r for r in rows}
    if len(bydate)!=EXPECTED_SESSIONS or sorted(bydate)!=session_dates(): raise AuditError(f"Expected 189 V1.7 profile dates, found {len(bydate)}")
    for d,r in bydate.items():
        if not r["is_complete"] or r["profile_status"]!="COMPLETE" or r["expected_bars"]!=48 or r["observed_bars"]!=48 or r["vah_upper"] is None or r["val_lower"] is None: raise AuditError(f"{d}: profile not COMPLETE 48/48 with VA levels")
    return bydate

def validate_days(candles):
    profiles={}; daybars={}
    for d in session_dates():
        rows=[]
        for i in range(48):
            x=candles[session_start(d)+BAR*i]
            rows.append({"candle_time":x["candle_time"],"open_value":x["open"],"high_value":x["high"],"low_value":x["low"],"close_value":x["close"]})
        v=validate_session(d,rows)
        if not v.valid: raise AuditError(f"{d}: canonical daily session validation failed: {v.report}")
        p,_=calculate_profile(d,v.candles)
        profiles[d]=p; daybars[d]=[candles[session_start(d)+BAR*i] for i in range(48)]
    return profiles,daybars

def subprofile(bars):
    """Dashboard's exact $50 / 70% TPO: floor-grid, lower POC tie, left-first VA expansion."""
    if not bars: return None
    counts={}
    for b in bars:
        lo=int((Decimal(str(b["low"]))/ROW).to_integral_value(rounding=ROUND_FLOOR)); hi=int((Decimal(str(b["high"]))/ROW).to_integral_value(rounding=ROUND_FLOOR))
        if lo<0 or hi<lo: raise AuditError("Invalid price range for TPO profile")
        for k in range(lo,hi+1): counts[k]=counts.get(k,0)+1
    mn,mx=min(counts),max(counts); dense={i:counts.get(i,0) for i in range(mn,mx+1)}
    poc=min(dense,key=lambda k:(-dense[k],k)); target=int((Decimal(sum(dense.values()))*VA).to_integral_value(rounding=ROUND_CEILING))
    lo=hi=poc; covered=dense[poc]
    while covered<target and (lo>mn or hi<mx):
        left=dense.get(lo-1,0); right=dense.get(hi+1,0)
        if lo==mn: choose_left=False
        elif hi==mx: choose_left=True
        else: choose_left=left>=right
        if choose_left: lo-=1; covered+=left
        else: hi+=1; covered+=right
    return {"val":Decimal(lo*50),"poc":Decimal(poc*50+25),"vah":Decimal((hi+1)*50)}

def value_regime(cur,prev):
    if cur is None or prev is None: return "UNAVAILABLE"
    a=(cur["val"],cur["poc"],cur["vah"]); b=(prev["val"],prev["poc"],prev["vah"])
    if cur["val"] > prev["val"] and cur["vah"] > prev["vah"]: return "VALUE STEPPED UP"
    if cur["val"] < prev["val"] and cur["vah"] < prev["vah"]: return "VALUE STEPPED DOWN"
    return "OVERLAPPING / INSIDE"

def build_blocks(daybars):
    result={}
    for d in session_dates():
        prior=[b for b in daybars.get(d-timedelta(days=1),[]) if b["candle_time"].hour>=20]
        specs=[("Prior US Overnight",prior,8)]
        b=daybars[d]
        specs.extend((("Asia",b[:16],16),("Europe",b[16:27],11),("US Cash",b[27:],21)))
        result[d]={}; prev=None
        for name,bars,need in specs:
            complete=bars if len(bars)==need else []
            prof=subprofile(complete) if complete else None
            regime=value_regime(prof,prev)
            result[d][name]={"bars":complete,"profile":prof,"regime":regime}
            if prof is not None: prev=prof
    return result

def fee_r(entry,exitp,risk,entry_rate): return ((entry*entry_rate+exitp*TAKER)*GST)/risk

def resolve(entry_idx,side,entry,stop,target,ordered):
    trade={"side":side,"stop_price":stop,"target_price":target}
    for b in ordered[entry_idx+1:]:
        outcome=evaluate_exit(trade,{"high":b["high"],"low":b["low"],"close":b["close"]})
        if outcome is not None:
            exitp=float(outcome["exit_price"]); gross=float(outcome["realized_r"]); risk=abs(entry-stop)
            return {"gross_r":gross,"net_tt":gross-fee_r(entry,exitp,risk,TAKER),"net_mt":gross-fee_r(entry,exitp,risk,MAKER),"exit_time":b["candle_time"],"exit_reason":outcome["exit_reason"]}
    return None

def summarize(rows):
    n=len(rows)
    if not n:return {"trades":0,"win_pct":None,"avg_gross_r":None,"net_r_tt":0.0,"net_r_mt":0.0,"max_dd_r":0.0}
    rr=sorted(rows,key=lambda x:x["entry_time"]); equity=peak=dd=0.0
    for x in rr: equity+=x["net_tt"]; peak=max(peak,equity); dd=max(dd,peak-equity)
    return {"trades":n,"win_pct":100*sum(x["gross_r"]>0 for x in rr)/n,"avg_gross_r":sum(x["gross_r"] for x in rr)/n,"net_r_tt":sum(x["net_tt"] for x in rr),"net_r_mt":sum(x["net_mt"] for x in rr),"max_dd_r":dd}

def test_a(daybars,daily_profiles,blocks):
    flat=sorted((b for day in daybars.values() for b in day),key=lambda x:x["candle_time"]); idx={b["candle_time"]:i for i,b in enumerate(flat)}
    trades=[]; unresolved=0; signal_count=0
    for d in session_dates()[1:]:
        prevprof=daily_profiles[d-timedelta(days=1)]; vah=float(prevprof.vah_upper); val=float(prevprof.val_lower)
        for name in ("Asia","Europe"):
            bars=blocks[d][name]["bars"]; regime=blocks[d][name]["regime"]
            if not bars or regime=="UNAVAILABLE": continue
            for b in bars:
                i=idx[b["candle_time"]]; previous=flat[i-1] if i else None
                if previous is None: continue
                sig=build_signal({"close":previous["close"]},{"open":b["open"],"high":b["high"],"low":b["low"],"close":b["close"]},vah,val)
                if sig is None: continue
                signal_count+=1
                outcome=resolve(i,sig.side,sig.entry_price,sig.stop_price,sig.target_price,flat)
                if outcome is None: unresolved+=1; break
                trades.append({**outcome,"entry_time":b["candle_time"]+BAR,"sub_session":name,"regime":regime,"side":sig.side,"discovery":classify_discovery([x["close"] for x in daybars[d] if x["candle_time"]<=b["candle_time"]],vah,val)})
                break
    groups={k:summarize([t for t in trades if t["regime"]==k]) for k in ("OVERLAPPING / INSIDE","VALUE STEPPED UP","VALUE STEPPED DOWN")}
    return {"signal_count":signal_count,"unresolved":unresolved,"trades":len(trades),"by_preceding_subsession_regime":groups,"trades_detail":trades}

def test_b(daybars,blocks):
    flat=sorted((b for day in daybars.values() for b in day),key=lambda x:x["candle_time"]); idx={b["candle_time"]:i for i,b in enumerate(flat)}
    events=[]; controls=[]; unresolved=0
    for d in session_dates():
        prior_name="Prior US Overnight"
        for name in ("Asia","Europe","US Cash"):
            cur=blocks[d][name]; prev=blocks[d][prior_name]; bars=cur["bars"]; pp=prev["profile"]; cp=cur["profile"]
            if bars and pp and cp:
                entrybar=bars[-1]; entry=entrybar["close"]; low=min(b["low"] for b in bars); ci=idx[entrybar["candle_time"]]
                # Same date/sub-session final completed candle; unconditional long, fixed $200 risk, 2R.
                co=resolve(ci,"LONG",entry,entry-200.0,entry+400.0,flat)
                if co is not None: controls.append({**co,"entry_time":entrybar["candle_time"]+BAR,"sub_session":name})
                else: unresolved+=1
                if low<float(pp["val"]) and float(pp["val"])<entry<float(pp["vah"]) and cur["regime"]=="OVERLAPPING / INSIDE":
                    stop=min(low,entry-200.0); risk=entry-stop; target=entry+2*risk
                    outcome=resolve(ci,"LONG",entry,stop,target,flat)
                    if outcome is None: unresolved+=1
                    else: events.append({**outcome,"entry_time":entrybar["candle_time"]+BAR,"sub_session":name,"risk_points":risk})
            prior_name=name
    return {"events":summarize(events),"matched_unconditional_final_bar_controls":summarize(controls),"event_count":len(events),"control_count":len(controls),"unresolved_or_censored":unresolved}

def self_test():
    assert [(a,b,n) for _,a,b,n in WINDOWS]==[(-4,0,8),(0,8,16),(8,13.5,11),(13.5,24,21)]
    p=subprofile([{"low":100,"high":199},{"low":100,"high":199},{"low":150,"high":249},{"low":150,"high":249}])
    assert p=={"val":Decimal("100"),"poc":Decimal("175"),"vah":Decimal("200")}
    assert value_regime({"val":200,"poc":225,"vah":250},{"val":100,"poc":125,"vah":150})=="VALUE STEPPED UP"
    assert value_regime({"val":100,"poc":175,"vah":150},{"val":100,"poc":125,"vah":150})=="OVERLAPPING / INSIDE"
    assert value_regime({"val":200,"poc":100,"vah":250},{"val":100,"poc":225,"vah":150})=="VALUE STEPPED UP"
    assert fee_r(10000,10200,200,TAKER)>fee_r(10000,10200,200,MAKER)
    assert summarize([])["trades"]==0
    s=build_signal({"close":500.0},{"open":500.0,"high":800.0,"low":450.0,"close":550.0},600.0,400.0)
    assert s is not None and s.pattern=="A" and s.side=="SHORT" and s.entry_price==550.0 and s.risk_points>=200
    assert classify_discovery([350.0],600.0,400.0)=="DISCOVERY_BELOW"
    out=evaluate_exit({"side":"LONG","stop_price":90,"target_price":120},{"high":130,"low":80,"close":100})
    assert out["exit_reason"]=="STOP_FIRST_AMBIGUOUS" and out["realized_r"]==-1.0
    print("OFFLINE SUB-SESSION REGIME AUDIT SELF-TEST PASS")

def run():
    target=os.environ.get("V17_TARGET_READONLY_DATABASE_URL"); source=os.environ.get("V17_SOURCE_READONLY_DATABASE_URL")
    if not target or not source: raise AuditError("Missing read-only Neon credentials")
    with connect_ro(target,TARGET_HOST,"V1.7 production profile branch") as tc, connect_ro(source,SOURCE_HOST,"Delta source candle branch") as sc:
        dbprofiles=read_profiles(tc); candles=read_candles(sc)
    daily,daybars=validate_days(candles)
    for d,p in daily.items():
        dbp=dbprofiles[d]
        if Decimal(str(p.vah_upper))!=Decimal(str(dbp["vah_upper"])) or Decimal(str(p.val_lower))!=Decimal(str(dbp["val_lower"])):
            raise AuditError(f"{d}: canonical daily.py VAH/VAL does not match persisted V1.7 profile")
    blocks=build_blocks(daybars); a=test_a(daybars,daily,blocks); b=test_b(daybars,blocks)
    report={"audit":"BTC sub-session regime audit","sample":{"start":str(START),"end":str(END),"complete_sessions":EXPECTED_SESSIONS,"price_candles":EXPECTED_SESSIONS*48,"v17_profiles":len(dbprofiles),"daily_profile_vah_val_parity":"PASS (all 189 persisted V1.7 profiles)"},
      "windows_utc_ist":{"prior_us_overnight":"20:00–00:00 UTC / 01:30–05:30 IST","asia":"00:00–08:00 UTC / 05:30–13:30 IST","europe":"08:00–13:30 UTC / 13:30–19:00 IST","us_cash":"13:30–00:00 UTC / 19:00–05:30 IST"},
      "method":{"profile":"Dashboard $50 TPO rows, 70% VA, lower POC tie, left-first expansion","test_a":"Exact amt_engine.playbook_v14 build_signal/classify_discovery/evaluate_exit; Pattern A only; Asia + Europe; max one per sub-session; prior completed UTC-session VAH/VAL; min $200 risk","test_b":"Sub-session low below prior completed sub-session VAL; final close reclaims inside prior VAL/VAH; OVERLAPPING / INSIDE value regime; final completed 30m close entry; stop below excursion low with at least $200 risk; long 2R; stop-first","fees":{"taker":TAKER,"maker":MAKER,"gst":GST,"effective_taker":TAKER*GST,"effective_maker":MAKER*GST},"control":"Same UTC date/sub-session final completed 30m close; unconditional long with fixed $200 risk and 2R target"},
      "test_a":{k:v for k,v in a.items() if k!="trades_detail"},"test_b":b}
    print(json.dumps(report,indent=2,default=str))

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--self-test",action="store_true"); args=ap.parse_args()
    try: self_test() if args.self_test else run(); return 0
    except Exception as e: print(f"Research stopped safely: {e}",file=sys.stderr); return 1
if __name__=="__main__": raise SystemExit(main())
