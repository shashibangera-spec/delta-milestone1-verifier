"""Pure presentation adapter for Auction State Observer V1.

This module maps existing dashboard values only. It does not classify auctions,
create events, query data, or calculate AMT profiles.
"""

from datetime import datetime


def _value(row, key):
    if row is None:
        return None
    if hasattr(row, "get"):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return getattr(row, key, None)


def _fmt_price(value):
    if value is None:
        return "NOT AVAILABLE"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "NOT AVAILABLE"


def _profile_values(profile):
    if not profile:
        return None
    return {
        "VAL": _fmt_price(_value(profile, "VAL")),
        "POC": _fmt_price(_value(profile, "POC")),
        "VAH": _fmt_price(_value(profile, "VAH")),
    }


def _status(name, status, detail):
    return {"name": name, "status": status, "detail": detail}


def build_observer_view_model(
    *, session_start, is_live, latest_price, prior_profile,
    developing_profile, price_sequence, confirmed_price_count,
):
    """Return five fixed-priority display fields from existing in-memory outputs."""
    latest_close = _value(latest_price, "close_value")
    latest_time = _value(latest_price, "candle_time")
    prior = _profile_values(prior_profile)
    developing = _profile_values(developing_profile)

    if price_sequence and price_sequence.get("contiguous"):
        candle_status = _status(
            "Candle Continuity", "VALID",
            f"{confirmed_price_count} confirmed PRICE candle(s); contiguous from session reset.",
        )
    elif not confirmed_price_count:
        candle_status = _status(
            "Candle Continuity", "NOT VERIFIED",
            "No confirmed PRICE candles are available for this session.",
        )
    else:
        details = []
        for key, label in (("missing", "missing"), ("duplicates", "duplicate"),
                           ("invalid", "invalid"), ("off_grid", "off-grid")):
            count = (price_sequence or {}).get(key, 0)
            if count:
                details.append(f"{count} {label}")
        candle_status = _status(
            "Candle Continuity", "INSUFFICIENT EVIDENCE",
            ", ".join(details) if details else "The confirmed sequence has not passed continuity checks.",
        )

    if is_live:
        if developing_profile and price_sequence and price_sequence.get("contiguous"):
            profile_status = _status(
                "Profile Completeness", "PENDING",
                "A developing confirmed prefix is available; the 48-bracket session is not complete.",
            )
        else:
            profile_status = _status(
                "Profile Completeness", "INSUFFICIENT EVIDENCE",
                "A validated developing profile is not available.",
            )
    elif developing_profile:
        profile_status = _status(
            "Profile Completeness", "VALID",
            "The selected completed-session profile is available from the existing 48-bracket validation path.",
        )
    else:
        profile_status = _status(
            "Profile Completeness", "INSUFFICIENT EVIDENCE",
            "The selected session does not have a validated complete profile.",
        )

    return {
        "session_start": session_start,
        "session_mode": "LIVE / DEVELOPING" if is_live else "COMPLETED HISTORICAL SESSION",
        "current_auction_condition": {
            "label": "Current Auction Condition",
            "value": "NOT VERIFIED",
            "detail": "No auction-state classification output is present in the current dashboard data contract.",
        },
        "price_location": {
            "label": "Price Location",
            "current_price": _fmt_price(latest_close),
            "latest_timestamp": latest_time,
            "prior_profile": prior,
            "detail": "Raw confirmed price and prior value references only; no derived location classification.",
        },
        "value_development": {
            "label": "Value Development",
            "prior_profile": prior,
            "developing_profile": developing,
            "detail": (
                "Existing AMT Engine V1.0 profile outputs. Developing values remain interim research output."
                if is_live else
                "Existing completed-session profile output. Daily acceptance is not inferred."
            ),
        },
        "latest_confirmed_event": {
            "label": "Latest Confirmed Event",
            "value": "NO VERIFIED CONFIRMED EVENT",
            "detail": "No confirmed-auction-event record contract is available in the current dashboard integration.",
        },
        "data_quality": [
            candle_status,
            _status(
                "Source Finality", "NOT VERIFIED",
                "The dashboard separates confirmed and provisional candle tables but has no independent source-finality evidence record.",
            ),
            profile_status,
            _status(
                "Calculation Validation", "NOT VERIFIED",
                "The dashboard does not read the daily AMT acceptance register; calculation execution is not acceptance.",
            ),
        ],
    }
