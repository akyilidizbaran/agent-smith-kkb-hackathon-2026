# Ad-hoc Publication Contract

Two things live here: how a machine-proposed series enters the catalog, and how ad-hoc
observations reach a table the agent can query. Both exist so that user-supplied data can be
used in a session **without** becoming indistinguishable from data somebody reviewed.

---

## 1. `register_series` — propose, never verify

```python
register_series(
    connection,
    record,                      # a dict shaped like a catalog YAML entry
    *,
    source_id="adhoc",
    confidence="derived",        # the only accepted value
    semantic_source="profiler",  # the only accepted value
    status="draft",              # the only accepted value
) -> RegistrationResult
```

The three evidence parameters appear in the signature so a reader sees what will be written
and a caller passing something else gets a refusal — not so the value can be chosen. Passing
`confidence="verified"` raises. So does setting it inside `record`: the three fields are
overwritten before validation, so a smuggled `verified` cannot slip past the parameter checks.

### One validator, not two

`record` goes through `lakehouse.catalog.series.build_series_record`, which is
`_parse_entry` — the same function the YAML loader uses, exposed publicly for this purpose.
The eighteen catalog rules cannot drift apart between the file path and the programmatic one,
because there is only one copy of them.

### Conflict and idempotence

| Situation | Behaviour |
|---|---|
| New `series_id` | Inserted as `derived` / `profiler` / `draft` |
| Same id, identical content hash | No-op. `updated_at` does not churn, so a retrying profiler is harmless |
| Same id, **different** content | `RegistrationConflict`. The stored draft is untouched |
| Existing row is `verified` | `RegistrationConflict`. A reviewed record is never replaced by a machine |
| Existing row is `active` or `deprecated` | `RegistrationConflict`. Published and withdrawn are both human decisions |

`first_obs` and `last_obs` are neither written nor cleared: they describe the Silver snapshot,
and a registration is not one. Writes run in one transaction, so a validation or constraint
failure leaves `meta.series` exactly as it was. YAML files are never written — a test asserts
their bytes are unchanged.

### Why a draft is unusable

`align_frequency` refuses anything that is not `status='active'` (`INACTIVE_SERIES`) *and*
anything that is not `semantic_confidence='verified'` (`UNVERIFIED_SEMANTICS`). A draft fails
both. That is the point: a profiler's proposal becomes usable only after a human promotes it,
and **this version ships no promotion path on purpose**.

---

## 2. `adhoc.fact_observation`

A separate schema, created by `sql/bootstrap/020_adhoc_observations.sql`. `001_schemas.sql` is
not edited; bootstrap globs `*.sql` in sorted order, so the new file is picked up with no code
change and re-running it is a no-op.

### Why separate, rather than rows in Silver

1. `materialize_fact_observation_snapshot` replaces the **whole** Silver table. One ad-hoc
   series would mean rebuilding every curated series beside it, and a mapping mistake would
   take the curated data down with it.
2. "Where did this number come from" becomes a schema boundary rather than a convention.
3. The demo copy can be dropped afterwards without touching curated data.

The columns are identical to `silver.fact_observation` — same names, same order, same
meanings — so a consumer that reads one reads the other.

### Storage-level constraints

| Constraint | Why it is in SQL and not only in code |
|---|---|
| `source_id = 'adhoc'` | A row claiming to be curated data cannot be inserted by any path |
| `quality_flag IN ('ok','missing_value','source_warning')` | Mirrors the Silver vocabulary |
| `value IS NULL OR isfinite(value)` | A direct INSERT cannot smuggle in a NaN |

Uniqueness of `(series_id, entity_id, observation_date, artifact_sha256)` is enforced in
application code inside the publication transaction, **not** by a primary key. DuckDB makes
every primary-key column `NOT NULL`, and `entity_id` is legitimately nullable — a series with
no entity breakdown has no entity. Adding a sentinel column to satisfy the key would diverge
from the Silver contract for nothing. This mirrors how Silver already gates duplicates.

---

## 3. `AdhocObservationMapping`

