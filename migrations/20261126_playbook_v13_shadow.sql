-- Playbook v1.3 shadow-only persistence. Apply to production amt_research.
-- Starts a fresh 0.0R observation ledger; deliberately does not backfill history.
BEGIN;

CREATE TABLE IF NOT EXISTS amt_engine_v17.playbook_v13_shadow_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    strategy_version text NOT NULL DEFAULT 'BTC_PLAYBOOK_V1.3',
    shadow_started_at timestamptz NOT NULL DEFAULT now(),
    starting_realized_r numeric NOT NULL DEFAULT 0.0 CHECK (starting_realized_r = 0.0),
    last_processed_candle_open timestamptz NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO amt_engine_v17.playbook_v13_shadow_state(singleton, strategy_version, starting_realized_r)
VALUES (true, 'BTC_PLAYBOOK_V1.3', 0.0)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS amt_engine_v17.playbook_v13_shadow_trades (
    trade_key text PRIMARY KEY CHECK (trade_key ~ '^[0-9a-f]{64}$'),
    strategy_version text NOT NULL DEFAULT 'BTC_PLAYBOOK_V1.3',
    session_date date NOT NULL,
    symbol text NOT NULL CHECK (symbol = 'BTCUSD'),
    pattern text NOT NULL CHECK (pattern IN ('A','B')),
    side text NOT NULL CHECK (side IN ('LONG','SHORT')),
    status text NOT NULL CHECK (status IN ('OPEN','CLOSED')),
    signal_candle_open timestamptz NOT NULL,
    signal_candle_close timestamptz NOT NULL,
    entry_time_utc timestamptz NOT NULL,
    entry_price numeric NOT NULL,
    stop_price numeric NOT NULL,
    target_price numeric NOT NULL,
    risk_points numeric NOT NULL CHECK (risk_points > 0),
    buffer_points numeric NOT NULL CHECK (buffer_points > 0),
    prior_profile_id uuid NOT NULL,
    prior_vah_upper numeric NOT NULL,
    prior_val_lower numeric NOT NULL,
    discovery_state text NOT NULL,
    opening_oi numeric NULL,
    entry_oi numeric NULL,
    oi_delta numeric NULL,
    oi_class text NOT NULL CHECK (oi_class IN ('EXPANSION','CONTRACTION_OR_FLAT','UNKNOWN')),
    oi_unknown_reason text NULL,
    opening_oi_observation_time timestamptz NULL,
    opening_oi_retrieved_at timestamptz NULL,
    oi_observation_time timestamptz NULL,
    oi_units text NOT NULL DEFAULT 'BTC' CHECK (oi_units = 'BTC'),
    price_retrieved_at timestamptz NULL,
    oi_retrieved_at timestamptz NULL,
    entry_cutoff_at timestamptz NOT NULL,
    exit_candle_open timestamptz NULL,
    exit_candle_close timestamptz NULL,
    exit_price numeric NULL,
    exit_reason text NULL,
    realized_r numeric NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (target_price > entry_price OR side = 'SHORT'),
    CHECK (target_price < entry_price OR side = 'LONG')
);

ALTER TABLE amt_engine_v17.playbook_v13_shadow_trades
    ADD COLUMN IF NOT EXISTS opening_oi_observation_time timestamptz NULL,
    ADD COLUMN IF NOT EXISTS opening_oi_retrieved_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS oi_observation_time timestamptz NULL,
    ADD COLUMN IF NOT EXISTS oi_units text NOT NULL DEFAULT 'BTC' CHECK (oi_units = 'BTC');

CREATE INDEX IF NOT EXISTS playbook_v13_shadow_trades_status_time_idx
ON amt_engine_v17.playbook_v13_shadow_trades(status, signal_candle_close DESC);

CREATE TABLE IF NOT EXISTS amt_engine_v17.playbook_v13_shadow_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_key text NOT NULL REFERENCES amt_engine_v17.playbook_v13_shadow_trades(trade_key),
    event_type text NOT NULL CHECK (event_type IN ('ENTRY','EXIT')),
    event_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (trade_key, event_type, event_at)
);

CREATE INDEX IF NOT EXISTS playbook_v13_shadow_events_time_idx
ON amt_engine_v17.playbook_v13_shadow_events(event_at DESC);

