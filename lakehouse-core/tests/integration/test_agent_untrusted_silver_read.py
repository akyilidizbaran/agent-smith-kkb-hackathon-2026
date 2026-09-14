"""The real agent handoff: read Silver over the hardened, read-only connection.

The independent audit's finding D1 said the untrusted connection could only see ``meta.*``,
because nothing materialized Bronze into a queryable table. Silver changed that — but the
claim had never been proved on a **disk** database with the trusted connection closed, which
is exactly the shape the agent's adapter runs in.

Every test here goes through the production path end to end: real connector, real parser,
real ingestion pipeline, real Silver adapter, real materialization, then a *separate*
``connect_untrusted`` handle over the same file and a guarded ``QueryExecutor``. Nothing in
this file is allowed to query Silver through a trusted connection; that would prove nothing.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pytest

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.bddk_weekly import BddkWeeklyConnector
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.db.connection import connect_untrusted
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.parsers.bddk_weekly import BddkWeeklyParser
from src.lakehouse.query.executor import QueryExecutor, TrustedConnectionError
from src.lakehouse.security.sql_guard import SqlGuardError
from src.lakehouse.silver.adapters.bddk_weekly import bddk_weekly_to_staging
from src.lakehouse.silver.foundation import materialize_fact_observation_snapshot
from src.lakehouse.silver.pipeline import stage_ingestion_result
from src.lakehouse.storage.parquet import ParquetStorage
from src.lakehouse.storage.raw import RawStorage


FIXTURE = Path("tests/fixtures/raw/bddk_weekly/bddk_weekly_housing_loans.json")
FETCHED_AT = datetime(2026, 9, 11, 8, tzinfo=timezone.utc)
REQUESTED_AT = datetime(2026, 9, 11, 7, tzinfo=timezone.utc)


class _FixtureResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}


class _FixtureSession:
    def __init__(self, fixture: Path) -> None:
        self._response = _FixtureResponse(fixture.read_bytes())

    def post(self, url: str, **_: Any) -> _FixtureResponse:
        return self._response


def _publish_silver(db_path: Path, tmp_path: Path) -> None:
    """Run the production path on a trusted connection, then close it completely."""

    connection = bootstrap_database(db_path)
    try:
        pipeline = IngestionPipeline(
            connector=BddkWeeklyConnector(
                RawStorage(tmp_path / "data/raw"),
                session=_FixtureSession(FIXTURE),
                max_attempts=1,
                clock=lambda: FETCHED_AT,
            ),
            parser=BddkWeeklyParser(),
            artifact_repository=ArtifactRepository(connection),
            parquet_storage=ParquetStorage(tmp_path / "data/bronze"),
        )
        spec = FetchSpec(
            source_id="bddk_weekly",
            dataset_id="bddk_weekly_housing_loans",
            locator="fixture://bddk_weekly",
            start_date=date(2026, 1, 2),
            end_date=date(2026, 6, 26),
            parameters={
                "dil": "tr",
                "id": "1.0.4",
                "parabirimi": "TRY",
                "sutun": "3",
                "tarafKodu": "10001",
                "kalem_id": "5690",
                "expected_measure_label": "a) Konut",
                "expected_currency": "TRY",
                "expected_column": "Toplam",
            },
            requested_at=REQUESTED_AT,
        )
        result = pipeline.run(spec)[0]
        staging, _ = stage_ingestion_result(result, adapter=bddk_weekly_to_staging)
        materialize_fact_observation_snapshot(connection, staging)
    finally:
        # The agent never inherits this handle.
        connection.close()


@pytest.fixture()
def published(tmp_path: Path) -> Path:
    db_path = tmp_path / "data/lakehouse.duckdb"
    _publish_silver(db_path, tmp_path)
    return db_path


# ------------------------------------------------------- the handoff itself


def test_agent_reads_silver_over_the_hardened_read_only_connection(published: Path) -> None:
    untrusted = connect_untrusted(published)
    try:
        executor = QueryExecutor(untrusted)
        result = executor.execute(
            """
            SELECT series_id, observation_date, value, frequency, unit, measure_type,
                   quality_flag, entity_id
            FROM silver.fact_observation
            ORDER BY observation_date
            """
        )

        assert result.columns == [
            "series_id",
            "observation_date",
            "value",
            "frequency",
            "unit",
            "measure_type",
            "quality_flag",
            "entity_id",
        ]
        assert result.row_count == 5
        assert result.truncated is False
        assert result.rows[0] == (
            "bddk_weekly:5690_3",
            date(2026, 1, 2),
            679216.118,
            "weekly",
            "TRY_mn",
            "stock",
            "ok",
            "bddk:10001",
        )
        # The holiday Thursday reaches the agent as the source published it.
        assert date(2026, 3, 19) in {row[1] for row in result.rows}
    finally:
        untrusted.close()


def test_agent_reads_catalog_coverage_over_the_same_connection(published: Path) -> None:
    """The out-of-range guard needs first_obs/last_obs, so they must be readable here too."""

    untrusted = connect_untrusted(published)
    try:
        result = QueryExecutor(untrusted).execute(
            "SELECT series_id, first_obs, last_obs FROM meta.series "
            "WHERE series_id = 'bddk_weekly:5690_3'"
        )
        assert result.rows == [
            ("bddk_weekly:5690_3", date(2026, 1, 2), date(2026, 6, 26))
        ]
    finally:
        untrusted.close()


def test_agent_can_join_silver_to_the_semantic_catalog(published: Path) -> None:
    """The adapter's real query shape: facts plus the semantics that explain them."""

    untrusted = connect_untrusted(published)
    try:
        result = QueryExecutor(untrusted).execute(
            """
            SELECT m.name_tr, m.default_agg, count(*) AS observations
            FROM silver.fact_observation AS f
            JOIN meta.series AS m ON m.series_id = f.series_id
            GROUP BY m.name_tr, m.default_agg
            """
        )
        assert result.row_count == 1
        assert result.rows[0][1] == "last"
        assert result.rows[0][2] == 5
    finally:
        untrusted.close()


