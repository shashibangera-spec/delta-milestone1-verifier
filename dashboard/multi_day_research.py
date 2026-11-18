"""Read-only multi-session BTC auction/OI research calculations."""
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import math

UTC = timezone.utc
BAR = timedelta(minutes=30)


def _utc(value):
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("candle_time must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _profile(candles, row_size, value_area):
    counts = defaultdict(int)
    for c in candles:
        lo = math.floor(float(c["low_value"]) / row_size)
        hi = math.floor(float(c["high_value"]) / row_size)
        for bucket in range(lo, hi + 1):
            counts[bucket] += 1
    if not counts:
        return None
    maximum = max(counts.values())
    poc = min(k for k, v in counts.items() if v == maximum)
    target = math.ceil(sum(counts.values()) * value_area)
    low = high = poc
    included = counts[poc]
    while included < target:
        lower, upper = counts.get(low-1, 0), counts.get(high+1, 0)
        if lower == 0 and upper == 0:
            break
        if lower >= upper:
            low -= 1
            included += lower
        else:
            high += 1
            included += upper
    return {"VAL": low*row_size, "POC": poc*row_size,
            "VAH": (high+1)*row_size, "TPOs": sum(counts.values()),
            "Rows": len(counts)}


def analyze_multi_day_range(price_candles, oi_candles, start, end_exclusive,
                            row_size=50.0, value_area=0.70):
    """Analyze whole sessions in [start, end_exclusive), UTC midnight boundaries."""
    start, end_exclusive = _utc(start), _utc(end_exclusive)
    if start.time().replace(tzinfo=None) != datetime.min.time():
        raise ValueError("start must be UTC midnight (05:30 IST reset)")
    if end_exclusive.time().replace(tzinfo=None) != datetime.min.time():
        raise ValueError("end_exclusive must be UTC midnight")
    if end_exclusive <= start:
        raise ValueError("end_exclusive must be after start")
    if row_size <= 0 or not 0 < value_area <= 1:
        raise ValueError("invalid TPO parameters")
    expected, t = [], start
    while t < end_exclusive:
        expected.append(t)
        t += BAR
    days = (end_exclusive-start).days
    boundary_time = start-BAR
    prices = {_utc(c["candle_time"]): c for c in price_candles}
    oi = {_utc(c["candle_time"]): c for c in oi_candles}
    p = {t: prices[t] for t in expected if t in prices}
    o = {t: oi[t] for t in expected if t in oi}
    problems = []
    if boundary_time not in oi:
        problems.append("Missing confirmed OI boundary candle immediately before selected start.")
    if len(p) != len(expected):
        problems.append(f"PRICE coverage {len(p)}/{len(expected)} expected candles.")
    if len(o) != len(expected):
        problems.append(f"OI coverage {len(o)}/{len(expected)} expected candles.")
    if set(p) != set(o):
        problems.append("Confirmed PRICE and OI timestamps do not match.")
    if len(expected) != days*48:
        problems.append("Selected range must contain whole UTC-day AMT sessions.")
    if problems:
        return {"valid": False, "reason": " ".join(problems),
                "session_count": days, "candle_count": len(set(p)&set(o))}
    pc, oc = [p[t] for t in expected], [o[t] for t in expected]
    profile = _profile(pc, row_size, value_area)
    if profile is None:
        return {"valid": False, "reason": "Composite TPO profile is empty.",
                "session_count": days, "candle_count": len(expected)}
    opening = float(oi[boundary_time]["close_value"])
    previous = opening
    positive = negative = above = inside = below = 0.0
    up = down = 0
    history = []
    for ts, price, oi_candle in zip(expected, pc, oc):
        oi_close = float(oi_candle["close_value"])
        delta = oi_close-previous
        if delta > 0:
            positive += delta
            up += 1
        elif delta < 0:
            negative += delta
            down += 1
        close = float(price["close_value"])
        if close > profile["VAH"]:
            above += delta
        elif close < profile["VAL"]:
            below += delta
        else:
            inside += delta
        history.append({"candle_time": ts.isoformat(), "price_close": close,
                        "oi_close": oi_close, "oi_change_btc": delta})
        previous = oi_close
    first = pc[:48]
    first_high = max(float(c["high_value"]) for c in first)
    first_low = min(float(c["low_value"]) for c in first)
    fully_inside = sum(float(c["low_value"]) >= first_low and float(c["high_value"]) <= first_high for c in pc)
    closes_inside = sum(first_low <= float(c["close_value"]) <= first_high for c in pc)
    closing = float(oc[-1]["close_value"])
    net = closing-opening
    if abs(above+inside+below-net) > 1e-8:
        return {"valid": False, "reason": "OI location attribution failed reconciliation.",
                "session_count": days, "candle_count": len(expected)}
    return {
        "valid": True, "reason": "All selected sessions are complete and PRICE/OI paired.",
        "session_count": days, "candle_count": len(expected), "profile": profile,
        "price_high": max(float(c["high_value"]) for c in pc),
        "price_low": min(float(c["low_value"]) for c in pc),
        "last_close": float(pc[-1]["close_value"]),
        "opening_oi": opening, "closing_oi": closing, "net_oi": net,
        "net_oi_pct": net/opening*100 if opening else None,
        "oi_positive_sum": positive, "oi_negative_sum": negative,
        "oi_up_count": up, "oi_down_count": down,
        "oi_by_value": {"above": above, "inside": inside, "below": below},
        "first_session_high": first_high, "first_session_low": first_low,
        "candles_fully_inside_first_range": fully_inside,
        "closes_inside_first_range": closes_inside, "history": history,
    }
