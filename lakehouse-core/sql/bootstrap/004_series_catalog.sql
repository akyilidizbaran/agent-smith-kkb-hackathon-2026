-- Semantic series catalog.
--
-- This table is deliberately separate from meta.artifact / meta.run / meta.dataset_version.
-- Those are *operational* metadata, derived automatically from what was ingested. meta.series
-- is *semantic* metadata: it is written by hand, reviewed by a human, versioned in Git as YAML
-- under catalog/series/, and loaded from there. Nothing infers rows into this table.
--
-- first_obs and last_obs are the one exception: they describe observed coverage and are
-- computed operationally later. The catalog loader never writes or clears them.

CREATE TABLE IF NOT EXISTS meta.series (
    series_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    native_code VARCHAR NOT NULL,
    dataset_id VARCHAR,
    name_tr VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    aliases VARCHAR[],
    tags VARCHAR[],
    frequency VARCHAR NOT NULL,
    week_anchor VARCHAR,
    unit VARCHAR,
    measure_type VARCHAR NOT NULL,
    default_agg VARCHAR,
    cumulative_reset VARCHAR,
    semantic_confidence VARCHAR NOT NULL,
    semantic_source VARCHAR NOT NULL,
    first_obs DATE,
    last_obs DATE,
    metadata_url VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'active',
    -- Hash of the semantic payload as written in YAML. Lets the loader tell "same content"
    -- from "changed content" so an unchanged catalog does not churn updated_at.
    catalog_content_sha256 VARCHAR NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,

    CONSTRAINT series_measure_type_vocabulary CHECK (measure_type IN (
        'stock', 'flow_periodic', 'flow_ytd', 'flow_cumulative',
        'rate', 'ratio', 'index', 'count', 'unknown'
    )),
    CONSTRAINT series_semantic_confidence_vocabulary CHECK (semantic_confidence IN (
        'verified', 'derived', 'unknown'
    )),
    CONSTRAINT series_status_vocabulary CHECK (status IN (
        'active', 'deprecated', 'draft'
    )),
    -- A series with no dataset_id has nothing to fetch it, so it cannot be 'active'.
    -- Keeping dataset_id nullable lets a series be catalogued before its connector exists,
    -- but only as a draft, so the agent layer never sees an active-but-unfetchable series.
    CONSTRAINT series_draft_requires_no_dataset CHECK (
        dataset_id IS NOT NULL OR status = 'draft'
    )
);
