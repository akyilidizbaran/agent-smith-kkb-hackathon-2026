"""End-to-end run tracking through IngestionPipeline, without touching the network.

Every test drives the real pipeline, the real artifact repository, the real Parquet storage
and a real DuckDB database. Only the connector and parser are stubs, because the point here
is the bookkeeping around them, not source behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import pandas as pd
import pytest

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.base import BaseConnector
from src.lakehouse.contracts.models import FetchedAsset, FetchSpec, ParsedBatch
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.errors import ErrorPayload, LakehouseError
from src.lakehouse.ingestion.observability import (
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCESS,
    RUN_STATUS_WARNING,
    RunRepository,
)
from src.lakehouse.ingestion.pipeline import IngestionPipeline, IngestionResult
from src.lakehouse.storage.parquet import ParquetStorage
from src.lakehouse.storage.raw import sha256_bytes


SOURCE_ID = "fake_source"
DATASET_ID = "fake_dataset"
FETCHED_AT = datetime(2026, 9, 10, 5, 0, tzinfo=timezone.utc)
RUN_START = datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc)


class _Clock:
    """Deterministic, strictly increasing UTC clock."""

    def __init__(self, start: datetime = RUN_START) -> None:
        self._moments: Iterator[datetime] = iter(
            start + timedelta(seconds=index) for index in range(1_000)
        )
        self.readings: list[datetime] = []

    def __call__(self) -> datetime:
        moment = next(self._moments)
        self.readings.append(moment)
        return moment


class ListConnector(BaseConnector):
    def __init__(self, assets: list[FetchedAsset]) -> None:
        self._assets = assets

    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        return list(self._assets)


class FailingConnector(BaseConnector):
    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        raise LakehouseError(
            ErrorPayload(
                error_code="SOURCE_UNAVAILABLE",
                message="request failed for https://example.invalid/x?key=LIVE-SECRET",
                source_id=spec.source_id,
                dataset_id=spec.dataset_id,
                retryable=True,
            )
        )


class MappingParser:
    """Return a prepared ParsedBatch per artifact digest."""

    def __init__(self, batches: dict[str, ParsedBatch]) -> None:
        self._batches = batches

    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        return self._batches[asset.artifact_sha256]


class FailingParser:
    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        raise LakehouseError(
            ErrorPayload(
                error_code="PARSE_FAILED",
                message="artifact is not valid JSON",
                source_id=asset.source_id,
                dataset_id=asset.dataset_id,
                retryable=False,
            )
        )


class FailingParquetStorage:
    def write(self, batch: ParsedBatch) -> Path:
        raise OSError("no space left on device")


def _asset(tmp_path: Path, payload: bytes) -> FetchedAsset:
    path = tmp_path / f"{sha256_bytes(payload)}.json"
    path.write_bytes(payload)
    return FetchedAsset(
        source_id=SOURCE_ID,
        dataset_id=DATASET_ID,
        locator="fixture://artifact.json",
        media_type="application/json",
        byte_size=len(payload),
        fetched_at=FETCHED_AT,
        artifact_sha256=sha256_bytes(payload),
        raw_path=path,
        http_status=200,
    )


def _batch(asset: FetchedAsset, *, rows: int = 2, warnings: list[str] | None = None) -> ParsedBatch:
    return ParsedBatch(
        source_id=asset.source_id,
        dataset_id=asset.dataset_id,
        artifact_sha256=asset.artifact_sha256,
        schema_version="fixture-v1",
        dataframe=pd.DataFrame({"value": list(range(rows))}),
        warnings=list(warnings or []),
    )


def _spec() -> FetchSpec:
    return FetchSpec(source_id=SOURCE_ID, dataset_id=DATASET_ID, locator="fixture://spec")


class NoOpRunRepositoryForComparisonOnly:
    """Explicitly named test double that records nothing.

    It exists for exactly one test: proving that the RAW/Bronze output of a run is identical
    whether or not bookkeeping happened. There is deliberately no production way to disable
    observability, so a comparison baseline has to be built here.
    """

    def start(self, *, run_id: str, source_id: str, dataset_id: str, started_at) -> str:
        return run_id

    def record_warnings(self, warnings, *, created_at) -> None:
        return None

    def finish(self, *, run_id, status, ended_at, rows_out=None, error=None) -> None:
        return None


def _pipeline(
    tmp_path: Path,
    connector,
    parser,
    *,
    parquet_storage=None,
    clock: _Clock | None = None,
    run_repository=None,
) -> IngestionPipeline:
    """Build a pipeline the way production would: observability is on by default."""

    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    return IngestionPipeline(
        connector=connector,
        parser=parser,
        artifact_repository=ArtifactRepository(connection),
        parquet_storage=parquet_storage or ParquetStorage(tmp_path / "data/bronze"),
        run_repository=run_repository,
        clock=clock or _Clock(),
    )


def _epoch(moment: datetime) -> int:
    """Millisecond epoch, matching DuckDB's ``epoch_ms``."""

    return int(moment.timestamp() * 1000)


