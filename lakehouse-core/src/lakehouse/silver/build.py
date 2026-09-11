"""Rebuild the whole Silver snapshot from what is already durable in Bronze.

Until now nothing in production wrote ``silver.fact_observation``. The generic foundation, the
source adapters and the projection all existed and were exercised by tests, but every caller
of :func:`materialize_fact_observation_snapshot` lived under ``tests/``. A real ingestion run
therefore ended at Bronze, and an agent reading Silver saw an empty table no matter how much
had been ingested. This module is that missing step.

It rebuilds rather than appends, because the snapshot operation is defined that way: a later
call replaces the entire table and never merges. Bronze is the durable, content-addressed
evidence, so "everything in Bronze, mapped through the catalog" is a complete and reproducible
definition of the snapshot — running it twice over the same Bronze tree yields the same table.

What it refuses to do is as important as what it does. A series the catalog has not given a
unit and a measure type is reported and left out, never published with an empty meaning. Two
artifacts that disagree about the same observation are a revision conflict and stop the build,
never a silent pick.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from ..storage.parquet import ParquetIdentity, ParquetStorage, read_identity
from .adapters.catalog_driven import (
    SOURCE_MAPPINGS,
    SeriesSemantics,
    catalog_driven_to_staging,
    load_series_semantics,
)
from .foundation import (
    SilverValidationError,
    artifact_vintage_id,
    materialize_fact_observation_snapshot,
)


@dataclass(frozen=True)
class SkippedArtifact:
    """One Bronze artifact that contributed nothing, and why."""

    bronze_path: Path
    reason: str


@dataclass
class SilverBuildReport:
    """What a rebuild actually published, and everything it declined to publish."""

    artifacts_found: int = 0
    artifacts_staged: int = 0
    rows_staged: int = 0
    rows_published: int = 0
    series_published: tuple[str, ...] = ()
    skipped_artifacts: list[SkippedArtifact] = field(default_factory=list)
    #: series_id -> why the catalog does not allow publishing it yet
    withheld_series: dict[str, str] = field(default_factory=dict)
    #: series_id -> how many Bronze rows were left out because of that
    withheld_rows: dict[str, int] = field(default_factory=dict)
    #: how many rows were dropped as identical boundary duplicates of another artifact's row
    deduplicated_rows: int = 0

    def render(self) -> str:
        """A short operator-facing summary; every number here is a count, never a guess."""

        lines = [
            f"bronze artifacts found : {self.artifacts_found}",
            f"bronze artifacts staged: {self.artifacts_staged}",
            f"rows staged            : {self.rows_staged}",
            f"boundary duplicates    : {self.deduplicated_rows}",
            f"rows published         : {self.rows_published}",
            f"series published       : {len(self.series_published)}",
        ]
        if self.withheld_series:
            withheld_by_reason: dict[str, int] = defaultdict(int)
            for reason in self.withheld_series.values():
                withheld_by_reason[reason] += 1
            lines.append(
                f"series withheld        : {len(self.withheld_series)} "
                f"({sum(self.withheld_rows.values())} rows)"
            )
            for reason, count in sorted(withheld_by_reason.items()):
                lines.append(f"  - {reason}: {count}")
        if self.skipped_artifacts:
            lines.append(f"artifacts skipped      : {len(self.skipped_artifacts)}")
            reasons: dict[str, int] = defaultdict(int)
            for skipped in self.skipped_artifacts:
                reasons[skipped.reason] += 1
            for reason, count in sorted(reasons.items()):
                lines.append(f"  - {reason}: {count}")
        return "\n".join(lines)


def discover_bronze_artifacts(bronze_root: Path) -> list[Path]:
    """Every Bronze Parquet file, in a deterministic order.

    Silver representations live under ``representation=silver`` in the same tree and are
    excluded: rebuilding Silver from a previous Silver output would launder a mapping mistake
    into evidence.
    """

    if not bronze_root.is_dir():
        return []
    return sorted(
        path
        for path in bronze_root.rglob("*.parquet")
        if "representation=silver" not in path.parts
    )


def _run_context(
    connection: duckdb.DuckDBPyConnection, identity: ParquetIdentity
) -> tuple[str | None, list[str]]:
    """Recover the ingestion run and its parser warnings for one artifact.

    The warnings are not decoration: ``quality_flag`` is ``source_warning`` exactly when the
    parse that produced these bytes warned. Rebuilding Silver without them would quietly
    upgrade a flagged observation to ``ok``, which is the one direction a quality flag must
    never move. ``meta.ingest_warning`` is where they were persisted, so they are read back
    rather than lost.
    """

    row = connection.execute(
        """
        SELECT run_id
        FROM meta.run_artifact
        WHERE artifact_sha256 = ?
        ORDER BY fetched_at, run_id
        LIMIT 1
        """,
        [identity.artifact_sha256],
    ).fetchone()
    if row is None:
        return None, []
    run_id = row[0]
    warnings = connection.execute(
        """
        SELECT message
        FROM meta.ingest_warning
        WHERE run_id = ?
          AND (artifact_sha256 IS NULL OR artifact_sha256 = ?)
        ORDER BY warning_seq
        """,
        [run_id, identity.artifact_sha256],
    ).fetchall()
    return run_id, [str(warning[0]) for warning in warnings]


def _publishable_rows(
    frame: pd.DataFrame,
    *,
    semantics: dict[str, SeriesSemantics],
    source_id: str,
    report: SilverBuildReport,
) -> pd.DataFrame:
    """Keep only the rows whose series the catalog is ready to publish, and account for the rest.

    One Bronze artifact can legitimately carry measures nobody catalogued — BDDK FinTürk
    returns a whole grid of consumer-credit columns while the catalog registers one of them.
    Leaving those out is correct; leaving them out quietly is not, so each exclusion is counted
    against its series in the report.
    """

    keep: list[bool] = []
    for series_id in frame["series_id"].tolist():
        series = semantics.get(series_id)
        if series is None:
            reason = "not in meta.series"
        elif series.source_id != source_id:
            reason = f"catalogued under source {series.source_id!r}"
        else:
            reason = series.unpublishable_reason
        if reason is None:
            keep.append(True)
            continue
        keep.append(False)
        report.withheld_series[str(series_id)] = reason
        report.withheld_rows[str(series_id)] = (
            report.withheld_rows.get(str(series_id), 0) + 1
        )
    return frame.loc[pd.Series(keep, index=frame.index)]


def _deduplicate_boundaries(
    staging: pd.DataFrame, report: SilverBuildReport
) -> pd.DataFrame:
    """Collapse identical observations that two artifacts both carry; refuse disagreements.

    EVDS windowing deliberately writes one Bronze artifact per window, and consecutive windows
    share their boundary observation. ``EvdsWindowReconciler`` resolves that inside a single
    run, in memory, before anything is combined — but Bronze keeps both artifacts, so a rebuild
    that reads Bronze directly meets the same boundary twice and has to apply the same rule:
    identical values are one observation, different values are a revision conflict and stop the
    build. Neither case is ever decided by picking whichever row happened to be read first.
    """

    if staging.empty:
        return staging

    key_columns = ["series_id", "entity_id", "observation_date"]
    ordered = staging.sort_values(
        key_columns + ["fetched_at", "artifact_sha256"],
        kind="mergesort",
        na_position="first",
    )
    seen: dict[tuple, tuple[object, str]] = {}
    keep_positions: list[int] = []
    for position, (_, row) in enumerate(ordered.iterrows()):
        key = tuple(
            None if pd.isna(row[column]) else row[column] for column in key_columns
        )
        value = row["value_raw"]
        normalized = None if value is None or pd.isna(value) else str(value).strip()
        if key in seen:
            previous, previous_artifact = seen[key]
            if previous != normalized:
                raise SilverValidationError(
                    "conflicting observations for the same Silver identity: "
                    f"series_id={key[0]!r}, entity_id={key[1]!r}, observation_date={key[2]!r} "
                    f"is {previous!r} in artifact {previous_artifact} and {normalized!r} in "
                    f"artifact {row['artifact_sha256']}. This is a revision, not a duplicate; "
                    "decide which vintage is current before rebuilding Silver."
                )
            report.deduplicated_rows += 1
            continue
        seen[key] = (normalized, str(row["artifact_sha256"]))
        keep_positions.append(position)
    return ordered.iloc[keep_positions].reset_index(drop=True)


def build_silver_snapshot(
    connection: duckdb.DuckDBPyConnection,
    *,
    bronze_root: Path,
    bronze_paths: Iterable[Path] | None = None,
) -> SilverBuildReport:
    """Map every catalogued Bronze observation into one new ``silver.fact_observation``."""

    report = SilverBuildReport()
    semantics = load_series_semantics(connection)
    paths = (
        sorted(bronze_paths)
        if bronze_paths is not None
        else discover_bronze_artifacts(bronze_root)
    )
    report.artifacts_found = len(paths)

    staged_frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            identity = read_identity(path)
        except Exception as exc:  # unreadable identity is evidence, not a crash
            report.skipped_artifacts.append(
                SkippedArtifact(path, f"unreadable Parquet identity: {exc}")
            )
            continue
        if identity.representation != "bronze":
            report.skipped_artifacts.append(
                SkippedArtifact(path, f"representation={identity.representation}")
            )
            continue
        if identity.source_id not in SOURCE_MAPPINGS:
            report.skipped_artifacts.append(
                SkippedArtifact(path, f"no Silver mapping for source {identity.source_id!r}")
            )
            continue

        frame = ParquetStorage.read(path)
        if frame.empty:
            report.skipped_artifacts.append(SkippedArtifact(path, "empty Bronze frame"))
            continue
        publishable = _publishable_rows(
            frame, semantics=semantics, source_id=identity.source_id, report=report
        )
        if publishable.empty:
            report.skipped_artifacts.append(
                SkippedArtifact(path, "no publishable series in this artifact")
            )
            continue

        run_id, warnings = _run_context(connection, identity)
        staged_frames.append(
            catalog_driven_to_staging(
                publishable,
                identity=identity,
                semantics=semantics,
                run_id=run_id,
                source_warnings=warnings,
                vintage_id=artifact_vintage_id(identity.artifact_sha256),
            )
        )
        report.artifacts_staged += 1

    if not staged_frames:
        return report

    staging = pd.concat(staged_frames, ignore_index=True)
    report.rows_staged = len(staging)
    staging = _deduplicate_boundaries(staging, report)

    published = materialize_fact_observation_snapshot(connection, staging)
    report.rows_published = len(published)
    report.series_published = tuple(sorted(set(published["series_id"].tolist())))
    return report


__all__ = [
    "SilverBuildReport",
    "SkippedArtifact",
    "build_silver_snapshot",
    "discover_bronze_artifacts",
]
