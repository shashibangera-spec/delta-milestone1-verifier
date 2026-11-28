#!/usr/bin/env python3
"""Read-only BTC Playbook v1.4 walk-forward and same-bar OI association audit."""
from __future__ import annotations
import argparse, json, os, sys
from datetime import date, datetime, time, timedelta, timezone
from scripts import research_subsession_regime_audit as base
from amt_engine.playbook_v14 import build_signal, evaluate_exit

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path: sys.path.insert(0,ROOT)
UTC=timezone.utc; BAR=timedelta(minutes=30)
IS_START=date(2026,5,22); IS_END=date(2026,8,31)
OOS_START=date(2026,9,1); OOS_END=date(2026,11,26)
TAKER=.0005; MAKER=.0002; GST=1.18
SUBSESSIONS=("Asia","Europe","US Cash")

class AuditError(RuntimeError): pass

def split_for_day(d):
    if IS_START<=d<=IS_END:return "IN_SAMPLE"
    if OOS_START<=d<=OOS_END:return "BLIND_OUT_OF_SAMPLE"
    return None

def split_end_exclusive(split):
    end=IS_END if split=="IN_SAMPLE" else OOS_END
    return datetime.combine(end+timedelta(days=1),time.min,UTC)

def fee_r(entry,exitp,risk,entry_rate):
    if risk<=0: raise AuditError("Non-positive risk")
    return ((entry*entry_rate+exitp*TAKER)*GST)/risk

def read_oi(conn,price):
    begin=datetime.combine(base.START,time.min,UTC)
    finish=datetime.combine(base.END+timedelta(days=1),time.min,UTC)
    with conn.cursor() as q:
        q.execute("""SELECT candle_time,open_value,close_value FROM research.delta_candles
          WHERE source=%s AND series_type='OI' AND symbol='OI:BTCUSD' AND resolution='30m'
          AND candle_time >= %s AND candle_time < %s ORDER BY candle_time""",
          (base.SOURCE,begin,finish))
        rows=q.fetchall()
    out={}
    for r in rows:
        ts=r["candle_time"].astimezone(UTC); op,cl=r["open_value"],r["close_value"]
        if op is None or cl is None or ts in out: raise AuditError(f"Null/duplicate OI at {ts}")
        out[ts]={"open":float(op),"close":float(cl),"delta":float(cl)-float(op)}
    if set(out)!=set(price):
        raise AuditError(f"PRICE/OI timestamp mismatch: missing={len(set(price)-set(out))}, extra={len(set(out)-set(price))}")
    return out

def bounded_exit(ts,side,entry,stop,target,flat,index,split):
    risk=abs(entry-stop); cutoff=split_end_exclusive(split)
    for future in flat[index[ts]+1:]:
        if future["candle_time"]>=cutoff: break
        x=evaluate_exit({"side":side,"stop_price":stop,"target_price":target},
                        {"high":future["high"],"low":future["low"],"close":future["close"]})
        if x:
            xp=float(x["exit_price"]); gross=float(x["realized_r"])
            return {"gross_r":gross,"net_tt":gross-fee_r(entry,xp,risk,TAKER),
                    "net_mt":gross-fee_r(entry,xp,risk,MAKER),
                    "entry_time":ts+BAR,"exit_time":future["candle_time"]+BAR,
                    "exit_reason":x["exit_reason"],"risk_points":risk}
    return None

def summarize(rows):
    n=len(rows)
    if not n:return {"trades":0,"win_pct":None,"avg_gross_r":None,
        "net_r_taker_taker":0.0,"net_r_maker_taker":0.0,"max_dd_r":0.0}
    ordered=sorted(rows,key=lambda x:x["entry_time"]); eq=peak=dd=0.0
    for x in ordered:
        eq+=x["net_tt"]; peak=max(peak,eq); dd=max(dd,peak-eq)
    return {"trades":n,"win_pct":100*sum(x["gross_r"]>0 for x in ordered)/n,
        "avg_gross_r":sum(x["gross_r"] for x in ordered)/n,
        "net_r_taker_taker":sum(x["net_tt"] for x in ordered),
        "net_r_maker_taker":sum(x["net_mt"] for x in ordered),"max_dd_r":dd}

