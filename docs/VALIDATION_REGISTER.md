# Validation Register

This register records evidence without mutating the source records. A green workflow run is not interchangeable with an accepted market-session calculation.

## 1. Historical parity

**Status:** COMPLETED, with conditional session-assignment qualification.

- Reference inventory: **183 completed profiles** and **8,113 TPO rows** (including six zero-count rows).
- Accepted historical parity comparison: all 183 profiles and 8,113 rows compared; **zero reported mismatches**.
- Compared profile fields include completeness, candle coverage, total TPOs, POC bounds/count, VAH/VAL bounds and value-area count.
- Row-level comparison includes row bounds, TPO count, POC flag and value-area flag.
- The parity utility uses read-only transactions on both data connections and reports zero writes to live and reference branches.
- Historical session assignment remains **CONDITIONAL**. Matching timestamps and replaying the stored reference does not independently prove whether Delta timestamps are candle-open or candle-close times.

Implementation reference: [parity utility commit 5e55c3ea](https://github.com/shashibangera-spec/delta-milestone1-verifier/commit/5e55c3ea8adbfc87907d0225d4d006a38746900b).

### Actions runs — do not confuse CI with the historical calculation

- [Run 44992010613](https://github.com/shashibangera-spec/delta-milestone1-verifier/actions/runs/44992010613) — workflow conclusion SUCCESS on 22 Nov 2026, feature SHA `2e14ce2736899a3ad6aa9452bcaecaea3f379c7a`. The **Offline parity tests (no database credentials)** job succeeded; the **Database connection identity preflight (read-only)** job succeeded; the **Historical parity (read-only)** job was **SKIPPED**. Thus the offline tests and read-only identity preflight ran, but the actual historical parity calculation did not run in this Actions execution.
- [Run 44991282590](https://github.com/shashibangera-spec/delta-milestone1-verifier/actions/runs/44991282590) — same distinction: offline parity tests and read-only identity preflight succeeded; historical parity job **SKIPPED**. It is not a historical calculation run.

The accepted historical parity result remains complete and immutable based on its separately retained evidence. The two Actions runs above are not cited as execution evidence for that calculation. Do not rerun or reopen historical parity as part of routine documentation maintenance.

## 2. Accepted daily profiles

| Session | Status | Preservation rule |
|---|---|---|
| 20 Nov 2026 | **ACCEPTED / IMMUTABLE** | Preserve the accepted profile, calculation record and fingerprint exactly. |
| 21 Nov 2026 | **PASS — ACCEPTED / IMMUTABLE** | Preserve the accepted PASS, profile, calculation record and fingerprint exactly. |

The accepted 20 and 21 November records are authoritative evidence. Their database IDs and fingerprints are not reproduced here because they are not available in the approved documentation context; do not invent them or replace them with inferred values.

### Daily workflow run 44988076116

[AMT Engine V1.0 daily research calculation — run 44988076116](https://github.com/shashibangera-spec/delta-milestone1-verifier/actions/runs/44988076116) completed SUCCESS.

- **Session date calculated:** 21 November 2026.
- **Execution date:** 22 November 2026.
- **Commit:** `030de5c293f1429680af14d74525b11c687c1b77`.
- The workflow's successful execution belongs to the 21 November session, not the 22 November session. The accepted 21 November PASS remains immutable; this run link must not be misrepresented as a calculation for the 22 November session.

## 3. 22 November 2026 session calculation

**Status: PENDING acceptance and validation.**

The 22 November session calculation is a separate scheduled validation. Do not mark it accepted based on run 44988076116: that run calculated the **21 November session** and was executed on 22 November. Before changing the 22 November session status, verify its own actual run, completed-session guard, run ID, revision/attempt, input fingerprint, persisted profile and TPO inventory, validation report, and explicit acceptance decision.

No verified run for the 22 November session is recorded here. This register intentionally leaves that session PENDING.

## 4. Offline CI and writer-boundary tests

[AMT Engine daily writer offline tests — run 44992010705](https://github.com/shashibangera-spec/delta-milestone1-verifier/actions/runs/44992010705)  
**Result:** SUCCESS, 22 Nov 2026. Commit: `2e14ce2736899a3ad6aa9452bcaecaea3f379c7a`. Workflow job: `offline-daily-writer-tests`.

Executed steps included compilation and `python -m unittest` for `tests/test_amt_engine_daily_job.py`, using offline fake connections/mocks only. Verified test cases:

- `test_success_writes_profile_rows_and_success_status_in_one_transaction`
- `test_rejected_input_records_attempt_without_profile_or_tpo_output`
- `test_output_failure_rolls_back_profile_and_tpo_then_marks_run_failed`
- `test_unchanged_input_is_retry_and_changed_input_is_restatement`
- `test_open_utc_session_is_rejected_before_calculation`
- `test_direct_process_call_rejects_open_session_before_identity_or_writes`
- `test_unexpected_runtime_identity_fails_closed_before_any_writes`
- `test_branch_and_hostname_guard_fails_closed`

The run used offline mocks; it did not dispatch the daily database-writing workflow. It verifies the tested code paths, not live database behavior.

Additional successful checks:
- [Daily unit tests run 44990466832](https://github.com/shashibangera-spec/delta-milestone1-verifier/actions/runs/44990466832) — SUCCESS.
- [Final branch verification run 44990466830](https://github.com/shashibangera-spec/delta-milestone1-verifier/actions/runs/44990466830) — SUCCESS.

## 5. Evidence interpretation

- **COMPLETED:** the specified calculation/test/review actually ran and its evidence is retained.
- **ACCEPTED:** the Product Owner/reviewer accepted the named record.
- **PENDING:** required calculation output or acceptance review has not been established.
- **CONDITIONAL:** result is valid only under a stated unresolved assumption.
- **UNVERIFIED:** the available evidence does not establish the claim.

Never convert a workflow SUCCESS into a market-data PASS without the session-specific record and validation evidence. Never overwrite accepted profiles or fingerprints.
