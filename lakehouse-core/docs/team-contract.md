# Data / Lakehouse Team Contract

## Runtime standard

- Python: 3.12
- Dependency manager: `uv`
- Reproducible setup: `uv sync` using `pyproject.toml` and `uv.lock`
- Test command: `make test`
- Minimal base build: `make build`
- Offline contract smoke test: `make demo-check`

The existing `requirements.txt` remains as a compatibility/export list during this migration.
`pyproject.toml` is the authoritative dependency declaration for `uv`; it contains no secrets.

## Boundary contracts

`Connector` accesses an external source and makes exact raw bytes available in RAW. It does not
parse, clean, normalize, aggregate, or apply business semantics.

`Parser` receives a persisted `FetchedAsset`, performs no network access, and returns a
provenance-preserving `ParsedBatch`. It does not implement Silver or Gold semantics.

The shared signatures are:

```python
class BaseConnector(ABC):
    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]: ...

class BaseParser(Protocol):
    def parse(self, asset: FetchedAsset) -> ParsedBatch: ...
```

`FetchSpec` contains `source_id`, `dataset_id`, `locator`, optional date bounds, `parameters`,
`headers_ref`, `timeout`, and UTC `requested_at`. Header values and secrets are never stored in
the model; `headers_ref` is a reference only.

`FetchedAsset` contains `source_id`, `dataset_id`, `locator`, `media_type`, `byte_size`, UTC
`fetched_at`, `artifact_sha256`, `raw_path`, optional successful `http_status`, and non-secret
metadata.

`ParsedBatch` contains `source_id`, `dataset_id`, `artifact_sha256`, `schema_version`, a pandas
`DataFrame`, and parser warnings.

## Naming and storage

- `source_id`: stable lowercase `snake_case`, such as `evds`, `bddk_monthly`, or `adhoc`.
- `dataset_id`: stable lowercase `snake_case` logical dataset name.
- `series_id`: stable source-namespaced identifier. New code must produce the canonical
  `source:<native_identifier>` form, such as `evds:TP.KTF12`. The legacy dotted form remains
  readable only for existing regression compatibility; new connectors and parsers must not
  produce dotted identifiers.
- `run_id`: UUID string.
- `vintage_id`: string identifying the source/dataset ingestion vintage.
- RAW path: `data/raw/{source_id}/{fetch_date}/{artifact_sha256}.{extension}`.
- RAW bytes are immutable, content-addressed, and written atomically. Duplicate bytes reuse the
  existing physical artifact.

Observation dates use `datetime.date`. Operational timestamps are timezone-aware UTC datetimes.
`fetched_at` is the download time; `observation_date` is the canonical date of an observation.
They are different concepts. Canonical numeric values are `float | None`; percentages such as
`%12.5` are stored as `12.5`, not `0.125`. Bronze retains source-faithful raw values.
Non-finite numeric values such as NaN and positive or negative Infinity are invalid Silver inputs
and fail validation; they are never converted to `NULL` or `missing_value`.

Silver is the canonical, typed, validated and source-independent observation layer. Trusted
DuckDB materialization is a complete snapshot replacement through
`materialize_fact_observation_snapshot(...)`: source-adapter outputs must be combined into the
intended snapshot before materialization. It is not source-specific Bronze structure, Gold
aggregation, cross-frequency alignment, revision/current-selection logic or agent behaviour.
Incremental, append, merge and current-vintage behavior are deferred. Silver semantics come
from `meta.series`; source-specific fields remain in Bronze.

## Errors and fixtures

The shared error codes are `SOURCE_UNAVAILABLE`, `FETCH_TIMEOUT`, `HTTP_ERROR`,
`UNSUPPORTED_FORMAT`, `PARSE_FAILED`, `SCHEMA_MISMATCH`, `EMPTY_DATASET`,
`OBSERVATION_COUNT_MISMATCH`, and `QUALITY_FAILED`. Every error payload has `error_code`,
`message`, `source_id`, `dataset_id`, and `retryable`.

Fixtures live under `tests/fixtures/raw/`, contain no secrets, and must run without internet.

## Definition of Done

A task is complete only when the code runs, relevant tests exist, `make test` passes, no secret is
introduced, provenance is preserved, contract changes are documented, and the 18-test Phase 0
regression behavior remains green.

## Change control

The following are shared contract files. No unilateral breaking change is allowed; changes must
be documented and reviewed before dependent tracks consume them:

- `pyproject.toml`
- `uv.lock`
- `src/lakehouse/contracts/*`
- `src/lakehouse/errors.py`
- `contracts/*`
- `schemas/*`

Use focused branches and pull requests. Keep source-access and infrastructure changes separate
until both tracks are ready for the first vertical slice.
