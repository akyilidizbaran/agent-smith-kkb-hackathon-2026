"""Focused tests for the BDDK Weekly and EVDS KFE Silver mappings."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.parsers.base import BaseParser
from src.lakehouse.parsers.bddk_weekly import BddkWeeklyParser
from src.lakehouse.parsers.evds import EvdsParser
from src.lakehouse.silver.adapters.bddk_weekly import bddk_weekly_to_staging
from src.lakehouse.silver.adapters.evds import evds_kfe_to_staging
from src.lakehouse.silver.foundation import (
    SILVER_STAGING_COLUMNS,
    SilverValidationError,
    materialize_fact_observation,
)
from src.lakehouse.storage.parquet import ParquetIdentity, ParquetStorage, read_identity
from src.lakehouse.storage.raw import RawStorage


FIXTURE_ROOT = Path("tests/fixtures/raw")
FETCHED_AT = datetime(2026, 9, 9, 8, tzinfo=timezone.utc)


def _bronze_from_fixture(
    tmp_path: Path,
    *,
    fixture: Path,
    source_id: str,
    dataset_id: str,
    parser: BaseParser,
    metadata: dict[str, object],
) -> tuple[pd.DataFrame, ParquetIdentity]:
    raw_storage = RawStorage(tmp_path / "data/raw")
    asset = raw_storage.store(
        source_id=source_id,
        dataset_id=dataset_id,
        locator=f"fixture://{fixture.name}",
        content=fixture.read_bytes(),
        media_type="application/json",
        fetched_at=FETCHED_AT,
        extension="json",
        metadata=metadata,
    )
    batch = parser.parse(asset)  # type: ignore[attr-defined]
    bronze_path = ParquetStorage(tmp_path / "data/bronze").write(batch)
    return ParquetStorage.read(bronze_path), read_identity(bronze_path)


def _bddk_weekly_bronze(tmp_path: Path) -> tuple[pd.DataFrame, ParquetIdentity]:
    return _bronze_from_fixture(
        tmp_path,
        fixture=FIXTURE_ROOT / "bddk_weekly/bddk_weekly_housing_loans.json",
        source_id="bddk_weekly",
        dataset_id="bddk_weekly_housing_loans",
        parser=BddkWeeklyParser(),
        metadata={
            "requested_chart_id": "1.0.4",
            "requested_kalem_id": "5690",
            "expected_measure_label": "a) Konut",
            "expected_currency": "TRY",
            "expected_column": "Toplam",
            "requested_column": "3",
            "requested_taraf": "10001",
        },
    )


def _kfe_bronze(tmp_path: Path) -> tuple[pd.DataFrame, ParquetIdentity]:
    return _bronze_from_fixture(
        tmp_path,
        fixture=FIXTURE_ROOT / "evds/evds_kfe_monthly.json",
        source_id="evds",
        dataset_id="evds_housing_price_index",
        parser=EvdsParser(),
        metadata={"requested_series": ["TP.KFE.TR"]},
    )


def test_bddk_weekly_maps_real_fixture_and_catalog_semantics(tmp_path: Path) -> None:
    frame, identity = _bddk_weekly_bronze(tmp_path)
    staging = bddk_weekly_to_staging(frame, identity=identity)

    assert list(staging.columns) == list(SILVER_STAGING_COLUMNS)
    assert len(staging) == 5
    assert staging.loc[0, "series_id"] == "bddk_weekly:5690_3"
    assert staging.loc[0, "observation_date"] == date(2026, 1, 2)
    assert staging.loc[0, "value_raw"] == 679216.118
    assert staging.loc[0, "entity_id"] is None
    assert staging["source_warning"].isna().all()
    assert staging.loc[0, "schema_version"] == "bddk_weekly_observations.v1"
    assert not {"date_raw", "entity_code", "column_label", "series_title"}.intersection(
        staging.columns
    )

    connection = bootstrap_database(":memory:")
    try:
        result = materialize_fact_observation(connection, staging)
        row = connection.execute(
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
            identity.artifact_sha256,
        )
        assert len(result) == 5
        assert result.loc[0, "schema_version"] == identity.schema_version
    finally:
        connection.close()


def test_bddk_weekly_preserves_non_friday_date_and_rejects_malformed_date(
    tmp_path: Path,
) -> None:
    frame, identity = _bddk_weekly_bronze(tmp_path)
    staging = bddk_weekly_to_staging(frame, identity=identity)

    # 19.03.2026 is Thursday; the catalog's Friday anchor must not rewrite it.
    thursday = staging.loc[staging["observation_date"] == date(2026, 3, 19), "observation_date"]
    assert thursday.iloc[0].weekday() == 3

    invalid = frame.iloc[[0]].copy()
    invalid.loc[invalid.index[0], "date_raw"] = "2026-01-02"
    with pytest.raises(SilverValidationError, match="invalid BDDK weekly date_raw"):
        bddk_weekly_to_staging(invalid, identity=identity)


def test_bddk_weekly_null_and_invalid_numeric_values_use_generic_foundation(
    tmp_path: Path,
) -> None:
    frame, identity = _bddk_weekly_bronze(tmp_path)
    one = frame.iloc[[0]].copy()

    missing = bddk_weekly_to_staging(one.assign(value_raw=None), identity=identity)
    connection = bootstrap_database(":memory:")
    try:
        result = materialize_fact_observation(connection, missing)
        assert pd.isna(result.loc[0, "value"])
        assert result.loc[0, "quality_flag"] == "missing_value"

        invalid = bddk_weekly_to_staging(one.assign(value_raw="abc"), identity=identity)
        with pytest.raises(SilverValidationError, match="DOUBLE"):
            materialize_fact_observation(connection, invalid)
    finally:
        connection.close()


def test_bddk_weekly_rejects_unsupported_series(tmp_path: Path) -> None:
    frame, identity = _bddk_weekly_bronze(tmp_path)
    frame.loc[frame.index[0], "series_id"] = "bddk_weekly:other"

    with pytest.raises(SilverValidationError, match="unsupported BDDK weekly series"):
        bddk_weekly_to_staging(frame, identity=identity)


def test_evds_kfe_maps_real_fixture_without_base_year_or_semantic_leakage(
    tmp_path: Path,
) -> None:
    frame, identity = _kfe_bronze(tmp_path)
    staging = evds_kfe_to_staging(frame, identity=identity)

    assert list(staging.columns) == list(SILVER_STAGING_COLUMNS)
    assert len(staging) == 3
    assert staging.loc[0, "series_id"] == "evds:TP.KFE.TR"
    assert staging.loc[0, "period_start"] == date(2026, 1, 1)
    assert staging.loc[0, "period_end"] == date(2026, 1, 31)
    assert staging.loc[0, "observation_date"] == date(2026, 1, 31)
    assert staging.loc[0, "value_raw"] == "211.73"
    assert staging.loc[0, "entity_id"] is None
    assert not {"date_raw", "unixtime", "series_name", "series_column"}.intersection(
        staging.columns
    )

    connection = bootstrap_database(":memory:")
    try:
        result = materialize_fact_observation(connection, staging)
        row = connection.execute(
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
            identity.artifact_sha256,
        )
        assert "semantic_confidence" not in result.columns
        assert len(result) == 3
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("raw", "period_start", "period_end"),
    [
        ("04-2025", date(2025, 4, 1), date(2025, 4, 30)),
        ("03-2025", date(2025, 3, 1), date(2025, 3, 31)),
        ("02-2025", date(2025, 2, 1), date(2025, 2, 28)),
        ("02-2024", date(2024, 2, 1), date(2024, 2, 29)),
    ],
)
def test_evds_kfe_uses_calendar_month_boundaries(
    tmp_path: Path, raw: str, period_start: date, period_end: date
) -> None:
    frame, identity = _kfe_bronze(tmp_path)
    one = frame.iloc[[0]].copy()
    one.loc[one.index[0], "date_raw"] = raw

    staging = evds_kfe_to_staging(one, identity=identity)
    assert staging.loc[0, "period_start"] == period_start
    assert staging.loc[0, "period_end"] == period_end
    assert staging.loc[0, "observation_date"] == period_end


@pytest.mark.parametrize("raw", ["2-2025", "02/2025", "13-2025", "02-25"])
def test_evds_kfe_rejects_malformed_or_invalid_month(
    tmp_path: Path, raw: str
) -> None:
    frame, identity = _kfe_bronze(tmp_path)
    one = frame.iloc[[0]].copy()
    one.loc[one.index[0], "date_raw"] = raw

    with pytest.raises(SilverValidationError, match="invalid EVDS KFE date_raw"):
        evds_kfe_to_staging(one, identity=identity)


def test_evds_kfe_null_and_invalid_numeric_values_use_generic_foundation(
    tmp_path: Path,
) -> None:
    frame, identity = _kfe_bronze(tmp_path)
    one = frame.iloc[[0]].copy()

    missing = evds_kfe_to_staging(one.assign(value_raw=None), identity=identity)
    connection = bootstrap_database(":memory:")
    try:
        result = materialize_fact_observation(connection, missing)
        assert pd.isna(result.loc[0, "value"])
        assert result.loc[0, "quality_flag"] == "missing_value"

        invalid = evds_kfe_to_staging(one.assign(value_raw="abc"), identity=identity)
        with pytest.raises(SilverValidationError, match="DOUBLE"):
            materialize_fact_observation(connection, invalid)
    finally:
        connection.close()


def test_evds_kfe_rejects_unsupported_series(tmp_path: Path) -> None:
    frame, identity = _kfe_bronze(tmp_path)
    frame.loc[frame.index[0], "series_id"] = "evds:TP.OTHER"

    with pytest.raises(SilverValidationError, match="unsupported EVDS series"):
        evds_kfe_to_staging(frame, identity=identity)


@pytest.mark.parametrize(
    ("fixture", "source_id", "dataset_id", "parser", "metadata", "adapter"),
    [
        (
            FIXTURE_ROOT / "bddk_weekly/bddk_weekly_housing_loans.json",
            "bddk_weekly",
            "bddk_weekly_housing_loans",
            BddkWeeklyParser(),
            {
                "requested_chart_id": "1.0.4",
                "requested_kalem_id": "5690",
                "expected_measure_label": "a) Konut",
                "expected_currency": "TRY",
                "expected_column": "Toplam",
                "requested_column": "3",
                "requested_taraf": "10001",
            },
            bddk_weekly_to_staging,
        ),
        (
            FIXTURE_ROOT / "evds/evds_kfe_monthly.json",
            "evds",
            "evds_housing_price_index",
            EvdsParser(),
            {"requested_series": ["TP.KFE.TR"]},
            evds_kfe_to_staging,
        ),
    ],
    ids=["bddk-weekly", "evds-kfe"],
)
def test_both_new_mappings_share_duplicate_and_revision_policy(
    tmp_path: Path,
    fixture: Path,
    source_id: str,
    dataset_id: str,
    parser: object,
    metadata: dict[str, object],
    adapter: object,
) -> None:
    frame, identity = _bronze_from_fixture(
        tmp_path,
        fixture=fixture,
        source_id=source_id,
        dataset_id=dataset_id,
        parser=parser,
        metadata=metadata,
    )
    staging = adapter(frame.iloc[[0]], identity=identity)  # type: ignore[operator]
    duplicate = pd.concat([staging, staging], ignore_index=True)
    connection = bootstrap_database(":memory:")
    try:
        with pytest.raises(SilverValidationError, match="duplicate Silver identity"):
            materialize_fact_observation(connection, duplicate)

        revision = staging.copy()
        revision["artifact_sha256"] = "c" * 64
        preserved = materialize_fact_observation(
            connection, pd.concat([staging, revision], ignore_index=True)
        )
        assert len(preserved) == 2
        assert set(preserved["artifact_sha256"]) == {identity.artifact_sha256, "c" * 64}
    finally:
        connection.close()
