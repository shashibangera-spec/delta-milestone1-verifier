-- Additive Playbook v1.4 shadow ledger. Existing v1.3 rows and tables are untouched.
BEGIN;

CREATE TABLE IF NOT EXISTS amt_engine_v17.playbook_v14_shadow_state
    (LIKE amt_engine_v17.playbook_v13_shadow_state INCLUDING ALL);
ALTER TABLE amt_engine_v17.playbook_v14_shadow_state
    ALTER COLUMN strategy_version SET DEFAULT 'BTC_PLAYBOOK_V1.4';
INSERT INTO amt_engine_v17.playbook_v14_shadow_state
    (singleton,strategy_version,starting_realized_r)
VALUES (true,'BTC_PLAYBOOK_V1.4',0.0)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS amt_engine_v17.playbook_v14_shadow_trades
    (LIKE amt_engine_v17.playbook_v13_shadow_trades INCLUDING ALL);
ALTER TABLE amt_engine_v17.playbook_v14_shadow_trades
    ALTER COLUMN strategy_version SET DEFAULT 'BTC_PLAYBOOK_V1.4';
ALTER TABLE amt_engine_v17.playbook_v14_shadow_trades
    ADD CONSTRAINT playbook_v14_pattern_a_only CHECK (pattern = 'A');

CREATE UNIQUE INDEX IF NOT EXISTS playbook_v14_shadow_one_open_trade_idx
ON amt_engine_v17.playbook_v14_shadow_trades ((status))
WHERE status = 'OPEN';

CREATE TABLE IF NOT EXISTS amt_engine_v17.playbook_v14_shadow_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_key text NOT NULL REFERENCES amt_engine_v17.playbook_v14_shadow_trades(trade_key),
    event_type text NOT NULL CHECK (event_type IN ('OPEN','EXIT')),
    event_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (trade_key,event_type,event_at)
);
CREATE INDEX IF NOT EXISTS playbook_v14_shadow_events_time_idx
ON amt_engine_v17.playbook_v14_shadow_events(event_at DESC);

CREATE OR REPLACE FUNCTION amt_engine_v17.record_playbook_v14_shadow_event(
    p_trade_key text, p_event_type text, p_event_at timestamptz, p_payload jsonb
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, amt_engine_v17
AS $$
BEGIN
    IF p_event_type NOT IN ('OPEN','EXIT') OR p_event_at IS NULL OR p_payload IS NULL THEN
        RAISE EXCEPTION 'INVALID_V14_SHADOW_EVENT';
    END IF;
    IF EXISTS (SELECT 1 FROM amt_engine_v17.playbook_v14_shadow_events
               WHERE trade_key=p_trade_key AND event_type=p_event_type AND event_at=p_event_at) THEN
        RETURN;
    END IF;
    IF p_event_type='OPEN' THEN
        INSERT INTO amt_engine_v17.playbook_v14_shadow_trades(
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
        UPDATE amt_engine_v17.playbook_v14_shadow_trades
        SET status='CLOSED',
            exit_candle_open=(p_payload->>'exit_candle_open')::timestamptz,
            exit_candle_close=(p_payload->>'exit_candle_close')::timestamptz,
            exit_price=(p_payload->>'exit_price')::numeric,
            exit_reason=p_payload->>'exit_reason',
            realized_r=(p_payload->>'realized_r')::numeric,
            updated_at=now()
        WHERE trade_key=p_trade_key AND status='OPEN';
        IF NOT FOUND THEN RAISE EXCEPTION 'V14_SHADOW_EXIT_WITHOUT_OPEN_TRADE'; END IF;
    END IF;
    INSERT INTO amt_engine_v17.playbook_v14_shadow_events(trade_key,event_type,event_at,payload)
    VALUES (p_trade_key,p_event_type,p_event_at,p_payload)
    ON CONFLICT (trade_key,event_type,event_at) DO NOTHING;
END;
$$;

CREATE OR REPLACE FUNCTION amt_engine_v17.advance_playbook_v14_shadow_cursor(
    p_candle_open timestamptz
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, amt_engine_v17
AS $cursor$
BEGIN
    IF p_candle_open IS NOT NULL THEN
        UPDATE amt_engine_v17.playbook_v14_shadow_state
        SET last_processed_candle_open=GREATEST(
            COALESCE(last_processed_candle_open,p_candle_open),p_candle_open
        ), updated_at=now()
        WHERE singleton=true;
    END IF;
END;
$cursor$;

REVOKE ALL ON amt_engine_v17.playbook_v14_shadow_state,
    amt_engine_v17.playbook_v14_shadow_trades,
    amt_engine_v17.playbook_v14_shadow_events FROM PUBLIC;
REVOKE ALL ON FUNCTION amt_engine_v17.record_playbook_v14_shadow_event(text,text,timestamptz,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION amt_engine_v17.advance_playbook_v14_shadow_cursor(timestamptz) FROM PUBLIC;
GRANT SELECT ON amt_engine_v17.playbook_v14_shadow_state,
    amt_engine_v17.playbook_v14_shadow_trades,
    amt_engine_v17.playbook_v14_shadow_events TO amt_dashboard_ro;
GRANT EXECUTE ON FUNCTION amt_engine_v17.record_playbook_v14_shadow_event(text,text,timestamptz,jsonb)
    TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.advance_playbook_v14_shadow_cursor(timestamptz)
    TO amt_v17_writer_login;
COMMIT;
