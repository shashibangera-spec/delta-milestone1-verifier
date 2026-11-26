"""Single-page read-only V1.7 / Playbook v1.3 observation dashboard."""
from __future__ import annotations

import os
import time
import secrets
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from decimal import Decimal
from urllib.parse import urlparse

import psycopg
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse
from psycopg.rows import dict_row

from amt_engine.playbook_v13 import classify_discovery

EXPECTED_HOST = "ep-morning-mountain-aopl02wv.c-2.ap-southeast-1.aws.neon.tech"
EXPECTED_SOURCE_HOST = "ep-sparkling-queen-aoqgp0mw.c-2.ap-southeast-1.aws.neon.tech"
EXPECTED_DATABASE = "amt_research"
EXPECTED_ROLE = "amt_dashboard_ro"

app = FastAPI(title="BTC V1.7 / Playbook V1.3 Observation Dashboard")
security = HTTPBasic()
_cache = {"at": 0.0, "data": None}


def require_dashboard_auth(credentials: HTTPBasicCredentials = Depends(security)):
    expected_user = os.environ.get("DASHBOARD_USERNAME", "")
    expected_password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not expected_user or not expected_password:
        raise HTTPException(status_code=503, detail="Dashboard authentication is not configured")
    user_ok = secrets.compare_digest(credentials.username, expected_user)
    password_ok = secrets.compare_digest(credentials.password, expected_password)
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid dashboard credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def _json(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json(v) for v in value]
    return value


def _validated_database_url(env_name, expected_host):
    url = os.environ.get(env_name, "")
    parsed = urlparse(url)
    accepted_hosts = {
        expected_host,
        expected_host.replace(".c-", "-pooler.c-"),
    }
    if parsed.scheme not in ("postgres", "postgresql") or parsed.hostname not in accepted_hosts:
        raise RuntimeError(f"{env_name} must use its approved amt_dashboard_ro Neon branch connection")
    if parsed.path.lstrip("/") != EXPECTED_DATABASE:
        raise RuntimeError(f"{env_name} must target amt_research")
    return url


