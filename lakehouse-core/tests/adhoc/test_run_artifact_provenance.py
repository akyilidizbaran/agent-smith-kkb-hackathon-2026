"""Run-artifact provenance: every fetched artifact is durably bound to the run that fetched it.

The independent counter-tests showed two gaps in publication: a forged ``asset.fetched_at``
was published unchallenged, and the ``run_id`` of *another* successful run over the same
source/dataset was accepted for an unrelated artifact. Both exist because ``meta.run`` only
recorded source/dataset, never which artifacts a run actually fetched. ``meta.run_artifact``
closes that gap and these tests pin its contract. Every file here is SYNTHETIC.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import duckdb
import pandas as pd
import pytest

from src.lakehouse.adhoc import AdhocPublicationError, publish_adhoc_observations
from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.base import BaseConnector
from src.lakehouse.contracts.models import FetchedAsset, FetchSpec, ParsedBatch
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.errors import ErrorPayload, LakehouseError
from src.lakehouse.ingestion.observability import (
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCESS,
    RunRepository,
)
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.storage.parquet import ParquetStorage
from src.lakehouse.storage.raw import sha256_bytes

from tests.adhoc.test_publication import _mapping, _prepare, _rows
from tests.generic._support import FETCHED_AT, ingest, spec, write_bytes, write_csv, xlsx_bytes


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
DATASET_ID = "adhoc_synthetic"
CSV = "donem,deger\n2026-01-31,10.5\n"


def _us(moment: datetime) -> int:
    """Exact microsecond epoch, matching DuckDB's ``epoch_us``."""

    return (moment.astimezone(timezone.utc) - _EPOCH) // timedelta(microseconds=1)


def _links(connection) -> list[tuple]:
    return connection.execute(
        """
        SELECT run_id, artifact_sha256, source_id, dataset_id, epoch_us(fetched_at),
               parser_config_sha256
        FROM meta.run_artifact ORDER BY run_id, artifact_sha256
        """
    ).fetchall()


def _run_status(connection, run_id: str) -> str:
    return connection.execute(
        "SELECT status FROM meta.run WHERE run_id = ?", [run_id]
    ).fetchone()[0]


def _link_for(result) -> tuple:
    return (
        result.run_id,
        result.asset.artifact_sha256,
        "adhoc",
        DATASET_ID,
        _us(FETCHED_AT),
        result.parsed_batch.parser_config_sha256,
    )


# --------------------------------------------------------------- stub pipeline


class _ListConnector(BaseConnector):
    def __init__(self, assets: list[FetchedAsset]) -> None:
        self._assets = assets

    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        return list(self._assets)


class _FailingParser:
    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        raise LakehouseError(
            ErrorPayload(
                error_code="PARSE_FAILED",
                message="SYNTHETIC parse failure after the artifact was registered",
                source_id=asset.source_id,
                dataset_id=asset.dataset_id,
                retryable=False,
            )
        )


class _PassthroughParser:
    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        return ParsedBatch(
            source_id=asset.source_id,
            dataset_id=asset.dataset_id,
            artifact_sha256=asset.artifact_sha256,
            schema_version="stub-v1",
            dataframe=pd.DataFrame({"value": [1]}),
        )


class _FailingParquetStorage:
    def write(self, batch: ParsedBatch) -> Path:
        raise OSError("SYNTHETIC: no space left on device")


def _adhoc_asset(
    tmp_path: Path,
    payload: bytes,
    *,
    source_id: str = "adhoc",
    dataset_id: str = DATASET_ID,
    fetched_at: datetime = FETCHED_AT,
) -> FetchedAsset:
    path = tmp_path / f"{sha256_bytes(payload)}.bin"
    path.write_bytes(payload)
    return FetchedAsset(
        source_id=source_id,
        dataset_id=dataset_id,
        locator="fixture://synthetic.bin",
        media_type="application/octet-stream",
        byte_size=len(payload),
        fetched_at=fetched_at,
        artifact_sha256=sha256_bytes(payload),
        raw_path=path,
        http_status=200,
    )


