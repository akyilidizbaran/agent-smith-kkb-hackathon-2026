CREATE TABLE IF NOT EXISTS meta.source (
    source_id VARCHAR PRIMARY KEY,
    description VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS meta.artifact (
    artifact_sha256 VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    locator VARCHAR NOT NULL,
    media_type VARCHAR NOT NULL,
    byte_size BIGINT NOT NULL,
    http_status INTEGER,
    fetched_at TIMESTAMPTZ NOT NULL,
    raw_path VARCHAR NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS meta.run (
    run_id VARCHAR PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    rows_in BIGINT,
    rows_out BIGINT,
    error VARCHAR
);

CREATE TABLE IF NOT EXISTS meta.dataset_version (
    dataset_id VARCHAR NOT NULL,
    vintage_id VARCHAR NOT NULL,
    artifact_sha256 VARCHAR NOT NULL,
    row_count BIGINT NOT NULL,
    schema_hash VARCHAR NOT NULL,
    content_hash VARCHAR NOT NULL,
    is_current BOOLEAN NOT NULL,
    PRIMARY KEY (dataset_id, vintage_id, artifact_sha256)
);
