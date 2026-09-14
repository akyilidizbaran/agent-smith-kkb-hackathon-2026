-- Ingestion observability: run tracking and durable parser warnings.
--
-- Parsers already produce meaningful data-quality warnings (silent truncation, period-count
-- mismatches, display defaults that must not be read as measured zeros, derived series ids).
-- Until this migration those warnings lived only in the in-memory ParsedBatch and were
-- dropped once IngestionPipeline returned. This migration gives them a home.
--
-- meta.run already exists (002_meta_tables.sql) and is intentionally NOT redefined here.
-- It gains two additive, nullable columns so a run can say which source and dataset it
-- touched; without them a run row cannot be attributed to anything. ADD COLUMN IF NOT
-- EXISTS keeps repeated bootstraps a no-op.
--
-- meta.run.status vocabulary written by the ingestion layer:
--   running  - the run has started and has not been closed yet
--   success  - the run completed and produced no parser warnings
--   warning  - the run completed and produced at least one parser warning
--   failed   - the run raised; ended_at and error are populated and the original
--              exception is re-raised to the caller
--
-- meta.run.rows_in stays NULL for source-to-Bronze ingestion on purpose: a connector
-- returns bytes, not rows, so there is no honest row count on the way in. Inventing one
-- would be worse than leaving it unknown.
-- meta.run.rows_out is the number of Bronze rows this run actually persisted, including
-- partial progress made before a failure.

ALTER TABLE meta.run ADD COLUMN IF NOT EXISTS source_id VARCHAR;
ALTER TABLE meta.run ADD COLUMN IF NOT EXISTS dataset_id VARCHAR;

CREATE TABLE IF NOT EXISTS meta.ingest_warning (
    run_id VARCHAR NOT NULL,

    -- Deterministic ordinal of the warning inside its run, starting at 1. Ordering is
    -- (asset order returned by the connector, warning order inside that ParsedBatch), so
    -- replaying the same run over the same bytes reproduces the same sequence numbers.
    warning_seq INTEGER NOT NULL,

    source_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,

    -- NULL when the warning could not be attributed to a single RAW artifact. Every
    -- warning written today comes from a parsed artifact and carries its digest.
    artifact_sha256 VARCHAR,

    -- Stored verbatim. Parser warnings are first-party text produced by this repository's
    -- own parsers; they carry no credentials and no response bodies, so they are never
    -- redacted or truncated. Losing warning detail would defeat the point of the table.
    message VARCHAR NOT NULL,

    created_at TIMESTAMPTZ NOT NULL,

    PRIMARY KEY (run_id, warning_seq),

    -- These two CHECK constraints were verified against the DuckDB version pinned in
    -- uv.lock: both reject bad rows and neither interferes with the ALTER above or with the
    -- UPDATE that closes a run.
    CONSTRAINT ingest_warning_seq_positive CHECK (warning_seq > 0),
    CONSTRAINT ingest_warning_message_not_blank CHECK (length(trim(message)) > 0)
);

-- Why there is NO `FOREIGN KEY (run_id) REFERENCES meta.run(run_id)` here
-- ----------------------------------------------------------------------
-- It was written, measured, and removed. On DuckDB 1.5.5 a foreign key makes the parent row
-- un-updatable in exactly the case this table creates:
--
--   INSERT INTO meta.ingest_warning ... (child now references the run)
--   UPDATE meta.run SET status = 'success' ... RETURNING run_id
--     -> Constraint Error: Violates foreign key constraint because key "run_id: ..." is
--        still referenced by a foreign key in a different table
--
-- The failure is specific to `UPDATE ... RETURNING`; the same UPDATE without RETURNING is
-- allowed. Measured across in-memory and file-backed databases, for single-column and
-- multi-column updates: RETURNING is refused in all four combinations, plain UPDATE is
-- accepted in all four, and both are accepted when no warning row exists yet.
--
-- The practical consequence was severe and silent: a run that produced any warning could
-- never be closed, so it stayed `running` forever -- and because failure recording is
-- deliberately best-effort, failed runs were silently left open too. That is worse than the
-- problem the constraint was meant to prevent.
--
-- Dropping RETURNING instead would trade an atomic conditional close for a blind UPDATE, and
-- would leave the close path depending on a DuckDB inconsistency that a future version could
-- resolve in either direction. So the referential rule lives in RunRepository, which refuses
-- to record a warning unless its run exists, is still `running`, and matches the warning's
-- source and dataset -- and additionally refuses a warning whose artifact digest is not
-- registered in meta.artifact, which a foreign key on run_id would not have covered at all.
-- See tests/ingestion/test_run_repository.py for the enforcement tests.