```python
AdhocObservationMapping(
    series_id,
    observation_date_column,
    value_column,
    entity_id_column=None,
    date_format=None,
    decimal_separator=".",
    thousands_separator=None,
)
```

**Layout only.** There is deliberately no `measure_type`, `frequency`, `unit` or aggregation
field, and a test asserts their absence over the real dataclass. Those are catalog facts:
letting a mapping carry them would let the same file mean two different things depending on
who published it.

Column names are looked up in the parsed frame. They are never interpolated into SQL.

### Dates

Only ISO `YYYY-MM-DD` is accepted without a declaration. Anything else needs an explicit
`date_format`.

`01/02/2026` is January 2nd or February 1st, and nothing in a file of such dates settles it —
a column where every day is ≤ 12 is consistent with both readings. So it is refused with a
message naming the fix, rather than resolved by locale, by majority vote, or by whichever
`strptime` pattern happens to be tried first.

### Numbers

`"1,5"` is one-and-a-half in Turkish and fifteen hundred in English. The separators must be
stated:

| Declaration | `"1.234.567,89"` | `"1,5"` | `"1.234,5"` |
|---|---|---|---|
| defaults (`.` decimal) | refused | refused | refused |
| `decimal_separator=","` | refused | `1.5` | refused (undeclared `.`) |
| `decimal_separator=","`, `thousands_separator="."` | `1234567.89` | `1.5` | `1234.5` |

Refusals name the parameter that would resolve them. NaN and Infinity are rejected outright
and are never converted to NULL — "not a number" and "no measurement" are different facts. An
empty cell stays NULL and is published with `quality_flag = 'missing_value'`, never as zero.

*CSV note:* CSV has no NULL. An empty field arrives at Bronze as an empty string, faithfully,
and the mapping is where "empty means no measurement" is stated.

---

## 4. `publish_adhoc_observations`

```python
publish_adhoc_observations(connection, result, mappings) -> AdhocPublicationResult
```

`result` is the `IngestionResult` the pipeline returned. Values are loaded from its durable
`bronze_path`, never from `parsed_batch.dataframe`. `read_identity` verifies source, dataset,
RAW artifact SHA, schema version, representation (`bronze`) and parser configuration SHA.
The asset and parsed batch must agree with that identity, and the canonical parser choices
must be present in durable artifact request provenance. Missing or invalid files fail closed.

Ad-hoc `IngestionResult` construction requires a UUID `run_id`; legacy non-ad-hoc four-argument
construction remains compatible with the baseline. Publication requires that run to exist in
`meta.run`, match source/dataset, and have `success` or `warning` status. The ad-hoc SQL table
also requires a non-NULL, nonblank run identifier. Quality flags use durable
`meta.ingest_warning` records, not a mutable in-memory warning list.

### Run–artifact provenance (`meta.run_artifact`)

A run row proves that *a* run over this source/dataset completed. It does not prove that
*this* run fetched *this* artifact, and the independent counter-tests exploited exactly that:
the `run_id` of another successful run over the same dataset was accepted, and a modified
`asset.fetched_at` was published because nothing durable was compared against it.

`sql/bootstrap/011_run_artifact.sql` adds the missing junction. `IngestionPipeline` writes one
`meta.run_artifact` row per `(run_id, artifact_sha256)` immediately after
`ArtifactRepository.register` and **before** parsing, carrying `source_id`, `dataset_id`, the
connector's `fetched_at` for that fetch and, when the connector produced one, the
`parser_config_sha256`. A parse or Bronze failure later in the run leaves the row in place and
the run still closes as `failed`. `RunRepository.link_artifact` refuses a link whose run does
not exist or is already closed, whose source/dataset differ from the run's, or whose artifact
is unregistered or registered under a different source/dataset; SQL additionally rejects blank
identifiers, malformed digests and a second row for the same pair. Re-linking the same pair
with identical facts is an exact no-op; different facts are a `RunArtifactIntegrityError`.

