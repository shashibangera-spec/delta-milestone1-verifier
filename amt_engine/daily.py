"""Deterministic daily AMT profile calculation; no database or OI dependency."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_CEILING
import hashlib
import json
import math
from typing import Iterable

METHOD_VERSION = "AMT_ENGINE_V1.0"
BAR_SECONDS = 1800
EXPECTED_BARS = 48
ROW_SIZE = Decimal("50")
VALUE_AREA_FRACTION = Decimal("0.70")
SOURCE = "delta_india"
SYMBOL = "BTCUSD"
RESOLUTION = "30m"


@dataclass(frozen=True)
class Candle:
    candle_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class TpoRow:
    row_lower: Decimal
    row_upper: Decimal
    tpo_count: int
    is_poc: bool
    is_value_area: bool


@dataclass(frozen=True)
class Profile:
    session_date: date
    expected_bars: int
    observed_bars: int
    is_complete: bool
    missing_candle_count: int
    first_candle: datetime
    last_candle: datetime
    total_tpos: int
    poc_lower: Decimal
    poc_upper: Decimal
    poc_tpo_count: int
    vah_lower: Decimal
    vah_upper: Decimal
    val_lower: Decimal
    val_upper: Decimal
    value_area_tpos: int
    session_open: Decimal
    session_high: Decimal
    session_low: Decimal
    session_close: Decimal


@dataclass(frozen=True)
class Validation:
    valid: bool
    report: dict
    candles: tuple[Candle, ...]
    input_fingerprint: str | None


def session_bounds(session_date: date) -> tuple[datetime, datetime]:
    """UTC 00:00 through next UTC 00:00; equals 05:30 IST session reset."""
    start = datetime.combine(session_date, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _decimal(value, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} is not numeric")
    if not result.is_finite():
        raise ValueError(f"{field} is not finite")
    return result


def _normalize_timestamp(value) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("candle_time must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical_decimal(value: Decimal) -> str:
    """Stable fixed-point representation: 1.0, 1.00 and 1 normalize identically."""
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _canonical_fingerprint(candles: Iterable[Candle]) -> str:
    payload = {
        "format": "amt-price-ohlc-v1",
        "method_version": METHOD_VERSION,
        "source": SOURCE,
        "symbol": SYMBOL,
        "resolution": RESOLUTION,
        "series_type": "PRICE",
        "rows": [
            [c.candle_time.isoformat(), _canonical_decimal(c.open), _canonical_decimal(c.high),
             _canonical_decimal(c.low), _canonical_decimal(c.close)]
            for c in sorted(candles, key=lambda x: x.candle_time)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_session(session_date: date, raw_rows: Iterable[dict], provisional_times: Iterable[datetime] = ()) -> Validation:
    """Fail closed unless all 48 exact UTC slots are unique, valid and confirmed."""
    start, end = session_bounds(session_date)
    expected = [start + timedelta(seconds=BAR_SECONDS * i) for i in range(EXPECTED_BARS)]
    buckets: dict[datetime, list[dict]] = {}
    malformed_rows = 0
    off_grid_rows = 0
    for row in raw_rows:
        try:
            ts = _normalize_timestamp(row["candle_time"])
        except Exception:
            malformed_rows += 1
            continue
        if ts < start or ts >= end:
            continue
        if ts.second or ts.microsecond or int(ts.timestamp()) % BAR_SECONDS:
            off_grid_rows += 1
        buckets.setdefault(ts, []).append(row)

    duplicates = sorted(ts for ts, rows in buckets.items() if len(rows) > 1)
    observed_timestamps = set(buckets)
    missing = [ts for ts in expected if ts not in observed_timestamps]
    provisional_set = set()
    for value in provisional_times:
        try:
            ts = _normalize_timestamp(value)
            if start <= ts < end:
                provisional_set.add(ts)
        except Exception:
            malformed_rows += 1

    candles: list[Candle] = []
    invalid_ohlc = []
    for ts in expected:
        rows = buckets.get(ts, [])
        if len(rows) != 1:
            continue
        row = rows[0]
        try:
            o = _decimal(row.get("open_value", row.get("open")), "open")
            h = _decimal(row.get("high_value", row.get("high")), "high")
            l = _decimal(row.get("low_value", row.get("low")), "low")
            c = _decimal(row.get("close_value", row.get("close")), "close")
            if h < l or h < max(o, c) or l > min(o, c):
                raise ValueError("OHLC ordering invalid")
            candles.append(Candle(ts, o, h, l, c))
        except Exception as exc:
            invalid_ohlc.append({"timestamp": ts.isoformat(), "reason": str(exc)})

    provisional = sorted(provisional_set)
    valid = (len(missing) == 0 and len(duplicates) == 0 and off_grid_rows == 0
             and malformed_rows == 0 and len(invalid_ohlc) == 0 and len(provisional) == 0
             and len(candles) == EXPECTED_BARS)
    fingerprint = _canonical_fingerprint(candles) if valid else None
    report = {
        "session_start_utc": start.isoformat(), "session_end_utc_exclusive": end.isoformat(),
        "expected_candles": EXPECTED_BARS, "observed_distinct_timestamps": len(observed_timestamps),
        "valid_observed_candles": len(candles), "missing_timestamps": [x.isoformat() for x in missing],
        "duplicate_timestamps": [x.isoformat() for x in duplicates], "off_grid_rows": off_grid_rows,
        "malformed_rows": malformed_rows, "invalid_ohlc": invalid_ohlc,
        "provisional_timestamps": [x.isoformat() for x in provisional], "valid": valid,
    }
    return Validation(valid, report, tuple(candles), fingerprint)


def _bucket(price: Decimal) -> int:
    return int((price / ROW_SIZE).to_integral_value(rounding=ROUND_FLOOR))


def _calculate_poc_and_value_area(counts: dict[int, int]) -> tuple[int, int, int, int, int]:
    """Shared V1.0 POC and Option A value-area expansion for complete and developing profiles."""
    if not counts:
        raise ValueError("no TPO rows generated")
    min_bucket, max_bucket = min(counts), max(counts)
    poc_bucket = min(counts, key=lambda b: (-counts[b], b))
    total_tpos = sum(counts.values())
    target = int((Decimal(total_tpos) * VALUE_AREA_FRACTION).to_integral_value(rounding=ROUND_CEILING))
    low_edge = high_edge = poc_bucket
    value_count = counts[poc_bucket]
    while value_count < target:
        candidates = []
        if low_edge > min_bucket:
            candidates.append((counts.get(low_edge - 1, 0), low_edge - 1))
        if high_edge < max_bucket:
            candidates.append((counts.get(high_edge + 1, 0), high_edge + 1))
        if not candidates:
            break
        chosen_count, chosen_bucket = min(candidates, key=lambda item: (-item[0], item[1]))
        value_count += chosen_count
        if chosen_bucket < low_edge:
            low_edge = chosen_bucket
        else:
            high_edge = chosen_bucket
    return poc_bucket, low_edge, high_edge, total_tpos, value_count


def calculate_profile(session_date: date, candles: Iterable[Candle]) -> tuple[Profile, tuple[TpoRow, ...]]:
    """Calculate 30m TPO visits on a zero-origin $50 grid using Option A VA expansion."""
    bars = tuple(sorted(candles, key=lambda c: c.candle_time))
    if len(bars) != EXPECTED_BARS:
        raise ValueError("calculate_profile requires exactly 48 validated candles")
    start, end = session_bounds(session_date)
    expected_times = [start + timedelta(seconds=BAR_SECONDS * i) for i in range(EXPECTED_BARS)]
    if [c.candle_time for c in bars] != expected_times:
        raise ValueError("candles must match all 48 exact session timestamps")
    for candle in bars:
        values = (candle.open, candle.high, candle.low, candle.close)
        if any(not isinstance(v, Decimal) or not v.is_finite() for v in values):
            raise ValueError("all OHLC values must be finite Decimal values")
        if candle.high < candle.low or candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
            raise ValueError("OHLC ordering invalid")

    counts: dict[int, int] = {}
    for candle in bars:
        low_bucket, high_bucket = _bucket(candle.low), _bucket(candle.high)
        for bucket in range(low_bucket, high_bucket + 1):
            counts[bucket] = counts.get(bucket, 0) + 1
    if not counts:
        raise ValueError("no TPO rows generated")

    poc_bucket, low_edge, high_edge, total_tpos, value_count = _calculate_poc_and_value_area(counts)

    rows = tuple(
        TpoRow(Decimal(bucket) * ROW_SIZE, Decimal(bucket + 1) * ROW_SIZE,
               counts.get(bucket, 0), bucket == poc_bucket, bucket in selected)
        for bucket in range(min_bucket, max_bucket + 1)
    )
    profile = Profile(
        session_date=session_date, expected_bars=EXPECTED_BARS, observed_bars=len(bars),
        is_complete=True, missing_candle_count=0, first_candle=bars[0].candle_time,
        last_candle=bars[-1].candle_time, total_tpos=total_tpos,
        poc_lower=Decimal(poc_bucket) * ROW_SIZE, poc_upper=Decimal(poc_bucket + 1) * ROW_SIZE,
        poc_tpo_count=counts[poc_bucket], vah_lower=Decimal(high_edge) * ROW_SIZE,
        vah_upper=Decimal(high_edge + 1) * ROW_SIZE, val_lower=Decimal(low_edge) * ROW_SIZE,
        val_upper=Decimal(low_edge + 1) * ROW_SIZE, value_area_tpos=value_count,
        session_open=bars[0].open, session_high=max(c.high for c in bars),
        session_low=min(c.low for c in bars), session_close=bars[-1].close,
    )
    return profile, rows


def assign_revision_attempt(latest_success: dict | None, prior_attempts: list[dict], fingerprint: str | None) -> tuple[int, int]:
    """Retry attempts stay within a revision; only changed inputs after success advance revision."""
    if latest_success is None:
        revision = max((int(x["revision_number"]) for x in prior_attempts), default=1)
    elif fingerprint is None or fingerprint == latest_success.get("input_fingerprint"):
        revision = int(latest_success["revision_number"])
    else:
        revision = int(latest_success["revision_number"]) + 1
    attempt = max((int(x["attempt_number"]) for x in prior_attempts
                   if int(x["revision_number"]) == revision), default=0) + 1
    return revision, attempt
