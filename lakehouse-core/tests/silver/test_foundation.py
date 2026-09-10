"""Offline tests for the generic Silver V1 foundation."""

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.silver.foundation import (
    FACT_OBSERVATION_COLUMNS,
    SilverValidationError,
    materialize_fact_observation_snapshot,
)


FETCHED_AT = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)
ARTIFACT_A = "a" * 64
ARTIFACT_B = "b" * 64


def _staging(**overrides: object) -> pd.DataFrame:
    row: dict[str, object] = {
        "series_id": "evds:TP.KTF12",
        "entity_id": None,
        "observation_date": date(2026, 1, 2),
        "period_start": None,
        "period_end": None,
        "value_raw": "18.61",
        "source_id": "evds",
        "dataset_id": "evds_housing_interest",
        "artifact_sha256": ARTIFACT_A,
        "fetched_at": FETCHED_AT,
        "schema_version": "evds_observations.v1",
        "vintage_id": None,
        "run_id": None,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _connection(tmp_path: Path):
    return bootstrap_database(tmp_path / "lakehouse.duckdb")


def _add_series(
    connection,
    *,
    series_id: str,
    source_id: str = "demo_energy",
    dataset_id: str = "demo_energy_load",
    frequency: str = "hourly",
    unit: str | None = "MW",
    measure_type: str = "count",
    semantic_confidence: str = "verified",
) -> None:
    connection.execute(
        """
        INSERT INTO meta.series (
            series_id, source_id, native_code, dataset_id, name_tr, description,
            aliases, tags, frequency, week_anchor, unit, measure_type, default_agg,
            cumulative_reset, semantic_confidence, semantic_source, catalog_content_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, [], [], ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            series_id,
            source_id,
            series_id.split(":", 1)[1],
            dataset_id,
            "Demo series",
            "Synthetic test-only series",
            frequency,
            None,
            unit,
            measure_type,
            None,
            None,
            semantic_confidence,
            "manual",
            "c" * 64,
        ],
    )


def test_healthy_generic_row_uses_catalog_semantics() -> None:
    connection = bootstrap_database(":memory:")
    try:
        result = materialize_fact_observation_snapshot(connection, _staging())

        assert list(result.columns) == list(FACT_OBSERVATION_COLUMNS)
        assert result.loc[0, "value"] == pytest.approx(18.61)
        assert result.loc[0, "quality_flag"] == "ok"
        assert result.loc[0, "frequency"] == "weekly"
        assert result.loc[0, "unit"] == "pct"
        assert result.loc[0, "measure_type"] == "rate"
    finally:
        connection.close()


def test_true_null_value_is_preserved_and_flagged() -> None:
    connection = bootstrap_database(":memory:")
    try:
        result = materialize_fact_observation_snapshot(connection, _staging(value_raw=None))

        assert pd.isna(result.loc[0, "value"])
        assert result.loc[0, "quality_flag"] == "missing_value"
    finally:
        connection.close()


def test_explicit_row_warning_is_flagged() -> None:
    connection = bootstrap_database(":memory:")
    try:
        result = materialize_fact_observation_snapshot(
            connection, _staging(source_warning="source row requires review")
        )

        assert result.loc[0, "quality_flag"] == "source_warning"
    finally:
        connection.close()


def test_invalid_non_null_numeric_value_fails() -> None:
    connection = bootstrap_database(":memory:")
    try:
        with pytest.raises(SilverValidationError, match="DOUBLE"):
            materialize_fact_observation_snapshot(connection, _staging(value_raw="abc"))
    finally:
        connection.close()


def test_finite_numeric_float_is_accepted() -> None:
    connection = bootstrap_database(":memory:")
    try:
        result = materialize_fact_observation_snapshot(
            connection, _staging(value_raw=18.61)
        )
        assert result.loc[0, "value"] == pytest.approx(18.61)
        assert result.loc[0, "quality_flag"] == "ok"
    finally:
        connection.close()


@pytest.mark.parametrize(
    "value_raw",
    [
        "nan",
        "NaN",
        "inf",
        "+inf",
        "-inf",
        "infinity",
        "+Infinity",
        "-Infinity",
        pytest.param(float("nan"), id="float-nan"),
        pytest.param(float("inf"), id="float-inf"),
        pytest.param(float("-inf"), id="float-negative-inf"),
    ],
)
def test_non_finite_numeric_values_fail_closed(value_raw: object) -> None:
    connection = bootstrap_database(":memory:")
    try:
        with pytest.raises(SilverValidationError, match="finite DOUBLE"):
            materialize_fact_observation_snapshot(
                connection, _staging(value_raw=value_raw)
            )
    finally:
        connection.close()


def test_unknown_series_fails_closed() -> None:
    connection = bootstrap_database(":memory:")
    try:
        with pytest.raises(SilverValidationError, match="catalog semantics"):
            materialize_fact_observation_snapshot(connection, _staging(series_id="evds:TP.UNKNOWN"))
    finally:
        connection.close()


def test_missing_unit_fails_closed() -> None:
    connection = bootstrap_database(":memory:", catalog_root=None)
    try:
        _add_series(connection, series_id="demo_energy:missing_unit", unit=None)
        staging = _staging(
            series_id="demo_energy:missing_unit",
            source_id="demo_energy",
            dataset_id="demo_energy_load",
            schema_version="demo_energy.v1",
        )
        with pytest.raises(SilverValidationError, match="catalog semantics"):
            materialize_fact_observation_snapshot(connection, staging)
    finally:
        connection.close()


def test_unknown_measure_type_fails_closed() -> None:
    connection = bootstrap_database(":memory:", catalog_root=None)
    try:
        _add_series(connection, series_id="demo_energy:unknown_measure", measure_type="unknown")
        staging = _staging(
            series_id="demo_energy:unknown_measure",
            source_id="demo_energy",
            dataset_id="demo_energy_load",
            schema_version="demo_energy.v1",
        )
        with pytest.raises(SilverValidationError, match="catalog semantics"):
            materialize_fact_observation_snapshot(connection, staging)
    finally:
        connection.close()


def test_invalid_observation_date_fails() -> None:
    connection = bootstrap_database(":memory:")
    try:
        with pytest.raises(SilverValidationError, match="observation_date"):
            materialize_fact_observation_snapshot(connection, _staging(observation_date="not-a-date"))
    finally:
        connection.close()


def test_duplicate_same_artifact_identity_fails() -> None:
    connection = bootstrap_database(":memory:")
    try:
        duplicate = pd.concat([_staging(), _staging()], ignore_index=True)
        with pytest.raises(SilverValidationError, match="duplicate Silver identity"):
            materialize_fact_observation_snapshot(connection, duplicate)
    finally:
        connection.close()


def test_different_artifacts_for_same_observation_are_preserved() -> None:
    connection = bootstrap_database(":memory:")
    try:
        revisions = pd.concat(
            [_staging(artifact_sha256=ARTIFACT_A), _staging(artifact_sha256=ARTIFACT_B)],
            ignore_index=True,
        )
        result = materialize_fact_observation_snapshot(connection, revisions)

        assert len(result) == 2
        assert set(result["artifact_sha256"]) == {ARTIFACT_A, ARTIFACT_B}
    finally:
        connection.close()


def test_null_entity_id_is_same_duplicate_identity() -> None:
    connection = bootstrap_database(":memory:")
    try:
        duplicate = pd.concat(
            [_staging(entity_id=None), _staging(entity_id=None)], ignore_index=True
        )
        with pytest.raises(SilverValidationError, match="duplicate Silver identity"):
            materialize_fact_observation_snapshot(connection, duplicate)
    finally:
        connection.close()


def test_source_specific_columns_are_rejected_at_generic_boundary() -> None:
    connection = bootstrap_database(":memory:")
    try:
        staging = _staging()
        staging["locator"] = "https://example.test/source"
        with pytest.raises(SilverValidationError, match="unsupported columns"):
            materialize_fact_observation_snapshot(connection, staging)
    finally:
        connection.close()


def test_generic_series_uses_catalog_values_without_finance_assumptions() -> None:
    connection = bootstrap_database(":memory:", catalog_root=None)
    try:
        _add_series(
            connection,
            series_id="demo_energy:load",
            unit="MW",
            measure_type="count",
        )
        staging = _staging(
            series_id="demo_energy:load",
            source_id="demo_energy",
            dataset_id="demo_energy_load",
            schema_version="demo_energy.v1",
            value_raw="42.5",
        )
        result = materialize_fact_observation_snapshot(connection, staging)

        assert result.loc[0, "unit"] == "MW"
        assert result.loc[0, "measure_type"] == "count"
        assert result.loc[0, "frequency"] == "hourly"
    finally:
        connection.close()


def test_same_staging_and_catalog_are_deterministic() -> None:
    connection = bootstrap_database(":memory:")
    try:
        first = materialize_fact_observation_snapshot(connection, _staging())
        second = materialize_fact_observation_snapshot(connection, _staging())

        pd.testing.assert_frame_equal(first, second)
    finally:
        connection.close()


def test_snapshot_api_explicitly_replaces_previous_complete_snapshot() -> None:
    connection = bootstrap_database(":memory:")
    snapshot_a = _staging()
    snapshot_b = _staging(
        series_id="evds:TP.KFE.TR",
        dataset_id="evds_housing_price_index",
        observation_date=date(2026, 1, 31),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        value_raw="211.73",
        artifact_sha256=ARTIFACT_B,
    )

    try:
        first = materialize_fact_observation_snapshot(connection, snapshot_a)
        assert set(first["series_id"]) == {"evds:TP.KTF12"}

        second = materialize_fact_observation_snapshot(connection, snapshot_b)
        assert set(second["series_id"]) == {"evds:TP.KFE.TR"}
        assert connection.execute(
            "SELECT series_id, artifact_sha256 FROM silver.fact_observation"
        ).fetchall() == [("evds:TP.KFE.TR", ARTIFACT_B)]
    finally:
        connection.close()
