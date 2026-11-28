import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from amt_engine.playbook_v13 import evaluate_exit

from amt_engine.playbook_v13_shadow_logger import (
    SOURCE_HOST,
    ShadowLoggerError,
    _connect_ro,
    _is_contiguous_30m,
)


class FakeCursor:
    def __init__(self, identity):
        self.identity = identity
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement):
        self.statements.append(statement)

    def fetchone(self):
        return self.identity


class FakeConnection:
    def __init__(self, identity):
        self.fake_cursor = FakeCursor(identity)
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def close(self):
        self.closed = True


class SourceIdentityTests(unittest.TestCase):
    def test_source_identity_accepts_dict_row_for_direct_and_pooler_hosts(self):
        hosts = (
            SOURCE_HOST,
            SOURCE_HOST.replace(".c-", "-pooler.c-"),
        )
        for host in hosts:
            with self.subTest(host=host):
                connection = FakeConnection(
                    {
                        "database_name": "amt_research",
                        "current_user": "amt_dashboard_ro",
                        "session_user": "amt_dashboard_ro",
                    }
                )
                url = f"postgresql://amt_dashboard_ro:placeholder@{host}/amt_research"

                with patch(
                    "amt_engine.playbook_v13_shadow_logger.psycopg.connect",
                    return_value=connection,
                ):
                    result = _connect_ro(url, SOURCE_HOST, "Live collector source")

                self.assertIs(result, connection)
                self.assertFalse(connection.closed)
                self.assertIn(
                    "SET TRANSACTION READ ONLY",
                    connection.fake_cursor.statements,
                )

    def test_source_identity_rejects_wrong_role_and_closes_connection(self):
        connection = FakeConnection(
            {
                "database_name": "amt_research",
                "current_user": "writer_role",
                "session_user": "writer_role",
            }
        )
        url = (
            f"postgresql://amt_dashboard_ro:placeholder@"
            f"{SOURCE_HOST}/amt_research"
        )

        with patch(
            "amt_engine.playbook_v13_shadow_logger.psycopg.connect",
            return_value=connection,
        ):
            with self.assertRaisesRegex(ShadowLoggerError, "identity mismatch"):
                _connect_ro(url, SOURCE_HOST, "Live collector source")

        self.assertTrue(connection.closed)


class MidnightContinuityTests(unittest.TestCase):
    def _bar(self, timestamp):
        return {"candle_time": timestamp}

    def test_2330_to_0000_utc_is_contiguous(self):
        previous = self._bar(datetime(2026, 11, 26, 23, 30, tzinfo=timezone.utc))
        current = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(_is_contiguous_30m(previous, current))

    def test_open_trade_can_be_evaluated_on_midnight_candle(self):
        previous = self._bar(datetime(2026, 11, 26, 23, 30, tzinfo=timezone.utc))
        current_open = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)
        trade = {"side": "LONG", "stop_price": 99.0, "target_price": 103.0}
        candle = {"high": 101.0, "low": 98.0, "close": 99.5}
        self.assertTrue(_is_contiguous_30m(previous, current_open))
        self.assertEqual(evaluate_exit(trade, candle)["exit_reason"], "STOP")

    def test_genuine_30m_gap_is_not_contiguous(self):
        previous = self._bar(datetime(2026, 11, 26, 23, 0, tzinfo=timezone.utc))
        current = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(_is_contiguous_30m(previous, current))


if __name__ == "__main__":
    unittest.main()
