"""Map the first BDDK monthly Bronze series to generic Silver staging."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from numbers import Integral

import pandas as pd

from ...parsers.bddk_monthly import BDDK_MONTHLY_SCHEMA_VERSION
from ...silver.foundation import SILVER_STAGING_COLUMNS, SilverValidationError
from ...storage.parquet import ParquetIdentity


SUPPORTED_SERIES_ID = "bddk_monthly:1534_Toplam"
"""The only BDDK monthly series mapped by this first Silver slice."""

_REQUIRED_BRONZE_COLUMNS = frozenset(
    {
        "source_id",
        "dataset_id",
        "series_id",
        "year_raw",
        "month_raw",
        "value_raw",
        "artifact_sha256",
        "fetched_at",
    }
)


def _validate_input(frame: pd.DataFrame, identity: ParquetIdentity) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    missing = sorted(_REQUIRED_BRONZE_COLUMNS - set(frame.columns))
    if missing:
        raise SilverValidationError(f"BDDK monthly Bronze frame is missing columns: {missing}")
    if frame.empty:
        raise SilverValidationError("BDDK monthly Bronze frame must not be empty")
    if identity.schema_version != BDDK_MONTHLY_SCHEMA_VERSION:
        raise SilverValidationError(
            "BDDK monthly Bronze schema_version mismatch: "
            f"expected {BDDK_MONTHLY_SCHEMA_VERSION!r}, got {identity.schema_version!r}"
        )

    expected = {
        "source_id": identity.source_id,
        "dataset_id": identity.dataset_id,
        "artifact_sha256": identity.artifact_sha256,
    }
    for column, value in expected.items():
        if any(row_value != value for row_value in frame[column].tolist()):
            raise SilverValidationError(
                f"BDDK monthly Bronze {column} conflicts with Parquet identity"
            )
    if any(row_value != SUPPORTED_SERIES_ID for row_value in frame["series_id"].tolist()):
        raise SilverValidationError(
            f"unsupported BDDK monthly series; only {SUPPORTED_SERIES_ID!r} is mapped"
        )


def _period_bounds(year_raw: object, month_raw: object, row_number: int) -> tuple[date, date]:
    if (
        isinstance(year_raw, bool)
        or isinstance(month_raw, bool)
        or not isinstance(year_raw, Integral)
        or not isinstance(month_raw, Integral)
    ):
        raise SilverValidationError(
            f"BDDK monthly year_raw/month_raw must be integer values at row {row_number}"
        )

    try:
        year = int(year_raw)
        month = int(month_raw)
        period_start = date(year, month, 1)
        period_end = date(year, month, monthrange(year, month)[1])
    except (TypeError, ValueError, OverflowError) as exc:
        raise SilverValidationError(
            f"invalid BDDK monthly year_raw/month_raw at row {row_number}: "
            f"{year_raw!r}/{month_raw!r}"
        ) from exc
    return period_start, period_end


def bddk_monthly_to_staging(
    frame: pd.DataFrame, *, identity: ParquetIdentity
) -> pd.DataFrame:
    """Map ``1534_Toplam`` Bronze rows to the generic Silver staging contract.

    Only the source's year/month representation is interpreted here. Values remain raw,
    entity identity is deliberately NULL, and frequency/unit/measure semantics come from
    ``meta.series`` in the generic Silver foundation.
    """

    _validate_input(frame, identity)
    records: list[dict[str, object]] = []
    for row_number, (_, row) in enumerate(frame.iterrows()):
        period_start, period_end = _period_bounds(
            row["year_raw"], row["month_raw"], row_number
        )
        records.append(
            {
                "series_id": row["series_id"],
                "entity_id": None,
                "observation_date": period_end,
                "period_start": period_start,
                "period_end": period_end,
                "value_raw": row["value_raw"],
                "source_id": row["source_id"],
                "dataset_id": row["dataset_id"],
                "artifact_sha256": row["artifact_sha256"],
                "fetched_at": row["fetched_at"],
                "schema_version": identity.schema_version,
                "vintage_id": None,
                "run_id": None,
                "source_warning": None,
            }
        )
    return pd.DataFrame.from_records(records, columns=SILVER_STAGING_COLUMNS)


__all__ = ["SUPPORTED_SERIES_ID", "bddk_monthly_to_staging"]
