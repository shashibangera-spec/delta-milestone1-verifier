#!/usr/bin/env python3
"""Read-only BTC Pattern A monthly stability and developing-value control audit."""
from __future__ import annotations
import argparse, os, sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amt_engine.playbook_v13 import build_signal, evaluate_exit

TARGET_HOST="ep-morning-mountain-aopl02wv.c-2.ap-southeast-1.aws.neon.tech"
SOURCE_HOST="ep-sparkling-queen-aoqgp0mw.c-2.ap-southeast-1.aws.neon.tech"
DB="amt_research"; ROLE="amt_dashboard_ro"; SOURCE="delta_india"; SYMBOL="BTCUSD"; METHOD="AMT_ENGINE_V1.7"
START=date(2026,5,21); END=date(2026,11,26); EXCLUDED={date(2026,11,20)}
UTC=timezone.utc; BAR=timedelta(minutes=30); TAKER=.0005; MAKER=.0002; GST=1.18
class ResearchError(RuntimeError): pass

def approved_dates():
    return [START+timedelta(days=i) for i in range((END-START).days+1) if START+timedelta(days=i) not in EXCLUDED]

def connect_ro(url,host,label):
    import psycopg
    from psycopg.rows import dict_row
    u=urlparse(url or "")
    if u.scheme not in ("postgres","postgresql") or u.hostname!=host: raise ResearchError(f"{label}: URL host does not match pinned Neon branch")
    c=psycopg.connect(url,sslmode="require",row_factory=dict_row)
    try:
        with c.cursor() as q:
            q.execute("SET TRANSACTION READ ONLY")
            q.execute("SELECT current_database() db,current_user usr,session_user su")
            r=q.fetchone()
        if (r["db"],r["usr"],r["su"])!=(DB,ROLE,ROLE): raise ResearchError(f"{label}: expected {DB}/{ROLE}/{ROLE}")
        return c
    except Exception: c.close(); raise

def read_profiles(c):
    with c.cursor() as q:
        q.execute("""SELECT session_date,profile_status,is_complete,expected_bars,observed_bars,vah_upper,val_lower
          FROM amt_engine_v17.session_profiles WHERE method_version=%s AND source=%s AND symbol=%s
          AND session_date BETWEEN %s AND %s ORDER BY session_date""",(METHOD,SOURCE,SYMBOL,START,END)); rows=q.fetchall()
    out={}
    for r in rows:
        d=r["session_date"]
        if d in EXCLUDED: continue
        if not r["is_complete"] or r["profile_status"]!="COMPLETE" or r["expected_bars"]!=48 or r["observed_bars"]!=48: raise ResearchError(f"{d}: incomplete profile")
        if r["vah_upper"] is None or r["val_lower"] is None or r["vah_upper"]<=r["val_lower"]: raise ResearchError(f"{d}: invalid prior value")
        out[d]={"vah":float(r["vah_upper"]),"val":float(r["val_lower"])}
    if sorted(out)!=approved_dates() or len(out)!=189: raise ResearchError(f"Expected 189 profiles, got {len(out)}")
    return out

def read_bars(c):
    begin=datetime(2026,5,20,tzinfo=UTC); end=datetime(2026,11,27,tzinfo=UTC)
    with c.cursor() as q:
        q.execute("""SELECT candle_time,open_value,high_value,low_value,close_value FROM research.delta_candles
          WHERE source=%s AND series_type='PRICE' AND symbol=%s AND resolution='30m'
          AND candle_time >= %s AND candle_time < %s ORDER BY candle_time""",(SOURCE,SYMBOL,begin,end)); rows=q.fetchall()
    out={}
    for r in rows:
        ts=r["candle_time"].astimezone(UTC); vals=[r[k] for k in ("open_value","high_value","low_value","close_value")]
        if any(v is None for v in vals): raise ResearchError(f"{ts}: null OHLC")
        o,h,l,cl=map(float,vals)
        if h<max(o,cl,l) or l>min(o,cl,h) or ts in out: raise ResearchError(f"{ts}: invalid or duplicate OHLC")
        out[ts]={"timestamp":ts,"open":o,"high":h,"low":l,"close":cl}
    n=sum(1 for ts in out if START<=ts.date()<=END and ts.date() not in EXCLUDED)
    if n!=9072: raise ResearchError(f"Expected 9,072 in-scope bars, got {n}")
    for d in approved_dates():
        s=datetime.combine(d,time(0),UTC)
        if any(s+BAR*i not in out for i in range(48)): raise ResearchError(f"{d}: missing UTC bar")
    return out

