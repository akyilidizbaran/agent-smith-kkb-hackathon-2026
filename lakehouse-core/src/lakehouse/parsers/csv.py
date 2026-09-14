"""Generic CSV parser with no source-specific or network behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..contracts.models import FetchedAsset, ParsedBatch
from ..errors import ErrorPayload, LakehouseError


class CsvParser:
    """Read a persisted CSV artifact without cleaning or normalization."""

    def __init__(self, schema_version: str = "1", **read_csv_kwargs: Any) -> None:
        self._schema_version = schema_version
        self._read_csv_kwargs = read_csv_kwargs

    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        """Read the asset's local path and retain its source provenance."""

        try:
            dataframe = pd.read_csv(Path(asset.raw_path), **self._read_csv_kwargs)
        except pd.errors.EmptyDataError as exc:
            raise LakehouseError(
                ErrorPayload(
                    error_code="EMPTY_DATASET",
                    message=f"CSV artifact is empty: {asset.raw_path}",
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=False,
                )
            ) from exc
        except Exception as exc:
            raise LakehouseError(
                ErrorPayload(
                    error_code="PARSE_FAILED",
                    message=f"Could not parse CSV artifact: {asset.raw_path}",
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=False,
                )
            ) from exc

        if dataframe.empty:
            raise LakehouseError(
                ErrorPayload(
                    error_code="EMPTY_DATASET",
                    message=f"CSV artifact has no rows: {asset.raw_path}",
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=False,
                )
            )

        return ParsedBatch(
            source_id=asset.source_id,
            dataset_id=asset.dataset_id,
            artifact_sha256=asset.artifact_sha256,
            schema_version=self._schema_version,
            dataframe=dataframe,
        )
