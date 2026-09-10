"""Focused tests for the first real Bronze to Silver source mappings."""

from __future__ import annotations

from datetime import date, datetime, timezone
import inspect
from pathlib import Path

import pandas as pd
import pytest

from src.lakehouse.parsers.bddk_monthly import BDDK_MONTHLY_SCHEMA_VERSION, BddkMonthlyParser
from src.lakehouse.parsers.evds import EVDS_SCHEMA_VERSION, EvdsParser
from src.lakehouse.parsers.base import BaseParser
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.silver.adapters.bddk_monthly import bddk_monthly_to_staging
from src.lakehouse.silver.adapters.evds import evds_ktf12_to_staging
from src.lakehouse.silver.adapters import bddk_monthly as bddk_monthly_adapter
from src.lakehouse.silver.adapters import evds as evds_adapter
from src.lakehouse.silver.foundation import (
    SILVER_STAGING_COLUMNS,
    SilverValidationError,
    materialize_fact_observation_snapshot,
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
    batch = parser.parse(asset)
    bronze_path = ParquetStorage(tmp_path / "data/bronze").write(batch)
    return ParquetStorage.read(bronze_path), read_identity(bronze_path)


def test_bddk_monthly_adapter_maps_real_bronze_shape_to_generic_staging(
    tmp_path: Path,
) -> None:
    frame, identity = _bronze_from_fixture(
        tmp_path,
        fixture=FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json",
        source_id="bddk_monthly",
        dataset_id="bddk_monthly_housing_loans",
        parser=BddkMonthlyParser(),
        metadata={"requested_kalem_sutun": ["1534?Toplam"]},
    )

    staging = bddk_monthly_to_staging(frame, identity=identity)
    first = staging.iloc[0]

    assert list(staging.columns) == list(SILVER_STAGING_COLUMNS)
    assert len(staging) == 5
    assert first["series_id"] == "bddk_monthly:1534_Toplam"
    assert first["entity_id"] is None
    assert first["observation_date"] == date(2026, 6, 30)
    assert first["period_start"] == date(2026, 6, 1)
    assert first["period_end"] == date(2026, 6, 30)
    assert first["value_raw"] == 801438
    assert first["source_warning"] is None
    assert first["schema_version"] == BDDK_MONTHLY_SCHEMA_VERSION
    assert "entity_label" not in staging.columns
    assert "measure_label" not in staging.columns


def test_bddk_monthly_adapter_uses_calendar_month_end_and_rejects_invalid_month(
    tmp_path: Path,
) -> None:
    frame, identity = _bronze_from_fixture(
        tmp_path,
        fixture=FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json",
        source_id="bddk_monthly",
        dataset_id="bddk_monthly_housing_loans",
        parser=BddkMonthlyParser(),
        metadata={"requested_kalem_sutun": ["1534?Toplam"]},
    )
    one = frame.iloc[[0]].copy()
    for year, month, expected_end in (
        (2024, 2, date(2024, 2, 29)),
        (2025, 2, date(2025, 2, 28)),
        (2025, 4, date(2025, 4, 30)),
        (2025, 1, date(2025, 1, 31)),
    ):
        one.loc[one.index[0], "year_raw"] = year
        one.loc[one.index[0], "month_raw"] = month
        staging = bddk_monthly_to_staging(one, identity=identity)
        assert staging.loc[0, "period_start"] == date(year, month, 1)
        assert staging.loc[0, "period_end"] == expected_end
        assert staging.loc[0, "observation_date"] == expected_end

    invalid = one.copy()
    invalid.loc[invalid.index[0], "month_raw"] = 13
    with pytest.raises(SilverValidationError, match="invalid BDDK monthly"):
        bddk_monthly_to_staging(invalid, identity=identity)


def test_bddk_monthly_adapter_fails_closed_for_unsupported_series(
    tmp_path: Path,
) -> None:
    frame, identity = _bronze_from_fixture(
        tmp_path,
        fixture=FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json",
        source_id="bddk_monthly",
        dataset_id="bddk_monthly_housing_loans",
        parser=BddkMonthlyParser(),
        metadata={"requested_kalem_sutun": ["1534?Toplam"]},
    )
    frame.loc[frame.index[0], "series_id"] = "bddk_monthly:another_series"

    with pytest.raises(SilverValidationError, match="unsupported BDDK monthly series"):
        bddk_monthly_to_staging(frame, identity=identity)


def test_evds_adapter_maps_real_bronze_shape_and_preserves_raw_value(
    tmp_path: Path,
) -> None:
    frame, identity = _bronze_from_fixture(
        tmp_path,
        fixture=FIXTURE_ROOT / "evds/evds_ktf12_weekly.json",
        source_id="evds",
        dataset_id="evds_housing_interest",
        parser=EvdsParser(),
        metadata={"requested_series": ["TP.KTF12"]},
    )

    staging = evds_ktf12_to_staging(frame, identity=identity)
    first = staging.iloc[0]

    assert list(staging.columns) == list(SILVER_STAGING_COLUMNS)
    assert len(staging) == 5
    assert first["series_id"] == "evds:TP.KTF12"
    assert first["entity_id"] is None
    assert first["observation_date"] == date(2021, 1, 1)
    assert first["period_start"] is None
    assert first["period_end"] is None
    assert first["value_raw"] == "18.61"
    assert first["source_warning"] is None
    assert first["schema_version"] == EVDS_SCHEMA_VERSION
    assert "date_raw" not in staging.columns
    assert "unixtime" not in staging.columns


def test_evds_adapter_preserves_source_day_and_rejects_malformed_date(
    tmp_path: Path,
) -> None:
    frame, identity = _bronze_from_fixture(
        tmp_path,
        fixture=FIXTURE_ROOT / "evds/evds_ktf12_weekly.json",
        source_id="evds",
        dataset_id="evds_housing_interest",
        parser=EvdsParser(),
        metadata={"requested_series": ["TP.KTF12"]},
    )
    one = frame.iloc[[0]].copy()
    one.loc[one.index[0], "date_raw"] = "01-07-2021"

    staging = evds_ktf12_to_staging(one, identity=identity)
    assert staging.loc[0, "observation_date"] == date(2021, 1, 7)

    invalid = one.copy()
    invalid.loc[invalid.index[0], "date_raw"] = "2021-01-07"
    with pytest.raises(SilverValidationError, match="invalid EVDS date_raw"):
        evds_ktf12_to_staging(invalid, identity=identity)


def test_adapters_reject_bronze_identity_conflicts(tmp_path: Path) -> None:
    frame, identity = _bronze_from_fixture(
        tmp_path,
        fixture=FIXTURE_ROOT / "evds/evds_ktf12_weekly.json",
        source_id="evds",
        dataset_id="evds_housing_interest",
        parser=EvdsParser(),
        metadata={"requested_series": ["TP.KTF12"]},
    )
    conflicting = ParquetIdentity(
        source_id=identity.source_id,
        dataset_id=identity.dataset_id,
        artifact_sha256="a" * 64,
        schema_version=identity.schema_version,
    )

    with pytest.raises(SilverValidationError, match="artifact_sha256 conflicts"):
        evds_ktf12_to_staging(frame, identity=conflicting)


def test_real_evds_mapping_rejects_same_artifact_duplicate_but_preserves_revision(
    tmp_path: Path,
) -> None:
    frame, identity = _bronze_from_fixture(
        tmp_path,
        fixture=FIXTURE_ROOT / "evds/evds_ktf12_weekly.json",
        source_id="evds",
        dataset_id="evds_housing_interest",
        parser=EvdsParser(),
        metadata={"requested_series": ["TP.KTF12"]},
    )
    staging = evds_ktf12_to_staging(frame.iloc[[0]], identity=identity)
    duplicate = pd.concat([staging, staging], ignore_index=True)

    connection = bootstrap_database(":memory:")
    try:
        with pytest.raises(SilverValidationError, match="duplicate Silver identity"):
            materialize_fact_observation_snapshot(connection, duplicate)

        revision = staging.copy()
        revision["artifact_sha256"] = "b" * 64
        preserved = materialize_fact_observation_snapshot(
            connection, pd.concat([staging, revision], ignore_index=True)
        )
        assert len(preserved) == 2
        assert set(preserved["artifact_sha256"]) == {identity.artifact_sha256, "b" * 64}
    finally:
        connection.close()


def test_adapters_are_local_frame_mappers_without_connector_dependency() -> None:
    assert "requests" not in inspect.getsource(bddk_monthly_adapter)
    assert "BaseConnector" not in inspect.getsource(bddk_monthly_adapter)
    assert "requests" not in inspect.getsource(evds_adapter)
    assert "BaseConnector" not in inspect.getsource(evds_adapter)
