"""Map the first BDDK monthly Bronze series to generic Silver staging."""

from __future__ import annotations

from collections.abc import Sequence
from calendar import monthrange
from datetime import date
from numbers import Integral
import unicodedata

import pandas as pd

from ...parsers.bddk_monthly import BDDK_MONTHLY_SCHEMA_VERSION
from ...silver.foundation import SILVER_STAGING_COLUMNS, SilverValidationError
from ...storage.parquet import ParquetIdentity
from ._context import bddk_entity_id, lineage_fields, staging_frame


SUPPORTED_SERIES_ID = "bddk_monthly:1534_Toplam"
"""The only BDDK monthly series mapped by this first Silver slice."""

_REQUIRED_BRONZE_COLUMNS = frozenset(
    {
        "source_id",
        "dataset_id",
        "series_id",
        "unit_label",
        "entity_label",
        "year_raw",
        "month_raw",
        "value_raw",
        "artifact_sha256",
        "fetched_at",
    }
)

_EXPECTED_SOURCE_UNIT = "milyon tl"


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


def _validate_source_unit(raw: object, row_number: int) -> None:
    if raw is None or raw is pd.NA or pd.isna(raw):
        raise SilverValidationError(
            f"BDDK monthly unit_label must not be NULL at row {row_number}"
        )
    if not isinstance(raw, str):
        raise SilverValidationError(
            f"BDDK monthly unit_label must be a string at row {row_number}"
        )
    normalized = " ".join(unicodedata.normalize("NFKC", raw).casefold().split())
    if normalized != _EXPECTED_SOURCE_UNIT:
        raise SilverValidationError(
            "BDDK monthly source unit conflicts with the reviewed TRY_mn mapping at row "
            f"{row_number}: {raw!r}; expected 'milyon TL'"
        )


def bddk_monthly_to_staging(
    frame: pd.DataFrame,
    *,
    identity: ParquetIdentity,
    run_id: str | None = None,
    source_warnings: Sequence[str] = (),
    vintage_id: str | None = None,
) -> pd.DataFrame:
    """Map ``1534_Toplam`` Bronze rows to the generic Silver staging contract.

    Only the source's year/month representation is interpreted here. Values remain raw,
    source unit and entity identity are checked explicitly, while frequency/unit/measure
    semantics still come from ``meta.series`` in the generic Silver foundation.
    """

    _validate_input(frame, identity)
    records: list[dict[str, object]] = []
    lineage = lineage_fields(
        identity,
        run_id=run_id,
        source_warnings=source_warnings,
        vintage_id=vintage_id,
    )
    for row_number, (_, row) in enumerate(frame.iterrows()):
        _validate_source_unit(row["unit_label"], row_number)
        period_start, period_end = _period_bounds(
            row["year_raw"], row["month_raw"], row_number
        )
        records.append(
            {
                "series_id": row["series_id"],
                "entity_id": bddk_entity_id(row["entity_label"], row_number=row_number),
                "observation_date": period_end,
                "period_start": period_start,
                "period_end": period_end,
                "value_raw": row["value_raw"],
                "source_id": row["source_id"],
                "dataset_id": row["dataset_id"],
                "artifact_sha256": row["artifact_sha256"],
                "fetched_at": row["fetched_at"],
                **lineage,
            }
        )
    return staging_frame(records)


__all__ = ["SUPPORTED_SERIES_ID", "bddk_monthly_to_staging"]
