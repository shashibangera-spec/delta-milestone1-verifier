import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import math
import json

import pandas as pd
import plotly.graph_objects as go
import psycopg
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from oi_attribution import calculate_value_area_oi_breakdown
from amt_engine.daily import calculate_profile, validate_session
from amt_engine.developing import calculate_developing_profile
from session_selection import LIVE_SESSION_LABEL, normalize_session_selection, return_to_live_session

st.set_page_config(page_title="BTC AMT Research Dashboard", page_icon="📊", layout="centered")

ROW_SIZE = 50.0
VALUE_AREA = 0.70
IST = timezone(timedelta(hours=5, minutes=30))

@st.cache_resource
def get_connection():
    url = os.environ["DATABASE_URL"]
    conn = psycopg.connect(url, autocommit=True, application_name="delta-amt-developing-staging")
    conn.execute("SET default_transaction_read_only = on")
    return conn

def runtime_db_status():
    row = get_connection().execute("""
        SELECT current_user,
               current_setting('default_transaction_read_only'),
               current_setting('transaction_read_only')
    """).fetchone()
    return {"role": row[0], "default_read_only": row[1], "transaction_read_only": row[2]}

def utc_midnight(dt):
    return dt.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

def fetch_data():
    conn = get_connection()
    # Full retained confirmed history is required for historical session selection.
    rows = conn.execute("""
        SELECT symbol, series_type, candle_time, open_value, high_value,
               low_value, close_value, volume
        FROM research.delta_candles
        WHERE source = 'delta_india'
          AND resolution = '30m'
          AND candle_time < now()
        ORDER BY candle_time ASC
    """).fetchall()
    provisional = conn.execute("""
        SELECT symbol, series_type, candle_time, open_value, high_value,
               low_value, close_value, status, observed_at
        FROM research.delta_candles_provisional
        WHERE source = 'delta_india'
          AND resolution = '30m'
          AND candle_time >= (date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') - interval '1 day'
          AND candle_time < now()
        ORDER BY candle_time DESC
    """).fetchall()
    cols = ["symbol","series_type","candle_time","open_value","high_value","low_value","close_value","volume"]
    pcols = ["symbol","series_type","candle_time","open_value","high_value","low_value","close_value","status","observed_at"]
    return pd.DataFrame(rows, columns=cols), pd.DataFrame(provisional, columns=pcols)

def tpo_profile(candles):
    counts = defaultdict(int)
    for c in candles:
        lo = math.floor(float(c["low_value"]) / ROW_SIZE)
        hi = math.floor(float(c["high_value"]) / ROW_SIZE)
        # One TPO per 30m bracket for each $50 row touched (inclusive).
        for bucket in range(lo, hi + 1):
            counts[bucket] += 1
    if not counts:
        return None
    max_count = max(counts.values())
    poc = min(k for k, v in counts.items() if v == max_count)
    total = sum(counts.values())
    target = math.ceil(total * VALUE_AREA)
    low = high = poc
    included = counts[poc]
    while included < target:
        lower_count = counts.get(low - 1, 0)
        upper_count = counts.get(high + 1, 0)
        if lower_count == 0 and upper_count == 0:
            break
        # Compare adjacent rows; ties expand downward.
        if lower_count >= upper_count:
            low -= 1
            included += lower_count
        else:
            high += 1
            included += upper_count
    return {
        "VAL": low * ROW_SIZE,
        "POC": poc * ROW_SIZE,
        "VAH": (high + 1) * ROW_SIZE,
        "TPOs": total,
        "Rows": len(counts),
    }

def candle_dicts(df):
    return df.to_dict("records")

def is_complete_session(df, start):
    expected = pd.date_range(start=start, periods=48, freq="30min")
    if df.empty:
        return False
    actual = pd.DatetimeIndex(df["candle_time"].sort_values().drop_duplicates())
    return len(df) == 48 and len(actual) == 48 and actual.equals(expected)

def complete_profile(df, start):
    if not is_complete_session(df, start):
        return None
    validated = validate_session(start.date(), candle_dicts(df))
    if not validated.valid:
        return None
    profile, rows = calculate_profile(start.date(), validated.candles)
    return {"VAL": float(profile.val_lower), "POC": float(profile.poc_lower),
            "VAH": float(profile.vah_upper), "TPOs": profile.total_tpos,
            "Rows": sum(1 for row in rows if row.tpo_count > 0),
            "ValueAreaTPOs": profile.value_area_tpos,
            "ValueAreaRows": sum(1 for row in rows if row.is_value_area)}

