"""Small generic foundation for the frozen Silver V1 contract.

This module accepts a prepared, source-independent staging frame. Source adapters are
responsible for turning Bronze shapes into that frame; this module deliberately has no
knowledge of any concrete source, source-specific dates, or source-specific series.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import math
from numbers import Real
from pathlib import Path
from typing import Final

import duckdb
import pandas as pd

from ..contracts.identifiers import (
    validate_dataset_id,
    validate_run_id,
    validate_series_id,
    validate_sha256,
    validate_source_id,
)


class SilverValidationError(ValueError):
    """Raised when prepared staging data cannot produce valid Silver rows."""


SILVER_STAGING_COLUMNS: Final[tuple[str, ...]] = (
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
)
"""The only columns accepted at the generic Bronze-to-Silver staging boundary."""

FACT_OBSERVATION_COLUMNS: Final[tuple[str, ...]] = (
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
)
"""Final Silver V1 projection columns in contract order."""

QUALITY_FLAGS: Final[frozenset[str]] = frozenset(
    {"ok", "missing_value", "source_warning"}
)

_REQUIRED_STAGING_COLUMNS: Final[frozenset[str]] = frozenset(
    set(SILVER_STAGING_COLUMNS) - {"source_warning"}
)
_NON_NULL_STAGING_COLUMNS: Final[tuple[str, ...]] = (
    "series_id",
    "observation_date",
    "source_id",
    "dataset_id",
    "artifact_sha256",
    "fetched_at",
    "schema_version",
)
_MODEL_PATH = Path(__file__).resolve().parents[3] / "models" / "silver" / "fact_observation.sql"
_STAGING_RELATION = "silver_staging"
_MODEL_RELATION = "silver_fact_observation_model"


def _as_date(value: object, field_name: str, row_number: int) -> date | None:
    if value is None or value is pd.NA or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise SilverValidationError(
        f"{field_name} must be a canonical date at row {row_number}"
    )


def _as_utc(value: object, row_number: int) -> datetime:
    if value is None or value is pd.NA or pd.isna(value):
        raise SilverValidationError(f"fetched_at must not be NULL at row {row_number}")
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SilverValidationError(
            f"fetched_at must be timezone-aware at row {row_number}"
        )
    return value.astimezone(timezone.utc)


def _result_date(value: object) -> date | None:
    """Keep DATE columns as Python dates after DuckDB's pandas conversion."""

    if value is None or value is pd.NA or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise SilverValidationError(f"Silver date value has unexpected type: {type(value)!r}")


