# BTC V1.7 / Playbook V1.3 browser dashboard

A standalone single-page FastAPI dashboard. It reads the production `amt_research` database using a server-side, least-privilege `amt_dashboard_ro` connection. No database credential is sent to the browser. The dashboard has no order-routing or alert capability.

## Railway deployment

Deploy this repository as a separate Railway service with the repository root as the build context (leave **Root Directory** blank) and Dockerfile path `browser_dashboard/Dockerfile`.

Set these Railway service variables:

- `DATABASE_URL` — the production `amt_dashboard_ro` PostgreSQL connection for database `amt_research` on branch `br-snowy-water-aog0ilqw` (host `ep-morning-mountain-aopl02wv.c-2.ap-southeast-1.aws.neon.tech`).
- `DASHBOARD_USERNAME` — a username you choose.
- `DASHBOARD_PASSWORD` — a strong password you choose; keep it in Railway variables, not in source control or chat.

Do not use the writer credential. The app validates the exact production host, database and database role, then sets each query transaction to read-only. The value remains server-side and is never returned by an endpoint.

Expose the service on its Railway-generated domain after the migration is applied and all three variables are configured. The dashboard UI and data API require HTTP Basic authentication. `/health` is the unauthenticated health-check path.

## Data shown

- Latest complete V1.7 AMT profile and its reference/prior profile.
- Persisted developing VAH/POC/VAL with snapshot progress out of 48.
- Latest available completed 30m BTC candle and causal two-close Discovery label.
- Current-session OI expansion/contraction/unknown classification.
- Cumulative Playbook v1.3 realized R, active position count, and recent shadow trades.

Developing levels are explicitly labelled as persisted V1.7 snapshots; they are not silently recomputed with a different TPO implementation. Live price and Discovery use the latest available completed source candles.


## Delta BTC options OI context (collector branch)
The BTCUSD tab includes an optional, read-only options OI context card. The collector stores Delta India ticker snapshots in the isolated `options_oi.btc_chain_snapshots` schema on collector branch `br-lingering-grass-ao07mgrx`. Apply `migrations/20261129_delta_btc_options_oi.sql` to that branch before enabling the feature. The migration grants SELECT to the existing `amt_dashboard_ro` role; the dashboard reads through its existing read-only `SOURCE_DATABASE_URL` connection. Do not use the production AMT branch or any writer credential for dashboard reads.

The collector samples the nearest two upcoming expiries and ATM +/- six listed strikes (up to 52 rows). Option rows are retained until 24 hours after the 12:00 UTC settlement timestamp. The BTCUSD card shows descriptive PCR and OI walls plus strike changes versus the nearest available ~30m snapshot. It does not infer buyer/seller intent, participant identity, or market direction.
