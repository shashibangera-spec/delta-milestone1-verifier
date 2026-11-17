import unittest
from continuous_collector import SLOT_SECONDS, EXPECTED_PRICE_ROWS, EXPECTED_OI_ROWS, EXPECTED_FEATURE_ROWS

class CollectorSafetyTests(unittest.TestCase):
    def test_grid_is_thirty_minutes(self):
        self.assertEqual(SLOT_SECONDS,1800)
    def test_baseline_guards_match_verified_neon_counts(self):
        self.assertEqual(EXPECTED_PRICE_ROWS,8641)
        self.assertEqual(EXPECTED_OI_ROWS,8641)
        self.assertEqual(EXPECTED_FEATURE_ROWS,1800)

if __name__=="__main__":
    unittest.main()
