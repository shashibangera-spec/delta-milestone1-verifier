import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import math

import pandas as pd
import plotly.graph_objects as go
import psycopg
import streamlit as st

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
    # Two complete AMT sessions: prior UTC day and current UTC day.
    rows = conn.execute("""
        SELECT symbol, series_type, candle_time, open_value, high_value,
               low_value, close_value, volume
        FROM research.delta_candles
        WHERE source = 'delta_india'
          AND resolution = '30m'
          AND candle_time >= (date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') - interval '1 day'
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

def fmt_ts(value):
    if pd.isna(value):
        return "—"
    dt = pd.Timestamp(value).to_pydatetime()
    return dt.astimezone(IST).strftime("%d %b %Y, %H:%M:%S IST")

def money(value):
    return "—" if value is None or pd.isna(value) else f"${float(value):,.2f}"

st.title("BTC AMT Research Dashboard")
st.caption("ISOLATED RESEARCH • Neon amt_research • SELECT-only database role")
st.info("Research-derived AMT from completed Delta 30-minute candles. This is not the locked Pine v7.2.2 production calculation and must be validated against it before operational use.")

if st.button("↻ Refresh data"):
    st.cache_data.clear()
    st.rerun()

@st.cache_data(ttl=45)
def load_frames():
    return fetch_data()

try:
    price_df, provisional_df = load_frames()
except Exception as exc:
    st.error(f"Database read failed: {exc}")
    st.stop()

now_utc = datetime.now(timezone.utc)
session_start = utc_midnight(now_utc)
prior_start = session_start - timedelta(days=1)
next_start = session_start + timedelta(days=1)
ist_start = session_start.astimezone(IST)

price = price_df[(price_df.series_type == "PRICE") & (price_df.symbol == "BTCUSD")].copy()
oi = price_df[(price_df.series_type == "OI") & (price_df.symbol == "OI:BTCUSD")].copy()
for frame in (price, oi):
    if not frame.empty:
        frame["candle_time"] = pd.to_datetime(frame["candle_time"], utc=True)

prior = price[(price.candle_time >= prior_start) & (price.candle_time < session_start)]
developing = price[(price.candle_time >= session_start) & (price.candle_time < next_start)]
prior_profile = tpo_profile(candle_dicts(prior))
developing_profile = tpo_profile(candle_dicts(developing))

latest_price = price.sort_values("candle_time").iloc[-1] if not price.empty else None
latest_oi = oi.sort_values("candle_time").iloc[-1] if not oi.empty else None

st.subheader("1 · PRICE ACTION & PRIOR VALUE AREA")
st.caption(f"AMT session reset: {ist_start.strftime('%d %b %Y, %H:%M')} IST / {session_start.strftime('%H:%M')} UTC")
if prior_profile:
    st.metric("Prior VAH", money(prior_profile["VAH"]))
    st.metric("Prior POC", money(prior_profile["POC"]))
    st.metric("Prior VAL", money(prior_profile["VAL"]))
    st.metric("Prior VA Width", money(prior_profile["VAH"] - prior_profile["VAL"]))
else:
    st.warning("Prior profile unavailable: no confirmed PRICE candles found for the previous 00:00–00:00 UTC session.")

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
st.subheader("2 · AMT STRUCTURE")
st.caption("Developing levels include confirmed 30m brackets in the current 00:00–00:00 UTC session only. The in-progress candle is excluded.")
if developing_profile:
    a,b,c = st.columns(3)
    a.metric("Developing VAL", money(developing_profile["VAL"]))
    b.metric("Developing POC", money(developing_profile["POC"]))
    c.metric("Developing VAH", money(developing_profile["VAH"]))
    st.caption(f"Confirmed brackets: {len(developing):,} / 48 • TPO counts: {developing_profile['TPOs']:,} • Occupied $50 rows: {developing_profile['Rows']:,}")
    if prior_profile:
        width_delta = (developing_profile["VAH"]-developing_profile["VAL"]) - (prior_profile["VAH"]-prior_profile["VAL"])
        st.metric("VA Expansion vs Prior", money(width_delta), help="Difference in value-area width; positive means wider, negative means narrower.")
else:
    st.warning("Developing profile not available yet for the current UTC session.")

st.divider()
st.subheader("3 · DELTA FUTURES OI & DATA INTEGRITY")
if not oi.empty:
    oi_session = oi[(oi.candle_time >= session_start) & (oi.candle_time < next_start)].sort_values("candle_time")
    latest_oi = oi.sort_values("candle_time").iloc[-1]
    st.metric("Latest confirmed OI · BTC", f"{float(latest_oi.close_value):,.3f}")
    st.caption(f"Latest confirmed OI candle: {fmt_ts(latest_oi.candle_time)}")
    if len(oi_session) >= 2:
        first_oi = float(oi_session.iloc[0].open_value)
        last_oi = float(oi_session.iloc[-1].close_value)
        delta = last_oi - first_oi
        st.metric("Current session OI change", f"{delta:+,.3f} BTC", f"{(delta/first_oi*100):+.3f}%" if first_oi else None)
    st.line_chart(oi_session.set_index("candle_time")["close_value"], height=180)
else:
    st.warning("No confirmed OI candles found.")

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

price_times = set(price.candle_time.tolist()) if not price.empty else set()
oi_times = set(oi.candle_time.tolist()) if not oi.empty else set()
common = price_times & oi_times
price_only = price_times - oi_times
oi_only = oi_times - price_times
st.markdown("**PRICE / OI synchronization**")
m1,m2,m3 = st.columns(3)
m1.metric("Shared candle slots", f"{len(common):,}")
m2.metric("PRICE-only slots", f"{len(price_only):,}")
m3.metric("OI-only slots", f"{len(oi_only):,}")
if not price_only and not oi_only:
    st.success("Confirmed PRICE and OI timestamps are fully aligned in the loaded window.")
else:
    st.warning("PRICE/OI timestamp mismatch detected in the loaded window.")

st.caption(f"Loaded {len(price):,} confirmed PRICE and {len(oi):,} confirmed OI candles. Auto-refresh cache: 45 seconds. All times shown in IST unless explicitly marked UTC.")
st.caption("TPO method: each confirmed 30m candle contributes one count to every $50 row touched from low through high (inclusive); POC is the most-counted row (lower row wins ties); 70% value area expands to the higher-count adjacent row, with ties expanding lower. Research prototype pending Pine parity validation.")
