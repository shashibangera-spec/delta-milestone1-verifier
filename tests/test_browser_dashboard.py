from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from browser_dashboard.auction_context import build_prior_auction_context
from browser_dashboard.main import EXPECTED_HOST, _calculate_v17_developing_profile, _calculate_subsession_value_progression, _calculate_nifty_intraday_value_progression, _connect, _discovery, _json, _session_rows, _validated_database_url, require_dashboard_auth


def rows(*closes):
    start = datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc)
    return [
        {"candle_time": start + timedelta(minutes=30 * i), "close_value": close}
        for i, close in enumerate(closes)
    ]



def test_subsession_value_progression_starts_with_prior_overnight_and_compares_in_order():
    day = date(2026, 11, 28)
    start = datetime(2026, 11, 28, 0, 0, tzinfo=timezone.utc)
    prior_start = start - timedelta(hours=4)
    candles = [
        {
            "candle_time": prior_start + timedelta(minutes=30 * i),
            "open_value": 10, "high_value": 100, "low_value": 0, "close_value": 90,
        }
        for i in range(8)
    ]
    candles.extend([
        {"candle_time": start, "open_value": 110, "high_value": 200, "low_value": 100, "close_value": 190},
        {"candle_time": start + timedelta(hours=8), "open_value": 210, "high_value": 300, "low_value": 200, "close_value": 290},
        {"candle_time": start + timedelta(hours=13, minutes=30), "open_value": 160, "high_value": 250, "low_value": 150, "close_value": 240},
        # This candle is not closed as of 14:15 UTC and must not enter the profile.
        {"candle_time": start + timedelta(hours=14), "open_value": 240, "high_value": 350, "low_value": 240, "close_value": 340},
    ])

    result = _calculate_subsession_value_progression(
        candles, day, start + timedelta(hours=14, minutes=15)
    )

    assert [row["candles"] for row in result] == [8, 1, 1, 1]
    assert [row["value_step"] for row in result] == [
        "INITIAL", "VALUE STEPPED UP", "VALUE STEPPED UP", "VALUE STEPPED DOWN"
    ]
    assert [row["sub_session"] for row in result] == [
        "Prior US Overnight (20:00–00:00 UTC / 01:30–05:30 IST)",
        "Asia (00:00–08:00 UTC / 05:30–13:30 IST)",
        "Europe (08:00–13:30 UTC / 13:30–19:00 IST)",
        "US Cash (13:30–00:00 UTC / 19:00–05:30 IST)",
    ]
    assert (result[0]["val"], result[0]["poc"], result[0]["vah"]) == (0, 25, 150)
    assert (result[1]["val"], result[1]["poc"], result[1]["vah"]) == (100, 125, 250)
    assert (result[2]["val"], result[2]["poc"], result[2]["vah"]) == (200, 225, 350)
    assert result[3]["open"] == 160
    assert result[3]["close"] == 240
    assert result[3]["candles"] == 1
def test_dashboard_discovery_starts_on_first_close_outside_value():
    assert _discovery(rows(60500), 60000, 59000) == "DISCOVERY_ABOVE"
    assert _discovery(rows(58000), 60000, 59000) == "DISCOVERY_BELOW"


def test_dashboard_discovery_terminates_after_two_strict_inside_closes():
    assert _discovery(rows(60500, 59500), 60000, 59000) == "DISCOVERY_ABOVE"
    assert _discovery(rows(60500, 59500, 59600), 60000, 59000) == "IN_VALUE"


def test_dashboard_discovery_opposite_boundary_breach_switches_state():
    assert _discovery(rows(60500, 58900), 60000, 59000) == "DISCOVERY_BELOW"


def test_dashboard_discovery_requires_contiguous_session_history():
    candles = rows(60500, 59500, 59600)
    candles[2]["candle_time"] += timedelta(minutes=30)
    assert _discovery(candles, 60000, 59000) == "UNKNOWN"


