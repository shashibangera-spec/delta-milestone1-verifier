from datetime import datetime, timezone

from options_oi_tracker import (
    parse_option_symbol, select_chain_rows, build_options_context,
    purge_expired_rows, parse_api_payload,
)


def ticker(symbol, product_id, kind, strike, oi=20):
    return {"symbol": symbol, "product_id": product_id, "contract_type": kind,
            "strike_price": str(strike), "oi": str(oi), "oi_value_usd": "100000",
            "oi_change_usd_6h": "250", "quotes": {"mark_iv": "0.55"},
            "greeks": {"delta": "0.4", "gamma": "0.001"}, "volume": 1.5}


def test_symbol_parsing_and_settlement_timestamp():
    parsed = parse_option_symbol("P-BTC-60000-291126")
    assert parsed["contract_type"] == "put_options"
    assert parsed["strike_price"] == 60000
    assert parsed["expiry_ts"] == datetime(2026, 11, 29, 12, tzinfo=timezone.utc)


def test_nearest_two_expiries_atm_plus_minus_six_dynamic_cap():
    rows, product_id = [], 1
    for expiry in ("291126", "301126", "011226"):
        for strike in range(55000, 70000, 500):
            for prefix, kind in (("C", "call_options"), ("P", "put_options")):
                rows.append(ticker(f"{prefix}-BTC-{strike}-{expiry}", product_id, kind, strike))
                product_id += 1
    selected = select_chain_rows(rows, 59418, datetime(2026, 11, 28, 18, tzinfo=timezone.utc))
    assert len(selected) == 52
    assert {r["expiry_date"].isoformat() for r in selected} == {"2026-11-29", "2026-11-30"}
    assert len({r["strike_price"] for r in selected if r["expiry_date"].isoformat() == "2026-11-29"}) == 13
    assert all(r["expiry_date"].isoformat() != "2026-12-01" for r in selected)


def test_payload_timestamp_is_microseconds():
    ts, spot, rows = parse_api_payload({"success": True, "timestamp": 1795975200000000,
                                        "spot_price": "59418.1", "result": []})
    assert ts.tzinfo is not None and spot == 59418.1 and rows == []


def test_settlement_based_purge_uses_expiry_plus_24_hours():
    class Fake:
        def __init__(self): self.sql = self.params = None
        def execute(self, sql, params): self.sql, self.params = sql, params
    fake = Fake()
    now = datetime(2026, 11, 30, 13, tzinfo=timezone.utc)
    purge_expired_rows(fake, now)
    assert "expiry_ts < %s - interval '24 hours'" in fake.sql
    assert fake.params == (now,)


def test_unwind_and_rebuild_thresholds():
    current = [
        {"product_id": 1, "symbol": "P-BTC-60000-291126", "strike_price": 60000,
         "contract_type": "put_options", "oi_btc": 30, "expiry_date": "2026-11-29"},
        {"product_id": 2, "symbol": "C-BTC-61000-291126", "strike_price": 61000,
         "contract_type": "call_options", "oi_btc": 20, "expiry_date": "2026-11-29"},
    ]
    baseline = [{"product_id": 1, "oi_btc": 50}, {"product_id": 2, "oi_btc": 5}]
    events = build_options_context(current, {"30m": baseline})["events"]
    assert [e["kind"] for e in events] == ["UNWIND", "REBUILD"]


def test_pcr_and_walls_are_descriptive():
    rows = [
        {"product_id": 1, "symbol": "P-BTC-60000-291126", "strike_price": 60000,
         "contract_type": "put_options", "oi_btc": 20, "expiry_date": "2026-11-29"},
        {"product_id": 2, "symbol": "C-BTC-61000-291126", "strike_price": 61000,
         "contract_type": "call_options", "oi_btc": 10, "expiry_date": "2026-11-29"},
    ]
    model = build_options_context(rows, {})
    assert model["expiries"][0]["pcr"]["put_call_ratio"] == 2
    assert len(model["expiries"][0]["top_put_walls"]) == 1

def test_payload_timestamp_and_spot_can_be_read_from_ticker_rows():
    row = ticker("P-BTC-60000-291126", 1, "put_options", 60000)
    row.update({"timestamp": 1795975200000000, "spot_price": "59418.1"})
    ts, spot, rows = parse_api_payload({"success": True, "result": [row]})
    assert ts == datetime.fromtimestamp(1795975200, tz=timezone.utc)
    assert spot == 59418.1
    assert rows == [row]
