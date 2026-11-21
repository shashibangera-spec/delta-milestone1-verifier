import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from amt_engine.daily import (
    BAR_SECONDS, EXPECTED_BARS, ROW_SIZE, Candle, assign_revision_attempt,
    calculate_profile, session_bounds, validate_session,
)


class DailyEngineTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 11, 19)
        self.start, _ = session_bounds(self.day)

    def rows(self, low=Decimal('100'), high=Decimal('200')):
        result = []
        for i in range(EXPECTED_BARS):
            ts = self.start + timedelta(seconds=i * BAR_SECONDS)
            result.append({'candle_time': ts, 'open_value': '150', 'high_value': str(high),
                           'low_value': str(low), 'close_value': '150'})
        return result

    def test_complete_session_validates_and_fingerprints(self):
        result = validate_session(self.day, self.rows())
        self.assertTrue(result.valid)
        self.assertEqual(len(result.candles), 48)
        self.assertEqual(len(result.input_fingerprint), 64)

    def test_fingerprint_normalizes_decimal_scale_and_identifies_price_series(self):
        from amt_engine.daily import _canonical_fingerprint
        ts = self.start
        a = [Candle(ts, Decimal("1.0"), Decimal("2.00"), Decimal("0.00"), Decimal("1.000"))]
        b = [Candle(ts, Decimal("1"), Decimal("2"), Decimal("0"), Decimal("1"))]
        self.assertEqual(_canonical_fingerprint(a), _canonical_fingerprint(b))

    def test_missing_candle_rejected_without_fingerprint(self):
        result = validate_session(self.day, self.rows()[:-1])
        self.assertFalse(result.valid)
        self.assertIsNone(result.input_fingerprint)
        self.assertEqual(len(result.report['missing_timestamps']), 1)

    def test_duplicate_timestamp_rejected(self):
        rows = self.rows(); rows.append(dict(rows[0]))
        result = validate_session(self.day, rows)
        self.assertFalse(result.valid)
        self.assertEqual(len(result.report['duplicate_timestamps']), 1)
        self.assertIsNone(result.input_fingerprint)

    def test_invalid_ohlc_rejected(self):
        rows = self.rows(); rows[0]['high_value'] = '120'; rows[0]['low_value'] = '130'
        result = validate_session(self.day, rows)
        self.assertFalse(result.valid)
        self.assertEqual(len(result.report['invalid_ohlc']), 1)

    def test_provisional_record_blocks_final_profile(self):
        ts = self.start + timedelta(minutes=30)
        result = validate_session(self.day, self.rows(), [ts])
        self.assertFalse(result.valid)
        self.assertIsNone(result.input_fingerprint)

    def test_off_grid_timestamp_rejected(self):
        rows = self.rows(); rows[0]['candle_time'] += timedelta(minutes=1)
        result = validate_session(self.day, rows)
        self.assertFalse(result.valid)
        self.assertGreater(result.report['off_grid_rows'], 0)

    def test_ohlc_nan_rejected(self):
        rows = self.rows(); rows[0]['open_value'] = 'NaN'
        result = validate_session(self.day, rows)
        self.assertFalse(result.valid)

    def test_grid_is_zero_origin_and_width_50(self):
        validated = validate_session(self.day, self.rows(Decimal('101'), Decimal('199')))
        profile, rows = calculate_profile(self.day, validated.candles)
        self.assertTrue(all(r.row_lower % ROW_SIZE == 0 for r in rows))
        self.assertTrue(all(r.row_upper - r.row_lower == ROW_SIZE for r in rows))
        self.assertEqual(rows[0].row_lower, Decimal('100'))
        self.assertEqual(rows[-1].row_upper, Decimal('200'))

    def test_exact_price_boundary_belongs_to_higher_bucket(self):
        validated = validate_session(self.day, self.rows(Decimal('100'), Decimal('150')))
        _, rows = calculate_profile(self.day, validated.candles)
        self.assertEqual([r.row_lower for r in rows], [Decimal('100'), Decimal('150')])

    def test_option_a_persists_zero_count_candidates(self):
        raw = self.rows(Decimal('0'), Decimal('50'))
        for row in raw[:24]:
            row['open_value'] = '25'
            row['close_value'] = '25'
        for row in raw[24:]:
            row['low_value'] = '450'
            row['high_value'] = '500'
            row['open_value'] = '475'
            row['close_value'] = '475'
        validated = validate_session(self.day, raw)
        profile, rows = calculate_profile(self.day, validated.candles)
        self.assertTrue(any(r.tpo_count == 0 for r in rows))
        self.assertTrue(all(r.tpo_count >= 0 for r in rows))
        self.assertEqual(len(rows), 11)
        self.assertEqual(sum(r.tpo_count for r in rows), profile.total_tpos)

    def test_poc_and_va_ties_choose_lower_price(self):
        raw = self.rows(Decimal('0'), Decimal('100'))
        for row in raw:
            row['open_value'] = '50'
            row['close_value'] = '50'
        validated = validate_session(self.day, raw)
        profile, rows = calculate_profile(self.day, validated.candles)
        self.assertEqual(profile.poc_lower, Decimal('0'))
        self.assertTrue(rows[0].is_value_area)

    def test_failed_retry_does_not_increment_revision(self):
        latest = {'revision_number': 3, 'input_fingerprint': 'a' * 64}
        prior = [{'revision_number': 3, 'attempt_number': 1}, {'revision_number': 3, 'attempt_number': 2}]
        self.assertEqual(assign_revision_attempt(latest, prior, 'a' * 64), (3, 3))

    def test_changed_successful_input_increments_revision(self):
        latest = {'revision_number': 3, 'input_fingerprint': 'a' * 64}
        prior = [{'revision_number': 3, 'attempt_number': 1}]
        self.assertEqual(assign_revision_attempt(latest, prior, 'b' * 64), (4, 1))

    def test_unavailable_fingerprint_is_not_fabricated(self):
        latest = {'revision_number': 3, 'input_fingerprint': 'a' * 64}
        prior = [{'revision_number': 3, 'attempt_number': 1}]
        self.assertEqual(assign_revision_attempt(latest, prior, None), (3, 2))


if __name__ == '__main__':
    unittest.main()
