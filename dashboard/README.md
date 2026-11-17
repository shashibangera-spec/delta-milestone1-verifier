# Milestone 3 — isolated BTC AMT browser dashboard

- Separate Railway service; does not modify the collector or production dashboard.
- Reads only `research.delta_candles` and `research.delta_candles_provisional`.
- Connects as Neon role `amt_dashboard_ro`; SELECT on only those two tables.
- AMT day boundary: 00:00 UTC / 05:30 IST.
- 30m bracket TPO, $50 rows, 70% value area; confirmed candles only.
- Provisional candle is displayed separately and excluded from profile/OI confirmed calculations.
- CMP is the latest confirmed 30m PRICE close, not a streaming ticker.
- Research-derived prototype; not Pine v7.2.2 parity-certified.

- OI ladder uses the previous session's confirmed 23:30 UTC candle close as PREV OI (the 30m candle that ends at 00:00 UTC / 05:30 IST).
- Each current-session confirmed 30m OI delta is current close minus previous OI close; attribution uses that same slot's confirmed PRICE close against fixed Prior Day VAL/VAH.
- Above / Inside / Below buckets are marked reconciled only when PRICE/OI slots match, the 30m sequence is contiguous from the reset, and the bucket sum equals DAY OI.
