from datetime import date, datetime, timezone

import pytest

from browser_dashboard.auction_context import (
    build_prior_structure_status,
    classify_live_range,
)


@pytest.mark.parametrize(("high", "low", "expected"), [
    (121, 96, "HH / HL"),
    (119, 84, "LL / LH"),
    (121, 84, "HH / LL (Outside)"),
    (120, 95, "LH / HL (Inside)"),
    (120, 94, "Mixed"),
])
def test_live_range_classification(high, low, expected):
    assert classify_live_range(high, low, 120, 95) == expected


def test_prior_hh_hl_breaks_only_on_a_low_breach():
    status = build_prior_structure_status("HH/HL", 119, 94, 120, 95, 122, 92)
    assert status == {"status": "BROKEN", "label": "PRIOR HH / HL BROKEN → LL / LH",
                      "inflection": {"price_name": "Prior Low", "price": 95,
                                     "value_name": "Prior VAL", "value": 92}}


def test_prior_ll_lh_breaks_only_on_a_high_breach():
    status = build_prior_structure_status("LL/LH", 121, 96, 120, 95, 122, 92)
    assert status == {"status": "BROKEN", "label": "PRIOR LL / LH BROKEN → HH / HL",
                      "inflection": {"price_name": "Prior High", "price": 120,
                                     "value_name": "Prior VAH", "value": 122}}


@pytest.mark.parametrize(("structure", "expected_label", "price_name", "value_name"), [
    ("HH/HL", "PRIOR HH / HL INTACT", "Prior Low", "Prior VAL"),
    ("LL/LH", "PRIOR LL / LH INTACT", "Prior High", "Prior VAH"),
])
def test_prior_structure_intact_shows_exact_price_and_value_inflections(
    structure, expected_label, price_name, value_name
):
    status = build_prior_structure_status(structure, 119, 96, 120, 95, 122, 92)
    assert status["status"] == "INTACT"
    assert status["label"] == expected_label
    assert status["inflection"]["price_name"] == price_name
    assert status["inflection"]["value_name"] == value_name


def test_prior_structure_is_not_claimed_when_history_or_range_is_missing():
    status = build_prior_structure_status("HH/HL", None, None, 120, 95)
    assert status["status"] == "UNAVAILABLE"
    assert status["label"] == "PRIOR STRUCTURE UNAVAILABLE"
