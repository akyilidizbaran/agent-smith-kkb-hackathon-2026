"""Generic orchestration from a connector fetch to a Bronze representation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..catalog.artifacts import ArtifactRepository
from ..connectors.base import BaseConnector
from ..contracts.models import FetchedAsset, FetchSpec, ParsedBatch
from ..errors import ErrorPayload, LakehouseError
from ..parsers.base import BaseParser
from ..storage.parquet import ParquetStorage


@dataclass(frozen=True)
class IngestionResult:
    """The persisted outputs and provenance of one source asset."""

    asset: FetchedAsset
    parsed_batch: ParsedBatch
    bronze_path: Path
    artifact_inserted: bool


@dataclass(frozen=True)
class IngestionPipeline:
    """Connect source access, artifact registration, parsing and Bronze storage."""

    connector: BaseConnector
    parser: BaseParser
    artifact_repository: ArtifactRepository
    parquet_storage: ParquetStorage

    def run(self, spec: FetchSpec) -> list[IngestionResult]:
        """Run one FetchSpec and return one result for each fetched asset."""

        assets = self.connector.fetch(spec)
        if not assets:
            raise LakehouseError(
                ErrorPayload(
                    error_code="EMPTY_DATASET",
                    message="connector returned no assets",
                    source_id=spec.source_id,
                    dataset_id=spec.dataset_id,
                    retryable=False,
                )
            )

        results: list[IngestionResult] = []
        for asset in assets:
            self._validate_asset(spec, asset)
            artifact_inserted = self.artifact_repository.register(asset)
            parsed_batch = self.parser.parse(asset)
            self._validate_batch(asset, parsed_batch)
            bronze_path = self.parquet_storage.write(parsed_batch)
            results.append(
                IngestionResult(
                    asset=asset,
                    parsed_batch=parsed_batch,
                    bronze_path=bronze_path,
                    artifact_inserted=artifact_inserted,
                )
            )
        return results

    @staticmethod
    def _validate_asset(spec: FetchSpec, asset: FetchedAsset) -> None:
        if asset.source_id != spec.source_id:
            raise LakehouseError(
                ErrorPayload(
                    error_code="SCHEMA_MISMATCH",
                    message=(
                        "FetchSpec/FetchedAsset source_id mismatch: "
                        f"expected {spec.source_id!r}, got {asset.source_id!r}"
                    ),
                    source_id=spec.source_id,
                    dataset_id=spec.dataset_id,
                    retryable=False,
                )
            )
        if asset.dataset_id != spec.dataset_id:
            raise LakehouseError(
                ErrorPayload(
                    error_code="SCHEMA_MISMATCH",
                    message=(
                        "FetchSpec/FetchedAsset dataset_id mismatch: "
                        f"expected {spec.dataset_id!r}, got {asset.dataset_id!r}"
                    ),
                    source_id=spec.source_id,
                    dataset_id=spec.dataset_id,
                    retryable=False,
                )
            )

    @staticmethod
    def _validate_batch(asset: FetchedAsset, batch: ParsedBatch) -> None:
        if batch.source_id != asset.source_id:
            raise LakehouseError(
                ErrorPayload(
                    error_code="SCHEMA_MISMATCH",
                    message=(
                        "FetchedAsset/ParsedBatch source_id mismatch: "
                        f"expected {asset.source_id!r}, got {batch.source_id!r}"
                    ),
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=False,
                )
            )
        if batch.dataset_id != asset.dataset_id:
            raise LakehouseError(
                ErrorPayload(
                    error_code="SCHEMA_MISMATCH",
                    message=(
                        "FetchedAsset/ParsedBatch dataset_id mismatch: "
                        f"expected {asset.dataset_id!r}, got {batch.dataset_id!r}"
                    ),
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=False,
                )
            )
        if batch.artifact_sha256 != asset.artifact_sha256:
            raise LakehouseError(
                ErrorPayload(
                    error_code="SCHEMA_MISMATCH",
                    message=(
                        "FetchedAsset/ParsedBatch artifact_sha256 mismatch: "
                        f"expected {asset.artifact_sha256!r}, got {batch.artifact_sha256!r}"
                    ),
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=False,
                )
            )


__all__ = ["IngestionPipeline", "IngestionResult"]
