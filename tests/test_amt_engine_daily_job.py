"""Offline mocked tests for the guarded daily writer; never connect to Neon."""
import unittest
import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from amt_engine import daily_job
from amt_engine.daily import BAR_SECONDS, EXPECTED_BARS, Candle, session_bounds


DAY = date(2026, 11, 19)


def make_raw(count=EXPECTED_BARS):
    start, _ = session_bounds(DAY)
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


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []
        self.one = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        if "SELECT current_database() AS database_name" in sql:
            self.one = self.conn.identity
            self.rows = []
        elif "FROM research.delta_candles_provisional" in sql:
            self.rows, self.one = [], None
        elif "FROM research.delta_candles" in sql:
            self.rows, self.one = self.conn.raw, None
        elif "SELECT revision_number,input_fingerprint,run_id" in sql:
            self.rows, self.one = [], self.conn.latest_success
        elif "SELECT revision_number,attempt_number" in sql:
            self.rows, self.one = self.conn.prior_attempts, None
        elif "INSERT INTO amt_engine.calculation_runs" in sql:
            self.conn.run_inserts.append(params)
        elif "INSERT INTO amt_engine.daily_profiles" in sql:
            self.conn.profile_inserts.append(params)
        elif "UPDATE amt_engine.calculation_runs SET execution_status='REJECTED'" in sql:
            self.conn.status_updates.append(("REJECTED", params))
        elif "UPDATE amt_engine.calculation_runs SET execution_status='FAILED'" in sql:
            self.conn.status_updates.append(("FAILED", params))
        elif "UPDATE amt_engine.calculation_runs SET execution_status='SUCCEEDED'" in sql:
            self.conn.status_updates.append(("SUCCEEDED", params))
        self.last_sql = sql

    def executemany(self, sql, params):
        if self.conn.fail_tpo_insert:
            raise RuntimeError("simulated TPO insert failure")
        self.conn.tpo_inserts.extend(params)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one


class FakeConnection:
    def __init__(self, raw=None, latest_success=None, prior_attempts=None, fail_tpo_insert=False, identity=None):
        self.raw = make_raw() if raw is None else raw
        self.latest_success = latest_success
        self.prior_attempts = prior_attempts or []
        self.fail_tpo_insert = fail_tpo_insert
        self.identity = identity or {"database_name": "amt_research", "current_user": "amt_engine_writer", "session_user": "amt_engine_writer"}
        self.run_inserts = []
        self.profile_inserts = []
        self.tpo_inserts = []
        self.status_updates = []
        self.rollback_count = 0
        self.commit_count = 0

    def cursor(self, *args, **kwargs):
        return FakeCursor(self)

    def commit(self):
        self.commit_count += 1

    @contextmanager
    def transaction(self):
        profile_len = len(self.profile_inserts)
        tpo_len = len(self.tpo_inserts)
        try:
            yield
        except Exception:
            del self.profile_inserts[profile_len:]
            del self.tpo_inserts[tpo_len:]
            self.rollback_count += 1
            raise


