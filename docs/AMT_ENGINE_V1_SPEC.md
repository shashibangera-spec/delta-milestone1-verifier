# AMT Engine V1.0 — Approved Specification

**Method version:** `AMT_ENGINE_V1.0`  
**Status:** APPROVED / FROZEN for the current validation baseline  
**Market data:** Delta India BTCUSD PRICE, 30-minute resolution  
**Session:** 00:00 UTC inclusive to next 00:00 UTC exclusive (05:30 IST reset)  
**Calculation:** deterministic price-only TPO profile

## 1. Scope and non-goals

The engine calculates a daily TPO profile from 48 completed 30-minute PRICE candles. It does not calculate volume-at-price, does not use OI to determine profile levels, and does not produce trade signals or predictive claims. Do not substitute a different TPO implementation or change tie-breaks under the V1.0 label.

## 2. Input contract

- Source: `delta_india`
- Symbol: `BTCUSD`
- Series type: `PRICE`
- Resolution: `30m`
- Expected bars: exactly 48
- Session bounds: UTC midnight through the next UTC midnight, end exclusive.
- Each candle must have timezone-aware timestamp and finite numeric OHLC values.
- OHLC ordering must satisfy `high >= max(open, close)`, `low <= min(open, close)`, and `high >= low`.

The validation gate fails closed for missing timestamps, duplicate timestamps, off-grid rows, malformed rows, invalid OHLC, provisional timestamps, or any observed candle count other than 48. A rejected session must not produce a final profile.

**Timestamp qualification:** UTC bounds are the implementation contract. The independent semantic question—whether upstream Delta timestamps denote candle open or candle close—remains unresolved. Session assignment to the intended market interval is therefore conditional until established from authoritative source semantics.

## 3. TPO row construction

- Row size: **$50**.
- Grid anchor: zero-origin global price grid.
- Bucket index: `floor(price / 50)`.
- Row lower bound: `bucket × $50`.
- Row upper bound: `(bucket + 1) × $50`.
- Each candle contributes one TPO visit to every bucket from the bucket containing its low through the bucket containing its high, inclusive.
- Repeated visits from separate candles increment the row count separately.
- Zero-count rows between the minimum and maximum occupied buckets remain represented when the value area expands across them.

This is an OHLC-range TPO approximation, not tick-level time-at-price or volume-at-price.

## 4. Point of Control (POC)

The POC is the row with the highest TPO count. If multiple rows tie for the highest count, choose the **lowest-price row**.

POC is stored and reported as a row interval with lower and upper bounds, not as an inferred single traded price.

## 5. Value Area (VA)

- Target coverage: **70%** of total TPO visits.
- Required visit count: ceiling of `total_tpos × 0.70`.
- Start with the POC row.
- At each iteration, compare only the immediately adjacent candidate row below and immediately adjacent candidate row above the current selected range.
- Choose the candidate with the larger TPO count.
- If candidate counts tie, choose the **lower-price candidate**.
- Add exactly one row per iteration. A zero-count intervening row is a valid candidate and is added when selected.
- Continue until selected TPO visits meet or exceed the target, or no candidates remain.

This is the approved **Option A one-row-at-a-time expansion**. Do not replace it with simultaneous two-sided expansion or skip zero-count rows.

The resulting VAH and VAL are represented as row bounds. Actual coverage may exceed 70% because rows are indivisible.

## 6. Output and deterministic evidence

The profile includes expected/observed bar counts, completeness, missing count, first/last candle, total TPO visits, POC row and count, VAH/VAL row bounds, value-area TPO count, and session OHLC.

The canonical input fingerprint is SHA-256 over a normalized, sorted representation of the method version, source, symbol, resolution, PRICE series type, timestamps and OHLC values. Decimal formatting is normalized so numerically equivalent representations (for example 1.0 and 1.00) hash consistently.

## 7. Revision and attempt semantics

- Execution attempts and calculation revisions are separate.
- A retry with unchanged input after a successful calculation remains in the same revision and increments the attempt.
- Changed input after a successful calculation creates a new revision (restatement).
- An unavailable/invalid input fingerprint remains NULL; it must not be fabricated.
- Failed output persistence must roll back the profile and all TPO rows before the separate FAILED audit status is recorded.

## 8. Writer safeguards (implementation controls, not a production-readiness claim)

The writer requires a fully closed UTC session and checks this inside the processing entrypoint, not only at CLI invocation. It verifies the approved Neon project, branch, database, hostname and runtime role on the connection used for reads/writes. It uses a per-session advisory lock and transactional output persistence. These controls do not establish unattended operation or remove the need for human review.

## 9. Change control

Any change to row size, grid anchor, candle allocation, POC tie-break, VA target, VA expansion, input contract, session convention, fingerprint format or revision semantics is a methodology change. It requires explicit Product Owner approval, a new version or formally approved amendment, tests, and a separate validation record. Documentation edits must not silently change these rules.