def test_a_replay(daily,blocks,oi,flat):
    idx={b["candle_time"]:i for i,b in enumerate(flat)}; output={}
    variants=("BASELINE","FILTER_1_NO_STEPPED_DOWN","FILTER_2_NO_STEPPED_DOWN_OR_OI_EXPANSION")
    for variant in variants:
        trades=[]; unresolved=signals=0
        for d in base.evaluation_dates():
            split=split_for_day(d)
            if not split or d not in daily or d-timedelta(days=1) not in daily: continue
            prior=daily[d-timedelta(days=1)]; vah=float(prior.vah_upper); val=float(prior.val_lower)
            for name in ("Asia","Europe"):
                session=blocks[d][name]; regime=session["regime"]
                if not session["bars"] or regime=="UNAVAILABLE": continue
                if variant!="BASELINE" and regime=="VALUE STEPPED DOWN": continue
                for bar in session["bars"]:
                    ts=bar["candle_time"]; i=idx[ts]
                    prev=flat[i-1] if i else None
                    if prev is None: continue
                    sig=build_signal({"close":prev["close"]},bar,vah,val)
                    if sig is None or sig.pattern!="A": continue
                    signals+=1; delta=oi[ts]["delta"]
                    if variant=="FILTER_2_NO_STEPPED_DOWN_OR_OI_EXPANSION" and delta>0:
                        continue
                    result=bounded_exit(ts,sig.side,sig.entry_price,sig.stop_price,sig.target_price,flat,idx,split)
                    if result is None: unresolved+=1
                    else: trades.append({**result,"regime":regime,"sub_session":name,"oi_delta":delta})
                    break
        output[variant]={"metrics":summarize(trades),"signals_considered":signals,
            "unresolved_or_censored":unresolved,
            "oi_expansion_entries":sum(x["oi_delta"]>0 for x in trades),
            "oi_flat_or_contraction_entries":sum(x["oi_delta"]<=0 for x in trades)}
    return output

def build_test_b_candidates(blocks,eligible,flat,idx):
    events=[]; controls=[]; unresolved=0
    for d in base.evaluation_dates():
        split=split_for_day(d)
        if not split or d not in eligible: continue
        prior_name="Prior US Overnight"
        for name in SUBSESSIONS:
            cur=blocks[d][name]; prev=blocks[d][prior_name]
            bars=cur["bars"]; pp=prev["profile"]; cp=cur["profile"]
            if bars and pp and cp:
                last=bars[-1]; ts=last["candle_time"]; entry=last["close"]
                low=min(x["low"] for x in bars); stop=min(low,entry-200.0); risk=entry-stop
                event=(low<float(pp["val"]) and float(pp["val"])<entry<float(pp["vah"])
                       and cur["regime"]=="OVERLAPPING / INSIDE")
                outcome=bounded_exit(ts,"LONG",entry,stop,entry+2*risk,flat,idx,split)
                row={"entry_time":ts+BAR,"day":d,"split":split,"sub_session":name,
                     "risk_points":risk,"is_event":event}
                if event:
                    if outcome is None: unresolved+=1
                    else: events.append({**row,**outcome})
                elif outcome is not None: controls.append({**row,**outcome})
            prior_name=name
    return events,controls,unresolved

def match_controls(events,controls):
    """Chronological greedy 1:1 matching; closest width, no replacement, earliest timestamp tie."""
    available=list(controls); pairs=[]; unmatched=[]
    for event in sorted(events,key=lambda x:x["entry_time"]):
        candidates=[c for c in available if c["split"]==event["split"] and c["sub_session"]==event["sub_session"]]
        if not candidates: unmatched.append(event); continue
        chosen=min(candidates,key=lambda c:(abs(c["risk_points"]-event["risk_points"]),c["entry_time"]))
        available.remove(chosen)
        pairs.append({"event":event,"control":chosen,
                      "absolute_stop_width_difference":abs(chosen["risk_points"]-event["risk_points"])})
    return pairs,unmatched

def test_b_replay(blocks,eligible,flat):
    idx={b["candle_time"]:i for i,b in enumerate(flat)}
    events,controls,unresolved=build_test_b_candidates(blocks,eligible,flat,idx)
    pairs,unmatched=match_controls(events,controls); result={}
    for split in ("IN_SAMPLE","BLIND_OUT_OF_SAMPLE"):
        matched=[p for p in pairs if p["event"]["split"]==split]
        erows=[p["event"] for p in matched]; crows=[p["control"] for p in matched]
        result[split]={"reclaim_events":summarize(erows),"one_to_one_matched_controls":summarize(crows),
            "matched_pairs":len(matched),"unmatched_reclaim_events":sum(x["split"]==split for x in unmatched),
            "unresolved_or_censored_reclaim_events":sum(x["split"]==split for x in events if x not in erows),
            "mean_absolute_stop_width_difference":sum(p["absolute_stop_width_difference"] for p in matched)/len(matched) if matched else None}
    return result

