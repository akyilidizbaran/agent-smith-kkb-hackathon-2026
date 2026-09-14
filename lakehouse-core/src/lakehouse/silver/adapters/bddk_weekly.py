"""Map the first BDDK weekly Bronze series to generic Silver staging."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
import re

import pandas as pd

from ...parsers.bddk_weekly import BDDK_WEEKLY_SCHEMA_VERSION
from ...silver.foundation import SILVER_STAGING_COLUMNS, SilverValidationError
from ...storage.parquet import ParquetIdentity
from ._context import bddk_entity_code, lineage_fields, staging_frame


SUPPORTED_SERIES_ID = "bddk_weekly:5690_3"
"""The only BDDK weekly series mapped by this Silver slice."""

_REQUIRED_BRONZE_COLUMNS = frozenset(
    {
        "source_id",
        "dataset_id",
        "series_id",
        "entity_code",
        "currency_label",
        "date_raw",
        "value_raw",
        "artifact_sha256",
        "fetched_at",
    }
)
_DATE_PATTERN = re.compile(r"^\d{1,2}\.\d{2}\.\d{4}$")


def _validate_input(frame: pd.DataFrame, identity: ParquetIdentity) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    missing = sorted(_REQUIRED_BRONZE_COLUMNS - set(frame.columns))
    if missing:
        raise SilverValidationError(f"BDDK weekly Bronze frame is missing columns: {missing}")
    if frame.empty:
        raise SilverValidationError("BDDK weekly Bronze frame must not be empty")
    if identity.schema_version != BDDK_WEEKLY_SCHEMA_VERSION:
        raise SilverValidationError(
            "BDDK weekly Bronze schema_version mismatch: "
            f"expected {BDDK_WEEKLY_SCHEMA_VERSION!r}, got {identity.schema_version!r}"
        )

    expected = {
        "source_id": identity.source_id,
        "dataset_id": identity.dataset_id,
        "artifact_sha256": identity.artifact_sha256,
    }
    for column, value in expected.items():
        if any(row_value != value for row_value in frame[column].tolist()):
            raise SilverValidationError(
                f"BDDK weekly Bronze {column} conflicts with Parquet identity"
            )
    if any(row_value != SUPPORTED_SERIES_ID for row_value in frame["series_id"].tolist()):
        raise SilverValidationError(
            f"unsupported BDDK weekly series; only {SUPPORTED_SERIES_ID!r} is mapped"
        )


def _observation_date(raw: object, row_number: int) -> date:
    if not isinstance(raw, str) or _DATE_PATTERN.fullmatch(raw) is None:
        raise SilverValidationError(
            f"invalid BDDK weekly date_raw at row {row_number}: {raw!r}"
        )
    try:
        return datetime.strptime(raw, "%d.%m.%Y").date()
    except ValueError as exc:
        raise SilverValidationError(
            f"invalid BDDK weekly date_raw at row {row_number}: {raw!r}"
        ) from exc


def bddk_weekly_to_staging(
    frame: pd.DataFrame,
    *,
    identity: ParquetIdentity,
    run_id: str | None = None,
    source_warnings: Sequence[str] = (),
    vintage_id: str | None = None,
) -> pd.DataFrame:
    """Map ``5690_3`` Bronze rows to the generic Silver staging contract.

    The source date is parsed only to a canonical date. No week anchoring, subtotal inference,
    numeric conversion, or catalog semantic enrichment occurs here.
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
        if (
            not isinstance(row["currency_label"], str)
            or row["currency_label"].strip() != "TRY"
        ):
            raise SilverValidationError(
                f"BDDK weekly currency_label must be 'TRY' at row {row_number}"
            )
        records.append(
            {
                "series_id": row["series_id"],
                "entity_id": bddk_entity_code(row["entity_code"], row_number=row_number),
                "observation_date": _observation_date(row["date_raw"], row_number),
                "period_start": None,
                "period_end": None,
                "value_raw": row["value_raw"],
                "source_id": row["source_id"],
                "dataset_id": row["dataset_id"],
                "artifact_sha256": row["artifact_sha256"],
                "fetched_at": row["fetched_at"],
                **lineage,
            }
        )
    return staging_frame(records)


__all__ = ["SUPPORTED_SERIES_ID", "bddk_weekly_to_staging"]
