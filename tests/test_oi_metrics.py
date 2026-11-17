import unittest

from oi_metrics import (
    CONTRACT_VALUE_BTC,
    candle_validation_status,
    contracts_to_btc,
)


class OIMetricsTests(unittest.TestCase):
    def test_delta_btcusd_contract_value(self):
        self.assertEqual(CONTRACT_VALUE_BTC, 0.001)

    def test_contract_counts_convert_to_btc(self):
        self.assertAlmostEqual(contracts_to_btc(647113), 647.113, places=9)
        self.assertAlmostEqual(contracts_to_btc(653354), 653.354, places=9)

    def test_rest_range_comparison_uses_btc_units(self):
        stream_min_btc = contracts_to_btc(647113)
        rest_low_btc = 647.757
        self.assertLess(stream_min_btc, rest_low_btc)
        self.assertAlmostEqual(rest_low_btc - stream_min_btc, 0.644, places=9)

    def test_incomplete_candle_is_provisional(self):
        self.assertEqual(
            candle_validation_status(100, 700, 0, 1800),
            "PROVISIONAL_INCOMPLETE",
        )

    def test_fully_observed_candle_is_complete(self):
        self.assertEqual(
            candle_validation_status(0, 1800, 0, 1800),
            "COMPLETE_30M_OBSERVATION",
        )


if __name__ == "__main__":
    unittest.main()