def prepare_staging_frame(staging: pd.DataFrame) -> pd.DataFrame:
    """Validate and return a generic, contract-ordered staging frame.

    The optional ``source_warning`` column is added as NULL when a source adapter has no
    row-level warning. Unknown columns are rejected so source-specific Bronze fields cannot
    cross the generic boundary accidentally.
    """

    if not isinstance(staging, pd.DataFrame):
        raise TypeError("staging must be a pandas DataFrame")

    columns = set(staging.columns)
    missing = sorted(_REQUIRED_STAGING_COLUMNS - columns)
    if missing:
        raise SilverValidationError(f"staging is missing required columns: {missing}")
    unexpected = sorted(columns - set(SILVER_STAGING_COLUMNS))
    if unexpected:
        raise SilverValidationError(f"staging contains unsupported columns: {unexpected}")

    prepared = staging.copy().reset_index(drop=True)
    if "source_warning" not in prepared:
        prepared["source_warning"] = None

    for field_name in _NON_NULL_STAGING_COLUMNS:
        if prepared[field_name].isna().any():
            raise SilverValidationError(f"staging field {field_name!r} must not be NULL")

    for row_number, row in prepared.iterrows():
        source_id = row["source_id"]
        dataset_id = row["dataset_id"]
        series_id = row["series_id"]
        artifact_sha256 = row["artifact_sha256"]
        schema_version = row["schema_version"]

        if not all(isinstance(value, str) for value in (source_id, dataset_id, series_id)):
            raise SilverValidationError(f"source identifiers must be strings at row {row_number}")
        validate_source_id(source_id)
        validate_dataset_id(dataset_id)
        validate_series_id(series_id, source_id=source_id)
        if not isinstance(artifact_sha256, str):
            raise SilverValidationError(f"artifact_sha256 must be a string at row {row_number}")
        validate_sha256(artifact_sha256)
        if not isinstance(schema_version, str) or not schema_version.strip():
            raise SilverValidationError(
                f"schema_version must be a non-empty string at row {row_number}"
            )

        entity_id = row["entity_id"]
        if entity_id is not None and entity_id is not pd.NA and not pd.isna(entity_id):
            if not isinstance(entity_id, str) or not entity_id.strip():
                raise SilverValidationError(
                    f"entity_id must be NULL or a non-empty string at row {row_number}"
                )

        for field_name in ("observation_date", "period_start", "period_end"):
            prepared.at[row_number, field_name] = _as_date(
                row[field_name], field_name, row_number
            )

        raw_value = row["value_raw"]
        if isinstance(raw_value, Real) and not isinstance(raw_value, bool):
            if not math.isfinite(float(raw_value)):
                raise SilverValidationError(
                    "non-null value_raw must be a finite DOUBLE: "
                    f"{raw_value!r}"
                )

        prepared.at[row_number, "fetched_at"] = _as_utc(row["fetched_at"], row_number)

        vintage_id = row["vintage_id"]
        if vintage_id is not None and vintage_id is not pd.NA and not pd.isna(vintage_id):
            if not isinstance(vintage_id, str) or not vintage_id.strip():
                raise SilverValidationError(
                    f"vintage_id must be NULL or a non-empty string at row {row_number}"
                )

        run_id = row["run_id"]
        if run_id is not None and run_id is not pd.NA and not pd.isna(run_id):
            prepared.at[row_number, "run_id"] = validate_run_id(run_id)

        warning = row["source_warning"]
        if warning is not None and warning is not pd.NA and not pd.isna(warning):
            if not isinstance(warning, str) or not warning.strip():
                raise SilverValidationError(
                    f"source_warning must be NULL or a non-empty string at row {row_number}"
                )

    # Keep nullable text columns as strings so an all-NULL column is not inferred as INTEGER
    # by DuckDB when the staging frame is registered.
    for field_name in ("entity_id", "vintage_id", "run_id", "source_warning"):
        prepared[field_name] = pd.array(prepared[field_name].tolist(), dtype="string")

    return prepared.loc[:, SILVER_STAGING_COLUMNS]


