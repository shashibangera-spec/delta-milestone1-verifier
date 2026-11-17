# Changelog

## PR #1 verification correction
- Preserve raw Delta ticker `oi[0]` contract counts and add BTC-normalized values using `contract_value_btc = 0.001`.
- Compare normalized stream OI (BTC) with REST `OI:BTCUSD` candle values (BTC).
- Label any 30-minute candle not fully covered by the observation window as `PROVISIONAL_INCOMPLETE`.
- Add regression tests for contract conversion, unit-consistent comparison, and provisional versus complete candle coverage.
- The original 65-minute Milestone 1 baseline report remains unchanged.
