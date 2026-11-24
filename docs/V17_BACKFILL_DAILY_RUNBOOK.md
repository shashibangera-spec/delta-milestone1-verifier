# V1.7 historical backfill and daily pipeline runbook

## Scope

This runner targets only Neon project `old-surf-34279165`, destination branch
`br-crimson-tooth-ao7oq469`, database `amt_research`, and the existing
`amt_v17_writer_login`. Its source is the read-only Delta candle branch
`br-lingering-grass-ao07mgrx`.

It does not touch the default/production Neon branch, the continuous collector,
the existing dashboard, Pine, or trading rules.

## Safety model

- Dry-run is the default. Persistence requires the explicit `--apply` flag.
- Source and destination metadata are read through separate read-only PostgreSQL
  connections. Writes use only the existing V1.7 writer login and V2 idempotent
  writer path.
- Both connections verify database, login and pinned endpoint host.
- The source query requires exactly 48 ordered 30-minute OPEN slots for PRICE
  and OI, with complete OHLC and retrieval timestamps.
- The candle close and source-availability cutoff remain strict. Since
  `research.delta_candles` has `retrieved_at` but no independent
  `source_available_at`, this pipeline explicitly derives source availability
  from candle close and labels that basis in the payload.
- Ingestion must be no later than session cutoff plus 10 minutes.
- Complete fingerprinted destination sessions are skipped. Existing incomplete
  or unfingerprinted sessions stop the run for manual reconciliation; they are
  never overwritten automatically.
- Sessions are processed chronologically. Prior-profile candidates are refreshed
  after each successful write, so a newly backfilled complete session becomes
  the next session's reference. Incomplete earlier sessions remain in the
  candidate list for the resolver to skip.
- Every applied session is verified for one complete profile, 48 developing
  snapshots, verified OI context, and both SHA-256 fingerprint fields.

## Required runtime environment

Configure these as runtime secrets/environment variables; never commit URLs:

- `DATABASE_URL`: existing writer login URL for the isolated dev branch.
- `NEON_PROJECT_ID=old-surf-34279165`
- `NEON_BRANCH_ID=br-crimson-tooth-ao7oq469`
- `NEON_DATABASE_NAME=amt_research`
- `V17_SOURCE_BRANCH_ID=br-lingering-grass-ao07mgrx`
- `V17_SOURCE_DATABASE_URL`: read-only `amt_dashboard_ro` URL on the source branch.
- `V17_TARGET_READ_BRANCH_ID=br-crimson-tooth-ao7oq469`
- `V17_TARGET_READONLY_DATABASE_URL`: read-only `amt_dashboard_ro` URL on the destination branch.

The destination `amt_dashboard_ro` login has SELECT only on
`session_profiles`, `developing_snapshots`, `session_oi_context`, and
`session_write_fingerprints`; it has no INSERT privilege. The source login
reads only `research.delta_candles`.

## Historical backfill

First run dry-run for the specific date range:

```bash
python -m amt_engine.v17_pipeline backfill --from-date 2026-11-21 --through-date 2026-11-21
```

Review the output. To persist only after review:

```bash
python -m amt_engine.v17_pipeline backfill --from-date 2026-11-21 --through-date 2026-11-21 --apply
```

Do not include dates with existing incomplete profiles until separately reconciled.
Do not backfill the current, still-open UTC session.

## Daily session

The default daily date is the previous UTC calendar date. Run dry-run first:

```bash
python -m amt_engine.v17_pipeline daily
```

Persist after reviewing the result:

```bash
python -m amt_engine.v17_pipeline daily --apply
```

A proposed schedule is 00:12 UTC daily (05:42 IST), allowing the 00:00 UTC
session boundary and the 10-minute ingestion grace to elapse. The scheduler
must invoke `daily --apply` only after the offline tests pass and all three
database URLs/identity variables are configured. Scheduling/deployment is a
separate approval gate; this repository change alone does not enable a live
daily job.

## Initial known state

- 2026-11-22 BTCUSD V1.7 profile is complete and fingerprinted.
- 2026-11-21 is the identified missing historical session; source audit showed
  48 complete PRICE and 48 complete OI rows, last retrieval 38.351 seconds
  after cutoff.
- 2026-11-20 has an existing INCOMPLETE profile. Its most recent earlier
  complete reference is 2026-11-19; the resolver must record 20 November as
  skipped/incomplete when processing 21 November.
- 2026-11-23 source records were present through the 23:30 UTC candle and
  retrieved 53.872 seconds after the 00:00 UTC cutoff; the daily runner should
  process this date on the next scheduled run after the grace window.
