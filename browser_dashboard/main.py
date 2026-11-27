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
from browser_dashboard.auction_context import (\n    build_prior_auction_context, classify_live_range, build_prior_structure_status,\n)

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


def _session_rows(rows, session_date):
    """Keep Discovery history isolated to one UTC auction day."""
    return [row for row in rows if row["candle_time"].astimezone(timezone.utc).date() == session_date]


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



def _calculate_v17_developing_profile(rows, session_start, now):
    """Calculate a read-only current-session profile using the frozen V1.7 TPO rules.

    Only a contiguous prefix of completed 30m candles from 00:00 UTC is eligible.
    The profile is withheld if the available prefix contains a gap or invalid OHLC.
    """
    from decimal import ROUND_FLOOR, ROUND_CEILING

    session_start = session_start.astimezone(timezone.utc)
    now = now.astimezone(timezone.utc)
    session_end = session_start + timedelta(hours=24)
    completed = []
    for row in sorted(rows, key=lambda item: item["candle_time"]):
        candle_open = row["candle_time"].astimezone(timezone.utc)
        candle_close = candle_open + timedelta(minutes=30)
        if candle_open < session_start or candle_open >= session_end or candle_close > now:
            continue
        completed.append(row)

    prefix = []
    expected_open = session_start
    status = "READY"
    for row in completed:
        candle_open = row["candle_time"].astimezone(timezone.utc)
        if candle_open != expected_open:
            status = "GAP_IN_COMPLETED_CANDLE_SEQUENCE"
            break
        try:
            low = Decimal(str(row["low_value"]))
            high = Decimal(str(row["high_value"]))
        except Exception:
            status = "INVALID_OHLC"
            break
        if not low.is_finite() or not high.is_finite() or low < 0 or high < low:
            status = "INVALID_OHLC"
            break
        prefix.append((low, high))
        expected_open += timedelta(minutes=30)

    result = {
        "progress": f"{len(prefix)}/48",
        "candle_count": len(prefix),
        "status": status if completed else "WAITING_FOR_FIRST_COMPLETED_CANDLE",
        "method_version": "AMT_ENGINE_V1.7",
        "row_size": 50,
        "value_area_fraction": 0.70,
        "session_start_utc": session_start,
        "dvah": None,
        "dpoc_lower": None,
        "dpoc_upper": None,
        "dval": None,
        "total_tpos": None,
    }
    if not prefix or status != "READY":
        return result

    # V1.7: zero-anchored $50 bins; each candle hits floor(low/50)..floor(high/50),
    # inclusive. The dense ladder retains zero-count rows between occupied bins.
    counts = {}
    for low, high in prefix:
        low_idx = int((low / Decimal(50)).to_integral_value(rounding=ROUND_FLOOR))
        high_idx = int((high / Decimal(50)).to_integral_value(rounding=ROUND_FLOOR))
        for row_index in range(low_idx, high_idx + 1):
            counts[row_index] = counts.get(row_index, 0) + 1

    min_index = min(counts)
    max_index = max(counts)
    dense = {idx: counts.get(idx, 0) for idx in range(min_index, max_index + 1)}
    total_tpos = sum(dense.values())
    target_tpos = int(
        (Decimal(total_tpos) * Decimal("0.70")).to_integral_value(rounding=ROUND_CEILING)
    )

    # V1.7 POC tie-break: lowest row_index among rows with the maximum TPO count.
    max_count = max(dense.values())
    poc_index = min(idx for idx, count in dense.items() if count == max_count)

    lo_index = hi_index = poc_index
    covered = dense[poc_index]
    while covered < target_tpos and (lo_index > min_index or hi_index < max_index):
        left_count = dense.get(lo_index - 1, 0)
        right_count = dense.get(hi_index + 1, 0)
        if lo_index == min_index:
            choose_left = False
        elif hi_index == max_index:
            choose_left = True
        else:
            # V1.7 tie-break: equal adjacent counts choose the lower row.
            choose_left = left_count >= right_count
        if choose_left:
            lo_index -= 1
            covered += left_count
        else:
            hi_index += 1
            covered += right_count

    result.update({
        "status": "READY",
        "dvah": Decimal((hi_index + 1) * 50),
        "dpoc_lower": Decimal(poc_index * 50),
        "dpoc_upper": Decimal((poc_index + 1) * 50),
        "dval": Decimal(lo_index * 50),
        "total_tpos": total_tpos,
        "target_tpos": target_tpos,
        "value_area_tpos": covered,
    })
    return result


