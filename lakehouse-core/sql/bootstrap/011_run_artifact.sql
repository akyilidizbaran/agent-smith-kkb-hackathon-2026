-- Run-artifact provenance: which RAW artifacts each ingestion run actually fetched.
--
-- meta.run (002, 010) records that a run happened and which source/dataset it covered.
-- meta.artifact (002) records that an artifact exists. Neither says "run R fetched artifact
-- A". Without that junction, publication could only check that a run *could* have produced
-- an artifact, so the run_id of any other successful run over the same source/dataset was
-- accepted, and the in-memory asset's fetched_at was published without a durable value to
-- compare it against. This table is that missing junction.
--
-- One row per (run_id, artifact_sha256). It is written by IngestionPipeline immediately after
-- ArtifactRepository.register and BEFORE parsing, so a parse or Bronze-write failure later in
-- the same run leaves the fact "this run downloaded these bytes" behind; the run itself still
-- closes as `failed`. The row is never updated: a re-link with identical facts is a no-op and
-- a re-link with different facts is refused in RunRepository.link_artifact.
--
-- fetched_at is the connector's own timestamp for THIS run's fetch. It can legitimately
-- differ from meta.artifact.fetched_at, which is the first fetch of the same bytes; both
-- are real events. Publication reads fetched_at from here, never from the in-memory result.
--
-- parser_config_sha256 is the generic connector's canonical parser-choice digest. Curated
-- sources have no such configuration and store NULL; the Bronze identity is then matched on
-- NULL as well.
--
-- Additive: CREATE TABLE IF NOT EXISTS, no column is added to any existing table, and runs
-- recorded before this migration simply have no rows here (and so cannot be published
-- ad-hoc without re-ingestion). No FOREIGN KEY, for the reason documented in
-- 010_ingestion_observability.sql: on the pinned DuckDB a child row makes the parent's
-- `UPDATE ... RETURNING` fail, and closing a run is exactly such an update. The referential
-- rules live in RunRepository.link_artifact instead.

CREATE TABLE IF NOT EXISTS meta.run_artifact (
    run_id VARCHAR NOT NULL,
    artifact_sha256 VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    parser_config_sha256 VARCHAR,

    PRIMARY KEY (run_id, artifact_sha256),

    -- These CHECK constraints were verified against the DuckDB version pinned in uv.lock
    -- (regexp_full_match is usable inside CHECK there).
    CONSTRAINT run_artifact_run_id_not_blank CHECK (length(trim(run_id)) > 0),
    CONSTRAINT run_artifact_sha256_shape CHECK (
        regexp_full_match(artifact_sha256, '[0-9a-f]{64}')
    ),
    CONSTRAINT run_artifact_source_not_blank CHECK (length(trim(source_id)) > 0),
    CONSTRAINT run_artifact_dataset_not_blank CHECK (length(trim(dataset_id)) > 0),
    CONSTRAINT run_artifact_parser_sha256_shape CHECK (
        parser_config_sha256 IS NULL OR regexp_full_match(parser_config_sha256, '[0-9a-f]{64}')
    )
);
