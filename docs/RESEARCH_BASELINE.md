# Historical AMT Research Baseline

**Status:** CLOSED — substantially complete, accepted with qualifications  
**Cohort:** 21 May–19 November 2026  
**Source:** Delta India BTCUSD 30-minute PRICE and OI records  
**Profiles:** 183 reconstructed in memory; no reconstructed profiles or event results persisted.

## 1. Research method

The reconstruction used the approved AMT Engine V1.0 methodology: globally anchored $50 rows, one TPO visit per candle per inclusive OHLC bucket, lower-price POC tie-break, 70% value area, and approved Option A one-row-at-a-time expansion with zero-count rows as candidates.

Developing profiles were reconstructed at 8,784 completed candle cutoffs using only candles through each cutoff. This was a read-only research exercise. The approved 20 and 21 November persisted profiles were excluded and left unchanged; the partial 22 November session was excluded.

## 2. Data quality

- 183 sessions × 48 bars = **8,784** PRICE candles.
- **8,784** OI candles; all 8,784 PRICE/OI timestamps matched.
- No missing PRICE bars, duplicate timestamps, off-grid slots, null PRICE OHLC, invalid PRICE OHLC relationships, or provisional rows in the cohort.
- OI OHLC values were present; OI `volume` was NULL for all 8,784 records. NULL is not zero and no unit is inferred.
- PRICE volume was present but not used for TPO.
- The first cohort session (21 May) has no preceding eligible cohort session; prior-value event study therefore contains 182 sessions.

## 3. Profile and migration observations

- Total TPO visits across final profiles: **57,382**.
- Actual value-area coverage: mean **71.92%**, median **71.43%**.
- Selected value-area width: mean approximately **$1,170**, median **$900**.
- Within-session adjacent-cutoff POC comparisons: **8,601**; POC moved in **918 (10.7%)**.
  - Up: 549; down: 369; unchanged: 7,683.
- Both VAH and VAL moved up in 550 cutoff transitions and down in 544.
- Across 182 completed-session transitions:
  - Mean POC shift: **−$76.92**; median $0.
  - Mean VAH shift: **−$77.75**.
  - Mean VAL shift: **−$80.49**.
  - Mean value-area Jaccard overlap: **23.78%**; median **19.84%**.

## 4. Descriptive event findings

Definitions used in the original research included:
- Prior value area represented as `[VAL_lower, VAH_upper)`.
- Above-value close: close at or above the VAH upper boundary.
- Below-value close: close below the VAL lower boundary.
- Confirmed discovery: two consecutive completed closes outside the same prior-value boundary.
- Rejection: candle trades beyond a prior boundary but closes back inside prior value.
- Unconfirmed failed excursion: first outside close followed by an inside close before a second same-side outside close.
- Confirmed failed discovery/re-entry: after two consecutive outside closes, a later close returns inside prior value.
- Acceptance/hold retest: after confirmation, later candle touches the broken boundary and closes outside on the same side.
- Whole-value migration: VAH and VAL both move in the same direction; POC migration is tracked separately.
- Initial Balance: first two completed 30-minute candles; wick and close breaks are separate.
- Edge extreme proxy: highest/lowest occupied TPO row has exactly one visit. This is not asserted to be true excess or a letter-based single print.

Initial descriptive counts (182 sessions with prior value reference):
- At least one outside-value close: **172/182 (94.5%)**.
- At least one confirmed discovery: **167/182 (91.8%)** — 79 upside, 88 downside.
- Upper rejection: 97 sessions; lower rejection: 99 sessions (can overlap).
- First outside episode returned inside before confirmation: 39 sessions.
- First confirmed episode later re-entered: 89 sessions.
- Post-confirmation boundary retest-and-hold: 70 sessions (35 upside, 35 downside).
- Opening location: 39 above prior value, 114 inside, 29 below. The exact opening price field is not sufficiently documented to certify whether it was the first candle open or another price.
- IB high wick break: 161; IB low wick break: 160; both sides wicked: 139.
- Later close above IB high: 149; later close below IB low: 149.
- IB width: mean approximately $382; median $321.
- Single-visit high edge rows: 142; 64 retested next session (45.1%).
- Single-visit low edge rows: 136; 66 retested next session (48.5%).

## 5. Forward excursion observations and qualifications

Reported confirmed-discovery forward excursion summaries:

| Horizon | Median MFE | Median MAE | Boundary revisits |
|---|---:|---:|---:|
| 1 bar | $119.50 | $118.00 | 51/167 |
| 2 bars | $190.00 | $145.00 | 66/167 |
| 4 bars | $267.50 | $197.50 | 80/167 |
| 8 bars | $368.50 | $258.50 | 95/167 |
| 16 bars | $489.50 | $350.50 | 114/167 |

The accepted clarification addendum explicitly records that the exact starting-price convention and incomplete-window handling are not sufficiently documented to certify. It also does not establish whether the confirmation candle was excluded from subsequent observations. The denominator 167 is the reported session denominator, not a verified full-window denominator for every horizon. Do not derive trading rules or predictive claims from these figures.

## 6. Mandatory qualifications and unresolved limitations

1. **Timestamp semantics:** grouping used 00:00 UTC timestamp-date boundaries (05:30 IST reset), but raw epoch equality does not prove whether Delta timestamps are candle-open or candle-close times. Session assignment is **CONDITIONAL**. If timestamps are close times, boundary candle assignment and dependent profile/event measurements may shift.
2. **MFE/MAE:** exact starting price, confirmation-candle inclusion, and incomplete-window treatment are not certified. Treat the reported numbers as descriptive only.
3. **Opening location:** exact price field used is not certified.
4. **Event counting:** counts primarily represent sessions with at least one qualifying event, not every occurrence. Repeated discoveries, excursions, re-entries and retests were not fully counted as separate events.
5. **Source instrument:** research metrics are Delta BTCUSD. Supabase snapshots on 21 November are Binance BTCUSDT and must not be pooled as identical data.
6. **TPO nature:** OHLC-range TPO is not tick-level time-at-price or volume-at-price.
7. **Extremes:** single-visit edge-row proxy is not proof of true excess/single prints.
8. **OI:** OI volume is NULL; units are not inferred. OI is supplementary and not a directional signal in this research.
9. **Legacy labels:** the 16-label feature table is Neon `research.amt_30m_features`, not Supabase `amt_snapshots`. Its historical label writer was not fully located; labels are not treated as validated event truth.
10. **Separate state machines:** Supabase `ResearchStateEngine`, the Pine-derived dashboard state machine and approved Neon AMT Engine V1.0 are distinct systems. Their labels and outputs must not be conflated.

## 7. Closure

The Historical AMT Research milestone is closed as substantially complete. This baseline and its qualifications are preserved. Do not initiate another reconstruction, recalculate historical profiles, modify the database, or reopen historical parity to resolve these limitations. A future research phase requires separate commissioning.