def _stub_pipeline(tmp_path: Path, connection, connector, parser, *, parquet_storage=None):
    return IngestionPipeline(
        connector=connector,
        parser=parser,
        artifact_repository=ArtifactRepository(connection),
        parquet_storage=parquet_storage or ParquetStorage(tmp_path / "data/bronze"),
    )


def _adhoc_spec() -> FetchSpec:
    return FetchSpec(source_id="adhoc", dataset_id=DATASET_ID, locator="fixture://spec")


# ------------------------------------------- 1. forged fetched_at is refused


@pytest.mark.parametrize(
    "delta",
    [timedelta(days=1), timedelta(microseconds=1), timedelta(days=-400)],
    ids=["one-day-later", "one-microsecond-later", "long-before"],
)
def test_01_forged_asset_fetched_at_is_refused(tmp_path: Path, delta: timedelta) -> None:
    connection, result = _prepare(tmp_path, CSV)
    try:
        forged = replace(result, asset=replace(result.asset, fetched_at=FETCHED_AT + delta))
        with pytest.raises(AdhocPublicationError, match="fetched_at"):
            publish_adhoc_observations(connection, forged, [_mapping()])
        assert _rows(connection) == []
    finally:
        connection.close()


def test_01_published_fetched_at_comes_from_the_durable_link(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, CSV)
    try:
        publish_adhoc_observations(connection, result, [_mapping()])
        durable = connection.execute(
            "SELECT epoch_us(fetched_at) FROM meta.run_artifact "
            "WHERE run_id = ? AND artifact_sha256 = ?",
            [result.run_id, result.asset.artifact_sha256],
        ).fetchone()
        published = connection.execute(
            "SELECT DISTINCT epoch_us(fetched_at) FROM adhoc.fact_observation"
        ).fetchall()
        assert durable == (_us(FETCHED_AT),)
        assert published == [durable]
    finally:
        connection.close()


# ----------------------------- 2. another successful run's identity is refused


def test_02_another_successful_run_of_the_same_dataset_is_refused(tmp_path: Path) -> None:
    connection, a = _prepare(tmp_path, CSV)
    try:
        path = write_csv(tmp_path / "uploads", "b.csv", "donem,deger\n2026-01-31,999\n")
        _, b = ingest(
            tmp_path, spec(str(path)), allowed_local_roots=[tmp_path], connection=connection
        )
        # Both runs are genuine, successful and cover the same source/dataset: the only
        # thing wrong with the swap is that run B never fetched artifact A.
        assert a.run_id != b.run_id
        assert _run_status(connection, b.run_id) == RUN_STATUS_SUCCESS
        assert connection.execute(
            "SELECT source_id, dataset_id FROM meta.run WHERE run_id = ?", [b.run_id]
        ).fetchone() == ("adhoc", DATASET_ID)

        with pytest.raises(AdhocPublicationError, match="run"):
            publish_adhoc_observations(connection, replace(a, run_id=b.run_id), [_mapping()])
        with pytest.raises(AdhocPublicationError, match="run"):
            publish_adhoc_observations(connection, replace(b, run_id=a.run_id), [_mapping()])
        assert _rows(connection) == []
    finally:
        connection.close()


# ------------------------------------------ 3. the correct link is accepted


def test_03_correct_run_artifact_link_is_accepted(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, CSV)
    try:
        assert _links(connection) == [_link_for(result)]
        published = publish_adhoc_observations(connection, result, [_mapping()])
        assert published.rows_written == 1
        assert connection.execute(
            "SELECT run_id, artifact_sha256, source_id, dataset_id, epoch_us(fetched_at) "
            "FROM adhoc.fact_observation"
        ).fetchall() == [
            (result.run_id, result.asset.artifact_sha256, "adhoc", DATASET_ID, _us(FETCHED_AT))
        ]
    finally:
        connection.close()


