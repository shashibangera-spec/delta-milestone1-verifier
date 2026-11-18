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


## Historical session selector

- The selector defaults to **Live / Current Session**; automatic 45-second refresh and the provisional panel are active only in Live mode.
- Historical choices are session start dates in retained confirmed history, each anchored at 00:00 UTC / 05:30 IST and ending at the next 00:00 UTC / 05:30 IST.
- Historical mode pauses auto-refresh, labels the view **Completed Historical Session**, and hides provisional data.
- Historical Prior Day and Session TPO profiles are shown only when each has all 48 confirmed 30m PRICE candles. Historical OI attribution is certified only with the exact prior-boundary OI close, 48 contiguous confirmed PRICE/OI pairs, identical timestamps, and bucket reconciliation within the strict tolerance.
- The first retained session date (21 May 2026) may not have its preceding session or 05:30 boundary OI candle in storage. In that case the unavailable Prior Day / PREV OI / attribution values deliberately remain unavailable; the dashboard does not synthesize missing history.
- Historical views use the same read-only amt_dashboard_ro database role and the same Neon amt_research branch as Live mode. No collector writes are performed.
