# V1.7 method notes — session envelope validation

## Session boundary and anti-lookahead contract

- Session dates are interpreted in Asia/Kolkata: 05:30 IST through the following 05:30 IST.
- The corresponding UTC envelope is 00:00:00 UTC inclusive through the next 00:00:00 UTC exclusive.
- The 48 PRICE candle OPEN timestamps must be exactly the 30-minute slots from 00:00 through 23:30 UTC.
- Every candle must be fully closed inside the session: `candle_open + 30 minutes <= session_cutoff`. A candle that closes after the cutoff is rejected.
- `source_available_at` must be at or before `session_cutoff`. The grace period never permits source data that was not available by the close.
- `ingested_at` may be later than the cutoff only to accommodate the normal REST polling delay after the final candle closes. The explicit maximum is **10 minutes**: `ingested_at <= session_cutoff + 10 minutes`.
- Any record ingested after that deadline is rejected. The grace period applies only to ingestion time; it does not extend the candle window, session cutoff, source availability, or calculation period.
- The current session must already be closed at validation time. Future and developing sessions remain rejected.

## Rationale

The final 23:30–00:00 UTC candle closes exactly at 00:00 UTC. A REST poll can retrieve that finalized candle seconds after close (the observed 22 November 2026 batch arrived 38.497 seconds after cutoff). Treating ingestion time as the candle's market-availability time would incorrectly reject a complete, finalized session. Keeping source availability bounded at the cutoff while allowing a narrowly bounded, documented 10-minute ingestion grace preserves the anti-lookahead boundary and accommodates normal transport latency.

## Validation coverage

Offline unit tests cover the 22 November 2026 48-slot session shape, a 38.497-second post-close ingestion, exact cutoff alignment, rejection after the 10-minute grace deadline, rejection of post-cutoff source availability, and closed-session enforcement. The isolated integration tests remain separate and continue to exercise the V2 writer against the isolated Neon development branch.
