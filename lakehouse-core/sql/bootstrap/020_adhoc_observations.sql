-- Ad-hoc observations: user-supplied data, structurally separated from the curated lakehouse.
--
-- Why a separate schema rather than rows inside silver.fact_observation:
--
-- 1. `materialize_fact_observation_snapshot` replaces the WHOLE Silver table. Adding one
--    ad-hoc series would mean rebuilding every curated series alongside it, and a mistake in
--    the ad-hoc mapping would take the curated data down with it.
-- 2. "Where did this number come from" is a question the jury will ask. A schema boundary
--    answers it structurally: anything in `adhoc` was uploaded during the session, anything in
--    `silver` came through a reviewed source connector.
-- 3. The demo copy can be dropped after the session without touching curated data.
--
-- 001_schemas.sql is deliberately NOT edited. Bootstrap globs *.sql in sorted order, so this
-- file is picked up after it with no code change, and re-running it is a no-op.

CREATE SCHEMA IF NOT EXISTS adhoc;

CREATE TABLE IF NOT EXISTS adhoc.fact_observation (
    -- Same columns, same meanings and same order as silver.fact_observation. A consumer that
    -- can read one can read the other; only the schema name says where the data came from.
    series_id VARCHAR NOT NULL,
    entity_id VARCHAR,
    observation_date DATE NOT NULL,
    period_start DATE,
    period_end DATE,
    value DOUBLE,
    frequency VARCHAR NOT NULL,
    unit VARCHAR,
    measure_type VARCHAR NOT NULL,
    quality_flag VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    artifact_sha256 VARCHAR NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    schema_version VARCHAR NOT NULL,
    vintage_id VARCHAR,
    run_id VARCHAR NOT NULL CHECK (length(trim(run_id)) > 0),

    -- The ad-hoc namespace is enforced by the storage layer, not only by the code that writes
    -- it. A row claiming to be curated data cannot be inserted here by any path.
    CONSTRAINT adhoc_source_is_adhoc CHECK (source_id = 'adhoc'),

    -- Mirrors the Silver quality vocabulary. `boundary_missing` is a Gold period flag and is
    -- deliberately absent: an observation-level row is either present, missing or warned.
    CONSTRAINT adhoc_quality_flag_vocabulary CHECK (
        quality_flag IN ('ok', 'missing_value', 'source_warning')
    ),

    -- A finite value or nothing. NaN and Infinity are rejected in application code as well;
    -- this is the second barrier, so a direct INSERT cannot smuggle one in.
    CONSTRAINT adhoc_value_is_finite CHECK (value IS NULL OR isfinite(value))
);

-- Uniqueness of (series_id, entity_id, observation_date, artifact_sha256) is enforced in
-- application code inside the publication transaction, not by a PRIMARY KEY. DuckDB makes
-- every PRIMARY KEY column NOT NULL, and `entity_id` is legitimately nullable in this
-- contract -- a series with no entity breakdown has no entity. Adding a sentinel column just
-- to satisfy the key would diverge from the Silver contract for no gain. This mirrors how
-- Silver already gates duplicates: in `_validate_sql_inputs`, before anything is written.
