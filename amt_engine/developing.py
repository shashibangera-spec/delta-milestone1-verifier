"""Fail-closed developing TPO profile using the approved V1.0 grid and Decimal rules."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from .daily import BAR_SECONDS, EXPECTED_BARS, ROW_SIZE, VALUE_AREA_FRACTION, session_bounds, _bucket


def calculate_developing_profile(session_date, raw_rows):
    """Return a developing profile only for a contiguous confirmed prefix from reset.

    raw_rows must come from the confirmed-candles table. This function independently
    checks sequence integrity and OHLC validity; provisional rows are never accepted.
    """
    rows = list(raw_rows)
    if not rows or len(rows) > EXPECTED_BARS:
        return None
    start, _ = session_bounds(session_date)
    candles = []
    seen = set()
    for index, row in enumerate(rows):
        try:
            ts = row["candle_time"]
            if not hasattr(ts, "tzinfo") or ts.tzinfo is None:
                return None
            ts = ts.astimezone(start.tzinfo)
            expected = start + timedelta(seconds=BAR_SECONDS * index)
            if ts != expected or ts in seen:
                return None
            seen.add(ts)
            values = []
            for field, alias in (("open_value", "open"), ("high_value", "high"),
                                 ("low_value", "low"), ("close_value", "close")):
                value = row.get(field, row.get(alias))
                number = Decimal(str(value))
                if not number.is_finite():
                    return None
                values.append(number)
            o, h, l, c = values
            if h < l or h < max(o, c) or l > min(o, c):
                return None
            candles.append((o, h, l, c))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return None

    counts = {}
    for _, high, low, _ in candles:
        lo_bucket, hi_bucket = _bucket(low), _bucket(high)
        for bucket in range(lo_bucket, hi_bucket + 1):
            counts[bucket] = counts.get(bucket, 0) + 1
    if not counts:
        return None

    poc_bucket = min(counts, key=lambda bucket: (-counts[bucket], bucket))
    total_tpos = sum(counts.values())
    target = int((Decimal(total_tpos) * VALUE_AREA_FRACTION).to_integral_value(rounding=ROUND_CEILING))
    low_edge = high_edge = poc_bucket
    included = counts[poc_bucket]
    min_bucket, max_bucket = min(counts), max(counts)
    while included < target:
        candidates = []
        if low_edge > min_bucket:
            candidates.append((counts.get(low_edge - 1, 0), low_edge - 1))
        if high_edge < max_bucket:
            candidates.append((counts.get(high_edge + 1, 0), high_edge + 1))
        if not candidates:
            break
        chosen_count, chosen_bucket = min(candidates, key=lambda item: (-item[0], item[1]))
        included += chosen_count
        if chosen_bucket < low_edge:
            low_edge = chosen_bucket
        else:
            high_edge = chosen_bucket

    return {
        "VAL": Decimal(low_edge) * ROW_SIZE,
        "POC": Decimal(poc_bucket) * ROW_SIZE,
        "VAH": Decimal(high_edge + 1) * ROW_SIZE,
        "TPOs": total_tpos,
        "Rows": len(counts),
        "ConfirmedBrackets": len(candles),
        "ProfileStatus": "DEVELOPING · RESEARCH OUTPUT · UNVALIDATED",
    }
