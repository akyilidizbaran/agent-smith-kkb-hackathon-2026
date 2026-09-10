"""Map the first EVDS weekly Bronze series to generic Silver staging."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from ...parsers.evds import EVDS_SCHEMA_VERSION
from ...silver.foundation import SILVER_STAGING_COLUMNS, SilverValidationError
from ...storage.parquet import ParquetIdentity


SUPPORTED_SERIES_ID = "evds:TP.KTF12"
"""The only EVDS series mapped by this first Silver slice."""

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


def _validate_input(frame: pd.DataFrame, identity: ParquetIdentity) -> None:
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
    if any(row_value != SUPPORTED_SERIES_ID for row_value in frame["series_id"].tolist()):
        raise SilverValidationError(
            f"unsupported EVDS series; only {SUPPORTED_SERIES_ID!r} is mapped"
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


def evds_ktf12_to_staging(
    frame: pd.DataFrame, *, identity: ParquetIdentity
) -> pd.DataFrame:
    """Map ``TP.KTF12`` Bronze rows to the generic Silver staging contract.

    The EVDS ``date_raw`` value is parsed strictly as ``MM-DD-YYYY``. No Friday alignment,
    numeric coercion, or catalog semantic enrichment is performed by this adapter.
    """

    _validate_input(frame, identity)
    records: list[dict[str, object]] = []
    for row_number, (_, row) in enumerate(frame.iterrows()):
        records.append(
            {
                "series_id": row["series_id"],
                "entity_id": None,
                "observation_date": _observation_date(row["date_raw"], row_number),
                "period_start": None,
                "period_end": None,
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


__all__ = ["SUPPORTED_SERIES_ID", "evds_ktf12_to_staging"]
