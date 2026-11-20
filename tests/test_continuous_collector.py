import unittest
from datetime import datetime, timezone

from continuous_collector import (
    SLOT_SECONDS,
    EXPECTED_PRICE_ROWS,
    EXPECTED_OI_ROWS,
    EXPECTED_FEATURE_ROWS,
    EXPECTED_FEATURE_START_UTC,
    EXPECTED_FEATURE_MAX_UTC,
    EXPECTED_FEATURE_BASELINE_CHECKSUM,
    EXPECTED_BASELINE_START_UTC,
    EXPECTED_BASELINE_MAX_UTC,
    EXPECTED_PRICE_BASELINE_CHECKSUM,
    EXPECTED_OI_BASELINE_CHECKSUM,
    CHECKSUM_DELIMITER_SQL,
    validate_historical_candle_baseline,
    validate_feature_baseline,
    validate_incremental_series_integrity,
)


class CollectorSafetyTests(unittest.TestCase):
    def setUp(self):
        self.baseline = {
            "PRICE": {
                "row_count": EXPECTED_PRICE_ROWS,
                "first_time": EXPECTED_BASELINE_START_UTC,
                "last_time": EXPECTED_BASELINE_MAX_UTC,
                "checksum": EXPECTED_PRICE_BASELINE_CHECKSUM,
            },
            "OI": {
                "row_count": EXPECTED_OI_ROWS,
                "first_time": EXPECTED_BASELINE_START_UTC,
                "last_time": EXPECTED_BASELINE_MAX_UTC,
                "checksum": EXPECTED_OI_BASELINE_CHECKSUM,
            },
        }

    def test_grid_is_thirty_minutes(self):
        self.assertEqual(SLOT_SECONDS, 1800)

    def test_original_baseline_constants_remain_fixed(self):
        self.assertEqual(EXPECTED_PRICE_ROWS, 8641)
        self.assertEqual(EXPECTED_OI_ROWS, 8641)
        self.assertEqual(EXPECTED_FEATURE_ROWS, 1800)
        self.assertEqual(EXPECTED_BASELINE_MAX_UTC, datetime(2026, 11, 17, 0, 0, tzinfo=timezone.utc))

    def test_valid_original_baseline_passes_even_when_live_tables_have_more_rows(self):
        # The validator receives the fixed historical prefix, never the live total.
        validate_historical_candle_baseline(self.baseline)

    def test_missing_historical_series_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "Missing historical OI"):
            validate_historical_candle_baseline({"PRICE": self.baseline["PRICE"]})

    def test_historical_row_count_change_fails_closed(self):
        changed = {**self.baseline, "PRICE": {**self.baseline["PRICE"], "row_count": 8795}}
        with self.assertRaisesRegex(RuntimeError, "row-count mismatch"):
            validate_historical_candle_baseline(changed)

    def test_historical_checksum_change_fails_closed(self):
        changed = {**self.baseline, "OI": {**self.baseline["OI"], "checksum": "tampered"}}
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            validate_historical_candle_baseline(changed)

    def test_historical_time_range_change_fails_closed(self):
        changed = {
            **self.baseline,
            "PRICE": {
                **self.baseline["PRICE"],
                "last_time": datetime(2026, 11, 17, 0, 30, tzinfo=timezone.utc),
            },
        }
        with self.assertRaisesRegex(RuntimeError, "time-range mismatch"):
            validate_historical_candle_baseline(changed)

    def test_original_amt_feature_history_is_pinned(self):
        validate_feature_baseline({
            "row_count": EXPECTED_FEATURE_ROWS,
            "first_time": EXPECTED_FEATURE_START_UTC,
            "last_time": EXPECTED_FEATURE_MAX_UTC,
            "checksum": EXPECTED_FEATURE_BASELINE_CHECKSUM,
        })

    def test_amt_feature_checksum_change_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "AMT feature baseline checksum mismatch"):
            validate_feature_baseline({
                "row_count": EXPECTED_FEATURE_ROWS,
                "first_time": EXPECTED_FEATURE_START_UTC,
                "last_time": EXPECTED_FEATURE_MAX_UTC,
                "checksum": "tampered",
            })

    def test_contiguous_incremental_price_and_oi_pass(self):
        validate_incremental_series_integrity({
            "PRICE": {"off_grid": 0, "grid_gaps": 0},
            "OI": {"off_grid": 0, "grid_gaps": 0},
        })

    def test_missing_incremental_series_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "Missing incremental OI"):
            validate_incremental_series_integrity({
                "PRICE": {"off_grid": 0, "grid_gaps": 0},
            })

    def test_off_grid_incremental_candle_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "Off-grid PRICE"):
            validate_incremental_series_integrity({
                "PRICE": {"off_grid": 1, "grid_gaps": 0},
                "OI": {"off_grid": 0, "grid_gaps": 0},
            })

    def test_missing_thirty_minute_slot_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "timestamp gaps"):
            validate_incremental_series_integrity({
                "PRICE": {"off_grid": 0, "grid_gaps": 1},
                "OI": {"off_grid": 0, "grid_gaps": 0},
            })


if __name__ == "__main__":
    unittest.main()

    def test_checksum_delimiter_is_literal_backslash_n(self):
        # PostgreSQL must hash rows separated by the two characters \\ and n,
        # matching the independently verified baseline checksum convention.
        self.assertEqual(CHECKSUM_DELIMITER_SQL, "E'\\\\n'")
