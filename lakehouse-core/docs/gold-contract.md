# Gold Contract — P0 functions

Gold is a set of **functions**, not a set of tables.

A table only answers questions about the series it was built for. On demo day the jury can
bring a series nobody catalogued in advance, and a table cannot grow a column for it. A
function applies the catalog's rule to whatever series it is handed, so a new series needs a
new `meta.series` row and nothing else.

Nothing in this layer materializes anything. These functions read
`silver.fact_observation` and `meta.series` and return DataFrames. Persisting Gold tables is
deliberately out of scope until the functions have been trusted for a while.

---

## 1. The three rules that hold everywhere

### 1.1 The catalog decides how numbers combine

`measure_type`, `default_agg`, `week_anchor`, the source `frequency` and
`semantic_confidence` are read from `meta.series` **at call time**. They are not parameters,
and no Gold function accepts one under any name — a test asserts this over the real
signatures.

The division of labour is: **the model picks the question, the catalog picks the arithmetic,
the function does the arithmetic.** A model that could pass `default_agg="sum"` for an
interest rate would be able to produce a confident, wrong number, so it cannot.

### 1.2 Fail-closed

When Gold cannot prove that a transformation preserves meaning, it raises `GoldError` instead
of returning a plausible number. The exception carries a machine-readable `reason` from a
closed vocabulary so the agent can tell "I refuse, and here is why" apart from "something
broke", and can ask the user rather than guess.

| Reason | Raised when |
|---|---|
| `SERIES_NOT_CATALOGUED` | no `meta.series` row exists, so no rule exists |
| `UNVERIFIED_SEMANTICS` | `semantic_confidence` is not `verified` and no consent was given |
| `INACTIVE_SERIES` | catalog `status` is `draft` or `deprecated`. **Not relaxed by any override** |
| `UNSUPPORTED_MEASURE_TYPE` | `ratio`, `count` or `unknown` — no verified rule in this repository |
| `MISSING_AGGREGATION_RULE` | a `rate`/`index` series with no `default_agg` |
| `UNSUPPORTED_AGGREGATION_RULE` | a `default_agg` that is meaningless for the measure type, e.g. `sum` on a rate |
| `UPSAMPLING_REFUSED` | the target period is finer than the source |
| `UNSUPPORTED_TARGET_FREQUENCY` | target is not `monthly` or `quarterly` |
| `UNSUPPORTED_SOURCE_FREQUENCY` | the catalog frequency has no coarseness ordering, or a cumulative series is not `monthly`/`quarterly` |
| `AMBIGUOUS_VINTAGE` | more than one reading exists for the same series, entity and date |
| `DECOMPOSITION_REQUIRED` | an accumulating series was passed to `align_frequency` |
| `NOT_DECOMPOSABLE` | a non-accumulating series was passed to `decompose_cumulative` |
| `MISSING_CUMULATIVE_RESET` | a `flow_ytd` series does not declare `cumulative_reset: yearly` |
| `NO_OBSERVATIONS` | the series is catalogued but the current Silver snapshot holds no rows for it |
| `PERIOD_GRAIN_CONFLICT` | a same-frequency series publishes more than once per period |
| `INVALID_ARGUMENT` | empty or duplicated `series_ids`, or a non-string `series_id` |

### 1.3 Read-only and parameterized

Only `SELECT` statements, and every identifier is bound as a parameter. Gold runs unchanged on
the hardened read-only connection the agent already uses: `access_mode=read_only`,
`enable_external_access=false`, `lock_configuration=true`. A test drives all three functions
over exactly that connection and then proves that a write and an external file read still
fail on it.

---

## 2. API

```python
align_frequency(
    connection, series_id, target_frequency, *, allow_unverified_semantics=False
) -> pd.DataFrame

decompose_cumulative(
    connection, series_id, *, allow_unverified_semantics=False
) -> pd.DataFrame

join_on_period(
    connection, series_ids, target_frequency, *, allow_unverified_semantics=False
) -> pd.DataFrame
```

`target_frequency` is `"monthly"` or `"quarterly"`. Everything else is refused rather than
approximated.