def test_dashboard_refuses_non_production_host_before_connecting(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://amt_dashboard_ro:secret@ep-old-bar-aoau4qop.c-2.ap-southeast-1.aws.neon.tech/amt_research",
    )
    with pytest.raises(RuntimeError, match="approved amt_dashboard_ro"):
        _connect()


def test_dashboard_accepts_approved_neon_pooler_host(monkeypatch):
    url = (
        "postgresql://amt_dashboard_ro:secret@"
        "ep-morning-mountain-aopl02wv-pooler.c-2.ap-southeast-1.aws.neon.tech/"
        "amt_research"
    )
    monkeypatch.setenv("DATABASE_URL", url)
    assert _validated_database_url("DATABASE_URL", EXPECTED_HOST) == url


def test_dashboard_rejects_wrong_branch_host(monkeypatch):
    monkeypatch.setenv(
        "SOURCE_DATABASE_URL",
        "postgresql://amt_dashboard_ro:secret@ep-wrong-branch.c-2.ap-southeast-1.aws.neon.tech/amt_research",
    )
    with pytest.raises(RuntimeError, match="approved amt_dashboard_ro"):
        _validated_database_url(
            "SOURCE_DATABASE_URL",
            "ep-sparkling-queen-aoqgp0mw.c-2.ap-southeast-1.aws.neon.tech",
        )


def test_dashboard_requires_configured_basic_auth(monkeypatch):
    monkeypatch.delenv("DASHBOARD_USERNAME", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_dashboard_auth(HTTPBasicCredentials(username="user", password="pass"))
    assert exc.value.status_code == 503


def test_dashboard_basic_auth_accepts_only_matching_credentials(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "observer")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "correct-horse-battery")
    assert require_dashboard_auth(
        HTTPBasicCredentials(username="observer", password="correct-horse-battery")
    ) == "observer"
    with pytest.raises(HTTPException) as exc:
        require_dashboard_auth(HTTPBasicCredentials(username="observer", password="wrong"))
    assert exc.value.status_code == 401


def test_dashboard_json_serializes_uuid_and_date_values():
    from uuid import UUID
    value = {
        "profile_id": UUID("12345678-1234-5678-1234-567812345678"),
        "session_date": date(2026, 11, 26),
    }
    assert _json(value) == {
        "profile_id": "12345678-1234-5678-1234-567812345678",
        "session_date": "2026-11-26",
    }


def test_prior_auction_classifies_close_migration_and_swing():
    profiles = [
        {"session_date": date(2026, 11, 25), "poc_lower": 100, "vah_upper": 110, "val_lower": 90},
        {"session_date": date(2026, 11, 26), "poc_lower": 102, "vah_upper": 112, "val_lower": 92},
    ]
    candles = [
        {"session_date": date(2026, 11, 25), "range": {"high": 115, "low": 85, "close": 105}},
        {"session_date": date(2026, 11, 26), "range": {"high": 120, "low": 95, "close": 114}},
    ]
    result = build_prior_auction_context(profiles, candles, [])
    assert result["close_location"] == "Above Value"
    assert result["value_migration"] == "Migrating Up"
    assert result["swing_structure"] == "HH/HL"


def test_prior_auction_marks_mixed_value_migration():
    profiles = [
        {"session_date": date(2026, 11, 25), "poc_lower": 100, "vah_upper": 110, "val_lower": 90},
        {"session_date": date(2026, 11, 26), "poc_lower": 102, "vah_upper": 109, "val_lower": 92},
    ]
    candles = [
        {"session_date": date(2026, 11, 25), "range": {"high": 115, "low": 85, "close": 105}},
        {"session_date": date(2026, 11, 26), "range": {"high": 116, "low": 86, "close": 100}},
    ]
    result = build_prior_auction_context(profiles, candles, [])
    assert result["value_migration"] == "Overlapping or Mixed"
    assert result["swing_structure"] == "HH/HL"


