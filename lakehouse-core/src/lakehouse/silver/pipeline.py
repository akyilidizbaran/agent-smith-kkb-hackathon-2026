"""Explicit bridge from an ingestion result to trusted Silver staging."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from ..ingestion.pipeline import IngestionResult
from ..storage.parquet import ParquetIdentity, ParquetStorage, read_identity


SilverAdapter = Callable[..., pd.DataFrame]


def stage_ingestion_result(
    result: IngestionResult,
    *,
    adapter: SilverAdapter,
) -> tuple[pd.DataFrame, ParquetIdentity]:
    """Read verified Bronze and carry its full lineage through a Silver adapter.

    This is the supported production boundary. Calling adapters directly remains useful for
    focused tests, but this bridge prevents callers from accidentally dropping parser warnings
    or the ingestion ``run_id``.
    """

    bronze = ParquetStorage.read(result.bronze_path)
    bronze_identity = read_identity(result.bronze_path)
    staging = adapter(
        bronze,
        identity=bronze_identity,
        run_id=result.run_id,
        source_warnings=result.parsed_batch.warnings,
    )
    return staging, bronze_identity


__all__ = ["SilverAdapter", "stage_ingestion_result"]
