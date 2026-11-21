-- REVIEW ONLY. This migration is intentionally not executed by this repository change.
-- Run only after separate explicit database-change approval and writer-role provisioning.
CREATE SCHEMA IF NOT EXISTS amt_engine;

CREATE TABLE amt_engine.calculation_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_date DATE NOT NULL,
    method_version TEXT NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    resolution TEXT NOT NULL DEFAULT '30m',
    revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    run_type TEXT NOT NULL CHECK (run_type IN ('INITIAL','RETRY','RESTATEMENT')),
    supersedes_run_id UUID NULL REFERENCES amt_engine.calculation_runs(run_id),
    correction_reason TEXT NULL,
    expected_candles INTEGER NOT NULL DEFAULT 48 CHECK (expected_candles = 48),
    observed_candles INTEGER NOT NULL DEFAULT 0 CHECK (observed_candles >= 0),
    missing_candles INTEGER NOT NULL DEFAULT 0 CHECK (missing_candles >= 0),
    duplicate_candles INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_candles >= 0),
    invalid_ohlc_candles INTEGER NOT NULL DEFAULT 0 CHECK (invalid_ohlc_candles >= 0),
    provisional_candles INTEGER NOT NULL DEFAULT 0 CHECK (provisional_candles >= 0),
    input_first_candle TIMESTAMPTZ NULL,
    input_last_candle TIMESTAMPTZ NULL,
    input_fingerprint CHAR(64) NULL CHECK (input_fingerprint IS NULL OR input_fingerprint ~ '^[0-9a-f]{64}$'),
    input_coverage JSONB NOT NULL,
    validation_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution_status TEXT NOT NULL CHECK (execution_status IN ('VALIDATING','REJECTED','SUCCEEDED','FAILED')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    calculated_at TIMESTAMPTZ NULL,
    CONSTRAINT calculation_runs_attempt_key UNIQUE
      (session_date,method_version,source,symbol,revision_number,attempt_number)
);
CREATE INDEX calculation_runs_session_idx
  ON amt_engine.calculation_runs(session_date,method_version,source,symbol,revision_number DESC,attempt_number DESC);
CREATE INDEX calculation_runs_status_idx ON amt_engine.calculation_runs(execution_status);

CREATE TABLE amt_engine.daily_profiles (
    run_id UUID PRIMARY KEY REFERENCES amt_engine.calculation_runs(run_id),
    session_date DATE NOT NULL,
    method_version TEXT NOT NULL,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    expected_bars INTEGER NOT NULL CHECK (expected_bars = 48),
    observed_bars INTEGER NOT NULL CHECK (observed_bars = 48),
    is_complete BOOLEAN NOT NULL CHECK (is_complete),
    missing_candle_count INTEGER NOT NULL CHECK (missing_candle_count = 0),
    first_candle TIMESTAMPTZ NOT NULL,
    last_candle TIMESTAMPTZ NOT NULL,
    total_tpos INTEGER NOT NULL CHECK (total_tpos > 0),
    poc_lower NUMERIC NOT NULL,
    poc_upper NUMERIC NOT NULL,
    poc_tpo_count INTEGER NOT NULL CHECK (poc_tpo_count > 0),
    vah_lower NUMERIC NOT NULL,
    vah_upper NUMERIC NOT NULL,
    val_lower NUMERIC NOT NULL,
    val_upper NUMERIC NOT NULL,
    value_area_tpos INTEGER NOT NULL CHECK (value_area_tpos > 0 AND value_area_tpos <= total_tpos),
    session_open NUMERIC NOT NULL,
    session_high NUMERIC NOT NULL,
    session_low NUMERIC NOT NULL,
    session_close NUMERIC NOT NULL,
    CHECK (session_high >= session_low AND session_high >= GREATEST(session_open,session_close)
       AND session_low <= LEAST(session_open,session_close)),
    CHECK (val_lower <= poc_lower AND val_upper <= poc_upper
       AND poc_lower <= vah_lower AND poc_upper <= vah_upper)
);
CREATE INDEX daily_profiles_session_idx
  ON amt_engine.daily_profiles(session_date,method_version,source,symbol);

CREATE TABLE amt_engine.daily_tpo_rows (
    run_id UUID NOT NULL REFERENCES amt_engine.calculation_runs(run_id),
    row_lower NUMERIC NOT NULL,
    row_upper NUMERIC NOT NULL,
    tpo_count INTEGER NOT NULL CHECK (tpo_count >= 0),
    is_poc BOOLEAN NOT NULL DEFAULT false,
    is_value_area BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (run_id,row_lower),
    CHECK (row_upper = row_lower + 50),
    CHECK (mod(row_lower,50) = 0)
);
CREATE INDEX daily_tpo_rows_run_value_idx ON amt_engine.daily_tpo_rows(run_id,is_value_area);

-- Minimum grants for a pre-created, dedicated writer role; do not run until approved.
-- GRANT USAGE ON SCHEMA research TO amt_engine_writer;
-- GRANT SELECT (source,symbol,series_type,resolution,candle_time,open_value,high_value,low_value,close_value)
--   ON research.delta_candles TO amt_engine_writer;
-- GRANT SELECT (source,symbol,series_type,resolution,candle_time,status)
--   ON research.delta_candles_provisional TO amt_engine_writer;
-- GRANT USAGE ON SCHEMA amt_engine TO amt_engine_writer;
-- GRANT SELECT,INSERT ON amt_engine.calculation_runs TO amt_engine_writer;
-- GRANT UPDATE (execution_status,calculated_at,validation_report) ON amt_engine.calculation_runs TO amt_engine_writer;
-- GRANT SELECT,INSERT ON amt_engine.daily_profiles TO amt_engine_writer;
-- GRANT SELECT,INSERT ON amt_engine.daily_tpo_rows TO amt_engine_writer;
-- No UPDATE/DELETE/TRUNCATE privileges on output tables.
