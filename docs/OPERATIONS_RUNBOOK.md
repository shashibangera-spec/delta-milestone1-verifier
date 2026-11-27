# Operations Runbook — AMT Engine V1.0

This is a controlled procedure for an explicitly authorized daily calculation. It is not evidence that unattended operation is enabled or production-ready. Follow the current approved workflow and repository configuration; do not improvise credentials, targets or methodology.

## 1. Before a daily calculation

1. Confirm explicit authorization for the specific session and execution.
2. Confirm the target session is fully closed: UTC session `[00:00, next 00:00)`. The writer independently rejects an open session.
3. Confirm execution is on the approved feature branch `feat/amt-engine-daily-v1-corrected`; the workflow has a branch guard and verifies the checked-out branch.
4. Confirm required repository secret and target identifiers are configured through the approved process. Never print credentials or connection strings.
5. Confirm the intended Neon research project/branch/database/role. The writer checks project, branch, database, hostname and runtime identity.
6. Review the approved method specification. Do not change it during an operational run.

## 2. Calculation and validation sequence

The daily calculation workflow is manually dispatched. It is not a scheduled unattended service.

1. Workflow checks the approved ref and checks out the approved feature branch.
2. Python dependencies are installed.
3. Offline test suite runs before database execution.
4. Secret presence is checked without displaying its value.
5. The one-session job validates the UTC closed-session boundary.
6. Runtime database identity is checked on the same connection used for source reads and writes.
7. A per-session advisory lock prevents concurrent processing of the same session/method/source/symbol key.
8. The job reads Delta PRICE candles and provisional timestamps for the requested UTC session.
9. Input validation requires 48 unique exact 30-minute timestamps, valid finite OHLC, no off-grid/malformed/duplicate/missing/provisional rows.
10. If invalid, record the rejected attempt and do not write a final profile/TPO set.
11. If valid, calculate the deterministic profile and persist the profile plus all TPO rows transactionally.
12. Verify the returned run ID, session, revision/attempt, fingerprint, status, profile completeness and row inventory before considering acceptance.

## 3. Acceptance checklist

- [ ] Session date and UTC bounds are correct.
- [ ] Session was closed before calculation.
- [ ] Source, symbol, series type and resolution are Delta India / BTCUSD / PRICE / 30m.
- [ ] Exactly 48 valid candles; no missing, duplicate, off-grid, malformed or provisional timestamps.
- [ ] Input fingerprint is present and retained.
- [ ] Run ID, revision number, attempt number and execution status are captured.
- [ ] Profile is complete and expected/observed bar counts are 48/48.
- [ ] POC, VAH, VAL and TPO rows are consistent with the approved V1.0 specification.
- [ ] Persistence transaction completed successfully; profile and TPO output are atomic.
- [ ] Independent review/acceptance is recorded before the register is changed to PASS/ACCEPTED.

A green Actions result alone is not a session acceptance.

## 4. Failure handling

- **Open session:** stop. Do not bypass the guard or change timestamps to force execution.
- **Wrong branch/target/role/hostname:** stop; do not retry against another database or branch.
- **Missing, duplicate, off-grid, malformed, invalid or provisional input:** retain the rejected validation evidence; do not create a final profile.
- **Fingerprint unavailable:** preserve NULL and investigate; never fabricate a fingerprint.
- **Output persistence failure:** the profile, TPO rows and in-transaction success status must roll back together; only the separate FAILED audit status may remain.
- **Unexpected runtime identity:** fail closed before any writes.
- **CI failure:** inspect the failed job/log and fix only under separate code-change authorization. Do not dispatch the daily writer as a substitute for offline testing.
- **Unclear result:** mark PENDING or UNVERIFIED. Do not infer PASS from partial logs.

Do not rerun a session that already has an accepted record without explicit restatement authorization. Preserve the original record and fingerprint.

## 5. Evidence preservation

For every authorized run, retain:
- GitHub Actions run URL and workflow name;
- branch and exact commit SHA;
- UTC session date and execution timestamp;
- run ID, revision, attempt and execution status;
- input fingerprint and validation report;
- profile values and TPO row count;
- explicit reviewer acceptance or rejection.

Accepted 20 and 21 November profiles and historical parity evidence are immutable. Do not update them in place. Any correction/restatement requires explicit authorization and a separately documented new revision.

## 6. Operational scope

No automatic scheduling or unattended operation is asserted here. The daily workflow is manually dispatched and gated. No changes to production collectors, dashboards, Pine Script, external repositories, Neon schema or production configuration are authorized by this runbook.
