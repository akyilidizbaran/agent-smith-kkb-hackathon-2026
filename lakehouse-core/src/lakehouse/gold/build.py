"""Materialize the reviewed Gold metrics as ``gold.<metric_id>`` tables, or record why not.

The functions stay the source of truth. A table built here is a *cached call* of one of
them, named and reviewed in ``catalog/gold/*.yml``, rebuilt from the current Silver snapshot
every time this runs. Three rules keep the cache honest:

1. **A refusal is recorded, never papered over.** If the function refuses a metric --
   unverified semantics, a stock handed to ``decompose_cumulative``, no observations -- the
   metric's row in ``meta.gold_build`` says ``refused`` with the reason, and any table a
   previous build left behind is **dropped**. A stale table that still answers is worse than
   a missing one.
2. **Every row carries its build.** ``gold_build_id``, ``gold_built_at``, the metric's
   catalog hash and the Silver fingerprint the build read are columns on the table, next to
   the per-row provenance the functions already emit (``artifact_sha256_list``,
   ``source_observation_dates`` ...). A consumer can tell a number's build from the row.
3. **Staleness is detectable.** The Silver fingerprint is a hash over every observation.
   After a ``silver`` rebuild the fingerprint changes, and a reader comparing the table's
   recorded fingerprint against the live one knows the table is behind.

The whole build is one transaction: either every metric's outcome lands or none does.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ..contracts.identifiers import new_run_id
from .align import align_frequency
from .catalog import DEFAULT_GOLD_CATALOG_ROOT, GoldMetricRecord, load_gold_catalog_files
from .cumulative import decompose_cumulative
from .errors import GoldError
from .join import join_on_period

GOLD_SCHEMA = "gold"
GOLD_BUILD_TABLE = "meta.gold_build"

PROVENANCE_COLUMNS: tuple[str, ...] = (
    "gold_metric_id",
    "gold_function",
    "gold_build_id",
    "gold_built_at",
    "gold_catalog_content_sha256",
    "silver_fingerprint",
)
"""Build-level provenance appended to every materialized row."""

_DOUBLE = frozenset({"value", "cumulative_value", "previous_cumulative_value", "raw_change"})
_DATE = frozenset({"period_start", "period_end", "previous_observation_date"})
_INTEGER = frozenset(
    {"observations", "missing_observations", "warned_observations", "contributor_count"}
)
_BOOLEAN = frozenset({"is_complete_period"})
_DATE_LIST = frozenset({"source_observation_dates"})
_VARCHAR_LIST = frozenset(
    {
        "artifact_sha256_list",
        "vintage_id_list",
        "run_id_list",
        "contributing_series",
        "absent_series",
    }
)


def sql_type_for(column: str) -> str:
    """The declared DuckDB type of a Gold column, by its base name.

    Joined frames prefix per-series fields with ``<key>::``; the base name after the last
    ``::`` decides the type. Declaring types explicitly, instead of trusting pandas
    inference over object columns, is what makes an all-NULL ``value`` column DOUBLE and an
    all-empty list column ``VARCHAR[]`` on every build.
    """

    base = column.rsplit("::", 1)[-1]
    if base in _DOUBLE:
        return "DOUBLE"
    if base in _DATE:
        return "DATE"
    if base in _INTEGER:
        return "INTEGER"
    if base in _BOOLEAN:
        return "BOOLEAN"
    if base in _DATE_LIST:
        return "DATE[]"
    if base in _VARCHAR_LIST:
        return "VARCHAR[]"
    return "VARCHAR"


def call_gold_function(
    connection: duckdb.DuckDBPyConnection,
    *,
    function: str,
    series_ids: tuple[str, ...] | list[str],
    target_frequency: str | None,
    allow_unverified_semantics: bool = False,
) -> pd.DataFrame:
    """Dispatch one reviewed call to the Gold function it names. Refusals propagate."""

    if function == "align_frequency":
        (series_id,) = series_ids
        return align_frequency(
            connection,
            series_id,
            target_frequency,  # type: ignore[arg-type]
            allow_unverified_semantics=allow_unverified_semantics,
        )
    if function == "decompose_cumulative":
        (series_id,) = series_ids
        return decompose_cumulative(
            connection, series_id, allow_unverified_semantics=allow_unverified_semantics
        )
    if function == "join_on_period":
        return join_on_period(
            connection,
            list(series_ids),
            target_frequency,  # type: ignore[arg-type]
            allow_unverified_semantics=allow_unverified_semantics,
        )
    raise ValueError(f"unknown Gold function {function!r}")


def silver_fingerprint(connection: duckdb.DuckDBPyConnection) -> tuple[str, int]:
    """(hash over every Silver observation, row count).

    Ordered before hashing so the same snapshot always yields the same digest, whatever
    order the rows were inserted in. A change to any value, date, entity or artifact changes
    the digest; a rebuild that publishes an identical snapshot does not.
    """

    row = connection.execute(
        """
        SELECT coalesce(md5(string_agg(
                   series_id || '|' || coalesce(entity_id, '') || '|' || observation_date
                   || '|' || coalesce(value::VARCHAR, '') || '|' || quality_flag
                   || '|' || artifact_sha256,
                   ','
                   ORDER BY series_id, entity_id, observation_date, artifact_sha256
               )), 'empty'),
               count(*)
        FROM silver.fact_observation
        """
    ).fetchone()
    return str(row[0]), int(row[1])


@dataclass(frozen=True)
class MetricBuildOutcome:
    """What happened to one metric in one build."""

    metric_id: str
    function: str
    status: str  # built | refused
    row_count: int = 0
    refusal_reason: str | None = None
    refusal_message: str | None = None
    dropped_stale_table: bool = False


@dataclass
class GoldBuildReport:
    """Everything one build did, including what it declined to do."""

    build_id: str
    built_at: datetime
    silver_fingerprint: str
    silver_row_count: int
    metrics_in_catalog: int = 0
    outcomes: list[MetricBuildOutcome] = field(default_factory=list)
    orphan_tables_dropped: tuple[str, ...] = ()

    @property
    def built(self) -> list[MetricBuildOutcome]:
        return [o for o in self.outcomes if o.status == "built"]

    @property
    def refused(self) -> list[MetricBuildOutcome]:
        return [o for o in self.outcomes if o.status == "refused"]

    def render(self) -> str:
        lines = [
            f"gold build id          : {self.build_id}",
            f"silver observations    : {self.silver_row_count} (fingerprint {self.silver_fingerprint[:12]})",
            f"metrics in catalog     : {self.metrics_in_catalog}",
            f"tables built           : {len(self.built)}",
        ]
        for outcome in self.built:
            lines.append(f"  - gold.{outcome.metric_id}: {outcome.row_count} rows ({outcome.function})")
        lines.append(f"metrics refused        : {len(self.refused)}")
        for outcome in self.refused:
            stale = " [stale table dropped]" if outcome.dropped_stale_table else ""
            lines.append(
                f"  - {outcome.metric_id}: {outcome.refusal_reason} -- {outcome.refusal_message}{stale}"
            )
        if self.orphan_tables_dropped:
            lines.append(
                f"orphan tables dropped  : {len(self.orphan_tables_dropped)} "
                f"({', '.join(self.orphan_tables_dropped)})"
            )
        return "\n".join(lines)


def _existing_gold_tables(connection: duckdb.DuckDBPyConnection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
            [GOLD_SCHEMA],
        ).fetchall()
    }


def _previously_built_metrics(connection: duckdb.DuckDBPyConnection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            f"SELECT DISTINCT metric_id FROM {GOLD_BUILD_TABLE} WHERE status = 'built'"
        ).fetchall()
    }


def _typed_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce pandas object columns so DuckDB sees the declared types, not a sample's guess."""

    typed = frame.copy()
    for column in typed.columns:
        kind = sql_type_for(str(column))
        if kind == "DOUBLE":
            typed[column] = pd.to_numeric(typed[column], errors="raise").astype("float64")
        elif kind == "INTEGER":
            typed[column] = pd.to_numeric(typed[column], errors="raise").astype("Int64")
        elif kind == "BOOLEAN":
            typed[column] = typed[column].astype("boolean")
    return typed


