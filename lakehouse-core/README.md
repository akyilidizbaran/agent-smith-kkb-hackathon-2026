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
       Gold (planned)
            |
   Agent tools (planned)
```

Connectors and parsers are implemented for the current source fixtures. Silver V1
is implemented and tested for four real series. Gold and Agent layers remain
planned; they are not required to run the current data path.

## Data Layers

- **RAW:** immutable original fetched bytes, identified by SHA-256.
- **Bronze:** parsed and source-faithful data stored as Parquet.
- **Silver:** canonical, validated, source-independent observations.
- **Gold:** planned analysis-ready joins, frequency alignment, aggregations, and derived views.

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
- `models/`: SQL models.
- `schemas/`: formal data contracts.
- `catalog/series/`: reviewed series metadata.
- `tests/`: contract, unit, security, infrastructure, and offline integration tests.
- `docs/`: detailed team and source documentation.

## Deferred Work

The following are intentionally planned for later work:

- Gold analytical models and cross-frequency joins.
- Weekly-to-monthly aggregation policy and other derived metrics.
- FinTürk Silver mapping and entity/geography modeling.
- Gold current-revision selection policy.
- Gold-only `QueryExecutor` restrictions.
- Agent tools and LangGraph orchestration.
