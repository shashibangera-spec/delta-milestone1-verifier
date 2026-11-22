import unittest
from datetime import date, timedelta
from decimal import Decimal

from amt_engine.daily import BAR_SECONDS, EXPECTED_BARS, calculate_profile, session_bounds, validate_session
from amt_engine.developing import calculate_developing_profile


class DevelopingProfileTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 11, 22)
        self.start, _ = session_bounds(self.day)

    def row(self, index, low, high):
        return {
            "candle_time": self.start + timedelta(seconds=index * BAR_SECONDS),
            "open_value": str((Decimal(low) + Decimal(high)) / 2),
            "high_value": str(high), "low_value": str(low),
            "close_value": str((Decimal(low) + Decimal(high)) / 2),
        }

    def test_option_a_bridges_zero_count_rows_one_at_a_time(self):
        rows = [self.row(i, "0", "50") for i in range(24)]
        rows += [self.row(i + 24, "450", "500") for i in range(24)]
        result = calculate_developing_profile(self.day, rows)
        self.assertIsNotNone(result)
        self.assertEqual(result["VAL"], Decimal("0"))
        self.assertEqual(result["VAH"], Decimal("500"))
        self.assertEqual(result["TPOs"], 96)

    def test_poc_tie_chooses_lower_price(self):
        rows = [self.row(i, "100", "150") for i in range(6)]
        result = calculate_developing_profile(self.day, rows)
        self.assertEqual(result["POC"], Decimal("100"))

    def test_value_area_expansion_tie_chooses_lower_candidate(self):
        rows = [self.row(i, "50", "99") for i in range(24)]
        rows += [self.row(i + 24, "0", "0") for i in range(12)]
        rows += [self.row(i + 36, "100", "100") for i in range(12)]
        result = calculate_developing_profile(self.day, rows)
        self.assertEqual(result["POC"], Decimal("50"))
        self.assertEqual(result["VAL"], Decimal("0"))
        self.assertEqual(result["VAH"], Decimal("100"))

    def test_partial_session_prefix_is_valid(self):
        rows = [self.row(i, "100", "200") for i in range(7)]
        result = calculate_developing_profile(self.day, rows)
        self.assertEqual(result["ConfirmedBrackets"], 7)
        self.assertEqual(result["InputValidationStatus"], "PASS · CONTIGUOUS CONFIRMED PREFIX")
        self.assertEqual(result["ProfileCalculationStatus"], "DEVELOPING · CALCULATED · RESEARCH OUTPUT")
        self.assertEqual(result["DailyAcceptanceStatus"], "NOT APPLICABLE · NOT ACCEPTED")

    def test_missing_middle_slot_fails_closed(self):
        rows = [self.row(i, "100", "200") for i in range(7)]
        del rows[3]
        self.assertIsNone(calculate_developing_profile(self.day, rows))

    def test_non_prefix_sequence_fails_closed(self):
        rows = [self.row(i, "100", "200") for i in range(7)]
        rows[3]["candle_time"] += timedelta(minutes=30)
        self.assertIsNone(calculate_developing_profile(self.day, rows))

    def test_duplicate_slot_fails_closed(self):
        rows = [self.row(i, "100", "200") for i in range(5)]
        rows[4]["candle_time"] = rows[3]["candle_time"]
        self.assertIsNone(calculate_developing_profile(self.day, rows))

    def test_off_grid_slot_fails_closed(self):
        rows = [self.row(i, "100", "200") for i in range(5)]
        rows[2]["candle_time"] += timedelta(minutes=1)
        self.assertIsNone(calculate_developing_profile(self.day, rows))

    def test_invalid_ohlc_fails_closed(self):
        rows = [self.row(i, "100", "200") for i in range(4)]
        rows[2]["low_value"] = "250"
        self.assertIsNone(calculate_developing_profile(self.day, rows))

    def test_completed_profile_matches_approved_v1_engine_fixture(self):
        raw = [self.row(i, "100", "200") for i in range(EXPECTED_BARS)]
        validation = validate_session(self.day, raw)
        self.assertTrue(validation.valid, validation.report)
        approved_profile, _ = calculate_profile(self.day, validation.candles)
        developing = calculate_developing_profile(self.day, raw)
        self.assertEqual(developing["VAL"], approved_profile.val_lower)
        self.assertEqual(developing["POC"], approved_profile.poc_lower)
        self.assertEqual(developing["VAH"], approved_profile.vah_upper)
        self.assertEqual(developing["TPOs"], approved_profile.total_tpos)


    def test_live_read_only_2026_11_22_confirmed_snapshot_matches_independent_decimal_fixture(self):
        # Read-only snapshot from research.delta_candles, source=delta_india,
        # resolution=30m, PRICE/BTCUSD, session 2026-11-22 00:00-07:00 UTC.
        raw = [
            ("60191", "60320", "60153", "60270.5"),
            ("60270.5", "60317", "60123.5", "60191"),
            ("60174.5", "60226.5", "60088.5", "60096"),
            ("60096.5", "60195", "59984.5", "60088"),
            ("60088", "60161", "59787", "59823.5"),
            ("59824", "59824", "59390", "59474.5"),
            ("59468", "59587.5", "59242.5", "59355"),
            ("59355", "59401", "59101", "59335.5"),
            ("59335.5", "59645", "59166", "59243.5"),
            ("59243.5", "59436", "59220", "59295"),
            ("59290", "59308", "58776", "58987"),
            ("58987.5", "59062.5", "58750", "58900"),
            ("58900", "59163.5", "58900", "59016.5"),
            ("59016", "59270.5", "58982.5", "59129.5"),
            ("59129", "59201.5", "58994.5", "59081.5"),
        ]
        candles = []
        for index, (o, h, l, c) in enumerate(raw):
            candles.append({
                "candle_time": self.start + timedelta(seconds=index * BAR_SECONDS),
                "open_value": o, "high_value": h, "low_value": l, "close_value": c,
            })
        result = calculate_developing_profile(self.day, candles)
        self.assertEqual(result["ConfirmedBrackets"], 15)
        self.assertEqual(result["TPOs"], 105)
        self.assertEqual(result["Rows"], 32)
        self.assertEqual(result["POC"], Decimal("59200"))
        self.assertEqual(result["VAL"], Decimal("58750"))
        self.assertEqual(result["VAH"], Decimal("59650"))


if __name__ == "__main__":
    unittest.main()
