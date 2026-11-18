import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from session_selection import (
    LIVE_SESSION_LABEL,
    SESSION_SELECTOR_KEY,
    normalize_session_selection,
    return_to_live_session,
)


class SessionSelectionStateTests(unittest.TestCase):
    def test_live_is_the_default(self):
        state = {}
        selected = normalize_session_selection(
            state, [LIVE_SESSION_LABEL, "2026-11-17"]
        )
        self.assertEqual(selected, LIVE_SESSION_LABEL)
        self.assertEqual(state[SESSION_SELECTOR_KEY], LIVE_SESSION_LABEL)

    def test_historical_selection_is_preserved(self):
        state = {SESSION_SELECTOR_KEY: "2026-11-17"}
        selected = normalize_session_selection(
            state, [LIVE_SESSION_LABEL, "2026-11-17"]
        )
        self.assertEqual(selected, "2026-11-17")

    def test_custom_range_does_not_change_session_selection(self):
        state = {
            SESSION_SELECTOR_KEY: "2026-11-17",
            "custom_auction_date_range": ("2026-11-10", "2026-11-17"),
        }
        normalize_session_selection(state, [LIVE_SESSION_LABEL, "2026-11-17"])
        self.assertEqual(state[SESSION_SELECTOR_KEY], "2026-11-17")
        self.assertEqual(
            state["custom_auction_date_range"],
            ("2026-11-10", "2026-11-17"),
        )

    def test_return_to_live_callback_sets_live_value(self):
        fake_streamlit = types.SimpleNamespace(
            session_state={SESSION_SELECTOR_KEY: "2026-11-17"}
        )
        with patch.dict(sys.modules, {"streamlit": fake_streamlit}):
            return_to_live_session()
        self.assertEqual(
            fake_streamlit.session_state[SESSION_SELECTOR_KEY],
            LIVE_SESSION_LABEL,
        )

    def test_removed_historical_option_falls_back_to_live(self):
        state = {SESSION_SELECTOR_KEY: "2026-11-16"}
        selected = normalize_session_selection(state, [LIVE_SESSION_LABEL])
        self.assertEqual(selected, LIVE_SESSION_LABEL)

    def test_dashboard_keeps_live_refresh_and_separate_custom_range(self):
        app_path = Path(__file__).with_name("app.py")
        source = app_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertIn('key="session_date_selector"', source)
        self.assertIn('key="return_to_live_session"', source)
        self.assertIn("on_click=return_to_live_session", source)
        self.assertIn('key="custom_auction_date_range"', source)
        self.assertIn('st_autorefresh(interval=45_000, key="dashboard_auto_refresh")', source)
        # The existing refresh remains conditional on live mode only.
        refresh_if = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "is_live"
            and any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "st_autorefresh"
                for child in ast.walk(node)
            )
        ]
        self.assertTrue(refresh_if)


if __name__ == "__main__":
    unittest.main()
