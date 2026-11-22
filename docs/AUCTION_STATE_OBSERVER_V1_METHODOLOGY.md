# Auction State Observer V1 — Final Methodology Baseline

**Status:** ACCEPTED FOR DOCUMENTATION PURPOSES / METHODOLOGY BASELINE CLOSED  
**Specification scope:** Methodology, evidence contract and deferred validation  
**Implementation status:** NOT AUTHORIZED / NOT IMPLEMENTATION-READY  
**Decision record:** [Issue #13](https://github.com/shashibangera-spec/delta-milestone1-verifier/issues/13), final Balance clarification comment [7077234994](https://github.com/shashibangera-spec/delta-milestone1-verifier/issues/13#issuecomment-7077234994)

> This document records the approved Observer V1 methodology. Written rules do not establish data availability, source finality, profile acceptance, calculation correctness, historical validation, or implementation readiness.

## 1. Purpose and evidence hierarchy

Auction State Observer V1 describes the current BTC auction. It is not a prediction engine, trading strategy, or buy/sell signal service. Its architecture is:

**Market evidence → Observer state/event evaluation → trader dashboard**

Primary evidence:
1. Confirmed, completed BTCUSD 30-minute OHLC candles.
2. The latest eligible, accepted, completed daily AMT profile, frozen as the primary value reference.
3. The current-session developing profile as secondary context.

OI, EMA, Initial Balance, single prints, excess, unfinished auctions and other derived features remain secondary/diagnostic. They do not alter V1 core classification. Do not infer long/short positioning, institutional intent, absorption, initiative/responsive activity, or trading direction from OI or unsupported proxies. Null volume is not zero. OHLC-range TPO is an approximation, not trade-level sequence.

## 2. Evaluation clock and reference profile

- Evaluate only completed, confirmed 30-minute candles. Use the latest confirmed close for price location and event evaluation.
- Provisional candles may be shown as provisional context but cannot trigger or confirm events.
- Freeze the latest eligible accepted completed daily profile's VAH, POC and VAL for the evaluation session and every candidate created against it.
- The developing profile is contextual evidence only; it must not move the frozen reference during an active candidate.
- If no eligible accepted completed profile exists, show the reference unavailable and suppress dependent classifications. Never silently substitute an unaccepted profile.
- The documented daily boundary is 00:00–24:00 UTC / 05:30–05:30 IST, conditional on verification of source timestamp semantics and session assignment.

## 3. Strict price/value semantics

| Close or observation | Meaning |
|---|---|
| Close strictly above frozen VAH | Outside above |
| Close strictly below frozen VAL | Outside below |
| Close strictly between VAL and VAH | Inside value |
| Close exactly at VAH or VAL | Boundary; neither inside nor outside |

A qualifying excursion is a completed candle with high strictly above VAH and/or low strictly below VAL. A wick alone is not acceptance, Discovery or confirmed rejection.

Upper and lower candidates are independent. A candle may breach both boundaries and close inside, creating two candidates. OHLC cannot establish intrabar ordering.

Missing, invalid, off-grid, unconfirmed or conflicting-duplicate candles break consecutive sequences. Do not synthesize bars or arbitrarily select a conflicting duplicate. Use the common zero-origin $50 TPO row grid for row-derived comparisons. One-row movement is observable resolution, not a universal economic migration threshold.

## 4. Operational Price Acceptance

Operational Price Acceptance is confirmed at the third consecutive completed 30-minute close strictly beyond the same frozen VAH or VAL. Any intervening close not strictly beyond that same boundary, or any invalid/missing candle, breaks the sequence.

This is an operational persistence rule, not proof of institutional acceptance or participant intent. It does not require value migration and is not synonymous with Discovery.

## 5. Discovery

Discovery requires both:
1. Operational Price Acceptance: three consecutive completed closes strictly beyond the same frozen boundary.
2. A valid, current, comparable developing profile at that same confirmation cutoff, with developing POC beyond the corresponding prior VA boundary and the corresponding developing VA edge also extended beyond that boundary.

Confirm only at the third qualifying close and only if the developing profile is valid as of that cutoff. If the profile is missing, stale, invalid or non-comparable, report Operational Price Acceptance only; Discovery remains unconfirmed. POC movement alone is insufficient.

Use **Discovery Candidate** for an unconfirmed excursion. Do not use an undefined “Discovery developing” stage. Upper and lower candidates remain independent; preserve conflicting evidence rather than forcing a direction.

## 6. Canonical Return to Value

There is one ordinary return event: **Return to Value after an unconfirmed outside attempt**.

- The first completed close strictly inside the same frozen prior value starts the sequence.
- The next consecutive completed close strictly inside confirms it.
- An excursion candle that closes strictly inside may count as the first inside close.
- One inside close alone is not confirmation.
- A close outside or exactly at the boundary, or a missing/invalid candle, interrupts the sequence.
- After interruption, require a fresh qualifying outside excursion before a new ordinary return candidate begins.

Do not emit a separate confirmed Rejection event for the same two-close sequence. “Rejection” may be explanatory prose only.

After confirmed Discovery, two subsequent consecutive closes strictly inside the same frozen prior value confirm **Failed Discovery / Return to Value**. Preserve the earlier Discovery event in history. A later return changes current condition, not historical confirmation.

## 7. Balance — final deterministic documentation rule

Balance is a condition requiring BOTH:
1. Two-sided price rotation around the frozen prior-value midpoint.
2. Stable developing POC, VAH and VAL relative to a frozen candidate-start developing profile.

### 7.1 Session anchor and snapshot

The Balance anchor is the **first expected 00:00–00:30 UTC candle** of the evaluation session, subject to verified source timestamp/session mapping.

Capture the developing-profile snapshot **at that anchor candle's confirmed close**, using the developing profile built from the first completed, confirmed bar in the session. Freeze its POC, VAH and VAL as the Balance-start reference.

The assessment window is the first **12 expected consecutive 30-minute bars**, including the anchor bar.

### 7.2 Complete-window requirement

- **All 12 expected bars must be present and valid.**
- Assess only after the twelfth bar has closed and is confirmed.
- If the anchor bar or its developing-profile snapshot is missing, invalid, provisional, stale or unavailable, the session result is **INSUFFICIENT EVIDENCE**.
- Any missing, invalid, conflicting-duplicate or unconfirmed bar within the 12-bar window makes that session's Balance assessment **INSUFFICIENT EVIDENCE**.
- Do not start late, backfill the anchor, compress the window, substitute a later bar or re-anchor the window.
- If the prior accepted profile or session mapping is NOT VERIFIED, Balance remains unavailable/NOT VERIFIED regardless of apparent price rotation.

### 7.3 Two-sided rotation

Within the complete 12-bar window, require at least one strict close-side transition from below to above the frozen prior-value midpoint and at least one strict transition from above to below. A close exactly at the midpoint is neutral and does not itself count as a crossing. POC crossings are supporting evidence, not mandatory. Do not infer intrabar order from OHLC.

### 7.4 Stable developing value

Compare developing POC, VAH and VAL independently with their respective frozen anchor-snapshot values.

- Each component must remain within **±$50 inclusive** of its own anchor value throughout the window.
- The end-of-window comparison is also required.
- A movement greater than $50 in any component cancels the candidate, even if that component later returns within tolerance.
- Exactly $50 remains within tolerance.
- Missing/invalid developing-profile snapshots mean insufficient evidence, never presumed stability.

The $50 tolerance is Balance-only; it is not a universal migration or rejection threshold.

### 7.5 Availability qualification

The 12-bar (six-hour) window is the selected initial operational design threshold, not an empirically validated market constant. **Balance remains unavailable as a confirmed first-screen condition until the read-only 6/12/16-bar historical sensitivity review is completed and accepted.** The rule is documented; the capability is not yet validated.

## 8. Value development

Compare developing POC, VAH and VAL independently against the same frozen prior accepted daily profile. Each component is reported as higher, lower, unchanged at row resolution, or not comparable/not verified.

Do not produce an aggregate upward/downward/mixed directional label in V1. Keep geometric value-area overlap separate from migration. Neither overlap nor migration alone confirms Discovery or Balance. If the developing profile is incomplete, invalid or not based on a contiguous confirmed prefix, suppress migration conclusions.

## 9. Session rollover

At the documented evaluation boundary, currently 00:00 UTC / 05:30 IST:
- Cancel unconfirmed candidates and reset consecutive-close counters.
- Freeze the newly eligible prior accepted profile as the new reference.
- Do not carry sequences across reference-profile versions.
- Preserve confirmed events in history.

This is conditional on verified source timestamp convention and session assignment. Until verified, suppress or mark session-dependent classifications NOT VERIFIED.

## 10. Event lifecycle, idempotency and provenance

Candidate lifecycle: **ATTEMPT → DEVELOPING → CONFIRMED**, or **CANCELLED / INTERRUPTED**.

- Store the frozen reference and candidate start for every candidate.
- Confirmation is immutable historical evidence; later action creates a later event.
- No candidate resumes across a data gap.
- Emit once on transition to confirmed; keep current condition separate from latest confirmed event.
- The latest confirmed event is the one with the latest completed-candle confirmation time.
- If both upper and lower candidates qualify, retain both and report conflict/complex auction.
- Repeated processing of the same candle must be idempotent.
- Conflicting duplicate inputs interrupt evaluation.
- Later source corrections append auditable correction/supersession records; do not silently rewrite history.

Retain reference-profile identity/version, source and calculation provenance, candidate start, confirmation candle key/time, profile snapshot provenance, and cancellation/interruption reason.

## 11. First-screen contract and exclusions

Five first-screen items:
1. Current auction condition.
2. Price location versus frozen prior accepted value.
3. Independent POC/VAH/VAL value development.
4. Latest confirmed event, side, reference and confirmation time (or explicitly none).
5. Separate data-quality status for confirmed candles, source finality, profile completeness and calculation validation/acceptance.

Secondary expandable detail may include TPO, price-action diagnostics, IB, EMA, OI, candidate events, event history and calculation diagnostics. These cannot alter core classification until separately defined and validated.

No forecasts, targets, confidence scores, buy/sell calls, unsupported intent labels, or unvalidated derived features in core state. No Pine parity claim without a separate same-input comparison. Supabase Binance and Neon Delta feeds are not interchangeable for parity claims.

## 12. NOT VERIFIED or unavailable evidence gates

The following are explicit blockers, not implied capabilities:

- **Accepted completed-profile eligibility — NOT VERIFIED.** No currently demonstrated trusted auditable acceptance artifact/workflow. Completeness, successful calculation, fingerprint and row existence do not establish acceptance. A trusted record must identify profile/session, instrument/feed, method/version, source inputs/fingerprint, validation result, authorizer/time, status/reason and revision/supersession handling. Dependent classifications remain suppressed until demonstrated.
- **Source finality — NOT VERIFIED.** Elapsed time or a final-looking candle is not proof that the provider will not revise it. Require source metadata or an evidenced approved finalization policy.
- **Exact instrument/feed/timestamp/session mapping — NOT VERIFIED / CONDITIONAL.** Establish BTCUSD source identity, venue/feed, candle key, open/close timestamp semantics, expected 30-minute grid, duplicate handling, confirmed/provisional status and UTC session assignment. Do not conflate BTCUSD/BTCUSDT or Delta/Binance.
- **Developing-profile as-of validity — NOT VERIFIED until demonstrated.** Confirm calculation method, row grid, session cutoff, completeness and same confirmed-candle watermark as the event decision.
- **Historical as-observed replay — UNAVAILABLE unless source revisions/snapshots exist.** Latest-data reconstruction must not be described as as-observed replay.
- **Calculation validation/acceptance — NOT VERIFIED until evidenced.** A successful run or complete output is not sufficient proof of correctness or acceptance.

Keep four data-quality dimensions separate: (1) confirmed candle availability/continuity, (2) source finality, (3) profile completeness, and (4) calculation validation/acceptance. Unknown never means PASS. No aggregate PASS is defined.

## 13. Deferred validation register

1. **Balance sensitivity review:** read-only historical comparison of 6-, 12- and 16-bar windows. Evaluate false activations, detection delay, insufficient-evidence frequency, resets, missing snapshots, market-regime sensitivity and stability/cancellation behaviour. Keep the same anchor, midpoint, source and ±$50 component rules. Record sample limitations. No threshold optimization from selected examples.
2. **Profile acceptance evidence:** demonstrate a trusted auditable acceptance artifact/workflow; otherwise retain NOT VERIFIED.
3. **Source finality/data contract:** establish exact feed, timestamps, finality, candle identity, expected grid, duplicates, delayed arrivals and corrections.
4. **Developing-profile cutoff:** prove valid as-of calculation at the exact confirmation candle cutoff.
5. **Event edge-case validation:** gaps, boundary equality, simultaneous upper/lower excursions, provisional bars, profile invalidity, confirmed Discovery then return, session rollover, duplicate processing, source correction, and all Balance anchor/window/midpoint/tolerance cases.
6. **Pine parity and secondary evidence:** separate commissioning and same-source comparison required; no implied parity or secondary-feature approval.

## 14. Final disposition

The Auction State Observer V1 methodology baseline is **ACCEPTED FOR DOCUMENTATION PURPOSES / CLOSED**. This closure records the approved rules and their qualifications. It does **not** establish evidence-gate completion, historical validation, Balance availability, implementation readiness, production readiness or authorization to implement.

The project freeze remains in force. This document authorizes no application code, database, schema, collector, PR implementation, staging, production dashboard or deployment changes.
