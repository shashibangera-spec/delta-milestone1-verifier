import unittest
from datetime import datetime, timezone

from observer_v1_model import build_observer_view_model


class ObserverV1PresentationModelTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 11, 22, tzinfo=timezone.utc)

    def test_fixed_five_field_contract_and_exact_unverified_states(self):
        result = build_observer_view_model(
            session_start=self.start, is_live=True, latest_price=None,
            prior_profile=None, developing_profile=None,
            price_sequence={"contiguous": False}, confirmed_price_count=0,
        )
        self.assertEqual(
            list(result.keys()),
            ["session_start", "session_mode", "current_auction_condition",
             "price_location", "value_development", "latest_confirmed_event", "data_quality"],
        )
        self.assertEqual(result["current_auction_condition"]["value"], "NOT VERIFIED")
        self.assertEqual(result["latest_confirmed_event"]["value"], "NO VERIFIED CONFIRMED EVENT")
        self.assertEqual([x["name"] for x in result["data_quality"]], [
            "Candle Continuity", "Source Finality", "Profile Completeness", "Calculation Validation"
        ])

    def test_raw_price_and_prior_profile_are_presented_without_classification(self):
        result = build_observer_view_model(
            session_start=self.start, is_live=True,
            latest_price={"close_value": 62123.5, "candle_time": self.start},
            prior_profile={"VAL": 60000, "POC": 61000, "VAH": 62000},
            developing_profile={"VAL": 60500, "POC": 61500, "VAH": 62500},
            price_sequence={"contiguous": True}, confirmed_price_count=8,
        )
        self.assertEqual(result["price_location"]["current_price"], "$62,123.50")
        self.assertEqual(result["price_location"]["prior_profile"]["POC"], "$61,000.00")
        self.assertNotIn("classification", result["price_location"])
        self.assertEqual(result["data_quality"][0]["status"], "VALID")
        self.assertEqual(result["data_quality"][2]["status"], "PENDING")
        self.assertEqual(result["data_quality"][1]["status"], "NOT VERIFIED")
        self.assertEqual(result["data_quality"][3]["status"], "NOT VERIFIED")

    def test_non_contiguous_sequence_is_insufficient_evidence(self):
        result = build_observer_view_model(
            session_start=self.start, is_live=True, latest_price=None,
            prior_profile=None, developing_profile=None,
            price_sequence={"contiguous": False, "missing": 1, "duplicates": 0, "invalid": 0, "off_grid": 0},
            confirmed_price_count=5,
        )
        self.assertEqual(result["data_quality"][0]["status"], "INSUFFICIENT EVIDENCE")
        self.assertIn("1 missing", result["data_quality"][0]["detail"])

    def test_completed_profile_completeness_requires_profile_output(self):
        complete = build_observer_view_model(
            session_start=self.start, is_live=False, latest_price=None,
            prior_profile=None, developing_profile={"VAL": 1, "POC": 2, "VAH": 3},
            price_sequence={"contiguous": True}, confirmed_price_count=48,
        )
        incomplete = build_observer_view_model(
            session_start=self.start, is_live=False, latest_price=None,
            prior_profile=None, developing_profile=None,
            price_sequence={"contiguous": False}, confirmed_price_count=47,
        )
        self.assertEqual(complete["data_quality"][2]["status"], "VALID")
        self.assertEqual(incomplete["data_quality"][2]["status"], "INSUFFICIENT EVIDENCE")

    def test_live_profile_is_pending_even_when_prefix_is_valid(self):
        result = build_observer_view_model(
            session_start=self.start, is_live=True, latest_price=None,
            prior_profile=None, developing_profile={"VAL": 1, "POC": 2, "VAH": 3},
            price_sequence={"contiguous": True}, confirmed_price_count=17,
        )
        self.assertEqual(result["data_quality"][2]["status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
