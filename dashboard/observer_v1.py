"""Streamlit presentation components for Auction State Observer V1."""

from html import escape

import streamlit as st

from observer_v1_model import build_observer_view_model


def _profile_html(profile):
    if not profile:
        return '<div class="observer-muted">Reference profile unavailable</div>'
    return (
        '<div class="observer-levels">'
        f'<span><small>VAH</small><b>{escape(profile["VAH"])}</b></span>'
        f'<span><small>POC</small><b>{escape(profile["POC"])}</b></span>'
        f'<span><small>VAL</small><b>{escape(profile["VAL"])}</b></span>'
        '</div>'
    )


def _status_class(status):
    return {
        "VALID": "valid",
        "PENDING": "pending",
        "NOT VERIFIED": "unverified",
        "INSUFFICIENT EVIDENCE": "insufficient",
        "NOT COMPARABLE": "unverified",
    }.get(status, "unverified")


def render_observer_v1(
    *, session_start, is_live, latest_price, prior_profile,
    developing_profile, price_sequence, confirmed_price_count, latest_oi,
):
    """Render the approved five-field Observer hierarchy and secondary details."""
    view = build_observer_view_model(
        session_start=session_start,
        is_live=is_live,
        latest_price=latest_price,
        prior_profile=prior_profile,
        developing_profile=developing_profile,
        price_sequence=price_sequence,
        confirmed_price_count=confirmed_price_count,
    )

    st.markdown(
        """
        <style>
        .observer-shell{background:#0b1220;border:1px solid #26364d;border-radius:16px;padding:20px;margin:8px 0 22px;color:#edf3fb}
        .observer-kicker{color:#91a8c4;font-size:11px;letter-spacing:.13em;font-weight:700}
        .observer-heading{font-size:25px;font-weight:750;margin:4px 0 2px;color:#f4f7fb}
        .observer-meta{font-size:12px;color:#9aacc2;margin-bottom:16px}
        .observer-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
        .observer-card{background:#121e30;border:1px solid #2b405b;border-radius:12px;padding:15px;min-width:0}
        .observer-card.primary{grid-column:1/-1}
        .observer-number{color:#76a9e8;font-size:11px;font-weight:800;letter-spacing:.12em}
        .observer-label{font-size:14px;font-weight:700;color:#dce7f5;margin:4px 0 10px}
        .observer-value{font-size:21px;line-height:1.25;font-weight:800;color:#f6f8fc;overflow-wrap:anywhere}
        .observer-detail{font-size:12px;line-height:1.5;color:#a7b7ca;margin-top:8px}
        .observer-levels{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:9px}
        .observer-levels span{display:flex;flex-direction:column;gap:4px;background:#0c1727;border-radius:8px;padding:9px;min-width:0}
        .observer-levels small{color:#8ea4bf;font-size:10px;font-weight:700}
        .observer-levels b{font-size:13px;color:#edf3fb;overflow-wrap:anywhere}
        .observer-muted{color:#d5a85d;font-size:13px}
        .observer-status-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
        .observer-status{background:#0c1727;border-radius:8px;padding:9px;min-width:0}
        .observer-status-name{font-size:11px;color:#b6c5d7;font-weight:700}
        .observer-pill{display:inline-block;margin-top:5px;padding:3px 7px;border-radius:5px;font-size:10px;font-weight:800;letter-spacing:.04em}
        .observer-pill.valid{background:#153d35;color:#8ee0bd}
        .observer-pill.pending{background:#493819;color:#f2cf82}
        .observer-pill.unverified,.observer-pill.insufficient{background:#47331c;color:#f0c47b}
        .observer-status-detail{font-size:11px;line-height:1.4;color:#94a8c0;margin-top:5px}
        @media(max-width:700px){
          .observer-shell{padding:13px;border-radius:12px}
          .observer-heading{font-size:21px}
          .observer-grid{grid-template-columns:minmax(0,1fr);gap:9px}
          .observer-card.primary{grid-column:auto}
          .observer-status-grid{grid-template-columns:minmax(0,1fr)}
          .observer-value{font-size:19px}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    session_label = view["session_start"].strftime("%d %b %Y · 00:00 UTC / 05:30 IST")
    cards = []
    condition = view["current_auction_condition"]
    cards.append(
        '<section class="observer-card primary">'
        '<div class="observer-number">01</div>'
        f'<div class="observer-label">{escape(condition["label"])}</div>'
        f'<div class="observer-value">{escape(condition["value"])}</div>'
        f'<div class="observer-detail">{escape(condition["detail"])}</div>'
        '</section>'
    )

    location = view["price_location"]
    cards.append(
        '<section class="observer-card">'
        '<div class="observer-number">02</div>'
        f'<div class="observer-label">{escape(location["label"])}</div>'
        f'<div class="observer-value">{escape(location["current_price"])}</div>'
        f'<div class="observer-detail">Latest confirmed 30m close'
        + (f' · {escape(str(location["latest_timestamp"]))}' if location["latest_timestamp"] is not None else "")
        + '</div>'
        + _profile_html(location["prior_profile"])
        + f'<div class="observer-detail">{escape(location["detail"])}</div>'
        + '</section>'
    )

    development = view["value_development"]
    cards.append(
        '<section class="observer-card">'
        '<div class="observer-number">03</div>'
        f'<div class="observer-label">{escape(development["label"])}</div>'
        '<div class="observer-detail">Prior completed profile</div>'
        + _profile_html(development["prior_profile"])
        + '<div class="observer-detail">Developing / selected session profile</div>'
        + _profile_html(development["developing_profile"])
        + f'<div class="observer-detail">{escape(development["detail"])}</div>'
        + '</section>'
    )

    event = view["latest_confirmed_event"]
    cards.append(
        '<section class="observer-card primary">'
        '<div class="observer-number">04</div>'
        f'<div class="observer-label">{escape(event["label"])}</div>'
        f'<div class="observer-value">{escape(event["value"])}</div>'
        f'<div class="observer-detail">{escape(event["detail"])}</div>'
        '</section>'
    )

    status_items = []
    for item in view["data_quality"]:
        status_items.append(
            '<div class="observer-status">'
            f'<div class="observer-status-name">{escape(item["name"])}</div>'
            f'<span class="observer-pill {_status_class(item["status"])}">{escape(item["status"])}</span>'
            f'<div class="observer-status-detail">{escape(item["detail"])}</div>'
            '</div>'
        )
    cards.append(
        '<section class="observer-card primary">'
        '<div class="observer-number">05</div>'
        '<div class="observer-label">Data Quality &amp; Confirmation</div>'
        '<div class="observer-status-grid">' + ''.join(status_items) + '</div>'
        '</section>'
    )

    html = (
        '<div class="observer-shell">'
        '<div class="observer-kicker">AUCTION STATE OBSERVER V1</div>'
        '<div class="observer-heading">BTC Auction Overview</div>'
        f'<div class="observer-meta">{escape(view["session_mode"])} · {escape(session_label)}</div>'
        '<div class="observer-grid">' + ''.join(cards) + '</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)

    with st.expander("Secondary AMT Details", expanded=False):
        st.markdown("**Auction structure · existing reference data**")
        if prior_profile:
            st.write(
                f"Prior VAH: {prior_profile['VAH']:,.2f} · "
                f"POC: {prior_profile['POC']:,.2f} · "
                f"VAL: {prior_profile['VAL']:,.2f}"
            )
        else:
            st.caption("Prior profile unavailable or incomplete.")
        st.markdown("**Profile details · existing AMT Engine V1.0 outputs**")
        if developing_profile:
            st.write(
                f"VAL: {developing_profile['VAL']:,.2f} · "
                f"POC: {developing_profile['POC']:,.2f} · "
                f"VAH: {developing_profile['VAH']:,.2f}"
            )
            st.caption(
                "Developing / calculated research output; not a completed or accepted daily profile."
                if is_live else
                "Selected completed-session profile; daily acceptance remains unverified."
            )
        else:
            st.caption("Developing / selected session profile unavailable.")
        st.markdown("**OI context · non-directional and existing only**")
        if latest_oi is not None:
            st.write(f"Latest confirmed OI close: {float(latest_oi.close_value):,.3f} BTC")
        else:
            st.caption("Latest confirmed OI close unavailable.")
        st.markdown("**Event and provenance**")
        st.write("NO VERIFIED CONFIRMED EVENT")
        st.caption("No event record source is connected to this dashboard.")
