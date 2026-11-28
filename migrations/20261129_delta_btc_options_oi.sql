-- Isolated Delta BTC options OI observation snapshots.
-- Target: collector branch br-lingering-grass-ao07mgrx, database amt_research.
BEGIN;
CREATE SCHEMA IF NOT EXISTS options_oi;
CREATE TABLE IF NOT EXISTS options_oi.btc_chain_snapshots (
    snapshot_ts timestamptz NOT NULL,
    product_id bigint NOT NULL,
    symbol text NOT NULL,
    expiry_date date NOT NULL,
    expiry_ts timestamptz NOT NULL,
    contract_type text NOT NULL CHECK (contract_type IN ('call_options','put_options')),
    strike_price numeric(18,2) NOT NULL CHECK (strike_price > 0),
    oi_btc numeric(24,10) NOT NULL CHECK (oi_btc >= 0),
    oi_usd numeric(28,8),
    oi_change_6h_usd numeric(28,8),
    mark_iv numeric(18,10),
    delta numeric(18,10),
    gamma numeric(24,14),
    volume_btc numeric(24,10),
    spot_price numeric(18,2) NOT NULL CHECK (spot_price > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_ts, product_id),
    CHECK (expiry_ts = (expiry_date::timestamp AT TIME ZONE 'UTC') + interval '12 hours')
);
CREATE INDEX IF NOT EXISTS btc_chain_snapshots_expiry_time_idx
    ON options_oi.btc_chain_snapshots (expiry_ts, snapshot_ts DESC);
CREATE INDEX IF NOT EXISTS btc_chain_snapshots_contract_strike_time_idx
    ON options_oi.btc_chain_snapshots (contract_type, strike_price, snapshot_ts DESC);
GRANT USAGE ON SCHEMA options_oi TO amt_dashboard_ro;
GRANT SELECT ON options_oi.btc_chain_snapshots TO amt_dashboard_ro;
COMMIT;

-- Rollback (manual/destructive; only if separately approved):
-- REVOKE SELECT ON options_oi.btc_chain_snapshots FROM amt_dashboard_ro;
-- REVOKE USAGE ON SCHEMA options_oi FROM amt_dashboard_ro;
-- DROP TABLE options_oi.btc_chain_snapshots;
-- DROP SCHEMA options_oi;
