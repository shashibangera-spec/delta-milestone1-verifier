"""Pure AMT auction-context calculations for the read-only dashboard."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _range(rows):
    if not rows:
        return None
    highs = [float(r["high_value"]) for r in rows if r.get("high_value") is not None]
    lows = [float(r["low_value"]) for r in rows if r.get("low_value") is not None]
    closes = [float(r["close_value"]) for r in rows if r.get("close_value") is not None]
    if not highs or not lows or not closes:
        return None
    return {"high": max(highs), "low": min(lows), "close": closes[-1]}


def _midpoint(profile):
    return (float(profile["vah_upper"]) + float(profile["val_lower"])) / 2.0


def _direction(values):
    if all(b > a for a, b in zip(values, values[1:])):
        return "UP"
    if all(b < a for a, b in zip(values, values[1:])):
        return "DOWN"
    return "MIXED"


def build_prior_auction_context(completed_profiles, completed_candles, developing_candles):
    """Build descriptive completed-auction and UTC sub-session context.

    Profiles/candles are ordered oldest first. All candles are completed 30m bars.
    """
    profiles = sorted(completed_profiles, key=lambda p: p["session_date"])
    sessions = sorted(completed_candles, key=lambda x: x["session_date"])
    if len(profiles) < 2 or len(sessions) < 2:
        prior = None
        migration = "Unavailable"
        swing = "Unavailable"
    else:
        old, new = profiles[-2], profiles[-1]
        metrics = ("poc_lower", "vah_upper", "val_lower")
        vals = [[float(p[k]) for p in profiles[-2:]] for k in metrics]
        vals.append([_midpoint(p) for p in profiles[-2:]])
        dirs = [_direction(v) for v in vals]
        migration = "Migrating Up" if all(x == "UP" for x in dirs) else (
            "Migrating Down" if all(x == "DOWN" for x in dirs) else "Overlapping or Mixed"
        )
        current_range, previous_range = sessions[-1]["range"], sessions[-2]["range"]
        if current_range and previous_range:
            hh = current_range["high"] > previous_range["high"]
            hl = current_range["low"] > previous_range["low"]
            lh = current_range["high"] < previous_range["high"]
            ll = current_range["low"] < previous_range["low"]
            swing = "HH/HL" if hh and hl else ("LL/LH" if ll and lh else "Mixed")
        else:
            swing = "Unavailable"
        prior = {"session_date": str(new["session_date"]), "profile": new}

    close_location = "Unavailable"
    if prior:
        close = sessions[-1]["range"]["close"] if sessions[-1]["range"] else None
        if close is not None:
            p = prior["profile"]
            close_location = "Above Value" if close > float(p["vah_upper"]) else (
                "Below Value" if close < float(p["val_lower"]) else "Within Value"
            )

    subsessions = []
    definitions = [
        ("Asia", time(0, 0), time(8, 0)),
        ("Europe", time(8, 0), time(13, 30)),
        ("US", time(13, 30), time(23, 59, 59, 999999)),
    ]
    prior_high = sessions[-1]["range"]["high"] if sessions and sessions[-1]["range"] else None
    prior_low = sessions[-1]["range"]["low"] if sessions and sessions[-1]["range"] else None
    rows = sorted(developing_candles, key=lambda r: r["candle_time"])

    # Live, descriptive comparison: completed current-session 30m range vs latest
    # completed auction range. No projection or inference is performed.
    live_highs = [float(r["high_value"]) for r in rows if r.get("high_value") is not None]
    live_lows = [float(r["low_value"]) for r in rows if r.get("low_value") is not None]
    live_swing = {"label": "Unavailable", "current_range": None, "prior_range": None,
                  "completed_candles": len(rows)}
    if live_highs and live_lows and prior_high is not None and prior_low is not None:
        current_high, current_low = max(live_highs), min(live_lows)
        hh, hl = current_high > prior_high, current_low > prior_low
        ll, lh = current_low < prior_low, current_high < prior_high
        if hh and ll:
            label = "HH / LL (Outside)"
        elif hh and hl:
            label = "HH / HL"
        elif ll and lh:
            label = "LL / LH"
        elif current_high <= prior_high and current_low >= prior_low:
            label = "LH / HL (Inside)"
        else:
            label = "Mixed"
        live_swing = {
            "label": label,
            "current_range": {"low": current_low, "high": current_high},
            "prior_range": {"low": prior_low, "high": prior_high},
            "completed_candles": len(rows),
        }
    for name, start, end in definitions:
        selected = [r for r in rows if start <= _utc(r["candle_time"]).time().replace(tzinfo=None) < end]
        value = _range(selected)
        if value is None:
            extension = "Not started"
        elif prior_high is not None and value["high"] > prior_high and value["low"] < prior_low:
            extension = "Both-side extension"
        elif prior_high is not None and value["high"] > prior_high:
            extension = "Above prior range"
        elif prior_low is not None and value["low"] < prior_low:
            extension = "Below prior range"
        else:
            extension = "Within prior range"
        subsessions.append({"name": name, "range": value, "development": extension})
    return {
        "session_date": str(prior["session_date"]) if prior else None,
        "close_location": close_location,
        "value_migration": migration,
        "swing_structure": swing,
        "live_intraday_swing": live_swing,
        "subsessions": subsessions,
        "informational_only": True,
    }
