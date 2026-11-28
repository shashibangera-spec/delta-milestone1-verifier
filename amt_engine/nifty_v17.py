"""Isolated NIFTY 50 Spot V1.7 AMT engine and Yahoo Finance backfill validator."""
from __future__ import annotations
import argparse,hashlib,json,os
from datetime import date,datetime,time,timedelta
from decimal import Decimal,ROUND_CEILING
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import pandas as pd
import psycopg
import yfinance as yf
from psycopg.rows import dict_row
IST=ZoneInfo("Asia/Kolkata"); SYMBOL="^NSEI"; SCHEMA="amt_nifty_v17"; DATABASE="amt_research"
WRITER_ROLE="amt_nifty_writer_login"; READER_ROLE="amt_dashboard_ro"
EXPECTED_HOST="ep-morning-mountain-aopl02wv-pooler.c-2.ap-southeast-1.aws.neon.tech"
ROW_SIZE=Decimal("10"); VALUE_AREA=Decimal("0.70")
EXPECTED_DATES=tuple(date.fromisoformat(x) for x in """2026-09-07 2026-09-08 2026-09-09 2026-09-10 2026-09-11 2026-09-15 2026-09-16 2026-09-17 2026-09-18 2026-09-21 2026-09-22 2026-09-23 2026-09-24 2026-09-25 2026-09-28 2026-09-29 2026-09-30 2026-10-01 2026-10-05 2026-10-06 2026-10-07 2026-10-08 2026-10-09 2026-10-12 2026-10-13 2026-10-14 2026-10-15 2026-10-16 2026-10-19 2026-10-21 2026-10-22 2026-10-23 2026-10-26 2026-10-27 2026-10-28 2026-10-29 2026-10-30 2026-11-02 2026-11-03 2026-11-04 2026-11-05 2026-11-06 2026-11-09 2026-11-11 2026-11-12 2026-11-13 2026-11-16 2026-11-17 2026-11-18 2026-11-19 2026-11-20 2026-11-23 2026-11-25 2026-11-26""".split())
DDL=(
"""CREATE TABLE IF NOT EXISTS amt_nifty_v17.sessions(session_date date PRIMARY KEY,symbol text NOT NULL DEFAULT '^NSEI',method_version text NOT NULL DEFAULT 'AMT_NIFTY_V1.7',row_size numeric NOT NULL,value_area_fraction numeric NOT NULL,expected_brackets integer NOT NULL,observed_brackets integer NOT NULL,is_complete boolean NOT NULL,vah numeric,poc numeric,val numeric,session_high numeric,session_low numeric,session_close numeric,close_location text,value_migration text,range_structure text,source_15m_rows integer NOT NULL,source_sha256 text NOT NULL,profile_sha256 text NOT NULL,created_at timestamptz NOT NULL DEFAULT now())""",
"""CREATE TABLE IF NOT EXISTS amt_nifty_v17.developing_snapshots(session_date date NOT NULL REFERENCES amt_nifty_v17.sessions(session_date),completed_brackets integer NOT NULL CHECK(completed_brackets BETWEEN 1 AND 13),dvah numeric NOT NULL,dpoc numeric NOT NULL,dval numeric NOT NULL,total_tpos integer NOT NULL,snapshot_sha256 text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(session_date,completed_brackets))""",
"""CREATE TABLE IF NOT EXISTS amt_nifty_v17.source_validations(validation_id bigserial PRIMARY KEY,source_symbol text NOT NULL,expected_sessions integer NOT NULL,observed_sessions integer NOT NULL,first_session date,last_session date,dataset_sha256 text NOT NULL,validation_status text NOT NULL CHECK(validation_status IN ('PASS','FAIL')),diagnostics jsonb NOT NULL DEFAULT '{}'::jsonb,validated_at timestamptz NOT NULL DEFAULT now())""")
def canonical_sha(payload):
 return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=True,default=str).encode()).hexdigest()
def validate_writer_url(url):
 p=urlparse(url or "")
 if p.scheme not in ("postgres","postgresql") or p.hostname!=EXPECTED_HOST: raise RuntimeError("NIFTY_V17_DATABASE_URL host is not the pinned Nifty production branch")
 if p.path.lstrip("/")!=DATABASE or p.username!=WRITER_ROLE: raise RuntimeError("NIFTY_V17_DATABASE_URL must use amt_nifty_writer_login on amt_research")
 return p
