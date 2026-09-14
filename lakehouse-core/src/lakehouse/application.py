"""Composition root for the operational lakehouse commands.

This module owns construction of production dependencies. It deliberately does not implement
source access, parsing, storage, catalog validation, publication, or run bookkeeping; those
responsibilities remain in their existing modules.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from .adhoc import (
    ADHOC_SOURCE_ID,
    AdhocObservationMapping,
    AdhocPublicationResult,
    publish_adhoc_observations,
)
from .catalog.artifacts import ArtifactRepository
from .catalog.registration import register_series
from .connectors.base import BaseConnector
from .connectors.evds import EvdsConnector
from .contracts.identifiers import new_run_id
from .contracts.models import FetchSpec
from .db.bootstrap import bootstrap_database
from .generic import GenericTabularConnector, GenericTabularParser
from .ingestion.pipeline import IngestionPipeline, IngestionResult
from .ingestion.windowing import (
    EvdsWindowFailure,
    EvdsWindowReconciler,
    WindowedIngestionFailure,
    plan_evds_windows,
    windowed_fetch_specs,
    wrap_window_failure,
)
from .parsers.base import BaseParser
from .parsers.evds import EvdsParser
from .storage.parquet import ParquetStorage
from .storage.raw import RawStorage


Clock = Callable[[], datetime]
ConnectorFactory = Callable[..., BaseConnector]
ParserFactory = Callable[[], BaseParser]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class KnownSourceDefinition:
    """One explicit source/dataset composition entry."""

    series: str
    connector_factory: ConnectorFactory
    parser_factory: ParserFactory
    frequency: str = "daily"


def _evds_cpi_connector(
    storage: RawStorage, *, session: Any = None, clock: Clock = _utc_now
) -> EvdsConnector:
    """Build the existing generic EVDS connector for the registered CPI dataset."""

    kwargs: dict[str, Any] = {"clock": clock}
    if session is not None:
        kwargs["session"] = session
    return EvdsConnector(storage, **kwargs)


KNOWN_SOURCES: dict[tuple[str, str], KnownSourceDefinition] = {
    ("evds", "evds_cpi"): KnownSourceDefinition(
        series="TP.FG.J0",
        connector_factory=_evds_cpi_connector,
        parser_factory=EvdsParser,
        frequency="monthly",
    ),
}
"""Supported source/dataset dispatch entries for this CLI version."""


@dataclass(frozen=True)
class BootstrapSummary:
    """Small stable result for the bootstrap command."""

    database: Path
    catalog_series_count: int


@dataclass(frozen=True)
class IngestionSummary:
    """Stable output fields for one production ingestion result."""

    source_id: str
    dataset_id: str
    status: str
    run_id: str
    artifact_sha256: str
    bronze_path: Path
    warning_count: int


@dataclass(frozen=True)
class WindowedIngestionSummary:
    """Stable output for one logical EVDS run and all of its window artifacts."""

    source_id: str
    dataset_id: str
    status: str
    run_id: str
    window_count: int
    artifact_sha256s: tuple[str, ...]
    bronze_paths: tuple[Path, ...]
    warning_count: int
    observation_count: int


@dataclass(frozen=True)
class AdhocIngestionSummary:
    """Stable output fields for one ad-hoc ingestion and publication."""

    ingestion: IngestionSummary
    publication: AdhocPublicationResult


def _resolve_known_source(source_id: str, dataset_id: str) -> KnownSourceDefinition:
    key = (source_id, dataset_id)
    definition = KNOWN_SOURCES.get(key)
    if definition is not None:
        return definition

    sources = sorted({source for source, _ in KNOWN_SOURCES})
    if source_id not in sources:
        raise ValueError(
            f"unknown source {source_id!r}; supported sources: {', '.join(sources)}"
        )
    datasets = sorted(dataset for source, dataset in KNOWN_SOURCES if source == source_id)
    raise ValueError(
        f"unknown dataset {dataset_id!r} for source {source_id!r}; "
        f"supported datasets: {', '.join(datasets)}"
    )


def _compose_pipeline(
    *,
    database: str | Path,
    data_root: str | Path,
    connector_factory: ConnectorFactory,
    parser_factory: ParserFactory,
    allowed_local_roots: Iterable[str | Path] | None = None,
    session: Any = None,
    clock: Clock | None = None,
) -> tuple[duckdb.DuckDBPyConnection, IngestionPipeline, Clock]:
    """Construct one trusted connection and one existing ingestion pipeline."""

    wall_clock = clock or _utc_now
    connection = bootstrap_database(database)
    try:
        raw_storage = RawStorage(Path(data_root) / "raw")
        connector_kwargs: dict[str, Any] = {"clock": wall_clock}
        if session is not None:
            connector_kwargs["session"] = session
        if allowed_local_roots is not None:
            connector_kwargs["allowed_local_roots"] = list(allowed_local_roots)
        connector = connector_factory(raw_storage, **connector_kwargs)
        pipeline = IngestionPipeline(
            connector=connector,
            parser=parser_factory(),
            artifact_repository=ArtifactRepository(connection),
            parquet_storage=ParquetStorage(Path(data_root) / "bronze"),
            clock=wall_clock,
        )
    except Exception:
        connection.close()
        raise
    return connection, pipeline, wall_clock


def _summary(
    connection: duckdb.DuckDBPyConnection, result: IngestionResult
) -> IngestionSummary:
    """Read terminal run facts from DuckDB and pair them with the pipeline result."""

    if result.run_id is None:
        raise ValueError("ingestion result did not carry a run_id")
    run = connection.execute(
        "SELECT source_id, dataset_id, status FROM meta.run WHERE run_id = ?",
        [result.run_id],
    ).fetchone()
    if run is None:
        raise ValueError(f"run {result.run_id} is missing from meta.run")
    warning_count = connection.execute(
        "SELECT count(*) FROM meta.ingest_warning WHERE run_id = ?",
        [result.run_id],
    ).fetchone()[0]
    return IngestionSummary(
        source_id=run[0],
        dataset_id=run[1],
        status=run[2],
        run_id=result.run_id,
        artifact_sha256=result.asset.artifact_sha256,
        bronze_path=result.bronze_path,
        warning_count=int(warning_count),
    )


def _windowed_summary(
    connection: duckdb.DuckDBPyConnection,
    results: list[IngestionResult],
    *,
    run_id: str,
    window_count: int,
    observation_count: int,
) -> WindowedIngestionSummary:
    """Read one logical run and retain every per-window output identity."""

    run = connection.execute(
        "SELECT source_id, dataset_id, status FROM meta.run WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if run is None:
        raise ValueError(f"run {run_id} is missing from meta.run")
    if any(result.run_id != run_id for result in results):
        raise ValueError("windowed ingestion results do not share one run_id")
    warning_count = connection.execute(
        "SELECT count(*) FROM meta.ingest_warning WHERE run_id = ?",
        [run_id],
    ).fetchone()[0]
    return WindowedIngestionSummary(
        source_id=run[0],
        dataset_id=run[1],
        status=run[2],
        run_id=run_id,
        window_count=window_count,
        artifact_sha256s=tuple(result.asset.artifact_sha256 for result in results),
        bronze_paths=tuple(result.bronze_path for result in results),
        warning_count=int(warning_count),
        observation_count=observation_count,
    )


def run_bootstrap(database: str | Path) -> BootstrapSummary:
    """Bootstrap the configured database through the existing idempotent service."""

    connection = bootstrap_database(database)
    try:
        count = connection.execute("SELECT count(*) FROM meta.series").fetchone()[0]
        return BootstrapSummary(database=Path(database), catalog_series_count=int(count))
    finally:
        connection.close()


def run_known_source_ingestion(
    *,
    source_id: str,
    dataset_id: str,
    start_date: date,
    end_date: date,
    database: str | Path,
    data_root: str | Path,
    timeout: float = 30.0,
    headers_ref: str | None = None,
    session: Any = None,
    clock: Clock | None = None,
) -> WindowedIngestionSummary:
    """Run a registered EVDS range through one logical, window-aware pipeline run."""

    definition = _resolve_known_source(source_id, dataset_id)
    windows = plan_evds_windows(start_date, end_date, frequency=definition.frequency)
    connection, pipeline, wall_clock = _compose_pipeline(
        database=database,
        data_root=data_root,
        connector_factory=definition.connector_factory,
        parser_factory=definition.parser_factory,
        session=session,
        clock=clock,
    )
    run_id = new_run_id()
    reconciler = EvdsWindowReconciler()
    try:
        logical_spec = FetchSpec(
            source_id=source_id,
            dataset_id=dataset_id,
            locator=f"registry://{source_id}/{dataset_id}",
            start_date=start_date,
            end_date=end_date,
            parameters={"series": definition.series, "type": "json"},
            headers_ref=headers_ref,
            timeout=timeout,
            requested_at=wall_clock(),
        )
        specs = windowed_fetch_specs(logical_spec, windows)
        try:
            results = pipeline.run_specs(
                specs,
                run_id=run_id,
                batch_validator=reconciler.validate_batch,
                failure_mapper=wrap_window_failure,
            )
        except EvdsWindowFailure as exc:
            raise WindowedIngestionFailure(
                run_id=run_id,
                window=exc.window,
                cause=exc,
            ) from exc
        combined = reconciler.combined()
        return _windowed_summary(
            connection,
            results,
            run_id=run_id,
            window_count=len(windows),
            observation_count=len(combined),
        )
    finally:
        connection.close()


def _adhoc_record(
    *,
    series_id: str,
    dataset_id: str,
    name: str,
    description: str,
    frequency: str,
    unit: str,
    measure_type: str,
    week_anchor: str | None,
    default_agg: str | None,
    cumulative_reset: str | None,
) -> dict[str, Any]:
    """Build the explicit draft catalog proposal required by registration."""

    if not series_id.startswith(f"{ADHOC_SOURCE_ID}:"):
        raise ValueError(
            f"series_id must use the {ADHOC_SOURCE_ID!r} namespace, for example "
            "adhoc:my_series"
        )
    native_code = series_id.split(":", 1)[1]
    if not native_code:
        raise ValueError("series_id must include a native series key after 'adhoc:'")
    return {
        "series_id": series_id,
        "native_code": native_code,
        "dataset_id": dataset_id,
        "name_tr": name,
        "description": description,
        "frequency": frequency,
        "unit": unit,
        "measure_type": measure_type,
        **({"week_anchor": week_anchor} if week_anchor is not None else {}),
        **({"default_agg": default_agg} if default_agg is not None else {}),
        **(
            {"cumulative_reset": cumulative_reset}
            if cumulative_reset is not None
            else {}
        ),
    }


def run_adhoc_ingestion(
    *,
    locator: str,
    dataset_id: str,
    database: str | Path,
    data_root: str | Path,
    allowed_local_roots: Iterable[str | Path] | None,
    parser_parameters: dict[str, Any],
    mapping: AdhocObservationMapping,
    series_record: dict[str, Any],
    timeout: float = 30.0,
    session: Any = None,
    clock: Clock | None = None,
) -> AdhocIngestionSummary:
    """Ingest a generic artifact, register a draft, and publish only to the ad-hoc table."""

    connection, pipeline, wall_clock = _compose_pipeline(
        database=database,
        data_root=data_root,
        connector_factory=GenericTabularConnector,
        parser_factory=GenericTabularParser,
        allowed_local_roots=allowed_local_roots,
        session=session,
        clock=clock,
    )
    try:
        spec = FetchSpec(
            source_id=ADHOC_SOURCE_ID,
            dataset_id=dataset_id,
            locator=locator,
            parameters=parser_parameters,
            timeout=timeout,
            requested_at=wall_clock(),
        )
        results = pipeline.run(spec)
        if len(results) != 1:
            raise ValueError(
                f"generic ingestion returned {len(results)} assets; exactly one is required"
            )
        result = results[0]
        register_series(connection, series_record)
        publication = publish_adhoc_observations(connection, result, [mapping])
        return AdhocIngestionSummary(
            ingestion=_summary(connection, result),
            publication=publication,
        )
    finally:
        connection.close()


__all__ = [
    "AdhocIngestionSummary",
    "BootstrapSummary",
    "IngestionSummary",
    "WindowedIngestionFailure",
    "WindowedIngestionSummary",
    "KNOWN_SOURCES",
    "KnownSourceDefinition",
    "run_adhoc_ingestion",
    "run_bootstrap",
    "run_known_source_ingestion",
    "_adhoc_record",
]