def _validate_sql_inputs(connection: duckdb.DuckDBPyConnection) -> None:
    invalid_value = connection.execute(
        """
        WITH converted AS (
            SELECT value_raw, TRY_CAST(value_raw AS DOUBLE) AS value
            FROM silver_staging
        )
        SELECT value_raw, value
        FROM converted
        WHERE value_raw IS NOT NULL
          AND (value IS NULL OR NOT isfinite(value))
        LIMIT 1
        """
    ).fetchone()
    if invalid_value is not None:
        raise SilverValidationError(
            "non-null value_raw must be a finite DOUBLE: "
            f"{invalid_value[0]!r}"
        )

    invalid_semantics = connection.execute(
        """
        SELECT s.series_id, m.series_id, m.frequency, m.unit, m.measure_type
        FROM silver_staging AS s
        LEFT JOIN meta.series AS m ON m.series_id = s.series_id
        WHERE m.series_id IS NULL
           OR m.source_id IS DISTINCT FROM s.source_id
           OR m.dataset_id IS DISTINCT FROM s.dataset_id
           OR m.frequency IS NULL
           OR NULLIF(TRIM(m.frequency), '') IS NULL
           OR m.unit IS NULL
           OR NULLIF(TRIM(m.unit), '') IS NULL
           OR m.measure_type IS NULL
           OR NULLIF(TRIM(m.measure_type), '') IS NULL
           OR m.measure_type = 'unknown'
        LIMIT 1
        """
    ).fetchone()
    if invalid_semantics is not None:
        raise SilverValidationError(
            "staging series is missing or has invalid catalog semantics: "
            f"{invalid_semantics[0]!r}"
        )

    duplicate = connection.execute(
        """
        SELECT series_id, entity_id, observation_date, artifact_sha256, COUNT(*) AS row_count
        FROM silver_staging
        GROUP BY series_id, entity_id, observation_date, artifact_sha256
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicate is not None:
        raise SilverValidationError(
            "duplicate Silver identity within one artifact: "
            f"series_id={duplicate[0]!r}, observation_date={duplicate[2]!r}, "
            f"artifact_sha256={duplicate[3]!r}, count={duplicate[4]}"
        )


def _unregister(connection: duckdb.DuckDBPyConnection, relation_name: str) -> None:
    try:
        connection.unregister(relation_name)
    except Exception:
        pass


def _validate_result(result: pd.DataFrame) -> None:
    if tuple(result.columns) != FACT_OBSERVATION_COLUMNS:
        raise SilverValidationError(
            "Silver model returned unexpected columns: " + repr(list(result.columns))
        )
    for field_name in (
        "series_id",
        "observation_date",
        "frequency",
        "unit",
        "measure_type",
        "quality_flag",
        "source_id",
        "dataset_id",
        "artifact_sha256",
        "fetched_at",
        "schema_version",
    ):
        if result[field_name].isna().any():
            raise SilverValidationError(f"Silver field {field_name!r} contains NULL")
    invalid_quality = set(result["quality_flag"].dropna().astype(str)) - QUALITY_FLAGS
    if invalid_quality:
        raise SilverValidationError(f"unsupported quality flags: {sorted(invalid_quality)}")


def materialize_fact_observation_snapshot(
    connection: duckdb.DuckDBPyConnection,
    staging: pd.DataFrame,
    *,
    model_path: Path = _MODEL_PATH,
) -> pd.DataFrame:
    """Replace ``silver.fact_observation`` with one complete validated snapshot.

    The caller must combine all intended source-adapter outputs before calling this operation.
    A later call replaces the entire trusted DuckDB table; it never appends, merges, or selects
    a current vintage. No source-specific adapter is invoked here.
    """

    prepared = prepare_staging_frame(staging)
    if not model_path.is_file():
        raise FileNotFoundError(model_path)

    _unregister(connection, _STAGING_RELATION)
    connection.register(_STAGING_RELATION, prepared)
    try:
        _validate_sql_inputs(connection)
        model_sql = model_path.read_text(encoding="utf-8").strip().rstrip(";")
        connection.execute(
            f"CREATE OR REPLACE TEMP VIEW {_MODEL_RELATION} AS {model_sql}"
        )
        result = connection.execute(f"SELECT * FROM {_MODEL_RELATION}").fetchdf()
        for field_name in ("observation_date", "period_start", "period_end"):
            result[field_name] = pd.Series(
                [_result_date(value) for value in result[field_name]],
                dtype="object",
            )
        _validate_result(result)
        connection.execute("CREATE SCHEMA IF NOT EXISTS silver")
        connection.execute(
            "CREATE OR REPLACE TABLE silver.fact_observation AS "
            f"SELECT * FROM {_MODEL_RELATION}"
        )
        return result
    finally:
        connection.execute(f"DROP VIEW IF EXISTS {_MODEL_RELATION}")
        _unregister(connection, _STAGING_RELATION)


__all__ = [
    "FACT_OBSERVATION_COLUMNS",
    "QUALITY_FLAGS",
    "SILVER_STAGING_COLUMNS",
    "SilverValidationError",
    "materialize_fact_observation_snapshot",
    "prepare_staging_frame",
]
