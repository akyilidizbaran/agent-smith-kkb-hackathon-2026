"""Shared context helpers for source-specific Silver adapters."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
import re
import unicodedata

import pandas as pd

from ...storage.parquet import ParquetIdentity
from ..foundation import SilverValidationError


_TURKISH_ASCII = str.maketrans(
    {"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u"}
)


def lineage_fields(
    identity: ParquetIdentity,
    *,
    run_id: str | None = None,
    source_warnings: Sequence[str] = (),
    vintage_id: str | None = None,
) -> dict[str, object]:
    """Build the lineage fields common to every staging record.

    Parser warnings apply to the batch rather than one source row, so every row derived from
    that artifact carries the same deterministic JSON array. The warning text also remains in
    ``meta.ingest_warning`` and can be reached from a final Silver row through ``run_id``.
    """

    warnings: list[str] = []
    for position, warning in enumerate(source_warnings):
        if not isinstance(warning, str) or not warning.strip():
            raise SilverValidationError(
                f"source warning at position {position} must be a non-empty string"
            )
        warnings.append(warning.strip())

    return {
        "schema_version": identity.schema_version,
        "vintage_id": vintage_id,
        "run_id": run_id,
        "source_warning": (
            json.dumps(warnings, ensure_ascii=False, separators=(",", ":"))
            if warnings
            else None
        ),
    }


def bddk_entity_id(raw_label: object, *, row_number: int) -> str:
    """Return a stable BDDK entity id from the source's population label.

    The known sector-total label is mapped to BDDK's requested party code ``10001`` so the
    monthly and weekly sources use the same entity. Unknown future labels remain distinct and
    deterministic; they are never collapsed to NULL.
    """

    if raw_label is None or raw_label is pd.NA or pd.isna(raw_label):
        raise SilverValidationError(
            f"BDDK entity label must not be NULL at row {row_number}"
        )
    if not isinstance(raw_label, str) or not raw_label.strip():
        raise SilverValidationError(
            f"BDDK entity label must be a non-empty string at row {row_number}"
        )

    label = " ".join(unicodedata.normalize("NFKC", raw_label).split())
    if label.casefold() == "sektör".casefold():
        return "bddk:10001"

    ascii_label = unicodedata.normalize("NFKD", label.casefold()).translate(_TURKISH_ASCII)
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_label).strip("_") or "entity"
    digest = hashlib.sha256(label.casefold().encode("utf-8")).hexdigest()[:8]
    return f"bddk:label:{slug}:{digest}"


def bddk_entity_code(raw_code: object, *, row_number: int) -> str:
    """Return a source-namespaced id from BDDK's stable party code."""

    if raw_code is None or raw_code is pd.NA or pd.isna(raw_code):
        raise SilverValidationError(
            f"BDDK entity code must not be NULL at row {row_number}"
        )
    code = str(raw_code).strip()
    if not code:
        raise SilverValidationError(
            f"BDDK entity code must not be empty at row {row_number}"
        )
    return f"bddk:{code}"


__all__ = ["bddk_entity_code", "bddk_entity_id", "lineage_fields"]
