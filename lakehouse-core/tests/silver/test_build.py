"""The Bronze to Silver production step: what it publishes, and what it refuses.

Before this module existed, every caller of ``materialize_fact_observation_snapshot`` lived
under ``tests/``. Ingestion ended at Bronze and ``silver.fact_observation`` stayed empty in any
real database, so these tests deliberately go through the same entry point an operator uses.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest

from src.lakehouse.contracts.identifiers import new_run_id
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.parsers.bddk_finturk import BddkFinTurkParser
from src.lakehouse.parsers.bddk_monthly import BddkMonthlyParser
from src.lakehouse.parsers.base import BaseParser
from src.lakehouse.parsers.evds import EvdsParser
from src.lakehouse.silver.build import build_silver_snapshot, discover_bronze_artifacts
from src.lakehouse.silver.foundation import SilverValidationError
from src.lakehouse.storage.parquet import ParquetStorage
from src.lakehouse.storage.raw import RawStorage


FIXTURE_ROOT = Path("tests/fixtures/raw")
FETCHED_AT = datetime(2026, 9, 9, 8, tzinfo=timezone.utc)


def _write_bronze(
    data_root: Path,
    *,
    fixture: Path,
    source_id: str,
    dataset_id: str,
    parser: BaseParser,
    metadata: dict[str, object],
) -> Path:
    asset = RawStorage(data_root / "raw").store(
        source_id=source_id,
        dataset_id=dataset_id,
        locator=f"fixture://{fixture.name}",
        content=fixture.read_bytes(),
        media_type="application/json",
        fetched_at=FETCHED_AT,
        extension="json",
        metadata=metadata,
    )
    return ParquetStorage(data_root / "bronze").write(parser.parse(asset))


def _bddk_monthly(data_root: Path) -> Path:
    return _write_bronze(
        data_root,
        fixture=FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json",
        source_id="bddk_monthly",
        dataset_id="bddk_monthly_housing_loans",
        parser=BddkMonthlyParser(),
        metadata={"requested_kalem_sutun": ["1534?Toplam"]},
    )


def _evds_weekly(data_root: Path) -> Path:
    return _write_bronze(
        data_root,
        fixture=FIXTURE_ROOT / "evds/evds_ktf12_weekly.json",
        source_id="evds",
        dataset_id="evds_housing_interest",
        parser=EvdsParser(),
        metadata={"requested_series": ["TP.KTF12"]},
    )


def _finturk(data_root: Path) -> Path:
    return _write_bronze(
        data_root,
        fixture=FIXTURE_ROOT / "bddk_finturk/bddk_finturk_yalova_2025_9.json",
        source_id="bddk_finturk",
        dataset_id="bddk_finturk_yalova_housing_loans",
        parser=BddkFinTurkParser(),
        metadata={"requested_sehir": "YALOVA"},
    )


def _window_bronze(
    tmp_path: Path, data_root: Path, items: list[dict], name: str
) -> Path:
    """Write one EVDS window as its own Bronze artifact, from its own RAW bytes."""

    window = tmp_path / f"{name}.json"
    window.write_text(
        json.dumps({"totalCount": len(items), "items": items}), encoding="utf-8"
    )
    return _write_bronze(
        data_root,
        fixture=window,
        source_id="evds",
        dataset_id="evds_housing_interest",
        parser=EvdsParser(),
        metadata={"requested_series": ["TP.KTF12"]},
    )


@pytest.fixture
def connection(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    con = bootstrap_database(tmp_path / "data" / "lakehouse.duckdb")
    yield con
    con.close()


def test_build_publishes_every_catalogued_bronze_observation(
    tmp_path: Path, connection: duckdb.DuckDBPyConnection
) -> None:
    data_root = tmp_path / "data"
    _bddk_monthly(data_root)
    _evds_weekly(data_root)

    report = build_silver_snapshot(connection, bronze_root=data_root / "bronze")

    assert report.artifacts_staged == 2
    assert report.rows_published == report.rows_staged > 0
    assert set(report.series_published) == {
        "bddk_monthly:1534_Toplam",
        "evds:TP.KTF12",
    }
    published = connection.execute(
        "SELECT count(*), count(DISTINCT series_id) FROM silver.fact_observation"
    ).fetchone()
    assert published == (report.rows_published, 2)


def test_build_is_reproducible_over_the_same_bronze_tree(
    tmp_path: Path, connection: duckdb.DuckDBPyConnection
) -> None:
    """A snapshot replaces the table, so running twice must not grow or reorder it."""

    data_root = tmp_path / "data"
    _bddk_monthly(data_root)
    _evds_weekly(data_root)

    build_silver_snapshot(connection, bronze_root=data_root / "bronze")
    first = connection.execute("SELECT * FROM silver.fact_observation").fetchdf()
    build_silver_snapshot(connection, bronze_root=data_root / "bronze")
    second = connection.execute("SELECT * FROM silver.fact_observation").fetchdf()

    assert first.equals(second)


def test_build_publishes_the_catalogued_measure_and_withholds_the_rest_with_a_reason(
    tmp_path: Path, connection: duckdb.DuckDBPyConnection
) -> None:
    """One FinTürk response is a grid; here the catalog registers one column of it.

    (Reproduced by deleting the other seven YALOVA entries below.) Seven of its eight measure
    columns are then not catalogued at all. Leaving them out is correct.
    Leaving them out without saying so is how a province quietly ends up with no rows and
    nobody can explain why, so each exclusion is counted against its series in the report.
    """

    data_root = tmp_path / "data"
    _bddk_monthly(data_root)
    _finturk(data_root)
    # 2026-09-13'ten beri katalog sekiz sütunun hepsini tanımlar (docs/sources/bddk_finturk.md,
    # Genişletme). Bu test "kataloglanmayan tutulur ve söylenir" davranışını ölçer; o durumu
    # yeniden kurmak için YALOVA'nın konut dışı yedi girdisi bu bağlantıdan çıkarılır.
    connection.execute(
        "DELETE FROM meta.series WHERE series_id LIKE 'bddk_finturk:YALOVA_%' "
        "AND series_id <> 'bddk_finturk:YALOVA_KonutKredisi'"
    )

    report = build_silver_snapshot(connection, bronze_root=data_root / "bronze")

    assert report.artifacts_staged == 2
    assert "bddk_finturk:YALOVA_KonutKredisi" in report.series_published
    assert report.withheld_series["bddk_finturk:YALOVA_TasitKredisi"] == "not in meta.series"
    assert len(report.withheld_series) == 7
    assert "series withheld        : 7" in report.render()

    quarter = connection.execute(
        """
        SELECT observation_date, period_start, unit, entity_id
        FROM silver.fact_observation
        WHERE series_id = 'bddk_finturk:YALOVA_KonutKredisi'
        """
    ).fetchone()
    assert quarter == (date(2025, 9, 30), date(2025, 7, 1), "TRY_th", "bddk:10001")


def test_build_keeps_the_parser_warning_that_produced_a_quality_flag(
    tmp_path: Path, connection: duckdb.DuckDBPyConnection
) -> None:
    """A rebuilt row must not look cleaner than the ingestion that produced it.

    ``quality_flag`` is derived from the parse warning, and Bronze does not carry warnings —
    they live in ``meta.ingest_warning``. If the rebuild did not read them back, every flagged
    observation would silently return as ``ok``.
    """

    data_root = tmp_path / "data"
    bronze_path = _evds_weekly(data_root)
    artifact_sha256 = bronze_path.stem.split("=", 1)[1]
    run_id = new_run_id()

    connection.execute(
        "INSERT INTO meta.run (run_id, started_at, status) VALUES (?, now(), 'success')",
        [run_id],
    )
    connection.execute(
        """
        INSERT INTO meta.run_artifact
            (run_id, artifact_sha256, source_id, dataset_id, fetched_at)
        VALUES (?, ?, 'evds', 'evds_housing_interest', now())
        """,
        [run_id, artifact_sha256],
    )
    connection.execute(
        """
        INSERT INTO meta.ingest_warning
            (run_id, warning_seq, source_id, dataset_id, artifact_sha256, message, created_at)
        VALUES (?, 1, 'evds', 'evds_housing_interest', ?, 'value coerced', now())
        """,
        [run_id, artifact_sha256],
    )

    build_silver_snapshot(connection, bronze_root=data_root / "bronze")

    flags, run_ids = connection.execute(
        """
        SELECT DISTINCT quality_flag, run_id FROM silver.fact_observation
        """
    ).fetchone()
    assert flags == "source_warning"
    assert run_ids == run_id


def test_identical_boundary_observations_collapse_once(
    tmp_path: Path, connection: duckdb.DuckDBPyConnection
) -> None:
    """EVDS windowing writes one artifact per window and windows share their boundary.

    Two artifacts that agree about the same observation are one observation, not two rows that
    would double count in every later aggregate.
    """

    data_root = tmp_path / "data"
    payload = json.loads(
        (FIXTURE_ROOT / "evds/evds_ktf12_weekly.json").read_text(encoding="utf-8")
    )
    items = payload["items"]
    assert len(items) == 5, "fixture precondition"

    # Two windows that overlap on exactly one observation, which is what the EVDS windowed
    # ingestion writes: separate RAW evidence per window, the boundary present in both.
    first = _window_bronze(tmp_path, data_root, items[:3], "w1")
    second = _window_bronze(tmp_path, data_root, items[2:], "w2")
    assert first != second, "the two windows must be distinct artifacts"

    report = build_silver_snapshot(connection, bronze_root=data_root / "bronze")

    assert report.rows_staged == 6
    assert report.deduplicated_rows == 1
    assert report.rows_published == 5


def test_disagreeing_observations_stop_the_build(
    tmp_path: Path, connection: duckdb.DuckDBPyConnection
) -> None:
    """Two artifacts that disagree are a revision. Picking one silently is the failure mode."""

    data_root = tmp_path / "data"
    _evds_weekly(data_root)
    revised = FIXTURE_ROOT / "evds/evds_ktf12_weekly.json"
    payload = revised.read_text(encoding="utf-8").replace('"18.61"', '"19.61"', 1)
    revised_path = tmp_path / "revised.json"
    revised_path.write_text(payload, encoding="utf-8")
    _write_bronze(
        data_root,
        fixture=revised_path,
        source_id="evds",
        dataset_id="evds_housing_interest",
        parser=EvdsParser(),
        metadata={"requested_series": ["TP.KTF12"]},
    )

    with pytest.raises(SilverValidationError, match="This is a revision, not a duplicate"):
        build_silver_snapshot(connection, bronze_root=data_root / "bronze")


def test_discovery_never_reads_a_silver_representation_back_in(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _bddk_monthly(data_root)
    silver_like = data_root / "bronze" / "representation=silver" / "x.parquet"
    silver_like.parent.mkdir(parents=True, exist_ok=True)
    silver_like.write_bytes(b"not parquet")

    found = discover_bronze_artifacts(data_root / "bronze")

    assert len(found) == 1
    assert "representation=silver" not in str(found[0])


def test_missing_bronze_tree_is_an_empty_report_not_a_crash(
    tmp_path: Path, connection: duckdb.DuckDBPyConnection
) -> None:
    report = build_silver_snapshot(connection, bronze_root=tmp_path / "nowhere")

    assert report.artifacts_found == 0
    assert report.rows_published == 0