# --------------------------------------------------- the guards stay in place


def test_the_connection_is_still_read_only_hardened_and_locked(published: Path) -> None:
    untrusted = connect_untrusted(published)
    try:
        def setting(name: str) -> Any:
            return untrusted.execute("SELECT current_setting(?)", [name]).fetchone()[0]

        assert setting("access_mode") == "read_only"
        assert setting("enable_external_access") is False
        assert setting("lock_configuration") is True
        assert setting("allow_community_extensions") is False
        assert setting("allow_unsigned_extensions") is False
    finally:
        untrusted.close()


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM silver.fact_observation",
        "UPDATE silver.fact_observation SET value = 0",
        "DROP TABLE silver.fact_observation",
        "CREATE TABLE evil AS SELECT 1",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "SELECT * FROM read_parquet('/tmp/anything.parquet')",
        "SELECT * FROM glob('/etc/*')",
        "SELECT 1; SELECT 2",
        "ATTACH '/tmp/other.duckdb' AS other",
        "INSTALL httpfs",
    ],
)
def test_the_sql_guard_still_refuses_everything_it_should(published: Path, sql: str) -> None:
    untrusted = connect_untrusted(published)
    try:
        with pytest.raises(SqlGuardError):
            QueryExecutor(untrusted).execute(sql)
    finally:
        untrusted.close()


def test_external_file_access_is_refused_by_the_engine_even_past_the_guard(
    published: Path,
) -> None:
    """Defence in depth: the guard is never the only barrier."""

    untrusted = connect_untrusted(published)
    try:
        # Bypass the guard deliberately and go straight to the engine.
        with pytest.raises(duckdb.PermissionException) as excinfo:
            untrusted.execute("SELECT * FROM read_csv_auto('/etc/passwd')")
        assert "file system operations are disabled" in str(excinfo.value)
    finally:
        untrusted.close()


def test_writing_through_the_untrusted_connection_is_refused(published: Path) -> None:
    untrusted = connect_untrusted(published)
    try:
        with pytest.raises(Exception):
            untrusted.execute("CREATE TABLE silver.injected AS SELECT 1")
    finally:
        untrusted.close()


def test_a_trusted_connection_is_still_refused_by_the_executor(published: Path) -> None:
    """The handoff must not be satisfiable by handing the agent a writable connection."""

    from src.lakehouse.db.connection import connect_trusted

    trusted = connect_trusted(published)
    try:
        with pytest.raises(TrustedConnectionError):
            QueryExecutor(trusted)
    finally:
        trusted.close()


def test_row_limit_is_enforced_on_the_agent_surface(published: Path) -> None:
    untrusted = connect_untrusted(published)
    try:
        result = QueryExecutor(untrusted).execute(
            "SELECT observation_date FROM silver.fact_observation ORDER BY observation_date",
            max_rows=2,
        )
        assert result.row_count == 2
        assert result.truncated is True
    finally:
        untrusted.close()
