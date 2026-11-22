# AMT Engine V1.0 — Research Verifier

This repository contains the AMT Engine V1.0 daily profile calculation and validation work, alongside the earlier Delta data-verification and collection utilities. The AMT Engine is a deterministic, price-only 30-minute TPO profile calculator for Delta India BTCUSD data. It is a research and validation system; this repository does **not** establish production readiness or unattended operational reliability.

## Current status (22 November 2026)

- **Methodology:** AMT Engine V1.0 is approved and frozen for the current validation baseline.
- **Historical parity:** 183 completed profiles and 8,113 TPO rows were compared with zero reported mismatches. Historical session assignment remains **CONDITIONAL** because timestamp open/close semantics have not been established.
- **Daily evidence:** 20 and 21 November accepted records are immutable; the 21 November result is accepted PASS. The 22 November daily record remains **PENDING** acceptance and validation.
- **CI:** the offline daily-writer test workflow passed on 22 November, including closed-session and persistence-rollback tests. This is not a daily database calculation.
- **Scope:** documentation and validation records only in this repository. No changes to production dashboard, collector, Pine Script, or external repositories are implied.

## Architecture

1. **Input boundary:** Delta India BTCUSD PRICE 30-minute candles, selected by explicit UTC session bounds.
2. **Validation:** fail-closed checks for 48 exact timestamps, duplicates, grid alignment, OHLC integrity, malformed rows and provisional candles.
3. **Calculation:** deterministic $50 TPO grid, POC selection and approved Option A 70% value-area expansion.
4. **Persistence layer:** separately guarded daily writer for the dedicated Neon research database. It is distinct from the pure calculation module.
5. **Parity utility:** read-only comparison against the approved reference profiles and TPO rows.

The calculation is price-only. OI is not an input to the approved profile calculation.

## Documentation

- [Project status](docs/PROJECT_STATUS.md)
- [AMT Engine V1.0 specification](docs/AMT_ENGINE_V1_SPEC.md)
- [Validation register](docs/VALIDATION_REGISTER.md)
- [Research baseline](docs/RESEARCH_BASELINE.md)
- [Operations runbook](docs/OPERATIONS_RUNBOOK.md)
- [Decision log](docs/DECISION_LOG.md)
- [Existing changelog](CHANGELOG.md)
- [Original Milestone 1 baseline report](reports/MILESTONE1_BASELINE_65MIN.md)

## Important boundaries

The accepted 20 and 21 November profiles and historical parity evidence are immutable. Do not recalculate or overwrite them as part of documentation maintenance. The 22 November daily calculation is a separate pending validation. Any new research phase, methodology change, database change, production action, or workflow change requires separate explicit authorization.

Documentation status labels are used literally: **COMPLETED**, **PENDING**, **CONDITIONAL**, and **UNVERIFIED**. A successful CI run does not by itself establish a validated database record or production readiness.
