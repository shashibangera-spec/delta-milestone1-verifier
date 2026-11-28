import unittest
from datetime import datetime, timezone

from continuous_collector import (
    SLOT_SECONDS,
    next_scheduled_wake,
    expected_latest_candle_open,
    retry_deadline_for,
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

    def test_collector_wakes_at_next_utc_02_or_32_boundary(self):
        cases = [
            (datetime(2026, 11, 28, 0, 1, 59, tzinfo=timezone.utc), datetime(2026, 11, 28, 0, 2, tzinfo=timezone.utc)),
            (datetime(2026, 11, 28, 0, 2, tzinfo=timezone.utc), datetime(2026, 11, 28, 0, 32, tzinfo=timezone.utc)),
            (datetime(2026, 11, 28, 0, 31, 59, tzinfo=timezone.utc), datetime(2026, 11, 28, 0, 32, tzinfo=timezone.utc)),
            (datetime(2026, 11, 28, 0, 32, tzinfo=timezone.utc), datetime(2026, 11, 28, 1, 2, tzinfo=timezone.utc)),
            (datetime(2026, 11, 28, 23, 40, tzinfo=timezone.utc), datetime(2026, 11, 29, 0, 2, tzinfo=timezone.utc)),
        ]
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(next_scheduled_wake(now), expected)

    def test_expected_latest_candle_is_last_fully_closed_slot(self):
        self.assertEqual(
            expected_latest_candle_open(datetime(2026, 11, 28, 0, 2, tzinfo=timezone.utc)),
            int(datetime(2026, 11, 27, 23, 30, tzinfo=timezone.utc).timestamp()),
        )
        self.assertEqual(
            expected_latest_candle_open(datetime(2026, 11, 28, 0, 32, tzinfo=timezone.utc)),
            int(datetime(2026, 11, 28, 0, 0, tzinfo=timezone.utc).timestamp()),
        )

    def test_collector_retries_stop_before_playbook_run(self):
        self.assertEqual(
            retry_deadline_for(datetime(2026, 11, 28, 0, 2, tzinfo=timezone.utc)),
            datetime(2026, 11, 28, 0, 6, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            retry_deadline_for(datetime(2026, 11, 28, 0, 32, tzinfo=timezone.utc)),
            datetime(2026, 11, 28, 0, 36, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            retry_deadline_for(datetime(2026, 11, 28, 0, 7, tzinfo=timezone.utc)),
            datetime(2026, 11, 28, 0, 7, tzinfo=timezone.utc),
        )

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

    def test_checksum_delimiter_uses_literal_backslash_n_in_sql(self):
        import inspect
        import continuous_collector

        source = inspect.getsource(continuous_collector.baseline_snapshot)
        self.assertIn("E'\\\\\\\\n'", source)


if __name__ == "__main__":
    unittest.main()



class CollectorPairPersistenceTests(unittest.TestCase):
    class FakeCursor:
        def __init__(self, pair_count):
            self.pair_count = pair_count
            self.sql = None
            self.params = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params):
            self.sql = sql
            self.params = params

        def fetchone(self):
            return {"paired_series_count": self.pair_count}

    class FakeConnection:
        def __init__(self, pair_count):
            self.fake_cursor = CollectorPairPersistenceTests.FakeCursor(pair_count)

        def cursor(self):
            return self.fake_cursor

    def test_candle_pair_ready_requires_exact_price_and_oi_timestamp(self):
        from continuous_collector import latest_pair_covers

        expected = int(datetime(2026, 11, 28, 0, 0, tzinfo=timezone.utc).timestamp())
        conn = self.FakeConnection(2)
        self.assertTrue(latest_pair_covers(conn, expected))
        self.assertIn("COUNT(DISTINCT series_type)", conn.fake_cursor.sql)
        self.assertEqual(conn.fake_cursor.params[0], datetime(2026, 11, 28, 0, 0, tzinfo=timezone.utc))

    def test_candle_pair_not_ready_when_either_series_is_missing(self):
        from continuous_collector import latest_pair_covers

        expected = int(datetime(2026, 11, 28, 0, 0, tzinfo=timezone.utc).timestamp())
        self.assertFalse(latest_pair_covers(self.FakeConnection(1), expected))
        self.assertFalse(latest_pair_covers(self.FakeConnection(0), expected))


def test_options_collection_failure_is_isolated_from_core_cycle():
    import continuous_collector

    def fail(_database_url):
        raise RuntimeError("simulated options API outage")

    assert continuous_collector.collect_options_safely("postgresql://unused", collector=fail) is False