def self_test():
    assert split_for_day(date(2026,5,21)) is None
    assert split_for_day(date(2026,5,22))=="IN_SAMPLE"
    assert split_for_day(date(2026,8,31))=="IN_SAMPLE"
    assert split_for_day(date(2026,9,1))=="BLIND_OUT_OF_SAMPLE"
    assert split_for_day(date(2026,11,26))=="BLIND_OUT_OF_SAMPLE"
    assert split_for_day(date(2026,11,27)) is None
    assert split_end_exclusive("IN_SAMPLE")==datetime(2026,9,1,tzinfo=UTC)
    assert fee_r(10000,10200,200,TAKER)>fee_r(10000,10200,200,MAKER)
    ev=[{"entry_time":datetime(2026,6,1,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Asia","risk_points":250.},
        {"entry_time":datetime(2026,6,2,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Asia","risk_points":300.}]
    co=[{"entry_time":datetime(2026,6,3,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Asia","risk_points":251.},
        {"entry_time":datetime(2026,6,4,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Asia","risk_points":299.},
        {"entry_time":datetime(2026,6,5,tzinfo=UTC),"split":"BLIND_OUT_OF_SAMPLE","sub_session":"Asia","risk_points":250.}]
    pairs,unmatched=match_controls(ev,co)
    assert len(pairs)==2 and not unmatched and [p["control"]["risk_points"] for p in pairs]==[251.,299.]
    tie=[{"entry_time":datetime(2026,6,1,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Europe","risk_points":250.}]
    tied,_=match_controls(tie,[
        {"entry_time":datetime(2026,6,4,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Europe","risk_points":249.},
        {"entry_time":datetime(2026,6,3,tzinfo=UTC),"split":"IN_SAMPLE","sub_session":"Europe","risk_points":251.}])
    assert tied[0]["control"]["entry_time"]==datetime(2026,6,3,tzinfo=UTC)
    assert summarize([])["trades"]==0
    print("OFFLINE V1.5 WALK-FORWARD / OI / MATCHED-CONTROL SELF-TEST PASS")

def run():
    tu=os.environ.get("V17_TARGET_READONLY_DATABASE_URL"); su=os.environ.get("V17_SOURCE_READONLY_DATABASE_URL")
    if not tu or not su: raise AuditError("Missing read-only Neon credentials")
    with base.connect_ro(tu,base.TARGET_HOST,"V1.7 profiles") as target, base.connect_ro(su,base.SOURCE_HOST,"Delta PRICE/OI") as source:
        profiles,skipped=base.read_profiles(target); price=base.read_candles(source); oi=read_oi(source,price)
    daily,daybars=base.validate_days(price)
    for d,p in profiles.items():
        calc=daily[d]
        if float(calc.vah_upper)!=float(p["vah_upper"]) or float(calc.val_lower)!=float(p["val_lower"]):
            raise AuditError(f"{d}: canonical daily AMT VAH/VAL parity failed")
    blocks=base.build_blocks(daybars); flat=sorted(price.values(),key=lambda x:x["candle_time"])
    wf=test_a_replay({d:daily[d] for d in profiles},blocks,oi,flat)
    tb=test_b_replay(blocks,set(profiles),flat)
    report={
      "audit":"BTC Playbook v1.5 read-only walk-forward and OI association",
      "sample":{"warmup":"2026-05-21","evaluation_sessions":base.EXPECTED_SESSIONS,
        "evaluation":"2026-05-22 through 2026-11-26","price_and_oi_candles":len(price),
        "eligible_v17_profiles":len(profiles),"skipped_incomplete_dates":[str(x) for x in skipped],
        "daily_profile_vah_val_parity":"PASS",
        "in_sample":"2026-05-22 through 2026-08-31",
        "blind_out_of_sample":"2026-09-01 through 2026-11-26"},
      "oi_method":{"series":"Delta India OI:BTCUSD 30m",
        "delta":"same completed OI candle close_value minus open_value, timestamp-aligned to PRICE excursion candle",
        "expansion":"delta > 0; zero/negative = flat or contraction",
        "alignment":"exact PRICE/OI timestamp-set equality; no later OI candle used",
        "interpretation":"contemporaneous descriptive association only; not causal attribution"},
      "test_a":{"rules":"Exact Playbook v1.4 build_signal/evaluate_exit; Pattern A; Asia + Europe; first accepted signal per sub-session; >=$200 stop; 2R; stop-first; exits bounded to sample split.",
        "filters":{"BASELINE":"No exclusions",
          "FILTER_1_NO_STEPPED_DOWN":"Exclude preceding VALUE STEPPED DOWN sub-sessions",
          "FILTER_2_NO_STEPPED_DOWN_OR_OI_EXPANSION":"Filter 1 plus exclude same-bar OI delta > 0"},
        "results":wf},
      "test_b":{"rules":"Failed sub-session breakdown below prior sub-session VAL; final completed close strictly inside prior sub-session value; current regime OVERLAPPING / INSIDE; long at final close; stop=min(sub-session low, entry-$200); 2R; stop-first; split-bounded exits.",
        "matching":"Chronological event order; one non-event final-bar control per event; same split and sub-session type; identical stop construction; closest absolute stop width; earliest control timestamp tie-break; no replacement.",
        "results":tb,"control_scope":"Non-event final completed sub-session bars, not intraday random-bar controls."},
      "fees":{"taker_per_leg":TAKER,"maker_per_leg":MAKER,"gst_multiplier":GST,
        "Taker/Taker":"0.05% each leg plus 18% GST","Maker/Taker":"0.02% entry + 0.05% exit plus 18% GST"},
      "caveats":["Same-bar OI is contemporaneous association, not proof of causality.",
        "In-sample exits cannot consume OOS candles; OOS exits are bounded by available 26 Nov data.",
        "Unresolved/censored trades are excluded from metrics and counted separately.",
        "21 May is warm-up only; incomplete persisted profiles are skipped."]}
    print(json.dumps(report,indent=2,default=str))

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--self-test",action="store_true"); args=ap.parse_args()
    try: self_test() if args.self_test else run(); return 0
    except Exception as exc: print(f"Research stopped safely: {exc}",file=sys.stderr); return 1
if __name__=="__main__": raise SystemExit(main())
