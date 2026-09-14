from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.connectors.base import BaseConnector, FetchSpec, FetchedAsset


class _StubConnector(BaseConnector):
    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        return [
            FetchedAsset(
                source_id=spec.source_id,
                dataset_id=spec.dataset_id,
                locator=spec.locator,
                media_type="application/json",
                byte_size=0,
                fetched_at=datetime.now(timezone.utc),
                artifact_sha256="0" * 64,
                raw_path=Path("data/raw/example.json"),
            )
        ]


def test_base_connector_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        BaseConnector()


def test_fetch_contract_returns_raw_asset_references() -> None:
    spec = FetchSpec(
        source_id="example_source",
        dataset_id="example_dataset",
        locator="https://example.test/data.json",
        parameters={"format": "json"},
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    assets = _StubConnector().fetch(spec)

    assert len(assets) == 1
    assert assets[0].source_id == spec.source_id
    assert assets[0].dataset_id == spec.dataset_id
    assert assets[0].locator == spec.locator
    assert assets[0].raw_path == Path("data/raw/example.json")
    assert len(assets[0].artifact_sha256) == 64
