from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.base import BaseConnector
from src.lakehouse.contracts.models import FetchedAsset, FetchSpec, ParsedBatch
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.errors import LakehouseError
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.storage.parquet import ParquetStorage
from src.lakehouse.storage.raw import sha256_bytes


class EmptyConnector(BaseConnector):
    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        return []


class SingleAssetConnector(BaseConnector):
    def __init__(self, asset: FetchedAsset) -> None:
        self._asset = asset

    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        return [self._asset]


class StaticParser:
    def __init__(self, batch: ParsedBatch) -> None:
        self._batch = batch

    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        return self._batch


def _asset(tmp_path: Path, *, source_id: str = "fake_source") -> FetchedAsset:
    content = b"artifact"
    return FetchedAsset(
        source_id=source_id,
        dataset_id="fake_dataset",
        locator="fixture://artifact.json",
        media_type="application/json",
        byte_size=len(content),
        fetched_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
        artifact_sha256=sha256_bytes(content),
        raw_path=tmp_path / "artifact.json",
        http_status=200,
    )


def _pipeline(
    tmp_path: Path,
    connector: BaseConnector,
    parser: StaticParser,
) -> IngestionPipeline:
    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    return IngestionPipeline(
        connector=connector,
        parser=parser,
        artifact_repository=ArtifactRepository(connection),
        parquet_storage=ParquetStorage(tmp_path / "data/bronze"),
    )


def test_zero_assets_raises_structured_empty_dataset_error(tmp_path: Path) -> None:
    spec = FetchSpec(
        source_id="fake_source",
        dataset_id="fake_dataset",
        locator="fixture://empty",
    )
    batch = ParsedBatch(
        source_id=spec.source_id,
        dataset_id=spec.dataset_id,
        artifact_sha256=sha256_bytes(b"unused"),
        schema_version="fixture-v1",
        dataframe=pd.DataFrame({"value": [1]}),
    )
    pipeline = _pipeline(tmp_path, EmptyConnector(), StaticParser(batch))

    with pytest.raises(LakehouseError) as excinfo:
        pipeline.run(spec)

    assert excinfo.value.payload.error_code == "EMPTY_DATASET"
    assert excinfo.value.payload.source_id == spec.source_id
    assert excinfo.value.payload.dataset_id == spec.dataset_id
    pipeline.artifact_repository.connection.close()


def test_fetched_asset_identity_mismatch_raises_structured_schema_error(
    tmp_path: Path,
) -> None:
    spec = FetchSpec(
        source_id="fake_source",
        dataset_id="fake_dataset",
        locator="fixture://asset",
    )
    asset = _asset(tmp_path, source_id="other_source")
    batch = ParsedBatch(
        source_id=asset.source_id,
        dataset_id=asset.dataset_id,
        artifact_sha256=asset.artifact_sha256,
        schema_version="fixture-v1",
        dataframe=pd.DataFrame({"value": [1]}),
    )
    pipeline = _pipeline(tmp_path, SingleAssetConnector(asset), StaticParser(batch))

    with pytest.raises(LakehouseError) as excinfo:
        pipeline.run(spec)

    assert excinfo.value.payload.error_code == "SCHEMA_MISMATCH"
    assert excinfo.value.payload.source_id == spec.source_id
    assert excinfo.value.payload.dataset_id == spec.dataset_id
    assert "other_source" in excinfo.value.payload.message
    pipeline.artifact_repository.connection.close()


def test_parsed_batch_artifact_mismatch_raises_structured_schema_error(
    tmp_path: Path,
) -> None:
    asset = _asset(tmp_path)
    incorrect_sha = sha256_bytes(b"different")
    batch = ParsedBatch(
        source_id=asset.source_id,
        dataset_id=asset.dataset_id,
        artifact_sha256=incorrect_sha,
        schema_version="fixture-v1",
        dataframe=pd.DataFrame({"value": [1]}),
    )
    pipeline = _pipeline(tmp_path, SingleAssetConnector(asset), StaticParser(batch))
    spec = FetchSpec(
        source_id=asset.source_id,
        dataset_id=asset.dataset_id,
        locator=asset.locator,
    )

    with pytest.raises(LakehouseError) as excinfo:
        pipeline.run(spec)

    assert excinfo.value.payload.error_code == "SCHEMA_MISMATCH"
    assert excinfo.value.payload.source_id == asset.source_id
    assert excinfo.value.payload.dataset_id == asset.dataset_id
    assert "artifact_sha256" in excinfo.value.payload.message
    pipeline.artifact_repository.connection.close()