def test_subsession_ranges_and_extensions_are_descriptive():
    from datetime import datetime
    profiles = [
        {"session_date": date(2026, 11, 25), "poc_lower": 100, "vah_upper": 110, "val_lower": 90},
        {"session_date": date(2026, 11, 26), "poc_lower": 102, "vah_upper": 112, "val_lower": 92},
    ]
    candles = [
        {"session_date": date(2026, 11, 25), "range": {"high": 115, "low": 85, "close": 105}},
        {"session_date": date(2026, 11, 26), "range": {"high": 120, "low": 95, "close": 114}},
    ]
    current = [
        {"candle_time": datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc), "high_value": 121, "low_value": 100, "close_value": 118},
        {"candle_time": datetime(2026, 11, 27, 8, 0, tzinfo=timezone.utc), "high_value": 119, "low_value": 94, "close_value": 96},
    ]
    result = build_prior_auction_context(profiles, candles, current)
    assert result["subsessions"][0]["development"] == "Above prior range"
    assert result["subsessions"][1]["development"] == "Below prior range"
    assert result["informational_only"] is True


def test_dashboard_discovery_rows_are_scoped_to_current_utc_day():
    previous_day = [
        {"candle_time": datetime(2026, 11, 25, 23, 0, tzinfo=timezone.utc), "close_value": 60500},
        {"candle_time": datetime(2026, 11, 25, 23, 30, tzinfo=timezone.utc), "close_value": 60600},
    ]
    current_day = [
        {"candle_time": datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc), "close_value": 59500},
        {"candle_time": datetime(2026, 11, 26, 0, 30, tzinfo=timezone.utc), "close_value": 59600},
    ]
    selected = _session_rows(previous_day + current_day, date(2026, 11, 26))
    assert selected == current_day
    assert _discovery(selected, 60000, 59000) == "IN_VALUE"


def test_live_v17_developing_profile_uses_zero_anchored_inclusive_50_dollar_bins():
    start = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)
    candles = [{
        "candle_time": start,
        "low_value": 100,
        "high_value": 200,
    }]
    result = _calculate_v17_developing_profile(
        candles, start, start + timedelta(minutes=30)
    )
    assert result["status"] == "READY"
    assert result["progress"] == "1/48"
    assert result["method_version"] == "AMT_ENGINE_V1.7"
    assert result["dpoc_lower"] == 100
    assert result["dpoc_upper"] == 150
    assert result["dval"] == 100
    assert result["dvah"] == 250
    assert result["total_tpos"] == 3


def test_live_v17_developing_profile_withholds_values_after_a_candle_gap():
    start = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)
    candles = [
        {"candle_time": start, "low_value": 100, "high_value": 150},
        {"candle_time": start + timedelta(hours=1), "low_value": 100, "high_value": 150},
    ]
    result = _calculate_v17_developing_profile(
        candles, start, start + timedelta(hours=1, minutes=30)
    )
    assert result["status"] == "GAP_IN_COMPLETED_CANDLE_SEQUENCE"
    assert result["progress"] == "1/48"
    assert result["dvah"] is None
    assert result["dpoc_lower"] is None
    assert result["dval"] is None


def test_live_v17_developing_profile_excludes_unclosed_and_future_candles():
    start = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)
    candles = [
        {"candle_time": start, "low_value": 100, "high_value": 150},
        {"candle_time": start + timedelta(minutes=30), "low_value": 200, "high_value": 250},
    ]
    result = _calculate_v17_developing_profile(
        candles, start, start + timedelta(minutes=45)
    )
    assert result["status"] == "READY"
    assert result["progress"] == "1/48"
    assert result["dpoc_lower"] == 100
    assert result["dvah"] == 200


