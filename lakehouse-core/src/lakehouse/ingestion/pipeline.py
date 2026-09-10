"""Generic orchestration from a connector fetch to a Bronze representation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..catalog.artifacts import ArtifactRepository
from ..connectors.base import BaseConnector
from ..contracts.identifiers import new_run_id
from ..contracts.models import FetchedAsset, FetchSpec, ParsedBatch
from ..errors import ErrorPayload, LakehouseError
from ..parsers.base import BaseParser
from ..storage.parquet import ParquetStorage
from .observability import (
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCESS,
    RUN_STATUS_WARNING,
    IngestionWarning,
    RunRepository,
    describe_exception,
)


def _utc_now() -> datetime:
    """Default wall clock for run boundaries."""

    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class IngestionResult:
    """The persisted outputs and provenance of one source asset.

    ``run_id`` closes the provenance chain: a Bronze file leads to the run that produced it,
    the run leads to its ``meta.artifact`` rows and to every ``meta.ingest_warning`` raised
    while parsing them. Every result returned by one ``IngestionPipeline.run`` call carries
    the same ``run_id``.

    The field is last and defaulted so that constructing a result the historical way, with
    the four original arguments, still works.
    """

    asset: FetchedAsset
    parsed_batch: ParsedBatch
    bronze_path: Path
    artifact_inserted: bool
    run_id: str | None = None


@dataclass
class _RunProgress:
    """Mutable bookkeeping for one run, shared between the loop and the recorder."""

    run_id: str
    rows_out: int = 0
    warning_count: int = 0


@dataclass(frozen=True)
class IngestionPipeline:
    """Connect source access, artifact registration, parsing and Bronze storage.

    **Run tracking is always on.** Every ``run`` call opens a ``meta.run`` row, persists
    every parser warning into ``meta.ingest_warning``, and closes the run as ``success``,
    ``warning`` or ``failed``. There is no configuration that turns this off: parser
    warnings describe real data-quality problems, and a pipeline that silently discards them
    is the defect this layer exists to remove.

    ``run_repository`` exists for dependency injection only. When it is not supplied the
    pipeline builds one over the ``ArtifactRepository`` connection, which is already a
    bootstrapped trusted DuckDB connection, so the four historical constructor arguments are
    enough to get full observability with no extra wiring:

    ``IngestionPipeline(connector=..., parser=..., artifact_repository=..., parquet_storage=...)``

    Keeping run bookkeeping in its own small class rather than folding it into
    ``ArtifactRepository`` keeps artifact registration a single concern; sharing one
    connection between the two is expected.
    """

    connector: BaseConnector
    parser: BaseParser
    artifact_repository: ArtifactRepository
    parquet_storage: ParquetStorage
    run_repository: RunRepository | None = None
    clock: Callable[[], datetime] = _utc_now

    def __post_init__(self) -> None:
        """Resolve the run repository so ``run_repository`` is never None after init."""

        if self.run_repository is None:
            object.__setattr__(
                self, "run_repository", RunRepository(self.artifact_repository.connection)
            )

    def run(self, spec: FetchSpec) -> list[IngestionResult]:
        """Run one FetchSpec and return one result for each fetched asset.

        When run tracking is enabled the run is closed exactly once. A failure closes it as
        ``failed`` and then re-raises the original exception untouched, so callers and their
        error handling are unaffected by the bookkeeping.
        """

        progress = _RunProgress(run_id=self._open_run(spec))
        try:
            results = self._ingest(spec, progress)
        except Exception as exception:
            self._close_failed_run(progress, exception)
            raise
        self._close_completed_run(progress)
        return results

    # ------------------------------------------------------------------ ingest

    def _ingest(self, spec: FetchSpec, progress: _RunProgress) -> list[IngestionResult]:
        """The unchanged source-to-Bronze sequence, instrumented but not reordered."""

        assets = self.connector.fetch(spec)
        if not assets:
            raise LakehouseError(
                ErrorPayload(
                    error_code="EMPTY_DATASET",
                    message="connector returned no assets",
                    source_id=spec.source_id,
                    dataset_id=spec.dataset_id,
                    retryable=False,
                )
            )

        results: list[IngestionResult] = []
        for asset in assets:
            self._validate_asset(spec, asset)
            artifact_inserted = self.artifact_repository.register(asset)
            parsed_batch = self.parser.parse(asset)
            self._validate_batch(asset, parsed_batch)
            # Warnings are stored before the Bronze write so that a write failure still
            # leaves behind what the parser managed to tell us about this artifact.
            self._record_warnings(progress, asset, parsed_batch)
            bronze_path = self.parquet_storage.write(parsed_batch)
            progress.rows_out += len(parsed_batch.dataframe)
            results.append(
                IngestionResult(
                    asset=asset,
                    parsed_batch=parsed_batch,
                    bronze_path=bronze_path,
                    artifact_inserted=artifact_inserted,
                    run_id=progress.run_id,
                )
            )
        return results

    # ----------------------------------------------------------- run recording

    def _now(self) -> datetime:
        """Read the injected clock and require a timezone-aware value."""

        moment = self.clock()
        if not isinstance(moment, datetime):
            raise TypeError("ingestion clock must return a datetime")
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("ingestion clock must return a timezone-aware datetime")
        return moment.astimezone(timezone.utc)

    def _open_run(self, spec: FetchSpec) -> str:
        """Open a ``running`` row and return its canonical run_id."""

        assert self.run_repository is not None  # guaranteed by __post_init__
        return self.run_repository.start(
            run_id=new_run_id(),
            source_id=spec.source_id,
            dataset_id=spec.dataset_id,
            started_at=self._now(),
        )

    def _record_warnings(
        self, progress: _RunProgress, asset: FetchedAsset, batch: ParsedBatch
    ) -> None:
        """Persist this batch's warnings verbatim, numbered deterministically."""

        assert self.run_repository is not None  # guaranteed by __post_init__
        if not batch.warnings:
            return
        records = []
        for message in batch.warnings:
            progress.warning_count += 1
            records.append(
                IngestionWarning(
                    run_id=progress.run_id,
                    warning_seq=progress.warning_count,
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    artifact_sha256=asset.artifact_sha256,
                    message=message,
                )
            )
        self.run_repository.record_warnings(records, created_at=self._now())

    def _close_completed_run(self, progress: _RunProgress) -> None:
        """Close a run that finished. Bookkeeping failures here are not swallowed."""

        assert self.run_repository is not None  # guaranteed by __post_init__
        status = RUN_STATUS_WARNING if progress.warning_count else RUN_STATUS_SUCCESS
        self.run_repository.finish(
            run_id=progress.run_id,
            status=status,
            ended_at=self._now(),
            rows_out=progress.rows_out,
        )

    def _close_failed_run(self, progress: _RunProgress, exception: Exception) -> None:
        """Close a failed run without ever masking the exception being propagated.

        Recording is best-effort here on purpose: if the database itself is what broke, the
        caller must still see the original failure rather than a secondary bookkeeping
        error. The stored text is redacted and length-bounded by ``describe_exception``.
        """

        assert self.run_repository is not None  # guaranteed by __post_init__
        try:
            self.run_repository.finish(
                run_id=progress.run_id,
                status=RUN_STATUS_FAILED,
                ended_at=self._now(),
                rows_out=progress.rows_out,
                error=describe_exception(exception),
            )
        except Exception:  # noqa: BLE001 - never replace the original failure
            pass

    @staticmethod
    def _validate_asset(spec: FetchSpec, asset: FetchedAsset) -> None:
        if asset.source_id != spec.source_id:
            raise LakehouseError(
                ErrorPayload(
                    error_code="SCHEMA_MISMATCH",
                    message=(
                        "FetchSpec/FetchedAsset source_id mismatch: "
                        f"expected {spec.source_id!r}, got {asset.source_id!r}"
                    ),
                    source_id=spec.source_id,
                    dataset_id=spec.dataset_id,
                    retryable=False,
                )
            )
        if asset.dataset_id != spec.dataset_id:
            raise LakehouseError(
                ErrorPayload(
                    error_code="SCHEMA_MISMATCH",
                    message=(
                        "FetchSpec/FetchedAsset dataset_id mismatch: "
                        f"expected {spec.dataset_id!r}, got {asset.dataset_id!r}"
                    ),
                    source_id=spec.source_id,
                    dataset_id=spec.dataset_id,
                    retryable=False,
                )
            )

    @staticmethod
    def _validate_batch(asset: FetchedAsset, batch: ParsedBatch) -> None:
        if batch.source_id != asset.source_id:
            raise LakehouseError(
                ErrorPayload(
                    error_code="SCHEMA_MISMATCH",
                    message=(
                        "FetchedAsset/ParsedBatch source_id mismatch: "
                        f"expected {asset.source_id!r}, got {batch.source_id!r}"
                    ),
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=False,
                )
            )
        if batch.dataset_id != asset.dataset_id:
            raise LakehouseError(
                ErrorPayload(
                    error_code="SCHEMA_MISMATCH",
                    message=(
                        "FetchedAsset/ParsedBatch dataset_id mismatch: "
                        f"expected {asset.dataset_id!r}, got {batch.dataset_id!r}"
                    ),
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=False,
                )
            )
        if batch.artifact_sha256 != asset.artifact_sha256:
            raise LakehouseError(
                ErrorPayload(
                    error_code="SCHEMA_MISMATCH",
                    message=(
                        "FetchedAsset/ParsedBatch artifact_sha256 mismatch: "
                        f"expected {asset.artifact_sha256!r}, got {batch.artifact_sha256!r}"
                    ),
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=False,
                )
            )


__all__ = ["IngestionPipeline", "IngestionResult", "RunRepository"]
