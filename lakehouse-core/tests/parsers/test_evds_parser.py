"""EVDS parser tests. Every test reads a committed fixture; none touches the network."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.lakehouse.contracts.models import FetchedAsset
from src.lakehouse.errors import LakehouseError
from src.lakehouse.parsers.evds import COLUMNS, EVDS_SCHEMA_VERSION, EvdsParser
from src.lakehouse.storage.raw import sha256_bytes


FIXTURE_DIR = Path("tests/fixtures/raw/evds")
WEEKLY = FIXTURE_DIR / "evds_ktf12_weekly.json"
MONTHLY = FIXTURE_DIR / "evds_kfe_monthly.json"
DAILY_WITH_NULLS = FIXTURE_DIR / "evds_usd_daily_with_nulls.json"


def _asset(path: Path, **overrides: object) -> FetchedAsset:
    content = path.read_bytes()
    defaults: dict[str, object] = {
        "source_id": "evds",
        "dataset_id": "evds_housing_interest",
        "locator": "https://evds3.tcmb.gov.tr/igmevdsms-dis/series=TP.KTF12",
        "media_type": "application/json",
        "byte_size": len(content),
        "fetched_at": datetime(2026, 9, 8, 6, 30, tzinfo=timezone.utc),
        "artifact_sha256": sha256_bytes(content),
        "raw_path": path,
        "http_status": 200,
        "metadata": {"requested_series": ["TP.KTF12"], "observation_limit": 1000},
    }
    defaults.update(overrides)
    return FetchedAsset(**defaults)  # type: ignore[arg-type]


# 8. The parser reads only the local RAW file and imports no network client.
def test_parser_reads_only_the_local_raw_file() -> None:
    source_text = Path("src/lakehouse/parsers/evds.py").read_text(encoding="utf-8")

    assert "requests" not in source_text
    assert "httpx" not in source_text
    assert "urllib" not in source_text
    assert "connectors" not in source_text


def test_parser_reads_the_path_it_is_given(tmp_path: Path) -> None:
    copied = tmp_path / "artifact.json"
    copied.write_bytes(WEEKLY.read_bytes())

    parsed = EvdsParser().parse(_asset(copied))

    assert len(parsed.dataframe) == 5


# 9. The parser produces a ParsedBatch from the fixture.
def test_parser_produces_parsed_batch_from_fixture() -> None:
    parsed = EvdsParser().parse(_asset(WEEKLY))

    assert parsed.schema_version == EVDS_SCHEMA_VERSION
    assert list(parsed.dataframe.columns) == COLUMNS
    assert len(parsed.dataframe) == 5
    assert parsed.warnings == []


# 10. source_id, dataset_id and artifact_sha256 are preserved end to end.
def test_provenance_fields_are_preserved() -> None:
    asset = _asset(WEEKLY)

    parsed = EvdsParser().parse(asset)

    assert parsed.source_id == asset.source_id
    assert parsed.dataset_id == asset.dataset_id
    assert parsed.artifact_sha256 == asset.artifact_sha256
    frame = parsed.dataframe
    assert set(frame["source_id"]) == {asset.source_id}
    assert set(frame["dataset_id"]) == {asset.dataset_id}
    assert set(frame["artifact_sha256"]) == {asset.artifact_sha256}
    assert set(frame["fetched_at"]) == {asset.fetched_at}
    assert set(frame["locator"]) == {asset.locator}


# 11. Source nulls stay null and are never turned into zero.
def test_source_nulls_are_preserved_and_never_become_zero() -> None:
    asset = _asset(
        DAILY_WITH_NULLS,
        dataset_id="evds_usd_buying_rate",
        metadata={"requested_series": ["TP.DK.USD.A.YTL"], "observation_limit": 1000},
    )

    frame = EvdsParser().parse(asset).dataframe

    values = list(frame["value_raw"])
    assert values == [None, "42.8457", None, None, "42.8810", "42.9648"]
    assert all(value is None or isinstance(value, str) for value in values)
    assert 0 not in values and 0.0 not in values
    assert sum(value is None for value in values) == 3


# 12. Fixture-driven tests pass without internet: implied by every test above.
def test_fixture_directory_contains_no_secret_material() -> None:
    for fixture in sorted(FIXTURE_DIR.glob("*.json")):
        text = fixture.read_text(encoding="utf-8").lower()
        assert "api_key" not in text
        assert "authorization" not in text
        assert "bearer " not in text
        document = json.loads(fixture.read_text(encoding="utf-8"))
        assert set(document) >= {"totalCount", "items", "seriesNames"}


def test_raw_date_and_value_fields_are_kept_verbatim() -> None:
    """`Tarih` is MM-DD-YYYY here; the parser must not reinterpret or reformat it."""

    frame = EvdsParser().parse(_asset(WEEKLY)).dataframe

    assert list(frame["date_raw"]) == [
        "01-01-2021",
        "01-08-2021",
        "01-15-2021",
        "01-22-2021",
        "07-03-2026",
    ]
    assert list(frame["value_raw"]) == ["18.61", "18.61", "18.40", "18.19", "41.45"]
    assert list(frame["unixtime"])[0] == "1609455600"


def test_monthly_fixture_uses_a_different_date_shape_without_special_casing() -> None:
    asset = _asset(
        MONTHLY,
        dataset_id="evds_housing_price_index",
        metadata={"requested_series": ["TP.KFE.TR"], "observation_limit": 1000},
    )

    frame = EvdsParser().parse(asset).dataframe

    assert list(frame["date_raw"]) == ["01-2026", "02-2026", "03-2026"]
    assert set(frame["series_id"]) == {"evds:TP.KFE.TR"}
    assert set(frame["series_name"]) == {"Residential Property Price Index (RPPI)"}


def test_series_id_uses_the_namespaced_contract_form() -> None:
    frame = EvdsParser().parse(_asset(WEEKLY)).dataframe

    assert set(frame["series_id"]) == {"evds:TP.KTF12"}
    assert set(frame["series_column"]) == {"TP_KTF12"}


def test_unmapped_column_falls_back_with_a_warning() -> None:
    asset = _asset(WEEKLY, metadata={"observation_limit": 1000})

    parsed = EvdsParser().parse(asset)

    assert set(parsed.dataframe["series_id"]) == {"evds:TP.KTF12"}
    assert any("underscores with dots" in warning for warning in parsed.warnings)


def test_observation_limit_is_reported_as_a_truncation_warning(tmp_path: Path) -> None:
    document = json.loads(WEEKLY.read_text(encoding="utf-8"))
    document["items"] = document["items"] * 2
    document["totalCount"] = len(document["items"])
    artifact = tmp_path / "truncated.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")

    parsed = EvdsParser().parse(
        _asset(
            artifact,
            metadata={"requested_series": ["TP.KTF12"], "observation_limit": 10},
        )
    )

    assert any("per-request limit" in warning for warning in parsed.warnings)


def test_total_count_mismatch_is_reported(tmp_path: Path) -> None:
    document = json.loads(WEEKLY.read_text(encoding="utf-8"))
    document["totalCount"] = 99
    artifact = tmp_path / "mismatch.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")

    parsed = EvdsParser().parse(_asset(artifact))

    assert any("totalCount 99" in warning for warning in parsed.warnings)


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        ("", "EMPTY_DATASET"),
        ("not json", "PARSE_FAILED"),
        ("[]", "SCHEMA_MISMATCH"),
        ('{"totalCount": 0}', "SCHEMA_MISMATCH"),
        ('{"items": []}', "EMPTY_DATASET"),
        ('{"items": [{"TP_KTF12": "1"}]}', "SCHEMA_MISMATCH"),
        ('{"items": [{"Tarih": "01-2026"}]}', "SCHEMA_MISMATCH"),
    ],
)
def test_malformed_responses_raise_the_shared_error_contract(
    tmp_path: Path, body: str, expected_code: str
) -> None:
    artifact = tmp_path / "broken.json"
    artifact.write_text(body, encoding="utf-8")

    with pytest.raises(LakehouseError) as excinfo:
        EvdsParser().parse(_asset(artifact))

    assert excinfo.value.payload.error_code == expected_code
    assert excinfo.value.payload.source_id == "evds"
    assert excinfo.value.payload.retryable is False


def test_parser_applies_no_silver_semantics() -> None:
    """No numeric casting, no frequency conversion, no aggregation, no date normalization."""

    source_text = Path("src/lakehouse/parsers/evds.py").read_text(encoding="utf-8")
    frame = EvdsParser().parse(_asset(WEEKLY)).dataframe

    assert frame["value_raw"].dtype == object
    assert frame["date_raw"].dtype == object
    assert "resample" not in source_text
    assert "date_key" not in list(frame.columns)
    assert "measure_type" not in list(frame.columns)


def test_series_id_satisfies_the_shared_identifier_contract() -> None:
    from src.lakehouse.contracts.identifiers import validate_series_id

    for fixture, series in (
        (WEEKLY, "TP.KTF12"),
        (MONTHLY, "TP.KFE.TR"),
        (DAILY_WITH_NULLS, "TP.DK.USD.A.YTL"),
    ):
        asset = _asset(
            fixture, metadata={"requested_series": [series], "observation_limit": 1000}
        )
        frame = EvdsParser().parse(asset).dataframe
        for series_id in set(frame["series_id"]):
            assert validate_series_id(series_id, source_id="evds") == series_id