def _runs(pipeline: IngestionPipeline) -> list[tuple]:
    # TIMESTAMPTZ values come back as epoch milliseconds, the convention this repository
    # already uses: materializing one as a Python datetime would require pytz, which is not
    # a project dependency.
    return pipeline.artifact_repository.connection.execute(
        """
        SELECT run_id, epoch_ms(started_at), epoch_ms(ended_at), status,
               rows_in, rows_out, error, source_id, dataset_id
        FROM meta.run
        """
    ).fetchall()


def _warnings(pipeline: IngestionPipeline) -> list[tuple]:
    return pipeline.artifact_repository.connection.execute(
        """
        SELECT run_id, warning_seq, source_id, dataset_id, artifact_sha256, message,
               epoch_ms(created_at)
        FROM meta.ingest_warning ORDER BY warning_seq
        """
    ).fetchall()


# ------------------------------------------------------- completed run states


def test_clean_ingestion_records_a_success_run(tmp_path: Path) -> None:
    """Acceptance criterion 1."""

    asset = _asset(tmp_path, b"clean")
    pipeline = _pipeline(
        tmp_path, ListConnector([asset]), MappingParser({asset.artifact_sha256: _batch(asset)})
    )
    try:
        results = pipeline.run(_spec())

        runs = _runs(pipeline)
        assert len(runs) == 1
        run_id, started_at, ended_at, status, rows_in, rows_out, error, source, dataset = runs[0]
        assert status == RUN_STATUS_SUCCESS
        assert error is None
        assert rows_in is None  # bytes in, not rows: never invented
        assert rows_out == 2
        assert (source, dataset) == (SOURCE_ID, DATASET_ID)
        assert started_at < ended_at
        assert _warnings(pipeline) == []
        assert len(results) == 1
    finally:
        pipeline.artifact_repository.connection.close()


def test_parser_warnings_downgrade_the_run_to_warning(tmp_path: Path) -> None:
    """Acceptance criteria 2 and 7."""

    message = (
        "1000 observations reached the EVDS per-request limit of 1000; the response may be "
        "silently truncated and the request range should be windowed"
    )
    asset = _asset(tmp_path, b"warned")
    pipeline = _pipeline(
        tmp_path,
        ListConnector([asset]),
        MappingParser({asset.artifact_sha256: _batch(asset, warnings=[message])}),
    )
    try:
        pipeline.run(_spec())

        run = _runs(pipeline)[0]
        assert run[3] == RUN_STATUS_WARNING
        assert run[5] == 2

        warnings = _warnings(pipeline)
        assert len(warnings) == 1
        assert warnings[0][0] == run[0]
        assert warnings[0][1] == 1
        assert warnings[0][4] == asset.artifact_sha256
        # Stored verbatim: no truncation, no reformatting, no invented error code.
        assert warnings[0][5] == message
    finally:
        pipeline.artifact_repository.connection.close()


