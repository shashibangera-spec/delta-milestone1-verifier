# Changelog

## PR #1 verification correction
- Preserve raw Delta ticker `oi[0]` contract counts and add BTC-normalized values using `contract_value_btc = 0.001`.
- Compare normalized stream OI (BTC) with REST `OI:BTCUSD` candle values (BTC).
- Label any 30-minute candle not fully covered by the observation window as `PROVISIONAL_INCOMPLETE`.
- Add regression tests for contract conversion, unit-consistent comparison, and provisional versus complete candle coverage.
- The original 65-minute Milestone 1 baseline report remains unchanged.


## Milestone 2 — continuous research collector

- Added a 24/7 Railway worker that polls Delta's BTCUSD PRICE and OI:BTCUSD 30-minute REST candles.
- Confirmed candles are saved atomically to `research.delta_candles` with conflict-safe upserts; unfinished candles are isolated in `research.delta_candles_provisional` and labelled `PROVISIONAL_INCOMPLETE`.
- Startup guards require the verified historical baseline (8,641 PRICE, 8,641 OI, 1,800 AMT feature rows). First confirmed save triggers row-count, checksum, and 30-minute grid verification.
- Collector is restricted to Neon database `amt_research`; branch ID is explicitly configured as `br-lingering-grass-ao07mgrx`.



## Neon collector baseline integrity correction

- Separate the immutable 8,641-row PRICE/OI historical prefix (through 2026-11-17 00:00 UTC) from subsequently appended confirmed candles; startup no longer compares live table totals against the original baseline counts.
- Pin the independently verified original PRICE/OI prefix checksums and UTC time range; startup fails closed if either historical prefix changes.
- Keep the 1,800-row AMT feature history unchanged and pin its independently verified original time range and checksum as an additional startup integrity guard.
- After the first new confirmed pair, verify historical checksums, PRICE/OI timestamp pairing, 30-minute grid alignment and continuity across each scoped series.
- Add regression coverage for valid expanded live history, historical row-count/checksum/time-range corruption, missing series, off-grid candles and 30-minute gaps.
- No Neon data, schema, Railway configuration or deployment changes are part of this correction.


## Neon collector checksum delimiter correction

- Correct the SQL checksum separator escaping so PostgreSQL hashes the immutable historical PRICE, OI and AMT feature baselines using the same literal backslash-n separator used when the approved baseline checksums were generated.
- Add a regression test to prevent the delimiter escaping from silently changing again.
- No market data, database schema, Railway variables, or dashboard behavior changed.


## AMT Engine V1 daily calculation preparation
- Added a standalone daily AMT calculation package for the Neon research project; collector and live dashboard remain untouched.
- Enforced 48 exact 30-minute UTC candles per session (00:00 UTC / 05:30 IST), strict timestamp/OHLC/duplicate/provisional validation, and no final profile on invalid input.
- Implemented zero-origin $50 TPO rows, exact-boundary higher-row assignment, lower-price POC and VA tie-breaks, and Option A zero-count VA expansion candidates.
- Separated revision numbers from execution attempt numbers; unchanged-input retries stay in the same revision and unavailable fingerprints remain NULL.
- Added a read-only historical parity utility for all 183 completed profiles and 8,113 reference TPO rows. Historical session assignment remains CONDITIONAL.
- Added a review-only SQL migration. No SQL, Neon permission, Railway, deployment, dashboard, or validation-branch changes were performed.


## AMT Engine V1.0 daily writer foundation
- Applied the three-table `amt_engine` schema to the dedicated Neon research branch `br-lingering-grass-ao07mgrx`.
- Created `amt_engine_writer` with schema-scoped access; granted SELECT on only the required source columns and SELECT/INSERT on AMT outputs, plus column-limited status updates on calculation runs.
- Verified source INSERT is denied, unapproved source columns are not selectable, and output DELETE is denied. Existing read-only identities were not modified.
- Added a manually triggered research-branch daily execution workflow; it requires the repository secret `AMT_ENGINE_DATABASE_URL` and does not deploy or run automatically.
- Historical parity evidence and conditional session-assignment qualification remain unchanged.