def normalize_yahoo(raw):
 if raw is None or raw.empty: raise ValueError("Yahoo Finance returned no ^NSEI 15m candles")
 f=raw.copy()
 if isinstance(f.columns,pd.MultiIndex): f.columns=f.columns.get_level_values(0)
 f=f.reset_index()
 if isinstance(f.columns,pd.MultiIndex): f.columns=f.columns.get_level_values(0)
 f.columns=[str(c).strip().lower().replace(" ","_") for c in f.columns]
 f=f.rename(columns={"datetime":"timestamp","date":"timestamp"})
 if "timestamp" not in f.columns: f=f.rename(columns={f.columns[0]:"timestamp"})
 f=f.loc[:,~f.columns.duplicated()].copy()
 if any(c not in f.columns for c in ("open","high","low","close")): raise ValueError(f"Yahoo OHLC columns missing: {list(f.columns)}")
 ts=pd.to_datetime(f["timestamp"],errors="coerce"); ts=ts.dt.tz_localize(IST) if ts.dt.tz is None else ts.dt.tz_convert(IST)
 f["timestamp"]=ts
 for c in ("open","high","low","close"): f[c]=pd.to_numeric(f[c],errors="coerce")
 f=f.dropna(subset=["timestamp","open","high","low","close"]).copy()
 f["timestamp"]=f["timestamp"].dt.floor("15min")
 return f.drop_duplicates("timestamp",keep="last").sort_values("timestamp")[["timestamp","open","high","low","close"]].reset_index(drop=True)
def fetch_yahoo(period="55d",now=None):
 now=(now or datetime.now(IST)).astimezone(IST)
 f=normalize_yahoo(yf.Ticker(SYMBOL).history(period=period,interval="15m",auto_adjust=False))
 f=f[f.timestamp.map(lambda x:x.to_pydatetime()+timedelta(minutes=15)<=now)]
 f=f[f.timestamp.map(lambda x:time(9,15)<=x.time()<=time(15,15))].copy()
 f["session_date"]=f.timestamp.dt.date
 return f.reset_index(drop=True)
def aggregate_session(frame,day):
 rows=frame[frame.session_date==day].sort_values("timestamp")
 lookup={r.timestamp.to_pydatetime().time():r for r in rows.itertuples(index=False)}
 bars=[]; missing=[]
 for i in range(13):
  start=datetime.combine(day,time(9,15))+timedelta(minutes=30*i)
  starts=[start.time()] if i==12 else [start.time(),(start+timedelta(minutes=15)).time()]
  if any(t not in lookup for t in starts): missing.append(i+1); continue
  pair=[lookup[t] for t in starts]
  bars.append({"bracket":i+1,"start":start.isoformat(),"open":float(pair[0].open),"high":max(float(x.high) for x in pair),"low":min(float(x.low) for x in pair),"close":float(pair[-1].close)})
 return bars,{"date":day.isoformat(),"received_15m":len(rows),"complete_brackets":len(bars),"missing_brackets":missing}