def _materialize(
    connection: duckdb.DuckDBPyConnection,
    record: GoldMetricRecord,
    frame: pd.DataFrame,
    *,
    build_id: str,
    built_at: datetime,
    fingerprint: str,
) -> int:
    typed = _typed_frame(frame)
    typed["gold_metric_id"] = record.metric_id
    typed["gold_function"] = record.function
    typed["gold_build_id"] = build_id
    typed["gold_built_at"] = built_at
    typed["gold_catalog_content_sha256"] = record.content_sha256
    typed["silver_fingerprint"] = fingerprint

    projections = []
    for column in typed.columns:
        name = str(column).replace('"', '""')
        if column == "gold_built_at":
            projections.append(f'"{name}"::TIMESTAMPTZ AS "{name}"')
        else:
            projections.append(f'"{name}"::{sql_type_for(str(column))} AS "{name}"')
    view = f"_gold_build_{record.metric_id}"
    connection.register(view, typed)
    try:
        connection.execute(
            f'CREATE OR REPLACE TABLE {GOLD_SCHEMA}."{record.metric_id}" AS '
            f"SELECT {', '.join(projections)} FROM {view}"
        )
    finally:
        connection.unregister(view)
    return int(
        connection.execute(
            f'SELECT count(*) FROM {GOLD_SCHEMA}."{record.metric_id}"'
        ).fetchone()[0]
    )


