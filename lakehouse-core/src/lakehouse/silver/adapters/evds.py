"""Map the supported EVDS Bronze series to generic Silver staging."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Sequence
from datetime import date, datetime
import re

import pandas as pd

from ...parsers.evds import EVDS_SCHEMA_VERSION
from ...silver.foundation import SILVER_STAGING_COLUMNS, SilverValidationError
from ...storage.parquet import ParquetIdentity
from ._context import lineage_fields, staging_frame


SUPPORTED_KTF12_SERIES_ID = "evds:TP.KTF12"
"""The first EVDS series mapped by this Silver slice."""

SUPPORTED_KFE_SERIES_ID = "evds:TP.KFE.TR"
"""The second EVDS series mapped by this Silver slice."""

SUPPORTED_CPI_SERIES_ID = "evds:TP.FG.J0"
"""Consumer price index. Mapped as an index *level*, never as a change rate."""

# Kept as a compatibility alias for the Phase 2.4 public constant.
SUPPORTED_SERIES_ID = SUPPORTED_KTF12_SERIES_ID

_REQUIRED_BRONZE_COLUMNS = frozenset(
    {
        "source_id",
        "dataset_id",
        "series_id",
        "date_raw",
        "value_raw",
        "artifact_sha256",
        "fetched_at",
    }
)


def _validate_input(
    frame: pd.DataFrame, identity: ParquetIdentity, *, expected_series_id: str
) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    missing = sorted(_REQUIRED_BRONZE_COLUMNS - set(frame.columns))
    if missing:
        raise SilverValidationError(f"EVDS Bronze frame is missing columns: {missing}")
    if frame.empty:
        raise SilverValidationError("EVDS Bronze frame must not be empty")
    if identity.schema_version != EVDS_SCHEMA_VERSION:
        raise SilverValidationError(
            "EVDS Bronze schema_version mismatch: "
            f"expected {EVDS_SCHEMA_VERSION!r}, got {identity.schema_version!r}"
        )

    expected = {
        "source_id": identity.source_id,
        "dataset_id": identity.dataset_id,
        "artifact_sha256": identity.artifact_sha256,
    }
    for column, value in expected.items():
        if any(row_value != value for row_value in frame[column].tolist()):
            raise SilverValidationError(f"EVDS Bronze {column} conflicts with Parquet identity")
    if any(row_value != expected_series_id for row_value in frame["series_id"].tolist()):
        raise SilverValidationError(
            f"unsupported EVDS series; only {expected_series_id!r} is mapped"
        )


def _observation_date(raw: object, row_number: int) -> date:
    if (
        not isinstance(raw, str)
        or len(raw) != 10
        or raw[2] != "-"
        or raw[5] != "-"
        or not raw[:2].isdigit()
        or not raw[3:5].isdigit()
        or not raw[6:].isdigit()
    ):
        raise SilverValidationError(
            f"invalid EVDS date_raw at row {row_number}: {raw!r}"
        )
    try:
        return datetime.strptime(raw, "%m-%d-%Y").date()
    except ValueError as exc:
        raise SilverValidationError(
            f"invalid EVDS date_raw at row {row_number}: {raw!r}"
        ) from exc


def _staging_record(
    row: pd.Series,
    *,
    observation_date: date,
    period_start: date | None,
    period_end: date | None,
    lineage: dict[str, object],
) -> dict[str, object]:
    """Build the shared generic staging record for either EVDS date policy."""

    return {
        "series_id": row["series_id"],
        "entity_id": None,
        "observation_date": observation_date,
        "period_start": period_start,
        "period_end": period_end,
        "value_raw": row["value_raw"],
        "source_id": row["source_id"],
        "dataset_id": row["dataset_id"],
        "artifact_sha256": row["artifact_sha256"],
        "fetched_at": row["fetched_at"],
        **lineage,
    }


def evds_ktf12_to_staging(
    frame: pd.DataFrame,
    *,
    identity: ParquetIdentity,
    run_id: str | None = None,
    source_warnings: Sequence[str] = (),
    vintage_id: str | None = None,
) -> pd.DataFrame:
    """Map ``TP.KTF12`` Bronze rows to the generic Silver staging contract.

    The EVDS ``date_raw`` value is parsed strictly as ``MM-DD-YYYY``. No Friday alignment,
    numeric coercion, or catalog semantic enrichment is performed by this adapter.
    """

    _validate_input(
        frame, identity, expected_series_id=SUPPORTED_KTF12_SERIES_ID
    )
    records: list[dict[str, object]] = []
    lineage = lineage_fields(
        identity,
        run_id=run_id,
        source_warnings=source_warnings,
        vintage_id=vintage_id,
    )
    for row_number, (_, row) in enumerate(frame.iterrows()):
        records.append(
            _staging_record(
                row,
                observation_date=_observation_date(row["date_raw"], row_number),
                period_start=None,
                period_end=None,
                lineage=lineage,
            )
        )
    return staging_frame(records)


_KFE_DATE_PATTERN = re.compile(r"^\d{2}-\d{4}$")


def _period_bounds(raw: object, row_number: int) -> tuple[date, date]:
    if not isinstance(raw, str) or _KFE_DATE_PATTERN.fullmatch(raw) is None:
        raise SilverValidationError(
            f"invalid EVDS KFE date_raw at row {row_number}: {raw!r}"
        )
    try:
        period_start = datetime.strptime(raw, "%m-%Y").date().replace(day=1)
        period_end = period_start.replace(day=monthrange(period_start.year, period_start.month)[1])
    except ValueError as exc:
        raise SilverValidationError(
            f"invalid EVDS KFE date_raw at row {row_number}: {raw!r}"
        ) from exc
    return period_start, period_end


def _evds_monthly_to_staging(
    frame: pd.DataFrame,
    *,
    identity: ParquetIdentity,
    expected_series_id: str,
    run_id: str | None = None,
    source_warnings: Sequence[str] = (),
    vintage_id: str | None = None,
) -> pd.DataFrame:
    """Map any monthly ``MM-YYYY`` EVDS series to generic Silver staging.

    Shared by every monthly EVDS series so a second one cannot drift from the first. The
    source month is converted to its first and last calendar dates and nothing else happens
    here: no base-year assumption, no rebasing, no percentage or change-rate conversion, no
    deflation, and no catalog semantic enrichment. Whether the values are a price level, a
    price index or anything else is decided by ``meta.series``, not by this function.
    """

    _validate_input(frame, identity, expected_series_id=expected_series_id)
    records: list[dict[str, object]] = []
    lineage = lineage_fields(
        identity,
        run_id=run_id,
        source_warnings=source_warnings,
        vintage_id=vintage_id,
    )
    for row_number, (_, row) in enumerate(frame.iterrows()):
        period_start, period_end = _period_bounds(row["date_raw"], row_number)
        records.append(
            _staging_record(
                row,
                observation_date=period_end,
                period_start=period_start,
                period_end=period_end,
                lineage=lineage,
            )
        )
    return staging_frame(records)


def evds_kfe_to_staging(
    frame: pd.DataFrame,
    *,
    identity: ParquetIdentity,
    run_id: str | None = None,
    source_warnings: Sequence[str] = (),
    vintage_id: str | None = None,
) -> pd.DataFrame:
    """Map ``TP.KFE.TR`` monthly Bronze rows to generic Silver staging."""

    return _evds_monthly_to_staging(
        frame,
        identity=identity,
        expected_series_id=SUPPORTED_KFE_SERIES_ID,
        run_id=run_id,
        source_warnings=source_warnings,
        vintage_id=vintage_id,
    )


def evds_cpi_to_staging(
    frame: pd.DataFrame,
    *,
    identity: ParquetIdentity,
    run_id: str | None = None,
    source_warnings: Sequence[str] = (),
    vintage_id: str | None = None,
) -> pd.DataFrame:
    """Map ``TP.FG.J0`` (TÜFE) monthly Bronze rows to generic Silver staging.

    The consumer price index reaches Silver as the **index level the source published**.
    Deflating a nominal series with it, rebasing it, or turning it into a month-over-month
    change rate are Gold concerns and are deliberately absent here. The base year is not
    assumed anywhere in this path; see ``catalog/series/evds.yml`` and
    ``docs/sources/evds.md`` for its verification status.
    """

    return _evds_monthly_to_staging(
        frame,
        identity=identity,
        expected_series_id=SUPPORTED_CPI_SERIES_ID,
        run_id=run_id,
        source_warnings=source_warnings,
        vintage_id=vintage_id,
    )


__all__ = [
    "SUPPORTED_CPI_SERIES_ID",
    "SUPPORTED_KFE_SERIES_ID",
    "SUPPORTED_KTF12_SERIES_ID",
    "SUPPORTED_SERIES_ID",
    "evds_cpi_to_staging",
    "evds_kfe_to_staging",
    "evds_ktf12_to_staging",
]
