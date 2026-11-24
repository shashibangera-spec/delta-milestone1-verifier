# Data Validation Status — Delta Milestone 1 Verifier

**Repository:** `shashibangera-spec/delta-milestone1-verifier`  
**Role:** Delta exchange data collection and milestone verification  
**Data/backend context:** Delta; Neon  
**Registry status:** Draft for review  
**Last inventory:** 2026-11-24  
**Source commit reviewed:** `a5701ba4468e989bde3fea9f4eeb1206cf3b1aa4`

## Status vocabulary

- **PASS** — exact check completed successfully with linked evidence.
- **CONDITIONAL** — evidence supports only the stated scope and qualifications.
- **OPEN** — unresolved finding or work item.
- **FAIL** — a check was run and failed.
- **NOT VERIFIED** — not checked in this validation.
- **SUPERSEDED** — replaced by a later linked baseline.

Never infer a successful CI run from a method note or test specification. Preserve exact source/data identity and the actual Actions URL for each executed validation.

## Accepted documented baselines

### DELTA-BASE-001 — Milestone 1 65-minute BTCUSD feed baseline
**Status: CONDITIONAL — historical feed evidence with explicit limitations**

The report `reports/MILESTONE1_BASELINE_65MIN.md` records an observation window of 3,900.1 seconds, from 2026-11-17 21:27:45.684 UTC to 22:32:45.742 UTC.

| Measure | Recorded result |
|---|---:|
| Railway deployment result | SUCCESS |
| WebSocket ticker messages | 774 |
| Ticker median interval | 5.032 s |
| Ticker mean interval | 5.040 s |
| Ticker maximum interval | 10.046 s |
| 30-minute candle updates | 3,264 |
| Reconnects | 1 |
| REST price candles | 145 |
| REST candles aligned to 1,800-second grid | 145 |
| Off-grid REST candles | 0 |
| Shared ticker/candle slots | 4 |

This supports basic feed availability/cadence during that observation window and alignment of the observed REST price candles to the 30-minute grid. The 00:00 UTC daily anchor corresponds to 05:30 IST.

**Qualifications**
- The deployment revision used for the report had a UTC-offset bug in fields labelled IST. Corrected source existed, but a corrected deployment and re-verification were still required.
- `oi[0]` was interpreted as OI contracts level and `oi[1]` as a 6-hour OI value change, not an OI level. The `oi[0]` min/max figures are not usable as validated OI-level evidence.
- No 30-minute OI OHLC series was validated.
- Candidate OI aggregation was explicitly marked `validated:false`.
- No comparison against historical `OI:BTCUSD` 30-minute REST data was established.
- This report does not establish a Neon connection, Neon credentials, or database writes.

### DELTA-BASE-002 — V1.7 session envelope and closed-session writer guard
**Status: CONDITIONAL — method and offline test notes**

The V1.7 session definition is Asia/Kolkata 05:30 inclusive through the next day 05:30 exclusive, equivalent to UTC 00:00 through the next UTC 00:00. A complete session contains exactly 48 price-candle open timestamps from 00:00 through 23:30 UTC, at 30-minute intervals.

The documented guard rules include:
- Only fully closed candles are eligible.
- `source_available_at` must be at or before the cutoff.
- Ingestion may occur after cutoff only within the documented 10-minute grace.
- Ingestion later than cutoff plus 10 minutes is rejected.
- The grace period does not extend the candle window or relax source-availability requirements.
- Current, future and developing sessions are rejected.

Method notes describe offline unit coverage for the 2026-11-22 48-slot shape, ingestion 38.497 seconds after close, exact cutoff, after-grace rejection, post-cutoff source availability and closed-session enforcement.

Do not claim a particular GitHub Actions execution unless the exact run URL and job/test evidence are linked.

### DELTA-BASE-003 — V1.7 Neon writer/backfill safety
**Status: CONDITIONAL — historical runbook, not a fresh Neon inspection**