def calculate_profile(bars):
 if not bars: raise ValueError("Cannot calculate TPO profile without complete brackets")
 counts={}
 for b in bars:
  for idx in range(int(Decimal(str(b["low"]))//ROW_SIZE),int(Decimal(str(b["high"]))//ROW_SIZE)+1): counts[idx]=counts.get(idx,0)+1
 poc=max(counts,key=lambda k:(counts[k],-k)); target=int((Decimal(sum(counts.values()))*VALUE_AREA).to_integral_value(rounding=ROUND_CEILING))
 lo=hi=poc; covered=counts[poc]
 while covered<target:
  left,right=counts.get(lo-1,0),counts.get(hi+1,0)
  if not left and not right: break
  if left>=right and left: lo-=1; covered+=left
  else: hi+=1; covered+=right
 return {"vah":float(Decimal(hi+1)*ROW_SIZE),"poc":float((Decimal(poc)+Decimal("0.5"))*ROW_SIZE),"val":float(Decimal(lo)*ROW_SIZE),"total_tpos":sum(counts.values()),"value_area_tpos":covered}
def profile_rows(frame,day):
 bars,diag=aggregate_session(frame,day)
 if len(bars)!=13 or diag["received_15m"]!=25: raise ValueError(f"{day}: expected 25 completed 15m candles / 13 brackets; got {diag}")
 snaps=[]
 for n in range(1,14):
  p=calculate_profile(bars[:n]); payload={"session_date":day.isoformat(),"completed_brackets":n,**p}; snaps.append({**payload,"snapshot_sha256":canonical_sha(payload)})
 p=calculate_profile(bars)
 return ({**p,"session_date":day.isoformat(),"expected_brackets":13,"observed_brackets":13,"is_complete":True,"session_high":max(x["high"] for x in bars),"session_low":min(x["low"] for x in bars),"session_close":bars[-1]["close"],"source_15m_rows":25},snaps,diag)
def validate_54_sessions(frame):
 actual=sorted(d for d in frame.session_date.unique() if d<datetime.now(IST).date()); complete=[]; incomplete=[]
 for d in actual:
  b,diag=aggregate_session(frame,d)
  if len(b)==13 and diag["received_15m"]==25: complete.append(d)
  else: incomplete.append(diag)
 missing=sorted(set(EXPECTED_DATES)-set(complete)); extra=sorted(set(complete)-set(EXPECTED_DATES))
 if tuple(complete)!=EXPECTED_DATES or missing or extra or incomplete: raise ValueError(f"54-session Yahoo validation failed: complete={len(complete)}, missing={[x.isoformat() for x in missing]}, unexpected={[x.isoformat() for x in extra]}, incomplete={incomplete}")
 payload=[{"date":d.isoformat(),"bars":aggregate_session(frame,d)[0]} for d in complete]
 return {"expected_sessions":54,"observed_sessions":54,"first_session":complete[0].isoformat(),"last_session":complete[-1].isoformat(),"dataset_sha256":canonical_sha(payload),"sessions":complete}
def classify_session(cur,prev):
 close=cur["session_close"]; loc="ABOVE VAH" if close>cur["vah"] else ("BELOW VAL" if close<cur["val"] else "INSIDE VALUE")
 if prev is None: return {"close_location":loc,"value_migration":"FIRST SESSION","range_structure":"FIRST SESSION"}
 if cur["vah"]>prev["vah"] and cur["poc"]>prev["poc"] and cur["val"]>prev["val"]: mig="VALUE UP"
 elif cur["vah"]<prev["vah"] and cur["poc"]<prev["poc"] and cur["val"]<prev["val"]: mig="VALUE DOWN"
 else: mig="VALUE OVERLAP / MIXED"
 h="HH" if cur["session_high"]>prev["session_high"] else ("LH" if cur["session_high"]<prev["session_high"] else "EQH")
 l="HL" if cur["session_low"]>prev["session_low"] else ("LL" if cur["session_low"]<prev["session_low"] else "EQL")
 return {"close_location":loc,"value_migration":mig,"range_structure":f"{h}/{l}"}
def connect_writer(url=None):
 url=url or os.environ.get("NIFTY_V17_DATABASE_URL",""); validate_writer_url(url)
 c=psycopg.connect(url,sslmode="require",row_factory=dict_row)
 with c.cursor() as q: q.execute("SELECT current_database() db,current_user usr,session_user su"); who=q.fetchone()
 if (who["db"],who["usr"],who["su"])!=(DATABASE,WRITER_ROLE,WRITER_ROLE): c.close(); raise RuntimeError("Connected database identity mismatch for isolated Nifty writer")
 return c
def migrate(conn):
 with conn.cursor() as q:
  q.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'amt_nifty_v17'")
  if q.fetchone() is None:
   raise RuntimeError("Required schema amt_nifty_v17 does not exist; refusing to create a schema or request database-level privileges")
  for ddl in DDL: q.execute(ddl)
  q.execute("GRANT USAGE ON SCHEMA amt_nifty_v17 TO amt_dashboard_ro")
  q.execute("GRANT SELECT ON ALL TABLES IN SCHEMA amt_nifty_v17 TO amt_dashboard_ro")
  q.execute("ALTER DEFAULT PRIVILEGES FOR ROLE amt_nifty_writer_login IN SCHEMA amt_nifty_v17 GRANT SELECT ON TABLES TO amt_dashboard_ro")
def persist_session(conn,frame,day,prior):
 s,snaps,_=profile_rows(frame,day); s.update(classify_session(s,prior)); bars,_=aggregate_session(frame,day)
 src_sha=canonical_sha(bars); prof_sha=canonical_sha({k:v for k,v in s.items() if k!="session_date"})
 with conn.cursor() as q:
  q.execute("SELECT source_sha256,profile_sha256 FROM amt_nifty_v17.sessions WHERE session_date=%s",(day,)); old=q.fetchone()
  if old:
   if old["source_sha256"]!=src_sha or old["profile_sha256"]!=prof_sha: raise RuntimeError(f"{day}: existing Nifty fingerprint mismatch; refusing overwrite")
   q.execute("SELECT completed_brackets,snapshot_sha256 FROM amt_nifty_v17.developing_snapshots WHERE session_date=%s ORDER BY completed_brackets",(day,))
   stored=q.fetchall()
   expected=[(x["completed_brackets"],x["snapshot_sha256"]) for x in snaps]
   actual=[(x["completed_brackets"],x["snapshot_sha256"]) for x in stored]
   if actual!=expected: raise RuntimeError(f"{day}: existing developing snapshot SHA/count mismatch; refusing skip")
   return {"date":day.isoformat(),"status":"SKIP_IDENTICAL","sha256":prof_sha}
  q.execute("""INSERT INTO amt_nifty_v17.sessions(session_date,row_size,value_area_fraction,expected_brackets,observed_brackets,is_complete,vah,poc,val,session_high,session_low,session_close,close_location,value_migration,range_structure,source_15m_rows,source_sha256,profile_sha256) VALUES(%s,10,.70,13,13,true,%s,%s,%s,%s,%s,%s,%s,%s,%s,25,%s,%s)""",(day,s["vah"],s["poc"],s["val"],s["session_high"],s["session_low"],s["session_close"],s["close_location"],s["value_migration"],s["range_structure"],src_sha,prof_sha))
  for x in snaps: q.execute("""INSERT INTO amt_nifty_v17.developing_snapshots(session_date,completed_brackets,dvah,dpoc,dval,total_tpos,snapshot_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s)""",(day,x["completed_brackets"],x["vah"],x["poc"],x["val"],x["total_tpos"],x["snapshot_sha256"]))
  q.execute("SELECT count(*) n FROM amt_nifty_v17.developing_snapshots WHERE session_date=%s",(day,))
  if q.fetchone()["n"]!=13: raise RuntimeError(f"{day}: expected 13 developing snapshots")
  q.execute("SELECT source_sha256,profile_sha256,is_complete,observed_brackets FROM amt_nifty_v17.sessions WHERE session_date=%s",(day,)); check=q.fetchone()
  if not check or check["source_sha256"]!=src_sha or check["profile_sha256"]!=prof_sha or not check["is_complete"] or check["observed_brackets"]!=13: raise RuntimeError(f"{day}: post-write SHA/integrity check failed")
 return {"date":day.isoformat(),"status":"INSERTED","sha256":prof_sha}
def run_validate():
 frame=fetch_yahoo("55d",datetime.now(IST))
 validation=validate_54_sessions(frame)
 return {k:v for k,v in validation.items() if k!="sessions"}
def run_backfill():
 frame=fetch_yahoo("55d",datetime.now(IST)); validation=validate_54_sessions(frame) # no connection/write until all 54 pass
 with connect_writer() as conn:
  with conn.transaction():
   migrate(conn); out=[]; prior=None
   for d in validation["sessions"]:
    s,_,_=profile_rows(frame,d); out.append(persist_session(conn,frame,d,prior)); prior=s
   with conn.cursor() as q: q.execute("""INSERT INTO amt_nifty_v17.source_validations(source_symbol,expected_sessions,observed_sessions,first_session,last_session,dataset_sha256,validation_status,diagnostics) VALUES('^NSEI',54,54,%s,%s,%s,'PASS',%s::jsonb)""",(validation["sessions"][0],validation["sessions"][-1],validation["dataset_sha256"],json.dumps({"complete_dates":[d.isoformat() for d in validation["sessions"]]})))
 return {"validation":{k:v for k,v in validation.items() if k!="sessions"},"writes":out}
def run_daily():
 now=datetime.now(IST); frame=fetch_yahoo("5d",now); day=now.date(); bars,diag=aggregate_session(frame,day)
 if len(bars)!=13 or diag["received_15m"]!=25: return {"status":"SKIP_INCOMPLETE_OR_HOLIDAY","diagnostics":diag}
 with connect_writer() as conn:
  with conn.transaction():
   migrate(conn)
   with conn.cursor() as q: q.execute("SELECT vah,poc,val,session_high,session_low FROM amt_nifty_v17.sessions WHERE session_date<%s ORDER BY session_date DESC LIMIT 1",(day,)); r=q.fetchone()
   prior=None if not r else {"vah":float(r["vah"]),"poc":float(r["poc"]),"val":float(r["val"]),"session_high":float(r["session_high"]),"session_low":float(r["session_low"])}
   result=persist_session(conn,frame,day,prior)
 return {"status":"SUCCESS","session":day.isoformat(),"result":result}
def main():
 p=argparse.ArgumentParser(); p.add_argument("mode",choices=("validate","backfill","daily")); a=p.parse_args()
 result=run_validate() if a.mode=="validate" else (run_backfill() if a.mode=="backfill" else run_daily())
 print(json.dumps(result,sort_keys=True,default=str))
if __name__=="__main__": main()
