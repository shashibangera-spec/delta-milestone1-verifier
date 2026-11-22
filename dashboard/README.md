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

 
## Custom multi-session date-range research

- Optional inclusive date range is separate from the existing Live / Current Session and single historical-session selector.
- Dates represent 00:00 UTC / 05:30 IST session starts. Every selected date is a full 48-candle session.
- Analysis fails closed unless all expected confirmed PRICE/OI timestamps exist and match, and the confirmed OI boundary candle immediately before selected start exists.
- Composite TPO uses the same $50 rows, inclusive candle-range counting, lower-row POC tie-break, 70% target, adjacent-row expansion, and downward tie-break as the existing dashboard.
- OI change is measured from the boundary reference before selected start through the final selected candle. Counts and value-location attribution are descriptive only, never directional signals.
- OI location attribution assigns each close-to-close change by confirmed PRICE close relative to composite VAH/VAL; buckets must reconcile to net OI change.
- First-session high/low containment is separate from composite value. No acceptance/rejection or Pine v7.2.2 parity is implied.
- Detailed table contains every paired 30m candle. SELECT-only; no collector, schema/data, alert, or Pine changes.


## AMT Engine V1.0 developing-profile integration

- The completed-session profile adapter imports the approved `amt_engine.daily` V1.0 validator and calculator from the existing approved implementation commit; the daily writer and its calculation path are not changed.
- Developing profile is a read-only research output calculated with Decimal arithmetic, the V1.0 zero-origin $50 grid, lower-price POC tie-break and Option A one-row-at-a-time value-area expansion (including zero-count intervening rows).
- Developing output is shown only for a contiguous prefix beginning at 00:00 UTC / 05:30 IST. Missing, duplicate, off-grid, invalid OHLC or non-prefix candles fail closed. Only rows from the confirmed candle table are passed; provisional rows remain excluded.
- **Input-validated profile** means the candle inputs passed the exact timestamp, 48-slot completeness and OHLC checks. This describes data validity only; it is not an AMT daily acceptance decision.
- **Calculated developing profile** means the current contiguous confirmed prefix passed validation and its POC/VAH/VAL were calculated with the approved V1.0 rules. It is an interim research output, not a completed daily profile and not accepted by the AMT Engine.
- **Daily profile accepted by the AMT Engine** is a separate status that can only be asserted when the dashboard verifies the matching session record in the daily acceptance register. The dashboard does not currently query that register. Therefore a prior-session profile is explicitly labelled INPUT VALIDATION: PASS; PROFILE CALCULATION: COMPLETE; DAILY AMT ENGINE ACCEPTANCE: NOT VERIFIED — NOT ACCEPTED.
- Developing and dashboard-calculated prior values are research outputs, not accepted daily records or trading signals. The timestamp open/close semantic qualification remains unchanged.


- Controlled live-validation gates and evidence requirements are documented in [`LIVE_VALIDATION_CHECKLIST.md`](LIVE_VALIDATION_CHECKLIST.md). This is a preparation checklist only; it does not authorize merge or deployment.