def load_overview():
    now = datetime.now(timezone.utc)
    session_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    auction_query_start = session_start - timedelta(days=3)
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

            prior_profile = None
            completed_profiles = []
            if profile:
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

            cur.execute("""SELECT session_date,poc_lower,vah_upper,val_lower
                           FROM amt_engine_v17.session_profiles
                           WHERE source='delta_india' AND symbol='BTCUSD'
                             AND method_version='AMT_ENGINE_V1.7'
                             AND profile_status='COMPLETE' AND is_complete=true
                             AND reference_status='AVAILABLE'
                           ORDER BY session_date DESC LIMIT 2""")
            completed_profiles = list(reversed(cur.fetchall()))

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
                                          ORDER BY candle_time""", (auction_query_start, now))
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
    current_session_rows = _session_rows(latest_price_rows, session_start.date())
    live_developing = _calculate_v17_developing_profile(
        current_session_rows, session_start, now
    )
    live_discovery = _discovery(current_session_rows, vah, val)
    candle_days = {}
    for candle in latest_price_rows:
        candle_day = candle["candle_time"].astimezone(timezone.utc).date()
        candle_days.setdefault(candle_day, []).append(candle)
    completed_candles = []
    for item in completed_profiles:
        day = item["session_date"]
        day_rows = candle_days.get(day, [])
        completed_candles.append({
            "session_date": day,
            "range": {
                "high": max((float(x["high_value"]) for x in day_rows), default=None),
                "low": min((float(x["low_value"]) for x in day_rows), default=None),
                "close": float(day_rows[-1]["close_value"]) if day_rows else None,
            } if day_rows else None,
        })
    auction_context = build_prior_auction_context(
        completed_profiles, completed_candles,
        candle_days.get(session_start.date(), []),
    )
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
        "developing": live_developing,
        "auction_context": auction_context,
        "live": {
            "price": latest_price_rows[-1] if latest_price_rows else None,
            "discovery": live_discovery,
            "oi": oi_context,
        },
        "shadow": {"state": shadow_state, "totals": shadow_totals, "trades": trades},
    })


def load_nifty_overview():
    from amt_engine.nifty_v17 import fetch_yahoo, aggregate_session, calculate_profile
    from zoneinfo import ZoneInfo
    now = datetime.now(timezone.utc)
    local_now = now.astimezone(ZoneInfo("Asia/Kolkata"))
    frame = fetch_yahoo("5d", local_now)
    day = local_now.date()
    current_rows = frame[frame["session_date"] == day]
    bars, diagnostics = aggregate_session(frame, day)
    prefix = []
    for bar in bars:
        if bar["bracket"] != len(prefix) + 1:
            break
        prefix.append(bar)
    developing = calculate_profile(prefix) if prefix else None
    latest = frame.iloc[-1] if not frame.empty else None
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT session_date,vah,poc,val,session_high,session_low,session_close,
                                  close_location,value_migration,range_structure,profile_sha256
                           FROM amt_nifty_v17.sessions ORDER BY session_date DESC LIMIT 1""")
            prior = cur.fetchone()
    current_range = None if current_rows.empty else {
        "high":float(current_rows["high"].max()),"low":float(current_rows["low"].min())}
    prior_range = None if prior is None else {
        "high":float(prior["session_high"]),"low":float(prior["session_low"])}
    nifty_live_swing = {"label":"Unavailable","current_range":None,"prior_range":prior_range,
                        "prior_structure_status":build_prior_structure_status(
                            prior.get("range_structure") if prior else None, None, None,
                            prior_range["high"] if prior_range else None,
                            prior_range["low"] if prior_range else None,
                            float(prior["vah"]) if prior and prior.get("vah") is not None else None,
                            float(prior["val"]) if prior and prior.get("val") is not None else None)}
    if current_range and prior_range:
        nifty_live_swing = {
            "label": classify_live_range(current_range["high"], current_range["low"],
                                          prior_range["high"], prior_range["low"]),
            "current_range": current_range, "prior_range": prior_range,
            "prior_structure_status": build_prior_structure_status(
                prior.get("range_structure") if prior else None,
                current_range["high"], current_range["low"],
                prior_range["high"], prior_range["low"],
                float(prior["vah"]) if prior and prior.get("vah") is not None else None,
                float(prior["val"]) if prior and prior.get("val") is not None else None)}
    return _json({"as_of_utc":now,"latest_price":None if latest is None else {
        "close":float(latest["close"]),"timestamp":latest["timestamp"].to_pydatetime()},
        "prior":prior,"developing":None if developing is None else {
        "dvah":developing["vah"],"dpoc":developing["poc"],"dval":developing["val"],"status":"READY"},
        "progress":f"{len(prefix)}/13","diagnostics":diagnostics,
        "current_range":current_range,"prior_range":prior_range,
        "live_intraday_swing":nifty_live_swing})