def test_03_both_runs_over_the_same_bytes_are_publishable(tmp_path: Path) -> None:
    """A re-run is a new run over the same artifact: two links, one artifact, both valid."""

    connection, first = _prepare(tmp_path, CSV)
    try:
        _, second = ingest(
            tmp_path,
            spec(str(tmp_path / "uploads" / "synthetic.csv")),
            allowed_local_roots=[tmp_path / "uploads"],
            connection=connection,
        )
        assert second.asset.artifact_sha256 == first.asset.artifact_sha256
        assert second.run_id != first.run_id
        assert _links(connection) == sorted([_link_for(first), _link_for(second)])
        assert connection.execute("SELECT count(*) FROM meta.artifact").fetchone() == (1,)

        publish_adhoc_observations(connection, first, [_mapping()])
        republished = publish_adhoc_observations(connection, second, [_mapping()])
        assert republished.rows_written == 0
        assert republished.rows_unchanged == 1
    finally:
        connection.close()


# ------------------- 4. a later failure keeps the link and fails the run


@pytest.mark.parametrize("failure", ["parser", "bronze_write"])
def test_04_download_stays_linked_when_a_later_step_fails(tmp_path: Path, failure: str) -> None:
    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    try:
        asset = _adhoc_asset(tmp_path, b"SYNTHETIC bytes that were really downloaded")
        if failure == "parser":
            pipeline = _stub_pipeline(tmp_path, connection, _ListConnector([asset]), _FailingParser())
            expected = LakehouseError
        else:
            pipeline = _stub_pipeline(
                tmp_path,
                connection,
                _ListConnector([asset]),
                _PassthroughParser(),
                parquet_storage=_FailingParquetStorage(),
            )
            expected = OSError

        with pytest.raises(expected):
            pipeline.run(_adhoc_spec())

        run_id, status = connection.execute("SELECT run_id, status FROM meta.run").fetchone()
        assert status == RUN_STATUS_FAILED
        assert _links(connection) == [
            (run_id, asset.artifact_sha256, "adhoc", DATASET_ID, _us(FETCHED_AT), None)
        ]
    finally:
        connection.close()


def test_04_generic_parser_refusal_keeps_the_link(tmp_path: Path) -> None:
    """The real connector and parser: a formula workbook is registered, then refused."""

    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    try:
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        workbook = write_bytes(
            uploads,
            "formula.xlsx",
            xlsx_bytes({"Sheet1": [["donem", "deger"], ["2026-01-31", "=1+1"]]}),
        )
        with pytest.raises(LakehouseError):
            ingest(tmp_path, spec(str(workbook)), allowed_local_roots=[uploads], connection=connection)

        run_id, status = connection.execute("SELECT run_id, status FROM meta.run").fetchone()
        assert status == RUN_STATUS_FAILED
        digest = sha256_bytes(workbook.read_bytes())
        (artifact_digest,) = connection.execute(
            "SELECT artifact_sha256 FROM meta.artifact"
        ).fetchone()
        assert artifact_digest == digest
        links = _links(connection)
        assert len(links) == 1
        assert links[0][:5] == (run_id, digest, "adhoc", DATASET_ID, _us(FETCHED_AT))
        assert links[0][5] is not None  # the generic connector's parser configuration hash
    finally:
        connection.close()


# ------------------------------------- 5. idempotent re-link duplicates nothing