def test_live_v17_developing_profile_rejects_invalid_ohlc():
    start = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)
    candles = [{"candle_time": start, "low_value": 200, "high_value": 100}]
    result = _calculate_v17_developing_profile(
        candles, start, start + timedelta(minutes=30)
    )
    assert result["status"] == "INVALID_OHLC"
    assert result["progress"] == "0/48"
    assert result["dvah"] is None


def test_developing_value_card_disclaims_playbook_reference_replacement():
    from browser_dashboard.main import HTML
    assert "LIVE DEVELOPING VALUE" in HTML
    assert "CURRENT SESSION" in HTML
    assert "frozen Prior Reference VAH/POC/VAL" in HTML
    assert "used by Playbook v1.4" in HTML


@pytest.mark.parametrize(
    "current_high,current_low,expected",
    [
        (121, 96, "HH / HL"),
        (119, 84, "LL / LH"),
        (121, 84, "HH / LL (Outside)"),
        (120, 95, "LH / HL (Inside)"),
    ],
)
def test_live_intraday_swing_compares_current_completed_range_to_prior_auction(
    current_high, current_low, expected
):
    profiles = [
        {"session_date": date(2026, 11, 25), "poc_lower": 100, "vah_upper": 110, "val_lower": 90},
        {"session_date": date(2026, 11, 26), "poc_lower": 102, "vah_upper": 112, "val_lower": 92},
    ]
    candles = [
        {"session_date": date(2026, 11, 25), "range": {"high": 115, "low": 85, "close": 105}},
        {"session_date": date(2026, 11, 26), "range": {"high": 120, "low": 95, "close": 114}},
    ]
    current = [{
        "candle_time": datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc),
        "high_value": current_high, "low_value": current_low, "close_value": 100,
    }]
    result = build_prior_auction_context(profiles, candles, current)
    swing = result["live_intraday_swing"]
    assert swing["label"] == expected
    assert swing["current_range"] == {"low": current_low, "high": current_high}
    assert swing["prior_range"] == {"low": 95, "high": 120}
    assert swing["completed_candles"] == 1


def test_live_intraday_swing_is_unavailable_without_current_completed_candles():
    profiles = [
        {"session_date": date(2026, 11, 25), "poc_lower": 100, "vah_upper": 110, "val_lower": 90},
        {"session_date": date(2026, 11, 26), "poc_lower": 102, "vah_upper": 112, "val_lower": 92},
    ]
    candles = [
        {"session_date": date(2026, 11, 25), "range": {"high": 115, "low": 85, "close": 105}},
        {"session_date": date(2026, 11, 26), "range": {"high": 120, "low": 95, "close": 114}},
    ]
    result = build_prior_auction_context(profiles, candles, [])
    assert result["live_intraday_swing"]["label"] == "Unavailable"
    assert result["live_intraday_swing"]["current_range"] is None


def test_dashboard_renders_live_intraday_swing_as_descriptive_visual_aid():
    from browser_dashboard.main import HTML
    assert "LIVE INTRADAY SWING VS PRIOR DAY" in HTML
    assert "factual comparison of completed 30m candles" in HTML


def test_btc_prior_structure_status_has_dedicated_nifty_style_pill_renderer():
    from browser_dashboard.main import HTML

    assert 'id="btc-prior-structure-status"' in HTML
    assert 'id="nifty-prior-structure-status"' in HTML
    assert "btcStatusNode.textContent=statusText" in HTML
    assert "btcStatusNode.className='sub structure-status '" in HTML
    assert "liveNode.innerHTML=" not in HTML


def test_dashboard_identifies_v14_shadow_mode_and_ledger():
    from browser_dashboard.main import HTML, load_overview
    assert "Playbook v1.4" in HTML
    assert "SHADOW_V1_4" in HTML
    assert "playbook_v14_shadow_trades" in __import__("inspect").getsource(load_overview)


