"""Read-only historical parity checker. Never writes to either Neon branch."""
from __future__ import annotations

import json
import os
from datetime import datetime, time, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from amt_engine.daily import (
    SOURCE, SYMBOL, RESOLUTION, validate_session, calculate_profile,
)

LIVE_URL = os.environ.get("LIVE_DATABASE_URL")
REFERENCE_URL = os.environ.get("REFERENCE_DATABASE_URL")
EXPECTED_PROFILES = 183
EXPECTED_TPO_ROWS = 8113


class ParityPreflightError(RuntimeError):
    """Raised with every invalid historical session; comparison must not start."""


def _connect_readonly(url):
    if not url:
        raise RuntimeError("Both LIVE_DATABASE_URL and REFERENCE_DATABASE_URL are required")
    return psycopg.connect(
        url, options="-c default_transaction_read_only=on", row_factory=dict_row
    )


def validate_all_reference_sessions(profiles, fetch_inputs):
    """Validate every reference session before allowing any parity comparison.

    fetch_inputs(day) returns (raw_price_rows, provisional_timestamps).
    Returns validated sessions keyed by date, or raises once with all failures.
    """
    validated_by_date = {}
    affected = []
    for reference_profile in profiles:
        day = reference_profile["session_date"]
        raw, provisional = fetch_inputs(day)
        validation = validate_session(day, raw, provisional)
        if not validation.valid:
            affected.append({
                "session_date": day.isoformat(),
                "reasons": validation.report,
            })
        else:
            validated_by_date[day] = validation

    if affected:
        raise ParityPreflightError(json.dumps({
            "message": "Historical parity stopped: one or more reference sessions have invalid PRICE inputs.",
            "affected_sessions": affected,
            "affected_session_count": len(affected),
            "comparison_started": False,
        }, sort_keys=True))
    return validated_by_date


def _profile_values(profile):
    return {
        "expected_bars": profile.expected_bars,
        "observed_bars": profile.observed_bars,
        "is_complete": profile.is_complete,
        "missing_candle_count": profile.missing_candle_count,
        "first_candle": profile.first_candle,
        "last_candle": profile.last_candle,
        "total_tpos": profile.total_tpos,
        "poc_lower": profile.poc_lower,
        "poc_upper": profile.poc_upper,
        "poc_tpo_count": profile.poc_tpo_count,
        "vah_lower": profile.vah_lower,
        "vah_upper": profile.vah_upper,
        "val_lower": profile.val_lower,
        "val_upper": profile.val_upper,
        "value_area_tpos": profile.value_area_tpos,
    }


def compare_session(reference_profile, reference_rows, calculated_profile, calculated_rows):
    """Return every profile-field and row-level difference for one session."""
    day = reference_profile["session_date"]
    mismatches = []
    for field, actual in _profile_values(calculated_profile).items():
        expected = reference_profile[field]
        if actual != expected:
            mismatches.append({
                "session_date": day.isoformat(), "kind": "PROFILE_FIELD",
                "field": field, "expected": str(expected), "actual": str(actual),
            })

    expected_map = {row["row_lower"]: row for row in reference_rows}
    actual_map = {row.row_lower: row for row in calculated_rows}
    for key in sorted(set(expected_map) - set(actual_map)):
        mismatches.append({
            "session_date": day.isoformat(), "kind": "MISSING_TPO_ROW",
            "row_lower": str(key), "expected": dict(expected_map[key]), "actual": None,
        })
    for key in sorted(set(actual_map) - set(expected_map)):
        row = actual_map[key]
        mismatches.append({
            "session_date": day.isoformat(), "kind": "UNEXPECTED_TPO_ROW",
            "row_lower": str(key), "expected": None,
            "actual": {
                "row_lower": str(row.row_lower), "row_upper": str(row.row_upper),
                "tpo_count": row.tpo_count, "is_poc": row.is_poc,
                "is_value_area": row.is_value_area,
            },
        })
    for key in sorted(set(actual_map) & set(expected_map)):
        actual_row, expected_row = actual_map[key], expected_map[key]
        for field, actual in (
            ("row_upper", actual_row.row_upper),
            ("tpo_count", actual_row.tpo_count),
            ("is_poc", actual_row.is_poc),
            ("is_value_area", actual_row.is_value_area),
        ):
            expected = expected_row[field]
            if actual != expected:
                mismatches.append({
                    "session_date": day.isoformat(), "kind": "TPO_FIELD",
                    "row_lower": str(key), "field": field,
                    "expected": str(expected), "actual": str(actual),
                })
    return mismatches


