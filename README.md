# AgentSmithler Workspace

AgentSmithler Workspace is the shared repository for the KKB Agentic Data Analytics
project. The current implemented component is `lakehouse-core/`, a local-first,
generic Python data lakehouse foundation.

## Current state

`lakehouse-core/` provides source access, immutable RAW artifacts, Bronze Parquet,
semantic catalog loading, and a validated source-independent Silver V1 observation
layer. Gold analytical models and Agent tools are planned work.

## Repository map

- `lakehouse-core/`: the analytical lakehouse component.
- `lakehouse-core/src/lakehouse/`: connectors, parsers, storage, catalog, Silver, and shared contracts.
- `lakehouse-core/models/`: SQL models, including the current Silver model.
- `lakehouse-core/schemas/`: formal data contracts.
- `lakehouse-core/docs/`: team, source, catalog, and architecture documentation.
- `lakehouse-core/tests/`: unit, contract, security, infrastructure, and offline integration tests.

For architecture, supported series, setup, and usage, see the
[`lakehouse-core README`](lakehouse-core/README.md).