def read_developing(c):
    with c.cursor() as q:
        q.execute("""SELECT candle_open,candle_close,developing_vah_upper,developing_val_lower
          FROM amt_engine_v17.developing_snapshots WHERE method_version=%s AND source=%s AND symbol=%s
          AND session_date BETWEEN %s AND %s ORDER BY candle_open""",(METHOD,SOURCE,SYMBOL,START,END)); rows=q.fetchall()
    out={}
    for r in rows:
        ts=r["candle_open"].astimezone(UTC)
        if r["developing_vah_upper"] is None or r["developing_val_lower"] is None: continue
        if ts in out: raise ResearchError(f"{ts}: duplicate developing snapshot")
        out[ts]={"vah":float(r["developing_vah_upper"]),"val":float(r["developing_val_lower"]),"close_ts":r["candle_close"].astimezone(UTC)}
    if len(out)!=9072: raise ResearchError(f"Expected 9,072 developing snapshots, got {len(out)}")
    return out

def prior_trend(d,ranges):
    a,b=ranges.get(d-timedelta(days=1)),ranges.get(d-timedelta(days=2))
    if not a or not b:return "MIXED"
    if a["high"]>b["high"] and a["low"]>b["low"]:return "HH/HL"
    if a["high"]<b["high"] and a["low"]<b["low"]:return "LL/LH"
    return "MIXED"

def status_2a(bars,i,trend):
    if trend not in ("HH/HL","LL/LH"):return "N/A"
    known=bars[:i]; lows=[]; highs=[]
    for j in range(2,len(known)-2):
        if all(known[j]["low"]<known[k]["low"] for k in (j-2,j-1,j+1,j+2)):lows.append((j,known[j]["low"]))
        if all(known[j]["high"]>known[k]["high"] for k in (j-2,j-1,j+1,j+2)):highs.append((j,known[j]["high"]))
    if trend=="HH/HL":
        q=[(idx,v) for (_,p),(idx,v) in zip(lows,lows[1:]) if v>p]
        if not q:return "INTACT"
        idx,level=q[-1]; broken=any(bars[k]["close"]<level for k in range(idx+2,i+1))
    else:
        q=[(idx,v) for (_,p),(idx,v) in zip(highs,highs[1:]) if v<p]
        if not q:return "INTACT"
        idx,level=q[-1]; broken=any(bars[k]["close"]>level for k in range(idx+2,i+1))
    return "BROKEN" if broken else "INTACT"

def utc_window(ts): return "Asia + Europe" if ts.time()<time(13,30) else "US Cash"
def fee_r(entry,xp,risk,entry_rate): return ((entry*entry_rate+xp*TAKER)*GST)/risk

def exit_trade(ts,side,entry,stop,target,bars,times,index,month,win,kind):
    risk=abs(entry-stop)
    if risk<=0:return None
    for future in times[index[ts]+1:]:
        x=evaluate_exit({"side":side,"stop_price":stop,"target_price":target},bars[future])
        if x:
            xp=float(x["exit_price"]); gross=float(x["realized_r"])
            return {"entry_time":ts+BAR,"month":month,"window":win,"side":side,"risk":risk,"gross":gross,
              "fee_tt":fee_r(entry,xp,risk,TAKER),"fee_mt":fee_r(entry,xp,risk,MAKER),"kind":kind}
    return None

def metrics(rows):
    rows=sorted(rows,key=lambda x:x["entry_time"]); n=len(rows)
    if not n:return (0,0.,0.,0.,0.,0.)
    g=[x["gross"] for x in rows]; tt=[x["gross"]-x["fee_tt"] for x in rows]; mt=[x["gross"]-x["fee_mt"] for x in rows]
    eq=peak=dd=0.
    for x in tt:eq+=x;peak=max(peak,eq);dd=max(dd,peak-eq)
    return n,100*sum(x>0 for x in g)/n,sum(g)/n,sum(tt),sum(mt),dd

