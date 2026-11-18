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

 
## Custom multi-session historical auction research
- Added optional inclusive custom session-date range panel, separate from existing live and single-session views.
- Added fail-closed multi-day PRICE/OI pairing, composite TPO, non-directional OI change statistics, composite-value attribution, first-session range containment, and paired 30m history.
- Added regression tests for complete three-day windows, missing PRICE/OI candles, missing boundary OI, partial-session ranges, and unpaired timestamps.
- No collector, database schema/data, production Pine, alert, or Railway deployment changes.


## PR 2 — session selector usability
- Give the session-date selector a stable Streamlit session-state key so its choice survives reruns.
- Add a historical-mode-only “Return to Live / Current Session” control that restores the Live selection and the existing 45-second refresh.
- Preserve the independent custom date-range research selector and all existing AMT/OI calculations.
- Add regression tests for Live default, historical selection persistence, custom-range independence, return-to-live behavior, invalid historical selection fallback, and live-only auto-refresh.
- UI-only change; no collector, database, schema, AMT methodology, OI attribution, or production deployment changes.
