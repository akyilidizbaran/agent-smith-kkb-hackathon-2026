-- Generic Silver V1 projection.
-- The only input relation is the source-independent `silver_staging` contract.

WITH typed AS (
    SELECT
        series_id,
        entity_id,
        CAST(observation_date AS DATE) AS observation_date,
        CAST(period_start AS DATE) AS period_start,
        CAST(period_end AS DATE) AS period_end,
        TRY_CAST(value_raw AS DOUBLE) AS value,
        value_raw,
        source_id,
        dataset_id,
        artifact_sha256,
        fetched_at,
        schema_version,
        vintage_id,
        run_id,
        source_warning
    FROM silver_staging
),
semantic AS (
    SELECT
        t.*,
        m.frequency,
        m.unit,
        m.measure_type
    FROM typed AS t
    INNER JOIN meta.series AS m
        ON m.series_id = t.series_id
)
SELECT
    series_id,
    entity_id,
    observation_date,
    period_start,
    period_end,
    value,
    frequency,
    unit,
    measure_type,
    CASE
        WHEN value_raw IS NULL THEN 'missing_value'
        WHEN source_warning IS NOT NULL THEN 'source_warning'
        ELSE 'ok'
    END AS quality_flag,
    source_id,
    dataset_id,
    artifact_sha256,
    fetched_at,
    schema_version,
    vintage_id,
    run_id
FROM semantic
-- A snapshot's row order is part of its identity here: acceptance tests compare Silver rows
-- positionally against their Bronze source, and a Silver Parquet representation is written
-- from this projection. Without an explicit order the join above decides, and that order
-- changed silently when meta.series grew from 5 rows to 1620 — five acceptance tests that had
-- been passing started failing on data that had not changed. Ordering is stated rather than
-- inherited from the optimiser.
ORDER BY
    series_id,
    entity_id NULLS FIRST,
    observation_date,
    period_start NULLS FIRST,
    artifact_sha256;