def run_parity():
    mismatches = []
    with _connect_readonly(LIVE_URL) as live, _connect_readonly(REFERENCE_URL) as reference:
        with reference.cursor() as cur:
            cur.execute(
                "SELECT * FROM amt_engine.session_profiles "
                "WHERE is_complete = true ORDER BY session_date"
            )
            profiles = cur.fetchall()
            cur.execute(
                "SELECT * FROM amt_engine.tpo_rows ORDER BY session_date,row_lower"
            )
            reference_rows = cur.fetchall()

        if len(profiles) != EXPECTED_PROFILES or len(reference_rows) != EXPECTED_TPO_ROWS:
            raise RuntimeError(
                f"Reference inventory mismatch: profiles={len(profiles)}, "
                f"rows={len(reference_rows)}; expected {EXPECTED_PROFILES} and {EXPECTED_TPO_ROWS}"
            )

        rows_by_date = {}
        for row in reference_rows:
            rows_by_date.setdefault(row["session_date"], []).append(row)

        def fetch_inputs(day):
            start_utc = datetime.combine(day, time.min, tzinfo=timezone.utc)
            end_utc = start_utc + timedelta(days=1)
            with live.cursor() as cur:
                cur.execute(
                    """SELECT candle_time,open_value,high_value,low_value,close_value
                       FROM research.delta_candles
                       WHERE source=%s AND symbol=%s AND series_type='PRICE' AND resolution=%s
                         AND candle_time >= %s AND candle_time < %s
                       ORDER BY candle_time""",
                    (SOURCE, SYMBOL, RESOLUTION, start_utc, end_utc),
                )
                raw = cur.fetchall()
                cur.execute(
                    """SELECT candle_time FROM research.delta_candles_provisional
                       WHERE source=%s AND symbol=%s AND series_type='PRICE' AND resolution=%s
                         AND candle_time >= %s AND candle_time < %s""",
                    (SOURCE, SYMBOL, RESOLUTION, start_utc, end_utc),
                )
                provisional = [row["candle_time"] for row in cur.fetchall()]
            return raw, provisional

        # Complete all 183 input checks before calculating or comparing even one profile.
        validated_by_date = validate_all_reference_sessions(profiles, fetch_inputs)

        calculated_profiles = 0
        calculated_rows = 0
        for reference_profile in profiles:
            day = reference_profile["session_date"]
            calculated_profile, calculated_tpo_rows = calculate_profile(
                day, validated_by_date[day].candles
            )
            calculated_profiles += 1
            calculated_rows += len(calculated_tpo_rows)
            mismatches.extend(compare_session(
                reference_profile, rows_by_date.get(day, []),
                calculated_profile, calculated_tpo_rows,
            ))

        report = {
            "reference_profiles": len(profiles),
            "reference_tpo_rows": len(reference_rows),
            "preflight_validated_profiles": len(validated_by_date),
            "calculated_profiles": calculated_profiles,
            "calculated_tpo_rows": calculated_rows,
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
            "historical_session_assignment": (
                "CONDITIONAL — parity does not independently prove source session assignment"
            ),
            "reference_branch_write_count": 0,
            "live_branch_write_count": 0,
        }
        # No truncation: serialize the complete mismatch collection.
        print(json.dumps(report, default=str, sort_keys=True, indent=2))
        return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(run_parity())