def print_months(title,groups):
    print("\n"+title); print(f"{'Month':<10} {'Trades':>7} {'Win %':>8} {'Avg Gross R':>12} {'Net T/T':>10} {'Net M/T':>10} {'Max DD R':>10}")
    for m in [f"2026-{i:02d}" for i in range(5,12)]:
        n,w,a,tt,mt,dd=metrics(groups.get(m,[])); print(f"{m:<10} {n:>7} {w:>8.2f} {a:>12.3f} {tt:>10.3f} {mt:>10.3f} {dd:>10.3f}")

def test_pattern_a(profiles,bars):
    times=sorted(bars); index={t:i for i,t in enumerate(times)}
    ranges=defaultdict(dict)
    for ts,b in bars.items():
        if ts.date() not in EXCLUDED:ranges[ts.date()][ts]=b
    daily={d:{"high":max(x["high"] for x in v.values()),"low":min(x["low"] for x in v.values())} for d,v in ranges.items() if len(v)==48}
    raw=defaultdict(list); unresolved=0
    for d,p in profiles.items():
        day=[bars[datetime.combine(d,time(0),UTC)+BAR*i] for i in range(48)]; trend=prior_trend(d,daily)
        for i,cur in enumerate(day):
            ts=cur["timestamp"]; prev=day[i-1] if i else bars.get(ts-BAR)
            if prev is None:continue
            sig=build_signal(prev,cur,p["vah"],p["val"])
            if not sig or sig.pattern!="A" or utc_window(ts)!="Asia + Europe":continue
            tr=exit_trade(ts,sig.side,sig.entry_price,sig.stop_price,sig.target_price,bars,times,index,d.strftime("%Y-%m"),utc_window(ts),"Pattern A")
            if tr is None:unresolved+=1;continue
            tr.update({"date":d,"subsession":"Asia" if ts.time()<time(8) else "Europe","stop_width":sig.risk_points,"2a":status_2a(day,i,trend)})
            raw[d.strftime("%Y-%m")].append(tr)
    capped=defaultdict(list); intact=defaultdict(list)
    for m,rows in raw.items():
        used=set()
        for tr in sorted(rows,key=lambda x:x["entry_time"]):
            k=(tr["date"],tr["subsession"])
            if tr["stop_width"]>=200 and k not in used:capped[m].append(tr);used.add(k)
            if tr["2a"]=="INTACT":intact[m].append(tr)
    print_months("TEST 1A — RAW PATTERN A | ASIA + EUROPE",raw)
    print_months("TEST 1B — MAX 1 PER SUB-SESSION + MIN STOP WIDTH $200",capped)
    print_months("TEST 1C — PATTERN A + 2A INTACT",intact)
    print(f"Unresolved Pattern A exits excluded: {unresolved}")

