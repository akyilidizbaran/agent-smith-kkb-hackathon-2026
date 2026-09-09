CREATE TABLE IF NOT EXISTS meta.artifact_request (
    artifact_sha256 VARCHAR NOT NULL,
    request_fingerprint VARCHAR NOT NULL,
    locator VARCHAR NOT NULL,
    request_metadata_json VARCHAR NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (artifact_sha256, request_fingerprint)
);