@app.get("/api/nifty-overview")
def nifty_overview(_username: str = Depends(require_dashboard_auth)):
    try:
        return JSONResponse(load_nifty_overview())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Nifty data unavailable: {type(exc).__name__}") from exc

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
<title>BTCUSD | NIFTY 50 Spot · AMT Dashboard</title>
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
footer{margin-top:18px;color:var(--muted);font-size:11px}.structure-status{margin-top:9px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;font-weight:700}
.tabbar{display:flex;gap:8px;margin:0 0 16px}.tab{border:1px solid var(--line);background:var(--panel);color:var(--muted);padding:9px 16px;border-radius:9px;font-weight:650;cursor:pointer}.tab.active{color:var(--text);border-color:var(--cyan);box-shadow:inset 0 -2px var(--cyan)}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){main{padding:12px}.grid{grid-template-columns:1fr 1fr}.metric{font-size:19px}.levels{grid-template-columns:1fr}}
</style></head>
<body><main>
<header><div><h1>MARKET AMT DASHBOARD</h1><div class="muted">Read-only market structure and observation</div></div><div class="stamp" id="asof">Loading…</div></header>
<nav class="tabbar" aria-label="Market dashboard"><button id="tab-btc" class="tab active" type="button">BTCUSD</button><button id="tab-nifty" class="tab" type="button">NIFTY 50 SPOT</button></nav>
<section id="nifty-view" class="section" hidden>
<section class="grid">
<div class="panel"><h2>Latest NIFTY 50 Spot</h2><div class="metric" id="nifty-price">—</div><div class="sub" id="nifty-price-time">Completed 15m Yahoo candle</div></div>
<div class="panel"><h2>Prior Session Close Location</h2><div class="metric" id="nifty-close-location">—</div><div class="sub" id="nifty-session-date">—</div></div>
<div class="panel"><h2>Value Migration</h2><div class="metric" id="nifty-migration">—</div><div class="sub">Prior completed auction</div></div>
<div class="panel"><h2>Range Structure</h2><div class="metric" id="nifty-range-structure">—</div><div class="sub">Compared with previous completed session</div></div>
</section>
<section class="panel section"><h2>Prior Completed Session · VAH / POC / VAL</h2><div class="levels"><div class="level"><small>VAH</small><b id="nifty-vah">—</b></div><div class="level"><small>POC</small><b id="nifty-poc">—</b></div><div class="level"><small>VAL</small><b id="nifty-val">—</b></div></div></section>
<section class="panel section"><h2>Live Developing Value · <span id="nifty-progress">0/13</span> completed brackets</h2><div class="levels"><div class="level"><small>dVAH</small><b id="nifty-dvah">—</b></div><div class="level"><small>dPOC</small><b id="nifty-dpoc">—</b></div><div class="level"><div><small>dVAL</small><b id="nifty-dval">—</b></div></div></div><div class="sub" id="nifty-developing-status">Completed 15m Yahoo candles only.</div></section>
<section class="panel section"><h2>Live Intraday Range vs. Prior Day</h2><div class="levels"><div class="level"><small>Current High</small><b id="nifty-current-high">—</b></div><div class="level"><small>Current Low</small><b id="nifty-current-low">—</b></div><div class="level"><small>Prior Range</small><b id="nifty-prior-range">—</b></div></div><div class="sub" id="nifty-range-status">Read-only completed 15m Yahoo range comparison.</div><div class="sub" id="nifty-range-classification">Live range structure: —</div><div class="sub structure-status" id="nifty-prior-structure-status">Prior structure: —</div></section>
<footer>NIFTY 50 Spot · Yahoo Finance ^NSEI · 10-point TPO rows · 70% value area · 09:15–15:30 IST. No OI or BTC data dependency.</footer>
</section>
<div id="btc-view">
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
<section class="panel section"><h2>LIVE DEVELOPING VALUE · CURRENT SESSION (<span id="developing-progress">0/48</span> CANDLES)</h2>
 <div class="levels">
  <div class="level"><small>dVAH</small><b id="dvah">—</b></div>
  <div class="level"><small>dPOC</small><b id="dpoc">—</b></div>
  <div class="level"><small>dVAL</small><b id="dval">—</b></div>
 </div>
 <div class="sub" id="developing-meta">Live intraday visual aid only · separate from frozen Prior Reference VAH/POC/VAL used by Playbook v1.3.</div>
