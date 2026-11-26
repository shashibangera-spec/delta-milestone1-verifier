-- Migration: 20261126_001_v17_production_schema
-- Source baseline: amt-engine-v1-7-development (br-crimson-tooth-ao7oq469)
-- Target: production (br-snowy-water-aog0ilqw), database amt_research
-- Reproduces the approved V1.7 schema and routine definitions; does not import historical session rows.
BEGIN;
CREATE SCHEMA IF NOT EXISTS amt_engine_v17;


CREATE SEQUENCE amt_engine_v17.developing_snapshots_snapshot_id_seq

ALTER SEQUENCE amt_engine_v17.developing_snapshots_snapshot_id_seq OWNED BY amt_engine_v17.developing_snapshots.snapshot_id;

CREATE TABLE amt_engine_v17.method_config (method_version text NOT NULL, session_timezone text NOT NULL, session_start_local time without time zone NOT NULL, session_length_bars integer NOT NULL, candle_resolution text NOT NULL, row_size numeric NOT NULL, value_area_fraction numeric NOT NULL, row_anchor text NOT NULL, source_timestamp_convention text NOT NULL DEFAULT 'UNKNOWN'::text, implementation_status text NOT NULL DEFAULT 'BLOCKED_PENDING_TIMESTAMP_EVIDENCE'::text, methodology_fingerprint text, created_at timestamp with time zone NOT NULL DEFAULT now(), notes text NOT NULL, CONSTRAINT method_config_candle_resolution_check CHECK ((candle_resolution = '30m'::text)), CONSTRAINT method_config_pkey PRIMARY KEY (method_version), CONSTRAINT method_config_row_anchor_check CHECK ((row_anchor = 'ZERO'::text)), CONSTRAINT method_config_row_size_check CHECK ((row_size = (50)::numeric)), CONSTRAINT method_config_session_length_bars_check CHECK ((session_length_bars = 48)), CONSTRAINT method_config_session_start_local_check CHECK ((session_start_local = '05:30:00'::time without time zone)), CONSTRAINT method_config_session_timezone_check CHECK ((session_timezone = 'Asia/Kolkata'::text)), CONSTRAINT method_config_source_timestamp_convention_check CHECK ((source_timestamp_convention = ANY (ARRAY['UNKNOWN'::text, 'OPEN'::text, 'CLOSE'::text]))), CONSTRAINT method_config_value_area_fraction_check CHECK ((value_area_fraction = 0.70)))

CREATE TABLE amt_engine_v17.session_profiles (profile_id uuid NOT NULL DEFAULT gen_random_uuid(), session_date date NOT NULL, method_version text NOT NULL, symbol text NOT NULL, source text NOT NULL, expected_bars integer NOT NULL, observed_bars integer NOT NULL, distinct_slots integer NOT NULL, missing_slots integer NOT NULL, duplicate_slots integer NOT NULL, invalid_slots integer NOT NULL, out_of_session_count integer NOT NULL, is_complete boolean NOT NULL, profile_status text NOT NULL, reference_profile_id uuid, reference_status text NOT NULL, first_candle_open timestamp with time zone, last_candle_open timestamp with time zone, total_tpos integer NOT NULL DEFAULT 0, poc_row_index bigint, poc_lower numeric, poc_upper numeric, poc_tpo_count integer, vah_row_index bigint, vah_lower numeric, vah_upper numeric, val_row_index bigint, val_lower numeric, val_upper numeric, value_area_tpos integer, target_tpos numeric, overshoot_tpos integer, overshoot_pct numeric, scheduled_boundary timestamp with time zone NOT NULL, cutoff_at timestamp with time zone, calculated_at timestamp with time zone NOT NULL DEFAULT now(), CONSTRAINT session_profiles_expected_bars_check CHECK ((expected_bars = 48)), CONSTRAINT session_profiles_method_version_fkey FOREIGN KEY (method_version) REFERENCES amt_engine_v17.method_config(method_version), CONSTRAINT session_profiles_pkey PRIMARY KEY (profile_id), CONSTRAINT session_profiles_profile_status_check CHECK ((profile_status = ANY (ARRAY['DEVELOPING'::text, 'COMPLETE'::text, 'INCOMPLETE'::text, 'QUARANTINED'::text]))), CONSTRAINT session_profiles_reference_profile_id_fkey FOREIGN KEY (reference_profile_id) REFERENCES amt_engine_v17.session_profiles(profile_id), CONSTRAINT session_profiles_reference_status_check CHECK ((reference_status = ANY (ARRAY['AVAILABLE'::text, 'NO_VALID_REFERENCE_PROFILE'::text, 'REFERENCE_SKIPPED_INCOMPLETE'::text, 'NOT_YET_RESOLVED'::text]))), CONSTRAINT session_profiles_session_date_method_version_symbol_source_key UNIQUE (session_date, method_version, symbol, source))

CREATE TABLE amt_engine_v17.tpo_rows (profile_id uuid NOT NULL, row_index bigint NOT NULL, row_lower numeric NOT NULL, row_upper numeric NOT NULL, tpo_count integer NOT NULL, is_poc boolean NOT NULL DEFAULT false, is_value_area boolean NOT NULL DEFAULT false, CONSTRAINT tpo_rows_check CHECK (((row_upper - row_lower) = (50)::numeric)), CONSTRAINT tpo_rows_pkey PRIMARY KEY (profile_id, row_index), CONSTRAINT tpo_rows_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES amt_engine_v17.session_profiles(profile_id) ON DELETE CASCADE, CONSTRAINT tpo_rows_tpo_count_check CHECK ((tpo_count >= 0)))

CREATE TABLE amt_engine_v17.developing_snapshots (snapshot_id bigint NOT NULL DEFAULT nextval('amt_engine_v17.developing_snapshots_snapshot_id_seq'::regclass), profile_id uuid NOT NULL, session_date date NOT NULL, expected_interval_open timestamp with time zone NOT NULL, candle_open timestamp with time zone NOT NULL, candle_close timestamp with time zone NOT NULL, source text NOT NULL, symbol text NOT NULL, source_candle_identity text NOT NULL, original_source_timestamp timestamp with time zone NOT NULL, timestamp_convention text NOT NULL, source_available_at timestamp with time zone, ingested_at timestamp with time zone, method_version text NOT NULL, reference_profile_id uuid, reference_status text NOT NULL, developing_tpos integer NOT NULL, developing_poc_lower numeric, developing_poc_upper numeric, developing_poc_count integer, developing_vah_lower numeric, developing_vah_upper numeric, developing_val_lower numeric, developing_val_upper numeric, developing_value_area_tpos integer, event_state jsonb NOT NULL DEFAULT '{}'::jsonb, calculated_at timestamp with time zone NOT NULL DEFAULT now(), CONSTRAINT developing_snapshots_method_version_fkey FOREIGN KEY (method_version) REFERENCES amt_engine_v17.method_config(method_version), CONSTRAINT developing_snapshots_pkey PRIMARY KEY (snapshot_id), CONSTRAINT developing_snapshots_profile_id_candle_open_key UNIQUE (profile_id, candle_open), CONSTRAINT developing_snapshots_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES amt_engine_v17.session_profiles(profile_id), CONSTRAINT developing_snapshots_reference_profile_id_fkey FOREIGN KEY (reference_profile_id) REFERENCES amt_engine_v17.session_profiles(profile_id), CONSTRAINT developing_snapshots_timestamp_convention_check CHECK ((timestamp_convention = ANY (ARRAY['UNKNOWN'::text, 'OPEN'::text, 'CLOSE'::text]))))

CREATE TABLE amt_engine_v17.boundary_snapshots (profile_id uuid NOT NULL, session_date date NOT NULL, scheduled_boundary timestamp with time zone NOT NULL, cutoff_at timestamp with time zone NOT NULL, last_valid_completed_candle_open timestamp with time zone, last_valid_completed_candle_close timestamp with time zone, source_available_at timestamp with time zone, ingested_at timestamp with time zone, session_status text NOT NULL, active_event_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[], boundary_payload jsonb NOT NULL DEFAULT '{}'::jsonb, captured_at timestamp with time zone NOT NULL DEFAULT now(), CONSTRAINT boundary_snapshots_pkey PRIMARY KEY (profile_id), CONSTRAINT boundary_snapshots_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES amt_engine_v17.session_profiles(profile_id), CONSTRAINT boundary_snapshots_session_status_check CHECK ((session_status = ANY (ARRAY['COMPLETE'::text, 'INCOMPLETE'::text]))))

CREATE TABLE amt_engine_v17.event_episodes (event_id uuid NOT NULL DEFAULT gen_random_uuid(), profile_id uuid NOT NULL, session_date date NOT NULL, method_version text NOT NULL, direction text NOT NULL, event_type text NOT NULL, started_at timestamp with time zone NOT NULL, terminated_at timestamp with time zone, termination_reason text, status text NOT NULL, outcome_window_status text NOT NULL DEFAULT 'OPEN'::text, provisional_acceptance_at timestamp with time zone, opposite_event_id uuid, initial_event_wick_interaction_at timestamp with time zone, first_subsequent_wick_intersection_at timestamp with time zone, first_boundary_touch_only_at timestamp with time zone, first_strict_wick_penetration_at timestamp with time zone, created_at timestamp with time zone NOT NULL DEFAULT now(), previous_opposite_event_id uuid, CONSTRAINT event_episodes_direction_check CHECK ((direction = ANY (ARRAY['UPPER'::text, 'LOWER'::text]))), CONSTRAINT event_episodes_event_type_check CHECK ((event_type = ANY (ARRAY['DISCOVERY_ABOVE'::text, 'DISCOVERY_BELOW'::text]))), CONSTRAINT event_episodes_method_version_fkey FOREIGN KEY (method_version) REFERENCES amt_engine_v17.method_config(method_version), CONSTRAINT event_episodes_opposite_event_id_fkey FOREIGN KEY (opposite_event_id) REFERENCES amt_engine_v17.event_episodes(event_id), CONSTRAINT event_episodes_outcome_window_status_check CHECK ((outcome_window_status = ANY (ARRAY['OPEN'::text, 'CENSORED_SESSION_END'::text, 'COMPLETE'::text]))), CONSTRAINT event_episodes_pkey PRIMARY KEY (event_id), CONSTRAINT event_episodes_previous_opposite_event_id_fkey FOREIGN KEY (previous_opposite_event_id) REFERENCES amt_engine_v17.event_episodes(event_id), CONSTRAINT event_episodes_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES amt_engine_v17.session_profiles(profile_id), CONSTRAINT event_episodes_status_check CHECK ((status = ANY (ARRAY['ACTIVE'::text, 'RETURNED'::text, 'BOUNDARY_CLOSE'::text, 'OPPOSITE_BREACH'::text, 'UNRESOLVED_SESSION_END'::text]))), CONSTRAINT event_episodes_termination_reason_check CHECK ((termination_reason = ANY (ARRAY['RETURN_INSIDE'::text, 'BOUNDARY_CLOSE'::text, 'OPPOSITE_SIDE_BREACH'::text, 'UNRESOLVED_SESSION_END'::text]))))

CREATE TABLE amt_engine_v17.event_wick_observations (event_id uuid NOT NULL, candle_open timestamp with time zone NOT NULL, wick_intersection boolean NOT NULL, boundary_touch_only boolean NOT NULL, strict_wick_penetration boolean NOT NULL, wick_low numeric, wick_high numeric, reference_val numeric NOT NULL, reference_vah numeric NOT NULL, observed_at timestamp with time zone NOT NULL, observation_type text NOT NULL, CONSTRAINT event_wick_observations_check CHECK (((NOT boundary_touch_only) OR (wick_intersection AND (NOT strict_wick_penetration)))), CONSTRAINT event_wick_observations_check1 CHECK (((NOT strict_wick_penetration) OR wick_intersection)), CONSTRAINT event_wick_observations_event_id_fkey FOREIGN KEY (event_id) REFERENCES amt_engine_v17.event_episodes(event_id) ON DELETE CASCADE, CONSTRAINT event_wick_observations_observation_type_check CHECK ((observation_type = ANY (ARRAY['INITIAL_EVENT_CANDLE'::text, 'SUBSEQUENT_CANDLE'::text]))), CONSTRAINT event_wick_observations_pkey PRIMARY KEY (event_id, candle_open))

CREATE TABLE amt_engine_v17.session_oi_context (profile_id uuid NOT NULL, opening_oi numeric, latest_oi numeric, absolute_change numeric, percentage_change numeric, context_state text, units_verified boolean NOT NULL DEFAULT false, calculated_at timestamp with time zone NOT NULL DEFAULT now(), CONSTRAINT session_oi_context_context_state_check CHECK ((context_state = ANY (ARRAY['EXPANSION'::text, 'CONTRACTION'::text, 'UNCHANGED'::text, 'UNAVAILABLE'::text]))), CONSTRAINT session_oi_context_pkey PRIMARY KEY (profile_id), CONSTRAINT session_oi_context_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES amt_engine_v17.session_profiles(profile_id))

CREATE TABLE amt_engine_v17.source_candle_audit (source text NOT NULL, symbol text NOT NULL, series_type text NOT NULL, resolution text NOT NULL, source_candle_time timestamp with time zone NOT NULL, canonical_open_time timestamp with time zone, timestamp_convention text NOT NULL, source_available_at timestamp with time zone, ingested_at timestamp with time zone, validation_status text NOT NULL, validation_detail jsonb NOT NULL DEFAULT '{}'::jsonb, recorded_at timestamp with time zone NOT NULL DEFAULT now(), CONSTRAINT source_candle_audit_pkey PRIMARY KEY (source, symbol, series_type, resolution, source_candle_time), CONSTRAINT source_candle_audit_series_type_check CHECK ((series_type = ANY (ARRAY['PRICE'::text, 'OI'::text]))), CONSTRAINT source_candle_audit_timestamp_convention_check CHECK ((timestamp_convention = ANY (ARRAY['UNKNOWN'::text, 'OPEN'::text, 'CLOSE'::text]))), CONSTRAINT source_candle_audit_validation_status_check CHECK ((validation_status = ANY (ARRAY['UNASSESSED'::text, 'VALID'::text, 'INVALID'::text, 'DUPLICATE'::text, 'OUT_OF_SESSION'::text, 'QUARANTINED'::text]))))

CREATE TABLE amt_engine_v17.session_write_fingerprints (session_date date NOT NULL, method_version text NOT NULL, symbol text NOT NULL, source text NOT NULL, profile_id uuid NOT NULL, fingerprint_version text NOT NULL, bundle_sha256 character(64) NOT NULL, created_at timestamp with time zone NOT NULL DEFAULT now(), persisted_sha256 character(64), CONSTRAINT session_write_fingerprints_bundle_sha256_check CHECK ((bundle_sha256 ~ '^[0-9a-f]{64}$'::text)), CONSTRAINT session_write_fingerprints_fingerprint_version_check CHECK ((fingerprint_version = 'AMT_ENGINE_V1.7_BUNDLE_SHA256_V1'::text)), CONSTRAINT session_write_fingerprints_persisted_sha256_check CHECK (((persisted_sha256 IS NULL) OR (persisted_sha256 ~ '^[0-9a-f]{64}$'::text))), CONSTRAINT session_write_fingerprints_pkey PRIMARY KEY (session_date, method_version, symbol, source), CONSTRAINT session_write_fingerprints_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES amt_engine_v17.session_profiles(profile_id), CONSTRAINT session_write_fingerprints_profile_id_key UNIQUE (profile_id))

CREATE TABLE amt_engine_v17.atr14_observations (symbol text NOT NULL, source text NOT NULL, candle_open timestamp with time zone NOT NULL, true_range numeric, atr14 numeric, pre_event_atr14 numeric, sequence_valid boolean NOT NULL, reset_reason text, seed_count integer NOT NULL DEFAULT 0, calculated_at timestamp with time zone NOT NULL DEFAULT now(), CONSTRAINT atr14_observations_pkey PRIMARY KEY (symbol, source, candle_open), CONSTRAINT atr14_observations_reset_reason_check CHECK ((reset_reason = ANY (ARRAY['MISSING_INTERVAL'::text, 'INVALID_OHLC'::text, 'DUPLICATE_INTERVAL'::text, 'UNRESOLVED_INTERVAL'::text]))))

CREATE INDEX atr14_observations_symbol_source_candle_open_idx ON amt_engine_v17.atr14_observations USING btree (symbol, source, candle_open)

CREATE INDEX developing_snapshots_profile_id_candle_open_idx ON amt_engine_v17.developing_snapshots USING btree (profile_id, candle_open)

CREATE INDEX event_episodes_previous_opposite_event_id_idx ON amt_engine_v17.event_episodes USING btree (previous_opposite_event_id)

CREATE INDEX event_episodes_profile_id_started_at_idx ON amt_engine_v17.event_episodes USING btree (profile_id, started_at)

CREATE INDEX session_profiles_session_date_idx ON amt_engine_v17.session_profiles USING btree (session_date DESC)

CREATE OR REPLACE FUNCTION amt_engine_v17.calculate_profile_fixture(p_bars jsonb, p_method_version text DEFAULT 'AMT_ENGINE_V1.7'::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_result jsonb;
BEGIN
  IF p_bars IS NULL OR jsonb_typeof(p_bars) <> 'array' OR jsonb_array_length(p_bars) = 0 THEN
    RAISE EXCEPTION 'p_bars must be a non-empty JSON array';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM jsonb_to_recordset(p_bars) AS b(low numeric, high numeric)
    WHERE b.low IS NULL OR b.high IS NULL OR b.low < 0 OR b.high < b.low
  ) THEN
    RAISE EXCEPTION 'Every fixture bar must have numeric low/high, low >= 0, and high >= low';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM amt_engine_v17.method_config
    WHERE method_version = p_method_version
      AND row_size = 50
      AND value_area_fraction = 0.70
      AND row_anchor = 'ZERO'
  ) THEN
    RAISE EXCEPTION 'Method configuration not found or incompatible';
  END IF;

  WITH RECURSIVE
  bars AS (
    SELECT b.low, b.high
    FROM jsonb_to_recordset(p_bars) AS b(low numeric, high numeric)
  ),
  row_hits AS (
    SELECT gs.row_index
    FROM bars b
    CROSS JOIN LATERAL generate_series(
      floor(b.low / 50)::bigint,
      floor(b.high / 50)::bigint
    ) AS gs(row_index)
  ),
  counts AS (
    SELECT row_index, count(*)::integer AS tpo_count
    FROM row_hits
    GROUP BY row_index
  ),
  dense AS (
    SELECT gs.row_index, COALESCE(c.tpo_count, 0)::integer AS tpo_count
    FROM (SELECT min(row_index) AS lo, max(row_index) AS hi FROM counts) x
    CROSS JOIN LATERAL generate_series(x.lo, x.hi) AS gs(row_index)
    LEFT JOIN counts c USING (row_index)
  ),
  totals AS (
    SELECT sum(tpo_count)::integer AS total_tpos,
           ceil(sum(tpo_count) * 0.70)::integer AS target_tpos
    FROM dense
  ),
  poc AS (
    SELECT d.row_index, d.tpo_count
    FROM dense d
    ORDER BY d.tpo_count DESC, d.row_index ASC
    LIMIT 1
  ),
  walk(step, lo_idx, hi_idx, covered, target_tpos) AS (
    SELECT 0, p.row_index, p.row_index, p.tpo_count, t.target_tpos
    FROM poc p CROSS JOIN totals t
    UNION ALL
    SELECT
      w.step + 1,
      CASE WHEN n.choose_left THEN w.lo_idx - 1 ELSE w.lo_idx END,
      CASE WHEN n.choose_left THEN w.hi_idx ELSE w.hi_idx + 1 END,
      w.covered + CASE WHEN n.choose_left THEN c.left_count ELSE c.right_count END,
      w.target_tpos
    FROM walk w
    CROSS JOIN LATERAL (
      SELECT
        COALESCE((SELECT tpo_count FROM dense WHERE row_index = w.lo_idx - 1), 0) AS left_count,
        COALESCE((SELECT tpo_count FROM dense WHERE row_index = w.hi_idx + 1), 0) AS right_count
    ) c
    CROSS JOIN LATERAL (
      SELECT
        CASE
          WHEN w.lo_idx = (SELECT min(row_index) FROM dense) THEN false
          WHEN w.hi_idx = (SELECT max(row_index) FROM dense) THEN true
          ELSE c.left_count >= c.right_count
        END AS choose_left
    ) n
    WHERE w.covered < w.target_tpos
      AND (w.lo_idx > (SELECT min(row_index) FROM dense)
           OR w.hi_idx < (SELECT max(row_index) FROM dense))
  ),
  final_walk AS (
    SELECT * FROM walk ORDER BY step DESC LIMIT 1
  ),
  row_json AS (
    SELECT jsonb_agg(
      jsonb_build_object(
        'row_index', d.row_index,
        'row_lower', d.row_index * 50,
        'row_upper', (d.row_index + 1) * 50,
        'tpo_count', d.tpo_count,
        'is_poc', d.row_index = p.row_index,
        'is_value_area', d.row_index BETWEEN f.lo_idx AND f.hi_idx
      ) ORDER BY d.row_index
    ) AS rows
    FROM dense d CROSS JOIN poc p CROSS JOIN final_walk f
  )
  SELECT jsonb_build_object(
    'method_version', p_method_version,
    'bar_count', jsonb_array_length(p_bars),
    'total_tpos', t.total_tpos,
    'target_tpos', t.target_tpos,
    'poc_row_index', p.row_index,
    'poc_lower', p.row_index * 50,
    'poc_upper', (p.row_index + 1) * 50,
    'poc_tpo_count', p.tpo_count,
    'val_row_index', f.lo_idx,
    'val_lower', f.lo_idx * 50,
    'val_upper', (f.lo_idx + 1) * 50,
    'vah_row_index', f.hi_idx,
    'vah_lower', f.hi_idx * 50,
    'vah_upper', (f.hi_idx + 1) * 50,
    'value_area_tpos', f.covered,
    'overshoot_tpos', f.covered - f.target_tpos,
    'rows', r.rows
  )
  INTO v_result
  FROM totals t CROSS JOIN poc p CROSS JOIN final_walk f CROSS JOIN row_json r;

  RETURN v_result;
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.canonical_open_time(p_source_timestamp timestamp with time zone, p_resolution text, p_convention text)
 RETURNS timestamp with time zone
 LANGUAGE plpgsql
 IMMUTABLE