def test_multiple_assets_and_warnings_share_one_run_with_stable_sequence(
    tmp_path: Path,
) -> None:
    """Acceptance criterion 3."""

    first = _asset(tmp_path, b"first")
    second = _asset(tmp_path, b"second")
    pipeline = _pipeline(
        tmp_path,
        ListConnector([first, second]),
        MappingParser(
            {
                first.artifact_sha256: _batch(first, rows=2, warnings=["first-a", "first-b"]),
                second.artifact_sha256: _batch(second, rows=3, warnings=["second-a"]),
            }
        ),
    )
    try:
        pipeline.run(_spec())

        runs = _runs(pipeline)
        assert len(runs) == 1
        run_id = runs[0][0]
        assert runs[0][3] == RUN_STATUS_WARNING
        assert runs[0][5] == 5  # 2 + 3 Bronze rows

        warnings = _warnings(pipeline)
        assert [row[1] for row in warnings] == [1, 2, 3]
        assert [row[5] for row in warnings] == ["first-a", "first-b", "second-a"]
        assert {row[0] for row in warnings} == {run_id}
        # Each warning stays attached to the artifact that produced it.
        assert [row[4] for row in warnings] == [
            first.artifact_sha256,
            first.artifact_sha256,
            second.artifact_sha256,
        ]
    finally:
        pipeline.artifact_repository.connection.close()


# ----------------------------------------------------------- failure closures


def test_connector_failure_closes_the_run_and_reraises(tmp_path: Path) -> None:
    """Acceptance criteria 4 and 8."""

    pipeline = _pipeline(tmp_path, FailingConnector(), MappingParser({}))
    try:
        with pytest.raises(LakehouseError) as excinfo:
            pipeline.run(_spec())
        assert excinfo.value.payload.error_code == "SOURCE_UNAVAILABLE"

        run = _runs(pipeline)[0]
        assert run[3] == RUN_STATUS_FAILED
        assert run[2] is not None  # ended_at populated
        assert run[5] == 0  # nothing reached Bronze
        assert "SOURCE_UNAVAILABLE" in run[6]
        assert "LIVE-SECRET" not in run[6]
        assert "example.invalid" in run[6]  # host survives, credential does not
    finally:
        pipeline.artifact_repository.connection.close()


def test_empty_connector_result_closes_the_run_as_failed(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path, ListConnector([]), MappingParser({}))
    try:
        with pytest.raises(LakehouseError) as excinfo:
            pipeline.run(_spec())
        assert excinfo.value.payload.error_code == "EMPTY_DATASET"

        run = _runs(pipeline)[0]
        assert run[3] == RUN_STATUS_FAILED
        assert "EMPTY_DATASET" in run[6]
    finally:
        pipeline.artifact_repository.connection.close()


def test_parser_failure_closes_the_run_as_failed(tmp_path: Path) -> None:
    """Acceptance criterion 5."""

    asset = _asset(tmp_path, b"unparseable")
    pipeline = _pipeline(tmp_path, ListConnector([asset]), FailingParser())
    try:
        with pytest.raises(LakehouseError) as excinfo:
            pipeline.run(_spec())
        assert excinfo.value.payload.error_code == "PARSE_FAILED"

        run = _runs(pipeline)[0]
        assert run[3] == RUN_STATUS_FAILED
        assert run[2] is not None
        assert "PARSE_FAILED" in run[6]
        # The artifact was registered before parsing, so RAW bookkeeping is unaffected.
        assert pipeline.artifact_repository.connection.execute(
            "SELECT count(*) FROM meta.artifact"
        ).fetchone() == (1,)
    finally:
        pipeline.artifact_repository.connection.close()


def test_bronze_write_failure_closes_the_run_as_failed(tmp_path: Path) -> None:
    """Acceptance criterion 6."""

    asset = _asset(tmp_path, b"unwritable")
    pipeline = _pipeline(
        tmp_path,
        ListConnector([asset]),
        MappingParser({asset.artifact_sha256: _batch(asset, warnings=["seen before the write"])}),
        parquet_storage=FailingParquetStorage(),
    )
    try:
        with pytest.raises(OSError, match="no space left"):
            pipeline.run(_spec())

        run = _runs(pipeline)[0]
        assert run[3] == RUN_STATUS_FAILED
        assert run[5] == 0  # the write never completed
        assert "OSError" in run[6]

        # The warning was persisted before the failing write, so it is not lost.
        warnings = _warnings(pipeline)
        assert [row[5] for row in warnings] == ["seen before the write"]
    finally:
        pipeline.artifact_repository.connection.close()