def sequence_diagnostics(frame, start):
    """Describe the observed confirmed prefix without querying or changing source data."""
    if frame.empty:
        return {"missing": 0, "duplicates": 0, "invalid": 0, "off_grid": 0, "contiguous": False}
    work = frame.copy()
    times = pd.to_datetime(work["candle_time"], utc=True, errors="coerce")
    bad_time = int(times.isna().sum())
    valid_mask = times.notna()
    work = work.loc[valid_mask].copy()
    times = times.loc[valid_mask]
    duplicates = int(times.duplicated(keep="first").sum())
    off_grid_mask = (times.dt.second != 0) | (times.dt.microsecond != 0) | ((times.astype("int64") // 1_000_000_000) % 1800 != 0)
    off_grid = int(off_grid_mask.sum())
    invalid = bad_time
    for _, row in work.iterrows():
        try:
            o, h, l, close = [float(row[k]) for k in ("open_value", "high_value", "low_value", "close_value")]
            if not all(math.isfinite(v) for v in (o, h, l, close)) or h < l or h < max(o, close) or l > min(o, close):
                invalid += 1
        except (TypeError, ValueError, OverflowError):
            invalid += 1
    start_ts = pd.Timestamp(start)
    latest = times.max() if not times.empty else None
    missing = 0
    if latest is not None and latest >= start_ts:
        last_slot = latest.floor("30min")
        expected = pd.date_range(start=start_ts, end=last_slot, freq="30min")
        observed = pd.DatetimeIndex(times.drop_duplicates())
        missing = len(expected.difference(observed))
    contiguous = (latest is not None and times.min() == start_ts and missing == 0
                  and duplicates == 0 and invalid == 0 and off_grid == 0
                  and len(times) == len(times.drop_duplicates()))
    return {"missing": missing, "duplicates": duplicates, "invalid": invalid,
            "off_grid": off_grid, "contiguous": bool(contiguous)}


def fmt_ts(value):
    if pd.isna(value):
        return "—"
    dt = pd.Timestamp(value).to_pydatetime()
    return dt.astimezone(IST).strftime("%d %b %Y, %H:%M:%S IST")

def money(value):
    return "—" if value is None or pd.isna(value) else f"${float(value):,.2f}"

st.title("BTC AMT Research Dashboard")
copy_snapshot_slot = st.empty()
st.caption("ISOLATED RESEARCH • Neon amt_research • SELECT-only database role")
try:
    db_status = runtime_db_status()
    st.caption(f"RUNTIME DB SAFETY · role={db_status['role']} · default_transaction_read_only={db_status['default_read_only']} · transaction_read_only={db_status['transaction_read_only']}")
except Exception as exc:
    st.error(f"Runtime database safety verification failed: {exc}")
    st.stop()

@st.cache_data(ttl=45)
def load_frames():
    price_frame, provisional_frame = fetch_data()
    return price_frame, provisional_frame, datetime.now(timezone.utc).isoformat()

try:
    price_df, provisional_df, data_refresh_utc = load_frames()
except Exception as exc:
    st.error(f"Database read failed: {exc}")
    st.stop()

price = price_df[(price_df.series_type == "PRICE") & (price_df.symbol == "BTCUSD")].copy()
oi = price_df[(price_df.series_type == "OI") & (price_df.symbol == "OI:BTCUSD")].copy()
for frame in (price, oi):
    if not frame.empty:
        frame["candle_time"] = pd.to_datetime(frame["candle_time"], utc=True)


# Optional multi-session research view; existing single-session flow remains unchanged.
st.divider()
st.subheader("HISTORICAL AUCTION RESEARCH · CUSTOM DATE RANGE")
st.caption("Inclusive AMT session dates. Each session is 05:30 IST to 05:30 IST and must contain 48 confirmed paired 30m PRICE/OI candles.")
available_research_dates = sorted({ts.date() for ts in price["candle_time"]}) if not price.empty else []
completed_research_dates = [d for d in available_research_dates if d < datetime.now(timezone.utc).date()]
if not completed_research_dates:
    st.info("No completed historical session dates are available for custom-range research yet.")
else:
    default_end = completed_research_dates[-1]
    default_start = completed_research_dates[max(0, len(completed_research_dates) - 3)]
    chosen_range = st.date_input(
        "CUSTOM SESSION RANGE · START → END", value=(default_start, default_end),
        min_value=completed_research_dates[0], max_value=completed_research_dates[-1],
        key="custom_auction_date_range",
        help="Both dates are included. Each date means 05:30 IST to the next 05:30 IST."
    )
    if st.button("Analyse custom date range", key="run_custom_auction_research"):
        if not isinstance(chosen_range, (tuple, list)) or len(chosen_range) != 2:
            st.warning("Select both a start date and an end date.")
        else:
            range_start_date, range_end_date = chosen_range
            if range_start_date > range_end_date:
                st.error("Start date must be on or before end date.")
            else:
                from multi_day_research import analyze_multi_day_range
                range_start = datetime.combine(range_start_date, datetime.min.time(), tzinfo=timezone.utc)
                range_end = datetime.combine(range_end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
                rp = price[(price.candle_time >= range_start) & (price.candle_time < range_end)].sort_values("candle_time")
                ro = oi[(oi.candle_time >= range_start - timedelta(minutes=30)) & (oi.candle_time < range_end)].sort_values("candle_time")
                result = analyze_multi_day_range(candle_dicts(rp), candle_dicts(ro), range_start, range_end, row_size=ROW_SIZE, value_area=VALUE_AREA)
                st.markdown(f"**Selected window:** {range_start_date:%d %b %Y} → {range_end_date:%d %b %Y} · {result['session_count']} AMT sessions")
                if not result["valid"]:
                    st.warning("Research result is incomplete; no composite conclusions are certified. " + result["reason"])
                else:
                    st.success(f"Data integrity passed · {result['candle_count']:,} paired confirmed 30m candles · {result['session_count']} complete sessions.")
                    st.markdown("**1 · Composite auction structure**")
                    a,b,c = st.columns(3)
                    a.metric("Composite VAL", money(result["profile"]["VAL"]))
                    b.metric("Composite POC", money(result["profile"]["POC"]))
                    c.metric("Composite VAH", money(result["profile"]["VAH"]))
                    a,b,c = st.columns(3)
                    a.metric("Price high", money(result["price_high"]))
                    b.metric("Price low", money(result["price_low"]))
                    c.metric("Last close", money(result["last_close"]))
                    st.caption(f"Composite TPOs: {result['profile']['TPOs']:,} · Occupied $50 rows: {result['profile']['Rows']:,}. Same dashboard research method; not Pine parity-certified.")
                    st.markdown("**2 · OI behaviour · non-directional context**")
                    a,b,c = st.columns(3)
                    a.metric("Opening OI reference", f"{result['opening_oi']:,.3f} BTC")
                    b.metric("Closing OI", f"{result['closing_oi']:,.3f} BTC")
                    c.metric("Net OI change", f"{result['net_oi']:+,.3f} BTC", help="Outstanding OI change; it does not identify long/short direction.")
                    a,b,c = st.columns(3)
                    a.metric("OI increase candles", str(result["oi_up_count"]))
                    b.metric("OI decrease candles", str(result["oi_down_count"]))
                    c.metric("OI change %", f"{result['net_oi_pct']:+.2f}%" if result["net_oi_pct"] is not None else "—")
                    st.caption(f"Positive OI changes: +{result['oi_positive_sum']:,.3f} BTC · Negative OI changes: {result['oi_negative_sum']:+,.3f} BTC. Descriptive only, not directional signals.")
                    st.markdown("**3 · OI changes by composite auction location**")
                    a,b,c = st.columns(3)
                    a.metric("Above composite VAH", f"{result['oi_by_value']['above']:+,.3f} BTC")
                    b.metric("Inside composite value", f"{result['oi_by_value']['inside']:+,.3f} BTC")
                    c.metric("Below composite VAL", f"{result['oi_by_value']['below']:+,.3f} BTC")
                    st.caption("Each close-to-close OI change is assigned by that candle's confirmed PRICE close relative to composite VAH/VAL. Buckets reconcile to net OI change.")
                    st.markdown("**4 · Range containment against first selected session**")
                    a,b,c = st.columns(3)
                    a.metric("First-session high", money(result["first_session_high"]))
                    b.metric("First-session low", money(result["first_session_low"]))
                    c.metric("Candles fully inside", f"{result['candles_fully_inside_first_range']}/{result['candle_count']}")
                    st.caption(f"Closes inside first-session range: {result['closes_inside_first_range']}/{result['candle_count']}. This is first-session high/low containment, not composite value containment.")
                    st.markdown("**5 · Paired 30-minute history**")
                    history = pd.DataFrame(result["history"])
                    history["candle_time_ist"] = pd.to_datetime(history["candle_time"], utc=True).dt.tz_convert(IST)
                    history["oi_change_btc"] = history["oi_change_btc"].round(6)
                    st.dataframe(history[["candle_time_ist","price_close","oi_close","oi_change_btc"]], use_container_width=True, hide_index=True)

now_utc = datetime.now(timezone.utc)
live_session_start = utc_midnight(now_utc)
available_dates = sorted({ts.date() for ts in price["candle_time"]}) if not price.empty else []
historical_dates = [d for d in available_dates if d < live_session_start.date()]
selection_labels = [LIVE_SESSION_LABEL] + [d.isoformat() for d in reversed(historical_dates)]
# Keep the selector's value stable across Streamlit reruns and 45-second refreshes.
normalize_session_selection(st.session_state, selection_labels)

selection = st.selectbox(
    "SESSION DATE",
    selection_labels,
    key="session_date_selector",
    help="Historical dates represent a completed 05:30 IST → 05:30 IST session. Live is the default."
)
is_live = selection == LIVE_SESSION_LABEL
if not is_live:
    st.button(
        "↩ Return to Live / Current Session",
        key="return_to_live_session",
        on_click=return_to_live_session,
        help="Switch back to the current 05:30 IST session and resume automatic refresh."
    )
if is_live:
    session_start = live_session_start
    st_autorefresh(interval=45_000, key="dashboard_auto_refresh")
else:
    selected_date = datetime.strptime(selection, "%Y-%m-%d").date()
    session_start = datetime.combine(selected_date, datetime.min.time(), tzinfo=timezone.utc)
    st.success(f"COMPLETED HISTORICAL SESSION · {selected_date.strftime('%d %b %Y')} · 05:30 IST → 05:30 IST")
prior_start = session_start - timedelta(days=1)
next_start = session_start + timedelta(days=1)
ist_start = session_start.astimezone(IST)

if st.button("↻ Refresh data"):
    st.cache_data.clear()
    st.rerun()

st.info("Research-derived AMT from completed Delta 30-minute candles. This is not the locked Pine v7.2.2 production calculation and must be validated against it before operational use.")

prior = price[(price.candle_time >= prior_start) & (price.candle_time < session_start)].sort_values("candle_time")
session_price = price[(price.candle_time >= session_start) & (price.candle_time < next_start)].sort_values("candle_time")
session_oi = oi[(oi.candle_time >= session_start) & (oi.candle_time < next_start)].sort_values("candle_time")
price_sequence = sequence_diagnostics(session_price, session_start)
refresh_key = f"_validation_refresh_{session_start.isoformat()}"
comparison_key = f"_validation_comparison_{session_start.isoformat()}"
current_refresh_state = {
    "loaded_at_utc": data_refresh_utc,
    "confirmed_price_count": len(session_price),
    "latest_confirmed_price_utc": session_price.iloc[-1].candle_time.isoformat() if not session_price.empty else None,
}
previous_refresh_state = st.session_state.get(refresh_key)
if previous_refresh_state is None:
    refresh_comparison = {"available": False}
    st.session_state[refresh_key] = current_refresh_state
elif previous_refresh_state.get("loaded_at_utc") != data_refresh_utc:
    refresh_comparison = {
        "available": True,
        "previous": previous_refresh_state,
        "count_changed": previous_refresh_state.get("confirmed_price_count") != current_refresh_state["confirmed_price_count"],
        "latest_changed": previous_refresh_state.get("latest_confirmed_price_utc") != current_refresh_state["latest_confirmed_price_utc"],
    }
    st.session_state[comparison_key] = refresh_comparison
    st.session_state[refresh_key] = current_refresh_state
else:
    refresh_comparison = st.session_state.get(comparison_key, {"available": False})
prior_profile = complete_profile(prior, prior_start)
session_profile = complete_profile(session_price, session_start) if not is_live else None
developing_raw = calculate_developing_profile(session_start.date(), candle_dicts(session_price)) if is_live else None
developing_profile = ({**developing_raw, "VAL": float(developing_raw["VAL"]), "POC": float(developing_raw["POC"]),
                      "VAH": float(developing_raw["VAH"]) } if developing_raw else None) if is_live else session_profile

latest_price = session_price.iloc[-1] if not session_price.empty else None
session_oi = oi[(oi.candle_time >= session_start) & (oi.candle_time < next_start)].sort_values("candle_time")
latest_oi = session_oi.iloc[-1] if not session_oi.empty else None

st.subheader("1 · PRICE ACTION & PRIOR VALUE AREA")
st.caption(f"AMT session reset: {ist_start.strftime('%d %b %Y, %H:%M')} IST / {session_start.strftime('%H:%M')} UTC")
if prior_profile:
    st.metric("Prior VAH", money(prior_profile["VAH"]))
    st.metric("Prior POC", money(prior_profile["POC"]))
    st.metric("Prior VAL", money(prior_profile["VAL"]))
    st.metric("Prior VA Width", money(prior_profile["VAH"] - prior_profile["VAL"]))
    st.caption("INPUT VALIDATION: PASS · 48/48 confirmed 30m PRICE candles, exact session timestamps and valid OHLC.")
    st.caption("PROFILE CALCULATION: COMPLETE · calculated with approved AMT Engine V1.0 rules.")
    st.caption("DAILY AMT ENGINE ACCEPTANCE: NOT VERIFIED · this dashboard does not read the daily acceptance register. NOT ACCEPTED.")
else:
    st.warning("Prior Day profile unavailable or incomplete: the previous session must contain all 48 confirmed 30m PRICE candles. Historical dates near the start of retained history may not have a preceding session.")

if not is_live:
    st.markdown("**Selected completed session profile**")
    if session_profile:
        sv1, sv2, sv3 = st.columns(3)
        sv1.metric("Session VAH", money(session_profile["VAH"]))
        sv2.metric("Session POC", money(session_profile["POC"]))
        sv3.metric("Session VAL", money(session_profile["VAL"]))
        st.caption("Calculated from all 48 confirmed 30m PRICE brackets in the selected historical session.")
    else:
        st.warning("Session profile unavailable: the selected date does not contain all 48 confirmed 30m PRICE candles.")

if latest_price is not None:
    cmp = float(latest_price.close_value)
    st.metric("Latest confirmed CMP · 30m close", money(cmp), help="Not a streaming tick. This is the close of the latest confirmed Delta REST candle.")
    st.caption(f"Latest confirmed PRICE candle: {fmt_ts(latest_price.candle_time)}")
    if prior_profile:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=[0, 1], y=[prior_profile["VAL"], prior_profile["VAH"]], mode="lines", line=dict(width=18), name="Prior Value Area"))
        fig.add_trace(go.Scatter(x=[0, 1], y=[prior_profile["POC"], prior_profile["POC"]], mode="lines", line=dict(width=3, dash="dash"), name="Prior POC"))
        fig.add_trace(go.Scatter(x=[0.5], y=[cmp], mode="markers+text", text=["CMP"], textposition="top center", marker=dict(size=13), name="Latest confirmed CMP"))
        fig.update_layout(height=420, xaxis=dict(visible=False), yaxis_title="BTC price (USD)", margin=dict(l=10,r=10,t=20,b=10), legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("No confirmed PRICE candles available.")

st.divider()
st.subheader("2 · SESSION OI ATTRIBUTION")
st.caption("PREV OI is the confirmed OI close at the previous 05:30 IST boundary. Each subsequent confirmed 30m OI close-to-close change is assigned by that candle's confirmed PRICE close against fixed Prior Day value levels.")
oi_session = session_oi
price_session = session_price
breakdown = None
if prior_profile:
    breakdown = calculate_value_area_oi_breakdown(candle_dicts(price_session), candle_dicts(oi), session_start, prior_profile["VAL"], prior_profile["VAH"], require_complete_session=not is_live)
if breakdown is None:
    st.warning("Historical OI attribution unavailable: the retained data does not include a complete Prior Day profile and/or the exact 05:30 IST boundary OI candle. Missing values are intentionally not inferred.")
    prev_col, day_col = st.columns(2)
    prev_col.metric("PREV OI", "—")
    day_col.metric("DAY OI", "—")
    st.markdown("**Vertical Value & OI Breakup Ladder**")
    with st.container(border=True):
        st.markdown("**ABOVE VALUE**")
        st.metric("Net OI above Prior VAH", "—")
        st.divider()
        st.markdown("**VALUE HIGH · Prior VAH**")
        st.metric("Prior VAH", money(prior_profile["VAH"]) if prior_profile else "—")
        st.divider()
        st.markdown("**POC + INSIDE VALUE**")
        poc_col, inside_col = st.columns(2)
        poc_col.metric("Prior POC", money(prior_profile["POC"]) if prior_profile else "—")
        inside_col.metric("Net OI inside Value", "—")
        st.divider()
        st.markdown("**VALUE LOW · Prior VAL**")
        st.metric("Prior VAL", money(prior_profile["VAL"]) if prior_profile else "—")
        st.divider()
        st.markdown("**BELOW VALUE**")
        st.metric("Net OI below Prior VAL", "—")
else:
    prev_col, day_col = st.columns(2)
    prev_col.metric("PREV OI", f"{breakdown['prev_oi']:,.3f} BTC" if breakdown["prev_oi"] is not None else "—",
                    help="Confirmed OI close of the final 30m candle ending exactly at 05:30 IST.")
    day_col.metric("DAY OI", f"{breakdown['day_oi']:+,.3f} BTC" if breakdown["day_oi"] is not None else "—",
                   help="Latest confirmed OI close minus PREV OI. Positive means net addition; negative means net deletion.")
    st.markdown("**Vertical Value & OI Breakup Ladder**")
    st.caption("Fixed reference: Prior Day VAH / POC / VAL. Both Prior VAL and Prior VAH are included inside Value.")
    with st.container(border=True):
        st.markdown("**ABOVE VALUE**")
        st.metric("Net OI added / deleted above Prior VAH", f"{breakdown['above']:+,.3f} BTC" if breakdown["above"] is not None else "—")
        st.divider()
        st.markdown("**VALUE HIGH · Prior VAH**")
        st.metric("Prior VAH", money(prior_profile["VAH"]))
        st.divider()
        st.markdown("**POC + INSIDE VALUE**")
        poc_col, inside_col = st.columns(2)
        poc_col.metric("Prior POC", money(prior_profile["POC"]))
        inside_col.metric("Net OI inside Value", f"{breakdown['inside']:+,.3f} BTC" if breakdown["inside"] is not None else "—")
        st.divider()
        st.markdown("**VALUE LOW · Prior VAL**")
        st.metric("Prior VAL", money(prior_profile["VAL"]))
        st.divider()
        st.markdown("**BELOW VALUE**")
        st.metric("Net OI added / deleted below Prior VAL", f"{breakdown['below']:+,.3f} BTC" if breakdown["below"] is not None else "—")
    if breakdown["valid"]:
        st.success(f"OI attribution reconciled: ABOVE + INSIDE + BELOW = DAY OI = {breakdown['day_oi']:+,.3f} BTC · {breakdown['candle_count']} paired confirmed 30m candles · discrepancy {breakdown['discrepancy']:+.8f} BTC.")
    else:
        st.warning("OI attribution is NOT certified as a complete session breakdown: " + breakdown["reason"])
    if latest_oi is not None:
        st.caption(f"Latest confirmed OI: {float(latest_oi.close_value):,.3f} BTC · {fmt_ts(latest_oi.candle_time)}")
    if not oi_session.empty:
        st.line_chart(oi_session.set_index("candle_time")["close_value"], height=180)

st.divider()
st.subheader("3 · " + ("DEVELOPING AMT STRUCTURE" if is_live else "COMPLETED SESSION AMT STRUCTURE"))
st.caption("INPUT VALIDATION: A developing profile is calculated only after the confirmed candles pass contiguous-prefix, timestamp and OHLC checks from the 00:00 UTC / 05:30 IST reset. Provisional candles are excluded; missing, duplicate, off-grid, invalid or interrupted sequences are withheld.")
st.caption("PROFILE CALCULATION: DEVELOPING · calculated research output using approved AMT Engine V1.0 rules; not a completed daily profile.")
st.caption("DAILY AMT ENGINE ACCEPTANCE: NOT APPLICABLE · the session is still developing. This output is NOT ACCEPTED as a daily profile.")
if developing_profile:
    a,b,c = st.columns(3)
    a.metric("Developing VAL" if is_live else "Session VAL", money(developing_profile["VAL"]))
    b.metric("Developing POC" if is_live else "Session POC", money(developing_profile["POC"]))
    c.metric("Developing VAH" if is_live else "Session VAH", money(developing_profile["VAH"]))
    st.caption(f"INPUT VALIDATION: PASS · {developing_profile.get('ConfirmedBrackets', len(session_price)):,} contiguous confirmed brackets · {developing_profile['TPOs']:,} TPOs · {developing_profile['Rows']:,} occupied $50 rows.")
    if prior_profile and is_live:
        width_delta = (developing_profile["VAH"]-developing_profile["VAL"]) - (prior_profile["VAH"]-prior_profile["VAL"])
        st.metric("VA Expansion vs Prior", money(width_delta), help="Difference in value-area width; positive means wider, negative means narrower.")
else:
    st.warning("Selected session profile unavailable because 48 confirmed 30m brackets are required.")

if is_live:
    st.divider()
    st.subheader("4 · PROVISIONAL DATA")
    prov_price = provisional_df[(provisional_df.series_type == "PRICE") & (provisional_df.symbol == "BTCUSD")] if not provisional_df.empty else pd.DataFrame()
    prov_oi = provisional_df[(provisional_df.series_type == "OI") & (provisional_df.symbol == "OI:BTCUSD")] if not provisional_df.empty else pd.DataFrame()
    with st.container(border=True):
        st.markdown("**PROVISIONAL_INCOMPLETE · excluded from AMT and confirmed OI metrics**")
        if not prov_price.empty or not prov_oi.empty:
            for label, frame in [("PRICE", prov_price), ("OI", prov_oi)]:
                if not frame.empty:
                    item = frame.iloc[0]
                    st.write(f"{label} · {item.status} · candle slot {fmt_ts(item.candle_time)}")
                    st.write(f"O {money(item.open_value)} · H {money(item.high_value)} · L {money(item.low_value)} · C {money(item.close_value)}")
        else:
            st.caption("No provisional candle currently staged.")

st.divider()
st.subheader("5 · DATA INTEGRITY")
price_times = set(price_session.candle_time.tolist()) if not price_session.empty else set()
oi_times = set(oi_session.candle_time.tolist()) if not oi_session.empty else set()
common = price_times & oi_times
price_only = price_times - oi_times
oi_only = oi_times - price_times
st.markdown("**PRICE / OI synchronization**")
m1,m2,m3 = st.columns(3)
m1.metric("Shared candle slots", f"{len(common):,}")
m2.metric("PRICE-only slots", f"{len(price_only):,}")
m3.metric("OI-only slots", f"{len(oi_only):,}")
if price_times and oi_times and not price_only and not oi_only:
    st.success("Confirmed PRICE and OI timestamps are fully aligned for the selected session.")
elif not price_times or not oi_times:
    st.warning("PRICE/OI synchronization cannot be assessed: one or both confirmed series are missing for this session.")
else:
    st.warning("PRICE/OI timestamp mismatch detected for the selected session.")

st.caption(f"Selected session: {len(price_session):,} confirmed PRICE and {len(oi_session):,} confirmed OI candles. " + ("Automatic refresh: every 45 seconds (live mode)." if is_live else "Auto-refresh paused (historical mode).") + " All times shown in IST unless explicitly marked UTC.")
st.caption("TPO method: each confirmed 30m candle contributes one count to every $50 row touched from low through high (inclusive); POC is the most-counted row (lower row wins ties); 70% value area expands to the higher-count adjacent row, with ties expanding lower. Research prototype pending Pine parity validation.")

# Build the export only after every displayed value for this run has been derived.
# It reads the same in-memory frames/profile objects used above and performs no DB query.
snapshot_now = datetime.now(timezone.utc)
snapshot_ist = snapshot_now.astimezone(IST)
prov_snapshot = provisional_df[
    (provisional_df.series_type == "PRICE") & (provisional_df.symbol == "BTCUSD")
].copy() if not provisional_df.empty else pd.DataFrame()
if not prov_snapshot.empty:
    prov_snapshot_times = pd.to_datetime(prov_snapshot["candle_time"], utc=True)
    prov_snapshot = prov_snapshot[(prov_snapshot_times >= pd.Timestamp(session_start)) & (prov_snapshot_times < pd.Timestamp(next_start))]
if not prov_snapshot.empty:
    prov_row = prov_snapshot.sort_values("candle_time", ascending=False).iloc[0]
    provisional_ts_utc = pd.Timestamp(prov_row.candle_time).isoformat()
    provisional_ts_ist = fmt_ts(prov_row.candle_time)
    provisional_status = str(prov_row.status)
else:
    provisional_ts_utc = "NONE"
    provisional_ts_ist = "NONE"
    provisional_status = "NO PROVISIONAL PRICE CANDLE"
first_price_ts = session_price.iloc[0].candle_time if not session_price.empty else None
latest_price_ts = session_price.iloc[-1].candle_time if not session_price.empty else None
latest_oi_ts = session_oi.iloc[-1].candle_time if not session_oi.empty else None
prior_session_date = prior_start.date().isoformat()
prior_input_status = "PASS · 48/48 exact confirmed candles and valid OHLC" if prior_profile else "NOT VERIFIED · prior complete profile unavailable"
prior_calculation_status = "COMPLETE · AMT Engine V1.0" if prior_profile else "NOT CALCULATED"
prior_acceptance_status = "NOT VERIFIED · dashboard does not read the daily acceptance register; NOT ACCEPTED"
developing_input_status = "PASS · contiguous confirmed prefix" if developing_profile and price_sequence["contiguous"] else "NOT VERIFIED / FAIL-CLOSED · sequence/profile unavailable"
developing_calculation_status = "CALCULATED · INTERIM RESEARCH OUTPUT" if developing_profile else "NOT CALCULATED · fail-closed"
provisional_exclusion = "YES · developing calculation receives confirmed PRICE rows only; provisional table is separate" if developing_profile else "NOT VERIFIED · developing profile unavailable"
commit_sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "NOT AVAILABLE")
deployment_id = os.environ.get("RAILWAY_DEPLOYMENT_ID", "NOT AVAILABLE")
refresh_interval = "45 seconds (live auto-refresh)" if is_live else "PAUSED (historical session)"
if refresh_comparison.get("available"):
    prev_state = refresh_comparison["previous"]
    prev_latest = prev_state.get("latest_confirmed_price_utc") or "NONE"
    count_change_text = "YES" if refresh_comparison["count_changed"] else "NO"
    latest_change_text = "YES" if refresh_comparison["latest_changed"] else "NO"
else:
    prev_latest = "NOT VERIFIED · no earlier refresh retained in this browser session"
    count_change_text = "NOT VERIFIED"
    latest_change_text = "NOT VERIFIED"
def snapshot_money(value):
    return "NOT AVAILABLE" if value is None else "$" + format(float(value), ",.2f")
snapshot_lines = [
    "BTC AMT RESEARCH DASHBOARD — VALIDATION SNAPSHOT",
    "Generated UTC: " + snapshot_now.isoformat(),
    "Generated IST: " + snapshot_ist.strftime("%Y-%m-%d %H:%M:%S %Z"),
    "",
    "A. DEPLOYMENT AND RUNTIME",
    "Dashboard: BTC AMT Research Dashboard",
    "Environment: ISOLATED STAGING",
    "Git commit SHA: " + commit_sha,
    "Deployment identifier: " + deployment_id,
    "Database runtime role: " + str(db_status.get("role", "NOT VERIFIED")),
    "default_transaction_read_only: " + str(db_status.get("default_read_only", "NOT VERIFIED")),
    "transaction_read_only: " + str(db_status.get("transaction_read_only", "NOT VERIFIED")),
    "",
    "B. SESSION AND SOURCE DATA",
    "Session date (UTC): " + session_start.date().isoformat(),
    "Reset boundary: " + session_start.strftime("%Y-%m-%d 00:00:00 UTC") + " / " + session_start.astimezone(IST).strftime("%Y-%m-%d 05:30:00 IST"),
    "Confirmed PRICE candle count: " + str(len(session_price)),
    "First confirmed PRICE candle: " + (pd.Timestamp(first_price_ts).isoformat() + " / " + fmt_ts(first_price_ts) if first_price_ts is not None else "NOT AVAILABLE"),
    "Latest confirmed PRICE candle: " + (pd.Timestamp(latest_price_ts).isoformat() + " / " + fmt_ts(latest_price_ts) if latest_price_ts is not None else "NOT AVAILABLE"),
    "Provisional PRICE candle: " + provisional_ts_utc + " / " + provisional_ts_ist,
    "Provisional PRICE status: " + provisional_status,
    "Confirmed OI candle count: " + str(len(session_oi)),
    "Latest confirmed OI candle: " + (pd.Timestamp(latest_oi_ts).isoformat() + " / " + fmt_ts(latest_oi_ts) if latest_oi_ts is not None else "NOT AVAILABLE"),
    "Missing candle count (observed prefix through latest slot): " + str(price_sequence["missing"]),
    "Duplicate candle count (extra duplicate rows): " + str(price_sequence["duplicates"]),
    "Invalid OHLC/timestamp count: " + str(price_sequence["invalid"]),
    "Off-grid candle count: " + str(price_sequence["off_grid"]),
    "Confirmed PRICE sequence contiguous: " + ("YES" if price_sequence["contiguous"] else "NO / NOT VERIFIED"),
    "",
    "C. DEVELOPING PROFILE",
    "VAL: " + (snapshot_money(developing_profile["VAL"]) if developing_profile else "NOT AVAILABLE"),
    "POC: " + (snapshot_money(developing_profile["POC"]) if developing_profile else "NOT AVAILABLE"),
    "VAH: " + (snapshot_money(developing_profile["VAH"]) if developing_profile else "NOT AVAILABLE"),
    "VA width: " + (snapshot_money(developing_profile["VAH"] - developing_profile["VAL"]) if developing_profile else "NOT AVAILABLE"),
    "Total TPO visits: " + (str(developing_profile["TPOs"]) if developing_profile else "NOT AVAILABLE"),
    "Occupied row count: " + (str(developing_profile["Rows"]) if developing_profile else "NOT AVAILABLE"),
    "Value-area TPO visits: " + (str(developing_profile.get("ValueAreaTPOs", "NOT AVAILABLE")) if developing_profile else "NOT AVAILABLE"),
    "Value-area row count (includes zero-count rows in contiguous VA): " + (str(developing_profile.get("ValueAreaRows", "NOT AVAILABLE")) if developing_profile else "NOT AVAILABLE"),
    "Profile input validation status: " + developing_input_status,
    "Profile calculation status: " + developing_calculation_status,
    "Provisional candles excluded: " + provisional_exclusion,
    "",
    "D. PRIOR COMPLETED PROFILE",
    "Prior session date: " + prior_session_date,
    "Prior VAL: " + (snapshot_money(prior_profile["VAL"]) if prior_profile else "NOT AVAILABLE"),
    "Prior POC: " + (snapshot_money(prior_profile["POC"]) if prior_profile else "NOT AVAILABLE"),
    "Prior VAH: " + (snapshot_money(prior_profile["VAH"]) if prior_profile else "NOT AVAILABLE"),
    "Prior input validation status: " + prior_input_status,
    "Prior calculation status: " + prior_calculation_status,
    "Daily AMT Engine acceptance status: " + prior_acceptance_status,
    "",
    "E. REFRESH DIAGNOSTICS",
    "Last successful data refresh timestamp (UTC): " + data_refresh_utc,
    "Current refresh interval: " + refresh_interval,
    "Latest confirmed PRICE timestamp at previous refresh (UTC): " + str(prev_latest),
    "Confirmed candle count changed since previous refresh: " + count_change_text,
    "Latest confirmed timestamp changed since previous refresh: " + latest_change_text,
    "Current provisional PRICE candle timestamp (UTC): " + provisional_ts_utc,
    "",
    "F. METHOD AND QUALIFICATIONS",
    "$50 global zero-origin row grid",
    "Inclusive OHLC TPO allocation: each confirmed 30m candle visits every row from low through high, inclusive",
    "POC tie-break: lower-priced row",
    "Value area: 70% of TPO visits; approved Option A expands one row at a time to the higher-count adjacent row, lower-priced row on tie, including zero-count rows between occupied rows",
    "Developing profile is interim research output only; NOT an accepted daily profile",
    "Dashboard calculation is not Pine v7.2.2 parity certification",
    "",
    "Evidence rule: unavailable diagnostics are labelled NOT VERIFIED; no database secrets or personal information are included."
]
validation_snapshot = "\n".join(snapshot_lines)
snapshot_json = json.dumps(validation_snapshot).replace("</", "<\\/")
copy_component = """
<div style="font-family:sans-serif;">
  <button id="copy-validation-snapshot" style="background:#2563eb;color:white;border:0;border-radius:7px;padding:11px 16px;font-weight:700;cursor:pointer;">
    COPY VALIDATION SNAPSHOT
  </button>
  <span id="copy-validation-status" role="status" aria-live="polite" style="margin-left:10px;font-size:13px;"></span>
</div>
<script>
const snapshotText = SNAPSHOT_JSON;
const button = document.getElementById("copy-validation-snapshot");
const status = document.getElementById("copy-validation-status");
button.addEventListener("click", async () => {
  status.textContent = "Copying…";
  try {
    await navigator.clipboard.writeText(snapshotText);
    status.textContent = "Copied successfully — paste into ChatGPT.";
    status.style.color = "#15803d";
  } catch (error) {
    try {
      const field = document.createElement("textarea");
      field.value = snapshotText;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      const copied = document.execCommand("copy");
      field.remove();
      if (!copied) throw new Error("Clipboard permission unavailable");
      status.textContent = "Copied successfully — paste into ChatGPT.";
      status.style.color = "#15803d";
    } catch (fallbackError) {
      status.textContent = "Copy failed. Use the plain-text snapshot below.";
      status.style.color = "#b91c1c";
    }
  }
});
</script>
""".replace("SNAPSHOT_JSON", snapshot_json)
with copy_snapshot_slot.container():
    st.components.v1.html(copy_component, height=54, scrolling=False)
with st.expander("Validation snapshot · plain text (manual copy fallback)", expanded=False):
    st.text_area("Snapshot text", value=validation_snapshot, height=420, label_visibility="collapsed")

