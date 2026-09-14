import inspect
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.lakehouse.contracts.identifiers import (
    new_run_id,
    validate_dataset_id,
    validate_run_id,
    validate_series_id,
    validate_source_id,
)
from src.lakehouse.contracts.models import FetchedAsset, FetchSpec
from src.lakehouse.contracts.types import CanonicalDate, CanonicalValue
from src.lakehouse.errors import ERROR_CODES, ErrorPayload
from src.lakehouse.parsers.base import BaseParser
from src.lakehouse.parsers.csv import CsvParser
from src.lakehouse.storage.raw import raw_artifact_path, sha256_bytes


def _asset(path: Path) -> FetchedAsset:
    return FetchedAsset(
        source_id="evds",
        dataset_id="evds_housing_interest",
        locator="fixture://sample.csv",
        media_type="text/csv",
        byte_size=44,
        fetched_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
        artifact_sha256=sha256_bytes(path.read_bytes()),
        raw_path=path,
        http_status=200,
    )


def test_fetch_spec_carries_the_shared_request_contract() -> None:
    requested_at = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)

    spec = FetchSpec(
        source_id="evds",
        dataset_id="evds_housing_interest",
        locator="https://example.test/series",
        start_date=date(2021, 1, 1),
        end_date=date(2026, 6, 30),
        parameters={"series": "TP.KTF12"},
        headers_ref="EVDS_HEADERS",
        timeout=15.0,
        requested_at=requested_at,
    )

    assert spec.requested_at == requested_at
    assert spec.parameters == {"series": "TP.KTF12"}
    assert spec.headers_ref == "EVDS_HEADERS"


def test_fetched_asset_is_the_metadata_and_provenance_contract() -> None:
    asset = _asset(Path("tests/fixtures/raw/sample.csv"))

    assert asset.source_id == "evds"
    assert asset.dataset_id == "evds_housing_interest"
    assert asset.artifact_sha256 == sha256_bytes(asset.raw_path.read_bytes())
    assert asset.http_status == 200


def test_parser_reads_local_fixture_and_preserves_provenance() -> None:
    asset = _asset(Path("tests/fixtures/raw/sample.csv"))

    parsed = CsvParser().parse(asset)

    assert isinstance(parsed.dataframe, pd.DataFrame)
    assert list(parsed.dataframe.columns) == ["date", "value"]
    assert parsed.source_id == asset.source_id
    assert parsed.dataset_id == asset.dataset_id
    assert parsed.artifact_sha256 == asset.artifact_sha256
    assert parsed.warnings == []


def test_parser_contract_has_only_fetched_asset_input_and_no_network_import() -> None:
    parameters = list(inspect.signature(BaseParser.parse).parameters)

    assert parameters == ["self", "asset"]
    parser_source = Path(__file__).parents[2] / "src/lakehouse/parsers/base.py"
    source_text = parser_source.read_text()
    assert "connectors" not in source_text
    assert "requests" not in source_text
    assert "httpx" not in source_text


def test_sha256_is_deterministic_for_identical_bytes() -> None:
    assert sha256_bytes(b"same bytes") == sha256_bytes(b"same bytes")
    assert sha256_bytes(b"same bytes") != sha256_bytes(b"different bytes")


def test_raw_path_is_deterministic_and_uses_the_contract() -> None:
    digest = sha256_bytes(b"same bytes")
    arguments = (Path("data/raw"), "evds", date(2026, 9, 8), digest, ".json")

    assert raw_artifact_path(*arguments) == raw_artifact_path(*arguments)
    assert str(raw_artifact_path(*arguments)) == f"data/raw/evds/2026-09-08/{digest}.json"


@pytest.mark.parametrize("value", ["", "EVDS", "evds-source", "evds.source"])
def test_source_id_and_dataset_id_require_lowercase_snake_case(value: str) -> None:
    with pytest.raises(ValueError):
        validate_source_id(value)
    with pytest.raises(ValueError):
        validate_dataset_id(value)


@pytest.mark.parametrize(
    "series_id",
    ["", "TP.KTF12", "EVDS.TP.KTF12", "evds.", "evds..KTF12"],
)
def test_series_id_requires_a_source_namespace(series_id: str) -> None:
    with pytest.raises(ValueError):
        validate_series_id(series_id)


def test_series_id_supports_stable_source_namespaces() -> None:
    assert validate_series_id("evds:TP.KTF12", source_id="evds") == "evds:TP.KTF12"
    assert validate_series_id("evds.TP.KTF12", source_id="evds") == "evds.TP.KTF12"
    with pytest.raises(ValueError):
        validate_series_id("evds:TP.KTF12", source_id="bddk_monthly")


def test_run_id_is_a_uuid_and_canonical_types_are_declared() -> None:
    run_id = new_run_id()

    assert validate_run_id(run_id) == run_id
    assert CanonicalDate is date
    assert CanonicalValue == float | None


def test_error_payload_exposes_the_shared_minimum_fields() -> None:
    payload = ErrorPayload(
        error_code="FETCH_TIMEOUT",
        message="source did not respond in time",
        source_id="evds",
        dataset_id="evds_housing_interest",
        retryable=True,
    )

    assert payload.error_code in ERROR_CODES
    assert payload.source_id == "evds"
    assert payload.dataset_id == "evds_housing_interest"
    assert payload.retryable is True