</section>
<section class="panel section"><h2>Prior Completed Auction · 00:00–00:00 UTC / 05:30–05:30 IST</h2>
 <div class="levels">
  <div class="level"><small>Close Location</small><b id="auction-close">—</b></div>
  <div class="level"><small>Value Migration</small><b id="auction-migration">—</b></div>
  <div class="level"><small>Swing Structure</small><b id="auction-swing">—</b></div>
 </div><div class="sub" id="auction-date">Descriptive context only · compares the latest two completed auctions</div>
</section>
<section class="panel section"><h2>Sub-Session Development · UTC</h2>
 <div class="levels" id="subsessions">
  <div class="level"><small>Asia · 00:00–08:00</small><b>—</b><div class="sub">Range / extension</div></div>
  <div class="level"><small>Europe · 08:00–13:30</small><b>—</b><div class="sub">Range / extension</div></div>
  <div class="level"><small>US · 13:30–00:00</small><b>—</b><div class="sub">Range / extension</div></div>
 </div><div class="sub" id="live-swing-vs-prior">Live intraday swing vs prior completed auction: awaiting completed candles</div>
 <div class="sub">Range development only; factual comparison of completed 30m candles, no directional prediction</div>
</section>
<section class="panel section"><h2>Playbook V1.3 — active and recent shadow trades</h2>
 <div class="scroll"><table><thead><tr><th>Session</th><th>Pattern</th><th>Side</th><th>Status</th><th>Entry</th><th>Stop</th><th>Target</th><th>Discovery</th><th>OI class</th><th>Exit</th><th>R</th></tr></thead><tbody id="trades"><tr><td colspan="11">Loading…</td></tr></tbody></table></div>
