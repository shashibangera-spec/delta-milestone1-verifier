"""Deterministic BTC Playbook v1.3 shadow rules. Research-only; never routes orders."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import math
from typing import Any, Iterable


@dataclass(frozen=True)
class Signal:
    pattern: str
    side: str
    entry_price: float
    stop_price: float
    target_price: float
    risk_points: float
    buffer_points: float
    prior_vah_upper: float
    prior_val_lower: float


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def classify_discovery(closes: Iterable[float], vah_upper: float, val_lower: float) -> str:
    """Replay causal Discovery from completed closes for the current session.

    Discovery begins on the first strict close outside prior value. It ends
    after two consecutive strict closes inside value or immediately when the
    opposite value boundary is breached by a close. Boundary-equal closes are
    neither outside nor inside and reset an inside streak without ending the
    active Discovery state.
    """
    values = [_num(x) for x in closes]
    values = [x for x in values if x is not None]
    if not values or vah_upper <= val_lower:
        return "UNKNOWN"

    state = "IN_VALUE"
    inside_streak = 0
    for close in values:
        if state == "IN_VALUE":
            if close > vah_upper:
                state, inside_streak = "DISCOVERY_ABOVE", 0
            elif close < val_lower:
                state, inside_streak = "DISCOVERY_BELOW", 0
        elif state == "DISCOVERY_ABOVE":
            if close < val_lower:
                state, inside_streak = "DISCOVERY_BELOW", 0
            elif val_lower < close < vah_upper:
                inside_streak += 1
                if inside_streak >= 2:
                    state, inside_streak = "IN_VALUE", 0
            else:
                inside_streak = 0
        elif state == "DISCOVERY_BELOW":
            if close > vah_upper:
                state, inside_streak = "DISCOVERY_ABOVE", 0
            elif val_lower < close < vah_upper:
                inside_streak += 1
                if inside_streak >= 2:
                    state, inside_streak = "IN_VALUE", 0
            else:
                inside_streak = 0
    return state


def build_signal(previous: dict, current: dict, vah_upper: float, val_lower: float) -> Signal | None:
    """Evaluate only a completed current candle; entry is its close.

    Pattern A: previous close was inside prior value; current wick tests a
    boundary and current close reclaims back inside value.
    Pattern B: previous close was strictly outside value; current wick retests
    that boundary and current close remains strictly outside.
    If both boundaries are wicked in one candle, upper-side (SHORT) wins.
    """
    vals = [_num(previous.get("close")), _num(current.get("open")),
            _num(current.get("high")), _num(current.get("low")),
            _num(current.get("close"))]
    prev_close, _, high, low, close = vals
    if any(x is None for x in vals):
        return None
    width = vah_upper - val_lower
    if width <= 0:
        return None
    buffer_points = 0.05 * width
    inside_before = val_lower < prev_close < vah_upper

    # Upper-side priority is deliberate and deterministic.
    if inside_before and high >= vah_upper and val_lower < close < vah_upper:
        stop = high + buffer_points
        risk = stop - close
        if risk > 0:
            return Signal("A", "SHORT", close, stop, close - 2.0 * risk,
                          risk, buffer_points, vah_upper, val_lower)
    if inside_before and low <= val_lower and val_lower < close < vah_upper:
        stop = low - buffer_points
        risk = close - stop
        if risk > 0:
            return Signal("A", "LONG", close, stop, close + 2.0 * risk,
                          risk, buffer_points, vah_upper, val_lower)

    if prev_close > vah_upper and low <= vah_upper and close > vah_upper:
        stop = low - buffer_points
        risk = close - stop
        if risk > 0:
            return Signal("B", "LONG", close, stop, close + 2.0 * risk,
                          risk, buffer_points, vah_upper, val_lower)
    if prev_close < val_lower and high >= val_lower and close < val_lower:
        stop = high + buffer_points
        risk = stop - close
        if risk > 0:
            return Signal("B", "SHORT", close, stop, close - 2.0 * risk,
                          risk, buffer_points, vah_upper, val_lower)
    return None


def evaluate_exit(trade: dict, candle: dict) -> dict | None:
    """Evaluate from the candle after entry. Stop wins if stop and target both touch."""
    high, low, close = (_num(candle.get(k)) for k in ("high", "low", "close"))
    if high is None or low is None or close is None:
        return None
    side = trade["side"]
    stop = float(trade["stop_price"])
    target = float(trade["target_price"])
    if side == "LONG":
        stop_hit, target_hit = low <= stop, high >= target
    else:
        stop_hit, target_hit = high >= stop, low <= target
    if stop_hit:
        return {"exit_reason": "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP",
                "exit_price": stop, "realized_r": -1.0}
    if target_hit:
        return {"exit_reason": "TARGET_2R", "exit_price": target, "realized_r": 2.0}
    return None