AS $function$
BEGIN
  IF p_source_timestamp IS NULL THEN
    RAISE EXCEPTION 'Source timestamp cannot be NULL';
  END IF;
  IF p_resolution <> '30m' THEN
    RAISE EXCEPTION 'Unsupported resolution: %', p_resolution;
  END IF;
  IF p_convention = 'OPEN' THEN
    RETURN p_source_timestamp;
  ELSIF p_convention = 'CLOSE' THEN
    RETURN p_source_timestamp - interval '30 minutes';
  ELSE
    RAISE EXCEPTION 'Timestamp convention is UNKNOWN or unsupported; historical session mapping is blocked';
  END IF;
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.validate_session_fixture(p_session_date date, p_bars jsonb, p_timestamp_convention text DEFAULT 'OPEN'::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_start timestamptz;
  v_end timestamptz;
  v_item jsonb;
  v_source_ts timestamptz;
  v_open_ts timestamptz;
  v_o numeric;
  v_h numeric;
  v_l numeric;
  v_c numeric;
  v_seen timestamptz[] := ARRAY[]::timestamptz[];
  v_duplicate_slots timestamptz[] := ARRAY[]::timestamptz[];
  v_invalid_slots timestamptz[] := ARRAY[]::timestamptz[];
  v_outside timestamptz[] := ARRAY[]::timestamptz[];
  v_missing timestamptz[] := ARRAY[]::timestamptz[];
  v_observed integer := 0;
  v_distinct integer := 0;
  v_invalid_count integer := 0;
  v_unmapped_invalid integer := 0;
  v_duplicate_count integer := 0;
  v_outside_count integer := 0;
  v_i integer;
  v_complete boolean;
  v_status text;
BEGIN
  IF p_session_date IS NULL THEN
    RAISE EXCEPTION 'p_session_date is required';
  END IF;
  IF p_bars IS NULL OR jsonb_typeof(p_bars) <> 'array' THEN
    RAISE EXCEPTION 'p_bars must be a JSON array';
  END IF;
  IF p_timestamp_convention NOT IN ('OPEN','CLOSE') THEN
    RAISE EXCEPTION 'Timestamp convention must be explicitly OPEN or CLOSE; UNKNOWN is blocked';
  END IF;

  v_start := ((p_session_date::timestamp + time '05:30') AT TIME ZONE 'Asia/Kolkata');
  v_end := v_start + interval '24 hours';

  FOR v_item IN SELECT value FROM jsonb_array_elements(p_bars)
  LOOP
    v_observed := v_observed + 1;
    BEGIN
      v_source_ts := (v_item->>'timestamp')::timestamptz;
      v_open_ts := amt_engine_v17.canonical_open_time(v_source_ts, '30m', p_timestamp_convention);
      v_o := NULLIF(v_item->>'open','')::numeric;
      v_h := NULLIF(v_item->>'high','')::numeric;
      v_l := NULLIF(v_item->>'low','')::numeric;
      v_c := NULLIF(v_item->>'close','')::numeric;
    EXCEPTION WHEN OTHERS THEN
      v_unmapped_invalid := v_unmapped_invalid + 1;
      CONTINUE;
    END;

    IF v_open_ts < v_start OR v_open_ts >= v_end THEN
      v_outside := array_append(v_outside, v_open_ts);
      CONTINUE;
    END IF;

    IF mod(extract(epoch FROM (v_open_ts - v_start))::bigint, 1800) <> 0 THEN
      v_unmapped_invalid := v_unmapped_invalid + 1;
      CONTINUE;
    END IF;

    IF v_open_ts = ANY(v_seen) THEN
      IF NOT (v_open_ts = ANY(v_duplicate_slots)) THEN
        v_duplicate_slots := array_append(v_duplicate_slots, v_open_ts);
      END IF;
    ELSE
      v_seen := array_append(v_seen, v_open_ts);
    END IF;

    IF v_o IS NULL OR v_h IS NULL OR v_l IS NULL OR v_c IS NULL
       OR v_l < 0 OR v_h < v_l
       OR v_o < v_l OR v_o > v_h
       OR v_c < v_l OR v_c > v_h THEN
      IF NOT (v_open_ts = ANY(v_invalid_slots)) THEN
        v_invalid_slots := array_append(v_invalid_slots, v_open_ts);
      END IF;
    END IF;
  END LOOP;

  v_distinct := cardinality(v_seen);
  v_duplicate_count := cardinality(v_duplicate_slots);
  v_invalid_count := cardinality(v_invalid_slots) + v_unmapped_invalid;
  v_outside_count := cardinality(v_outside);

  FOR v_i IN 0..47 LOOP
    IF NOT ((v_start + (v_i * interval '30 minutes')) = ANY(v_seen)) THEN
      v_missing := array_append(v_missing, v_start + (v_i * interval '30 minutes'));
    END IF;
  END LOOP;

  v_complete := v_observed = 48
    AND v_distinct = 48
    AND cardinality(v_missing) = 0
    AND v_duplicate_count = 0
    AND v_invalid_count = 0
    AND v_outside_count = 0;

  v_status := CASE WHEN v_complete THEN 'COMPLETE'
                   WHEN v_outside_count > 0 OR v_invalid_count > 0 OR v_duplicate_count > 0 THEN 'QUARANTINED'
                   ELSE 'INCOMPLETE' END;

  RETURN jsonb_build_object(
    'session_date', p_session_date,
    'session_timezone', 'Asia/Kolkata',
    'session_start', v_start,
    'session_end_exclusive', v_end,
    'timestamp_convention_used_for_fixture', p_timestamp_convention,
    'expected_bars', 48,
    'observed_bars', v_observed,
    'distinct_slots', v_distinct,
    'missing_slots', cardinality(v_missing),
    'missing_slot_opens', to_jsonb(v_missing),
    'duplicate_slots', v_duplicate_count,
    'duplicate_slot_opens', to_jsonb(v_duplicate_slots),
    'invalid_slots', v_invalid_count,
    'invalid_slot_opens', to_jsonb(v_invalid_slots),
    'out_of_session_count', v_outside_count,
    'out_of_session_opens', to_jsonb(v_outside),
    'is_complete', v_complete,
    'profile_status', v_status
  );
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.build_developing_snapshots_fixture(p_session_date date, p_bars jsonb, p_timestamp_convention text DEFAULT 'OPEN'::text, p_method_version text DEFAULT 'AMT_ENGINE_V1.7'::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_start timestamptz; v_end timestamptz; v_norm jsonb; v_bar jsonb;
  v_prefix jsonb := '[]'::jsonb; v_snapshots jsonb := '[]'::jsonb;
  v_open timestamptz; v_prev timestamptz := NULL; v_count integer := 0;
  v_o numeric; v_h numeric; v_l numeric; v_c numeric; v_profile jsonb;
BEGIN
  IF p_session_date IS NULL THEN RAISE EXCEPTION 'p_session_date is required'; END IF;
  IF p_bars IS NULL OR jsonb_typeof(p_bars) <> 'array' OR jsonb_array_length(p_bars)=0 THEN
    RAISE EXCEPTION 'p_bars must be a non-empty JSON array';
  END IF;
  IF p_timestamp_convention NOT IN ('OPEN','CLOSE') THEN
    RAISE EXCEPTION 'Explicit OPEN or CLOSE convention required; UNKNOWN is blocked';
  END IF;
  v_start := ((p_session_date::timestamp + time '05:30') AT TIME ZONE 'Asia/Kolkata');
  v_end := v_start + interval '24 hours';
  IF EXISTS (SELECT 1 FROM jsonb_to_recordset(p_bars) AS x(candle_id text, source_timestamp timestamptz, open numeric, high numeric, low numeric, close numeric)
             WHERE candle_id IS NULL OR source_timestamp IS NULL OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL) THEN
    RAISE EXCEPTION 'Every candle requires identity, source timestamp and complete OHLC';
  END IF;
  SELECT jsonb_agg(jsonb_build_object(
    'candle_id',x.candle_id,'source_timestamp',x.source_timestamp,
    'canonical_open_time',amt_engine_v17.canonical_open_time(x.source_timestamp,'30m',p_timestamp_convention),
    'open',x.open,'high',x.high,'low',x.low,'close',x.close
  ) ORDER BY amt_engine_v17.canonical_open_time(x.source_timestamp,'30m',p_timestamp_convention),x.candle_id)
  INTO v_norm
  FROM jsonb_to_recordset(p_bars) AS x(candle_id text,source_timestamp timestamptz,open numeric,high numeric,low numeric,close numeric);

  FOR v_bar IN SELECT value FROM jsonb_array_elements(v_norm) ORDER BY (value->>'canonical_open_time')::timestamptz
  LOOP
    v_open := (v_bar->>'canonical_open_time')::timestamptz;
    v_o := (v_bar->>'open')::numeric; v_h := (v_bar->>'high')::numeric;
    v_l := (v_bar->>'low')::numeric; v_c := (v_bar->>'close')::numeric;
    IF v_open < v_start OR v_open >= v_end THEN RAISE EXCEPTION 'Out-of-session candle quarantined: %',v_open; END IF;
    IF mod(extract(epoch FROM (v_open-v_start))::bigint,1800) <> 0 THEN RAISE EXCEPTION 'Misaligned candle timestamp: %',v_open; END IF;
    IF v_prev IS NOT NULL AND v_open = v_prev THEN RAISE EXCEPTION 'Duplicate canonical candle slot: %',v_open; END IF;
    IF v_l < 0 OR v_h < v_l OR v_o < v_l OR v_o > v_h OR v_c < v_l OR v_c > v_h THEN
      RAISE EXCEPTION 'Invalid OHLC candle: %',v_open;
    END IF;
    v_prev := v_open; v_count := v_count+1;
    v_prefix := v_prefix || jsonb_build_array(jsonb_build_object('low',v_l,'high',v_h));
    v_profile := amt_engine_v17.calculate_profile_fixture(v_prefix,p_method_version);
    v_snapshots := v_snapshots || jsonb_build_array(jsonb_build_object(
      'session_date',p_session_date,'method_version',p_method_version,'snapshot_sequence',v_count,
      'candle_id',v_bar->>'candle_id','source_timestamp',v_bar->>'source_timestamp',
      'canonical_open_time',v_open,'canonical_close_time',v_open+interval '30 minutes',
      'developing_profile',v_profile
    ));
  END LOOP;
  RETURN jsonb_build_object(
    'session_date',p_session_date,'method_version',p_method_version,
    'timestamp_convention_used_for_fixture',p_timestamp_convention,'snapshot_count',v_count,
    'is_finalizable',v_count=48 AND v_prev=v_start+interval '23 hours 30 minutes',
    'snapshots',v_snapshots
  );
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.finalize_profile_fixture(p_session_date date, p_bars jsonb, p_timestamp_convention text, p_method_version text DEFAULT 'AMT_ENGINE_V1.7'::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_validation jsonb;
  v_levels jsonb;
  v_rows jsonb;
  v_final_open timestamptz;
BEGIN
  v_validation := amt_engine_v17.validate_session_fixture(p_session_date,p_bars,p_timestamp_convention);
  IF COALESCE((v_validation->>'is_complete')::boolean,false) IS NOT TRUE THEN
    RAISE EXCEPTION 'Profile cannot be finalized: session validation status % (observed %, distinct %, missing %, duplicate %, invalid %, out-of-session %)',
      v_validation->>'profile_status',v_validation->>'observed_bars',v_validation->>'distinct_slots',
      v_validation->>'missing_slots',v_validation->>'duplicate_slots',v_validation->>'invalid_slots',
      v_validation->>'out_of_session_count';
  END IF;
  SELECT jsonb_agg(jsonb_build_object('low',x.low,'high',x.high) ORDER BY
    amt_engine_v17.canonical_open_time(x.timestamp,'30m',p_timestamp_convention))
  INTO v_rows
  FROM jsonb_to_recordset(p_bars) AS x(timestamp timestamptz,low numeric,high numeric);
  v_levels := amt_engine_v17.calculate_profile_fixture(v_rows,p_method_version);
  v_final_open := ((p_session_date::timestamp + time '05:30') AT TIME ZONE 'Asia/Kolkata') + interval '23 hours 30 minutes';
  RETURN jsonb_build_object(
    'session_date',p_session_date,
    'method_version',p_method_version,
    'profile_status','COMPLETE',
    'session_validation',v_validation,
    'final_candle_open',v_final_open,
    'final_candle_close',v_final_open+interval '30 minutes',
    'reference_profile_id',NULL,
    'reference_status','NOT_YET_RESOLVED',
    'profile',v_levels,
    'persisted',false
  );
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.resolve_reference_fixture(p_current_session_date date, p_prior_profiles jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_selected record;
  v_skipped date[];
  v_skipped_count integer := 0;
  v_status text;
BEGIN
  IF p_current_session_date IS NULL THEN
    RAISE EXCEPTION 'Current session date is required';
  END IF;
  IF p_prior_profiles IS NULL OR jsonb_typeof(p_prior_profiles) <> 'array' THEN
    RAISE EXCEPTION 'Prior profiles must be a JSON array';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM jsonb_to_recordset(p_prior_profiles) AS p(
      session_date date, profile_id text, profile_status text, is_complete boolean
    )
    WHERE p.session_date IS NULL
       OR p.profile_status IS NULL
       OR p.is_complete IS NULL
       OR (p.is_complete AND (p.profile_id IS NULL OR p.profile_id = ''))
  ) THEN
    RAISE EXCEPTION 'Each candidate requires session_date, profile_status and is_complete; complete candidates also require profile_id';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM jsonb_to_recordset(p_prior_profiles) AS p(
      session_date date, profile_id text, profile_status text, is_complete boolean
    )
    WHERE p.session_date >= p_current_session_date
  ) THEN
    RAISE EXCEPTION 'Reference candidates must be strictly earlier than current session';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM jsonb_to_recordset(p_prior_profiles) AS p(
      session_date date, profile_id text, profile_status text, is_complete boolean
    )
    GROUP BY p.session_date HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION 'Duplicate candidate session dates are not permitted';
  END IF;

  SELECT p.session_date, p.profile_id, p.profile_status, p.is_complete
  INTO v_selected
  FROM jsonb_to_recordset(p_prior_profiles) AS p(
    session_date date, profile_id text, profile_status text, is_complete boolean
  )
  WHERE p.session_date < p_current_session_date
    AND p.profile_status = 'COMPLETE'
    AND p.is_complete IS TRUE
  ORDER BY p.session_date DESC
  LIMIT 1;

  SELECT COALESCE(array_agg(p.session_date ORDER BY p.session_date), ARRAY[]::date[])
  INTO v_skipped
  FROM jsonb_to_recordset(p_prior_profiles) AS p(
    session_date date, profile_id text, profile_status text, is_complete boolean
  )
  WHERE p.session_date < p_current_session_date
    AND (v_selected.session_date IS NULL OR p.session_date > v_selected.session_date)
    AND NOT (p.profile_status = 'COMPLETE' AND p.is_complete IS TRUE);

  v_skipped_count := cardinality(v_skipped);

  IF v_selected.session_date IS NULL THEN
    v_status := 'NO_VALID_REFERENCE_PROFILE';
  ELSIF v_skipped_count > 0 THEN
    v_status := 'REFERENCE_SKIPPED_INCOMPLETE';
  ELSE
    v_status := 'AVAILABLE';
  END IF;

  RETURN jsonb_build_object(
    'current_session_date', p_current_session_date,
    'reference_profile_id', v_selected.profile_id,
    'reference_session_date', v_selected.session_date,
    'reference_status', v_status,
    'skipped_incomplete_sessions', to_jsonb(v_skipped),
    'skipped_incomplete_count', v_skipped_count,
    'selection_rule', 'MOST_RECENT_EARLIER_COMPLETE_PROFILE'
  );
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.build_event_episodes_fixture(p_session_date date, p_bars jsonb, p_prior_vah numeric, p_prior_val numeric)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
 v_start timestamptz; v_end timestamptz; v_bar jsonb; v_open timestamptz;
 v_close numeric; v_prev timestamptz:=NULL; v_active_direction text:=NULL;
 v_active_id text:=NULL; v_active_opposite_id text:=NULL;
 v_active_started timestamptz; v_inside_count integer:=0; v_event_seq integer:=0;
 v_events jsonb:='[]'::jsonb; v_new_id text; v_old_id text;
 v_opposite_direction text; v_completed_at timestamptz;
BEGIN
 IF p_session_date IS NULL OR p_prior_vah IS NULL OR p_prior_val IS NULL OR p_prior_vah<=p_prior_val THEN
  RAISE EXCEPTION 'Session date and valid prior value area (VAH > VAL) are required';
 END IF;
 IF p_bars IS NULL OR jsonb_typeof(p_bars)<>'array' OR jsonb_array_length(p_bars)=0 THEN
  RAISE EXCEPTION 'p_bars must be a non-empty JSON array';
 END IF;
 IF EXISTS (
  SELECT 1 FROM jsonb_to_recordset(p_bars) AS b(candle_id text,canonical_open_time timestamptz,open numeric,high numeric,low numeric,close numeric)
  WHERE b.candle_id IS NULL OR b.canonical_open_time IS NULL OR b.open IS NULL OR b.high IS NULL OR b.low IS NULL OR b.close IS NULL
   OR b.low<0 OR b.high<b.low OR b.open<b.low OR b.open>b.high OR b.close<b.low OR b.close>b.high
 ) THEN RAISE EXCEPTION 'Every event fixture candle requires identity, canonical timestamp and valid OHLC'; END IF;
 v_start:=((p_session_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata');
 v_end:=v_start+interval '24 hours';
 FOR v_bar IN SELECT value FROM jsonb_array_elements(p_bars) ORDER BY (value->>'canonical_open_time')::timestamptz LOOP
  v_open:=(v_bar->>'canonical_open_time')::timestamptz;
  v_close:=(v_bar->>'close')::numeric;
  v_completed_at:=v_open+interval '30 minutes';
  IF v_open<v_start OR v_open>=v_end THEN RAISE EXCEPTION 'Out-of-session event candle: %',v_open; END IF;
  IF mod(extract(epoch FROM (v_open-v_start))::bigint,1800)<>0 THEN RAISE EXCEPTION 'Misaligned event candle: %',v_open; END IF;
  IF v_prev IS NOT NULL AND v_open<=v_prev THEN RAISE EXCEPTION 'Duplicate or unordered event candle: %',v_open; END IF;
  v_prev:=v_open;
  v_opposite_direction:=CASE WHEN v_close>p_prior_vah THEN 'UPPER'
    WHEN v_close<p_prior_val THEN 'LOWER' ELSE NULL END;
  IF v_active_direction IS NULL THEN
   IF v_opposite_direction IS NOT NULL THEN
    v_event_seq:=v_event_seq+1; v_active_id:='E'||v_event_seq::text;
    v_active_direction:=v_opposite_direction; v_active_started:=v_open;
    v_active_opposite_id:=NULL; v_inside_count:=0;
   END IF;
  ELSIF v_opposite_direction IS NOT NULL AND v_opposite_direction<>v_active_direction THEN
   v_event_seq:=v_event_seq+1; v_new_id:='E'||v_event_seq::text; v_old_id:=v_active_id;
   v_events:=v_events||jsonb_build_array(jsonb_build_object(
    'event_id',v_active_id,'direction',v_active_direction,
    'event_type',CASE WHEN v_active_direction='UPPER' THEN 'DISCOVERY_ABOVE' ELSE 'DISCOVERY_BELOW' END,
    'started_at',v_active_started,'terminated_at',v_completed_at,
    'termination_reason','OPPOSITE_SIDE_BREACH','status','OPPOSITE_BREACH',
    'provisional_acceptance_at',NULL,'opposite_event_id',v_new_id,
    'previous_opposite_event_id',v_active_opposite_id
   ));
   v_active_id:=v_new_id; v_active_direction:=v_opposite_direction;
   v_active_started:=v_open; v_active_opposite_id:=v_old_id; v_inside_count:=0;
  ELSIF v_opposite_direction=v_active_direction THEN
   v_inside_count:=0;
  ELSIF v_close>p_prior_val AND v_close<p_prior_vah THEN
   v_inside_count:=v_inside_count+1;
   IF v_inside_count>=2 THEN
    v_events:=v_events||jsonb_build_array(jsonb_build_object(
     'event_id',v_active_id,'direction',v_active_direction,
     'event_type',CASE WHEN v_active_direction='UPPER' THEN 'DISCOVERY_ABOVE' ELSE 'DISCOVERY_BELOW' END,
     'started_at',v_active_started,'terminated_at',v_completed_at,
     'termination_reason','RETURN_INSIDE','status','RETURNED',
     'provisional_acceptance_at',v_completed_at,'opposite_event_id',NULL,
     'previous_opposite_event_id',v_active_opposite_id
    ));
    v_active_direction:=NULL; v_active_id:=NULL; v_active_opposite_id:=NULL;
    v_active_started:=NULL; v_inside_count:=0;
   END IF;
  ELSE
   v_inside_count:=0;
  END IF;
 END LOOP;
 IF v_active_direction IS NOT NULL THEN
  v_events:=v_events||jsonb_build_array(jsonb_build_object(
   'event_id',v_active_id,'direction',v_active_direction,
   'event_type',CASE WHEN v_active_direction='UPPER' THEN 'DISCOVERY_ABOVE' ELSE 'DISCOVERY_BELOW' END,
   'started_at',v_active_started,'terminated_at',v_end,
   'termination_reason','UNRESOLVED_SESSION_END','status','UNRESOLVED_SESSION_END',
   'provisional_acceptance_at',NULL,'opposite_event_id',NULL,
   'previous_opposite_event_id',v_active_opposite_id
  ));
 END IF;
 RETURN jsonb_build_object('session_date',p_session_date,'prior_vah',p_prior_vah,'prior_val',p_prior_val,
  'event_count',jsonb_array_length(v_events),'events',v_events,'session_end',v_end,'persisted',false);
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.classify_event_wick_fixture(p_direction text, p_event_started_at timestamp with time zone, p_candle_open_time timestamp with time zone, p_open numeric, p_high numeric, p_low numeric, p_close numeric, p_reference_vah numeric, p_reference_val numeric)
 RETURNS jsonb
 LANGUAGE plpgsql
 IMMUTABLE
AS $function$
DECLARE
  v_wick_low numeric;
  v_wick_high numeric;
  v_nonzero boolean;
  v_intersection boolean := false;
  v_boundary_only boolean := false;
  v_strict boolean := false;
BEGIN
  IF p_direction NOT IN ('UPPER','LOWER') THEN RAISE EXCEPTION 'Direction must be UPPER or LOWER'; END IF;
  IF p_event_started_at IS NULL OR p_candle_open_time IS NULL OR p_open IS NULL OR p_high IS NULL OR p_low IS NULL OR p_close IS NULL
     OR p_reference_vah IS NULL OR p_reference_val IS NULL OR p_reference_vah <= p_reference_val THEN
    RAISE EXCEPTION 'Complete event, candle and prior value-area inputs are required';
  END IF;
  IF p_low < 0 OR p_high < p_low OR p_open < p_low OR p_open > p_high OR p_close < p_low OR p_close > p_high THEN
    RAISE EXCEPTION 'Invalid OHLC candle';
  END IF;

  IF p_direction = 'UPPER' THEN
    v_wick_low := p_low;
    v_wick_high := LEAST(p_open,p_close);
  ELSE
    v_wick_low := GREATEST(p_open,p_close);
    v_wick_high := p_high;
  END IF;
  v_nonzero := v_wick_high > v_wick_low;

  IF v_nonzero THEN
    v_intersection := v_wick_high >= p_reference_val AND v_wick_low <= p_reference_vah;
    IF p_direction = 'UPPER' THEN
      v_boundary_only := v_wick_low = p_reference_vah;
      v_strict := v_wick_low < p_reference_vah AND v_wick_high > p_reference_val;
    ELSE
      v_boundary_only := v_wick_high = p_reference_val;
      v_strict := v_wick_high > p_reference_val AND v_wick_low < p_reference_vah;
    END IF;
  END IF;

  RETURN jsonb_build_object(
    'direction',p_direction,
    'candle_open_time',p_candle_open_time,
    'observed_at',p_candle_open_time+interval '30 minutes',
    'observation_type',CASE WHEN p_candle_open_time=p_event_started_at THEN 'INITIAL_EVENT_CANDLE' ELSE 'SUBSEQUENT_CANDLE' END,
    'wick_low',v_wick_low,'wick_high',v_wick_high,
    'wick_intersection',v_intersection,
    'boundary_touch_only',v_boundary_only,
    'strict_wick_penetration',v_strict,
    'zero_length_wick',NOT v_nonzero
  );
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.calculate_atr14_fixture(p_bars jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_item jsonb;
  v_rows jsonb := '[]'::jsonb;
  v_open timestamptz;
  v_prev_open timestamptz := NULL;
  v_prev_close numeric := NULL;
  v_high numeric; v_low numeric; v_close numeric;
  v_tr numeric;
  v_atr numeric := NULL;
  v_seed numeric[] := ARRAY[]::numeric[];
  v_seed_count integer := 0;
  v_slot_count integer;
  v_resolved boolean;
  v_reset_reason text;
  v_sequence_valid boolean;
  v_needs_first_after_break boolean := false;
  v_started boolean := false;
  v_true_range numeric;
BEGIN
  IF p_bars IS NULL OR jsonb_typeof(p_bars) <> 'array' OR jsonb_array_length(p_bars)=0 THEN
    RAISE EXCEPTION 'p_bars must be a non-empty JSON array';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_to_recordset(p_bars) AS b(candle_id text,canonical_open_time timestamptz,high numeric,low numeric,close numeric)
    WHERE b.candle_id IS NULL OR b.canonical_open_time IS NULL
  ) THEN RAISE EXCEPTION 'Each ATR fixture candle requires identity and canonical timestamp'; END IF;

  FOR v_item IN
    SELECT jsonb_build_object(
      'candle_id',b.candle_id,'canonical_open_time',b.canonical_open_time,
      'high',b.high,'low',b.low,'close',b.close,
      'is_resolved',COALESCE(b.is_resolved,true),
      'slot_count',count(*) OVER (PARTITION BY b.canonical_open_time)
    )
    FROM jsonb_to_recordset(p_bars) AS b(
      candle_id text,canonical_open_time timestamptz,
      high numeric,low numeric,close numeric,is_resolved boolean
    )
    ORDER BY b.canonical_open_time,b.candle_id
  LOOP
    v_open := (v_item->>'canonical_open_time')::timestamptz;
    v_high := NULLIF(v_item->>'high','')::numeric;
    v_low := NULLIF(v_item->>'low','')::numeric;
    v_close := NULLIF(v_item->>'close','')::numeric;
    v_slot_count := (v_item->>'slot_count')::integer;
    v_resolved := (v_item->>'is_resolved')::boolean;
    v_tr := NULL; v_reset_reason := NULL; v_sequence_valid := false;

    IF v_slot_count > 1 THEN
      v_reset_reason := 'DUPLICATE_INTERVAL';
      v_seed := ARRAY[]::numeric[]; v_seed_count := 0; v_atr := NULL;
      v_prev_open := NULL; v_prev_close := NULL; v_needs_first_after_break := true; v_started := true;
    ELSIF NOT v_resolved THEN
      v_reset_reason := 'UNRESOLVED_INTERVAL';
      v_seed := ARRAY[]::numeric[]; v_seed_count := 0; v_atr := NULL;
      v_prev_open := NULL; v_prev_close := NULL; v_needs_first_after_break := true; v_started := true;
    ELSIF v_high IS NULL OR v_low IS NULL OR v_close IS NULL OR v_low < 0 OR v_high < v_low OR v_close < v_low OR v_close > v_high THEN
      v_reset_reason := 'INVALID_OHLC';
      v_seed := ARRAY[]::numeric[]; v_seed_count := 0; v_atr := NULL;
      v_prev_open := NULL; v_prev_close := NULL; v_needs_first_after_break := true; v_started := true;
    ELSIF mod(extract(epoch FROM v_open)::bigint,1800) <> 0 THEN
      v_reset_reason := 'UNRESOLVED_INTERVAL';
      v_seed := ARRAY[]::numeric[]; v_seed_count := 0; v_atr := NULL;
      v_prev_open := NULL; v_prev_close := NULL; v_needs_first_after_break := true; v_started := true;
    ELSIF v_prev_open IS NOT NULL AND v_open <> v_prev_open + interval '30 minutes' THEN
      v_reset_reason := 'MISSING_INTERVAL';
      v_seed := ARRAY[]::numeric[]; v_seed_count := 0; v_atr := NULL;
      v_prev_open := v_open; v_prev_close := v_close; v_needs_first_after_break := false; v_started := true;
    ELSIF v_needs_first_after_break THEN
      v_prev_open := v_open; v_prev_close := v_close;
      v_needs_first_after_break := false; v_started := true;
    ELSE
      IF NOT v_started THEN
        v_tr := v_high-v_low;
      ELSE
        v_tr := GREATEST(v_high-v_low,abs(v_high-v_prev_close),abs(v_low-v_prev_close));
      END IF;
      v_sequence_valid := true;
      v_seed_count := v_seed_count+1;
      IF v_seed_count <= 14 THEN
        v_seed := array_append(v_seed,v_tr);
        IF v_seed_count = 14 THEN
          SELECT avg(x) INTO v_atr FROM unnest(v_seed) x;
        END IF;
      ELSE
        v_atr := ((v_atr*13)+v_tr)/14;
      END IF;
      v_prev_open := v_open; v_prev_close := v_close; v_started := true;
    END IF;

    v_rows := v_rows || jsonb_build_array(jsonb_build_object(
      'candle_id',v_item->>'candle_id',
      'candle_open',v_open,
      'true_range',v_tr,
      'atr14',v_atr,
      'pre_event_atr14',NULL,
      'sequence_valid',v_sequence_valid,
      'reset_reason',v_reset_reason,
      'seed_count',v_seed_count
    ));
  END LOOP;

  RETURN jsonb_build_object('observation_count',jsonb_array_length(v_rows),'observations',v_rows,'persisted',false);
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.calculate_session_oi_context_fixture(p_opening_oi numeric, p_latest_oi numeric, p_units_verified boolean)
 RETURNS jsonb
 LANGUAGE plpgsql
 IMMUTABLE
AS $function$
DECLARE v_change numeric; v_pct numeric; v_state text;
BEGIN
  IF p_opening_oi IS NULL OR p_latest_oi IS NULL OR p_opening_oi<=0 OR p_latest_oi<0 THEN
    RETURN jsonb_build_object('opening_oi',p_opening_oi,'latest_oi',p_latest_oi,
      'absolute_change',NULL,'percentage_change',NULL,'context_state','UNAVAILABLE',
      'units_verified',COALESCE(p_units_verified,false),'interpretation','NON_DIRECTIONAL_CONTEXT_ONLY');
  END IF;
  v_change:=p_latest_oi-p_opening_oi; v_pct:=100*v_change/p_opening_oi;
  v_state:=CASE WHEN v_change>0 THEN 'EXPANSION' WHEN v_change<0 THEN 'CONTRACTION' ELSE 'UNCHANGED' END;
  RETURN jsonb_build_object('opening_oi',p_opening_oi,'latest_oi',p_latest_oi,
    'absolute_change',v_change,'percentage_change',v_pct,'context_state',v_state,
    'units_verified',COALESCE(p_units_verified,false),'interpretation','NON_DIRECTIONAL_CONTEXT_ONLY');
END; $function$


CREATE OR REPLACE FUNCTION amt_engine_v17.build_boundary_snapshot_fixture(p_session_date date, p_cutoff_at timestamp with time zone, p_records jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
 v_boundary timestamptz;
 v_last record;
 v_excluded_late integer:=0;
 v_not_completed integer:=0;
 v_status text;
BEGIN
 IF p_session_date IS NULL OR p_cutoff_at IS NULL THEN
  RAISE EXCEPTION 'Session date and explicit cutoff timestamp are required';
 END IF;
 IF p_records IS NULL OR jsonb_typeof(p_records)<>'array' THEN
  RAISE EXCEPTION 'Boundary source records must be a JSON array';
 END IF;
 v_boundary:=((p_session_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata')+interval '24 hours';
 IF p_cutoff_at>v_boundary THEN
  RAISE EXCEPTION 'Cutoff cannot be later than the fixed session boundary';
 END IF;
 IF EXISTS (
  SELECT 1 FROM jsonb_to_recordset(p_records) AS r(
   candle_id text,candle_open timestamptz,candle_close timestamptz,
   source_available_at timestamptz,ingested_at timestamptz,is_valid boolean)
  WHERE candle_id IS NULL OR candle_open IS NULL OR candle_close IS NULL
   OR source_available_at IS NULL OR ingested_at IS NULL OR is_valid IS NULL
   OR candle_close<>candle_open+interval '30 minutes'
 ) THEN
  RAISE EXCEPTION 'Boundary records require identity, timestamps, validity and exact 30m interval';
 END IF;
 -- Source availability remains strict at cutoff; only ingestion receipt gets 10 minutes.
 SELECT count(*) INTO v_excluded_late
 FROM jsonb_to_recordset(p_records) AS r(
  candle_id text,candle_open timestamptz,candle_close timestamptz,
  source_available_at timestamptz,ingested_at timestamptz,is_valid boolean)
 WHERE r.candle_close<=p_cutoff_at
  AND (r.source_available_at>p_cutoff_at
       OR r.ingested_at>p_cutoff_at+interval '10 minutes');
 SELECT count(*) INTO v_not_completed
 FROM jsonb_to_recordset(p_records) AS r(
  candle_id text,candle_open timestamptz,candle_close timestamptz,
  source_available_at timestamptz,ingested_at timestamptz,is_valid boolean)
 WHERE r.candle_close>p_cutoff_at AND r.candle_close<=v_boundary;
 SELECT r.candle_id,r.candle_open,r.candle_close,
  r.source_available_at,r.ingested_at,r.is_valid
 INTO v_last
 FROM jsonb_to_recordset(p_records) AS r(
  candle_id text,candle_open timestamptz,candle_close timestamptz,
  source_available_at timestamptz,ingested_at timestamptz,is_valid boolean)
 WHERE r.is_valid IS TRUE
  AND r.candle_close<=v_boundary
  AND r.candle_close<=p_cutoff_at
  AND r.source_available_at<=p_cutoff_at
  AND r.ingested_at<=p_cutoff_at+interval '10 minutes'
 ORDER BY r.candle_close DESC,r.candle_id
 LIMIT 1;
 v_status:=CASE WHEN v_last.candle_close=v_boundary THEN 'COMPLETE' ELSE 'INCOMPLETE' END;
 RETURN jsonb_build_object(
  'session_date',p_session_date,'scheduled_boundary',v_boundary,'cutoff_at',p_cutoff_at,
  'last_valid_candle_id',v_last.candle_id,
  'last_valid_completed_candle_open',v_last.candle_open,
  'last_valid_completed_candle_close',v_last.candle_close,
  'source_available_at',v_last.source_available_at,'ingested_at',v_last.ingested_at,
  'session_status',v_status,'late_records_excluded',v_excluded_late,
  'records_not_yet_completed_at_cutoff',v_not_completed,
  'late_arrivals_can_rewrite_snapshot',false,'persisted',false
 );
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.integrate_event_context_fixture(p_session_date date, p_bars jsonb, p_prior_vah numeric, p_prior_val numeric)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_event_result jsonb;
  v_atr_result jsonb;
  v_events jsonb := '[]'::jsonb;
  v_event jsonb;
  v_obs jsonb := '[]'::jsonb;
  v_bar jsonb;
  v_atr jsonb;
  v_start timestamptz;
  v_end timestamptz;
  v_pre_atr numeric;
  v_pre_atr_open timestamptz;
  v_item jsonb;
  v_direction text;
BEGIN
  v_event_result:=amt_engine_v17.build_event_episodes_fixture(p_session_date,p_bars,p_prior_vah,p_prior_val);
  SELECT jsonb_agg(jsonb_build_object(
    'candle_id',b.candle_id,'canonical_open_time',b.canonical_open_time,
    'high',b.high,'low',b.low,'close',b.close,'is_resolved',COALESCE(b.is_resolved,true)
  ) ORDER BY b.canonical_open_time)
  INTO v_item
  FROM jsonb_to_recordset(p_bars) AS b(
    candle_id text,canonical_open_time timestamptz,high numeric,low numeric,close numeric,is_resolved boolean
  );
  v_atr_result:=amt_engine_v17.calculate_atr14_fixture(v_item);

  FOR v_event IN SELECT value FROM jsonb_array_elements(v_event_result->'events') LOOP
    v_start:=(v_event->>'started_at')::timestamptz;
    v_end:=COALESCE((v_event->>'terminated_at')::timestamptz,
      (((p_session_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata')+interval '24 hours'));
    v_direction:=v_event->>'direction';
    v_pre_atr:=NULL; v_pre_atr_open:=NULL;

    SELECT (a->>'atr14')::numeric,(a->>'candle_open')::timestamptz
    INTO v_pre_atr,v_pre_atr_open
    FROM jsonb_array_elements(v_atr_result->'observations') a
    WHERE (a->>'candle_open')::timestamptz < v_start
      AND (a->>'atr14') IS NOT NULL
    ORDER BY (a->>'candle_open')::timestamptz DESC LIMIT 1;

    v_obs:='[]'::jsonb;
    FOR v_bar IN
      SELECT value FROM jsonb_array_elements(p_bars)
      WHERE (value->>'canonical_open_time')::timestamptz >= v_start
        AND (value->>'canonical_open_time')::timestamptz < v_end
      ORDER BY (value->>'canonical_open_time')::timestamptz
    LOOP
      v_obs:=v_obs || jsonb_build_array(
        amt_engine_v17.classify_event_wick_fixture(
          v_direction,v_start,(v_bar->>'canonical_open_time')::timestamptz,
          (v_bar->>'open')::numeric,(v_bar->>'high')::numeric,
          (v_bar->>'low')::numeric,(v_bar->>'close')::numeric,
          p_prior_vah,p_prior_val
        )
      );
    END LOOP;

    v_event:=v_event || jsonb_build_object(
      'pre_event_atr14',v_pre_atr,
      'pre_event_atr14_candle_open',v_pre_atr_open,
      'wick_observations',v_obs
    );
    v_events:=v_events || jsonb_build_array(v_event);
  END LOOP;

  RETURN jsonb_build_object(
    'session_date',p_session_date,'prior_vah',p_prior_vah,'prior_val',p_prior_val,
    'events',v_events,'event_count',jsonb_array_length(v_events),
    'atr_observations',v_atr_result->'observations',
    'persisted',false
  );
END; $function$


CREATE OR REPLACE FUNCTION amt_engine_v17.persist_profile_bundle(p_bundle jsonb, p_test_mode boolean DEFAULT false)
 RETURNS uuid
 LANGUAGE plpgsql
AS $function$
DECLARE
  p jsonb;
  v_profile_id uuid;
  v_expected integer;
  v_observed integer;
  v_distinct integer;
  v_convention text;
  v_status text;
  v_row jsonb;
  v_row_count integer:=0;
BEGIN
  IF p_bundle IS NULL OR jsonb_typeof(p_bundle)<>'object' OR jsonb_typeof(p_bundle->'profile')<>'object'
     OR jsonb_typeof(p_bundle->'rows')<>'array' THEN
    RAISE EXCEPTION 'Bundle must contain profile object and rows array';
  END IF;
  p:=p_bundle->'profile';

  SELECT source_timestamp_convention INTO v_convention
  FROM amt_engine_v17.method_config
  WHERE method_version=p->>'method_version';
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown method version'; END IF;

  IF p_test_mode IS DISTINCT FROM true AND v_convention NOT IN ('OPEN','CLOSE') THEN
    RAISE EXCEPTION 'Writer blocked: source timestamp convention is not verified';
  END IF;
  IF p_test_mode IS TRUE AND COALESCE(p->>'symbol','') NOT LIKE 'TEST\_%' ESCAPE '\' THEN
    RAISE EXCEPTION 'Test mode is restricted to TEST_ symbols';
  END IF;

  v_expected:=COALESCE((p->>'expected_bars')::integer,0);
  v_observed:=COALESCE((p->>'observed_bars')::integer,0);
  v_distinct:=COALESCE((p->>'distinct_slots')::integer,0);
  v_status:=COALESCE(p->>'profile_status','');
  IF v_expected<>48 OR v_observed<>48 OR v_distinct<>48
     OR COALESCE((p->>'missing_slots')::integer,-1)<>0
     OR COALESCE((p->>'duplicate_slots')::integer,-1)<>0
     OR COALESCE((p->>'invalid_slots')::integer,-1)<>0
     OR COALESCE((p->>'out_of_session_count')::integer,-1)<>0
     OR v_status<>'COMPLETE'
     OR COALESCE((p->>'is_complete')::boolean,false) IS NOT TRUE THEN
    RAISE EXCEPTION 'Writer guard: only a fully validated 48-candle COMPLETE profile can be persisted';
  END IF;

  IF (p->>'scheduled_boundary') IS NULL OR (p->>'cutoff_at') IS NULL
     OR (p->>'cutoff_at')::timestamptz>(p->>'scheduled_boundary')::timestamptz THEN
    RAISE EXCEPTION 'Writer guard: explicit cutoff at or before scheduled boundary is required';
  END IF;
  IF (p->>'session_date')::date >= (now() AT TIME ZONE 'Asia/Kolkata')::date THEN
    RAISE EXCEPTION 'Writer guard: session must be closed before persistence';
  END IF;
  IF jsonb_array_length(p_bundle->'rows')=0 THEN RAISE EXCEPTION 'Complete profile requires TPO rows'; END IF;

  INSERT INTO amt_engine_v17.session_profiles(
    session_date,method_version,symbol,source,expected_bars,observed_bars,distinct_slots,
    missing_slots,duplicate_slots,invalid_slots,out_of_session_count,is_complete,profile_status,
    reference_profile_id,reference_status,first_candle_open,last_candle_open,total_tpos,
    poc_row_index,poc_lower,poc_upper,poc_tpo_count,vah_row_index,vah_lower,vah_upper,
    val_row_index,val_lower,val_upper,value_area_tpos,target_tpos,overshoot_tpos,overshoot_pct,
    scheduled_boundary,cutoff_at
  ) VALUES (
    (p->>'session_date')::date,p->>'method_version',p->>'symbol',p->>'source',
    v_expected,v_observed,v_distinct,(p->>'missing_slots')::integer,(p->>'duplicate_slots')::integer,
    (p->>'invalid_slots')::integer,(p->>'out_of_session_count')::integer,true,'COMPLETE',
    NULLIF(p->>'reference_profile_id','')::uuid,COALESCE(p->>'reference_status','NO_VALID_REFERENCE_PROFILE'),
    NULLIF(p->>'first_candle_open','')::timestamptz,NULLIF(p->>'last_candle_open','')::timestamptz,
    COALESCE((p->>'total_tpos')::integer,0),NULLIF(p->>'poc_row_index','')::bigint,
    NULLIF(p->>'poc_lower','')::numeric,NULLIF(p->>'poc_upper','')::numeric,
    NULLIF(p->>'poc_tpo_count','')::integer,NULLIF(p->>'vah_row_index','')::bigint,
    NULLIF(p->>'vah_lower','')::numeric,NULLIF(p->>'vah_upper','')::numeric,
    NULLIF(p->>'val_row_index','')::bigint,NULLIF(p->>'val_lower','')::numeric,
    NULLIF(p->>'val_upper','')::numeric,NULLIF(p->>'value_area_tpos','')::integer,
    NULLIF(p->>'target_tpos','')::numeric,NULLIF(p->>'overshoot_tpos','')::integer,
    NULLIF(p->>'overshoot_pct','')::numeric,(p->>'scheduled_boundary')::timestamptz,
    (p->>'cutoff_at')::timestamptz
  ) RETURNING profile_id INTO v_profile_id;

  FOR v_row IN SELECT value FROM jsonb_array_elements(p_bundle->'rows') LOOP
    INSERT INTO amt_engine_v17.tpo_rows(
      profile_id,row_index,row_lower,row_upper,tpo_count,is_poc,is_value_area
    ) VALUES (
      v_profile_id,(v_row->>'row_index')::bigint,(v_row->>'row_lower')::numeric,
      (v_row->>'row_upper')::numeric,(v_row->>'tpo_count')::integer,
      COALESCE((v_row->>'is_poc')::boolean,false),
      COALESCE((v_row->>'is_value_area')::boolean,false)
    );
    v_row_count:=v_row_count+1;
  END LOOP;

  IF v_row_count<>jsonb_array_length(p_bundle->'rows') THEN
    RAISE EXCEPTION 'TPO row count mismatch';
  END IF;
  RETURN v_profile_id;
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.persist_full_session_bundle_internal(p_bundle jsonb, p_test_mode boolean DEFAULT false)
 RETURNS uuid
 LANGUAGE plpgsql
AS $function$
DECLARE
 p jsonb; v_profile_id uuid; v_method text; v_convention text;
 v_expected int; v_observed int; v_distinct int;
 v_item jsonb; v_event_ids uuid[]:=ARRAY[]::uuid[];
 v_event_id uuid; v_opposite uuid; v_previous uuid; v_row_count int:=0;
 v_snapshot_count int:=0; v_atr_count int:=0; v_event_count int:=0; v_wick_count int:=0;
 v_boundary jsonb; v_oi jsonb; v_cutoff timestamptz;
BEGIN
 IF p_bundle IS NULL OR jsonb_typeof(p_bundle)<>'object' OR
    jsonb_typeof(p_bundle->'profile')<>'object' OR
    jsonb_typeof(p_bundle->'rows')<>'array' OR
    jsonb_typeof(p_bundle->'developing_snapshots')<>'array' OR
    jsonb_typeof(p_bundle->'atr_observations')<>'array' OR
    jsonb_typeof(p_bundle->'events')<>'array' OR
    jsonb_typeof(p_bundle->'wick_observations')<>'array' OR
    jsonb_typeof(p_bundle->'boundary_snapshot')<>'object' OR
    jsonb_typeof(p_bundle->'oi_context')<>'object' THEN
   RAISE EXCEPTION 'Full bundle requires profile, rows, snapshots, ATR, events, wicks, boundary and OI objects';
 END IF;
 p:=p_bundle->'profile'; v_method:=p->>'method_version';
 SELECT source_timestamp_convention INTO v_convention FROM amt_engine_v17.method_config WHERE method_version=v_method;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown method version'; END IF;
 IF p_test_mode IS DISTINCT FROM true AND v_convention NOT IN ('OPEN','CLOSE') THEN
   RAISE EXCEPTION 'Writer blocked: source timestamp convention is not verified';
 END IF;
 IF p_test_mode IS TRUE AND COALESCE(p->>'symbol','') NOT LIKE 'TEST\_%' ESCAPE '\' THEN
   RAISE EXCEPTION 'Test mode is restricted to TEST_ symbols';
 END IF;
 v_expected:=COALESCE((p->>'expected_bars')::int,0);
 v_observed:=COALESCE((p->>'observed_bars')::int,0);
 v_distinct:=COALESCE((p->>'distinct_slots')::int,0);
 IF v_expected<>48 OR v_observed<>48 OR v_distinct<>48 OR
    COALESCE((p->>'missing_slots')::int,-1)<>0 OR
    COALESCE((p->>'duplicate_slots')::int,-1)<>0 OR
    COALESCE((p->>'invalid_slots')::int,-1)<>0 OR
    COALESCE((p->>'out_of_session_count')::int,-1)<>0 OR
    COALESCE((p->>'is_complete')::boolean,false) IS NOT TRUE OR
    p->>'profile_status'<>'COMPLETE' THEN
   RAISE EXCEPTION 'Writer guard: only fully validated 48-candle COMPLETE profiles may be persisted';
 END IF;
 IF (p->>'scheduled_boundary') IS NULL OR (p->>'cutoff_at') IS NULL OR
    (p->>'cutoff_at')::timestamptz>(p->>'scheduled_boundary')::timestamptz THEN
   RAISE EXCEPTION 'Writer guard: explicit cutoff at or before boundary required';
 END IF;
 v_cutoff:=(p->>'cutoff_at')::timestamptz;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_bundle->'developing_snapshots') x
   WHERE NULLIF(x->>'source_available_at','') IS NULL OR NULLIF(x->>'ingested_at','') IS NULL
      OR (x->>'source_available_at')::timestamptz>v_cutoff OR (x->>'ingested_at')::timestamptz>v_cutoff+interval '10 minutes') THEN
   RAISE EXCEPTION 'Writer guard: every PRICE snapshot must have source and ingestion receipts at or before cutoff';
 END IF;
 IF (p->>'session_date')::date >= (now() AT TIME ZONE 'Asia/Kolkata')::date THEN
   RAISE EXCEPTION 'Writer guard: session must be closed before persistence';
 END IF;
 IF jsonb_array_length(p_bundle->'rows')=0 THEN RAISE EXCEPTION 'Profile must include TPO rows'; END IF;

 v_boundary:=p_bundle->'boundary_snapshot';
 IF NULLIF(v_boundary->>'source_available_at','') IS NULL OR NULLIF(v_boundary->>'ingested_at','') IS NULL
    OR (v_boundary->>'source_available_at')::timestamptz>v_cutoff OR (v_boundary->>'ingested_at')::timestamptz>v_cutoff+interval '10 minutes' THEN
   RAISE EXCEPTION 'Writer guard: boundary PRICE receipts must be known and at or before cutoff';
 END IF;
 IF (v_boundary->>'session_date')::date<>(p->>'session_date')::date OR
    (v_boundary->>'scheduled_boundary')::timestamptz<>(p->>'scheduled_boundary')::timestamptz OR
    (v_boundary->>'cutoff_at')::timestamptz>(p->>'scheduled_boundary')::timestamptz OR
    v_boundary->>'session_status'<>'COMPLETE' THEN
   RAISE EXCEPTION 'Boundary snapshot does not certify this closed session';
 END IF;
 v_oi:=p_bundle->'oi_context';
 IF COALESCE(v_oi->>'context_state','UNAVAILABLE') NOT IN ('EXPANSION','CONTRACTION','UNCHANGED','UNAVAILABLE') THEN
   RAISE EXCEPTION 'Invalid OI context state';
 END IF;

 INSERT INTO amt_engine_v17.session_profiles(
  session_date,method_version,symbol,source,expected_bars,observed_bars,distinct_slots,
  missing_slots,duplicate_slots,invalid_slots,out_of_session_count,is_complete,profile_status,
  reference_profile_id,reference_status,first_candle_open,last_candle_open,total_tpos,
  poc_row_index,poc_lower,poc_upper,poc_tpo_count,vah_row_index,vah_lower,vah_upper,
  val_row_index,val_lower,val_upper,value_area_tpos,target_tpos,overshoot_tpos,overshoot_pct,
  scheduled_boundary,cutoff_at
 ) VALUES (
  (p->>'session_date')::date,v_method,p->>'symbol',p->>'source',48,48,48,0,0,0,0,true,'COMPLETE',
  NULLIF(p->>'reference_profile_id','')::uuid,COALESCE(p->>'reference_status','NO_VALID_REFERENCE_PROFILE'),
  NULLIF(p->>'first_candle_open','')::timestamptz,NULLIF(p->>'last_candle_open','')::timestamptz,
  COALESCE((p->>'total_tpos')::int,0),NULLIF(p->>'poc_row_index','')::bigint,
  NULLIF(p->>'poc_lower','')::numeric,NULLIF(p->>'poc_upper','')::numeric,
  NULLIF(p->>'poc_tpo_count','')::int,NULLIF(p->>'vah_row_index','')::bigint,
  NULLIF(p->>'vah_lower','')::numeric,NULLIF(p->>'vah_upper','')::numeric,
  NULLIF(p->>'val_row_index','')::bigint,NULLIF(p->>'val_lower','')::numeric,
  NULLIF(p->>'val_upper','')::numeric,NULLIF(p->>'value_area_tpos','')::int,
  NULLIF(p->>'target_tpos','')::numeric,NULLIF(p->>'overshoot_tpos','')::int,
  NULLIF(p->>'overshoot_pct','')::numeric,(p->>'scheduled_boundary')::timestamptz,
  (p->>'cutoff_at')::timestamptz
 ) RETURNING profile_id INTO v_profile_id;

 FOR v_item IN SELECT value FROM jsonb_array_elements(p_bundle->'rows') LOOP
  INSERT INTO amt_engine_v17.tpo_rows(profile_id,row_index,row_lower,row_upper,tpo_count,is_poc,is_value_area)
  VALUES(v_profile_id,(v_item->>'row_index')::bigint,(v_item->>'row_lower')::numeric,
   (v_item->>'row_upper')::numeric,(v_item->>'tpo_count')::int,
   COALESCE((v_item->>'is_poc')::boolean,false),COALESCE((v_item->>'is_value_area')::boolean,false));
  v_row_count:=v_row_count+1;
 END LOOP;

 FOR v_item IN SELECT value FROM jsonb_array_elements(p_bundle->'developing_snapshots') LOOP
  INSERT INTO amt_engine_v17.developing_snapshots(
   profile_id,session_date,expected_interval_open,candle_open,candle_close,source,symbol,
   source_candle_identity,original_source_timestamp,timestamp_convention,source_available_at,ingested_at,
   method_version,reference_profile_id,reference_status,developing_tpos,developing_poc_lower,
   developing_poc_upper,developing_poc_count,developing_vah_lower,developing_vah_upper,
   developing_val_lower,developing_val_upper,developing_value_area_tpos,event_state
  ) VALUES (
   v_profile_id,(p->>'session_date')::date,(v_item->>'expected_interval_open')::timestamptz,
   (v_item->>'candle_open')::timestamptz,(v_item->>'candle_close')::timestamptz,
   v_item->>'source',v_item->>'symbol',v_item->>'source_candle_identity',
   (v_item->>'original_source_timestamp')::timestamptz,v_item->>'timestamp_convention',
   NULLIF(v_item->>'source_available_at','')::timestamptz,NULLIF(v_item->>'ingested_at','')::timestamptz,
   v_method,NULLIF(v_item->>'reference_profile_id','')::uuid,
   COALESCE(v_item->>'reference_status','NO_VALID_REFERENCE_PROFILE'),
   (v_item->>'developing_tpos')::int,NULLIF(v_item->>'developing_poc_lower','')::numeric,
   NULLIF(v_item->>'developing_poc_upper','')::numeric,NULLIF(v_item->>'developing_poc_count','')::int,
   NULLIF(v_item->>'developing_vah_lower','')::numeric,NULLIF(v_item->>'developing_vah_upper','')::numeric,
   NULLIF(v_item->>'developing_val_lower','')::numeric,NULLIF(v_item->>'developing_val_upper','')::numeric,
   NULLIF(v_item->>'developing_value_area_tpos','')::int,COALESCE(v_item->'event_state','{}'::jsonb)
  );
  v_snapshot_count:=v_snapshot_count+1;
 END LOOP;

 FOR v_item IN SELECT value FROM jsonb_array_elements(p_bundle->'atr_observations') LOOP
  INSERT INTO amt_engine_v17.atr14_observations(
   symbol,source,candle_open,true_range,atr14,pre_event_atr14,sequence_valid,reset_reason,seed_count
  ) VALUES (
   p->>'symbol',p->>'source',(v_item->>'candle_open')::timestamptz,
   NULLIF(v_item->>'true_range','')::numeric,NULLIF(v_item->>'atr14','')::numeric,
   NULLIF(v_item->>'pre_event_atr14','')::numeric,(v_item->>'sequence_valid')::boolean,
   NULLIF(v_item->>'reset_reason',''),COALESCE((v_item->>'seed_count')::int,0)
  );
  v_atr_count:=v_atr_count+1;
 END LOOP;

 -- Insert episodes first without cross-links; apply reciprocal links in a second pass.
 FOR v_item IN SELECT value FROM jsonb_array_elements(p_bundle->'events') LOOP
  v_event_id:=(v_item->>'event_id')::uuid;
  IF v_event_id=ANY(v_event_ids) THEN RAISE EXCEPTION 'Duplicate event_id in bundle'; END IF;
  v_event_ids:=array_append(v_event_ids,v_event_id);
  INSERT INTO amt_engine_v17.event_episodes(
   event_id,profile_id,session_date,method_version,direction,event_type,started_at,terminated_at,
   termination_reason,status,outcome_window_status,provisional_acceptance_at,opposite_event_id,previous_opposite_event_id,
   initial_event_wick_interaction_at,first_subsequent_wick_intersection_at,
   first_boundary_touch_only_at,first_strict_wick_penetration_at
  ) VALUES (
   v_event_id,v_profile_id,(p->>'session_date')::date,v_method,v_item->>'direction',v_item->>'event_type',
   (v_item->>'started_at')::timestamptz,NULLIF(v_item->>'terminated_at','')::timestamptz,
   NULLIF(v_item->>'termination_reason',''),v_item->>'status',
   COALESCE(v_item->>'outcome_window_status','OPEN'),
   NULLIF(v_item->>'provisional_acceptance_at','')::timestamptz,NULL,NULL,
   NULLIF(v_item->>'initial_event_wick_interaction_at','')::timestamptz,
   NULLIF(v_item->>'first_subsequent_wick_intersection_at','')::timestamptz,
   NULLIF(v_item->>'first_boundary_touch_only_at','')::timestamptz,
   NULLIF(v_item->>'first_strict_wick_penetration_at','')::timestamptz
  );
  v_event_count:=v_event_count+1;
 END LOOP;
 FOR v_item IN SELECT value FROM jsonb_array_elements(p_bundle->'events') LOOP
  v_opposite:=NULLIF(v_item->>'opposite_event_id','')::uuid;
  v_previous:=NULLIF(v_item->>'previous_opposite_event_id','')::uuid;
  IF v_opposite IS NOT NULL THEN
   IF NOT (v_opposite=ANY(v_event_ids)) THEN RAISE EXCEPTION 'Next opposite event link must point inside this session bundle'; END IF;
   UPDATE amt_engine_v17.event_episodes SET opposite_event_id=v_opposite
    WHERE event_id=(v_item->>'event_id')::uuid;
  END IF;
  IF v_previous IS NOT NULL THEN
   IF NOT (v_previous=ANY(v_event_ids)) THEN RAISE EXCEPTION 'Previous opposite event link must point inside this session bundle'; END IF;
   UPDATE amt_engine_v17.event_episodes SET previous_opposite_event_id=v_previous
    WHERE event_id=(v_item->>'event_id')::uuid;
  END IF;
 END LOOP;

 FOR v_item IN SELECT value FROM jsonb_array_elements(p_bundle->'wick_observations') LOOP
  INSERT INTO amt_engine_v17.event_wick_observations(
   event_id,candle_open,wick_intersection,boundary_touch_only,strict_wick_penetration,
   wick_low,wick_high,reference_val,reference_vah,observed_at,observation_type
  ) VALUES (
   (v_item->>'event_id')::uuid,(v_item->>'candle_open')::timestamptz,
   (v_item->>'wick_intersection')::boolean,(v_item->>'boundary_touch_only')::boolean,
   (v_item->>'strict_wick_penetration')::boolean,NULLIF(v_item->>'wick_low','')::numeric,
   NULLIF(v_item->>'wick_high','')::numeric,(v_item->>'reference_val')::numeric,
   (v_item->>'reference_vah')::numeric,(v_item->>'observed_at')::timestamptz,
   v_item->>'observation_type'
  );
  v_wick_count:=v_wick_count+1;
 END LOOP;

 INSERT INTO amt_engine_v17.session_oi_context(
  profile_id,opening_oi,latest_oi,absolute_change,percentage_change,context_state,units_verified
 ) VALUES (
  v_profile_id,NULLIF(v_oi->>'opening_oi','')::numeric,NULLIF(v_oi->>'latest_oi','')::numeric,
  NULLIF(v_oi->>'absolute_change','')::numeric,NULLIF(v_oi->>'percentage_change','')::numeric,
  COALESCE(v_oi->>'context_state','UNAVAILABLE'),COALESCE((v_oi->>'units_verified')::boolean,false)
 );

 INSERT INTO amt_engine_v17.boundary_snapshots(
  profile_id,session_date,scheduled_boundary,cutoff_at,last_valid_completed_candle_open,
  last_valid_completed_candle_close,source_available_at,ingested_at,session_status,active_event_ids,boundary_payload
 ) VALUES (
  v_profile_id,(v_boundary->>'session_date')::date,(v_boundary->>'scheduled_boundary')::timestamptz,
  (v_boundary->>'cutoff_at')::timestamptz,NULLIF(v_boundary->>'last_valid_completed_candle_open','')::timestamptz,
  NULLIF(v_boundary->>'last_valid_completed_candle_close','')::timestamptz,
  NULLIF(v_boundary->>'source_available_at','')::timestamptz,NULLIF(v_boundary->>'ingested_at','')::timestamptz,
  v_boundary->>'session_status',
  ARRAY(SELECT jsonb_array_elements_text(COALESCE(v_boundary->'active_event_ids','[]'::jsonb))::uuid),
  COALESCE(v_boundary->'boundary_payload','{}'::jsonb)
 );

 RETURN v_profile_id;
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.persist_full_session_bundle_unvalidated_internal(p_bundle jsonb, p_test_mode boolean DEFAULT false)
 RETURNS uuid
 LANGUAGE plpgsql
AS $function$
DECLARE p jsonb; b jsonb; v_profile_id uuid; v_item jsonb; v_audit_count int:=0; v_cutoff timestamptz;
BEGIN
 IF p_bundle IS NULL OR jsonb_typeof(p_bundle)<>'object' THEN RAISE EXCEPTION 'Bundle must be an object'; END IF;
 p:=p_bundle->'profile'; b:=p_bundle->'boundary_snapshot';
 IF jsonb_typeof(p)<>'object' OR jsonb_typeof(b)<>'object' THEN RAISE EXCEPTION 'Profile and boundary snapshot are required'; END IF;
 v_cutoff:=NULLIF(p->>'cutoff_at','')::timestamptz;
 IF v_cutoff IS NULL THEN RAISE EXCEPTION 'Writer guard: explicit cutoff required'; END IF;
 IF jsonb_typeof(p_bundle->'developing_snapshots')<>'array' OR jsonb_array_length(p_bundle->'developing_snapshots')<>48 THEN
  RAISE EXCEPTION 'Full session persistence requires exactly 48 developing snapshots';
 END IF;
 IF jsonb_typeof(p_bundle->'atr_observations')<>'array' OR jsonb_array_length(p_bundle->'atr_observations')<>48 THEN
  RAISE EXCEPTION 'Full session persistence requires exactly 48 ATR observations, including NULL/reset rows';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_bundle->'developing_snapshots') x
   WHERE NULLIF(x->>'source_available_at','') IS NULL OR NULLIF(x->>'ingested_at','') IS NULL
      OR (x->>'source_available_at')::timestamptz>v_cutoff OR (x->>'ingested_at')::timestamptz>v_cutoff+interval '10 minutes') THEN
  RAISE EXCEPTION 'Writer guard: every PRICE snapshot must have source and ingestion receipts at or before cutoff';
 END IF;
 IF (b->>'session_date')::date<>(p->>'session_date')::date
    OR (b->>'scheduled_boundary')::timestamptz<>(p->>'scheduled_boundary')::timestamptz
    OR (b->>'last_valid_completed_candle_close')::timestamptz<>(p->>'scheduled_boundary')::timestamptz
    OR (b->>'last_valid_completed_candle_open')::timestamptz<>(p->>'scheduled_boundary')::timestamptz-interval '30 minutes'
    OR (b->>'cutoff_at')::timestamptz>(b->>'scheduled_boundary')::timestamptz
    OR b->>'session_status'<>'COMPLETE' THEN
  RAISE EXCEPTION 'Boundary snapshot must certify the final expected 30m candle at the fixed boundary';
 END IF;
 IF COALESCE((p->>'cutoff_at')::timestamptz,(b->>'cutoff_at')::timestamptz) IS DISTINCT FROM (b->>'cutoff_at')::timestamptz THEN
  RAISE EXCEPTION 'Profile and boundary cutoff timestamps must match';
 END IF;
 IF NULLIF(b->>'source_available_at','') IS NULL OR NULLIF(b->>'ingested_at','') IS NULL
    OR (b->>'source_available_at')::timestamptz>v_cutoff OR (b->>'ingested_at')::timestamptz>v_cutoff+interval '10 minutes' THEN
  RAISE EXCEPTION 'Writer guard: boundary PRICE receipts must be known and at or before cutoff';
 END IF;
 IF jsonb_typeof(p_bundle->'source_audit') IS NOT NULL AND jsonb_typeof(p_bundle->'source_audit')<>'array' THEN
  RAISE EXCEPTION 'source_audit must be an array when supplied';
 END IF;
 IF jsonb_typeof(p_bundle->'source_audit')='array' AND EXISTS(
   SELECT 1 FROM jsonb_array_elements(p_bundle->'source_audit') x
   WHERE NULLIF(x->>'source_available_at','') IS NULL OR NULLIF(x->>'ingested_at','') IS NULL
      OR (x->>'source_available_at')::timestamptz>v_cutoff OR (x->>'ingested_at')::timestamptz>v_cutoff+interval '10 minutes') THEN
  RAISE EXCEPTION 'Writer guard: every source-audit receipt must be known and at or before cutoff';
 END IF;
 v_profile_id:=amt_engine_v17.persist_full_session_bundle_internal(p_bundle,p_test_mode);
 FOR v_item IN SELECT value FROM jsonb_array_elements(COALESCE(p_bundle->'source_audit','[]'::jsonb)) LOOP
  INSERT INTO amt_engine_v17.source_candle_audit(source,symbol,series_type,resolution,source_candle_time,canonical_open_time,timestamp_convention,source_available_at,ingested_at,validation_status,validation_detail)
  VALUES(v_item->>'source',v_item->>'symbol',v_item->>'series_type',v_item->>'resolution',(v_item->>'source_candle_time')::timestamptz,
   NULLIF(v_item->>'canonical_open_time','')::timestamptz,v_item->>'timestamp_convention',NULLIF(v_item->>'source_available_at','')::timestamptz,
   NULLIF(v_item->>'ingested_at','')::timestamptz,v_item->>'validation_status',COALESCE(v_item->'validation_detail','{}'::jsonb));
  v_audit_count:=v_audit_count+1;
 END LOOP;
 RETURN v_profile_id;
END; $function$


CREATE OR REPLACE FUNCTION amt_engine_v17.attach_frozen_reference_fixture(p_snapshots jsonb, p_reference_profile_id uuid, p_reference_status text, p_reference_session_date date, p_reference_vah numeric, p_reference_val numeric, p_reference_poc numeric)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_out jsonb := '[]'::jsonb;
  v_item jsonb;
  v_expected_status text;
BEGIN
  IF p_snapshots IS NULL OR jsonb_typeof(p_snapshots)<>'array' THEN
    RAISE EXCEPTION 'Snapshots must be a JSON array';
  END IF;
  v_expected_status := CASE WHEN p_reference_profile_id IS NULL THEN 'NO_VALID_REFERENCE_PROFILE' ELSE p_reference_status END;
  IF p_reference_profile_id IS NOT NULL AND (
       p_reference_status NOT IN ('AVAILABLE','REFERENCE_SKIPPED_INCOMPLETE')
       OR p_reference_session_date IS NULL OR p_reference_vah IS NULL
       OR p_reference_val IS NULL OR p_reference_poc IS NULL
       OR p_reference_val > p_reference_vah
  ) THEN
    RAISE EXCEPTION 'A selected reference requires identity, date and valid VAH/VAL/POC levels';
  END IF;
  FOR v_item IN SELECT value FROM jsonb_array_elements(p_snapshots) LOOP
    v_item := v_item || jsonb_build_object(
      'reference_profile_id',p_reference_profile_id,
      'reference_status',v_expected_status,
      'reference_session_date',p_reference_session_date,
      'reference_vah',p_reference_vah,
      'reference_val',p_reference_val,
      'reference_poc',p_reference_poc
    );
    v_item := jsonb_set(v_item,'{event_state}',jsonb_build_object(
      'reference_profile_id',p_reference_profile_id,
      'reference_status',v_expected_status,
      'reference_vah',p_reference_vah,
      'reference_val',p_reference_val,
      'reference_poc',p_reference_poc
    ),true);
    v_out := v_out || jsonb_build_array(v_item);
  END LOOP;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(v_out) s
    WHERE s->>'reference_status' IS DISTINCT FROM v_expected_status
       OR NULLIF(s->>'reference_profile_id','') IS DISTINCT FROM p_reference_profile_id::text
       OR NULLIF(s->>'reference_vah','')::numeric IS DISTINCT FROM p_reference_vah
       OR NULLIF(s->>'reference_val','')::numeric IS DISTINCT FROM p_reference_val
       OR NULLIF(s->>'reference_poc','')::numeric IS DISTINCT FROM p_reference_poc
  ) THEN
    RAISE EXCEPTION 'Frozen reference consistency check failed across developing snapshots';
  END IF;
  RETURN v_out;
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.validate_full_session_bundle_fixture(p_bundle jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  p jsonb := p_bundle->'profile';
  b jsonb := p_bundle->'boundary_snapshot';
  s jsonb := p_bundle->'developing_snapshots';
  a jsonb := p_bundle->'atr_observations';
  e jsonb := p_bundle->'events';
  w jsonb := p_bundle->'wick_observations';
  v_start timestamptz;
  v_end timestamptz;
  v_ref_id text;
  v_ref_status text;
  v_ref_vah numeric;
  v_ref_val numeric;
  v_ref_poc numeric;
  v_snap_count int;
  v_atr_count int;
  v_event_count int;
  v_wick_count int;
  v_bad int;
  v_reason text[] := ARRAY[]::text[];
BEGIN
  IF p_bundle IS NULL OR jsonb_typeof(p_bundle)<>'object'
     OR jsonb_typeof(p)<>'object' OR jsonb_typeof(b)<>'object'
     OR jsonb_typeof(s)<>'array' OR jsonb_typeof(a)<>'array'
     OR jsonb_typeof(e)<>'array' OR jsonb_typeof(w)<>'array' THEN
    RAISE EXCEPTION 'Bundle requires profile, boundary, snapshots, ATR, events and wick arrays';
  END IF;
  v_start := ((p->>'session_date')::date::timestamp + time '05:30') AT TIME ZONE 'Asia/Kolkata';
  v_end := v_start + interval '24 hours';
  v_ref_id := NULLIF(p->>'reference_profile_id','');
  v_ref_status := COALESCE(p->>'reference_status','NO_VALID_REFERENCE_PROFILE');
  v_ref_vah := NULLIF(p->>'reference_vah','')::numeric;
  v_ref_val := NULLIF(p->>'reference_val','')::numeric;
  v_ref_poc := NULLIF(p->>'reference_poc','')::numeric;

  v_snap_count := jsonb_array_length(s);
  v_atr_count := jsonb_array_length(a);
  v_event_count := jsonb_array_length(e);
  v_wick_count := jsonb_array_length(w);

  IF v_snap_count<>48 THEN v_reason:=array_append(v_reason,'SNAPSHOT_COUNT_NOT_48'); END IF;
  IF v_atr_count<>48 THEN v_reason:=array_append(v_reason,'ATR_COUNT_NOT_48'); END IF;

  SELECT count(*) INTO v_bad FROM (
    SELECT (x->>'snapshot_sequence')::int AS seq,
           (x->>'candle_open')::timestamptz AS op,
           (x->>'candle_close')::timestamptz AS cl,
           x->>'source_candle_identity' AS ident
    FROM jsonb_array_elements(s) x
  ) q
  WHERE q.seq IS NULL OR q.op IS NULL OR q.cl IS NULL OR q.ident IS NULL
     OR q.op<v_start OR q.op>=v_end OR q.cl<>q.op+interval '30 minutes'
     OR mod(extract(epoch FROM (q.op-v_start))::bigint,1800)<>0;
  IF v_bad>0 THEN v_reason:=array_append(v_reason,'INVALID_SNAPSHOT_IDENTITY_OR_INTERVAL'); END IF;

  SELECT count(*) INTO v_bad FROM (
    SELECT (x->>'snapshot_sequence')::int seq FROM jsonb_array_elements(s) x
    GROUP BY 1 HAVING count(*)<>1
  ) q;
  IF v_bad>0 THEN v_reason:=array_append(v_reason,'DUPLICATE_SNAPSHOT_SEQUENCE'); END IF;

  SELECT count(*) INTO v_bad FROM (
    SELECT x->>'source_candle_identity' ident FROM jsonb_array_elements(s) x
    GROUP BY 1 HAVING count(*)<>1
  ) q;
  IF v_bad>0 THEN v_reason:=array_append(v_reason,'DUPLICATE_SNAPSHOT_CANDLE_IDENTITY'); END IF;

  SELECT count(*) INTO v_bad FROM jsonb_array_elements(s) x
  WHERE COALESCE(x->>'reference_status','')<>v_ref_status
     OR NULLIF(x->>'reference_profile_id','') IS DISTINCT FROM v_ref_id
     OR NULLIF(x->>'reference_vah','')::numeric IS DISTINCT FROM v_ref_vah
     OR NULLIF(x->>'reference_val','')::numeric IS DISTINCT FROM v_ref_val
     OR NULLIF(x->>'reference_poc','')::numeric IS DISTINCT FROM v_ref_poc;
  IF v_bad>0 THEN v_reason:=array_append(v_reason,'FROZEN_REFERENCE_MISMATCH'); END IF;

  SELECT count(*) INTO v_bad FROM (
    SELECT (x->>'candle_open')::timestamptz op FROM jsonb_array_elements(a) x
    GROUP BY 1 HAVING count(*)<>1
  ) q;
  IF v_bad>0 OR v_atr_count<>48 THEN v_reason:=array_append(v_reason,'ATR_CANDLE_IDENTITY_DUPLICATE_OR_COUNT'); END IF;

  SELECT count(*) INTO v_bad
  FROM jsonb_array_elements(s) x
  WHERE NOT EXISTS (
    SELECT 1 FROM jsonb_array_elements(a) y
    WHERE (y->>'candle_open')::timestamptz=(x->>'candle_open')::timestamptz
  );
  IF v_bad>0 THEN v_reason:=array_append(v_reason,'SNAPSHOT_WITHOUT_MATCHING_ATR'); END IF;

  SELECT count(*) INTO v_bad FROM jsonb_array_elements(e) x
  WHERE (x->>'started_at')::timestamptz<v_start
     OR (x->>'started_at')::timestamptz>=v_end
     OR mod(extract(epoch FROM ((x->>'started_at')::timestamptz-v_start))::bigint,1800)<>0
     OR ((x->>'terminated_at') IS NOT NULL AND
         ((x->>'terminated_at')::timestamptz<(x->>'started_at')::timestamptz
          OR (x->>'terminated_at')::timestamptz>v_end));
  IF v_bad>0 THEN v_reason:=array_append(v_reason,'EVENT_TIMESTAMP_OUTSIDE_SESSION_OR_INVALID'); END IF;

  SELECT count(*) INTO v_bad FROM jsonb_array_elements(e) x
  WHERE NULLIF(x->>'opposite_event_id','') IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements(e) y
      WHERE y->>'event_id'=x->>'opposite_event_id'
        AND y->>'previous_opposite_event_id'=x->>'event_id'
    );
  IF v_bad>0 THEN v_reason:=array_append(v_reason,'NEXT_OPPOSITE_EVENT_LINK_NOT_RECIPROCAL'); END IF;

  SELECT count(*) INTO v_bad FROM jsonb_array_elements(e) x
  WHERE NULLIF(x->>'previous_opposite_event_id','') IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements(e) y
      WHERE y->>'event_id'=x->>'previous_opposite_event_id'
        AND y->>'opposite_event_id'=x->>'event_id'
    );
  IF v_bad>0 THEN v_reason:=array_append(v_reason,'PREVIOUS_OPPOSITE_EVENT_LINK_NOT_RECIPROCAL'); END IF;

  SELECT count(*) INTO v_bad FROM jsonb_array_elements(w) x
  WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements(e) y WHERE y->>'event_id'=x->>'event_id')
     OR (x->>'candle_open')::timestamptz<v_start
     OR (x->>'candle_open')::timestamptz>=v_end;
  IF v_bad>0 THEN v_reason:=array_append(v_reason,'WICK_WITHOUT_EVENT_OR_OUTSIDE_SESSION'); END IF;

  IF (b->>'session_date')::date<>(p->>'session_date')::date
     OR (b->>'scheduled_boundary')::timestamptz<>v_end
     OR (b->>'last_valid_completed_candle_open')::timestamptz<>v_end-interval '30 minutes'
     OR (b->>'last_valid_completed_candle_close')::timestamptz<>v_end
     OR b->>'session_status'<>'COMPLETE'
     OR (b->>'cutoff_at')::timestamptz>(b->>'scheduled_boundary')::timestamptz
     OR (p->>'cutoff_at')::timestamptz IS DISTINCT FROM (b->>'cutoff_at')::timestamptz
  THEN v_reason:=array_append(v_reason,'BOUNDARY_CERTIFICATION_INVALID'); END IF;

  IF COALESCE((p->>'is_complete')::boolean,false) IS NOT TRUE
     OR p->>'profile_status'<>'COMPLETE'
     OR COALESCE((p->>'observed_bars')::int,0)<>48
     OR COALESCE((p->>'distinct_slots')::int,0)<>48
     OR COALESCE((p->>'missing_slots')::int,-1)<>0
     OR COALESCE((p->>'duplicate_slots')::int,-1)<>0
     OR COALESCE((p->>'invalid_slots')::int,-1)<>0
     OR COALESCE((p->>'out_of_session_count')::int,-1)<>0
  THEN v_reason:=array_append(v_reason,'PROFILE_VALIDATION_NOT_COMPLETE'); END IF;

  RETURN jsonb_build_object(
    'is_consistent',cardinality(v_reason)=0,
    'reasons',to_jsonb(v_reason),
    'snapshot_count',v_snap_count,'atr_count',v_atr_count,
    'event_count',v_event_count,'wick_observation_count',v_wick_count,
    'reference_profile_id',v_ref_id,'reference_status',v_ref_status,
    'session_date',p->>'session_date',
    'writes_performed',false
  );
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.persist_consistent_full_session_bundle(p_bundle jsonb, p_test_mode boolean DEFAULT false)
 RETURNS uuid
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_check jsonb;
BEGIN
  v_check := amt_engine_v17.validate_full_session_bundle_fixture(p_bundle);
  IF COALESCE((v_check->>'is_consistent')::boolean,false) IS NOT TRUE THEN
    RAISE EXCEPTION 'Bundle consistency gate failed: %', v_check->'reasons';
  END IF;
  RETURN amt_engine_v17.persist_full_session_bundle(p_bundle,p_test_mode);
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.validate_developing_snapshot_chain_fixture(p_snapshots jsonb, p_session_date date, p_reference_profile_id uuid, p_reference_status text, p_reference_vah numeric, p_reference_val numeric, p_reference_poc numeric)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_start timestamptz;
  v_bad int;
  v_count int;
  v_result jsonb;
BEGIN
  IF p_snapshots IS NULL OR jsonb_typeof(p_snapshots)<>'array' THEN
    RAISE EXCEPTION 'Snapshot chain must be a JSON array';
  END IF;
  IF p_session_date IS NULL OR p_reference_status IS NULL THEN
    RAISE EXCEPTION 'Session date and frozen reference status are required';
  END IF;
  IF p_reference_profile_id IS NULL AND p_reference_status<>'NO_VALID_REFERENCE_PROFILE' THEN
    RAISE EXCEPTION 'Missing reference identity requires NO_VALID_REFERENCE_PROFILE';
  END IF;
  IF p_reference_profile_id IS NOT NULL AND (
    p_reference_status NOT IN ('AVAILABLE','REFERENCE_SKIPPED_INCOMPLETE')
    OR p_reference_vah IS NULL OR p_reference_val IS NULL OR p_reference_poc IS NULL
    OR p_reference_val>p_reference_vah
  ) THEN RAISE EXCEPTION 'Selected reference requires identity and valid VAH/VAL/POC'; END IF;

  v_start:=((p_session_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata');
  v_count:=jsonb_array_length(p_snapshots);

  SELECT count(*) INTO v_bad
  FROM jsonb_array_elements(p_snapshots) x
  WHERE COALESCE((x->>'snapshot_sequence')::int,-1)<1
     OR COALESCE((x->>'snapshot_sequence')::int,-1)>48
     OR NULLIF(x->>'candle_id','') IS NULL
     OR (x->>'canonical_open_time')::timestamptz IS NULL
     OR (x->>'canonical_close_time')::timestamptz IS DISTINCT FROM
          (x->>'canonical_open_time')::timestamptz+interval '30 minutes'
     OR (x->>'canonical_open_time')::timestamptz <>
          v_start+((COALESCE((x->>'snapshot_sequence')::int,0)-1)*interval '30 minutes')
     OR (x->>'reference_status') IS DISTINCT FROM p_reference_status
     OR NULLIF(x->>'reference_profile_id','') IS DISTINCT FROM p_reference_profile_id::text
     OR NULLIF(x->>'reference_vah','')::numeric IS DISTINCT FROM p_reference_vah
     OR NULLIF(x->>'reference_val','')::numeric IS DISTINCT FROM p_reference_val
     OR NULLIF(x->>'reference_poc','')::numeric IS DISTINCT FROM p_reference_poc
     OR (x->'event_state'->>'reference_status') IS DISTINCT FROM p_reference_status
     OR NULLIF(x->'event_state'->>'reference_profile_id','') IS DISTINCT FROM p_reference_profile_id::text
     OR NULLIF(x->'event_state'->>'reference_vah','')::numeric IS DISTINCT FROM p_reference_vah
     OR NULLIF(x->'event_state'->>'reference_val','')::numeric IS DISTINCT FROM p_reference_val
     OR NULLIF(x->'event_state'->>'reference_poc','')::numeric IS DISTINCT FROM p_reference_poc;

  IF v_count<>48 THEN v_bad:=v_bad+1; END IF;

  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(p_snapshots) x
    GROUP BY x->>'snapshot_sequence' HAVING count(*)<>1
  ) THEN v_bad:=v_bad+1; END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(p_snapshots) x
    GROUP BY x->>'candle_id' HAVING count(*)<>1
  ) THEN v_bad:=v_bad+1; END IF;

  v_result:=jsonb_build_object(
    'is_valid',v_bad=0,
    'snapshot_count',v_count,
    'expected_count',48,
    'frozen_reference_profile_id',p_reference_profile_id,
    'frozen_reference_status',p_reference_status,
    'violations',v_bad,
    'writes_performed',false
  );
  RETURN v_result;
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.build_session_calculation_fixture(p_session_date date, p_bars jsonb, p_timestamp_convention text, p_prior_profiles jsonb, p_cutoff_at timestamp with time zone, p_boundary_records jsonb, p_opening_oi numeric DEFAULT NULL::numeric, p_latest_oi numeric DEFAULT NULL::numeric, p_oi_units_verified boolean DEFAULT false)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_validation jsonb; v_profile jsonb; v_snap_result jsonb; v_reference jsonb;
  v_ref_id uuid; v_ref_date date; v_ref_status text;
  v_ref_vah numeric; v_ref_val numeric; v_ref_poc numeric;
  v_snapshots jsonb; v_events jsonb := '[]'::jsonb; v_atr jsonb;
  v_boundary jsonb; v_oi jsonb; v_bars jsonb; v_snap_bars jsonb;
  v_rows jsonb; v_start timestamptz; v_end timestamptz; v_final_open timestamptz;
BEGIN
  IF p_timestamp_convention NOT IN ('OPEN','CLOSE') THEN
    RAISE EXCEPTION 'Timestamp convention must be explicitly OPEN or CLOSE';
  END IF;
  v_validation:=amt_engine_v17.validate_session_fixture(p_session_date,p_bars,p_timestamp_convention);
  IF COALESCE((v_validation->>'is_complete')::boolean,false) IS NOT TRUE THEN
    RAISE EXCEPTION 'Session calculation blocked by source validation: %',v_validation;
  END IF;
  v_profile:=amt_engine_v17.finalize_profile_fixture(p_session_date,p_bars,p_timestamp_convention,'AMT_ENGINE_V1.7');

  SELECT jsonb_agg(jsonb_build_object(
    'candle_id',b.candle_id,'source_timestamp',b.timestamp,
    'open',b.open,'high',b.high,'low',b.low,'close',b.close
  ) ORDER BY amt_engine_v17.canonical_open_time(b.timestamp,'30m',p_timestamp_convention))
  INTO v_snap_bars
  FROM jsonb_to_recordset(p_bars) AS b(candle_id text,timestamp timestamptz,open numeric,high numeric,low numeric,close numeric);
  v_snap_result:=amt_engine_v17.build_developing_snapshots_fixture(p_session_date,v_snap_bars,p_timestamp_convention,'AMT_ENGINE_V1.7');
  IF COALESCE((v_snap_result->>'is_finalizable')::boolean,false) IS NOT TRUE THEN
    RAISE EXCEPTION 'Developing snapshot chain is not finalizable';
  END IF;

  v_reference:=amt_engine_v17.resolve_reference_fixture(p_session_date,p_prior_profiles);
  v_ref_id:=NULLIF(v_reference->>'reference_profile_id','')::uuid;
  v_ref_date:=NULLIF(v_reference->>'reference_session_date','')::date;
  v_ref_status:=v_reference->>'reference_status';
  IF v_ref_id IS NOT NULL THEN
    SELECT vah_upper,val_lower,poc_lower INTO v_ref_vah,v_ref_val,v_ref_poc
    FROM amt_engine_v17.session_profiles
    WHERE profile_id=v_ref_id AND session_date=v_ref_date AND is_complete IS TRUE AND profile_status='COMPLETE';
    IF NOT FOUND THEN RAISE EXCEPTION 'Reference resolver selected a profile not present as valid persisted profile'; END IF;
  END IF;

  v_snapshots:=amt_engine_v17.attach_frozen_reference_fixture(
    v_snap_result->'snapshots',v_ref_id,v_ref_status,v_ref_date,v_ref_vah,v_ref_val,v_ref_poc
  );
  IF NOT (amt_engine_v17.validate_developing_snapshot_chain_fixture(
    v_snapshots,p_session_date,v_ref_id,v_ref_status,v_ref_vah,v_ref_val,v_ref_poc
  )->>'is_valid')::boolean THEN RAISE EXCEPTION 'Developing snapshot chain failed validation'; END IF;

  v_start:=((p_session_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata');
  v_end:=v_start+interval '24 hours';
  SELECT jsonb_agg(jsonb_build_object(
    'candle_id',b.candle_id,'canonical_open_time',amt_engine_v17.canonical_open_time(b.timestamp,'30m',p_timestamp_convention),
    'open',b.open,'high',b.high,'low',b.low,'close',b.close,'is_resolved',true
  ) ORDER BY amt_engine_v17.canonical_open_time(b.timestamp,'30m',p_timestamp_convention))
  INTO v_bars
  FROM jsonb_to_recordset(p_bars) AS b(candle_id text,timestamp timestamptz,open numeric,high numeric,low numeric,close numeric);

  IF v_ref_id IS NOT NULL THEN
    v_events:=amt_engine_v17.integrate_event_context_fixture(p_session_date,v_bars,v_ref_vah,v_ref_val)->'events';
    v_atr:=amt_engine_v17.integrate_event_context_fixture(p_session_date,v_bars,v_ref_vah,v_ref_val)->'atr_observations';
  ELSE
    v_atr:=amt_engine_v17.calculate_atr14_fixture(v_bars)->'observations';
  END IF;

  v_boundary:=amt_engine_v17.build_boundary_snapshot_fixture(p_session_date,p_cutoff_at,p_boundary_records);
  v_final_open:=v_end-interval '30 minutes';
  IF v_boundary->>'session_status'<>'COMPLETE'
     OR (v_boundary->>'last_valid_completed_candle_open')::timestamptz IS DISTINCT FROM v_final_open
     OR (v_boundary->>'last_valid_completed_candle_close')::timestamptz IS DISTINCT FROM v_end THEN
    RAISE EXCEPTION 'Fixed boundary snapshot does not certify the final expected candle';
  END IF;
  v_oi:=amt_engine_v17.calculate_session_oi_context_fixture(p_opening_oi,p_latest_oi,p_oi_units_verified);

  SELECT jsonb_agg(jsonb_build_object(
    'row_index',r.row_index,'row_lower',r.row_lower,'row_upper',r.row_upper,
    'tpo_count',r.tpo_count,'is_poc',r.is_poc,'is_value_area',r.is_value_area
  ) ORDER BY r.row_index)
  INTO v_rows
  FROM jsonb_to_recordset(v_profile->'profile'->'rows') AS r(
    row_index bigint,row_lower numeric,row_upper numeric,tpo_count int,is_poc boolean,is_value_area boolean
  );

  RETURN jsonb_build_object(
    'session_date',p_session_date,'method_version','AMT_ENGINE_V1.7',
    'source_timestamp_convention_used',p_timestamp_convention,
    'session_validation',v_validation,'profile_calculation',v_profile,
    'tpo_rows',COALESCE(v_rows,'[]'::jsonb),'reference_resolution',v_reference,
    'developing_snapshots',v_snapshots,'event_episodes',v_events,
    'atr_observations',v_atr,'oi_context',v_oi,'boundary_snapshot',v_boundary,
    'calculation_only',true,'persisted',false,'writer_bundle_adapter','NOT_YET_BUILT'
  );
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.adapt_session_calculation_to_writer_bundle_fixture(p_calculation jsonb, p_symbol text, p_source text, p_source_audit jsonb DEFAULT '[]'::jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_levels jsonb:=p_calculation->'profile_calculation'->'profile';
  v_validation jsonb:=p_calculation->'session_validation';
  v_ref jsonb:=p_calculation->'reference_resolution';
  v_boundary jsonb:=p_calculation->'boundary_snapshot';
  v_date date:=(p_calculation->>'session_date')::date;
  v_start timestamptz;
  v_ref_id text; v_ref_status text;
  v_snap jsonb; v_dev jsonb; v_atr jsonb; v_event jsonb; v_wick jsonb; v_audit jsonb;
  v_snapshots jsonb:='[]'; v_atrs jsonb:='[]'; v_events jsonb:='[]'; v_wicks jsonb:='[]';
  v_event_map jsonb:='{}'; v_event_id uuid; v_opp_id uuid; v_prev_id uuid; v_id text;
  v_pre_atr numeric; v_obs_open timestamptz; v_active_ids jsonb:='[]';
  v_rows jsonb:=p_calculation->'tpo_rows'; v_profile jsonb; v_boundary_out jsonb;
  v_seq int:=0;
BEGIN
  IF p_calculation IS NULL OR p_calculation->>'calculation_only'<>'true'
     OR p_calculation->>'persisted'<>'false' THEN RAISE EXCEPTION 'Calculation-only input required'; END IF;
  IF p_symbol IS NULL OR p_source IS NULL OR jsonb_typeof(p_source_audit)<>'array' OR jsonb_array_length(p_source_audit)<>48
     THEN RAISE EXCEPTION 'Symbol, source and exactly 48 source audit records are required'; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_source_audit) x
    WHERE x->>'source' IS DISTINCT FROM p_source OR x->>'symbol' IS DISTINCT FROM p_symbol
       OR NULLIF(x->>'series_type','') IS NULL OR x->>'resolution'<>'30m'
       OR NULLIF(x->>'source_candle_time','') IS NULL OR NULLIF(x->>'canonical_open_time','') IS NULL
       OR x->>'timestamp_convention' IS DISTINCT FROM p_calculation->>'source_timestamp_convention_used'
       OR x->>'validation_status' IS DISTINCT FROM 'VALID')
     THEN RAISE EXCEPTION 'Source audit records must match source/symbol, preserve timestamps and use VALID status'; END IF;
  IF (SELECT count(DISTINCT (x->>'canonical_open_time')::timestamptz) FROM jsonb_array_elements(p_source_audit) x)<>48
     THEN RAISE EXCEPTION 'Source audit canonical slots must be unique'; END IF;
  IF COALESCE((v_validation->>'is_complete')::boolean,false) IS NOT TRUE THEN RAISE EXCEPTION 'Incomplete session cannot be adapted'; END IF;
  v_ref_id:=NULLIF(v_ref->>'reference_profile_id',''); v_ref_status:=v_ref->>'reference_status';
  v_start:=((v_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata');

  FOR v_event IN SELECT value FROM jsonb_array_elements(COALESCE(p_calculation->'event_episodes','[]'::jsonb)) LOOP
    v_id:=v_event->>'event_id';
    v_event_map:=v_event_map||jsonb_build_object(v_id,md5('AMT_ENGINE_V1.7|'||v_date::text||'|'||v_id)::uuid);
  END LOOP;

  FOR v_snap IN SELECT value FROM jsonb_array_elements(p_calculation->'developing_snapshots') LOOP
    v_seq:=v_seq+1; v_dev:=v_snap->'developing_profile';
    SELECT x INTO v_audit FROM jsonb_array_elements(p_source_audit) x
    WHERE (x->>'canonical_open_time')::timestamptz=(v_snap->>'canonical_open_time')::timestamptz;
    IF v_audit IS NULL THEN RAISE EXCEPTION 'No source audit record for snapshot candle %',v_snap->>'candle_id'; END IF;
    v_snapshots:=v_snapshots||jsonb_build_array(jsonb_build_object(
      'snapshot_sequence',v_seq,
      'expected_interval_open',v_snap->'canonical_open_time',
      'candle_open',v_snap->'canonical_open_time','candle_close',v_snap->'canonical_close_time',
      'source',p_source,'symbol',p_symbol,'source_candle_identity',v_snap->'candle_id',
      'original_source_timestamp',v_snap->'source_timestamp',
      'timestamp_convention',p_calculation->>'source_timestamp_convention_used',
      'source_available_at',v_audit->'source_available_at','ingested_at',v_audit->'ingested_at',
      'reference_profile_id',v_ref_id,'reference_status',v_ref_status,
      'reference_vah',v_snap->'reference_vah','reference_val',v_snap->'reference_val','reference_poc',v_snap->'reference_poc',
      'developing_tpos',v_dev->'total_tpos','developing_poc_lower',v_dev->'poc_lower',
      'developing_poc_upper',v_dev->'poc_upper','developing_poc_count',v_dev->'poc_tpo_count',
      'developing_vah_lower',v_dev->'vah_lower','developing_vah_upper',v_dev->'vah_upper',
      'developing_val_lower',v_dev->'val_lower','developing_val_upper',v_dev->'val_upper',
      'developing_value_area_tpos',v_dev->'value_area_tpos',
      'event_state',jsonb_build_object('reference_profile_id',v_ref_id,'reference_status',v_ref_status,
        'reference_vah',v_snap->'reference_vah','reference_val',v_snap->'reference_val','reference_poc',v_snap->'reference_poc')
    ));
  END LOOP;

  FOR v_atr IN SELECT value FROM jsonb_array_elements(p_calculation->'atr_observations') LOOP
    v_pre_atr:=NULL;
    IF EXISTS (
      SELECT 1 FROM jsonb_array_elements(COALESCE(p_calculation->'event_episodes','[]'::jsonb)) ev
      WHERE (ev->>'started_at')::timestamptz=(v_atr->>'candle_open')::timestamptz
    ) THEN
      SELECT (x->>'atr14')::numeric INTO v_pre_atr FROM jsonb_array_elements(p_calculation->'atr_observations') x
      WHERE (x->>'candle_open')::timestamptz<(v_atr->>'candle_open')::timestamptz AND x->>'atr14' IS NOT NULL
      ORDER BY (x->>'candle_open')::timestamptz DESC LIMIT 1;
    END IF;
    v_atrs:=v_atrs||jsonb_build_array(v_atr||jsonb_build_object('pre_event_atr14',v_pre_atr));
  END LOOP;

  FOR v_event IN SELECT value FROM jsonb_array_elements(COALESCE(p_calculation->'event_episodes','[]'::jsonb)) LOOP
    v_id:=v_event->>'event_id'; v_event_id:=(v_event_map->>v_id)::uuid;
    v_opp_id:=NULLIF(v_event_map->>(v_event->>'opposite_event_id'),'')::uuid;
    v_prev_id:=NULLIF(v_event_map->>(v_event->>'previous_opposite_event_id'),'')::uuid;
    v_events:=v_events||jsonb_build_array(jsonb_build_object(
      'event_id',v_event_id,'direction',v_event->'direction','event_type',v_event->'event_type',
      'started_at',v_event->'started_at','terminated_at',v_event->'terminated_at',
      'termination_reason',v_event->'termination_reason','status',v_event->'status',
      'outcome_window_status',CASE WHEN v_event->>'status'='UNRESOLVED_SESSION_END'
        THEN 'CENSORED_SESSION_END' ELSE 'COMPLETE' END,
      'provisional_acceptance_at',v_event->'provisional_acceptance_at',
      'opposite_event_id',v_opp_id,'previous_opposite_event_id',v_prev_id,'initial_event_wick_interaction_at',NULL,
      'first_subsequent_wick_intersection_at',NULL,'first_boundary_touch_only_at',NULL,
      'first_strict_wick_penetration_at',NULL
    ));
    FOR v_wick IN SELECT value FROM jsonb_array_elements(COALESCE(v_event->'wick_observations','[]'::jsonb)) LOOP
      v_obs_open:=COALESCE(NULLIF(v_wick->>'candle_open','')::timestamptz,
        NULLIF(v_wick->>'candle_open_time','')::timestamptz,
        (v_wick->>'observed_at')::timestamptz-interval '30 minutes');
      v_wicks:=v_wicks||jsonb_build_array(jsonb_build_object(
        'event_id',v_event_id,'candle_open',v_obs_open,
        'wick_intersection',COALESCE((v_wick->>'wick_intersection')::boolean,false),
        'boundary_touch_only',COALESCE((v_wick->>'boundary_touch_only')::boolean,false),
        'strict_wick_penetration',COALESCE((v_wick->>'strict_wick_penetration')::boolean,false),
        'wick_low',v_wick->'wick_low','wick_high',v_wick->'wick_high',
        'reference_val',COALESCE(v_wick->'reference_val',p_calculation->'developing_snapshots'->0->'reference_val'),'reference_vah',COALESCE(v_wick->'reference_vah',p_calculation->'developing_snapshots'->0->'reference_vah'),
        'observed_at',v_wick->'observed_at','observation_type',v_wick->'observation_type'
      ));
    END LOOP;
    IF v_event->>'status'='UNRESOLVED_SESSION_END' THEN v_active_ids:=v_active_ids||jsonb_build_array(v_event_id); END IF;
  END LOOP;

  v_profile:=jsonb_build_object(
    'session_date',v_date,'method_version','AMT_ENGINE_V1.7','symbol',p_symbol,'source',p_source,
    'expected_bars',48,'observed_bars',48,'distinct_slots',48,'missing_slots',0,'duplicate_slots',0,
    'invalid_slots',0,'out_of_session_count',0,'is_complete',true,'profile_status','COMPLETE',
    'reference_profile_id',v_ref_id,'reference_status',v_ref_status,
    'reference_vah',p_calculation->'developing_snapshots'->0->'reference_vah',
    'reference_val',p_calculation->'developing_snapshots'->0->'reference_val',
    'reference_poc',p_calculation->'developing_snapshots'->0->'reference_poc',
    'first_candle_open',v_start,'last_candle_open',v_start+interval '23 hours 30 minutes',
    'total_tpos',v_levels->'total_tpos','poc_row_index',v_levels->'poc_row_index',
    'poc_lower',v_levels->'poc_lower','poc_upper',v_levels->'poc_upper','poc_tpo_count',v_levels->'poc_tpo_count',
    'vah_row_index',v_levels->'vah_row_index','vah_lower',v_levels->'vah_lower','vah_upper',v_levels->'vah_upper',
    'val_row_index',v_levels->'val_row_index','val_lower',v_levels->'val_lower','val_upper',v_levels->'val_upper',
    'value_area_tpos',v_levels->'value_area_tpos','target_tpos',v_levels->'target_tpos',
    'overshoot_tpos',v_levels->'overshoot_tpos',
    'overshoot_pct',CASE WHEN (v_levels->>'target_tpos')::numeric>0 THEN
      100*(v_levels->>'overshoot_tpos')::numeric/(v_levels->>'target_tpos')::numeric ELSE 0 END,
    'scheduled_boundary',v_boundary->'scheduled_boundary','cutoff_at',v_boundary->'cutoff_at'
  );
  v_boundary_out:=v_boundary||jsonb_build_object('active_event_ids',v_active_ids,
    'boundary_payload',jsonb_build_object('late_arrivals_can_rewrite_snapshot',false,
      'late_records_excluded',v_boundary->'late_records_excluded'));

  RETURN jsonb_build_object('profile',v_profile,'rows',v_rows,'developing_snapshots',v_snapshots,
    'atr_observations',v_atrs,'events',v_events,'wick_observations',v_wicks,
    'oi_context',p_calculation->'oi_context','boundary_snapshot',v_boundary_out,
    'source_audit',p_source_audit,'adapter_version','AMT_ENGINE_V1.7_WRITER_ADAPTER_2',
    'calculation_only',true,'persisted',false);
END;$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.validate_live_session_inputs_fixture(p_session_date date, p_price_records jsonb, p_oi_records jsonb, p_cutoff_at timestamp with time zone)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
 v_start timestamptz;
 v_end timestamptz;
 v_reasons text[]:=ARRAY[]::text[];
 v_price_count int:=0; v_oi_count int:=0;
 v_price_distinct int:=0; v_oi_distinct int:=0;
 v_price_invalid int:=0; v_oi_invalid int:=0;
 v_price_late int:=0; v_oi_late int:=0;
 v_price_missing int:=0; v_oi_missing int:=0;
 v_price_dupes int:=0; v_oi_dupes int:=0;
 v_unmatched int:=0;
BEGIN
 IF p_session_date IS NULL OR p_cutoff_at IS NULL THEN
  RAISE EXCEPTION 'Session date and cutoff are required';
 END IF;
 IF jsonb_typeof(p_price_records)<>'array' OR jsonb_typeof(p_oi_records)<>'array' THEN
  RAISE EXCEPTION 'Price and OI records must both be JSON arrays';
 END IF;
 v_start:=((p_session_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata');
 v_end:=v_start+interval '24 hours';

 SELECT count(*) INTO v_price_count FROM jsonb_array_elements(p_price_records);
 SELECT count(*) INTO v_oi_count FROM jsonb_array_elements(p_oi_records);

 SELECT count(DISTINCT canonical_open),count(*) FILTER(WHERE invalid)
 INTO v_price_distinct,v_price_invalid
 FROM (
  SELECT amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN') canonical_open,
   (r.open IS NULL OR r.high IS NULL OR r.low IS NULL OR r.close IS NULL
    OR r.low<0 OR r.high<r.low OR r.open<r.low OR r.open>r.high
    OR r.close<r.low OR r.close>r.high
    OR r.source_available_at IS NULL OR r.ingested_at IS NULL) invalid
  FROM jsonb_to_recordset(p_price_records) AS r(
   timestamp timestamptz,open numeric,high numeric,low numeric,close numeric,
   source_available_at timestamptz,ingested_at timestamptz)
 ) x;
 SELECT count(DISTINCT canonical_open),count(*) FILTER(WHERE invalid)
 INTO v_oi_distinct,v_oi_invalid
 FROM (
  SELECT amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN') canonical_open,
   (r.open IS NULL OR r.high IS NULL OR r.low IS NULL OR r.close IS NULL
    OR r.low<0 OR r.high<r.low OR r.open<r.low OR r.open>r.high
    OR r.close<r.low OR r.close>r.high
    OR r.source_available_at IS NULL OR r.ingested_at IS NULL) invalid
  FROM jsonb_to_recordset(p_oi_records) AS r(
   timestamp timestamptz,open numeric,high numeric,low numeric,close numeric,
   source_available_at timestamptz,ingested_at timestamptz)
 ) x;

 SELECT count(*) INTO v_price_dupes FROM (
  SELECT amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN') t
  FROM jsonb_to_recordset(p_price_records) AS r(timestamp timestamptz)
  GROUP BY 1 HAVING count(*)>1
 ) d;
 SELECT count(*) INTO v_oi_dupes FROM (
  SELECT amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN') t
  FROM jsonb_to_recordset(p_oi_records) AS r(timestamp timestamptz)
  GROUP BY 1 HAVING count(*)>1
 ) d;

 -- Closed-candle boundary remains strict. Source availability has no grace;
 -- ingestion receipt alone may arrive up to 10 minutes after session cutoff.
 SELECT count(*) INTO v_price_late FROM jsonb_to_recordset(p_price_records) AS r(
  timestamp timestamptz,source_available_at timestamptz,ingested_at timestamptz)
 WHERE r.timestamp+interval '30 minutes'<=p_cutoff_at
  AND (r.source_available_at>p_cutoff_at
       OR r.ingested_at>p_cutoff_at+interval '10 minutes');
 SELECT count(*) INTO v_oi_late FROM jsonb_to_recordset(p_oi_records) AS r(
  timestamp timestamptz,source_available_at timestamptz,ingested_at timestamptz)
 WHERE r.timestamp+interval '30 minutes'<=p_cutoff_at
  AND (r.source_available_at>p_cutoff_at
       OR r.ingested_at>p_cutoff_at+interval '10 minutes');

 SELECT count(*) INTO v_price_missing FROM generate_series(0,47) g(i)
 WHERE NOT EXISTS(SELECT 1 FROM jsonb_to_recordset(p_price_records) AS r(timestamp timestamptz)
  WHERE amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')=v_start+g.i*interval '30 minutes');
 SELECT count(*) INTO v_oi_missing FROM generate_series(0,47) g(i)
 WHERE NOT EXISTS(SELECT 1 FROM jsonb_to_recordset(p_oi_records) AS r(timestamp timestamptz)
  WHERE amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')=v_start+g.i*interval '30 minutes');

 SELECT count(*) INTO v_unmatched FROM (
  SELECT t FROM (
   SELECT amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN') t
   FROM jsonb_to_recordset(p_price_records) AS r(timestamp timestamptz)
   UNION
   SELECT amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN') t
   FROM jsonb_to_recordset(p_oi_records) AS r(timestamp timestamptz)
  ) slots
  WHERE (SELECT count(*) FROM jsonb_to_recordset(p_price_records) AS r(timestamp timestamptz)
    WHERE amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')=slots.t)
   <> (SELECT count(*) FROM jsonb_to_recordset(p_oi_records) AS r(timestamp timestamptz)
    WHERE amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')=slots.t)
 ) q;

 IF v_price_count<>48 OR v_price_distinct<>48 OR v_price_missing>0 OR v_price_dupes>0 THEN
  v_reasons:=array_append(v_reasons,'PRICE_SERIES_NOT_EXACTLY_48_UNIQUE_SESSION_INTERVALS');
 END IF;
 IF v_oi_count<>48 OR v_oi_distinct<>48 OR v_oi_missing>0 OR v_oi_dupes>0 THEN
  v_reasons:=array_append(v_reasons,'OI_SERIES_NOT_EXACTLY_48_UNIQUE_SESSION_INTERVALS');
 END IF;
 IF v_price_invalid>0 THEN v_reasons:=array_append(v_reasons,'INVALID_PRICE_OHLC_OR_RECEIPT_METADATA'); END IF;
 IF v_oi_invalid>0 THEN v_reasons:=array_append(v_reasons,'INVALID_OI_OHLC_OR_RECEIPT_METADATA'); END IF;
 IF v_price_late>0 THEN v_reasons:=array_append(v_reasons,'LATE_PRICE_RECORDS_PRESENT'); END IF;
 IF v_oi_late>0 THEN v_reasons:=array_append(v_reasons,'LATE_OI_RECORDS_PRESENT'); END IF;
 IF v_unmatched>0 THEN v_reasons:=array_append(v_reasons,'PRICE_OI_INTERVALS_NOT_PAIRED'); END IF;
 IF EXISTS(SELECT 1 FROM jsonb_to_recordset(p_price_records) AS r(timestamp timestamptz)
  WHERE amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')<v_start
   OR amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')>=v_end)
 OR EXISTS(SELECT 1 FROM jsonb_to_recordset(p_oi_records) AS r(timestamp timestamptz)
  WHERE amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')<v_start
   OR amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')>=v_end) THEN
  v_reasons:=array_append(v_reasons,'OUT_OF_SESSION_INTERVAL_PRESENT');
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_to_recordset(p_price_records) AS r(timestamp timestamptz)
  WHERE extract(epoch FROM (amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')-v_start))::bigint%1800<>0)
 OR EXISTS(SELECT 1 FROM jsonb_to_recordset(p_oi_records) AS r(timestamp timestamptz)
  WHERE extract(epoch FROM (amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')-v_start))::bigint%1800<>0) THEN
  v_reasons:=array_append(v_reasons,'OFF_GRID_INTERVAL_PRESENT');
 END IF;
 RETURN jsonb_build_object('session_date',p_session_date,'session_start',v_start,'session_end_exclusive',v_end,
  'cutoff_at',p_cutoff_at,'price_records',v_price_count,'oi_records',v_oi_count,
  'price_distinct_intervals',v_price_distinct,'oi_distinct_intervals',v_oi_distinct,
  'price_missing_intervals',v_price_missing,'oi_missing_intervals',v_oi_missing,
  'price_duplicate_intervals',v_price_dupes,'oi_duplicate_intervals',v_oi_dupes,
  'price_invalid_records',v_price_invalid,'oi_invalid_records',v_oi_invalid,
  'late_price_records',v_price_late,'late_oi_records',v_oi_late,
  'unpaired_interval_count',v_unmatched,'is_valid',cardinality(v_reasons)=0,'reasons',to_jsonb(v_reasons),
  'interpretation','PRICE_AND_OI_INPUT_INTEGRITY_ONLY_NOT_A_DIRECTIONAL_SIGNAL','persisted',false);
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.build_validated_session_calculation_fixture(p_session_date date, p_price_records jsonb, p_oi_records jsonb, p_prior_profiles jsonb, p_cutoff_at timestamp with time zone, p_oi_units_verified boolean DEFAULT false)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
 v_validation jsonb; v_price_bars jsonb; v_boundary_records jsonb;
 v_opening_oi numeric; v_latest_oi numeric; v_result jsonb;
BEGIN
 v_validation:=amt_engine_v17.validate_live_session_inputs_fixture(
  p_session_date,p_price_records,p_oi_records,p_cutoff_at);
 IF COALESCE((v_validation->>'is_valid')::boolean,false) IS NOT TRUE THEN
  RAISE EXCEPTION 'Live session input validation failed: %',v_validation->'reasons';
 END IF;
 IF jsonb_typeof(p_prior_profiles)<>'array' THEN
  RAISE EXCEPTION 'Prior profile candidates must be a JSON array';
 END IF;

 SELECT jsonb_agg(jsonb_build_object(
  'candle_id',COALESCE(NULLIF(r.candle_id,''),'PRICE|'||to_char(r.timestamp AT TIME ZONE 'UTC','YYYYMMDDHH24MISS')),
  'timestamp',r.timestamp,'open',r.open,'high',r.high,'low',r.low,'close',r.close
 ) ORDER BY r.timestamp)
 INTO v_price_bars
 FROM jsonb_to_recordset(p_price_records) AS r(
  candle_id text,timestamp timestamptz,open numeric,high numeric,low numeric,close numeric);

 SELECT jsonb_agg(jsonb_build_object(
  'candle_id',COALESCE(NULLIF(r.candle_id,''),'PRICE|'||to_char(r.timestamp AT TIME ZONE 'UTC','YYYYMMDDHH24MISS')),
  'candle_open',r.timestamp,'candle_close',r.timestamp+interval '30 minutes',
  'source_available_at',r.source_available_at,'ingested_at',r.ingested_at,
  'is_valid',(r.open IS NOT NULL AND r.high IS NOT NULL AND r.low IS NOT NULL AND r.close IS NOT NULL
   AND r.low>=0 AND r.high>=r.low AND r.open BETWEEN r.low AND r.high AND r.close BETWEEN r.low AND r.high)
 ) ORDER BY r.timestamp)
 INTO v_boundary_records
 FROM jsonb_to_recordset(p_price_records) AS r(
  candle_id text,timestamp timestamptz,open numeric,high numeric,low numeric,close numeric,
  source_available_at timestamptz,ingested_at timestamptz);

 SELECT (array_agg(r.open ORDER BY r.timestamp))[1],
        (array_agg(r.close ORDER BY r.timestamp DESC))[1]
 INTO v_opening_oi,v_latest_oi
 FROM jsonb_to_recordset(p_oi_records) AS r(timestamp timestamptz,open numeric,close numeric);

 v_result:=amt_engine_v17.build_session_calculation_fixture(
  p_session_date,v_price_bars,'OPEN',p_prior_profiles,p_cutoff_at,
  v_boundary_records,v_opening_oi,v_latest_oi,p_oi_units_verified);

 RETURN v_result||jsonb_build_object(
  'live_input_validation',v_validation,
  'oi_input_interval_count',jsonb_array_length(p_oi_records),
  'calculation_only',true,'persisted',false,
  'input_contract_version','PAIRED_PRICE_OI_48_INTERVALS_V1'
 );
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.adapt_dual_series_session_calculation_fixture(p_calculation jsonb, p_symbol text, p_source text, p_source_audit jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE v_price_audit jsonb; v_bundle jsonb; v_oi_count int;
BEGIN
 IF jsonb_typeof(p_source_audit)<>'array' OR jsonb_array_length(p_source_audit)<48 OR jsonb_array_length(p_source_audit)>96 THEN
  RAISE EXCEPTION 'Dual-series audit must contain 48 PRICE records and 0-48 OI records';
 END IF;
 IF jsonb_typeof(p_calculation->'oi_input_audit')<>'array' THEN
  RAISE EXCEPTION 'Calculation must carry OI input receipt evidence';
 END IF;
 v_oi_count:=jsonb_array_length(p_calculation->'oi_input_audit');
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_source_audit) x
  WHERE x->>'source' IS DISTINCT FROM p_source OR x->>'symbol' IS DISTINCT FROM p_symbol
   OR x->>'resolution'<>'30m' OR x->>'timestamp_convention'<>'OPEN'
   OR NULLIF(x->>'source_candle_time','') IS NULL OR NULLIF(x->>'canonical_open_time','') IS NULL
   OR NULLIF(x->>'source_available_at','') IS NULL OR NULLIF(x->>'ingested_at','') IS NULL
   OR (x->>'series_type'='PRICE' AND x->>'validation_status'<>'VALID')
   OR (x->>'series_type'='OI' AND x->>'validation_status' NOT IN ('VALID','QUARANTINED','INVALID'))
   OR x->>'series_type' NOT IN ('PRICE','OI')) THEN
  RAISE EXCEPTION 'Dual-series audit records have invalid identity, timestamps, metadata or status';
 END IF;
 IF (SELECT count(*) FROM jsonb_array_elements(p_source_audit) x WHERE x->>'series_type'='PRICE')<>48
 OR (SELECT count(*) FROM jsonb_array_elements(p_source_audit) x WHERE x->>'series_type'='OI')<>v_oi_count
 OR (SELECT count(DISTINCT (x->>'canonical_open_time')::timestamptz) FROM jsonb_array_elements(p_source_audit) x WHERE x->>'series_type'='PRICE')<>48
 OR (SELECT count(DISTINCT (x->>'canonical_open_time')::timestamptz) FROM jsonb_array_elements(p_source_audit) x WHERE x->>'series_type'='OI')<>v_oi_count THEN
  RAISE EXCEPTION 'Dual-series audit counts/unique intervals do not match supplied inputs';
 END IF;

 -- OI receipt evidence is compared by instant, not JSON timestamp spelling.
 -- Compare in both directions so neither missing nor extra calculation receipts pass.
 IF EXISTS(
  SELECT 1 FROM jsonb_array_elements(p_source_audit) x
  WHERE x->>'series_type'='OI'
   AND NOT EXISTS(
    SELECT 1 FROM jsonb_array_elements(p_calculation->'oi_input_audit') y
    WHERE NULLIF(x->>'source_candle_time','')::timestamptz
          IS NOT DISTINCT FROM NULLIF(y->>'source_candle_time','')::timestamptz
      AND NULLIF(x->>'canonical_open_time','')::timestamptz
          IS NOT DISTINCT FROM NULLIF(y->>'canonical_open_time','')::timestamptz
      AND NULLIF(x->>'source_available_at','')::timestamptz
          IS NOT DISTINCT FROM NULLIF(y->>'source_available_at','')::timestamptz
      AND NULLIF(x->>'ingested_at','')::timestamptz
          IS NOT DISTINCT FROM NULLIF(y->>'ingested_at','')::timestamptz
   )
 )
 OR EXISTS(
  SELECT 1 FROM jsonb_array_elements(p_calculation->'oi_input_audit') y
  WHERE NOT EXISTS(
   SELECT 1 FROM jsonb_array_elements(p_source_audit) x
   WHERE x->>'series_type'='OI'
     AND NULLIF(x->>'source_candle_time','')::timestamptz
         IS NOT DISTINCT FROM NULLIF(y->>'source_candle_time','')::timestamptz
     AND NULLIF(x->>'canonical_open_time','')::timestamptz
         IS NOT DISTINCT FROM NULLIF(y->>'canonical_open_time','')::timestamptz
     AND NULLIF(x->>'source_available_at','')::timestamptz
         IS NOT DISTINCT FROM NULLIF(y->>'source_available_at','')::timestamptz
     AND NULLIF(x->>'ingested_at','')::timestamptz
         IS NOT DISTINCT FROM NULLIF(y->>'ingested_at','')::timestamptz
  )
 ) THEN
  RAISE EXCEPTION 'OI audit does not exactly match supplied OI input receipt evidence';
 END IF;

 IF COALESCE((p_calculation->'live_input_validation'->>'oi_context_available')::boolean,false)
 AND (v_oi_count<>48 OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_source_audit) x
  WHERE x->>'series_type'='PRICE' AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_source_audit) y
   WHERE y->>'series_type'='OI' AND (y->>'canonical_open_time')::timestamptz=(x->>'canonical_open_time')::timestamptz))
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_source_audit) x
   WHERE x->>'series_type'='OI' AND x->>'validation_status'<>'VALID')) THEN
  RAISE EXCEPTION 'OI context marked available without 48 paired valid OI audit intervals';
 END IF;
 SELECT jsonb_agg(x ORDER BY (x->>'canonical_open_time')::timestamptz)
 INTO v_price_audit FROM jsonb_array_elements(p_source_audit) x WHERE x->>'series_type'='PRICE';
 v_bundle:=amt_engine_v17.adapt_session_calculation_to_writer_bundle_fixture(p_calculation,p_symbol,p_source,v_price_audit);
 RETURN v_bundle||jsonb_build_object('source_audit',p_source_audit,'oi_input_audit',p_calculation->'oi_input_audit',
  'adapter_version','AMT_ENGINE_V1.7_DUAL_SERIES_ADAPTER_4',
  'source_audit_counts',jsonb_build_object('PRICE',48,'OI',v_oi_count));
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.persist_validated_dual_series_bundle_fixture(p_bundle jsonb, p_test_mode boolean DEFAULT false)
 RETURNS uuid
 LANGUAGE plpgsql
AS $function$
DECLARE p jsonb; a jsonb; v_source text; v_symbol text; v_date date;
 v_oi_count int; v_oi_available boolean; v_cutoff timestamptz;
BEGIN
 p:=p_bundle->'profile'; a:=p_bundle->'source_audit'; v_cutoff:=NULLIF(p->>'cutoff_at','')::timestamptz;
 IF v_cutoff IS NULL THEN RAISE EXCEPTION 'Persistence blocked: explicit cutoff required'; END IF;
 IF jsonb_typeof(a)<>'array' OR jsonb_array_length(a)<48 OR jsonb_array_length(a)>96 THEN
  RAISE EXCEPTION 'Persistence blocked: 48 PRICE and 0-48 OI audit records required';
 END IF;
 IF jsonb_typeof(p_bundle->'oi_input_audit')<>'array' THEN
  RAISE EXCEPTION 'Persistence blocked: OI receipt evidence missing';
 END IF;
 v_oi_count:=jsonb_array_length(p_bundle->'oi_input_audit');
 v_oi_available:=COALESCE((p_bundle->'oi_context'->>'context_state')<>'UNAVAILABLE',false);
 v_source:=p->>'source'; v_symbol:=p->>'symbol'; v_date:=(p->>'session_date')::date;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(a) x
  WHERE x->>'source' IS DISTINCT FROM v_source OR x->>'resolution'<>'30m' OR x->>'timestamp_convention'<>'OPEN'
   OR NULLIF(x->>'source_candle_time','') IS NULL OR NULLIF(x->>'canonical_open_time','') IS NULL
   OR NULLIF(x->>'source_available_at','') IS NULL OR NULLIF(x->>'ingested_at','') IS NULL
   OR (x->>'source_available_at')::timestamptz>v_cutoff
   OR (x->>'ingested_at')::timestamptz>v_cutoff+interval '10 minutes'
   OR (x->>'series_type'='PRICE' AND (x->>'symbol' IS DISTINCT FROM v_symbol OR x->>'validation_status'<>'VALID'))
   OR (x->>'series_type'='OI' AND (x->>'symbol' IS DISTINCT FROM ('OI:'||v_symbol) OR x->>'validation_status' NOT IN ('VALID','QUARANTINED','INVALID')))
   OR x->>'series_type' NOT IN ('PRICE','OI')) THEN
  RAISE EXCEPTION 'Persistence blocked: invalid dual-series source audit identity, metadata or post-grace receipt';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_bundle->'oi_input_audit') x
  WHERE NULLIF(x->>'source_available_at','') IS NULL OR NULLIF(x->>'ingested_at','') IS NULL
   OR (x->>'source_available_at')::timestamptz>v_cutoff
   OR (x->>'ingested_at')::timestamptz>v_cutoff+interval '10 minutes') THEN
  RAISE EXCEPTION 'Persistence blocked: OI receipt evidence missing or after permitted grace';
 END IF;
 IF (SELECT count(*) FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE')<>48
 OR (SELECT count(*) FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI')<>v_oi_count
 OR (SELECT count(DISTINCT (x->>'canonical_open_time')::timestamptz) FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE')<>48
 OR (SELECT count(DISTINCT (x->>'canonical_open_time')::timestamptz) FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI')<>v_oi_count THEN
  RAISE EXCEPTION 'Persistence blocked: source audit counts/unique intervals failed';
 END IF;
 IF EXISTS(
  SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI'
   AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_bundle->'oi_input_audit') y
    WHERE NULLIF(y->>'source_candle_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(x->>'source_candle_time','')::timestamptz
     AND NULLIF(y->>'canonical_open_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(x->>'canonical_open_time','')::timestamptz
     AND NULLIF(y->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(x->>'source_available_at','')::timestamptz
     AND NULLIF(y->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(x->>'ingested_at','')::timestamptz)
 )
 OR EXISTS(
  SELECT 1 FROM jsonb_array_elements(p_bundle->'oi_input_audit') y
  WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI'
    AND NULLIF(x->>'source_candle_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_candle_time','')::timestamptz
    AND NULLIF(x->>'canonical_open_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'canonical_open_time','')::timestamptz
    AND NULLIF(x->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_available_at','')::timestamptz
    AND NULLIF(x->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'ingested_at','')::timestamptz)
 ) THEN
  RAISE EXCEPTION 'Persistence blocked: OI audit differs from supplied OI receipt evidence';
 END IF;
 IF v_oi_available AND (v_oi_count<>48 OR EXISTS(SELECT 1 FROM jsonb_array_elements(a) x
  WHERE x->>'series_type'='OI' AND x->>'validation_status'<>'VALID')
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE'
   AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(a) y WHERE y->>'series_type'='OI'
    AND (y->>'canonical_open_time')::timestamptz=(x->>'canonical_open_time')::timestamptz))) THEN
  RAISE EXCEPTION 'Persistence blocked: available OI context requires 48 paired valid OI intervals';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(a) x
  WHERE (x->>'canonical_open_time')::timestamptz<((v_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata')
   OR (x->>'canonical_open_time')::timestamptz>=(((v_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata')+interval '24 hours')
   OR (x->>'canonical_open_time')::timestamptz<>(x->>'source_candle_time')::timestamptz) THEN
  RAISE EXCEPTION 'Persistence blocked: audit timestamps do not match session or OPEN convention';
 END IF;
 RETURN amt_engine_v17.persist_consistent_full_session_bundle(p_bundle,p_test_mode);
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.build_audited_dual_series_calculation_fixture(p_session_date date, p_price_records jsonb, p_oi_records jsonb, p_prior_profiles jsonb, p_cutoff_at timestamp with time zone, p_oi_units_verified boolean DEFAULT false)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE v_validation jsonb; v_price_bars jsonb; v_boundary_records jsonb;
 v_oi_audit jsonb; v_opening_oi numeric; v_latest_oi numeric; v_result jsonb;
BEGIN
 v_validation:=amt_engine_v17.validate_price_required_oi_optional_fixture(
  p_session_date,p_price_records,p_oi_records,p_cutoff_at);
 IF COALESCE((v_validation->>'price_is_valid')::boolean,false) IS NOT TRUE THEN
  RAISE EXCEPTION 'Price session validation failed: %',v_validation->'price_validation'->'reasons';
 END IF;
 IF jsonb_typeof(p_prior_profiles)<>'array' THEN RAISE EXCEPTION 'Prior profile candidates must be a JSON array'; END IF;

 SELECT jsonb_agg(jsonb_build_object('candle_id',COALESCE(NULLIF(r.candle_id,''),'PRICE|'||to_char(r.timestamp AT TIME ZONE 'UTC','YYYYMMDDHH24MISS')),
  'timestamp',r.timestamp,'open',r.open,'high',r.high,'low',r.low,'close',r.close) ORDER BY r.timestamp)
 INTO v_price_bars FROM jsonb_to_recordset(p_price_records) AS r(candle_id text,timestamp timestamptz,open numeric,high numeric,low numeric,close numeric);

 SELECT jsonb_agg(jsonb_build_object('candle_id',COALESCE(NULLIF(r.candle_id,''),'PRICE|'||to_char(r.timestamp AT TIME ZONE 'UTC','YYYYMMDDHH24MISS')),
  'candle_open',r.timestamp,'candle_close',r.timestamp+interval '30 minutes',
  'source_available_at',r.source_available_at,'ingested_at',r.ingested_at,
  'is_valid',(r.open IS NOT NULL AND r.high IS NOT NULL AND r.low IS NOT NULL AND r.close IS NOT NULL
   AND r.low>=0 AND r.high>=r.low AND r.open BETWEEN r.low AND r.high AND r.close BETWEEN r.low AND r.high)
 ) ORDER BY r.timestamp)
 INTO v_boundary_records FROM jsonb_to_recordset(p_price_records) AS r(
  candle_id text,timestamp timestamptz,open numeric,high numeric,low numeric,close numeric,
  source_available_at timestamptz,ingested_at timestamptz);

 IF COALESCE((v_validation->>'oi_context_available')::boolean,false) THEN
  SELECT (array_agg(r.open ORDER BY r.timestamp))[1],(array_agg(r.close ORDER BY r.timestamp DESC))[1]
  INTO v_opening_oi,v_latest_oi FROM jsonb_to_recordset(p_oi_records) AS r(timestamp timestamptz,open numeric,close numeric);
 END IF;
 SELECT jsonb_agg(jsonb_build_object('source_candle_time',r.timestamp,
  'canonical_open_time',amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN'),
  'source_available_at',r.source_available_at,'ingested_at',r.ingested_at) ORDER BY r.timestamp)
 INTO v_oi_audit FROM jsonb_to_recordset(p_oi_records) AS r(
  timestamp timestamptz,source_available_at timestamptz,ingested_at timestamptz);

 v_result:=amt_engine_v17.build_session_calculation_fixture(
  p_session_date,v_price_bars,'OPEN',p_prior_profiles,p_cutoff_at,v_boundary_records,
  v_opening_oi,v_latest_oi,CASE WHEN COALESCE((v_validation->>'oi_context_available')::boolean,false)
   THEN p_oi_units_verified ELSE false END);
 RETURN v_result||jsonb_build_object('live_input_validation',v_validation,
  'oi_input_interval_count',jsonb_array_length(p_oi_records),
  'oi_input_audit',COALESCE(v_oi_audit,'[]'::jsonb),
  'calculation_only',true,'persisted',false,
  'input_contract_version','PRICE_REQUIRED_OI_OPTIONAL_V1');
END;$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.validate_price_required_oi_optional_fixture(p_session_date date, p_price_records jsonb, p_oi_records jsonb, p_cutoff_at timestamp with time zone)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE v_price jsonb; v_oi jsonb; v_pair_mismatch int; v_oi_ok boolean; v_oi_warnings jsonb;
BEGIN
 IF p_price_records IS NULL OR jsonb_typeof(p_price_records)<>'array' THEN
  RAISE EXCEPTION 'Price records must be a JSON array';
 END IF;
 IF p_oi_records IS NULL OR jsonb_typeof(p_oi_records)<>'array' THEN
  RAISE EXCEPTION 'OI records must be a JSON array; use [] when unavailable';
 END IF;
 v_price:=amt_engine_v17.validate_live_session_inputs_fixture(p_session_date,p_price_records,p_price_records,p_cutoff_at);
 IF jsonb_array_length(p_oi_records)=0 THEN
  v_oi:=jsonb_build_object('is_valid',false,'reasons',jsonb_build_array('OI_SERIES_NOT_EXACTLY_48_UNIQUE_SESSION_INTERVALS'));
 ELSE
  v_oi:=amt_engine_v17.validate_live_session_inputs_fixture(p_session_date,p_oi_records,p_oi_records,p_cutoff_at);
 END IF;
 SELECT count(*) INTO v_pair_mismatch FROM (
  SELECT t FROM (
   SELECT amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN') t
   FROM jsonb_to_recordset(p_price_records) AS r(timestamp timestamptz)
   UNION
   SELECT amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN') t
   FROM jsonb_to_recordset(p_oi_records) AS r(timestamp timestamptz)
  ) u
  WHERE (SELECT count(*) FROM jsonb_to_recordset(p_price_records) AS r(timestamp timestamptz)
   WHERE amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')=u.t)
  <> (SELECT count(*) FROM jsonb_to_recordset(p_oi_records) AS r(timestamp timestamptz)
   WHERE amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN')=u.t)
 ) q;
 v_oi_ok:=COALESCE((v_oi->>'is_valid')::boolean,false) AND v_pair_mismatch=0;
 SELECT COALESCE(jsonb_agg(DISTINCT to_jsonb(CASE value
  WHEN 'PRICE_SERIES_NOT_EXACTLY_48_UNIQUE_SESSION_INTERVALS' THEN 'OI_SERIES_NOT_EXACTLY_48_UNIQUE_SESSION_INTERVALS'
  WHEN 'LATE_PRICE_RECORDS_PRESENT' THEN 'LATE_OI_RECORDS_PRESENT'
  WHEN 'INVALID_PRICE_OHLC_OR_RECEIPT_METADATA' THEN 'INVALID_OI_OHLC_OR_RECEIPT_METADATA'
  WHEN 'OUT_OF_SESSION_INTERVAL_PRESENT' THEN 'OI_OUT_OF_SESSION_INTERVAL_PRESENT'
  WHEN 'OFF_GRID_INTERVAL_PRESENT' THEN 'OI_OFF_GRID_INTERVAL_PRESENT'
  WHEN 'PRICE_OI_INTERVALS_NOT_PAIRED' THEN 'OI_INTERVAL_SET_INCOMPLETE'
  ELSE value END)), '[]'::jsonb)
 INTO v_oi_warnings FROM jsonb_array_elements_text(COALESCE(v_oi->'reasons','[]'::jsonb)) e(value);
 IF v_pair_mismatch>0 AND NOT v_oi_warnings @> jsonb_build_array('OI_INTERVAL_SET_INCOMPLETE') THEN
  v_oi_warnings:=v_oi_warnings||jsonb_build_array('OI_INTERVAL_SET_INCOMPLETE');
 END IF;
 RETURN jsonb_build_object('session_date',p_session_date,'session_start',v_price->'session_start',
  'session_end_exclusive',v_price->'session_end_exclusive','cutoff_at',p_cutoff_at,
  'price_validation',v_price,'oi_validation',v_oi,
  'price_is_valid',COALESCE((v_price->>'is_valid')::boolean,false),
  'oi_context_available',v_oi_ok,'oi_warnings',v_oi_warnings,
  'is_valid',COALESCE((v_price->>'is_valid')::boolean,false),
  'oi_interval_count',jsonb_array_length(p_oi_records),
  'interpretation','PRICE_PROFILE_VALIDATION_REQUIRED; OI_IS_OPTIONAL_NON_DIRECTIONAL_CONTEXT_ONLY',
  'persisted',false);
END;$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.build_audited_dual_series_calculation_fixture_v2(p_session_date date, p_price_records jsonb, p_oi_records jsonb, p_prior_profiles jsonb, p_cutoff_at timestamp with time zone, p_oi_units_verified boolean DEFAULT false)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$ DECLARE v_result jsonb; v_price_audit jsonb; BEGIN v_result:=amt_engine_v17.build_audited_dual_series_calculation_fixture(p_session_date,p_price_records,p_oi_records,p_prior_profiles,p_cutoff_at,p_oi_units_verified); SELECT jsonb_agg(jsonb_build_object('candle_id',COALESCE(NULLIF(r.candle_id,''),'PRICE|'||to_char(r.timestamp AT TIME ZONE 'UTC','YYYYMMDDHH24MISS')),'source_candle_time',r.timestamp,'canonical_open_time',amt_engine_v17.canonical_open_time(r.timestamp,'30m','OPEN'),'source_available_at',r.source_available_at,'ingested_at',r.ingested_at,'validation_status','VALID') ORDER BY r.timestamp) INTO v_price_audit FROM jsonb_to_recordset(p_price_records) r(candle_id text,timestamp timestamptz,source_available_at timestamptz,ingested_at timestamptz); RETURN v_result||jsonb_build_object('price_input_audit',COALESCE(v_price_audit,'[]'::jsonb),'input_contract_version','PRICE_REQUIRED_OI_OPTIONAL_V2'); END;$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.adapt_dual_series_session_calculation_fixture_v5(p_calculation jsonb, p_symbol text, p_source text, p_source_audit jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
 v_bundle jsonb;
 v_boundary jsonb;
BEGIN
 IF jsonb_typeof(p_calculation->'price_input_audit')<>'array'
    OR jsonb_array_length(p_calculation->'price_input_audit')<>48 THEN
  RAISE EXCEPTION 'Calculation must carry exactly 48 PRICE input receipt records';
 END IF;
 IF jsonb_typeof(p_source_audit)<>'array' THEN
  RAISE EXCEPTION 'Supplied source audit must be a JSON array';
 END IF;
 IF (SELECT count(*) FROM jsonb_array_elements(p_source_audit) x
     WHERE x->>'series_type'='PRICE')<>48
 OR EXISTS(
  SELECT 1 FROM jsonb_array_elements(p_source_audit) x
  WHERE x->>'series_type'='PRICE'
   AND NOT EXISTS(
    SELECT 1 FROM jsonb_array_elements(p_calculation->'price_input_audit') y
    WHERE NULLIF(x->>'source_candle_time','')::timestamptz
          IS NOT DISTINCT FROM NULLIF(y->>'source_candle_time','')::timestamptz
      AND NULLIF(x->>'canonical_open_time','')::timestamptz
          IS NOT DISTINCT FROM NULLIF(y->>'canonical_open_time','')::timestamptz
      AND NULLIF(x->>'source_available_at','')::timestamptz
          IS NOT DISTINCT FROM NULLIF(y->>'source_available_at','')::timestamptz
      AND NULLIF(x->>'ingested_at','')::timestamptz
          IS NOT DISTINCT FROM NULLIF(y->>'ingested_at','')::timestamptz
      AND x->>'validation_status'=y->>'validation_status'
   )
 )
 OR EXISTS(
  SELECT 1 FROM jsonb_array_elements(p_calculation->'price_input_audit') y
  WHERE NOT EXISTS(
   SELECT 1 FROM jsonb_array_elements(p_source_audit) x
   WHERE x->>'series_type'='PRICE'
     AND NULLIF(x->>'source_candle_time','')::timestamptz
         IS NOT DISTINCT FROM NULLIF(y->>'source_candle_time','')::timestamptz
     AND NULLIF(x->>'canonical_open_time','')::timestamptz
         IS NOT DISTINCT FROM NULLIF(y->>'canonical_open_time','')::timestamptz
     AND NULLIF(x->>'source_available_at','')::timestamptz
         IS NOT DISTINCT FROM NULLIF(y->>'source_available_at','')::timestamptz
     AND NULLIF(x->>'ingested_at','')::timestamptz
         IS NOT DISTINCT FROM NULLIF(y->>'ingested_at','')::timestamptz
     AND x->>'validation_status'=y->>'validation_status'
  )
 ) THEN
  RAISE EXCEPTION 'PRICE audit does not exactly match supplied PRICE input receipt evidence';
 END IF;
 v_bundle:=amt_engine_v17.adapt_dual_series_session_calculation_fixture(
  p_calculation,p_symbol,p_source,p_source_audit
 );
 v_boundary:=v_bundle->'boundary_snapshot';
 IF NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(p_source_audit) x
  WHERE x->>'series_type'='PRICE'
    AND NULLIF(x->>'source_candle_time','')::timestamptz
        IS NOT DISTINCT FROM NULLIF(v_boundary->>'last_valid_completed_candle_open','')::timestamptz
    AND NULLIF(x->>'source_available_at','')::timestamptz
        IS NOT DISTINCT FROM NULLIF(v_boundary->>'source_available_at','')::timestamptz
    AND NULLIF(x->>'ingested_at','')::timestamptz
        IS NOT DISTINCT FROM NULLIF(v_boundary->>'ingested_at','')::timestamptz
 ) THEN
  RAISE EXCEPTION 'PRICE audit receipt does not match boundary snapshot selection';
 END IF;
 RETURN v_bundle||jsonb_build_object(
  'adapter_version','AMT_ENGINE_V1.7_DUAL_SERIES_ADAPTER_5',
  'price_input_audit',p_calculation->'price_input_audit'
 );
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.persist_validated_dual_series_bundle_fixture_v2(p_bundle jsonb, p_test_mode boolean DEFAULT false)
 RETURNS uuid
 LANGUAGE plpgsql
AS $function$
DECLARE v_id uuid; v_boundary jsonb; v_audit jsonb;
BEGIN
 IF jsonb_typeof(p_bundle->'price_input_audit')<>'array'
    OR jsonb_array_length(p_bundle->'price_input_audit')<>48 THEN
  RAISE EXCEPTION 'Persistence blocked: exact 48 PRICE receipt evidence required';
 END IF;
 v_audit:=p_bundle->'source_audit';
 IF jsonb_typeof(v_audit)<>'array' THEN
  RAISE EXCEPTION 'Persistence blocked: source audit array required';
 END IF;
 IF (SELECT count(*) FROM jsonb_array_elements(v_audit) x WHERE x->>'series_type'='PRICE')<>48
 OR EXISTS(
  SELECT 1 FROM jsonb_array_elements(v_audit) x
  WHERE x->>'series_type'='PRICE' AND NOT EXISTS(
   SELECT 1 FROM jsonb_array_elements(p_bundle->'price_input_audit') y
   WHERE NULLIF(y->>'source_candle_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(x->>'source_candle_time','')::timestamptz
    AND NULLIF(y->>'canonical_open_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(x->>'canonical_open_time','')::timestamptz
    AND NULLIF(y->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(x->>'source_available_at','')::timestamptz
    AND NULLIF(y->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(x->>'ingested_at','')::timestamptz
    AND y->>'validation_status'=x->>'validation_status'
  )
 )
 OR EXISTS(
  SELECT 1 FROM jsonb_array_elements(p_bundle->'price_input_audit') y
  WHERE NOT EXISTS(
   SELECT 1 FROM jsonb_array_elements(v_audit) x
   WHERE x->>'series_type'='PRICE'
    AND NULLIF(x->>'source_candle_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_candle_time','')::timestamptz
    AND NULLIF(x->>'canonical_open_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'canonical_open_time','')::timestamptz
    AND NULLIF(x->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_available_at','')::timestamptz
    AND NULLIF(x->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'ingested_at','')::timestamptz
    AND x->>'validation_status'=y->>'validation_status'
  )
 ) THEN
  RAISE EXCEPTION 'Persistence blocked: PRICE audit differs from calculation input receipts';
 END IF;
 v_boundary:=p_bundle->'boundary_snapshot';
 IF NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(v_audit) x
  WHERE x->>'series_type'='PRICE'
   AND NULLIF(x->>'source_candle_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(v_boundary->>'last_valid_completed_candle_open','')::timestamptz
   AND NULLIF(x->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(v_boundary->>'source_available_at','')::timestamptz
   AND NULLIF(x->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(v_boundary->>'ingested_at','')::timestamptz
 ) THEN
  RAISE EXCEPTION 'Persistence blocked: PRICE receipt does not match boundary snapshot';
 END IF;
 v_id:=amt_engine_v17.persist_validated_dual_series_bundle_fixture(p_bundle,p_test_mode);
 RETURN v_id;
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.persist_idempotent_dual_series_bundle_fixture_v1(p_bundle jsonb, p_test_mode boolean DEFAULT false)
 RETURNS uuid
 LANGUAGE plpgsql
AS $function$
  DECLARE
    p jsonb;
    v_date date;
    v_method text;
    v_symbol text;
    v_source text;
    v_lock_key text;
    v_fingerprint text;
    v_existing_profile_id uuid;
    v_stored_fingerprint text;
    v_ledger_profile_id uuid;
    v_profile_id uuid;
  BEGIN
    IF p_bundle IS NULL OR jsonb_typeof(p_bundle)<>'object'
       OR jsonb_typeof(p_bundle->'profile')<>'object' THEN
      RAISE EXCEPTION 'Idempotent writer requires a complete bundle with profile identity';
    END IF;

    p:=p_bundle->'profile';
    v_date:=(p->>'session_date')::date;
    v_method:=p->>'method_version';
    v_symbol:=p->>'symbol';
    v_source:=p->>'source';

    IF v_date IS NULL OR v_method IS NULL OR v_symbol IS NULL OR v_source IS NULL THEN
      RAISE EXCEPTION 'Idempotent writer requires session_date, method_version, symbol and source';
    END IF;

    -- Versioned SHA-256 over the complete JSONB bundle, including source receipt evidence.
    -- JSONB canonicalizes object-key order; array order and all values remain significant.
    v_fingerprint:=encode(
      sha256(convert_to('AMT_ENGINE_V1.7_BUNDLE_SHA256_V1|'||p_bundle::text,'UTF8')),
      'hex'
    );

    v_lock_key:=concat_ws('|',v_date::text,v_method,v_symbol,v_source);
    PERFORM pg_advisory_xact_lock(hashtextextended(v_lock_key,0));

    SELECT profile_id INTO v_existing_profile_id
    FROM amt_engine_v17.session_profiles
    WHERE session_date=v_date AND method_version=v_method
      AND symbol=v_symbol AND source=v_source
    FOR UPDATE;

    SELECT profile_id,bundle_sha256 INTO v_ledger_profile_id,v_stored_fingerprint
    FROM amt_engine_v17.session_write_fingerprints
    WHERE session_date=v_date AND method_version=v_method
      AND symbol=v_symbol AND source=v_source;

    IF v_existing_profile_id IS NOT NULL THEN
      IF v_ledger_profile_id IS NULL THEN
        RAISE EXCEPTION 'RETRY_BLOCKED_NO_FINGERPRINT: existing session predates fingerprint ledger; manual reconciliation required';
      END IF;
      IF v_ledger_profile_id IS DISTINCT FROM v_existing_profile_id THEN
        RAISE EXCEPTION 'RETRY_BLOCKED_LEDGER_PROFILE_MISMATCH: fingerprint ledger points to a different profile';
      END IF;
      IF v_stored_fingerprint IS DISTINCT FROM v_fingerprint THEN
        RAISE EXCEPTION 'CONFLICTING_REPLAY: session identity exists but complete bundle SHA-256 differs';
      END IF;
      RETURN v_existing_profile_id;
    END IF;

    IF v_ledger_profile_id IS NOT NULL THEN
      RAISE EXCEPTION 'RETRY_BLOCKED_ORPHAN_FINGERPRINT: fingerprint ledger exists without matching session profile';
    END IF;

    -- First write: existing validated atomic writer persists the full bundle.
    -- The fingerprint ledger insert is in the same transaction as that write.
    v_profile_id:=amt_engine_v17.persist_validated_dual_series_bundle_fixture_v2(p_bundle,p_test_mode);

    INSERT INTO amt_engine_v17.session_write_fingerprints(
      session_date,method_version,symbol,source,profile_id,
      fingerprint_version,bundle_sha256
    ) VALUES (
      v_date,v_method,v_symbol,v_source,v_profile_id,
      'AMT_ENGINE_V1.7_BUNDLE_SHA256_V1',v_fingerprint
    );

    RETURN v_profile_id;
  END;
  $function$


CREATE OR REPLACE FUNCTION amt_engine_v17.calculate_persisted_session_sha256_v1(p_profile_id uuid)
 RETURNS text
 LANGUAGE plpgsql
 STABLE
AS $function$
  DECLARE
    v_profile record;
    v_start timestamptz;
    v_end timestamptz;
    v_payload jsonb;
  BEGIN
    SELECT * INTO v_profile
    FROM amt_engine_v17.session_profiles
    WHERE profile_id=p_profile_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'PERSISTED_INTEGRITY_PROFILE_NOT_FOUND: %',p_profile_id;
    END IF;

    v_start:=((v_profile.session_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata');
    v_end:=v_start+interval '24 hours';

    SELECT jsonb_build_object(
      'digest_version','AMT_ENGINE_V1.7_PERSISTED_SHA256_V1',
      'session_profile',to_jsonb(v_profile)-'calculated_at',
      'tpo_rows',COALESCE((
        SELECT jsonb_agg(to_jsonb(t) ORDER BY t.row_index)
        FROM amt_engine_v17.tpo_rows t WHERE t.profile_id=p_profile_id
      ),'[]'::jsonb),
      'developing_snapshots',COALESCE((
        SELECT jsonb_agg(to_jsonb(d)-'snapshot_id'-'calculated_at' ORDER BY d.candle_open)
        FROM amt_engine_v17.developing_snapshots d WHERE d.profile_id=p_profile_id
      ),'[]'::jsonb),
      'event_episodes',COALESCE((
        SELECT jsonb_agg(to_jsonb(e)-'created_at' ORDER BY e.started_at,e.event_id)
        FROM amt_engine_v17.event_episodes e WHERE e.profile_id=p_profile_id
      ),'[]'::jsonb),
      'event_wick_observations',COALESCE((
        SELECT jsonb_agg(to_jsonb(w) ORDER BY w.event_id,w.candle_open)
        FROM amt_engine_v17.event_wick_observations w
        JOIN amt_engine_v17.event_episodes e ON e.event_id=w.event_id
        WHERE e.profile_id=p_profile_id
      ),'[]'::jsonb),
      'atr14_observations',COALESCE((
        SELECT jsonb_agg(to_jsonb(a)-'calculated_at' ORDER BY a.candle_open)
        FROM amt_engine_v17.atr14_observations a
        WHERE a.symbol=v_profile.symbol AND a.source=v_profile.source
          AND a.candle_open>=v_start AND a.candle_open<v_end
      ),'[]'::jsonb),
      'session_oi_context',COALESCE((
        SELECT to_jsonb(o)-'calculated_at'
        FROM amt_engine_v17.session_oi_context o WHERE o.profile_id=p_profile_id
      ),'null'::jsonb),
      'boundary_snapshot',COALESCE((
        SELECT to_jsonb(b)-'captured_at'
        FROM amt_engine_v17.boundary_snapshots b WHERE b.profile_id=p_profile_id
      ),'null'::jsonb),
      'source_candle_audit',COALESCE((
        SELECT jsonb_agg(to_jsonb(a)-'recorded_at'
          ORDER BY a.series_type,a.source_candle_time)
        FROM amt_engine_v17.source_candle_audit a
        WHERE a.source=v_profile.source AND a.symbol=v_profile.symbol
          AND (
            (a.source_candle_time>=v_start AND a.source_candle_time<v_end)
            OR (a.canonical_open_time>=v_start AND a.canonical_open_time<v_end)
          )
      ),'[]'::jsonb)
    ) INTO v_payload;

    RETURN encode(sha256(convert_to(
      'AMT_ENGINE_V1.7_PERSISTED_SHA256_V1|'||v_payload::text,'UTF8'
    )),'hex');
  END;
  $function$


CREATE OR REPLACE FUNCTION amt_engine_v17.persist_idempotent_dual_series_bundle_fixture_v2(p_bundle jsonb, p_test_mode boolean DEFAULT false)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'amt_engine_v17'
AS $function$
  DECLARE
    p jsonb;
    v_date date;
    v_method text;
    v_symbol text;
    v_source text;
    v_lock_key text;
    v_profile_id uuid;
    v_existing_fingerprint text;
    v_expected_fingerprint text;
    v_stored_persisted_sha text;
    v_actual_persisted_sha text;
    v_updated integer;
  BEGIN
    IF p_bundle IS NULL OR jsonb_typeof(p_bundle)<>'object'
       OR jsonb_typeof(p_bundle->'profile')<>'object' THEN
      RAISE EXCEPTION 'Integrity writer requires a complete bundle with profile identity';
    END IF;

    p:=p_bundle->'profile';
    v_date:=(p->>'session_date')::date;
    v_method:=p->>'method_version';
    v_symbol:=p->>'symbol';
    v_source:=p->>'source';

    IF v_date IS NULL OR v_method IS NULL OR v_symbol IS NULL OR v_source IS NULL THEN
      RAISE EXCEPTION 'Integrity writer requires session_date, method_version, symbol and source';
    END IF;

    v_lock_key:=concat_ws('|',v_date::text,v_method,v_symbol,v_source);
    PERFORM pg_advisory_xact_lock(hashtextextended(v_lock_key,0));

    v_expected_fingerprint:=encode(sha256(convert_to(
      'AMT_ENGINE_V1.7_BUNDLE_SHA256_V1|'||p_bundle::text,'UTF8'
    )),'hex');

    SELECT bundle_sha256,persisted_sha256
      INTO v_existing_fingerprint,v_stored_persisted_sha
    FROM amt_engine_v17.session_write_fingerprints
    WHERE session_date=v_date AND method_version=v_method
      AND symbol=v_symbol AND source=v_source;

    -- v1 takes the same transaction-level lock re-entrantly, validates the input fingerprint,
    -- and performs the atomic first write if this session identity is new.
    v_profile_id:=amt_engine_v17.persist_idempotent_dual_series_bundle_fixture_v1(
      p_bundle,p_test_mode
    );

    IF v_existing_fingerprint IS NULL THEN
      v_actual_persisted_sha:=amt_engine_v17.calculate_persisted_session_sha256_v1(v_profile_id);
      UPDATE amt_engine_v17.session_write_fingerprints
      SET persisted_sha256=v_actual_persisted_sha
      WHERE session_date=v_date AND method_version=v_method
        AND symbol=v_symbol AND source=v_source
        AND profile_id=v_profile_id
        AND bundle_sha256=v_expected_fingerprint
        AND persisted_sha256 IS NULL;
      GET DIAGNOSTICS v_updated=ROW_COUNT;
      IF v_updated<>1 THEN
        RAISE EXCEPTION 'PERSISTED_FINGERPRINT_WRITE_FAILED: expected exactly one ledger update, got %',v_updated;
      END IF;
      RETURN v_profile_id;
    END IF;

    IF v_existing_fingerprint IS DISTINCT FROM v_expected_fingerprint THEN
      RAISE EXCEPTION 'CONFLICTING_REPLAY: complete input bundle fingerprint differs';
    END IF;

    IF v_stored_persisted_sha IS NULL THEN
      RAISE EXCEPTION 'PERSISTED_INTEGRITY_UNAVAILABLE: existing fingerprint has no persisted-record digest; manual reconciliation required';
    END IF;

    v_actual_persisted_sha:=amt_engine_v17.calculate_persisted_session_sha256_v1(v_profile_id);
    IF v_actual_persisted_sha IS DISTINCT FROM v_stored_persisted_sha THEN
      RAISE EXCEPTION 'PERSISTED_INTEGRITY_MISMATCH: stored child records differ from the accepted persisted digest';
    END IF;

    RETURN v_profile_id;
  END;
  $function$


CREATE OR REPLACE FUNCTION amt_engine_v17.assert_full_bundle_source_audit(p_bundle jsonb)
 RETURNS void
 LANGUAGE plpgsql
 STABLE
 SET search_path TO 'pg_catalog', 'amt_engine_v17'
AS $function$
DECLARE
 p jsonb := p_bundle->'profile';
 b jsonb := p_bundle->'boundary_snapshot';
 a jsonb := p_bundle->'source_audit';
 pia jsonb := p_bundle->'price_input_audit';
 oia jsonb := p_bundle->'oi_input_audit';
 oi jsonb := p_bundle->'oi_context';
 v_cutoff timestamptz;
 v_date date;
 v_start timestamptz;
 v_price_count int;
 v_oi_count int;
 v_oi_input_count int;
 v_oi_available boolean;
BEGIN
 IF jsonb_typeof(p)<>'object' OR jsonb_typeof(a)<>'array'
    OR jsonb_typeof(pia)<>'array' OR jsonb_array_length(pia)<>48
    OR jsonb_typeof(oia)<>'array' THEN
   RAISE EXCEPTION 'Source audit contract: profile, source_audit, exact 48 PRICE input receipts and OI receipt array are required';
 END IF;
 v_cutoff:=NULLIF(p->>'cutoff_at','')::timestamptz;
 v_date:=(p->>'session_date')::date;
 IF v_cutoff IS NULL OR v_date IS NULL THEN
   RAISE EXCEPTION 'Source audit contract: session date and cutoff are required';
 END IF;
 v_start:=((v_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata');
 v_oi_available:=COALESCE(oi->>'context_state','UNAVAILABLE')<>'UNAVAILABLE';
 IF jsonb_array_length(a)<48 OR jsonb_array_length(a)>96 THEN
   RAISE EXCEPTION 'Source audit contract: expected 48 PRICE plus zero to 48 OI rows';
 END IF;
 SELECT count(*) INTO v_price_count FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE';
 SELECT count(*) INTO v_oi_count FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI';
 v_oi_input_count:=jsonb_array_length(oia);
 IF v_price_count<>48 OR v_oi_count<>v_oi_input_count OR v_oi_input_count>48 THEN
   RAISE EXCEPTION 'Source audit contract: PRICE/OI audit counts do not match receipt evidence';
 END IF;
 IF EXISTS (
   SELECT 1 FROM jsonb_array_elements(a) x
   WHERE x->>'source' IS DISTINCT FROM p->>'source'
     OR x->>'resolution' IS DISTINCT FROM '30m'
     OR x->>'timestamp_convention' IS DISTINCT FROM 'OPEN'
     OR NULLIF(x->>'source_candle_time','') IS NULL
     OR NULLIF(x->>'canonical_open_time','') IS NULL
     OR NULLIF(x->>'source_available_at','') IS NULL
     OR NULLIF(x->>'ingested_at','') IS NULL
     OR (x->>'source_available_at')::timestamptz>v_cutoff
     OR (x->>'ingested_at')::timestamptz>v_cutoff
     OR (x->>'canonical_open_time')::timestamptz<>(x->>'source_candle_time')::timestamptz
     OR (x->>'canonical_open_time')::timestamptz<v_start
     OR (x->>'canonical_open_time')::timestamptz>=v_start+interval '24 hours'
     OR extract(epoch FROM ((x->>'canonical_open_time')::timestamptz-v_start))::bigint%1800<>0
     OR (x->>'series_type'='PRICE' AND (x->>'symbol' IS DISTINCT FROM p->>'symbol' OR x->>'validation_status'<>'VALID'))
     OR (x->>'series_type'='OI' AND x->>'validation_status' NOT IN ('VALID','QUARANTINED','INVALID'))
     OR x->>'series_type' NOT IN ('PRICE','OI')
 ) THEN
   RAISE EXCEPTION 'Source audit contract: malformed identity, timestamp, status, or late receipt';
 END IF;
 IF (SELECT count(DISTINCT (x->>'canonical_open_time')::timestamptz)
     FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE')<>48
    OR (SELECT count(DISTINCT (x->>'canonical_open_time')::timestamptz)
     FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI')<>v_oi_count THEN
   RAISE EXCEPTION 'Source audit contract: duplicate canonical PRICE/OI intervals';
 END IF;
 IF EXISTS (
   SELECT 1 FROM jsonb_array_elements(pia) y
   WHERE y->>'validation_status'<>'VALID'
     OR NOT EXISTS (
       SELECT 1 FROM jsonb_array_elements(a) x
       WHERE x->>'series_type'='PRICE'
         AND x->>'source'=p->>'source' AND x->>'symbol'=p->>'symbol'
         AND x->>'source_candle_time'=y->>'source_candle_time'
         AND x->>'canonical_open_time'=y->>'canonical_open_time'
         AND x->>'source_available_at'=y->>'source_available_at'
         AND x->>'ingested_at'=y->>'ingested_at'
         AND x->>'validation_status'=y->>'validation_status'
     )
 ) OR EXISTS (
   SELECT 1 FROM jsonb_array_elements(a) x
   WHERE x->>'series_type'='PRICE'
     AND NOT EXISTS (
       SELECT 1 FROM jsonb_array_elements(pia) y
       WHERE y->>'source_candle_time'=x->>'source_candle_time'
         AND y->>'canonical_open_time'=x->>'canonical_open_time'
         AND y->>'source_available_at'=x->>'source_available_at'
         AND y->>'ingested_at'=x->>'ingested_at'
         AND y->>'validation_status'=x->>'validation_status'
     )
 ) THEN
   RAISE EXCEPTION 'Source audit contract: PRICE audit must exactly match all 48 calculation input receipts';
 END IF;
 IF EXISTS (
   SELECT 1 FROM jsonb_array_elements(p_bundle->'developing_snapshots') s
   WHERE s->>'source' IS DISTINCT FROM p->>'source'
      OR s->>'symbol' IS DISTINCT FROM p->>'symbol'
      OR NULLIF(s->>'candle_open','') IS NULL
      OR NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(a) x
        WHERE x->>'series_type'='PRICE'
          AND (x->>'canonical_open_time')::timestamptz=(s->>'candle_open')::timestamptz
          AND x->>'source_available_at'=s->>'source_available_at'
          AND x->>'ingested_at'=s->>'ingested_at'
      )
 ) THEN
   RAISE EXCEPTION 'Source audit contract: every developing snapshot must map one-to-one to its PRICE audit receipt';
 END IF;
 IF EXISTS (
   SELECT 1 FROM jsonb_array_elements(a) x
   WHERE x->>'series_type'='PRICE'
     AND NOT EXISTS (
       SELECT 1 FROM jsonb_array_elements(p_bundle->'developing_snapshots') s
       WHERE (s->>'candle_open')::timestamptz=(x->>'canonical_open_time')::timestamptz
         AND s->>'source_available_at'=x->>'source_available_at'
         AND s->>'ingested_at'=x->>'ingested_at'
     )
 ) THEN
   RAISE EXCEPTION 'Source audit contract: PRICE audit contains a receipt not represented by a developing snapshot';
 END IF;
 IF NOT EXISTS (
   SELECT 1 FROM jsonb_array_elements(a) x
   WHERE x->>'series_type'='PRICE'
     AND (x->>'canonical_open_time')::timestamptz=(b->>'last_valid_completed_candle_open')::timestamptz
     AND x->>'source_available_at'=b->>'source_available_at'
     AND x->>'ingested_at'=b->>'ingested_at'
 ) THEN
   RAISE EXCEPTION 'Source audit contract: boundary receipt must match the final PRICE candle receipt';
 END IF;
 IF EXISTS (
   SELECT 1 FROM jsonb_array_elements(oia) y
   WHERE NULLIF(y->>'source_candle_time','') IS NULL
      OR NULLIF(y->>'canonical_open_time','') IS NULL
      OR NULLIF(y->>'source_available_at','') IS NULL
      OR NULLIF(y->>'ingested_at','') IS NULL
      OR (y->>'source_available_at')::timestamptz>v_cutoff
      OR (y->>'ingested_at')::timestamptz>v_cutoff
      OR NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(a) x
        WHERE x->>'series_type'='OI'
          AND x->>'source'=y->>'source' AND x->>'symbol'=y->>'symbol'
          AND x->>'source_candle_time'=y->>'source_candle_time'
          AND x->>'canonical_open_time'=y->>'canonical_open_time'
          AND x->>'source_available_at'=y->>'source_available_at'
          AND x->>'ingested_at'=y->>'ingested_at'
      )
 ) OR EXISTS (
   SELECT 1 FROM jsonb_array_elements(a) x
   WHERE x->>'series_type'='OI'
     AND NOT EXISTS (
       SELECT 1 FROM jsonb_array_elements(oia) y
       WHERE x->>'source'=y->>'source' AND x->>'symbol'=y->>'symbol'
         AND x->>'source_candle_time'=y->>'source_candle_time'
         AND x->>'canonical_open_time'=y->>'canonical_open_time'
         AND x->>'source_available_at'=y->>'source_available_at'
         AND x->>'ingested_at'=y->>'ingested_at'
     )
 ) THEN
   RAISE EXCEPTION 'Source audit contract: OI source audit must exactly match supplied OI input receipts';
 END IF;
 IF v_oi_available AND (
   v_oi_count<>48 OR v_oi_input_count<>48
   OR EXISTS (SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI' AND x->>'validation_status'<>'VALID')
   OR EXISTS (
     SELECT 1 FROM jsonb_array_elements(a) x
     WHERE x->>'series_type'='PRICE'
       AND NOT EXISTS (
         SELECT 1 FROM jsonb_array_elements(a) y
         WHERE y->>'series_type'='OI'
           AND y->>'canonical_open_time'=x->>'canonical_open_time'
       )
   )
 ) THEN
   RAISE EXCEPTION 'Source audit contract: available OI context requires 48 paired VALID OI receipts';
 END IF;
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.assert_full_bundle_source_audit_v2(p_bundle jsonb)
 RETURNS void
 LANGUAGE plpgsql
 STABLE
 SET search_path TO 'pg_catalog', 'amt_engine_v17'
AS $function$
DECLARE p jsonb:=p_bundle->'profile'; b jsonb:=p_bundle->'boundary_snapshot'; a jsonb:=p_bundle->'source_audit'; pia jsonb:=p_bundle->'price_input_audit'; oia jsonb:=p_bundle->'oi_input_audit'; oi jsonb:=p_bundle->'oi_context'; v_cutoff timestamptz; v_date date; v_start timestamptz; v_price_count int; v_oi_count int; v_oi_input_count int; v_oi_available boolean;
BEGIN
 IF jsonb_typeof(p)<>'object' OR jsonb_typeof(a)<>'array' OR jsonb_typeof(pia)<>'array' OR jsonb_array_length(pia)<>48 OR jsonb_typeof(oia)<>'array' OR jsonb_typeof(oi)<>'object' THEN RAISE EXCEPTION 'Source audit contract: profile, audit arrays, 48 PRICE receipts and OI context required'; END IF;
 v_cutoff:=NULLIF(p->>'cutoff_at','')::timestamptz; v_date:=(p->>'session_date')::date;
 IF v_cutoff IS NULL OR v_date IS NULL THEN RAISE EXCEPTION 'Source audit contract: date and cutoff required'; END IF;
 v_start:=((v_date::timestamp+time '05:30') AT TIME ZONE 'Asia/Kolkata'); v_oi_available:=COALESCE(oi->>'context_state','UNAVAILABLE')<>'UNAVAILABLE';
 IF jsonb_array_length(a)<48 OR jsonb_array_length(a)>96 THEN RAISE EXCEPTION 'Source audit contract: expected 48 PRICE and zero to 48 OI rows'; END IF;
 SELECT count(*) INTO v_price_count FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE';
 SELECT count(*) INTO v_oi_count FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI'; v_oi_input_count:=jsonb_array_length(oia);
 IF v_price_count<>48 OR v_oi_count<>v_oi_input_count OR v_oi_input_count>48 THEN RAISE EXCEPTION 'Source audit contract: audit counts do not match input receipts'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'source' IS DISTINCT FROM p->>'source' OR x->>'resolution'<>'30m' OR x->>'timestamp_convention'<>'OPEN' OR NULLIF(x->>'source_candle_time','') IS NULL OR NULLIF(x->>'canonical_open_time','') IS NULL OR NULLIF(x->>'source_available_at','') IS NULL OR NULLIF(x->>'ingested_at','') IS NULL OR (x->>'source_available_at')::timestamptz>v_cutoff OR (x->>'ingested_at')::timestamptz>v_cutoff+interval '10 minutes' OR (x->>'canonical_open_time')::timestamptz<>(x->>'source_candle_time')::timestamptz OR (x->>'canonical_open_time')::timestamptz<v_start OR (x->>'canonical_open_time')::timestamptz>=v_start+interval '24 hours' OR extract(epoch FROM ((x->>'canonical_open_time')::timestamptz-v_start))::bigint%1800<>0 OR (x->>'series_type'='PRICE' AND (x->>'symbol' IS DISTINCT FROM p->>'symbol' OR x->>'validation_status'<>'VALID')) OR (x->>'series_type'='OI' AND (x->>'symbol' IS DISTINCT FROM ('OI:' || (p->>'symbol')) OR x->>'validation_status' NOT IN ('VALID','QUARANTINED','INVALID'))) OR x->>'series_type' NOT IN ('PRICE','OI')) THEN RAISE EXCEPTION 'Source audit contract: malformed identity, timestamp, status or late receipt'; END IF;
 IF (SELECT count(DISTINCT (x->>'canonical_open_time')::timestamptz) FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE')<>48 OR (SELECT count(DISTINCT (x->>'canonical_open_time')::timestamptz) FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI')<>v_oi_count THEN RAISE EXCEPTION 'Source audit contract: duplicate canonical intervals'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(pia) y WHERE y->>'validation_status'<>'VALID' OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE' AND NULLIF(x->>'source_candle_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_candle_time','')::timestamptz AND NULLIF(x->>'canonical_open_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'canonical_open_time','')::timestamptz AND NULLIF(x->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_available_at','')::timestamptz AND NULLIF(x->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'ingested_at','')::timestamptz AND x->>'validation_status'=y->>'validation_status')) OR EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE' AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(pia) y WHERE NULLIF(x->>'source_candle_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_candle_time','')::timestamptz AND NULLIF(x->>'canonical_open_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'canonical_open_time','')::timestamptz AND NULLIF(x->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_available_at','')::timestamptz AND NULLIF(x->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'ingested_at','')::timestamptz AND x->>'validation_status'=y->>'validation_status')) THEN RAISE EXCEPTION 'Source audit contract: PRICE audit does not exactly match calculation receipts'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_bundle->'developing_snapshots') s WHERE s->>'source' IS DISTINCT FROM p->>'source' OR s->>'symbol' IS DISTINCT FROM p->>'symbol' OR NULLIF(s->>'candle_open','') IS NULL OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE' AND (x->>'canonical_open_time')::timestamptz=(s->>'candle_open')::timestamptz AND NULLIF(x->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(s->>'source_available_at','')::timestamptz AND NULLIF(x->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(s->>'ingested_at','')::timestamptz)) OR EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE' AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_bundle->'developing_snapshots') s WHERE (s->>'candle_open')::timestamptz=(x->>'canonical_open_time')::timestamptz AND NULLIF(s->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(x->>'source_available_at','')::timestamptz AND NULLIF(s->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(x->>'ingested_at','')::timestamptz)) THEN RAISE EXCEPTION 'Source audit contract: PRICE receipts do not map one-to-one to developing snapshots'; END IF;
 IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE' AND (x->>'canonical_open_time')::timestamptz=(b->>'last_valid_completed_candle_open')::timestamptz AND NULLIF(x->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(b->>'source_available_at','')::timestamptz AND NULLIF(x->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(b->>'ingested_at','')::timestamptz) THEN RAISE EXCEPTION 'Source audit contract: boundary receipt does not match final PRICE candle'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(oia) y WHERE NULLIF(y->>'source_candle_time','') IS NULL OR NULLIF(y->>'canonical_open_time','') IS NULL OR NULLIF(y->>'source_available_at','') IS NULL OR NULLIF(y->>'ingested_at','') IS NULL OR (y->>'source_available_at')::timestamptz>v_cutoff OR (y->>'ingested_at')::timestamptz>v_cutoff+interval '10 minutes' OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI' AND NULLIF(x->>'source_candle_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_candle_time','')::timestamptz AND NULLIF(x->>'canonical_open_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'canonical_open_time','')::timestamptz AND NULLIF(x->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_available_at','')::timestamptz AND NULLIF(x->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'ingested_at','')::timestamptz)) OR EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI' AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(oia) y WHERE NULLIF(x->>'source_candle_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_candle_time','')::timestamptz AND NULLIF(x->>'canonical_open_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'canonical_open_time','')::timestamptz AND NULLIF(x->>'source_available_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'source_available_at','')::timestamptz AND NULLIF(x->>'ingested_at','')::timestamptz IS NOT DISTINCT FROM NULLIF(y->>'ingested_at','')::timestamptz)) THEN RAISE EXCEPTION 'Source audit contract: OI audit does not exactly match supplied OI receipts'; END IF;
 IF v_oi_available AND (v_oi_count<>48 OR v_oi_input_count<>48 OR EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='OI' AND x->>'validation_status'<>'VALID') OR EXISTS(SELECT 1 FROM jsonb_array_elements(a) x WHERE x->>'series_type'='PRICE' AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(a) y WHERE y->>'series_type'='OI' AND NULLIF(y->>'canonical_open_time','')::timestamptz IS NOT DISTINCT FROM NULLIF(x->>'canonical_open_time','')::timestamptz))) THEN RAISE EXCEPTION 'Source audit contract: available OI context requires 48 paired VALID OI receipts'; END IF;
END; $function$


CREATE OR REPLACE FUNCTION amt_engine_v17.persist_full_session_bundle(p_bundle jsonb, p_test_mode boolean)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'amt_engine_v17'
AS $function$
BEGIN
 IF p_bundle IS NULL OR jsonb_typeof(p_bundle)<>'object' THEN
  RAISE EXCEPTION 'Bundle must be an object';
 END IF;
 PERFORM amt_engine_v17.assert_full_bundle_source_audit_v3(p_bundle);
 RETURN amt_engine_v17.persist_full_session_bundle_unvalidated_internal(p_bundle,p_test_mode);
END;
$function$


CREATE OR REPLACE FUNCTION amt_engine_v17.assert_full_bundle_source_audit_v3(p_bundle jsonb)
 RETURNS void
 LANGUAGE plpgsql
 STABLE
 SET search_path TO 'pg_catalog', 'amt_engine_v17'
AS $function$
DECLARE
 v_snap_count int;
 v_snap_slots int;
 v_oi_count int;
 v_oi_slots int;
BEGIN
 PERFORM amt_engine_v17.assert_full_bundle_source_audit_v2(p_bundle);
 SELECT count(*),count(DISTINCT (x->>'candle_open')::timestamptz)
 INTO v_snap_count,v_snap_slots
 FROM jsonb_array_elements(p_bundle->'developing_snapshots') x;
 IF v_snap_count<>48 OR v_snap_slots<>48 THEN
  RAISE EXCEPTION 'Source audit contract: developing snapshots must contain exactly 48 unique candle opens';
 END IF;
 SELECT count(*),count(DISTINCT (x->>'canonical_open_time')::timestamptz)
 INTO v_oi_count,v_oi_slots
 FROM jsonb_array_elements(p_bundle->'oi_input_audit') x;
 IF v_oi_count<>v_oi_slots THEN
  RAISE EXCEPTION 'Source audit contract: duplicate OI input receipt intervals';
 END IF;
END;
$function$


INSERT INTO amt_engine_v17.method_config (method_version,session_timezone,session_start_local,session_length_bars,candle_resolution,row_size,value_area_fraction,row_anchor,source_timestamp_convention,implementation_status,methodology_fingerprint,created_at,notes) VALUES ('AMT_ENGINE_V1.7','Asia/Kolkata','05:30:00',48,'30m',50,0.70,'ZERO','OPEN','HISTORICAL_MAPPING_IN_PROGRESS',NULL,'2026-11-23T12:41:36.219Z','Frozen Version 1.7 methodology. REST candle time is configured as UTC candle-open timestamp based on user-supplied live verification on api.india.delta.exchange for BTCUSD and OI:BTCUSD at 2026-11-23 14:38 UTC, plus historical chart/raw-payload comparisons. Live-fetch guard: request end must be <= current UTC time; exclude any candle where candle_open_time + 1800 seconds > current UTC time. Future-end zero-volume flat placeholder candles must be excluded. Historical receipt-time and fixed-boundary snapshot limitations remain; this approval does not certify historical real-time availability or production readiness. | OPEN timestamp convention verified by user-provided live Delta India REST test for BTCUSD and OI:BTCUSD; ingestion must cap end at current UTC and exclude bars whose open+1800s exceeds current UTC. | OI:BTCUSD unit verified from contemporaneous Delta India API evidence supplied 2026-11-24: ticker oi=654.0390 BTC and oi_value=654.0390 with oi_value_symbol=BTC; oi_contracts=654039 and contract_value=0.001 BTC/contract; oi_value_usd=40178923.8480 USD. Live OI:BTCUSD 30m OHLC close=652.701 is on BTC-value scale. Canonical OI candle unit is BTC (base currency), not contracts or USD. Contracts=OI_BTC/contract_value; USD notional=OI_BTC*price. Historical BTCUSD/delta_india v1.7 OI context units_verified reflects this series-level unit verification; no historical values were converted. | Exact live OPEN-boundary reconciliation supplied by user on 2026-11-24: Unix 1795465800 = 2026-11-23 20:30:00 UTC labels the 20:30-21:00 candle (OI open 657.577, close 653.633); Unix 1795467600 = 2026-11-23 21:00:00 UTC labels the 21:00-21:30 candle (OI open 653.633, close 652.701). Delta ticker snapshot at 2026-11-23T20:58:52.928Z (OI 654.0390 BTC; 654039 contracts; 0.001 BTC/contract) occurred in the final ~67 seconds of the 20:30-21:00 candle. Candle close 653.633 equals next candle open 653.633. OPEN timestamp convention and BTC base-unit interpretation are settled; series-level units_verified=true.') ON CONFLICT (method_version) DO NOTHING;

-- Least-privilege application grants; login roles are provisioned separately.
REVOKE ALL ON ALL TABLES IN SCHEMA amt_engine_v17 FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA amt_engine_v17 FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA amt_engine_v17 FROM PUBLIC;
GRANT USAGE ON SCHEMA amt_engine_v17 TO amt_v17_writer_login, amt_dashboard_ro;
GRANT SELECT ON amt_engine_v17.method_config, amt_engine_v17.session_profiles TO amt_v17_writer_login;
GRANT USAGE, SELECT ON SEQUENCE amt_engine_v17.developing_snapshots_snapshot_id_seq TO amt_v17_writer_login;
GRANT SELECT ON amt_engine_v17.developing_snapshots, amt_engine_v17.event_episodes, amt_engine_v17.event_wick_observations, amt_engine_v17.session_oi_context, amt_engine_v17.session_profiles, amt_engine_v17.session_write_fingerprints, amt_engine_v17.tpo_rows TO amt_dashboard_ro;
GRANT USAGE ON SCHEMA research TO amt_dashboard_ro;
GRANT SELECT ON research.delta_candles TO amt_dashboard_ro;


GRANT EXECUTE ON FUNCTION amt_engine_v17.calculate_profile_fixture(jsonb,text) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.canonical_open_time(timestamp with time zone,text,text) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.validate_session_fixture(date,jsonb,text) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.build_developing_snapshots_fixture(date,jsonb,text,text) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.finalize_profile_fixture(date,jsonb,text,text) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.resolve_reference_fixture(date,jsonb) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.build_event_episodes_fixture(date,jsonb,numeric,numeric) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.classify_event_wick_fixture(text,timestamp with time zone,timestamp with time zone,numeric,numeric,numeric,numeric,numeric,numeric) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.calculate_atr14_fixture(jsonb) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.calculate_session_oi_context_fixture(numeric,numeric,boolean) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.build_boundary_snapshot_fixture(date,timestamp with time zone,jsonb) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.integrate_event_context_fixture(date,jsonb,numeric,numeric) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.attach_frozen_reference_fixture(jsonb,uuid,text,date,numeric,numeric,numeric) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.validate_developing_snapshot_chain_fixture(jsonb,date,uuid,text,numeric,numeric,numeric) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.build_session_calculation_fixture(date,jsonb,text,jsonb,timestamp with time zone,jsonb,numeric,numeric,boolean) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.adapt_session_calculation_to_writer_bundle_fixture(jsonb,text,text,jsonb) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.validate_live_session_inputs_fixture(date,jsonb,jsonb,timestamp with time zone) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.adapt_dual_series_session_calculation_fixture(jsonb,text,text,jsonb) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.build_audited_dual_series_calculation_fixture(date,jsonb,jsonb,jsonb,timestamp with time zone,boolean) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.validate_price_required_oi_optional_fixture(date,jsonb,jsonb,timestamp with time zone) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.build_audited_dual_series_calculation_fixture_v2(date,jsonb,jsonb,jsonb,timestamp with time zone,boolean) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.adapt_dual_series_session_calculation_fixture_v5(jsonb,text,text,jsonb) TO amt_v17_writer_login;
GRANT EXECUTE ON FUNCTION amt_engine_v17.persist_idempotent_dual_series_bundle_fixture_v2(jsonb,boolean) TO amt_v17_writer_login;

COMMIT;