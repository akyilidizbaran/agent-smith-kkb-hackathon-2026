-- Gold build ledger: which reviewed metric was materialized from which Silver snapshot.
--
-- Gold is a set of functions (docs/gold-contract.md). A table under the `gold` schema is a
-- named, reviewed call of one of them (catalog/gold/*.yml) cached from the Silver snapshot
-- current at build time. This table is the only place that says which metric a `gold.*`
-- table implements, when it was built, and -- just as important -- which metrics the
-- functions REFUSED to build and why. A refused metric has no table; its row here is the
-- evidence that nobody silently skipped it.
--
-- One row per (build_id, metric_id). Rows are never updated except to clear is_current when
-- a newer build for the same metric lands, so the history of every build is kept.
--
-- silver_fingerprint is a digest over every Silver observation at build time. A reader that
-- compares it against the live digest knows whether the table is behind a later `silver`
-- rebuild, without trusting timestamps.
CREATE TABLE IF NOT EXISTS meta.gold_build (
    build_id VARCHAR NOT NULL,
    metric_id VARCHAR NOT NULL,
    function VARCHAR NOT NULL,
    series_ids VARCHAR[] NOT NULL,
    target_frequency VARCHAR,
    name_tr VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    aliases VARCHAR[],
    tags VARCHAR[],
    allow_unverified_semantics BOOLEAN NOT NULL,
    status VARCHAR NOT NULL,
    row_count BIGINT,
    refusal_reason VARCHAR,
    refusal_message VARCHAR,
    catalog_content_sha256 VARCHAR NOT NULL,
    silver_fingerprint VARCHAR NOT NULL,
    silver_row_count BIGINT NOT NULL,
    is_current BOOLEAN NOT NULL,
    built_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (build_id, metric_id),
    CONSTRAINT gold_build_status_vocabulary CHECK (status IN ('built', 'refused')),
    CONSTRAINT gold_build_function_vocabulary CHECK (function IN (
        'align_frequency', 'decompose_cumulative', 'join_on_period'
    ))
);
