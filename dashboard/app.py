import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import math

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
    conn = psycopg.connect(url, autocommit=True)
    conn.execute("SET default_transaction_read_only = on")
    return conn

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
            "VAH": float(profile.vah_upper), "TPOs": profile.total_tpos, "Rows": len(rows)}

def fmt_ts(value):
    if pd.isna(value):
        return "—"
    dt = pd.Timestamp(value).to_pydatetime()
    return dt.astimezone(IST).strftime("%d %b %Y, %H:%M:%S IST")

def money(value):
    return "—" if value is None or pd.isna(value) else f"${float(value):,.2f}"

st.title("BTC AMT Research Dashboard")
st.caption("ISOLATED RESEARCH • Neon amt_research • SELECT-only database role")

@st.cache_data(ttl=45)
def load_frames():
    return fetch_data()

try:
    price_df, provisional_df = load_frames()
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
    st.caption("CALCULATED ONLY · approved AMT Engine V1.0 · 48 confirmed candles. The dashboard has not verified a daily validation/acceptance record; this is NOT an accepted prior-value reference.")
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
st.caption("RESEARCH OUTPUT ONLY · Developing levels require a contiguous confirmed 30m prefix from the 00:00 UTC / 05:30 IST reset. Provisional, missing, duplicate, off-grid or invalid candles cause the developing profile to be withheld. Completed profiles use the approved AMT Engine V1.0 core.")
if developing_profile:
    a,b,c = st.columns(3)
    a.metric("Developing VAL" if is_live else "Session VAL", money(developing_profile["VAL"]))
    b.metric("Developing POC" if is_live else "Session POC", money(developing_profile["POC"]))
    c.metric("Developing VAH" if is_live else "Session VAH", money(developing_profile["VAH"]))
    st.caption(f"Confirmed brackets: {developing_profile.get('ConfirmedBrackets', len(session_price)):,} / 48 · TPO counts: {developing_profile['TPOs']:,} · Occupied $50 rows: {developing_profile['Rows']:,} · DEVELOPING / UNVALIDATED / NOT ACCEPTED")
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
