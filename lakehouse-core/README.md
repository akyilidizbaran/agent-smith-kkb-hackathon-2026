# Lakehouse Core

## Purpose

`lakehouse-core` is a local-first, generic Python data lakehouse component. It
collects source data without coupling the core model to a particular provider,
keeps the original evidence, and produces validated analytical observations.

## Architecture

```text
BDDK / EVDS / future sources
            |
        Connector
            |
           RAW
            |
         Parser
            |
      Bronze Parquet
            |
 IngestionResult context
 (run_id + warnings)
            |
  Source-specific Silver Adapter
            |
   Generic Silver Staging
            |
    meta.series enrichment
            |
   silver.fact_observation
            |
 Silver Parquet + trusted DuckDB
            |
 Gold analytical functions
            |
   Agent tools (planned)
```

Connectors and parsers are implemented for the current source fixtures. Silver V1
is implemented and tested for four captured real series. A fifth TÜFE mapping is
contract-tested with an explicitly synthetic EVDS envelope while its official
`TP.FG.J0` capture and base-year evidence remain pending. Gold P0 functions are
implemented; Agent tools remain planned.

## Current Delivery Status

The Silver V1 acceptance gate is closed. The current Agent/Data P0 handoff adds:

- `evds:TP.FG.J0` CPI catalog and Silver mapping support;
- transactional `first_obs` / `last_obs` refresh from the complete Silver snapshot;
- a file-backed untrusted connection and guarded `QueryExecutor` proof that reads
  `silver.fact_observation` without granting write access;
- regression coverage for CPI mapping, coverage refresh, query safety, and
  Parquet/Arrow null preservation.

The Agent/Data P0 checkpoint has **576 passing tests**, including **37/37 Silver
acceptance tests**. See
[`docs/branches/agent-data-p0.md`](docs/branches/agent-data-p0.md) for the exact scope,
evidence boundary, and remaining work.

`evds:TP.FG.J0` is code-ready but its checked-in test envelope is explicitly
synthetic. Until a keyed EVDS capture and official base-year evidence are added, its
catalog confidence remains `derived`; the codebase must not present it as externally
verified.

### Gold P0

Gold is implemented as read-only functions rather than prebuilt source-specific tables:

- `align_frequency(...)` applies the catalog's stock/flow/rate/index rule to monthly or
  quarterly periods;
- `decompose_cumulative(...)` safely decomposes supported monthly/quarterly cumulative
  series;
- `join_on_period(...)` outer-joins independently aligned series without hiding coverage
  gaps.

The functions read `measure_type`, `default_agg`, frequency, status, and semantic
confidence from `meta.series`; callers cannot supply their own arithmetic. Unsupported,
inactive, under-evidenced, ambiguous-vintage, or unsafe transformations fail closed with a
machine-readable reason. Derived rows retain contributor dates and artifact/vintage/run
lineage. No interpolation, implicit carry-forward, silent revision selection, or database
write is performed.

The current branch checkpoint has **677 passing tests**: the unchanged 576-test baseline
plus **101 Gold tests**. The API and limitations are documented in
[`docs/gold-contract.md`](docs/gold-contract.md), with implementation evidence in
[`docs/branches/gold-functions-v1.md`](docs/branches/gold-functions-v1.md).

## Data Layers

- **RAW:** immutable original fetched bytes, identified by SHA-256.
- **Bronze:** parsed and source-faithful data stored as Parquet.
- **Silver:** canonical, validated, source-independent observations.
- **Gold:** read-only, catalog-driven frequency alignment, cumulative decomposition, and
  period joins; no persisted Gold tables yet.

## Silver V1

The canonical table is `silver.fact_observation`. Its formal contract is
[`schemas/fact_observation.yml`](schemas/fact_observation.yml). Important fields
include `series_id`, `observation_date`, `value`, `frequency`, `unit`,
`measure_type`, `quality_flag`, and artifact/source provenance.

The current tested mappings are:

| Series | Frequency | Unit | Measure |
|---|---|---|---|
| `bddk_monthly:1534_Toplam` | monthly | `TRY_mn` | stock |
| `bddk_weekly:5690_3` | weekly | `TRY_mn` | stock |
| `evds:TP.KTF12` | weekly | `pct` | rate |
| `evds:TP.KFE.TR` | monthly | `index` | index |
| `evds:TP.FG.J0` | monthly | `index` | index *(external evidence pending)* |

Frequency, unit, and measure semantics come from `meta.series`; they are not
hard-coded into the generic Silver foundation.

## Important Semantics

- A true source `NULL` remains `NULL` and receives `quality_flag = missing_value`.
- Invalid dates, invalid numerics, NaN, and positive or negative Infinity fail validation.
- Source-specific Bronze fields do not enter `silver.fact_observation`.
- BDDK Weekly observation dates are preserved exactly; `week_anchor` does not rewrite them.
- EVDS KFE remains an index; no base year or rebasing is assumed.
- Same-artifact duplicate observations fail; the same observation from different artifacts is preserved.
- Every immutable artifact gets a deterministic `artifact:<sha256>` vintage; current revision selection is deferred.
- BDDK source units are reconciled before publication and source populations receive stable `entity_id` values.
- Parser warnings mark derived rows as `source_warning` and remain queryable through the row's `run_id`.
- Silver Parquet carries its own `fact_observation.v1` / `silver` representation identity.

Silver materialization uses:

```python
staging, bronze_identity = stage_ingestion_result(result, adapter=source_adapter)
silver = materialize_fact_observation_snapshot(connection, staging)
silver_path = silver_storage.write_frame(
    silver,
    identity=silver_identity_for(bronze_identity),
)
```

The function expects the complete intended Silver staging snapshot and replaces
the complete `silver.fact_observation` table. It is not append, upsert, merge, or
incremental revision handling. Outputs from multiple adapters must be combined
before calling it.

## Quick Start

Python 3.12 and `uv` are required.

```bash
uv sync --frozen
uv lock --check
make test
make build
make demo-check
```

## Testing

The automated end-to-end tests use fixture/fake transport and the production path:

```text
fixture/fake transport -> connector -> RAW -> parser -> Bronze
-> Silver adapter -> Silver foundation -> Parquet -> DuckDB
```

The test suite does not require live BDDK or EVDS network access.

## Repository Map

- `src/lakehouse/connectors/`: external source access.
- `src/lakehouse/parsers/`: persisted RAW to source-faithful Bronze parsing.
- `src/lakehouse/storage/`: RAW and Parquet persistence.
- `src/lakehouse/catalog/`: `meta.series` semantic catalog loading.
- `src/lakehouse/silver/`: generic Silver foundation and source adapters.
- `src/lakehouse/gold/`: fail-closed analytical transformations over Silver.
- `models/`: SQL models.
- `schemas/`: formal data contracts.
- `catalog/series/`: reviewed series metadata.
- `tests/`: contract, unit, security, infrastructure, and offline integration tests.
- `docs/`: detailed team and source documentation.

## Deferred Work

The following are intentionally planned for later work:

- Generic connector/parser and programmatic draft-series registration.
- An isolated ad-hoc observation surface and executable ingestion CLI.
- EVDS request windowing for responses that exceed source observation limits.
- FinTürk Silver mapping and entity/geography modeling.
- Broader catalog coverage for retrieval and genericity evaluation.
- Safe decomposition-to-alignment composition and persisted Gold publication.
- Gold current-revision selection policy.
- Gold-only `QueryExecutor` restrictions.
- Agent tools and LangGraph orchestration.