Publication then requires the `(run_id, artifact_sha256)` link to exist and to agree with the
result on `source_id`, `dataset_id`, `fetched_at` (to the microsecond) and
`parser_config_sha256`, and requires the link's source/dataset to match `meta.artifact`. The
published `fetched_at` is the link's value, never the in-memory asset's. A result carrying
another run's identity, or a forged `fetched_at`, is refused before any row is written.

### Gates, in order

1. Each mapping is an `AdhocObservationMapping` and no `series_id` repeats.
2. The artifact's source is `adhoc`; asset, batch, request configuration and durable Bronze
   identities agree, the run exists and matches as described above, and the durable
   `meta.run_artifact` link for this exact run and artifact exists and agrees with the
   result on source, dataset, `fetched_at` and parser configuration.
3. Each `series_id` exists in `meta.series`, belongs to source `adhoc`, and its `dataset_id`
   matches the artifact's. Frequency, unit and measure type are read from that row.
4. Every mapped column exists in the persisted Bronze frame.
5. Every date and value converts under the declared formats. Grouped numbers require 1–3
   leading integer digits followed by exact groups of three; grouping in a fraction or
   exponent is refused. For example `1,23,456` cannot become `123456`.
6. No `(entity_id, observation_date)` repeats within one artifact — a single file cannot state
   two readings for one period.

**All of it runs before a single row is inserted**, so a mapping that fails halfway leaves
nothing behind. The insert itself is one transaction.

### Duplicates and revisions

| Situation | Behaviour |
|---|---|
| Same artifact, same mapping, same values | No-op. `rows_unchanged` counts them |
| Same identity, **different** value | `AdhocPublicationConflict`. An artifact is immutable, so this is a mapping mistake, not a revision |
| Different artifact, same series/entity/date | Both rows kept. This is what a revision looks like |

There is no destructive clear or delete API. Gold already fails closed on
`AMBIGUOUS_VINTAGE` when two readings exist for one period, so a revision is visible rather
than silently resolved.

### What publication does not do

- **Silver is never touched.** A test asserts the schema does not even exist afterwards.
- **`meta.series.first_obs` / `last_obs` are not updated.** Those describe the Silver
  snapshot; ad-hoc rows are not part of one, and quietly widening the coverage window would
  make the agent's out-of-range guard lie.
- **Nothing is promoted.** A draft series with published ad-hoc rows is still refused by Gold.

---

## 5. The whole path

```text
local file or http(s) URL
  → GenericTabularConnector      (allow-list, size limit, format resolution)
  → immutable RAW artifact       (sha256, meta.artifact, meta.artifact_request)
  → IngestionPipeline            (meta.run, meta.run_artifact, meta.ingest_warning)
  → GenericTabularParser         (strings only, no inference)
  → Bronze Parquet               (adhoc_tabular.v1)
  → register_series(...)         (derived / profiler / draft)
  → AdhocObservationMapping      (explicit layout)
  → adhoc.fact_observation
  → connect_untrusted + QueryExecutor   (read-only, guarded)
```

`tests/adhoc/test_end_to_end.py` runs exactly this, on a real temporary file, and asserts the
byte digest, the provenance chain, the surviving parser warning, the draft catalog state, the
canonical date and value, the preserved NULL, that Silver is untouched, and that the agent's
connection can read the table but not write to it.

### Trust and migration limits

The local database and immutable storage directory remain trusted infrastructure. Identity
metadata is checked, but this is not a cryptographic signature over the complete Parquet
file. `meta.run_artifact` binds each run to the artifacts it fetched, so a result that carries
another run's identity or a `fetched_at` the pipeline never recorded is refused; what it does
not do is stop a writer with trusted SQL access from inserting a consistent forged link, and
direct trusted SQL writes still bypass application-level run matching and duplicate checks.
Runs recorded before `011_run_artifact.sql` existed have no link rows and must be re-ingested
before their results can be published.

This uncommitted migration is corrected in place. `CREATE TABLE IF NOT EXISTS` does not
upgrade a database that already created the old nullable table. Such deployments need an
explicit schema migration after resolving legacy NULL runs; no existing user database is
rewritten by this change. Fresh bootstrap enforces the corrected constraints.
