from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.lakehouse.connectors.base import BaseConnector
from src.lakehouse.contracts.models import FetchedAsset, FetchSpec, ParsedBatch
from src.lakehouse.errors import LakehouseError
from src.lakehouse.parsers.base import BaseParser
from src.lakehouse.storage.raw import RawStorage


class FakeConnector(BaseConnector):
    """Offline connector stub: source access is represented by fixed fixture bytes."""

    def __init__(self, storage: RawStorage, content: bytes) -> None:
        self._storage = storage
        self._content = content

    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        return [
            self._storage.store(
                source_id=spec.source_id,
                dataset_id=spec.dataset_id,
                locator=spec.locator,
                content=self._content,
                media_type="text/csv",
                fetched_at=spec.requested_at,
                extension="csv",
                http_status=200,
            )
        ]


class FakeParser:
    """Offline parser stub that reads only the local RAW artifact path."""

    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        return ParsedBatch(
            source_id=asset.source_id,
            dataset_id=asset.dataset_id,
            artifact_sha256=asset.artifact_sha256,
            schema_version="fake-v1",
            dataframe=pd.read_csv(asset.raw_path),
        )


def test_fake_connector_raw_storage_fake_parser_chain_is_offline_and_deterministic(
    tmp_path: Path,
) -> None:
    content = b"date,value\n2026-01-31,10.5\n2026-02-28,11.0\n"
    storage = RawStorage(tmp_path / "data/raw")
    connector = FakeConnector(storage, content)
    parser: BaseParser = FakeParser()
    spec = FetchSpec(
        source_id="fake_source",
        dataset_id="fake_dataset",
        locator="fixture://sample.csv",
        requested_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    first_asset = connector.fetch(spec)[0]
    second_spec = FetchSpec(
        source_id=spec.source_id,
        dataset_id=spec.dataset_id,
        locator=spec.locator,
        requested_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )
    second_asset = connector.fetch(second_spec)[0]
    parsed = parser.parse(first_asset)

    assert first_asset.raw_path == second_asset.raw_path
    assert first_asset.artifact_sha256 == second_asset.artifact_sha256
    assert first_asset.source_id == parsed.source_id == spec.source_id
    assert first_asset.dataset_id == parsed.dataset_id == spec.dataset_id
    assert first_asset.artifact_sha256 == parsed.artifact_sha256
    assert first_asset.raw_path.read_bytes() == content
    assert len(list((tmp_path / "data/raw").rglob("*.csv"))) == 1
    assert parsed.dataframe.to_dict(orient="records") == [
        {"date": "2026-01-31", "value": 10.5},
        {"date": "2026-02-28", "value": 11.0},
    ]


def test_failed_http_response_is_not_written_as_raw_artifact(tmp_path: Path) -> None:
    storage = RawStorage(tmp_path / "data/raw")

    try:
        storage.store(
            source_id="fake_source",
            dataset_id="fake_dataset",
            locator="https://example.test/data.csv",
            content=b"not accepted",
            media_type="text/csv",
            fetched_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
            extension="csv",
            http_status=503,
        )
    except LakehouseError as exc:
        assert exc.payload.error_code == "HTTP_ERROR"
        assert exc.payload.retryable is True
    else:
        raise AssertionError("failed HTTP response should not be stored")

    assert not list((tmp_path / "data/raw").rglob("*"))
