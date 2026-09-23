# Agent Tool Failure Recovery

## Observed bug

Manual testing showed a failed historical-data retrieval could end with a
data-absence answer even though a different catalog, Gold, or query path could
retrieve the same concept. A later unrelated turn could also appear to revive
the old attempt.

## Root cause

`AnalyticsAgent._ask` returned control to narration after a recoverable tool
error without a structured availability outcome. The model's absence wording
was therefore not distinguishable from authoritative coverage evidence.
`LakehouseSearchTool` also kept empty and pending search streaks on the tool
instance; before this change they were not reset at a user-turn boundary.
The core greeting path itself is deterministic and does not call the LLM, so
an actual pending execution was not found in that path. The stale-state risk
was nevertheless real for stateful tool counters and any future execution
continuation.

## Failure taxonomy

Existing `ToolError` codes are mapped to recovery classes without replacing
the project error contract:

- `SQL_FAILED`: query execution; never proof of absence.
- `INVALID_ARGS`: argument repair or a different tool; never proof of absence.
- `GOLD_REQUIRED`: semantic guard; route to Gold-compatible handling.
- `JOIN_MISMATCH`: alignment/grain recovery or an explicit limitation.
- `DATASET_NOT_FOUND`: reference resolution; search is bounded before absence.
- retryable `TOOL_FAILED`: bounded transient/provider recovery.
- access, unsafe, stale, and coverage decisions remain terminal when their
  existing contract says that retrying cannot change the result.

## Availability semantics

Execution state exposes `FOUND`, `CONFIRMED_ABSENT`, `RETRIEVAL_FAILED`,
`ACCESS_BLOCKED`, `UNSUPPORTED`, and `UNKNOWN`. `RETRIEVAL_FAILED` is the
default outcome for an unsuccessful query or unresolved reference. It cannot
be promoted to `CONFIRMED_ABSENT` by model narration. Coverage evidence and an
authoritative empty catalog search are the only absence paths.

## Same-turn recovery

After a recoverable failure the harness gives the planner a bounded fresh-plan
opportunity. The planner may search, inspect schema, repair arguments, or use
Gold. Identical tool and argument signatures are blocked by the existing loop
guard, and recovery attempts are capped at three. Successful data-producing
execution changes the outcome to `FOUND` and ends recovery.

## Turn finalization

`ExecutionState` is created per user turn and is attached to the answer as
structured execution metadata. Stateful registered tools receive
`begin_turn`; the lakehouse search streaks are reset there. A finalized failed
turn does not commit a failed series, SQL, or absence claim into semantic
follow-up context.

## Explicit retry behavior

The phrases `tekrar dene`, `yeniden çek`, and `bir daha dene` explicitly reopen
the most recent retrieval failure. The previous semantic question is supplied
as context, while its failed signatures are excluded from blind replay. A
normal new substantive question closes that retry affordance; a greeting does
not execute it and remains a greeting.

## Loop protection

The existing maximum-step and duplicate-call guards remain active. Recovery
does not add work to successful one-path queries. Failed paths receive only
bounded replan prompts and then finalize with a truthful retrieval failure.

## Observability

Answer artifacts include turn id, failure class, tool error code, retryability,
recovery attempt, recovery action, duplicate-call state, availability status,
finalization reason, and whether an explicit retry restored the previous task.
Only structured metadata is exposed; raw prompts, credentials, and large
tool payloads are excluded.

## Tests

`tests/test_tool_failure_recovery.py` covers the observed error classes,
absence proof, same-turn alternate paths, bounded retries, loop protection,
greeting isolation, explicit retry, context rollback, session isolation, API
serialization, and turn-scoped lakehouse search state. Existing multi-turn,
Agent, and Lakehouse suites remain regression gates.

## Known limitations

Recovery still depends on the planner selecting an available alternate tool
or repair after the harness presents structured feedback. Access and coverage
failures are not retried blindly. Manual provider failures may still require
operator or credential investigation.