def _record_outcome(
    connection: duckdb.DuckDBPyConnection,
    record: GoldMetricRecord,
    outcome: MetricBuildOutcome,
    *,
    build_id: str,
    built_at: datetime,
    fingerprint: str,
    silver_rows: int,
) -> None:
    connection.execute(
        f"UPDATE {GOLD_BUILD_TABLE} SET is_current = false WHERE metric_id = ? AND is_current",
        [record.metric_id],
    )
    connection.execute(
        f"""
        INSERT INTO {GOLD_BUILD_TABLE} (
            build_id, metric_id, function, series_ids, target_frequency, name_tr, description,
            aliases, tags, allow_unverified_semantics, status, row_count, refusal_reason,
            refusal_message, catalog_content_sha256, silver_fingerprint, silver_row_count,
            is_current, built_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, true, ?)
        """,
        [
            build_id,
            record.metric_id,
            record.function,
            list(record.series_ids),
            record.target_frequency,
            record.name_tr,
            record.description,
            list(record.aliases),
            list(record.tags),
            record.allow_unverified_semantics,
            outcome.status,
            outcome.row_count if outcome.status == "built" else None,
            outcome.refusal_reason,
            outcome.refusal_message,
            record.content_sha256,
            fingerprint,
            silver_rows,
            built_at,
        ],
    )


def build_gold_tables(
    connection: duckdb.DuckDBPyConnection,
    *,
    catalog_root: Path = DEFAULT_GOLD_CATALOG_ROOT,
    clock: Callable[[], datetime] | None = None,
) -> GoldBuildReport:
    """Rebuild every catalogued metric from the current Silver snapshot, in one transaction.

    ``connection`` must be a trusted (writable) connection on a bootstrapped database:
    ``meta.gold_build`` and the ``gold`` schema come from the bootstrap SQL.
    """

    records = load_gold_catalog_files(catalog_root)
    built_at = (clock or (lambda: datetime.now(timezone.utc)))()
    build_id = new_run_id()
    fingerprint, silver_rows = silver_fingerprint(connection)
    report = GoldBuildReport(
        build_id=build_id,
        built_at=built_at,
        silver_fingerprint=fingerprint,
        silver_row_count=silver_rows,
        metrics_in_catalog=len(records),
    )

    connection.begin()
    try:
        existing = _existing_gold_tables(connection)
        previously_built = _previously_built_metrics(connection)
        for record in records:
            try:
                frame = call_gold_function(
                    connection,
                    function=record.function,
                    series_ids=record.series_ids,
                    target_frequency=record.target_frequency,
                    allow_unverified_semantics=record.allow_unverified_semantics,
                )
            except GoldError as exc:
                dropped = record.metric_id in existing
                if dropped:
                    connection.execute(f'DROP TABLE {GOLD_SCHEMA}."{record.metric_id}"')
                outcome = MetricBuildOutcome(
                    metric_id=record.metric_id,
                    function=record.function,
                    status="refused",
                    refusal_reason=exc.refusal.reason,
                    refusal_message=exc.refusal.message,
                    dropped_stale_table=dropped,
                )
            else:
                rows = _materialize(
                    connection, record, frame,
                    build_id=build_id, built_at=built_at, fingerprint=fingerprint,
                )
                outcome = MetricBuildOutcome(
                    metric_id=record.metric_id, function=record.function,
                    status="built", row_count=rows,
                )
            _record_outcome(
                connection, record, outcome,
                build_id=build_id, built_at=built_at,
                fingerprint=fingerprint, silver_rows=silver_rows,
            )
            report.outcomes.append(outcome)

        # A metric removed from the catalog must not keep answering from a table this
        # module built earlier. Tables the build never wrote are not its to drop.
        catalogued = {record.metric_id for record in records}
        orphans = sorted((previously_built & existing) - catalogued)
        for metric_id in orphans:
            connection.execute(f'DROP TABLE {GOLD_SCHEMA}."{metric_id}"')
            connection.execute(
                f"UPDATE {GOLD_BUILD_TABLE} SET is_current = false WHERE metric_id = ?",
                [metric_id],
            )
        report.orphan_tables_dropped = tuple(orphans)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return report


__all__ = [
    "GOLD_BUILD_TABLE",
    "GOLD_SCHEMA",
    "PROVENANCE_COLUMNS",
    "GoldBuildReport",
    "MetricBuildOutcome",
    "build_gold_tables",
    "call_gold_function",
    "silver_fingerprint",
    "sql_type_for",
]
