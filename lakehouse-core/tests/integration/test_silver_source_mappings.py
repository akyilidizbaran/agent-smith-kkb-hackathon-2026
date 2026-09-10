"""Offline end-to-end tests for the four current real Bronze to Silver mappings."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.bddk_monthly import BddkMonthlyConnector
from src.lakehouse.connectors.bddk_weekly import BddkWeeklyConnector
from src.lakehouse.connectors.evds import EVDS_API_KEY_ENV, EvdsConnector
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.parsers.bddk_monthly import BddkMonthlyParser
from src.lakehouse.parsers.bddk_weekly import BddkWeeklyParser
from src.lakehouse.parsers.evds import EvdsParser
from src.lakehouse.silver.adapters.bddk_monthly import bddk_monthly_to_staging
from src.lakehouse.silver.adapters.bddk_weekly import bddk_weekly_to_staging
from src.lakehouse.silver.adapters.evds import evds_kfe_to_staging, evds_ktf12_to_staging
from src.lakehouse.silver.foundation import FACT_OBSERVATION_COLUMNS, materialize_fact_observation
from src.lakehouse.storage.parquet import ParquetStorage, read_identity
from src.lakehouse.storage.raw import RawStorage, sha256_bytes


FIXTURE_ROOT = Path("tests/fixtures/raw")
FETCHED_AT = datetime(2026, 9, 9, 8, tzinfo=timezone.utc)
REQUESTED_AT = datetime(2026, 9, 9, 7, tzinfo=timezone.utc)


class FixtureResponse:
    """Minimal response object consumed by the production connectors."""

    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}


class FixtureSession:
    """Replay committed fixture bytes without opening a network connection."""

    def __init__(self, fixture: Path) -> None:
        self._response = FixtureResponse(fixture.read_bytes())
        self.calls: list[tuple[str, str]] = []

    def post(self, url: str, **_: Any) -> FixtureResponse:
        self.calls.append(("POST", url))
        return self._response

    def get(self, url: str, **_: Any) -> FixtureResponse:
        self.calls.append(("GET", url))
        return self._response


def _run_to_silver(
    tmp_path: Path,
    *,
    connector: Any,
    parser: Any,
    spec: FetchSpec,
    adapter: Any,
):
    raw_storage = RawStorage(tmp_path / "data/raw")
    bronze_storage = ParquetStorage(tmp_path / "data/bronze")
    trusted = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    pipeline = IngestionPipeline(
        connector=connector(raw_storage),
        parser=parser,
        artifact_repository=ArtifactRepository(trusted),
        parquet_storage=bronze_storage,
    )

    result = pipeline.run(spec)[0]
    bronze = ParquetStorage.read(result.bronze_path)
    identity = read_identity(result.bronze_path)
    staging = adapter(bronze, identity=identity)
    silver = materialize_fact_observation(trusted, staging)
    silver_path = ParquetStorage(tmp_path / "data/silver/fact_observation").write_frame(
        silver, identity=identity
    )
    return trusted, result, staging, silver, silver_path


def test_bddk_monthly_reaches_silver_from_real_connector_parser_and_fixture(
    tmp_path: Path,
) -> None:
    fixture = FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json"
    session = FixtureSession(fixture)

    def connector_factory(storage: RawStorage) -> BddkMonthlyConnector:
        return BddkMonthlyConnector(
            storage, session=session, max_attempts=1, clock=lambda: FETCHED_AT
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
        },
        requested_at=REQUESTED_AT,
    )
    trusted, result, staging, silver, silver_path = _run_to_silver(
        tmp_path,
        connector=connector_factory,
        parser=BddkMonthlyParser(),
        spec=spec,
        adapter=bddk_monthly_to_staging,
    )

    try:
        assert session.calls and all(method == "POST" for method, _ in session.calls)
        assert result.asset.raw_path.read_bytes() == fixture.read_bytes()
        assert result.asset.artifact_sha256 == sha256_bytes(fixture.read_bytes())
        assert result.parsed_batch.warnings
        assert staging["source_warning"].isna().all()
        assert list(staging.columns) == [
            "series_id",
            "entity_id",
            "observation_date",
            "period_start",
            "period_end",
            "value_raw",
            "source_id",
            "dataset_id",
            "artifact_sha256",
            "fetched_at",
            "schema_version",
            "vintage_id",
            "run_id",
            "source_warning",
        ]
        row = trusted.execute(
            """
            SELECT series_id, entity_id, observation_date, period_start, period_end,
                   value, frequency, unit, measure_type, quality_flag,
                   source_id, dataset_id, artifact_sha256
            FROM silver.fact_observation
            WHERE observation_date = DATE '2026-06-30'
            """
        ).fetchone()
        assert row == (
            "bddk_monthly:1534_Toplam",
            None,
            date(2026, 6, 30),
            date(2026, 6, 1),
            date(2026, 6, 30),
            801438.0,
            "monthly",
            "TRY_mn",
            "stock",
            "ok",
            "bddk_monthly",
            "bddk_monthly_housing_loans",
            result.asset.artifact_sha256,
        )
        assert len(silver) == 5
        assert silver_path.is_file()
        assert read_identity(silver_path) == read_identity(result.bronze_path)
        assert json.loads(
            trusted.execute(
                "SELECT request_metadata_json FROM meta.artifact_request"
            ).fetchone()[0]
        )["requested_kalem_sutun"] == ["1534?Toplam"]
    finally:
        trusted.close()


def test_evds_ktf12_reaches_silver_from_real_connector_parser_and_fixture(
    tmp_path: Path, monkeypatch: Any
) -> None:
    fixture = FIXTURE_ROOT / "evds/evds_ktf12_weekly.json"
    session = FixtureSession(fixture)
    fake_key = "phase-2-4-test-only-key"
    monkeypatch.setenv(EVDS_API_KEY_ENV, fake_key)

    def connector_factory(storage: RawStorage) -> EvdsConnector:
        return EvdsConnector(
            storage, session=session, max_attempts=1, clock=lambda: FETCHED_AT
        )

    spec = FetchSpec(
        source_id="evds",
        dataset_id="evds_housing_interest",
        locator="fixture://evds/evds_ktf12_weekly.json",
        start_date=date(2021, 1, 1),
        end_date=date(2026, 7, 3),
        parameters={"series": "TP.KTF12"},
        requested_at=REQUESTED_AT,
    )
    trusted, result, staging, silver, silver_path = _run_to_silver(
        tmp_path,
        connector=connector_factory,
        parser=EvdsParser(),
        spec=spec,
        adapter=evds_ktf12_to_staging,
    )

    try:
        assert session.calls and all(method == "GET" for method, _ in session.calls)
        assert result.asset.raw_path.read_bytes() == fixture.read_bytes()
        assert result.asset.artifact_sha256 == sha256_bytes(fixture.read_bytes())
        row = trusted.execute(
            """
            SELECT series_id, entity_id, observation_date, period_start, period_end,
                   value, frequency, unit, measure_type, quality_flag,
                   source_id, dataset_id, artifact_sha256
            FROM silver.fact_observation
            WHERE observation_date = DATE '2021-01-01'
            """
        ).fetchone()
        assert row == (
            "evds:TP.KTF12",
            None,
            date(2021, 1, 1),
            None,
            None,
            18.61,
            "weekly",
            "pct",
            "rate",
            "ok",
            "evds",
            "evds_housing_interest",
            result.asset.artifact_sha256,
        )
        assert len(silver) == 5
        assert silver_path.is_file()
        assert read_identity(silver_path) == read_identity(result.bronze_path)
        assert fake_key not in json.dumps(result.asset.metadata)
    finally:
        trusted.close()


def test_bddk_and_evds_coexist_in_one_canonical_silver_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both real source shapes must produce one shared fact_observation schema."""

    bddk_fixture = FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json"
    evds_fixture = FIXTURE_ROOT / "evds/evds_ktf12_weekly.json"
    bddk_session = FixtureSession(bddk_fixture)
    evds_session = FixtureSession(evds_fixture)
    monkeypatch.setenv(EVDS_API_KEY_ENV, "phase-2-4-combined-test-key")

    raw_storage = RawStorage(tmp_path / "data/raw")
    bronze_storage = ParquetStorage(tmp_path / "data/bronze")
    trusted = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    repository = ArtifactRepository(trusted)

    bddk_pipeline = IngestionPipeline(
        connector=BddkMonthlyConnector(
            raw_storage, session=bddk_session, max_attempts=1, clock=lambda: FETCHED_AT
        ),
        parser=BddkMonthlyParser(),
        artifact_repository=repository,
        parquet_storage=bronze_storage,
    )
    evds_pipeline = IngestionPipeline(
        connector=EvdsConnector(
            raw_storage, session=evds_session, max_attempts=1, clock=lambda: FETCHED_AT
        ),
        parser=EvdsParser(),
        artifact_repository=repository,
        parquet_storage=bronze_storage,
    )

    bddk_result = bddk_pipeline.run(
        FetchSpec(
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
            },
            requested_at=REQUESTED_AT,
        )
    )[0]
    evds_result = evds_pipeline.run(
        FetchSpec(
            source_id="evds",
            dataset_id="evds_housing_interest",
            locator="fixture://evds/evds_ktf12_weekly.json",
            start_date=date(2021, 1, 1),
            end_date=date(2026, 7, 3),
            parameters={"series": "TP.KTF12"},
            requested_at=REQUESTED_AT,
        )
    )[0]

    try:
        bddk_staging = bddk_monthly_to_staging(
            ParquetStorage.read(bddk_result.bronze_path),
            identity=read_identity(bddk_result.bronze_path),
        )
        evds_staging = evds_ktf12_to_staging(
            ParquetStorage.read(evds_result.bronze_path),
            identity=read_identity(evds_result.bronze_path),
        )
        silver = materialize_fact_observation(
            trusted, pd.concat([bddk_staging, evds_staging], ignore_index=True)
        )

        assert list(silver.columns) == [
            "series_id",
            "entity_id",
            "observation_date",
            "period_start",
            "period_end",
            "value",
            "frequency",
            "unit",
            "measure_type",
            "quality_flag",
            "source_id",
            "dataset_id",
            "artifact_sha256",
            "fetched_at",
            "schema_version",
            "vintage_id",
            "run_id",
        ]
        assert trusted.execute(
            """
            SELECT series_id, frequency, unit, measure_type, COUNT(*)
            FROM silver.fact_observation
            GROUP BY series_id, frequency, unit, measure_type
            ORDER BY series_id
            """
        ).fetchall() == [
            ("bddk_monthly:1534_Toplam", "monthly", "TRY_mn", "stock", 5),
            ("evds:TP.KTF12", "weekly", "pct", "rate", 5),
        ]
    finally:
        trusted.close()