def test_partial_progress_is_kept_when_a_later_asset_fails(tmp_path: Path) -> None:
    first = _asset(tmp_path, b"good")
    second = _asset(tmp_path, b"bad")

    class SecondAssetFails:
        def parse(self, asset: FetchedAsset) -> ParsedBatch:
            if asset.artifact_sha256 == first.artifact_sha256:
                return _batch(first, rows=4, warnings=["first asset warned"])
            raise RuntimeError("second asset exploded")

    pipeline = _pipeline(tmp_path, ListConnector([first, second]), SecondAssetFails())
    try:
        with pytest.raises(RuntimeError, match="exploded"):
            pipeline.run(_spec())

        run = _runs(pipeline)[0]
        assert run[3] == RUN_STATUS_FAILED
        assert run[5] == 4  # the first asset's rows really are in Bronze
        assert [row[5] for row in _warnings(pipeline)] == ["first asset warned"]
    finally:
        pipeline.artifact_repository.connection.close()


# ------------------------------------------------------- determinism and time


def test_run_timestamps_are_utc_and_come_from_the_injected_clock(tmp_path: Path) -> None:
    """Acceptance criterion 9."""

    clock = _Clock()
    asset = _asset(tmp_path, b"timed")
    pipeline = _pipeline(
        tmp_path,
        ListConnector([asset]),
        MappingParser({asset.artifact_sha256: _batch(asset, warnings=["w"])}),
        clock=clock,
    )
    try:
        pipeline.run(_spec())

        run = _runs(pipeline)[0]
        assert run[1] == _epoch(clock.readings[0])
        assert run[2] == _epoch(clock.readings[-1])
        assert _warnings(pipeline)[0][6] == _epoch(clock.readings[1])

        # The columns really are timezone-aware, so the stored epoch is unambiguous.
        types = dict(
            pipeline.artifact_repository.connection.execute(
                """
                SELECT column_name, data_type FROM information_schema.columns
                WHERE table_schema = 'meta' AND table_name = 'run'
                """
            ).fetchall()
        )
        assert types["started_at"].upper().startswith("TIMESTAMP WITH TIME ZONE")
    finally:
        pipeline.artifact_repository.connection.close()


def test_a_clock_returning_naive_time_is_rejected(tmp_path: Path) -> None:
    asset = _asset(tmp_path, b"naive")
    pipeline = _pipeline(
        tmp_path,
        ListConnector([asset]),
        MappingParser({asset.artifact_sha256: _batch(asset)}),
        clock=lambda: datetime(2026, 9, 10, 6, 0),
    )
    try:
        with pytest.raises(ValueError, match="timezone-aware"):
            pipeline.run(_spec())
    finally:
        pipeline.artifact_repository.connection.close()


def test_each_run_gets_a_distinct_run_id(tmp_path: Path) -> None:
    asset = _asset(tmp_path, b"repeat")
    pipeline = _pipeline(
        tmp_path, ListConnector([asset]), MappingParser({asset.artifact_sha256: _batch(asset)})
    )
    try:
        pipeline.run(_spec())
        pipeline.run(_spec())
        run_ids = {row[0] for row in _runs(pipeline)}
        assert len(run_ids) == 2
    finally:
        pipeline.artifact_repository.connection.close()


# --------------------------------------------------------- backward behaviour


def test_tracking_does_not_change_the_result_or_the_bronze_bytes(tmp_path: Path) -> None:
    """Acceptance criterion 10, part two: RAW/Bronze output is identical either way."""

    payload = b"comparable"
    outputs = {}
    baselines = {
        "recording": None,  # default: the real RunRepository is created automatically
        "not_recording": NoOpRunRepositoryForComparisonOnly(),
    }
    for label, repository in baselines.items():
        root = tmp_path / label
        raw_root = root / "raw"
        raw_root.mkdir(parents=True)
        asset = _asset(raw_root, payload)
        pipeline = _pipeline(
            root,
            ListConnector([asset]),
            MappingParser({asset.artifact_sha256: _batch(asset, rows=3, warnings=["w1"])}),
            run_repository=repository,
        )
        try:
            results = pipeline.run(_spec())
        finally:
            pipeline.artifact_repository.connection.close()
        outputs[label] = (
            results[0].asset.artifact_sha256,
            results[0].bronze_path.relative_to(root).as_posix(),
            results[0].artifact_inserted,
            list(results[0].parsed_batch.warnings),
            results[0].bronze_path.read_bytes(),
        )

    assert outputs["recording"] == outputs["not_recording"]