def test_05_relinking_the_identical_pair_is_a_no_op(tmp_path: Path) -> None:
    from src.lakehouse.ingestion.observability import RunArtifactLink

    connection, result = _prepare(tmp_path, CSV)
    try:
        repository = RunRepository(connection)
        link = RunArtifactLink(
            run_id=result.run_id,
            artifact_sha256=result.asset.artifact_sha256,
            source_id="adhoc",
            dataset_id=DATASET_ID,
            fetched_at=FETCHED_AT,
            parser_config_sha256=result.parsed_batch.parser_config_sha256,
        )
        before = _links(connection)
        assert repository.link_artifact(link) is False
        assert repository.link_artifact(link) is False
        assert _links(connection) == before == [_link_for(result)]
        # Identical means identical: the same instant expressed in another zone is the same link.
        shifted = replace(link, fetched_at=FETCHED_AT.astimezone(timezone(timedelta(hours=3))))
        assert repository.link_artifact(shifted) is False
        assert _links(connection) == before
    finally:
        connection.close()


def test_05_same_asset_twice_in_one_run_links_once(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    try:
        asset = _adhoc_asset(tmp_path, b"SYNTHETIC returned twice by one fetch")
        pipeline = _stub_pipeline(
            tmp_path, connection, _ListConnector([asset, asset]), _PassthroughParser()
        )
        results = pipeline.run(_adhoc_spec())
        assert len(results) == 2
        assert {result.run_id for result in results} == {results[0].run_id}
        assert _links(connection) == [
            (results[0].run_id, asset.artifact_sha256, "adhoc", DATASET_ID, _us(FETCHED_AT), None)
        ]
    finally:
        connection.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("fetched_at", FETCHED_AT + timedelta(seconds=1)),
        ("parser_config_sha256", "0" * 64),
        ("parser_config_sha256", None),
    ],
)
def test_05_relinking_with_different_facts_is_a_conflict(tmp_path: Path, field, value) -> None:
    from src.lakehouse.ingestion.observability import RunArtifactIntegrityError, RunArtifactLink

    connection, result = _prepare(tmp_path, CSV)
    try:
        link = RunArtifactLink(
            run_id=result.run_id,
            artifact_sha256=result.asset.artifact_sha256,
            source_id="adhoc",
            dataset_id=DATASET_ID,
            fetched_at=FETCHED_AT,
            parser_config_sha256=result.parsed_batch.parser_config_sha256,
        )
        before = _links(connection)
        with pytest.raises(RunArtifactIntegrityError):
            RunRepository(connection).link_artifact(replace(link, **{field: value}))
        assert _links(connection) == before
    finally:
        connection.close()


# ---------------- 6. forged or inconsistent links fail SQL and application checks


@pytest.mark.parametrize(
    "row",
    [
        pytest.param([" ", "a" * 64, "adhoc", DATASET_ID, FETCHED_AT, None], id="blank-run-id"),
        pytest.param([str(uuid4()), "Z" * 64, "adhoc", DATASET_ID, FETCHED_AT, None], id="non-hex-sha"),
        pytest.param([str(uuid4()), "a" * 63, "adhoc", DATASET_ID, FETCHED_AT, None], id="short-sha"),
        pytest.param([str(uuid4()), "a" * 64, " ", DATASET_ID, FETCHED_AT, None], id="blank-source"),
        pytest.param([str(uuid4()), "a" * 64, "adhoc", "", FETCHED_AT, None], id="blank-dataset"),
        pytest.param([str(uuid4()), "a" * 64, "adhoc", DATASET_ID, None, None], id="null-fetched-at"),
        pytest.param([str(uuid4()), "a" * 64, "adhoc", DATASET_ID, FETCHED_AT, "short"], id="bad-parser-sha"),
    ],
)
def test_06_sql_rejects_malformed_link_rows(tmp_path: Path, row: list) -> None:
    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    try:
        with pytest.raises(duckdb.ConstraintException):
            connection.execute(
                "INSERT INTO meta.run_artifact (run_id, artifact_sha256, source_id, dataset_id, "
                "fetched_at, parser_config_sha256) VALUES (?, ?, ?, ?, ?, ?)",
                row,
            )
        assert _links(connection) == []
    finally:
        connection.close()


