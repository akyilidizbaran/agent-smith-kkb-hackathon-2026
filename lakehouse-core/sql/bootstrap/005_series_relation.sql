-- Canonical relationships between semantic series.
--
-- The source catalog remains the authority for one series' meaning.  This table records
-- stable parent/child, dimension and variant links so consumers do not infer them from a
-- user question.  It is intentionally separate from meta.series: existing catalog rows and
-- ingestion contracts remain backward compatible.

CREATE TABLE IF NOT EXISTS meta.series_relation (
    series_id VARCHAR PRIMARY KEY,
    concept_id VARCHAR NOT NULL,
    parent_series_id VARCHAR,
    relation_type VARCHAR NOT NULL,
    dimension_path VARCHAR[],
    additivity VARCHAR NOT NULL DEFAULT 'unknown',
    relation_confidence VARCHAR NOT NULL DEFAULT 'derived',
    relation_source VARCHAR NOT NULL DEFAULT 'source_adapter',
    relation_content_sha256 VARCHAR NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,

    CONSTRAINT series_relation_type_vocabulary CHECK (relation_type IN (
        'standalone', 'parent_total', 'child_breakdown', 'dimension_member', 'variant', 'derived'
    )),
    CONSTRAINT series_relation_additivity_vocabulary CHECK (
        additivity IN ('additive', 'non_additive', 'unknown')
    ),
    CONSTRAINT series_relation_confidence_vocabulary CHECK (
        relation_confidence IN ('verified', 'derived', 'unknown')
    )
);
