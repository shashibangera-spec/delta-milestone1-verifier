"""Offline tests for historical parity preflight and complete mismatch collection."""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from amt_engine.daily import BAR_SECONDS, EXPECTED_BARS, session_bounds, validate_session, calculate_profile
from amt_engine.parity_check import (
    ParityPreflightError, validate_all_reference_sessions, compare_session,
)


def make_raw(day, count=EXPECTED_BARS):
    start, _ = session_bounds(day)
    return [
        {
            "candle_time": start + timedelta(seconds=i * BAR_SECONDS),
            "open_value": Decimal("125"),
            "high_value": Decimal("175"),
            "low_value": Decimal("100"),
            "close_value": Decimal("150"),
        }
        for i in range(count)
    ]


class ParityPreflightTests(unittest.TestCase):
    def test_all_sessions_validated_before_returning_validated_inputs(self):
        days = [date(2026, 11, 17) + timedelta(days=i) for i in range(3)]
        profiles = [{"session_date": day} for day in days]
        called = []

        def fetch(day):
            called.append(day)
            return make_raw(day), []

        result = validate_all_reference_sessions(profiles, fetch)
        self.assertEqual(called, days)
        self.assertEqual(set(result), set(days))
        self.assertEqual(len(result), 3)

    def test_all_invalid_sessions_reported_and_assessment_stops(self):
        days = [date(2026, 11, 17) + timedelta(days=i) for i in range(4)]
        profiles = [{"session_date": day} for day in days]
        called = []

        def fetch(day):
            called.append(day)
            if day in (days[1], days[3]):
                return make_raw(day, 47), []
            return make_raw(day), []

        with self.assertRaises(ParityPreflightError) as caught:
            validate_all_reference_sessions(profiles, fetch)

        # The final session is still checked; no invalid session is silently skipped.
        self.assertEqual(called, days)
        message = str(caught.exception)
        self.assertIn(days[1].isoformat(), message)
        self.assertIn(days[3].isoformat(), message)
        self.assertIn('"comparison_started": false', message)
        self.assertIn("missing_timestamps", message)


class CompleteMismatchReportTests(unittest.TestCase):
    def test_all_missing_tpo_rows_are_returned_without_truncation(self):
        day = date(2026, 11, 19)
        validated = validate_session(day, make_raw(day))
        calculated_profile, calculated_rows = calculate_profile(day, validated.candles)
        reference_profile = {
            "session_date": day,
            "expected_bars": calculated_profile.expected_bars,
            "observed_bars": calculated_profile.observed_bars,
            "is_complete": calculated_profile.is_complete,
            "missing_candle_count": calculated_profile.missing_candle_count,
            "first_candle": calculated_profile.first_candle,
            "last_candle": calculated_profile.last_candle,
            "total_tpos": calculated_profile.total_tpos,
            "poc_lower": calculated_profile.poc_lower,
            "poc_upper": calculated_profile.poc_upper,
            "poc_tpo_count": calculated_profile.poc_tpo_count,
            "vah_lower": calculated_profile.vah_lower,
            "vah_upper": calculated_profile.vah_upper,
            "val_lower": calculated_profile.val_lower,
            "val_upper": calculated_profile.val_upper,
            "value_area_tpos": calculated_profile.value_area_tpos,
        }
        actual_keys = {row.row_lower for row in calculated_rows}
        # Add 175 distinct reference rows absent from the calculated profile.
        reference_rows = [
            {
                "row_lower": Decimal(i * 50),
                "row_upper": Decimal((i + 1) * 50),
                "tpo_count": 0,
                "is_poc": False,
                "is_value_area": False,
            }
            for i in range(175)
            if Decimal(i * 50) not in actual_keys
        ]

        mismatches = compare_session(
            reference_profile, reference_rows, calculated_profile, calculated_rows
        )
        missing = [m for m in mismatches if m["kind"] == "MISSING_TPO_ROW"]
        self.assertEqual(len(missing), len(reference_rows))
        self.assertGreater(len(mismatches), 100)
        self.assertEqual(
            {Decimal(m["row_lower"]) for m in missing},
            {row["row_lower"] for row in reference_rows},
        )


if __name__ == "__main__":
    unittest.main()
