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


if __name__ == "__main__":
    unittest.main()