def test_bddk_weekly_reaches_silver_from_real_connector_parser_and_fixture(
    tmp_path: Path,
) -> None:
    fixture = FIXTURE_ROOT / "bddk_weekly/bddk_weekly_housing_loans.json"
    session = FixtureSession(fixture)

    def connector_factory(storage: RawStorage) -> BddkWeeklyConnector:
        return BddkWeeklyConnector(
            storage, session=session, max_attempts=1, clock=lambda: FETCHED_AT
        )

    spec = FetchSpec(
        source_id="bddk_weekly",
        dataset_id="bddk_weekly_housing_loans",
        locator="fixture://bddk_weekly/bddk_weekly_housing_loans.json",
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
    trusted, result, staging, silver, silver_path = _run_to_silver(
        tmp_path,
        connector=connector_factory,
        parser=BddkWeeklyParser(),
        spec=spec,
        adapter=bddk_weekly_to_staging,
    )

    try:
        assert session.calls and all(method == "POST" for method, _ in session.calls)
        assert result.asset.raw_path.read_bytes() == fixture.read_bytes()
        assert result.asset.artifact_sha256 == sha256_bytes(fixture.read_bytes())
        assert result.parsed_batch.schema_version == "bddk_weekly_observations.v1"
        assert staging.loc[2, "observation_date"] == date(2026, 3, 19)
        row = trusted.execute(
            """
            SELECT series_id, entity_id, observation_date, value, frequency,
                   unit, measure_type, quality_flag, source_id, dataset_id,
                   artifact_sha256
            FROM silver.fact_observation
            WHERE observation_date = DATE '2026-03-19'
            """
        ).fetchone()
        assert row == (
            "bddk_weekly:5690_3",
            None,
            date(2026, 3, 19),
            734860.422,
            "weekly",
            "TRY_mn",
            "stock",
            "ok",
            "bddk_weekly",
            "bddk_weekly_housing_loans",
            result.asset.artifact_sha256,
        )
        assert len(silver) == 5
        assert silver_path.is_file()
        assert read_identity(silver_path) == read_identity(result.bronze_path)
    finally:
        trusted.close()


def test_evds_kfe_reaches_silver_from_generic_connector_parser_and_fixture(
    tmp_path: Path, monkeypatch: Any
) -> None:
    fixture = FIXTURE_ROOT / "evds/evds_kfe_monthly.json"
    session = FixtureSession(fixture)
    fake_key = "phase-2-5-kfe-test-only-key"
    monkeypatch.setenv(EVDS_API_KEY_ENV, fake_key)

    def connector_factory(storage: RawStorage) -> EvdsConnector:
        return EvdsConnector(
            storage, session=session, max_attempts=1, clock=lambda: FETCHED_AT
        )

    spec = FetchSpec(
        source_id="evds",
        dataset_id="evds_housing_price_index",
        locator="fixture://evds/evds_kfe_monthly.json",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        parameters={"series": "TP.KFE.TR", "frequency": "5"},
        requested_at=REQUESTED_AT,
    )
    trusted, result, staging, silver, silver_path = _run_to_silver(
        tmp_path,
        connector=connector_factory,
        parser=EvdsParser(),
        spec=spec,
        adapter=evds_kfe_to_staging,
    )

    try:
        assert session.calls and all(method == "GET" for method, _ in session.calls)
        assert result.asset.raw_path.read_bytes() == fixture.read_bytes()
        assert result.asset.artifact_sha256 == sha256_bytes(fixture.read_bytes())
        assert result.parsed_batch.schema_version == "evds_observations.v1"
        assert staging.loc[0, "observation_date"] == date(2026, 1, 31)
        row = trusted.execute(
            """
            SELECT series_id, entity_id, observation_date, period_start, period_end,
                   value, frequency, unit, measure_type, quality_flag,
                   source_id, dataset_id, artifact_sha256
            FROM silver.fact_observation
            WHERE observation_date = DATE '2026-01-31'
            """
        ).fetchone()
        assert row == (
            "evds:TP.KFE.TR",
            None,
            date(2026, 1, 31),
            date(2026, 1, 1),
            date(2026, 1, 31),
            211.73,
            "monthly",
            "index",
            "index",
            "ok",
            "evds",
            "evds_housing_price_index",
            result.asset.artifact_sha256,
        )
        assert len(silver) == 3
        assert silver_path.is_file()
        assert read_identity(silver_path) == read_identity(result.bronze_path)
        assert fake_key not in json.dumps(result.asset.metadata)
    finally:
        trusted.close()


def test_all_four_real_series_coexist_in_one_fact_observation_table(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The four current real series share the exact canonical Silver schema."""

    monkeypatch.setenv(EVDS_API_KEY_ENV, "phase-2-5-four-series-test-only-key")
    raw_storage = RawStorage(tmp_path / "data/raw")
    bronze_storage = ParquetStorage(tmp_path / "data/bronze")
    trusted = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    repository = ArtifactRepository(trusted)

    def run_pipeline(connector: Any, parser: Any, spec: FetchSpec):
        return IngestionPipeline(
            connector=connector,
            parser=parser,
            artifact_repository=repository,
            parquet_storage=bronze_storage,
        ).run(spec)[0]

    bddk_monthly_fixture = FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json"
    bddk_weekly_fixture = FIXTURE_ROOT / "bddk_weekly/bddk_weekly_housing_loans.json"
    evds_ktf12_fixture = FIXTURE_ROOT / "evds/evds_ktf12_weekly.json"
    evds_kfe_fixture = FIXTURE_ROOT / "evds/evds_kfe_monthly.json"

    bddk_monthly_result = run_pipeline(
        BddkMonthlyConnector(
            raw_storage,
            session=FixtureSession(bddk_monthly_fixture),
            max_attempts=1,
            clock=lambda: FETCHED_AT,
        ),
        BddkMonthlyParser(),
        FetchSpec(
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
            },
            requested_at=REQUESTED_AT,
        ),
    )
    bddk_weekly_result = run_pipeline(
        BddkWeeklyConnector(
            raw_storage,
            session=FixtureSession(bddk_weekly_fixture),
            max_attempts=1,
            clock=lambda: FETCHED_AT,
        ),
        BddkWeeklyParser(),
        FetchSpec(
            source_id="bddk_weekly",
            dataset_id="bddk_weekly_housing_loans",
            locator="fixture://bddk_weekly/bddk_weekly_housing_loans.json",
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
        ),
    )
    evds_ktf12_result = run_pipeline(
        EvdsConnector(
            raw_storage,
            session=FixtureSession(evds_ktf12_fixture),
            max_attempts=1,
            clock=lambda: FETCHED_AT,
        ),
        EvdsParser(),
        FetchSpec(
            source_id="evds",
            dataset_id="evds_housing_interest",
            locator="fixture://evds/evds_ktf12_weekly.json",
            start_date=date(2021, 1, 1),
            end_date=date(2026, 7, 3),
            parameters={"series": "TP.KTF12"},
            requested_at=REQUESTED_AT,
        ),
    )
    evds_kfe_result = run_pipeline(
        EvdsConnector(
            raw_storage,
            session=FixtureSession(evds_kfe_fixture),
            max_attempts=1,
            clock=lambda: FETCHED_AT,
        ),
        EvdsParser(),
        FetchSpec(
            source_id="evds",
            dataset_id="evds_housing_price_index",
            locator="fixture://evds/evds_kfe_monthly.json",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            parameters={"series": "TP.KFE.TR", "frequency": "5"},
            requested_at=REQUESTED_AT,
        ),
    )

    try:
        def stage(result: Any, adapter: Any) -> pd.DataFrame:
            return adapter(
                ParquetStorage.read(result.bronze_path),
                identity=read_identity(result.bronze_path),
            )

        staging = pd.concat(
            [
                stage(bddk_monthly_result, bddk_monthly_to_staging),
                stage(bddk_weekly_result, bddk_weekly_to_staging),
                stage(evds_ktf12_result, evds_ktf12_to_staging),
                stage(evds_kfe_result, evds_kfe_to_staging),
            ],
            ignore_index=True,
        )
        silver = materialize_fact_observation(trusted, staging)
        assert list(silver.columns) == list(FACT_OBSERVATION_COLUMNS)
        assert trusted.execute(
            """
            SELECT series_id, frequency, unit, measure_type, COUNT(*),
                   MIN(observation_date), MAX(observation_date)
            FROM silver.fact_observation
            GROUP BY series_id, frequency, unit, measure_type
            ORDER BY series_id
            """
        ).fetchall() == [
            (
                "bddk_monthly:1534_Toplam",
                "monthly",
                "TRY_mn",
                "stock",
                5,
                date(2021, 1, 31),
                date(2026, 6, 30),
            ),
            (
                "bddk_weekly:5690_3",
                "weekly",
                "TRY_mn",
                "stock",
                5,
                date(2026, 1, 2),
                date(2026, 6, 26),
            ),
            (
                "evds:TP.KFE.TR",
                "monthly",
                "index",
                "index",
                3,
                date(2026, 1, 31),
                date(2026, 3, 31),
            ),
            (
                "evds:TP.KTF12",
                "weekly",
                "pct",
                "rate",
                5,
                date(2021, 1, 1),
                date(2026, 7, 3),
            ),
        ]
    finally:
        trusted.close()
