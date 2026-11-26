from amt_engine.playbook_v13 import (
    build_signal, classify_discovery, classify_oi, evaluate_exit,
    session_end_exit,
)


def candle(open_, high, low, close):
    return {"open": open_, "high": high, "low": low, "close": close}


def test_pattern_a_long_uses_five_percent_prior_value_width_and_two_r_target():
    signal = build_signal(
        candle(105, 110, 101, 105),
        candle(105, 106, 98, 103),
        vah_upper=120, val_lower=100,
    )
    assert signal is not None
    assert (signal.pattern, signal.side) == ("A", "LONG")
    assert signal.buffer_points == 1.0
    assert signal.stop_price == 97.0
    assert signal.entry_price == 103.0
    assert signal.risk_points == 6.0
    assert signal.target_price == 115.0


def test_pattern_b_long_requires_prior_close_outside_then_wick_retest_and_reclose():
    signal = build_signal(
        candle(121, 125, 120, 123),
        candle(123, 130, 119, 124),
        vah_upper=120, val_lower=100,
    )
    assert signal is not None
    assert (signal.pattern, signal.side) == ("B", "LONG")
    assert signal.stop_price == 118.0
    assert signal.target_price == 136.0


def test_pattern_b_does_not_accept_close_back_inside_value():
    signal = build_signal(
        candle(121, 125, 120, 123),
        candle(123, 124, 118, 119.99),
        vah_upper=120, val_lower=100,
    )
    assert signal is None


def test_upper_side_priority_when_both_pattern_a_boundaries_are_wicked():
    signal = build_signal(
        candle(110, 115, 105, 110),
        candle(110, 121, 99, 110),
        vah_upper=120, val_lower=100,
    )
    assert signal is not None
    assert (signal.pattern, signal.side) == ("A", "SHORT")


def test_strict_inside_close_does_not_count_as_reclaim_at_boundary():
    signal = build_signal(
        candle(110, 115, 105, 110),
        candle(110, 115, 99, 100),
        vah_upper=120, val_lower=100,
    )
    assert signal is None


def test_discovery_is_causal_and_requires_two_consecutive_completed_closes():
    assert classify_discovery([101], 100, 90) == "DISCOVERY_CANDIDATE_ABOVE"
    assert classify_discovery([101, 102], 100, 90) == "DISCOVERY_ABOVE"
    assert classify_discovery([89], 100, 90) == "DISCOVERY_CANDIDATE_BELOW"
    assert classify_discovery([89, 88], 100, 90) == "DISCOVERY_BELOW"
    assert classify_discovery([89, 95], 100, 90) == "IN_VALUE"


def test_stop_wins_when_stop_and_target_are_both_touched():
    trade = {"side": "LONG", "stop_price": 98, "target_price": 112, "risk_points": 2}
    result = evaluate_exit(trade, candle(100, 113, 97, 105))
    assert result == {"exit_reason": "STOP_FIRST_AMBIGUOUS", "exit_price": 98.0, "realized_r": -1.0}


def test_target_exit_is_two_r():
    trade = {"side": "SHORT", "stop_price": 102, "target_price": 76, "risk_points": 13}
    result = evaluate_exit(trade, candle(100, 99, 75, 80))
    assert result == {"exit_reason": "TARGET_2R", "exit_price": 76.0, "realized_r": 2.0}


def test_session_end_exit_marks_to_market_in_r():
    trade = {"side": "LONG", "entry_price": 100, "risk_points": 5}
    result = session_end_exit(trade, candle(105, 108, 103, 107))
    assert result == {"exit_reason": "SESSION_END", "exit_price": 107.0, "realized_r": 1.4}


def test_oi_class_preserves_unknown_and_non_positive_as_flat_or_contraction():
    assert classify_oi(100, 101)["oi_class"] == "EXPANSION"
    assert classify_oi(100, 100)["oi_class"] == "CONTRACTION_OR_FLAT"
    assert classify_oi(100, 99)["oi_class"] == "CONTRACTION_OR_FLAT"
    unknown = classify_oi(None, 99)
    assert unknown["oi_class"] == "UNKNOWN"
    assert unknown["oi_unknown_reason"] == "OPENING_OI_UNAVAILABLE"
