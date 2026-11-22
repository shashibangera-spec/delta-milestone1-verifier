# Controlled live validation — AMT Engine V1.0 developing dashboard

## Gate and scope

This checklist applies only after separate Product Owner approval to merge and deploy PR #12 to the isolated PR #3 Railway dashboard. Until then, validation is offline/read-only only. No merge, deployment, collector change, production BTC dashboard change, schema change, database write, historical-record mutation, or methodology change is authorized by this checklist.

The dashboard remains SELECT-only and its developing values remain research outputs.

## Status vocabulary (must remain distinct)

1. **Input validation: PASS** — the observed confirmed PRICE candle sequence has the required timestamps and valid OHLC. For a completed session, all 48 exact 30m slots must be present. For a developing session, only a contiguous prefix beginning 00:00 UTC / 05:30 IST is valid.
2. **Profile calculation: DEVELOPING / COMPLETE** — POC, VAH and VAL have been calculated from the input that passed validation using the approved V1.0 rules. A developing result is interim research output.
3. **Daily AMT Engine acceptance: ACCEPTED / NOT ACCEPTED** — this is a separate authoritative daily-record status. The dashboard does not read the daily acceptance register. It must continue to display **NOT VERIFIED — NOT ACCEPTED** for its prior profile and must not infer acceptance from successful input validation or calculation.

## Live observations after approved deployment

### A. Confirmed candle arrival and refresh

- Record the session date, UTC/IST reset, dashboard refresh time and latest confirmed PRICE candle timestamp.
- Compare the timestamp and OHLC with a read-only SELECT from `research.delta_candles` for `delta_india / 30m / PRICE / BTCUSD`.
- Confirm the dashboard profile changes when a new confirmed candle is committed and visible after the dashboard's 45-second cache/refresh cycle.
- Record the prior and new confirmed bracket counts, POC, VAH and VAL. Do not expect an update at the exact candle boundary; collector finalization and refresh are asynchronous.

### B. Provisional exclusion

- Identify the current in-progress slot in `research.delta_candles_provisional`.
- Confirm it appears only in the provisional/incomplete display.
- Confirm the confirmed bracket count, TPO total and POC/VAH/VAL do not include it.
- When that slot is promoted to the confirmed table after completion, verify the profile changes only then.

### C. Fail-closed behaviour

- Do not inject malformed rows into any live or production table.
- Use the committed offline fixtures/tests for missing middle slot, duplicate timestamp, off-grid timestamp, invalid OHLC and non-prefix/interrupted sequence.
- During live observation, if a real sequence gap, duplicate or invalid row is encountered, verify the dashboard withholds the developing profile and reports the validation failure; do not repair or skip the row in the dashboard.

### D. Independent calculation

For each captured confirmed PRICE snapshot, independently reconstruct the profile with exact Decimal arithmetic:
- Zero-origin $50 buckets; each candle contributes one TPO to every bucket touched by its low-to-high range, inclusive.
- POC is the highest-count row; ties choose the lower-price row.
- Value-area target is ceiling(70% of total TPOs).
- Expand one adjacent row at a time from POC; compare adjacent counts, choose the higher count, and choose the lower-price candidate on ties.
- Zero-count intervening rows remain valid candidates; continue until the target is met or the occupied profile boundary is reached.
- Compare POC lower bound, VAL lower bound and VAH upper bound exactly, plus TPO total and occupied row count.

Retain the raw confirmed candle snapshot, query time, independent calculation output and dashboard capture together as evidence.

### E. Session-close reconciliation

- Wait until exactly 48 confirmed 30m PRICE candles for the session are present and the sequence passes the completed-session validator.
- Capture the final developing POC/VAH/VAL and the dashboard's completed-session profile.
- Independently compare those levels with the accepted daily AMT Engine V1.0 record for the same session date, including its input fingerprint and acceptance status.
- Record any difference and the known timestamp/open-vs-close session-assignment qualification. Do not reinterpret or reopen historical parity based on this single live validation.
- Even if the numbers match, the dashboard label remains **DAILY AMT ENGINE ACCEPTANCE: NOT VERIFIED — NOT ACCEPTED** unless a later separately authorized integration verifies the matching acceptance-register record.

## Evidence and stop conditions

The validation report must include timestamps, source branch/environment, confirmed/provisional row counts, exact profile values, independent Decimal outputs, daily accepted record reference/fingerprint and any timestamp qualification.

Stop and report a blocker if the confirmed feed is stale, sequence integrity fails, provisional data contaminates the confirmed calculation, independent values differ, the accepted daily record is missing/unavailable, or the deployed dashboard cannot be proven to use the intended read-only role and isolated service.

No changes to collector, database/schema, daily writer, accepted records, existing production BTC dashboard or approved methodology are part of this validation.
