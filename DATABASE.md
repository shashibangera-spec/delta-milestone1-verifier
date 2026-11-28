# Neon database layout — Delta BTC research

## Existing immutable research objects
The existing `research.delta_candles`, `research.delta_candles_provisional`,
`research.amt_30m_features`, and `amt_engine` objects are outside the scope of
the options OI feature. This feature does not alter their schemas or data.

## Delta BTC options OI snapshots
Apply `migrations/20261129_delta_btc_options_oi.sql` manually to database
`amt_research` on collector branch `br-lingering-grass-ao07mgrx` after review.
It creates the isolated `options_oi.btc_chain_snapshots` table and grants SELECT
to the existing `amt_dashboard_ro` role. It does not create or change roles.

The continuous collector writes using its existing collector database URL in a
separate connection and transaction. The dashboard reads through its existing
read-only `SOURCE_DATABASE_URL` connection, which is validated against the
approved collector-branch host and `amt_dashboard_ro` identity.

Rows are sampled for the nearest two upcoming expiries and ATM +/- six listed
strikes per expiry and option type (up to 52 rows). `expiry_ts` is 12:00 UTC on
the symbol's DDMMYY date. The retention predicate is
`expiry_ts < snapshot_ts - interval '24 hours'`, i.e. settlement plus 24 hours.

## Rollback
No automatic rollback is performed. If rollback is separately approved, first
stop the collector's options subtask, then revoke the read-only grants and drop
only `options_oi.btc_chain_snapshots` and `options_oi` using the commented
rollback statements in the migration. Do not drop or modify `research` or
`amt_engine` objects.