class DailyWriterTests(unittest.TestCase):
    def test_success_writes_profile_rows_and_success_status_in_one_transaction(self):
        conn = FakeConnection()
        result = daily_job.process_session(conn, DAY)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(len(conn.profile_inserts), 1)
        self.assertGreater(len(conn.tpo_inserts), 0)
        self.assertEqual(conn.status_updates[-1][0], "SUCCEEDED")
        audit = json.loads(conn.run_inserts[0][19])["runtime_audit"]
        self.assertEqual(audit["current_user"], "amt_engine_writer")
        self.assertEqual(audit["session_user"], "amt_engine_writer")
        self.assertEqual(audit["neon_branch_id"], daily_job.EXPECTED_NEON_BRANCH_ID)
        self.assertTrue(audit["identity_verified"])
        self.assertEqual(result["runtime_audit"], audit)
        self.assertEqual(conn.rollback_count, 0)

    def test_rejected_input_records_attempt_without_profile_or_tpo_output(self):
        conn = FakeConnection(raw=make_raw(47))
        result = daily_job.process_session(conn, DAY)
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(conn.profile_inserts, [])
        self.assertEqual(conn.tpo_inserts, [])
        self.assertEqual(conn.status_updates[-1][0], "REJECTED")

    def test_output_failure_rolls_back_profile_and_tpo_then_marks_run_failed(self):
        conn = FakeConnection(fail_tpo_insert=True)
        with self.assertRaisesRegex(RuntimeError, "simulated TPO insert failure"):
            daily_job.process_session(conn, DAY)
        self.assertEqual(conn.profile_inserts, [])
        self.assertEqual(conn.tpo_inserts, [])
        self.assertEqual(conn.rollback_count, 1)
        self.assertEqual(conn.status_updates[-1][0], "FAILED")

    def test_unchanged_input_is_retry_and_changed_input_is_restatement(self):
        raw = make_raw()
        # Obtain the real deterministic fingerprint without any database access.
        from amt_engine.daily import validate_session
        fingerprint = validate_session(DAY, raw).input_fingerprint
        same = FakeConnection(
            raw=raw,
            latest_success={"revision_number": 2, "input_fingerprint": fingerprint, "run_id": "prior"},
            prior_attempts=[{"revision_number": 2, "attempt_number": 1}],
        )
        daily_job.process_session(same, DAY)
        self.assertEqual(same.run_inserts[0][6:9], (2, 2, "RETRY"))

        changed = FakeConnection(
            raw=raw,
            latest_success={"revision_number": 2, "input_fingerprint": "0" * 64, "run_id": "prior"},
            prior_attempts=[{"revision_number": 2, "attempt_number": 1}],
        )
        daily_job.process_session(changed, DAY)
        self.assertEqual(changed.run_inserts[0][6:9], (3, 1, "RESTATEMENT"))

    def test_open_utc_session_is_rejected_before_calculation(self):
        with self.assertRaisesRegex(RuntimeError, "not fully closed"):
            daily_job.validate_session_closed(date(2026, 11, 21), datetime(2026, 11, 21, 23, 59, tzinfo=timezone.utc))
        daily_job.validate_session_closed(date(2026, 11, 21), datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc))

    def test_unexpected_runtime_identity_fails_closed_before_any_writes(self):
        conn = FakeConnection(identity={"database_name": "amt_research", "current_user": "amt_research_owner", "session_user": "amt_engine_writer"})
        with self.assertRaisesRegex(RuntimeError, "Runtime database identity check failed"):
            daily_job.process_session(conn, DAY)
        self.assertEqual(conn.run_inserts, [])
        self.assertEqual(conn.profile_inserts, [])
        self.assertEqual(conn.tpo_inserts, [])

    def test_branch_and_hostname_guard_fails_closed(self):
        valid_url = "postgresql://user:pass@" + sorted(daily_job.EXPECTED_NEON_HOSTS)[0] + "/amt_research"
        daily_job.validate_target_environment(valid_url, daily_job.EXPECTED_NEON_PROJECT_ID,
                                              daily_job.EXPECTED_NEON_BRANCH_ID, daily_job.EXPECTED_DATABASE_NAME)
        with self.assertRaisesRegex(RuntimeError, "NEON_PROJECT_ID"):
            daily_job.validate_target_environment(valid_url, "wrong-project", daily_job.EXPECTED_NEON_BRANCH_ID, daily_job.EXPECTED_DATABASE_NAME)
        with self.assertRaisesRegex(RuntimeError, "NEON_DATABASE_NAME"):
            daily_job.validate_target_environment(valid_url, daily_job.EXPECTED_NEON_PROJECT_ID, daily_job.EXPECTED_NEON_BRANCH_ID, "wrong-db")
        with self.assertRaisesRegex(RuntimeError, "NEON_BRANCH_ID"):
            daily_job.validate_target_environment(valid_url, daily_job.EXPECTED_NEON_PROJECT_ID, "wrong-branch", daily_job.EXPECTED_DATABASE_NAME)
        with self.assertRaisesRegex(RuntimeError, "hostname"):
            daily_job.validate_target_environment("postgresql://user:pass@unapproved.example/db",
                                                  daily_job.EXPECTED_NEON_PROJECT_ID, daily_job.EXPECTED_NEON_BRANCH_ID, daily_job.EXPECTED_DATABASE_NAME)
        with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
            daily_job.validate_target_environment(None, daily_job.EXPECTED_NEON_PROJECT_ID, daily_job.EXPECTED_NEON_BRANCH_ID, daily_job.EXPECTED_DATABASE_NAME)


if __name__ == "__main__":
    unittest.main()