CREATE OR REPLACE FUNCTION amt_engine_v17.record_playbook_v13_shadow_event(
    p_trade_key text, p_event_type text, p_event_at timestamptz, p_payload jsonb
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, amt_engine_v17
AS $$
BEGIN
    IF p_event_type NOT IN ('ENTRY','EXIT') OR p_event_at IS NULL OR p_payload IS NULL THEN
        RAISE EXCEPTION 'INVALID_SHADOW_EVENT';
    END IF;

    IF EXISTS (
        SELECT 1 FROM amt_engine_v17.playbook_v13_shadow_events
        WHERE trade_key=p_trade_key AND event_type=p_event_type AND event_at=p_event_at
    ) THEN
        RETURN;
    END IF;

    IF p_event_type = 'ENTRY' THEN
        INSERT INTO amt_engine_v17.playbook_v13_shadow_trades(
            trade_key,session_date,symbol,pattern,side,status,
            signal_candle_open,signal_candle_close,entry_time_utc,entry_price,stop_price,target_price,
            risk_points,buffer_points,prior_profile_id,prior_vah_upper,prior_val_lower,
            discovery_state,opening_oi,entry_oi,oi_delta,oi_class,oi_unknown_reason,
            opening_oi_observation_time,opening_oi_retrieved_at,oi_observation_time,oi_units,
            price_retrieved_at,oi_retrieved_at,entry_cutoff_at
        ) VALUES (
            p_trade_key,(p_payload->>'session_date')::date,p_payload->>'symbol',
            p_payload->>'pattern',p_payload->>'side','OPEN',
            (p_payload->>'signal_candle_open')::timestamptz,
            (p_payload->>'signal_candle_close')::timestamptz,
            (p_payload->>'entry_time_utc')::timestamptz,
            (p_payload->>'entry_price')::numeric,(p_payload->>'stop_price')::numeric,
            (p_payload->>'target_price')::numeric,(p_payload->>'risk_points')::numeric,
            (p_payload->>'buffer_points')::numeric,(p_payload->>'prior_profile_id')::uuid,
            (p_payload->>'prior_vah_upper')::numeric,(p_payload->>'prior_val_lower')::numeric,
            p_payload->>'discovery_state',(p_payload->>'opening_oi')::numeric,
            (p_payload->>'entry_oi')::numeric,(p_payload->>'oi_delta')::numeric,
            p_payload->>'oi_class',p_payload->>'oi_unknown_reason',
            (p_payload->>'opening_oi_observation_time')::timestamptz,
            (p_payload->>'opening_oi_retrieved_at')::timestamptz,
            (p_payload->>'oi_observation_time')::timestamptz,
            COALESCE(p_payload->>'oi_units','BTC'),
            (p_payload->>'price_retrieved_at')::timestamptz,
            (p_payload->>'oi_retrieved_at')::timestamptz,
            (p_payload->>'entry_cutoff_at')::timestamptz
        ) ON CONFLICT (trade_key) DO NOTHING;
    ELSE
        UPDATE amt_engine_v17.playbook_v13_shadow_trades
        SET status='CLOSED',
            exit_candle_open=(p_payload->>'exit_candle_open')::timestamptz,
            exit_candle_close=(p_payload->>'exit_candle_close')::timestamptz,
            exit_price=(p_payload->>'exit_price')::numeric,
            exit_reason=p_payload->>'exit_reason',
            realized_r=(p_payload->>'realized_r')::numeric,
            updated_at=now()
        WHERE trade_key=p_trade_key AND status='OPEN';
        IF NOT FOUND THEN
            IF EXISTS (
                SELECT 1 FROM amt_engine_v17.playbook_v13_shadow_events
                WHERE trade_key=p_trade_key AND event_type=p_event_type AND event_at=p_event_at
            ) THEN
                RETURN;
            END IF;
            RAISE EXCEPTION 'SHADOW_EXIT_WITHOUT_OPEN_TRADE';
        END IF;
    END IF;

    INSERT INTO amt_engine_v17.playbook_v13_shadow_events(trade_key,event_type,event_at,payload)
    VALUES (p_trade_key,p_event_type,p_event_at,p_payload)
    ON CONFLICT (trade_key,event_type,event_at) DO NOTHING;
END;
$$;

CREATE OR REPLACE FUNCTION amt_engine_v17.advance_playbook_v13_shadow_cursor(
    p_candle_open timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, amt_engine_v17
AS $cursor$
BEGIN
    IF p_candle_open IS NOT NULL THEN
        UPDATE amt_engine_v17.playbook_v13_shadow_state
        SET last_processed_candle_open = GREATEST(
                COALESCE(last_processed_candle_open, p_candle_open), p_candle_open
            ),
            updated_at = now()
        WHERE singleton = true;
    END IF;
END;
$cursor$;

REVOKE ALL ON amt_engine_v17.playbook_v13_shadow_state,
    amt_engine_v17.playbook_v13_shadow_trades,
    amt_engine_v17.playbook_v13_shadow_events FROM PUBLIC;
REVOKE ALL ON FUNCTION amt_engine_v17.record_playbook_v13_shadow_event(text,text,timestamptz,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION amt_engine_v17.advance_playbook_v13_shadow_cursor(timestamptz) FROM PUBLIC;

GRANT SELECT ON amt_engine_v17.playbook_v13_shadow_state,
    amt_engine_v17.playbook_v13_shadow_trades,
    amt_engine_v17.playbook_v13_shadow_events TO amt_dashboard_ro;
GRANT EXECUTE ON FUNCTION amt_engine_v17.record_playbook_v13_shadow_event(text,text,timestamptz,jsonb)
    TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.advance_playbook_v13_shadow_cursor(timestamptz)
    TO amt_v17_writer_login;

COMMIT;
