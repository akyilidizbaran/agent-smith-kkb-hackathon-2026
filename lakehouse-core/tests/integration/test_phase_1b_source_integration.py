"""Offline integration tests for the production source connectors and parsers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.bddk_monthly import BddkMonthlyConnector
from src.lakehouse.connectors.evds import EVDS_API_KEY_ENV, EvdsConnector
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.db.connection import connect_untrusted
from src.lakehouse.ingestion.pipeline import IngestionPipeline, IngestionResult
from src.lakehouse.parsers.bddk_monthly import BddkMonthlyParser
from src.lakehouse.parsers.evds import EvdsParser
from src.lakehouse.query.executor import QueryExecutor
from src.lakehouse.security.sql_guard import SqlGuardError
from src.lakehouse.storage.parquet import ParquetStorage, read_identity
from src.lakehouse.storage.raw import RawStorage, sha256_bytes


FIXTURE_ROOT = Path("tests/fixtures/raw")


class FixtureResponse:
    """Small HTTP response stub exposing only the connector-consumed fields."""

    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}


class FixtureSession:
    """Injected transport that returns committed fixture bytes without opening a socket."""

    def __init__(self, fixture: Path) -> None:
        self._response = FixtureResponse(fixture.read_bytes())
        self.calls: list[tuple[str, str]] = []

    def post(self, url: str, **_: Any) -> FixtureResponse:
        self.calls.append(("POST", url))
        return self._response

    def get(self, url: str, **_: Any) -> FixtureResponse:
        self.calls.append(("GET", url))
        return self._response


def _assert_flow(
    tmp_path: Path,
    *,
    connector: Any,
    parser: Any,
    spec: FetchSpec,
    fixture: Path,
    expected_rows: int,
    expected_series_id: str,
) -> tuple[IngestionResult, IngestionResult]:
    raw_storage = RawStorage(tmp_path / "data/raw")
    parquet_storage = ParquetStorage(tmp_path / "data/bronze")
    database_path = tmp_path / "data/lakehouse.duckdb"
    trusted = bootstrap_database(database_path)
    pipeline = IngestionPipeline(
        connector=connector(raw_storage),
        parser=parser,
        artifact_repository=ArtifactRepository(trusted),
        parquet_storage=parquet_storage,
    )

    first_result = pipeline.run(spec)[0]
    second_result = pipeline.run(spec)[0]

    assert first_result.asset.source_id == spec.source_id
    assert first_result.asset.dataset_id == spec.dataset_id
    assert first_result.asset.raw_path.is_file()
    assert first_result.asset.artifact_sha256 == sha256_bytes(fixture.read_bytes())
    assert first_result.parsed_batch.source_id == first_result.asset.source_id
    assert first_result.parsed_batch.dataset_id == first_result.asset.dataset_id
    assert first_result.parsed_batch.artifact_sha256 == first_result.asset.artifact_sha256
    assert set(first_result.parsed_batch.dataframe["series_id"]) == {expected_series_id}
    assert len(first_result.parsed_batch.dataframe) == expected_rows

    identity = read_identity(first_result.bronze_path)
    assert identity.source_id == first_result.asset.source_id
    assert identity.dataset_id == first_result.asset.dataset_id
    assert identity.artifact_sha256 == first_result.asset.artifact_sha256
    assert identity.schema_version == first_result.parsed_batch.schema_version
    assert first_result.bronze_path.is_file()
    assert second_result.asset.artifact_sha256 == first_result.asset.artifact_sha256
    assert second_result.bronze_path == first_result.bronze_path
    assert first_result.artifact_inserted is True
    assert second_result.artifact_inserted is False
    assert trusted.execute("SELECT count(*) FROM meta.artifact").fetchone() == (1,)

    parquet_storage.register_local_parquet(
        trusted, first_result.bronze_path, "bronze_fixture"
    )
    trusted.execute(
        "CREATE TABLE bronze.integration_fixture AS SELECT * FROM bronze_fixture"
    )
    trusted.close()

    untrusted = connect_untrusted(database_path)
    query = QueryExecutor(untrusted).execute(
        "SELECT count(*) AS row_count FROM bronze.integration_fixture"
    )
    assert query.columns == ["row_count"]
    assert query.rows == [(expected_rows,)]
    assert query.truncated is False
    with pytest.raises(SqlGuardError):
        QueryExecutor(untrusted).execute("INSERT INTO bronze.integration_fixture VALUES (1)")
    with pytest.raises(SqlGuardError):
        QueryExecutor(untrusted).execute("SELECT * FROM read_parquet('outside.parquet')")
    untrusted.close()
    return first_result, second_result


def test_bddk_real_connector_and_parser_use_offline_fixture(
    tmp_path: Path,
) -> None:
    fixture = FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json"
    session = FixtureSession(fixture)
    fetched_at = datetime(2026, 9, 9, 8, tzinfo=timezone.utc)

    def connector_factory(storage: RawStorage) -> BddkMonthlyConnector:
        return BddkMonthlyConnector(
            storage,
            session=session,
            max_attempts=1,
            clock=lambda: fetched_at,
        )

    spec = FetchSpec(
        source_id="bddk_monthly",
        dataset_id="bddk_monthly_housing_loans",
        locator="fixture://bddk_monthly/bddk_monthly_housing_loans.json",
        start_date=date(2026, 2, 1),
        end_date=date(2026, 6, 1),
        parameters={
            "periyot": "1",
            "paraBirimi": "TL",
            "taraf": ["10001"],
            "kalemSutun": "1534?Toplam",
            "gosterimTuru": "grid",
        },
        requested_at=datetime(2026, 9, 9, 7, tzinfo=timezone.utc),
    )
    first, second = _assert_flow(
        tmp_path,
        connector=connector_factory,
        parser=BddkMonthlyParser(),
        spec=spec,
        fixture=fixture,
        expected_rows=5,
        expected_series_id="bddk_monthly:1534_Toplam",
    )

    assert len(session.calls) == 2
    assert all(method == "POST" for method, _ in session.calls)
    assert first.asset.metadata["requested_kalem_sutun"] == ["1534?Toplam"]
    assert first.asset.metadata["requested_taraf"] == ["10001"]
    assert second.asset.metadata == first.asset.metadata


def test_evds_real_connector_and_parser_use_offline_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = FIXTURE_ROOT / "evds/evds_ktf12_weekly.json"
    session = FixtureSession(fixture)
    fetched_at = datetime(2026, 9, 9, 8, tzinfo=timezone.utc)
    fake_key = "test-only-evds-key"
    monkeypatch.setenv(EVDS_API_KEY_ENV, fake_key)

    def connector_factory(storage: RawStorage) -> EvdsConnector:
        return EvdsConnector(
            storage,
            session=session,
            max_attempts=1,
            clock=lambda: fetched_at,
        )

    spec = FetchSpec(
        source_id="evds",
        dataset_id="evds_housing_interest",
        locator="fixture://evds/evds_ktf12_weekly.json",
        start_date=date(2021, 1, 1),
        end_date=date(2026, 7, 3),
        parameters={"series": "TP.KTF12"},
        requested_at=datetime(2026, 9, 9, 7, tzinfo=timezone.utc),
    )
    first, second = _assert_flow(
        tmp_path,
        connector=connector_factory,
        parser=EvdsParser(),
        spec=spec,
        fixture=fixture,
        expected_rows=5,
        expected_series_id="evds:TP.KTF12",
    )

    assert len(session.calls) == 2
    assert all(method == "GET" for method, _ in session.calls)
    assert first.asset.metadata["requested_series"] == ["TP.KTF12"]
    assert fake_key not in repr(first.asset.metadata)
    assert fake_key not in str(first.asset.raw_path)
    assert second.asset.metadata == first.asset.metadata