def test_06_sql_rejects_a_second_row_for_the_same_pair(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, CSV)
    try:
        with pytest.raises(duckdb.ConstraintException):
            connection.execute(
                "INSERT INTO meta.run_artifact (run_id, artifact_sha256, source_id, dataset_id, "
                "fetched_at, parser_config_sha256) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    result.run_id,
                    result.asset.artifact_sha256,
                    "adhoc",
                    DATASET_ID,
                    FETCHED_AT + timedelta(days=1),
                    None,
                ],
            )
        assert _links(connection) == [_link_for(result)]
    finally:
        connection.close()


@pytest.mark.parametrize(
    "kind",
    ["unknown_run", "closed_run", "run_other_dataset", "unregistered_artifact",
     "artifact_other_dataset", "link_claims_other_source"],
)
def test_06_application_refuses_inconsistent_links(tmp_path: Path, kind: str) -> None:
    from src.lakehouse.ingestion.observability import RunArtifactIntegrityError, RunArtifactLink

    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    try:
        repository = RunRepository(connection)
        artifacts = ArtifactRepository(connection)
        asset = _adhoc_asset(tmp_path, b"SYNTHETIC registered artifact")
        now = datetime(2026, 9, 13, 10, tzinfo=timezone.utc)

        run_id = repository.start(
            run_id=str(uuid4()), source_id="adhoc", dataset_id=DATASET_ID, started_at=now
        )
        link = RunArtifactLink(
            run_id=run_id,
            artifact_sha256=asset.artifact_sha256,
            source_id="adhoc",
            dataset_id=DATASET_ID,
            fetched_at=FETCHED_AT,
            parser_config_sha256=None,
        )

        if kind == "unknown_run":
            artifacts.register(asset)
            link = replace(link, run_id=str(uuid4()))
        elif kind == "closed_run":
            artifacts.register(asset)
            repository.finish(run_id=run_id, status=RUN_STATUS_SUCCESS, ended_at=now, rows_out=0)
        elif kind == "run_other_dataset":
            artifacts.register(asset)
            other = repository.start(
                run_id=str(uuid4()), source_id="adhoc", dataset_id="adhoc_other", started_at=now
            )
            link = replace(link, run_id=other)
        elif kind == "unregistered_artifact":
            pass  # meta.artifact has no row for this digest
        elif kind == "artifact_other_dataset":
            artifacts.register(replace(asset, dataset_id="adhoc_other"))
        elif kind == "link_claims_other_source":
            artifacts.register(asset)
            link = replace(link, source_id="evds")

        with pytest.raises(RunArtifactIntegrityError):
            repository.link_artifact(link)
        assert _links(connection) == []
    finally:
        connection.close()


def test_06_publication_requires_the_link_to_agree_with_the_artifact(tmp_path: Path) -> None:
    """Even a trusted-SQL link row is cross-checked: it must name this artifact's dataset."""

    connection, result = _prepare(tmp_path, CSV)
    try:
        forged_run = str(uuid4())
        now = datetime(2026, 9, 13, 10, tzinfo=timezone.utc)
        RunRepository(connection).start(
            run_id=forged_run, source_id="adhoc", dataset_id=DATASET_ID, started_at=now
        )
        RunRepository(connection).finish(
            run_id=forged_run, status=RUN_STATUS_SUCCESS, ended_at=now, rows_out=0
        )
        connection.execute(
            "INSERT INTO meta.run_artifact (run_id, artifact_sha256, source_id, dataset_id, "
            "fetched_at, parser_config_sha256) VALUES (?, ?, ?, ?, ?, ?)",
            [
                forged_run,
                result.asset.artifact_sha256,
                "adhoc",
                "adhoc_other",
                FETCHED_AT,
                result.parsed_batch.parser_config_sha256,
            ],
        )
        with pytest.raises(AdhocPublicationError, match="dataset"):
            publish_adhoc_observations(connection, replace(result, run_id=forged_run), [_mapping()])
        assert _rows(connection) == []
    finally:
        connection.close()