def test_four_argument_constructor_records_runs_by_default(tmp_path: Path) -> None:
    """Acceptance criteria 1 and 2: the historical call site now gets full observability.

    No RunRepository, no clock, no extra wiring: exactly the four arguments every existing
    call site already passes.
    """

    message = "5 periods returned but 66 were requested"
    asset = _asset(tmp_path, b"legacy")
    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    pipeline = IngestionPipeline(
        connector=ListConnector([asset]),
        parser=MappingParser({asset.artifact_sha256: _batch(asset, warnings=[message])}),
        artifact_repository=ArtifactRepository(connection),
        parquet_storage=ParquetStorage(tmp_path / "data/bronze"),
    )
    try:
        assert isinstance(pipeline.run_repository, RunRepository)

        results = pipeline.run(_spec())

        runs = _runs(pipeline)
        assert len(runs) == 1
        assert runs[0][3] == RUN_STATUS_WARNING
        assert (runs[0][7], runs[0][8]) == (SOURCE_ID, DATASET_ID)

        warnings = _warnings(pipeline)
        assert [row[5] for row in warnings] == [message]
        assert warnings[0][0] == runs[0][0]
        assert results[0].run_id == runs[0][0]
    finally:
        connection.close()


def test_default_pipeline_shares_the_artifact_repository_connection(tmp_path: Path) -> None:
    """The auto-created repository reuses the already-bootstrapped trusted connection."""

    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    pipeline = IngestionPipeline(
        connector=ListConnector([]),
        parser=MappingParser({}),
        artifact_repository=ArtifactRepository(connection),
        parquet_storage=ParquetStorage(tmp_path / "data/bronze"),
    )
    try:
        assert pipeline.run_repository.connection is connection
    finally:
        connection.close()


def test_an_injected_run_repository_is_used_instead_of_the_default(tmp_path: Path) -> None:
    """Dependency injection still works; None means "build one", never "turn it off"."""

    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    injected = RunRepository(connection)
    pipeline = IngestionPipeline(
        connector=ListConnector([]),
        parser=MappingParser({}),
        artifact_repository=ArtifactRepository(connection),
        parquet_storage=ParquetStorage(tmp_path / "data/bronze"),
        run_repository=injected,
    )
    try:
        assert pipeline.run_repository is injected
    finally:
        connection.close()


# ------------------------------------------------------------- run_id on results


def test_every_result_of_one_call_carries_the_same_run_id(tmp_path: Path) -> None:
    """Acceptance criterion 3."""

    first = _asset(tmp_path, b"first")
    second = _asset(tmp_path, b"second")
    third = _asset(tmp_path, b"third")
    pipeline = _pipeline(
        tmp_path,
        ListConnector([first, second, third]),
        MappingParser(
            {
                first.artifact_sha256: _batch(first),
                second.artifact_sha256: _batch(second, warnings=["w"]),
                third.artifact_sha256: _batch(third),
            }
        ),
    )
    try:
        results = pipeline.run(_spec())

        run_ids = {result.run_id for result in results}
        assert len(results) == 3
        assert len(run_ids) == 1

        run_id = run_ids.pop()
        assert run_id is not None
        assert run_id == _runs(pipeline)[0][0]
        # The chain Bronze -> run -> warning is now walkable from a result alone.
        assert {row[0] for row in _warnings(pipeline)} == {run_id}
    finally:
        pipeline.artifact_repository.connection.close()


def test_separate_calls_carry_different_run_ids_on_their_results(tmp_path: Path) -> None:
    asset = _asset(tmp_path, b"twice")
    pipeline = _pipeline(
        tmp_path, ListConnector([asset]), MappingParser({asset.artifact_sha256: _batch(asset)})
    )
    try:
        first = pipeline.run(_spec())[0].run_id
        second = pipeline.run(_spec())[0].run_id
        assert first is not None and second is not None and first != second
    finally:
        pipeline.artifact_repository.connection.close()


def test_ingestion_result_still_accepts_the_four_historical_arguments(tmp_path: Path) -> None:
    """run_id is additive: it is last and defaulted, so old construction keeps working."""

    asset = _asset(tmp_path, b"shape")
    result = IngestionResult(
        asset=asset,
        parsed_batch=_batch(asset),
        bronze_path=tmp_path / "x.parquet",
        artifact_inserted=True,
    )
    assert result.run_id is None
