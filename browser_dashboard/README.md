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