</section>
<footer>Research-only. No order routing, alerts, or execution. Developing values show persisted candle-by-candle V1.7 snapshots; live price and causal state use the latest available completed source candles. Refreshes every 10 seconds.</footer>
</div><!-- /btc-view -->
</main>
<script>
let activeMarket='btc';
function selectMarket(market){
 activeMarket=market;
 document.getElementById('btc-view').hidden=market!=='btc';
 document.getElementById('nifty-view').hidden=market!=='nifty';
 document.getElementById('tab-btc').classList.toggle('active',market==='btc');
 document.getElementById('tab-nifty').classList.toggle('active',market==='nifty');
 if(market==='nifty')refreshNifty().catch(e=>{document.getElementById('nifty-developing-status').textContent='Nifty data unavailable: '+e.message});
}
async function refreshNifty(){
 const r=await fetch('/api/nifty-overview',{cache:'no-store'});if(!r.ok)throw new Error('API '+r.status);
 const d=await r.json(),p=d.prior||{},v=d.developing||{},cr=d.current_range||{},pr=d.prior_range||{},px=d.latest_price||{};
 document.getElementById('nifty-price').textContent=fmt(px.close);
 document.getElementById('nifty-price-time').textContent=px.timestamp?'Completed 15m candle · '+new Date(px.timestamp).toISOString().slice(0,16)+' UTC':'No completed Yahoo candle';
 document.getElementById('nifty-session-date').textContent=p.session_date?'Session '+p.session_date:'No persisted completed session';
 document.getElementById('nifty-close-location').textContent=p.close_location||'—';
 document.getElementById('nifty-migration').textContent=p.value_migration||'—';
 document.getElementById('nifty-range-structure').textContent=p.range_structure||'—';
 document.getElementById('nifty-vah').textContent=fmt(p.vah);document.getElementById('nifty-poc').textContent=fmt(p.poc);document.getElementById('nifty-val').textContent=fmt(p.val);
 document.getElementById('nifty-progress').textContent=d.progress||'0/13';
 document.getElementById('nifty-dvah').textContent=fmt(v.dvah);document.getElementById('nifty-dpoc').textContent=fmt(v.dpoc);document.getElementById('nifty-dval').textContent=fmt(v.dval);
 document.getElementById('nifty-developing-status').textContent=v.status==='READY'?'Computed from '+d.progress+' completed brackets; informational only.':'No contiguous completed bracket prefix yet.';
 document.getElementById('nifty-current-high').textContent=fmt(cr.high);document.getElementById('nifty-current-low').textContent=fmt(cr.low);
 document.getElementById('nifty-prior-range').textContent=pr.high===undefined?'—':fmt(pr.low)+' – '+fmt(pr.high);
 document.getElementById('nifty-range-status').textContent=cr.high===undefined?'Current completed-candle range unavailable.':'Current completed-candle range '+fmt(cr.low)+' – '+fmt(cr.high)+(pr.high===undefined?'':' vs prior '+fmt(pr.low)+' – '+fmt(pr.high));
 const ns=d.live_intraday_swing||{},nps=ns.prior_structure_status||{},ni=nps.inflection||{};
 document.getElementById('nifty-range-classification').textContent='LIVE RANGE STRUCTURE · '+(ns.label||'Unavailable');
 document.getElementById('nifty-prior-structure-status').textContent=(nps.label||'PRIOR STRUCTURE UNAVAILABLE')+(ni.price_name?' · '+ni.price_name+' '+fmt(ni.price)+' · '+ni.value_name+' '+fmt(ni.value):'');
 document.getElementById('nifty-prior-structure-status').className='sub structure-status '+(nps.status==='BROKEN'?'red':nps.status==='INTACT'?'green':'amber');
}

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
 document.getElementById('developing-progress').textContent=v.progress||'0/48';
 document.getElementById('dvah').textContent=fmt(v.dvah);document.getElementById('dpoc').textContent=fmt(v.dpoc_lower)+'–'+fmt(v.dpoc_upper);document.getElementById('dval').textContent=fmt(v.dval);
 const developingStatus=v.status==='READY'?'Computed from '+(v.candle_count||0)+' completed 30m candles · V1.7 $50-bin TPO. Visual aid only; separate from frozen Prior Reference VAH/POC/VAL used by Playbook v1.3.':(v.status||'LIVE DEVELOPING PROFILE UNAVAILABLE')+' · No developing levels displayed. Visual aid only; Playbook v1.3 continues to use frozen Prior Reference VAH/POC/VAL.';
 document.getElementById('developing-meta').textContent=developingStatus;
 const state=sh.state||{};document.getElementById('shadow-state').textContent=state.shadow_started_at?'Started '+new Date(state.shadow_started_at).toISOString().slice(0,16)+' · baseline '+fmt(state.starting_realized_r)+'R':'Shadow migration not applied';
 const auction=d.auction_context||{};
 document.getElementById('auction-close').textContent=auction.close_location||'Unavailable';
 document.getElementById('auction-migration').textContent=auction.value_migration||'Unavailable';
 document.getElementById('auction-swing').textContent=auction.swing_structure||'Unavailable';
 document.getElementById('auction-date').textContent=auction.session_date?'Completed auction '+auction.session_date+' UTC · descriptive, non-predictive':'Completed auction context unavailable';
 const liveSwing=auction.live_intraday_swing||{};
 const currentRange=liveSwing.current_range, priorRange=liveSwing.prior_range;
 const priorStatus=liveSwing.prior_structure_status||{}, inflection=priorStatus.inflection||{};
 const liveSwingText=currentRange&&priorRange
  ? 'LIVE INTRADAY RANGE · '+(liveSwing.label||'Unavailable')+' · Current '+fmt(currentRange.low)+' – '+fmt(currentRange.high)+' vs prior '+fmt(priorRange.low)+' – '+fmt(priorRange.high)+' · '+(liveSwing.completed_candles||0)+' completed candles'
  : 'LIVE INTRADAY RANGE · '+(liveSwing.label||'Unavailable')+' · Range comparison unavailable';
 const statusText=(priorStatus.label||'PRIOR STRUCTURE UNAVAILABLE')+(inflection.price_name?' · '+inflection.price_name+' '+fmt(inflection.price)+' · '+inflection.value_name+' '+fmt(inflection.value):'');
 const liveNode=document.getElementById('live-swing-vs-prior');
 liveNode.innerHTML='<div>'+liveSwingText+'</div><div class="structure-status '+(priorStatus.status==='BROKEN'?'red':priorStatus.status==='INTACT'?'green':'amber')+'>'+statusText+'</div>';

 document.getElementById('subsessions').innerHTML=(auction.subsessions||[]).map((s,i)=>{
  const range=s.range?fmt(s.range.low)+' – '+fmt(s.range.high):'Not started';
  const label=['Asia · 00:00–08:00','Europe · 08:00–13:30','US · 13:30–00:00'][i];
  return '<div class="level"><small>'+label+' UTC</small><b>'+range+'</b><div class="sub">'+(s.development||'Unavailable')+'</div></div>';
 }).join('');
 const trades=sh.trades||[];const open=trades.filter(t=>t.status==='OPEN').length;const total=trades.filter(t=>t.realized_r!==null).reduce((a,t)=>a+Number(t.realized_r),0);
 const totals=sh.totals||{};document.getElementById('shadow-r').textContent=Number(totals.realized_r||0).toFixed(2)+'R';document.getElementById('shadow-state').textContent+=' · '+(totals.open_trades||0)+' open · '+(totals.total_trades||0)+' total trades';
 document.getElementById('trades').innerHTML=trades.length?trades.map(t=>'<tr><td>'+t.session_date+'</td><td>'+t.pattern+'</td><td>'+t.side+'</td><td>'+t.status+'</td><td>'+fmt(t.entry_price)+'</td><td>'+fmt(t.stop_price)+'</td><td>'+fmt(t.target_price)+'</td><td>'+t.discovery_state+'</td><td>'+t.oi_class+'</td><td>'+ (t.exit_reason||'—')+'</td><td>'+ (t.realized_r===null?'—':Number(t.realized_r).toFixed(2)+'R')+'</td></tr>').join(''):'<tr><td colspan="11">No shadow trades logged yet</td></tr>';
}
document.getElementById('tab-btc').addEventListener('click',()=>selectMarket('btc'));document.getElementById('tab-nifty').addEventListener('click',()=>selectMarket('nifty'));refresh().catch(e=>{document.getElementById('asof').textContent='Data unavailable: '+e.message});setInterval(()=>{if(activeMarket==='btc')refresh().catch(()=>{});else refreshNifty().catch(()=>{});},10000);
</script></body></html>"""
