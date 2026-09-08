# Test Fixtures

Fixtures are small, local, secret-free files that represent persisted RAW artifacts.
They must be sufficient for parser and contract tests without network access.

`raw/sample.csv` is a synthetic CSV fixture with two date/value rows. It is intentionally
source-agnostic; no BDDK or EVDS endpoint is encoded in the fixture.

Expected parser behavior:

- Read the file from its local path.
- Return a `pandas.DataFrame` inside `ParsedBatch`.
- Preserve `source_id`, `dataset_id`, and `artifact_sha256` from the `FetchedAsset`.
- Apply no cleaning, normalization, or Silver/Gold semantics.

## Source-specific fixtures

`raw/evds/` holds trimmed excerpts of real EVDS3 responses. `raw/bddk_monthly/` holds trimmed
excerpts of real BDDK monthly bulletin responses. Each directory has its own README
documenting the capture method, the response envelope, and the source anomalies encoded.
