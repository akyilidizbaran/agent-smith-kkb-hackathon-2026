"""Offline integration test for the BDDK weekly source, using the production classes.

The connector, parser, RAW storage, artifact repository, Parquet storage and the ingestion
pipeline are all the real implementations. Only two inputs are substituted, and neither of
them is source logic:

- the HTTP transport, which returns committed fixture bytes instead of opening a socket, and
- the connector clock, so that ``fetched_at`` and the RAW path are deterministic.

This is therefore an offline test of real code, **not** a live call to BDDK.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.bddk_weekly import (
    BDDK_WEEKLY_SERIES_PATH,
    BddkWeeklyConnector,
)
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.db.connection import connect_untrusted
from src.lakehouse.errors import LakehouseError
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.parsers.bddk_weekly import (
    BDDK_WEEKLY_SCHEMA_VERSION,
    BddkWeeklyParser,
)
from src.lakehouse.query.executor import QueryExecutor
from src.lakehouse.security.sql_guard import SqlGuardError
from src.lakehouse.storage.parquet import ParquetStorage, read_identity
from src.lakehouse.storage.raw import RawStorage, sha256_bytes


FIXTURE_DIR = Path("tests/fixtures/raw/bddk_weekly")
HOUSING = FIXTURE_DIR / "bddk_weekly_housing_loans.json"
UNKNOWN_ITEM = FIXTURE_DIR / "bddk_weekly_unknown_item.json"

FETCHED_AT = datetime(2026, 9, 10, 6, 15, 42, tzinfo=timezone.utc)
REQUESTED_AT = datetime(2026, 9, 9, 21, 30, tzinfo=timezone.utc)
EXPECTED_ROWS = 5
EXPECTED_SERIES_ID = "bddk_weekly:5690_3"


class FixtureResponse:
    """HTTP response stub exposing only the fields the connector consumes."""

    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200
        self.headers = {"Content-Type": "application/json; charset=utf-8"}


class FixtureSession:
    """Injected transport returning committed fixture bytes without opening a socket."""

    def __init__(self, fixture: Path) -> None:
        self._response = FixtureResponse(fixture.read_bytes())
        self.calls: list[tuple[str, str, list[tuple[str, str]]]] = []

    def post(self, url: str, *, data: list[tuple[str, str]], **_: Any) -> FixtureResponse:
        self.calls.append(("POST", url, list(data)))
        return self._response


def _spec() -> FetchSpec:
    return FetchSpec(
        source_id="bddk_weekly",
        dataset_id="bddk_weekly_housing_loans",
        locator=f"https://www.bddk.org.tr{BDDK_WEEKLY_SERIES_PATH}",
        start_date=date(2026, 1, 2),
        end_date=date(2026, 6, 26),
        parameters={
            "id": "1.0.4",
            "kalem_id": "5690",
            "expected_measure_label": "a) Konut",
            "expected_currency": "TRY",
            "expected_column": "Toplam",
            "parabirimi": "TRY",
            "sutun": "3",
            "tarafKodu": "10001",
        },
        requested_at=REQUESTED_AT,
    )


def _pipeline(tmp_path: Path, session: FixtureSession) -> tuple[IngestionPipeline, Path, Any]:
    raw_storage = RawStorage(tmp_path / "data/raw")
    parquet_storage = ParquetStorage(tmp_path / "data/bronze")
    database_path = tmp_path / "data/lakehouse.duckdb"
    trusted = bootstrap_database(database_path)
    pipeline = IngestionPipeline(
        connector=BddkWeeklyConnector(
            raw_storage,
            session=session,  # type: ignore[arg-type]
            max_attempts=1,
            clock=lambda: FETCHED_AT,
        ),
        parser=BddkWeeklyParser(),
        artifact_repository=ArtifactRepository(trusted),
        parquet_storage=parquet_storage,
    )
    return pipeline, database_path, trusted


def test_bddk_weekly_flows_from_connector_to_bronze_and_safe_query(tmp_path: Path) -> None:
    """Connector → immutable RAW → meta.artifact → Parser → ParsedBatch → Bronze Parquet."""

    session = FixtureSession(HOUSING)
    pipeline, database_path, trusted = _pipeline(tmp_path, session)

    first = pipeline.run(_spec())[0]
    second = pipeline.run(_spec())[0]

    # --- the connector sent the verified request and stored exact bytes
    assert len(session.calls) == 2
    method, url, form = session.calls[0]
    assert method == "POST"
    assert url.endswith(BDDK_WEEKLY_SERIES_PATH)
    assert dict(form)["id"] == "1.0.4"
    assert dict(form)["parabirimi"] == "TRY"
    assert first.asset.raw_path.is_file()
    assert first.asset.raw_path.read_bytes() == HOUSING.read_bytes()
    assert first.asset.artifact_sha256 == sha256_bytes(HOUSING.read_bytes())
    assert first.asset.fetched_at == FETCHED_AT

    # --- meta.artifact registered once for identical bytes
    assert first.artifact_inserted is True
    assert second.artifact_inserted is False
    assert trusted.execute("SELECT count(*) FROM meta.artifact").fetchone() == (1,)
    assert second.asset.raw_path == first.asset.raw_path
    assert len(list((tmp_path / "data/raw").rglob("*.json"))) == 1

    # --- the parsed batch keeps provenance and stays raw
    batch = first.parsed_batch
    assert batch.source_id == first.asset.source_id
    assert batch.dataset_id == first.asset.dataset_id
    assert batch.artifact_sha256 == first.asset.artifact_sha256
    assert batch.schema_version == BDDK_WEEKLY_SCHEMA_VERSION
    assert len(batch.dataframe) == EXPECTED_ROWS
    assert set(batch.dataframe["series_id"]) == {EXPECTED_SERIES_ID}
    assert list(batch.dataframe["date_raw"])[0] == "2.01.2026"
    assert list(batch.dataframe["value_raw"])[-1] == 800464.007

    # --- Bronze Parquet carries the representation identity
    identity = read_identity(first.bronze_path)
    assert identity.source_id == "bddk_weekly"
    assert identity.dataset_id == "bddk_weekly_housing_loans"
    assert identity.artifact_sha256 == first.asset.artifact_sha256
    assert identity.schema_version == BDDK_WEEKLY_SCHEMA_VERSION
    assert first.bronze_path.is_file()
    assert second.bronze_path == first.bronze_path

    # --- the Bronze rows are readable through the hardened read-only boundary
    parquet_storage = ParquetStorage(tmp_path / "data/bronze")
    parquet_storage.register_local_parquet(trusted, first.bronze_path, "bronze_weekly")
    trusted.execute(
        "CREATE TABLE bronze.bddk_weekly_fixture AS SELECT * FROM bronze_weekly"
    )
    trusted.close()

    untrusted = connect_untrusted(database_path)
    result = QueryExecutor(untrusted).execute(
        "SELECT count(*) AS row_count FROM bronze.bddk_weekly_fixture"
    )
    assert result.columns == ["row_count"]
    assert result.rows == [(EXPECTED_ROWS,)]
    assert result.truncated is False
    with pytest.raises(SqlGuardError):
        QueryExecutor(untrusted).execute(
            "INSERT INTO bronze.bddk_weekly_fixture VALUES (1)"
        )
    untrusted.close()


def test_application_error_under_http_200_never_reaches_bronze(tmp_path: Path) -> None:
    """A real capture: HTTP 200 with a placeholder title and empty arrays.

    The connector still stores those bytes faithfully — that is the source's real answer —
    but the parser refuses them, so nothing is written to Bronze.
    """

    session = FixtureSession(UNKNOWN_ITEM)
    pipeline, _, trusted = _pipeline(tmp_path, session)

    with pytest.raises(LakehouseError) as excinfo:
        pipeline.run(_spec())

    assert excinfo.value.payload.error_code == "SOURCE_UNAVAILABLE"
    assert excinfo.value.payload.source_id == "bddk_weekly"
    # the RAW artifact and its metadata row exist; the Bronze representation does not
    assert len(list((tmp_path / "data/raw").rglob("*.json"))) == 1
    assert trusted.execute("SELECT count(*) FROM meta.artifact").fetchone() == (1,)
    trusted.close()
    assert not list((tmp_path / "data/bronze").rglob("*.parquet"))
