# Operational CLI

## Why it exists

Before this branch, tests and demos assembled the production connector, parser, storage,
catalog, and ingestion services manually. This CLI provides one executable composition root
without introducing a second ingestion architecture.

## Commands

Run these commands from `lakehouse-core` with Python 3.12 and `uv`:

```bash
uv run python -m lakehouse --help
uv run python -m lakehouse bootstrap
uv run python -m lakehouse ingest \
  --source evds \
  --dataset evds_cpi \
  --start-date 2026-01-01 \
  --end-date 2026-03-31
```

The EVDS date range is required. Long ranges are automatically split into deterministic
365-day windows while short ranges remain one request; see
docs/branches/evds-windowing.md. Only the explicitly registered evds/evds_cpi dataset is
dispatched by this CLI.

For a local or public tabular artifact, publication needs an explicit layout and semantic
statement. The following is the minimum local CSV shape:

```bash
uv run python -m lakehouse ingest-file /path/to/observations.csv \
  --dataset-id adhoc_dataset \
  --allowed-local-root /path/to \
  --series-id adhoc:my_series \
  --date-column observation_date \
  --value-column value \
  --name "My series" \
  --description "Description supplied by the operator" \
  --frequency monthly \
  --unit unit_name \
  --measure-type stock
```

Additional format options are available for `csv`, `tsv`, `json`, `xlsx`, and static `html`
inputs. Use `--help` for delimiter, encoding, sheet/table selection, date, number, and
optional entity-column settings. A local path is readable only when it is inside one of the
explicit `--allowed-local-root` directories. Public HTTP(S) input is handled by the same
generic connector, with its existing URL and response limits.

## Architecture

```text
argparse CLI
    -> src/lakehouse/application.py
    -> existing connector + parser + IngestionPipeline
    -> RAW + ArtifactRepository + Bronze Parquet + RunRepository
```

Known sources use a small `(source_id, dataset_id)` registry. Adding an entry wires an
existing source connector/parser pair; the CLI does not contain provider endpoint logic.
Ad-hoc files use `GenericTabularConnector` and `GenericTabularParser`, then the existing
`register_series`, `AdhocObservationMapping`, and `publish_adhoc_observations` services.
They are published only to `adhoc.fact_observation`, never to curated Silver.

## Configuration

The ingestion commands accept:

- `--database`, defaulting to `data/lakehouse.duckdb`;
- `--data-root`, whose `raw/` and `bronze/` children hold persisted artifacts;
- `--timeout` for source or generic HTTP requests.

Generic local ingestion additionally requires explicit `--allowed-local-root` values. The
CLI does not turn the current directory, `/`, or the user's home directory into a universal
allow-list.

## Credentials

The EVDS connector reads `EVDS_API_KEY` by default. `--headers-ref` may name a different
environment variable when the existing `FetchSpec` contract requires it. The secret itself
is never a CLI argument, logged, persisted, or included in request provenance.

## Output

Successful ingestion prints stable fields from the pipeline result and durable run metadata:

```text
status: success
run_id: ...
artifact_sha256: ...
bronze_path: ...
```

Warnings are reported as a count while their detailed provenance remains in the existing
metadata tables.

## Safety

The CLI delegates local path policy, URL restrictions, redirect revalidation, response-size
limits, format ambiguity checks, formula rejection, parser configuration hashing, artifact
registration, run lifecycle, and ad-hoc provenance verification to the existing production
components. It does not write `meta.run`, RAW, Parquet, or Silver rows directly.

## Current limitation

Live CPI evidence and official base-year verification remain outside this phase. The
windowing policy protects against the existing per-request observation limit but does not
claim an EVDS rate quota.

## Tests

Dedicated offline CLI tests cover the module entry point, fresh and repeated bootstrap,
controlled EVDS ingestion and missing credentials, unknown source/dataset errors, local CSV
and XLSX publication, invalid and out-of-root paths, ambiguous input, result output, and
idempotent repeated execution. No live EVDS, BDDK, or internet request is made.
