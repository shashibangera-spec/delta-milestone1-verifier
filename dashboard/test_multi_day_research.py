import unittest
from datetime import datetime, timedelta, timezone
from multi_day_research import analyze_multi_day_range

UTC = timezone.utc
START = datetime(2026, 11, 15, 0, 0, tzinfo=UTC)
END = START + timedelta(days=3)


def rows(start, count, price):
    result = []
    for i in range(count):
        ts = start + timedelta(minutes=30*i)
        if price:
            result.append({"candle_time": ts, "open_value": 100+i, "high_value": 110+i,
                           "low_value": 90+i, "close_value": 100+i, "volume": 1})
        else:
            result.append({"candle_time": ts, "close_value": 500+i*0.5})
    return result


class MultiDayResearchTests(unittest.TestCase):
    def setUp(self):
        self.price = rows(START, 144, True)
        self.oi = [{"candle_time": START-timedelta(minutes=30), "close_value": 500.0}]
        self.oi += rows(START, 144, False)

    def test_three_complete_days(self):
        r = analyze_multi_day_range(self.price, self.oi, START, END)
        self.assertTrue(r["valid"], r["reason"])
        self.assertEqual((r["session_count"], r["candle_count"]), (3, 144))
        self.assertEqual(r["opening_oi"], 500.0)
        self.assertAlmostEqual(r["closing_oi"], 571.5)
        self.assertAlmostEqual(r["net_oi"], 71.5)
        self.assertEqual(r["oi_up_count"], 144)
        self.assertEqual(len(r["history"]), 144)
        self.assertAlmostEqual(sum(r["oi_by_value"].values()), r["net_oi"])

    def test_missing_price_candle_fails_closed(self):
        r = analyze_multi_day_range(self.price[:-1], self.oi, START, END)
        self.assertFalse(r["valid"])
        self.assertIn("PRICE coverage", r["reason"])

    def test_missing_oi_candle_fails_closed(self):
        r = analyze_multi_day_range(self.price, self.oi[:-1], START, END)
        self.assertFalse(r["valid"])
        self.assertIn("OI coverage", r["reason"])

    def test_missing_boundary_fails_closed(self):
        r = analyze_multi_day_range(self.price, self.oi[1:], START, END)
        self.assertFalse(r["valid"])
        self.assertIn("boundary candle", r["reason"])

    def test_partial_session_range_rejected(self):
        r = analyze_multi_day_range(self.price, self.oi, START, START+timedelta(days=2,hours=12))
        self.assertFalse(r["valid"])
        self.assertIn("whole UTC-day", r["reason"])

    def test_unpaired_timestamp_rejected(self):
        broken = list(self.oi)
        broken[1] = dict(broken[1], candle_time=broken[1]["candle_time"]+timedelta(minutes=30))
        r = analyze_multi_day_range(self.price, broken, START, END)
        self.assertFalse(r["valid"])
        self.assertIn("timestamps do not match", r["reason"])


if __name__ == "__main__":
    unittest.main()