### Why these signatures and not the ones in `DATA_TEAM_REQUESTS.md`

The proposal was:

```python
align_frequency(series_id, target, *, measure_type, default_agg, week_anchor)
```

Three problems, all of them the same problem:

1. **`measure_type`, `default_agg` and `week_anchor` as parameters put the semantic rule in
   the caller's hands.** The caller here is a language model. Passing `default_agg="sum"` for
   an interest rate would produce a number that looks like an answer and is not one. They are
   read from `meta.series` instead.
2. **No connection argument.** These functions must read Silver and the catalog, and *which*
   database they read is a security decision — the read-only agent handle or a trusted one.
   Making it explicit keeps that decision visible at the call site.
3. **`decompose_cumulative(series_id, *, measure_type)`** has the same issue, and
   additionally `flow_ytd` needs `cumulative_reset`, which the proposal omits entirely.

---

## 3. Behaviour matrix: `measure_type` × target frequency

Target is always `monthly` or `quarterly`; the source frequency must be equal or finer.

| `measure_type` | Rule | Why |
|---|---|---|
| `stock` | **last** — the chronologically final reading in the period, whatever it is | A stock is a level at a point in time. Summing weekly balances would add the same money once per week. If that final reading is missing the closing balance is unknown, so the result is NULL with `boundary_missing`; reaching back to an earlier week would be a forward fill. |
| `flow_periodic` | **sum** of the non-missing readings | Each observation covers its own period, so periods add up. |
| `rate` | catalog **`default_agg`** (`avg`, `last`, `first`, `min`, `max`) | There is no single right answer; the catalog author decides. `sum` is refused. |
| `index` | catalog **`default_agg`** (same set) | Same reasoning. Refused outright when `default_agg` is absent, because averaging versus period-end is a methodology choice this repository will not make on its own. |
| `ratio` | **refused** | A ratio must be recomputed from its numerator and denominator over the target period. Averaging ratios is a different number, and Silver does not carry the two components. |
| `flow_ytd` | **refused** — call `decompose_cumulative` first | Adding year-to-date totals counts earlier periods again. |
| `flow_cumulative` | **refused** — call `decompose_cumulative` first | Same. |
| `count` | **refused** | A count may be a point-in-time population (aggregates like a stock) or events in a period (aggregates like a flow). Nothing in this repository establishes which. |
| `unknown` | **refused** | The catalog is saying the meaning was never established. |

### Same frequency = identity

`monthly → monthly` still runs every gate, then passes each observation through unchanged;
`aggregation` reads `"identity"`. If such a series publishes more than once in a period that
is a grain problem, not something to average, and it raises `PERIOD_GRAIN_CONFLICT`.

### Upsampling

Always refused. The only way to turn a quarterly series into a monthly one is to invent
observations the source never published.

### Period labelling

A Gold row is labelled by its **period end**, matching Silver's convention for month-labelled
observations. Which period an observation falls into is decided by its `observation_date` and
nothing else. A BDDK weekly bulletin published on a holiday **Thursday** falls in the month
that Thursday belongs to; it is never moved to the following Friday first, even though the
catalog declares `week_anchor: friday`. The committed fixture contains exactly this case
(2026-03-19) and a test pins it.

---

## 4. Missing values, warnings, duplicates, provenance

### Missing values

A missing observation is never read as a zero and never silently dropped. Aggregation uses the
non-missing observations, and the period reports how many were missing.

**Boundary rules and value rules behave differently, on purpose.**

`last` and `first` select **one observation by position** over *all* the period's readings and
return that observation's value as published. They do not skip a missing reading to reach an
earlier one — that would be carrying the previous value forward, which is interpolation under
another name. A stock whose closing reading is missing has an *unknown* closing balance.

`sum`, `avg`, `min` and `max` compute over the readings that exist. That is where the
partial-null policy lives, and only there.

| Situation | `value` | `quality_flag` |
|---|---|---|
| every contributing observation missing | `None` | `missing_value` |
| boundary rule, selected observation missing | `None` | `boundary_missing` |
| value rule, some observations missing | computed from the rest | `partial_period` |
| boundary rule, selected present, others missing | the selected reading | `partial_period` |
| none missing, at least one parser warning | computed | `source_warning` |
| none missing, no warnings | computed | `ok` |

