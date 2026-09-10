# AgentSmithler Workspace

AgentSmithler Workspace is the shared repository for the KKB Agentic Data Analytics
project. The current implemented component is `lakehouse-core/`, a local-first,
generic Python data lakehouse foundation.

## Current state

`lakehouse-core/` provides source access, immutable RAW artifacts, Bronze Parquet,
semantic catalog loading, ingestion observability, and an acceptance-tested,
source-independent Silver V1 observation layer. The first Agent/Data P0 handoff is
also implemented: CPI catalog/Silver support, automatic series coverage, and safe
read-only Agent queries over Silver. Gold analytical functions are the next delivery.

## Repository map

- `lakehouse-core/`: the analytical lakehouse component.
- `lakehouse-core/src/lakehouse/`: connectors, parsers, storage, catalog, Silver, and shared contracts.
- `lakehouse-core/models/`: SQL models, including the current Silver model.
- `lakehouse-core/schemas/`: formal data contracts.
- `lakehouse-core/docs/`: team, source, catalog, and architecture documentation.
- `lakehouse-core/tests/`: unit, contract, security, infrastructure, and offline integration tests.

For architecture, supported series, setup, and usage, see the
[`lakehouse-core README`](lakehouse-core/README.md).

## Current delivery checkpoints

- Silver V1 acceptance and data-trust closure:
  [`silver-v1-acceptance-pack.md`](lakehouse-core/docs/acceptance/silver-v1-acceptance-pack.md)
- Agent/Data P0 handoff:
  [`agent-data-p0.md`](lakehouse-core/docs/branches/agent-data-p0.md)
- Independent architecture and quality audit:
  [`data-lakehouse-bagimsiz-denetim-raporu-2026-09-10.md`](lakehouse-core/docs/audits/data-lakehouse-bagimsiz-denetim-raporu-2026-09-10.md)

The remaining Data/Lakehouse scope is delivered in focused branches: Gold
frequency/cumulative/join functions first, then generic and ad-hoc ingestion,
operational CLI/windowing, and finally catalog/FinTürk expansion.
