from datetime import datetime, timedelta, timezone

UTC = timezone.utc
BAR = timedelta(minutes=30)


def _utc(value):
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("candle_time must be a timezone-aware datetime")
    return value.astimezone(UTC)


def calculate_value_area_oi_breakdown(price_candles, oi_candles, session_start, prior_val, prior_vah):
    """Attribute each confirmed 30m OI close-to-close delta by that bar's confirmed PRICE close."""
    start = _utc(session_start)
    boundary_time = start - BAR
    prices = {_utc(c["candle_time"]): c for c in price_candles}
    oi = {_utc(c["candle_time"]): c for c in oi_candles}
    boundary = oi.get(boundary_time)
    if boundary is None:
        return {"valid": False, "reason": "Missing confirmed OI boundary candle ending at 05:30 IST.",
                "prev_oi": None, "day_oi": None, "above": None, "inside": None, "below": None,
                "latest_oi": None, "candle_count": 0, "discrepancy": None}
    prev_oi = float(boundary["close_value"])
    current_oi = {t: c for t, c in oi.items() if start <= t < start + timedelta(days=1)}
    current_prices = {t: c for t, c in prices.items() if start <= t < start + timedelta(days=1)}
    if not current_oi:
        return {"valid": False, "reason": "No confirmed OI candles in the current session yet.",
                "prev_oi": prev_oi, "day_oi": 0.0, "above": 0.0, "inside": 0.0, "below": 0.0,
                "latest_oi": prev_oi, "candle_count": 0, "discrepancy": 0.0}
    latest_time = max(current_oi)
    latest_oi = float(current_oi[latest_time]["close_value"])
    day_oi = latest_oi - prev_oi
    common_times = sorted(set(current_oi) & set(current_prices))
    timestamps_match = set(current_oi) == set(current_prices)
    expected, t = [], start
    while t <= latest_time:
        expected.append(t)
        t += BAR
    contiguous = sorted(current_oi) == expected
    complete_pairs = (timestamps_match and contiguous and bool(common_times)
                      and common_times[0] == start and common_times[-1] == latest_time)
    if not complete_pairs:
        reasons = []
        if not timestamps_match:
            reasons.append("PRICE/OI confirmed candle timestamps differ.")
        if not contiguous:
            reasons.append("A confirmed 30m slot is missing between the reset and latest OI candle.")
        if not common_times:
            reasons.append("No paired confirmed PRICE/OI candles are available.")
        return {"valid": False, "reason": " ".join(reasons),
                "prev_oi": prev_oi, "day_oi": day_oi, "above": None, "inside": None, "below": None,
                "latest_oi": latest_oi, "candle_count": len(common_times), "discrepancy": None}

    above = inside = below = 0.0
    previous_close = prev_oi
    for timestamp in common_times:
        current_close = float(current_oi[timestamp]["close_value"])
        delta = current_close - previous_close
        price_close = float(current_prices[timestamp]["close_value"])
        if price_close > float(prior_vah):
            above += delta
        elif price_close < float(prior_val):
            below += delta
        else:
            inside += delta
        previous_close = current_close
    discrepancy = above + inside + below - day_oi
    valid = abs(discrepancy) <= 1e-8
    reason = "All confirmed 30m candles reconcile exactly." if valid else "OI zone buckets do not reconcile to DAY OI."
    return {"valid": bool(valid), "reason": reason,
            "prev_oi": prev_oi, "day_oi": day_oi, "above": above, "inside": inside, "below": below,
            "latest_oi": latest_oi, "candle_count": len(common_times), "discrepancy": discrepancy}