Precedence is strongest-first as listed. The counts `observations`,
`missing_observations` and `warned_observations` are always present, so a consumer never has
to infer which case produced the flag.

An all-missing period returns `None`, not `0`. Turning "the source did not publish" into "the
source published a zero" is the single most damaging thing this layer could do.

### Catalog status

Only `status = 'active'` series are transformed. `draft` means the semantics are still being
written and `deprecated` means they were withdrawn; both raise `INACTIVE_SERIES`.

This gate is **not** relaxed by `allow_unverified_semantics`. Consenting to an
under-evidenced series and using one the catalog has taken out of service are different
decisions, and one override must not silently grant both.

### A catalogued series with no observations

`align_frequency` and `decompose_cumulative` raise `NO_OBSERVATIONS`, and `join_on_period`
propagates it rather than dropping the column. An empty frame would let a caller render an
empty chart as though the period genuinely had no activity; a missing join column is
invisible, while a refusal is not.

### Duplicates and revisions — fail-closed

Silver keeps every vintage on purpose: its duplicate gate includes `artifact_sha256`, so two
artifacts reporting the same period both survive. That is correct for an append-only fact
table and wrong to resolve silently here.

**There is no revision policy in this repository yet.** Gold therefore refuses any series
whose grain (`series_id`, `entity_id`, `observation_date`) carries more than one reading, and
the error names the conflicting dates and artifact counts. It does not pick the newest, the
largest or the first.

### Entities

Every function works **per entity**. A series covering both the sector total and one bank
group produces one line each; they are never merged. In `join_on_period` the entity is part of
the column key, so the two cannot collide.

### Provenance

**Aligned rows** carry `artifact_sha256_list`, `vintage_id_list`, `run_id_list` and
`source_observation_dates` — every artifact, vintage, ingestion run and source date that
contributed.

**Decomposed rows** are derived from *two* observations, so both are represented: the current
reading in `artifact_sha256` / `vintage_id` / `run_id`, the base in `previous_artifact_sha256`
/ `previous_vintage_id` / `previous_run_id` / `previous_observation_date`, plus the same
`*_list` columns and `source_observation_dates` as a set. `contributor_count` is `1` for rows
that genuinely rest on a single reading — a `flow_ytd` January, `no_prior_base`, a missing
reading — and `2` for a real difference.

A decomposed row's `quality_flag` is derived from **every** contributing observation. If the
base reading carried a parser warning, the flow computed from it is flagged `source_warning`
even though the current reading looks clean on its own. `decomposition_flag` and
`quality_flag` are separate: the first says whether the arithmetic was attributable, the
second says how trustworthy its inputs were.

**Joined rows** carry each series' lists — including `source_observation_dates` — under its
own column prefix. When a series published nothing in a period, its list fields are **empty
lists** and its counts are `0`; `<key>::series_id` still names the series, so an absent cell
stays attributable.

---

## 5. `decompose_cumulative`

Converts an accumulating series into per-period flows. Output keeps the **source** frequency:
this function changes what a value *means*, not which period it belongs to.

### Supported source frequencies: `monthly` and `quarterly` only

A difference is one period's flow only when the two readings sit in **adjacent** periods, so
decomposition needs a trustworthy "is the previous reading the previous period?" test.
Calendar months and quarters give one.

Weekly and daily series do not. BDDK's own weekly bulletin moves to a Thursday on a holiday
week, so a 6- or 8-day step is normal publishing rather than a gap — and treating either as
evidence one way would be a guess. Those frequencies raise `UNSUPPORTED_SOURCE_FREQUENCY`
rather than being decomposed on an assumption. **A multi-period difference is never published
as one period's flow.**

Two readings mapping to the same period raise `PERIOD_GRAIN_CONFLICT`: differencing a period
against itself is bad grain, not a gap.

Every row states its own status:

