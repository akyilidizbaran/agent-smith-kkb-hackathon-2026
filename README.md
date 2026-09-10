# AgentSmithler Workspace

AgentSmithler Workspace is the shared repository for the KKB Agentic Data Analytics
project. The current implemented component is `lakehouse-core/`, a local-first,
generic Python data lakehouse foundation.

## Current state

`lakehouse-core/` provides source access, immutable RAW artifacts, Bronze Parquet,
semantic catalog loading, ingestion observability, and an acceptance-tested,
source-independent Silver V1 observation layer. The first Agent/Data P0 handoff is
also implemented: CPI catalog/Silver support, automatic series coverage, and safe
read-only Agent queries over Silver. Gold P0 is implemented as catalog-driven,
fail-closed functions for frequency alignment, cumulative decomposition, and period joins.
Generic and ad-hoc ingestion V1 is also implemented: unknown CSV, XLSX, JSON-record, and
static HTML inputs can be ingested through a guarded connector/parser path, registered only
as draft/derived catalog entries, and published into an isolated ad-hoc observation table
with durable run-to-artifact provenance.

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
- Gold P0 API and branch delivery:
  [`gold-contract.md`](lakehouse-core/docs/gold-contract.md) ·
  [`gold-functions-v1.md`](lakehouse-core/docs/branches/gold-functions-v1.md)
- Generic and ad-hoc ingestion V1:
  [`generic-ingestion-contract.md`](lakehouse-core/docs/generic-ingestion-contract.md) ·
  [`adhoc-publication-contract.md`](lakehouse-core/docs/adhoc-publication-contract.md) ·
  [`generic-adhoc-review-fixes.md`](lakehouse-core/docs/branches/generic-adhoc-review-fixes.md)
- Independent architecture and quality audit:
  [`data-lakehouse-bagimsiz-denetim-raporu-2026-09-10.md`](lakehouse-core/docs/audits/data-lakehouse-bagimsiz-denetim-raporu-2026-09-10.md)

The Generic/Ad-hoc branch checkpoint has **942 passing tests**. The remaining
Data/Lakehouse scope is operational CLI/windowing, then catalog/FinTürk expansion and
live-source evidence closure.