def test_nifty_intraday_value_progression_uses_three_completed_bracket_windows():
    from zoneinfo import ZoneInfo
    from amt_engine.nifty_v17 import calculate_profile

    day = date(2026, 11, 27)
    ist = ZoneInfo("Asia/Kolkata")
    bars = []
    for bracket in range(1, 14):
        base = 25000 if bracket <= 4 else (25100 if bracket <= 9 else 24900)
        bars.append({
            "bracket": bracket,
            "start": (datetime.combine(day, datetime.min.time()) +
                      timedelta(minutes=15 + 30 * (bracket - 1))).isoformat(),
            "open": base, "high": base + 20, "low": base - 20, "close": base + 10,
        })

    result = _calculate_nifty_intraday_value_progression(
        bars, day, datetime(2026, 11, 27, 15, 30, tzinfo=ist), calculate_profile
    )

    assert [row["candles"] for row in result] == [4, 5, 4]
    assert [row["session"] for row in result] == [
        "Morning Open / IB (09:15–11:15 IST · Brackets 1–4)",
        "Midday Session (11:15–13:45 IST · Brackets 5–9)",
        "Afternoon Close (13:45–15:30 IST · Brackets 10–13)",
    ]
    assert result[0]["value_step"] == "INITIAL"
    assert result[1]["value_step"] == "VALUE STEPPED UP"
    assert result[2]["value_step"] == "VALUE STEPPED DOWN"
    assert result[0]["open"] == 25000
    assert result[2]["close"] == 24910


def test_nifty_intraday_value_progression_excludes_uncompleted_and_breaks_on_gaps():
    from zoneinfo import ZoneInfo
    from amt_engine.nifty_v17 import calculate_profile

    day = date(2026, 11, 27)
    ist = ZoneInfo("Asia/Kolkata")
    bars = [{
        "bracket": bracket, "open": 25000, "high": 25020,
        "low": 24980, "close": 25010,
    } for bracket in (1, 2, 4, 5, 6, 7, 8, 9)]
    result = _calculate_nifty_intraday_value_progression(
        bars, day, datetime(2026, 11, 27, 12, 0, tzinfo=ist), calculate_profile
    )
    assert result[0]["candles"] == 2
    assert result[1]["candles"] == 5
    assert result[1]["value_step"] == "UNAVAILABLE"
    assert result[2]["candles"] == 0