The runbook identifies these historical resources:
- Neon project: `old-surf-34279165`
- Source branch: `br-lingering-grass-ao07mgrx`
- Destination branch: `br-crimson-tooth-ao7oq469`
- Destination database: `amt_research`

These identifiers are reproduced from documentation and have not been freshly queried in this inventory.

The documented safety model requires dry-run by default and explicit `--apply`; an isolated development branch rather than the default/production branch; separate read-only source and destination metadata checks; writer login and V2 idempotent write path; verification of database/login/host; exactly 48 ordered 30-minute PRICE and OI slots; skipping complete fingerprinted sessions; stopping on incomplete or unfingerprinted sessions rather than auto-overwriting; and verification of one complete profile, 48 developing snapshots, OI context and both SHA-256 fingerprints.

Historical notes record:
- 2026-11-22: complete and fingerprinted.
- 2026-11-21: missing, but 48 price plus 48 OI records were available; ingestion was 38.351 seconds after cutoff.
- 2026-11-20: incomplete.
- 2026-11-19: previous complete session.
- 2026-11-23 through 23:30 UTC: retrieved 53.872 seconds after cutoff.

These are historical runbook notes, not a new database read or write.

## Open findings

| ID | Finding | Status / next evidence |
|---|---|---|
| DELTA-OPEN-001 | Neon identity should be recorded per run. | OPEN — record project, branch, database, host identity and login role for each validation without exposing credentials. |
| DELTA-OPEN-002 | Closed-session writer boundary and persistence rollback test execution. | OPEN — capture exact offline/test-only GitHub Actions run URL, job, test files and exact cases. Do not dispatch the daily database-writing workflow to test this. |
| DELTA-OPEN-003 | Current BTC options product metadata. | OPEN — verify calls/puts, contract value, contract unit currency and expiry using authoritative current product metadata. |
| DELTA-OPEN-004 | Gamma/GEX scaling. | OPEN — confirm authoritative units and retain a worked example. |
| DELTA-OPEN-005 | Options trades endpoint evidence. | OPEN — capture a timestamped real BTC option trades endpoint HTTP 200 response and reconcile the earlier parser/endpoint discrepancy. |
| DELTA-OPEN-006 | Expiry settlement timestamp and timezone. | OPEN — establish settlement/TWAP boundaries and handling of missing observations. |
| DELTA-OPEN-007 | Historical parity qualification. | CLOSED WITH ORIGINAL QUALIFICATION — preserve the original conditional session-assignment qualification; do not casually rerun or reopen parity. |
| DELTA-OPEN-008 | Exact offline/test-only Actions evidence. | OPEN — link the actual run and list executed test files/cases and counts. |
| DELTA-OPEN-009 | Archive identity. | OPEN — record exact archive commit/object identity and SHA-256 where applicable. |

## Validation register

| Validation ID | Date | Scope | Outcome | Evidence / limitation |
|---|---|---|---|---|
| DELTA-M1-20261117 | 2026-11-17 | 65-minute BTCUSD feed baseline | CONDITIONAL | Historical report; timestamp-label and OI qualifications above |
| DELTA-V17-METHOD | 2026-11-24 | V1.7 method and runbook inventory | CONDITIONAL | Documentation review; not a fresh Neon query |
| DELTA-INV-20261124 | 2026-11-24 | Repository documentation inventory | CONDITIONAL | No production workflow dispatch, database write or fresh Neon inspection |

## Evidence rules

Record exact commit SHA, data/session date, symbol, timeframe, timezone, source timestamps, ingestion timestamps, expected and observed slot counts, duplicate/missing/conflicting slots, fingerprints, Neon project/branch/database identity, exact test command and test names, Actions run URL, and whether the operation was offline, read-only, isolated or production-facing.

## Safety boundary

This registry commit is documentation-only. Do not dispatch a daily database-writing workflow to test a code change. No production workflow dispatch, Neon write, collector execution, schema change, deployment or Stage C activity is authorized by this documentation task. Historical parity remains closed with its original qualification.