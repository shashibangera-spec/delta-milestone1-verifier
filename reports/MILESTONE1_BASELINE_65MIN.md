# Milestone 1 Baseline — Delta BTCUSD Feed Verification

**Status:** Completed  
**Run duration:** 3,900.1 seconds (65 minutes)  
**Railway project:** `delta-milestone1-verifier`  
**Deployment:** `d28d4b48-348a-4ce1-8bc6-df3191d9ccc7`  
**Deployment status:** `SUCCESS`  
**Observation window (UTC):** 2026-11-17 21:27:45.684 to 22:32:45.742  
**Observation window (IST):** Not reliably reported by this deployed revision. The log fields labelled `start_ist` and `end_ist` incorrectly carried UTC offsets. A timezone-corrected source revision exists and must be deployed and re-verified.

## Observed results

| Check | Result |
|---|---:|
| Runtime | 3,900.1 seconds |
| WebSocket ticker messages | 774 |
| Ticker interval median | 5.032 seconds |
| Ticker interval mean | 5.040 seconds |
| Maximum ticker interval | 10.046 seconds |
| 30-minute candle update messages | 3,264 |
| WebSocket reconnects | 1 |
| REST price candles retrieved | 145 |
| REST timestamps on 1,800-second grid | 145 |
| Off-grid REST timestamps | 0 |
| Shared ticker/candle update slots | 4 |

The observed REST daily anchors were UTC midnight, equivalent to 05:30 IST. The report listed 16–19 November 2026 as anchor dates.

## OI interpretation and limitations

- The ticker payload's `oi[0]` was interpreted as the open-interest contracts level.
- `oi[1]` was interpreted as the six-hour change in OI value in the settling symbol, **not** the OI level.
- The run did not produce usable `oi[0]` min/max values in its final summary.
- No 30-minute OI OHLC series was validated. The earlier candidate aggregation was explicitly marked `validated: false`.
- The run did not compare the WebSocket ticker OI values with Delta's historical `OI:BTCUSD` 30-minute REST candles.

## Safety

The final Railway report explicitly recorded:

- `database_clients_in_worker: false`
- `neon_connection: false`
- `neon_credentials_used: false`
- `neon_writes: 0`

No Neon or Supabase writes were performed by this verifier.

## Baseline conclusion

This run supports the basic availability and cadence of the Delta public ticker/candlestick WebSocket feed and the 30-minute price-candle timestamp grid. It does **not** validate the semantics or correctness of a 30-minute OI OHLC series.

This report is retained as the immutable Milestone 1 baseline. Subsequent OI verification results must be recorded separately and must not overwrite these observations.