def test_overview_cache_is_per_endpoint_and_expires_after_45_seconds(monkeypatch):
    import browser_dashboard.main as dashboard

    dashboard._response_cache.clear()
    clock = {"now": 100.0}
    calls = {"btc": 0, "nifty": 0}
    monkeypatch.setattr(dashboard.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(dashboard, "load_overview", lambda: calls.__setitem__("btc", calls["btc"] + 1) or {"source": "btc"})
    monkeypatch.setattr(dashboard, "load_nifty_overview", lambda: calls.__setitem__("nifty", calls["nifty"] + 1) or {"source": "nifty"})

    assert dashboard.overview("observer").body == b'{"source":"btc"}'
    assert dashboard.overview("observer").body == b'{"source":"btc"}'
    assert dashboard.nifty_overview("observer").body == b'{"source":"nifty"}'
    assert calls == {"btc": 1, "nifty": 1}

    clock["now"] = 144.9
    dashboard.overview("observer")
    dashboard.nifty_overview("observer")
    assert calls == {"btc": 1, "nifty": 1}

    clock["now"] = 145.0
    dashboard.overview("observer")
    dashboard.nifty_overview("observer")
    assert calls == {"btc": 2, "nifty": 2}
    dashboard._response_cache.clear()


def test_dashboard_refresh_pauses_when_hidden_and_resumes_immediately():
    from browser_dashboard.main import HTML

    assert "const REFRESH_INTERVAL_MS=60000" in HTML
    assert "document.addEventListener('visibilitychange'" in HTML
    assert "if(document.hidden){stopRefreshTimer();return;}" in HTML
    assert "refreshActiveMarket();" in HTML
    assert "setInterval(refreshActiveMarket,REFRESH_INTERVAL_MS)" in HTML
    assert "},10000)" not in HTML
    assert "if(!document.hidden)refresh()" in HTML


def test_value_ladder_nearest_levels_and_distance_percent_math_for_btcusd():
    from browser_dashboard.main import _build_value_ladder_model

    model = _build_value_ladder_model(
        "BTCUSD", 87420,
        {"vah": 87650, "poc": 87300, "val": 87100},
        {"vah": 87550, "poc": 87350, "val": 87200},
        3,
    )
    assert model["nearest_above"] == {
        "level": 87550.0, "points": 130.0, "percent": pytest.approx(130 / 87420 * 100)
    }
    assert model["nearest_below"] == {
        "level": 87350.0, "points": -70.0, "percent": pytest.approx(70 / 87420 * 100)
    }
    assert model["playbook_boundaries"] is True


def test_value_ladder_nifty_is_descriptive_and_has_no_playbook_boundary():
    from browser_dashboard.main import _build_value_ladder_model

    model = _build_value_ladder_model(
        "NIFTY 50 SPOT", 26180.5,
        {"vah": 26250, "poc": 26150, "val": 26050},
        {"vah": 26220, "poc": 26170, "val": 26100},
        4,
    )
    assert model["nearest_above"]["level"] == 26220
    assert model["nearest_above"]["points"] == 39.5
    assert model["nearest_above"]["percent"] == pytest.approx(39.5 / 26180.5 * 100)
    assert model["nearest_below"]["level"] == 26170
    assert model["nearest_below"]["points"] == -10.5
    assert model["playbook_boundaries"] is False


def test_value_ladder_label_stagger_preserves_price_positions_and_minimum_gap():
    from browser_dashboard.main import _build_value_ladder_model

    model = _build_value_ladder_model(
        "BTCUSD", 100,
        {"vah": 100.01, "poc": 100.02, "val": 99.99},
        {"vah": 100.015, "poc": 100.025, "val": 99.985},
        2, plot_height=260, min_label_gap=24,
    )
    for lane in ("prior", "developing"):
        lane_levels = sorted(
            [item for item in model["levels"] if item["lane"] == lane and item["y"] is not None],
            key=lambda item: item["label_y"],
        )
        assert all(
            right["label_y"] - left["label_y"] >= 24 - 1e-9
            for left, right in zip(lane_levels, lane_levels[1:])
        )
        assert any(item["y"] != item["label_y"] for item in lane_levels)
    # The underlying level coordinate remains the exact price-proportional coordinate.
    assert len({round(item["y"], 6) for item in model["levels"] if item["value"] is not None}) > 1


def test_value_ladder_zero_completed_candles_returns_na_for_all_developing_levels():
    from browser_dashboard.main import _build_value_ladder_model

    model = _build_value_ladder_model(
        "NIFTY 50 SPOT", 25000,
        {"vah": 25100, "poc": 25000, "val": 24900},
        {"vah": 25120, "poc": 25020, "val": 24920},
        0,
    )
    assert model["candle_count"] == 0
    assert [item["value"] for item in model["levels"] if item["lane"] == "developing"] == [None, None, None]


def test_value_ladder_rendering_is_wired_for_btcusd_and_nifty_responsive_layout():
    from browser_dashboard.main import HTML

    assert 'id="btc-value-ladder-card"' in HTML
    assert 'id="nifty-value-ladder-card"' in HTML
    assert "renderValueLadder('btc',d.value_ladder)" in HTML
    assert "renderValueLadder('nifty',d.value_ladder)" in HTML
    assert "@media(max-width:767px)" in HTML
    assert "LIVE CMP" in HTML
    assert "SHARED PRICE AXIS" in HTML
    assert "Nearest Level Above" in HTML
    assert "Nearest Level Below" in HTML
    assert "No NIFTY Playbook trigger" in HTML
