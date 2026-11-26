import unittest
from unittest.mock import patch

from amt_engine.playbook_v13_shadow_logger import (
    SOURCE_HOST,
    ShadowLoggerError,
    _connect_ro,
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


if __name__ == "__main__":
    unittest.main()
