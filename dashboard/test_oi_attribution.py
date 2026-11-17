import unittest
from datetime import datetime, timedelta, timezone
from oi_attribution import calculate_value_area_oi_breakdown

UTC = timezone.utc
START = datetime(2026, 11, 18, 0, 0, tzinfo=UTC)
BOUNDARY = {"candle_time": START - timedelta(minutes=30), "close_value": 100.0}

def row(minute, close):
    return {"candle_time": START + timedelta(minutes=minute), "close_value": close}

class OIAttributionTests(unittest.TestCase):
    def test_three_zones_reconcile_exactly(self):
        prices = [row(0, 110), row(30, 100), row(60, 90)]
        oi = [BOUNDARY, row(0, 103), row(30, 101), row(60, 106)]
        r = calculate_value_area_oi_breakdown(prices, oi, START, 95, 105)
        self.assertTrue(r["valid"], r["reason"])
        self.assertEqual((r["prev_oi"], r["day_oi"]), (100, 6))
        self.assertEqual((r["above"], r["inside"], r["below"]), (3, -2, 5))
        self.assertEqual(r["above"] + r["inside"] + r["below"], r["day_oi"])

    def test_value_area_boundaries_are_inside_value(self):
        prices = [row(0, 95), row(30, 105)]
        oi = [BOUNDARY, row(0, 102), row(30, 104)]
        r = calculate_value_area_oi_breakdown(prices, oi, START, 95, 105)
        self.assertTrue(r["valid"], r["reason"])
        self.assertEqual((r["inside"], r["above"], r["below"]), (4, 0, 0))

    def test_missing_price_oi_slot_fails_closed(self):
        prices = [row(0, 110), row(60, 90)]
        oi = [BOUNDARY, row(0, 103), row(30, 102), row(60, 106)]
        r = calculate_value_area_oi_breakdown(prices, oi, START, 95, 105)
        self.assertFalse(r["valid"])
        self.assertIn("timestamps differ", r["reason"])\n        self.assertIsNone(r["above"])

    def test_missing_boundary_oi_fails_closed(self):
        r = calculate_value_area_oi_breakdown([row(0, 100)], [row(0, 101)], START, 95, 105)
        self.assertFalse(r["valid"])
        self.assertIsNone(r["prev_oi"])

    def test_missing_30m_slot_fails_closed(self):
        prices = [row(0, 110), row(60, 90)]
        oi = [BOUNDARY, row(0, 103), row(60, 106)]
        r = calculate_value_area_oi_breakdown(prices, oi, START, 95, 105)
        self.assertFalse(r["valid"])
        self.assertIn("slot is missing", r["reason"])\n        self.assertIsNone(r["above"])

if __name__ == "__main__":
    unittest.main()