def test_dv(bars,dv):
    times=sorted(bars); index={t:i for i,t in enumerate(times)}; events=[]; first_out=set()
    for ts in times:
        if ts not in dv or ts.date() not in approved_dates():continue
        b=bars[ts]; v=dv[ts]; c=b["close"]; vah=v["vah"]; val=v["val"]
        if c>vah: direction="UP"; side="LONG"; boundary=vah; risk=c-boundary
        elif c<val: direction="DOWN"; side="SHORT"; boundary=val; risk=boundary-c
        else:continue
        key=(ts.date(),direction)
        if key in first_out or risk<=0:continue
        first_out.add(key); win=utc_window(ts); month=ts.strftime("%Y-%m")
        cont=exit_trade(ts,side,c,boundary,c+(2*risk if side=="LONG" else -2*risk),bars,times,index,month,win,"Continuation")
        if cont:events.append(cont)
        extreme=b["high"] if direction=="UP" else b["low"]
        for rt in times[index[ts]+1:]:
            if rt.date()!=ts.date():break
            rb=bars[rt]; extreme=max(extreme,rb["high"]) if direction=="UP" else min(extreme,rb["low"])
            if val<=rb["close"]<=vah:
                rs="SHORT" if direction=="UP" else "LONG"; entry=rb["close"]; stop=extreme; rr=abs(entry-stop)
                if rr>0:
                    target=entry-2*rr if rs=="SHORT" else entry+2*rr
                    reclaim=exit_trade(rt,rs,entry,stop,target,bars,times,index,rt.strftime("%Y-%m"),utc_window(rt),"Reclaim")
                    if reclaim:events.append(reclaim)
                break
    # Controls are every non-event bar, exactly matched by month/window/side/risk and setup type.
    event_bars={x["entry_time"]-BAR for x in events}; controls=[]; match_keys=set()
    for e in events:
        key=(e["month"],e["window"],e["side"],e["risk"],e["kind"])
        if key in match_keys:continue
        match_keys.add(key)
        for ts in times:
            if ts.date().strftime("%Y-%m")!=e["month"] or utc_window(ts)!=e["window"] or ts.date() in EXCLUDED or ts in event_bars:continue
            entry=bars[ts]["close"]; risk=e["risk"]; stop=entry-risk if e["side"]=="LONG" else entry+risk
            target=entry+2*risk if e["side"]=="LONG" else entry-2*risk
            tr=exit_trade(ts,e["side"],entry,stop,target,bars,times,index,e["month"],e["window"],"Control")
            if tr:tr["match_key"]=key;controls.append(tr)
    print("\nTEST 2 — DEVELOPING VALUE RECLAIM VS CONTINUATION / MATCHED CONTROLS")
    print("Event: first outside close per UTC date and direction; continuation enters outside close; reclaim enters first later close inside same frozen dVA, stop beyond excursion extreme.")
    print("Controls: every non-event bar matched on month, UTC window, direction and exact dollar stop-distance; 2R; stop-first.")
    for w in ("Asia + Europe","US Cash"):
        for kind in ("Continuation","Reclaim"):
            ev=[x for x in events if x["window"]==w and x["kind"]==kind]
            keys={(x["month"],x["window"],x["side"],x["risk"],x["kind"]) for x in ev}
            co=[x for x in controls if x.get("match_key") in keys]
            for label,rows in ((kind,ev),("Matched controls",co)):
                n,wr,avg,tt,mt,dd=metrics(rows)
                print(f"{w:<14} {label:<18} N={n:5d} Win={wr:6.2f}% AvgGrossR={avg:7.3f} NetTT={tt:8.3f} NetMT={mt:8.3f}")
    print(f"Test 2 event trades={len(events)}; control trades={len(controls)}")

def self_test():
    assert len(approved_dates())==189 and 189*48==9072
    assert utc_window(datetime(2026,5,21,0,0,tzinfo=UTC))=="Asia + Europe"
    assert utc_window(datetime(2026,5,21,13,30,tzinfo=UTC))=="US Cash"
    assert fee_r(100,110,10,TAKER)>fee_r(100,110,10,MAKER)
    x=evaluate_exit({"side":"LONG","stop_price":95,"target_price":110},{"high":111,"low":94,"close":100})
    assert x and x["realized_r"]==-1 and x["exit_reason"]=="STOP_FIRST_AMBIGUOUS"
    assert metrics([])[0]==0
    # 2A pivot confirmation is unavailable until both right-hand candles have closed.
    assert status_2a([{"low":i,"high":i+1,"close":i} for i in range(8)],7,"MIXED")=="N/A"
    print("OFFLINE DV CONTROL AUDIT SELF-TEST PASS")

def run():
    tu=os.environ.get("V17_TARGET_READONLY_DATABASE_URL"); su=os.environ.get("V17_SOURCE_READONLY_DATABASE_URL")
    if not tu or not su:raise ResearchError("Missing read-only Neon secrets")
    with connect_ro(tu,TARGET_HOST,"V1.7 profiles and developing snapshots") as target, connect_ro(su,SOURCE_HOST,"Delta India candles") as source:
        profiles=read_profiles(target); dv=read_developing(target); bars=read_bars(source)
    print("BTCUSD | 189 complete sessions | 21 May–26 Nov 2026 | 9,072 30m candles + developing snapshots")
    print("20 Nov excluded from event/trade sample; connections verified amt_research / amt_dashboard_ro; SET TRANSACTION READ ONLY.")
    print("Fees: Taker/Taker 0.05% each leg; Maker/Taker 0.02% entry + 0.05% exit; 18% GST; 2:1 R:R; stop-first.")
    print("Test 1: exact V1.3 Pattern A build_signal/evaluate_exit; Asia+Europe only; 2A uses confirmed 2-left/2-right pivots.")
    test_pattern_a(profiles,bars); test_dv(bars,dv)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--self-test",action="store_true");a=p.parse_args()
    try:self_test() if a.self_test else run();return 0
    except Exception as e:print(f"Research stopped safely: {e}",file=sys.stderr);return 1
if __name__=="__main__":raise SystemExit(main())