| `decomposition_flag` | `value` | Meaning |
|---|---|---|
| `ok` | the change | Between two known, adjacent readings. |
| `no_prior_base` | `None` | The first reading of a `flow_cumulative` series. Whatever accumulated before the series starts is unknown. |
| `unattributable_year_start` | `None` | A `flow_ytd` year whose first reading is **not** the year's opening period. The value covers January onwards, so attributing it to one period would overstate it. `raw_change` keeps the number. |
| `spans_multiple_periods` | `None` | The previous reading is not the immediately preceding period. The change is real but covers the gap too, so `raw_change` keeps it and the period does not claim it. |
| `negative_change` | the change | Below zero. Either a genuine negative flow or a revision of the running total; nothing in Silver says which, so it is emitted **and** flagged. |
| `missing_value` | `None` | This reading is missing. It also cannot become the base for the next difference. |

`flow_ytd` specifics:

- The difference is taken **within a calendar year**. January is never measured against the
  previous December.
- January's year-to-date total **is** January's flow, so it is emitted as `ok`.
- `cumulative_reset: yearly` must be declared, or the reset boundary is unknown and the call
  is refused.

---

## 6. `join_on_period`

Aligns each series with **its own** catalog rule, then joins on the shared period axis. A
weekly loan stock takes month-end while a weekly interest rate is averaged, in the same call.

- **Outer join over the union of periods.** A period where only one series published still
  appears, with the other side `None` and its `observations` at zero. Coverage differences
  stay visible instead of being trimmed away.
- `contributing_series`, `absent_series` and `is_complete_period` state the coverage of each
  row explicitly.
- **If any series cannot be transformed safely the whole call is refused.** A comparison table
  quietly missing one of its columns is worse than no table.
- Column keys are `series_id` (or `series_id@entity_id`) followed by `::` and the field:
  `evds:TP.KTF12::value`, `bddk_weekly:5690_3@bddk:10001::quality_flag`.

---

## 7. The `allow_unverified_semantics` override

Default **`False`**. It relaxes exactly one thing: the `semantic_confidence` gate.

It must be a **real `bool`**; a truthy string such as `"false"` raises `INVALID_ARGUMENT`
rather than opening the gate. It cannot supply a measure type, an aggregation rule, a
frequency or a week anchor — those have no parameter to pass them through. It does not relax
the `status` gate. So an agent that flips this flag still cannot choose
how the numbers are combined; it can only accept responsibility for a series the catalog
itself marks as not fully evidenced.

The intended caller is a human answering *"yes, use the unverified series anyway"*, relayed by
the agent. It is not a knob for a model to turn on its own initiative.

**Today this matters for two real series.** `evds:TP.KFE.TR` and `evds:TP.FG.J0` are both
`semantic_confidence: derived` because their base year is unverified — see
`docs/sources/evds.md`. Neither converts automatically. Deflating a nominal series with TÜFE
is a Gold-level calculation that additionally needs the base year, and until that evidence
arrives no function in this repository performs it.

---

## 8. Deliberately not here

- **No composition between the two transformations.** `align_frequency` reads Silver by
  `series_id`; it does not accept a frame, so a decomposed result cannot be piped into it, and
  asking for the same series again returns `DECOMPOSITION_REQUIRED`. This is deliberate for
  V1: summing per-period flows across a quarter is only correct when every period in that
  quarter produced an attributable flow, and rows flagged `no_prior_base`,
  `unattributable_year_start` or `spans_multiple_periods` carry no value, so a naive sum would
  silently understate the quarter. A safe path would need an explicit contract for what a
  quarter containing an unattributable month *means* — refuse the quarter, or report it as
  partial with the count — and that decision has not been taken. Until it is, downsampling a
  decomposed series is out of scope rather than half-supported.
- **No persisted Gold tables.** Materialization comes after the functions have been trusted.
- **No deflation, no rebasing, no real-terms conversion.** It needs a verified base year.
- **No `semiannual`, `yearly` or `daily` targets.** Only what is tested.
- **No revision or current-vintage selection.** Fail-closed until a policy exists.
- **No interpolation, forward-fill, back-fill or zero-fill.** Ever.
- **No rounding.** Values are returned as computed.
