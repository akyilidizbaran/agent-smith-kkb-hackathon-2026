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
FROM semantic;