def _connect(env_name="DATABASE_URL", expected_host=EXPECTED_HOST):
    url = _validated_database_url(env_name, expected_host)
    conn = psycopg.connect(url, sslmode="require", row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SELECT current_database() AS db,current_user AS usr,session_user AS su")
            identity = cur.fetchone()
        if (identity["db"], identity["usr"], identity["su"]) != (
            EXPECTED_DATABASE, EXPECTED_ROLE, EXPECTED_ROLE
        ):
            raise RuntimeError("Dashboard database identity must be amt_dashboard_ro on amt_research")
        return conn
    except Exception:
        conn.close()
        raise


def _discovery(closes, vah, val):
    if not closes or vah is None or val is None:
        return "UNKNOWN"
    ordered = sorted(closes, key=lambda row: row["candle_time"])
    times = [row["candle_time"].astimezone(timezone.utc) for row in ordered]
    if times[0].hour != 0 or times[0].minute != 0:
        return "UNKNOWN"
    if any((right - left) != timedelta(minutes=30) for left, right in zip(times, times[1:])):
        return "UNKNOWN"
    return classify_discovery(
        [float(row["close_value"]) for row in ordered],
        float(vah), float(val)
    )


def load_overview():
    now = datetime.now(timezone.utc)
    session_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT p.profile_id,p.reference_profile_id,p.session_date,p.method_version,p.profile_status,
                                  p.is_complete,p.expected_bars,p.observed_bars,p.missing_slots,
                                  p.duplicate_slots,p.invalid_slots,p.out_of_session_count,
                                  p.poc_lower,p.poc_upper,p.vah_upper,p.val_lower,p.total_tpos,
                                  o.opening_oi,o.latest_oi,o.absolute_change,o.percentage_change,
                                  o.context_state AS session_oi_class,o.units_verified
                           FROM amt_engine_v17.session_profiles p
                           LEFT JOIN amt_engine_v17.session_oi_context o USING(profile_id)
                           WHERE p.source='delta_india' AND p.symbol='BTCUSD'
                             AND p.method_version='AMT_ENGINE_V1.7'
                             AND p.profile_status IN ('DEVELOPING','COMPLETE')
                           ORDER BY p.session_date DESC LIMIT 1""")
            profile = cur.fetchone()

            developing = None
            prior_profile = None
            if profile:
                cur.execute("""SELECT count(*) AS snapshots,
                                      (array_agg(developing_poc_lower ORDER BY candle_open DESC))[1] AS dpoc_lower,
                                      (array_agg(developing_poc_upper ORDER BY candle_open DESC))[1] AS dpoc_upper,
                                      (array_agg(developing_vah_upper ORDER BY candle_open DESC))[1] AS dvah,
                                      (array_agg(developing_val_lower ORDER BY candle_open DESC))[1] AS dval,
                                      max(candle_close) AS last_candle_close
                               FROM amt_engine_v17.developing_snapshots
                               WHERE profile_id=%s""", (profile["profile_id"],))
                developing = cur.fetchone()
                if profile.get("profile_id"):
                    reference_id = (
                        profile["reference_profile_id"]
                        if profile["profile_status"] == "DEVELOPING"
                        else profile["profile_id"]
                    )
                    cur.execute("""SELECT profile_id,session_date,poc_lower,poc_upper,vah_upper,val_lower
                                   FROM amt_engine_v17.session_profiles
                                   WHERE profile_id=%s AND profile_status='COMPLETE' AND is_complete=true""",
                                (reference_id,))
                    prior_profile = cur.fetchone()

            # Live candles are read from the collector branch; production AMT profiles
            # and the shadow ledger remain on the production branch above/below.
            with _connect("SOURCE_DATABASE_URL", EXPECTED_SOURCE_HOST) as source_conn:
                with source_conn.cursor() as source_cur:
                    source_cur.execute("""SELECT candle_time,open_value,high_value,low_value,close_value,retrieved_at
                                          FROM research.delta_candles
                                          WHERE source='delta_india' AND series_type='PRICE' AND symbol='BTCUSD'
                                            AND resolution='30m'
                                            AND candle_time >= %s
                                            AND candle_time + interval '30 minutes' <= %s
                                          ORDER BY candle_time""", (session_start, now))
                    latest_price_rows = source_cur.fetchall()

                    source_cur.execute("""SELECT candle_time,open_value,close_value,retrieved_at
                                          FROM research.delta_candles
                                          WHERE source='delta_india' AND series_type='OI' AND symbol='OI:BTCUSD'
                                            AND resolution='30m' AND candle_time >= %s
                                            AND retrieved_at <= %s
                                          ORDER BY retrieved_at""", (session_start, now))
                    oi_rows = source_cur.fetchall()

            cur.execute("""SELECT trade_key,session_date,pattern,side,status,signal_candle_close,
                                  entry_time_utc,entry_price,stop_price,target_price,risk_points,
                                  discovery_state,opening_oi,entry_oi,oi_delta,oi_class,
                                  exit_candle_close,exit_price,exit_reason,realized_r
                           FROM amt_engine_v17.playbook_v13_shadow_trades
                           ORDER BY signal_candle_close DESC LIMIT 12""")
            trades = cur.fetchall()

            cur.execute("""SELECT shadow_started_at,last_processed_candle_open,starting_realized_r
                           FROM amt_engine_v17.playbook_v13_shadow_state WHERE singleton=true""")
            shadow_state = cur.fetchone()
            cur.execute("""SELECT COALESCE(sum(realized_r),0) AS realized_r,
                                  count(*) AS total_trades,
                                  count(*) FILTER (WHERE status='OPEN') AS open_trades
                           FROM amt_engine_v17.playbook_v13_shadow_trades""")
            shadow_totals = cur.fetchone()

    vah = prior_profile.get("vah_upper") if prior_profile else None
    val = prior_profile.get("val_lower") if prior_profile else None
    live_discovery = _discovery(latest_price_rows, vah, val)
    opening_row = next(
        (row for row in oi_rows if row["candle_time"].astimezone(timezone.utc) == session_start),
        None,
    )
    latest_oi_row = max(oi_rows, key=lambda row: row["retrieved_at"], default=None)
    oi_context = {
        "opening_oi": float(opening_row["open_value"])
            if opening_row and opening_row["open_value"] is not None else None,
        "entry_oi": float(latest_oi_row["close_value"])
            if latest_oi_row and latest_oi_row["close_value"] is not None else None,
    }
    if oi_context["opening_oi"] is None or oi_context["entry_oi"] is None:
        oi_context.update({"delta": None, "class": "UNKNOWN"})
    else:
        delta = oi_context["entry_oi"] - oi_context["opening_oi"]
        oi_context.update({"delta": delta, "class": "EXPANSION" if delta > 0 else "CONTRACTION_OR_FLAT"})

    return _json({
        "as_of_utc": now,
        "profile": profile,
        "prior_profile": prior_profile,
        "developing": {
            **(developing or {}),
            "progress": f"{int(developing['snapshots']) if developing else 0}/48",
        } if profile else None,
        "live": {
            "price": latest_price_rows[-1] if latest_price_rows else None,
            "discovery": live_discovery,
            "oi": oi_context,
        },
        "shadow": {"state": shadow_state, "totals": shadow_totals, "trades": trades},
    })


@app.get("/", response_class=HTMLResponse)
def index(_username: str = Depends(require_dashboard_auth)):
    return HTML


@app.get("/health")
def health():
    return {"status": "ok", "service": "btc-v17-v13-dashboard"}


@app.get("/api/overview")
def overview(_username: str = Depends(require_dashboard_auth)):
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["at"] < 10:
        return JSONResponse(_cache["data"])
    try:
        data = load_overview()
        _cache.update({"at": now, "data": data})
        return JSONResponse(data)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Dashboard data unavailable: {type(exc).__name__}") from exc


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTC | V1.7 + Playbook V1.3</title>
<style>
:root{color-scheme:dark;--bg:#0b1018;--panel:#121b28;--line:#243247;--muted:#93a4b8;--text:#e8eef7;--cyan:#58c7dc;--green:#52d6a1;--red:#ff7b86;--amber:#f2c66d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 Inter,ui-sans-serif,system-ui,sans-serif}
main{max-width:1440px;margin:auto;padding:22px}header{display:flex;justify-content:space-between;align-items:center;gap:16px;border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:18px}
h1{font-size:20px;margin:0;letter-spacing:.02em}h2{font-size:13px;color:var(--muted);font-weight:650;text-transform:uppercase;letter-spacing:.09em;margin:0 0 14px}
small,.muted{color:var(--muted)}.stamp{font:12px ui-monospace,monospace;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:12px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;min-width:0}
.metric{font:600 23px ui-monospace,monospace;margin-top:7px}.sub{font-size:12px;color:var(--muted);margin-top:4px}
.section{margin-top:14px}.levels{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.level{padding:12px;border:1px solid var(--line);border-radius:9px}.level b{display:block;font:600 18px ui-monospace,monospace;margin-top:5px}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--muted);font-weight:600}
.scroll{overflow-x:auto}.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:3px 8px;font-size:11px}
.green{color:var(--green)}.red{color:var(--red)}.amber{color:var(--amber)}.cyan{color:var(--cyan)}
footer{margin-top:18px;color:var(--muted);font-size:11px}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){main{padding:12px}.grid{grid-template-columns:1fr 1fr}.metric{font-size:19px}.levels{grid-template-columns:1fr}}
</style></head>
<body><main>
<header><div><h1>BTC / V1.7 AMT + PLAYBOOK V1.3</h1><div class="muted">Read-only market structure and shadow observation</div></div><div class="stamp" id="asof">Loading…</div></header>
<section class="grid">
 <div class="panel"><h2>Latest BTC price</h2><div class="metric" id="price">—</div><div class="sub" id="price-time">—</div></div>
 <div class="panel"><h2>Causal discovery</h2><div class="metric" id="discovery">—</div><div class="sub">Completed 30m closes only</div></div>
 <div class="panel"><h2>Live OI class</h2><div class="metric" id="oi-class">—</div><div class="sub" id="oi-delta">—</div></div>
 <div class="panel"><h2>Shadow ledger</h2><div class="metric" id="shadow-r">0.0R</div><div class="sub" id="shadow-state">—</div></div>
</section>
<section class="panel section"><h2>AMT structure — latest complete V1.7 session</h2>
 <div class="levels">
  <div class="level"><small>Prior VAH / current profile</small><b id="vah">—</b></div>
  <div class="level"><small>Prior POC</small><b id="poc">—</b></div>
  <div class="level"><small>Prior VAL</small><b id="val">—</b></div>
 </div>
 <div class="sub" id="profile-meta">—</div>
</section>
<section class="panel section"><h2>Developing value — persisted V1.7 snapshots</h2>
 <div class="levels">
  <div class="level"><small>dVAH</small><b id="dvah">—</b></div>
  <div class="level"><small>dPOC</small><b id="dpoc">—</b></div>
  <div class="level"><small>dVAL</small><b id="dval">—</b></div>
 </div>
 <div class="sub" id="developing-meta">—</div>
</section>
<section class="panel section"><h2>Playbook V1.3 — active and recent shadow trades</h2>
 <div class="scroll"><table><thead><tr><th>Session</th><th>Pattern</th><th>Side</th><th>Status</th><th>Entry</th><th>Stop</th><th>Target</th><th>Discovery</th><th>OI class</th><th>Exit</th><th>R</th></tr></thead><tbody id="trades"><tr><td colspan="11">Loading…</td></tr></tbody></table></div>
</section>
<footer>Research-only. No order routing, alerts, or execution. Developing values show persisted candle-by-candle V1.7 snapshots; live price and causal state use the latest available completed source candles. Refreshes every 10 seconds.</footer>
</main>
<script>
const fmt=v=>v===null||v===undefined?'—':Number(v).toLocaleString('en-US',{maximumFractionDigits:2});
const cls=v=>String(v||'').includes('ABOVE')||v==='EXPANSION'?'green':String(v||'').includes('BELOW')||v==='CONTRACTION_OR_FLAT'?'red':'amber';
async function refresh(){
 const r=await fetch('/api/overview',{cache:'no-store'});if(!r.ok)throw new Error('API '+r.status);
 const d=await r.json();const p=d.profile||{},v=d.developing||{},l=d.live||{},sh=d.shadow||{};
 document.getElementById('asof').textContent='UTC '+new Date(d.as_of_utc).toISOString().replace('T',' ').slice(0,19);
 const px=l.price||{};document.getElementById('price').textContent=fmt(px.close_value);
 document.getElementById('price-time').textContent=px.candle_time?'Candle '+new Date(px.candle_time).toISOString().slice(0,16)+' UTC':'No live candle';
 const dis=document.getElementById('discovery');dis.textContent=l.discovery||'UNKNOWN';dis.className='metric '+cls(l.discovery);
 const oi=l.oi||{};const oiEl=document.getElementById('oi-class');oiEl.textContent=oi.class||'UNKNOWN';oiEl.className='metric '+cls(oi.class);
 document.getElementById('oi-delta').textContent=oi.delta===null?'OI unavailable':'Δ '+fmt(oi.delta)+' BTC';
 document.getElementById('vah').textContent=fmt((d.prior_profile||{}).vah_upper);document.getElementById('poc').textContent=fmt((d.prior_profile||{}).poc_lower)+'–'+fmt((d.prior_profile||{}).poc_upper);document.getElementById('val').textContent=fmt((d.prior_profile||{}).val_lower);
 document.getElementById('profile-meta').textContent=p.session_date?'Developing session '+p.session_date+' · '+p.profile_status+' · '+p.observed_bars+'/48 candles · prior reference '+((d.prior_profile||{}).session_date||'unavailable'):'No V1.7 session profile';
 document.getElementById('dvah').textContent=fmt(v.dvah);document.getElementById('dpoc').textContent=fmt(v.dpoc_lower)+'–'+fmt(v.dpoc_upper);document.getElementById('dval').textContent=fmt(v.dval);
 document.getElementById('developing-meta').textContent=v.progress?'Persisted progress '+v.progress+' · last candle close '+(v.last_candle_close?new Date(v.last_candle_close).toISOString():'—'):'No developing snapshots';
 const state=sh.state||{};document.getElementById('shadow-state').textContent=state.shadow_started_at?'Started '+new Date(state.shadow_started_at).toISOString().slice(0,16)+' · baseline '+fmt(state.starting_realized_r)+'R':'Shadow migration not applied';
 const trades=sh.trades||[];const open=trades.filter(t=>t.status==='OPEN').length;const total=trades.filter(t=>t.realized_r!==null).reduce((a,t)=>a+Number(t.realized_r),0);
 const totals=sh.totals||{};document.getElementById('shadow-r').textContent=Number(totals.realized_r||0).toFixed(2)+'R';document.getElementById('shadow-state').textContent+=' · '+(totals.open_trades||0)+' open · '+(totals.total_trades||0)+' total trades';
 document.getElementById('trades').innerHTML=trades.length?trades.map(t=>'<tr><td>'+t.session_date+'</td><td>'+t.pattern+'</td><td>'+t.side+'</td><td>'+t.status+'</td><td>'+fmt(t.entry_price)+'</td><td>'+fmt(t.stop_price)+'</td><td>'+fmt(t.target_price)+'</td><td>'+t.discovery_state+'</td><td>'+t.oi_class+'</td><td>'+ (t.exit_reason||'—')+'</td><td>'+ (t.realized_r===null?'—':Number(t.realized_r).toFixed(2)+'R')+'</td></tr>').join(''):'<tr><td colspan="11">No shadow trades logged yet</td></tr>';
}
refresh().catch(e=>{document.getElementById('asof').textContent='Data unavailable: '+e.message});setInterval(()=>refresh().catch(()=>{}),10000);
</script></body></html>"""
