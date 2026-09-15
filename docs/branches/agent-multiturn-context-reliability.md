# Agent Multi-Turn Context Reliability

## Problem

The Agent already kept a bounded chat history, but history alone left follow-up
semantics implicit. A question such as `2024'te?` could lose the prior series,
while `İstanbul'la karşılaştır` could leave a stale Ankara filter in place.
The previous turn was also not exposed as a structured, inspectable decision.

## Design

`kkb_agent.core.follow_up` resolves a small set of explicit semantic fields for
the current question:

`domain`, `source`, `metric`, `series`, `entity`, `geography`, `date_range`,
`frequency`, `aggregation`, and `comparison_target`.

The resolver is a deterministic hint layer. The model still selects a
catalog-backed tool call, and tool output remains authoritative. The resolver
does not create SQL, invent series identifiers, or resample data.

## Transition rules

- A short, referential question may inherit confirmed fields from the same
  Agent session.
- An explicitly stated current field overrides the inherited value. This
  includes year, geography, frequency, aggregation, and series variants such
  as buying versus selling.
- A comparison may extend geography or retain multiple date targets instead
  of silently replacing the earlier target.
- A domain or source switch clears source-specific metric, series, entity,
  geography, frequency, aggregation, and comparison state. A generic date can
  remain available for the new scope.
- A frequency change is only a request to use an existing catalog/Gold
  capability. It never authorizes SQL-side resampling.
- An unresolved reference or an unsupported frequency without a series fails
  closed and asks for clarification rather than guessing.
- Context is session-local and is cleared by `AnalyticsAgent.reset()`.

## Commit and failure safety

A proposed resolution is committed only after a successful data-producing tool
step and when clarification is not required. If the follow-up tool call fails,
the previous committed context stays intact; a failed request cannot fabricate
fresh state for the next turn.

Each answer includes a `follow_up_resolution` artifact with the current
resolution, inherited/overridden/cleared fields, ambiguity, and commit status.
The web payload exposes this structured trace through `follow_up` without
serializing the complete raw conversation history.

## Verification

`tests/test_follow_up_context.py` covers 13 cases: year inheritance and
override, geography replacement and comparison extension, frequency changes,
series variants, comparison targets, unresolved references, domain reset,
standalone scope changes, fail-closed ambiguity, tool-failure rollback,
session isolation, and API observability.

## Limitations

The resolver intentionally handles only explicit, high-confidence lexical
signals. Complex references still go through the model and the existing
clarification/tool contracts. Catalog metadata and successful tool results are
the source of truth when a hint conflicts with available data.
