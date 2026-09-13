"""BDDK FinTürk parser tests. Every test reads a committed fixture; none touches the network."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.lakehouse.contracts.identifiers import validate_series_id
from src.lakehouse.contracts.models import FetchedAsset
from src.lakehouse.errors import LakehouseError
from src.lakehouse.parsers.bddk_finturk import (
    BDDK_FINTURK_SCHEMA_VERSION,
    COLUMNS,
    BddkFinTurkParser,
)
from src.lakehouse.storage.raw import sha256_bytes


FIXTURE_DIR = Path("tests/fixtures/raw/bddk_finturk")
YALOVA_2025_9 = FIXTURE_DIR / "bddk_finturk_yalova_2025_9.json"

_MEASURE_COLUMNS = {
    "TasitKredisi",
    "KonutKredisi",
    "KrediliMevduatHesabi",
    "DigerTuketiciKredileri",
    "BireyselKrediKartlari",
    "TakiptekiTasitKredisi",
    "TakiptekiKonutKredisi",
    "TakiptekiDigerTuketiciKredileri",
}


def _asset(path: Path, **overrides: object) -> FetchedAsset:
    content = path.read_bytes()
    defaults: dict[str, object] = {
        "source_id": "bddk_finturk",
        "dataset_id": "bddk_finturk_yalova_housing_loans",
        "locator": "https://www.bddk.org.tr/BultenFinturk/tr/Home/VeriGetir",
        "media_type": "application/json",
        "byte_size": len(content),
        "fetched_at": datetime(2026, 9, 10, 22, tzinfo=timezone.utc),
        "artifact_sha256": sha256_bytes(content),
        "raw_path": path,
        "http_status": 200,
        "metadata": {"requested_sehir": "YALOVA", "requested_donem": "2025-9"},
    }
    defaults.update(overrides)
    return FetchedAsset(**defaults)  # type: ignore[arg-type]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    artifact = tmp_path / name
    artifact.write_text(body, encoding="utf-8")
    return artifact


def test_parser_reads_only_the_local_raw_file() -> None:
    source_text = Path("src/lakehouse/parsers/bddk_finturk.py").read_text(encoding="utf-8")

    assert "requests" not in source_text
    assert "httpx" not in source_text
    assert "urllib" not in source_text
    assert "connectors" not in source_text


def test_parser_produces_parsed_batch_with_preserved_provenance() -> None:
    asset = _asset(YALOVA_2025_9)

    parsed = BddkFinTurkParser().parse(asset)

    assert parsed.schema_version == BDDK_FINTURK_SCHEMA_VERSION
    assert list(parsed.dataframe.columns) == COLUMNS
    assert parsed.source_id == asset.source_id
    assert parsed.dataset_id == asset.dataset_id
    assert parsed.artifact_sha256 == asset.artifact_sha256
    frame = parsed.dataframe
    assert set(frame["artifact_sha256"]) == {asset.artifact_sha256}
    assert set(frame["fetched_at"]) == {asset.fetched_at}
    assert set(frame["locator"]) == {asset.locator}


def test_one_response_row_produces_one_output_row_per_measure_column() -> None:
    """A single FinTürk row carries every measure at once; the parser fans it out."""

    frame = BddkFinTurkParser().parse(_asset(YALOVA_2025_9)).dataframe

    assert len(frame) == 8
    assert set(frame["measure_column"]) == _MEASURE_COLUMNS
    assert set(frame["entity_label"]) == {"YALOVA"}
    assert set(frame["party_label"]) == {"SEKTÖR"}
    assert set(frame["year_raw"]) == {2025}
    assert set(frame["month_raw"]) == {9}


def test_verified_golden_values_from_the_live_response() -> None:
    """Yalova, 2025-9, tabloNo=3, as BDDK returned it."""

    frame = BddkFinTurkParser().parse(_asset(YALOVA_2025_9)).dataframe
    by_measure = dict(zip(frame["measure_column"], frame["value_raw"]))

    assert by_measure["TasitKredisi"] == 192843
    assert by_measure["KonutKredisi"] == 2104493
    assert by_measure["KrediliMevduatHesabi"] == 2436929
    assert by_measure["DigerTuketiciKredileri"] == 4911508
    assert by_measure["BireyselKrediKartlari"] == 8316033
    assert by_measure["TakiptekiTasitKredisi"] == 1614
    assert by_measure["TakiptekiKonutKredisi"] == 2295
    assert by_measure["TakiptekiDigerTuketiciKredileri"] == 394348


def test_series_id_uses_the_namespaced_contract_form() -> None:
    frame = BddkFinTurkParser().parse(_asset(YALOVA_2025_9)).dataframe

    series_ids = set(frame["series_id"])
    assert series_ids == {f"bddk_finturk:YALOVA_{measure}" for measure in _MEASURE_COLUMNS}
    for series_id in series_ids:
        assert validate_series_id(series_id, source_id="bddk_finturk") == series_id


def test_turkish_sehir_letters_are_transliterated_to_ascii(tmp_path: Path) -> None:
    """AĞRI must slug to ASCII 'AGRI', matching the catalog, not collapse under a naive strip."""

    document = json.loads(YALOVA_2025_9.read_text(encoding="utf-8"))
    document["Json"]["data"]["rows"][0]["cell"][3] = "AĞRI"
    artifact = _write(tmp_path, "agri.json", json.dumps(document, ensure_ascii=False))

    frame = BddkFinTurkParser().parse(
        _asset(artifact, metadata={"requested_sehir": "AĞRI"})
    ).dataframe

    assert all(series_id.startswith("bddk_finturk:AGRI_") for series_id in frame["series_id"])
    assert set(frame["entity_label"]) == {"AĞRI"}


def test_requested_sehir_mismatch_is_rejected(tmp_path: Path) -> None:
    asset = _asset(YALOVA_2025_9, metadata={"requested_sehir": "ANKARA"})

    with pytest.raises(LakehouseError) as excinfo:
        BddkFinTurkParser().parse(asset)

    assert excinfo.value.payload.error_code == "SCHEMA_MISMATCH"
    assert "ANKARA" in excinfo.value.payload.message
    assert "YALOVA" in excinfo.value.payload.message


def test_more_than_one_row_is_a_schema_error(tmp_path: Path) -> None:
    document = json.loads(YALOVA_2025_9.read_text(encoding="utf-8"))
    document["Json"]["data"]["rows"].append(document["Json"]["data"]["rows"][0])
    artifact = _write(tmp_path, "two_rows.json", json.dumps(document, ensure_ascii=False))

    with pytest.raises(LakehouseError) as excinfo:
        BddkFinTurkParser().parse(_asset(artifact))

    assert excinfo.value.payload.error_code == "SCHEMA_MISMATCH"
    assert "exactly 1 was expected" in excinfo.value.payload.message


def test_zero_rows_is_empty_dataset(tmp_path: Path) -> None:
    document = json.loads(YALOVA_2025_9.read_text(encoding="utf-8"))
    document["Json"]["data"]["rows"] = []
    artifact = _write(tmp_path, "no_rows.json", json.dumps(document, ensure_ascii=False))

    with pytest.raises(LakehouseError) as excinfo:
        BddkFinTurkParser().parse(_asset(artifact))

    assert excinfo.value.payload.error_code == "EMPTY_DATASET"


def test_application_error_inside_http_200_is_rejected(tmp_path: Path) -> None:
    """BDDK can answer HTTP 200 with success:false; that must not become a parsed batch."""

    artifact = _write(
        tmp_path,
        "app_error.json",
        json.dumps({"success": False, "error": "Rapor üretilirken hata oluştu!"}),
    )

    with pytest.raises(LakehouseError) as excinfo:
        BddkFinTurkParser().parse(_asset(artifact))

    assert excinfo.value.payload.error_code == "SOURCE_UNAVAILABLE"
    assert excinfo.value.payload.retryable is True
    assert "Rapor üretilirken hata oluştu!" in excinfo.value.payload.message


def test_grid_display_default_of_zero_is_reported_as_a_warning() -> None:
    parsed = BddkFinTurkParser().parse(_asset(YALOVA_2025_9))

    assert any("defaultValue" in warning for warning in parsed.warnings)
    assert any("must not be treated as a measured zero" in w for w in parsed.warnings)


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        ("", "EMPTY_DATASET"),
        ("not json", "PARSE_FAILED"),
        ("[]", "SCHEMA_MISMATCH"),
        ('{"success": true}', "SCHEMA_MISMATCH"),
        ('{"success": true, "Json": {}}', "SCHEMA_MISMATCH"),
        ('{"success": true, "Json": {"colModels": [{"name": "Sehir"}]}}', "SCHEMA_MISMATCH"),
    ],
)
def test_malformed_responses_raise_the_shared_error_contract(
    tmp_path: Path, body: str, expected_code: str
) -> None:
    artifact = _write(tmp_path, "broken.json", body)

    with pytest.raises(LakehouseError) as excinfo:
        BddkFinTurkParser().parse(_asset(artifact))

    assert excinfo.value.payload.error_code == expected_code
    assert excinfo.value.payload.source_id == "bddk_finturk"


def test_no_measure_columns_is_a_schema_error(tmp_path: Path) -> None:
    document = {
        "success": True,
        "Json": {
            "colModels": [{"name": "Sehir"}, {"name": "Yil"}],
            "data": {"rows": [{"cell": ["YALOVA", 2025]}]},
        },
    }
    artifact = _write(tmp_path, "structural_only.json", json.dumps(document))

    with pytest.raises(LakehouseError) as excinfo:
        BddkFinTurkParser().parse(_asset(artifact))

    assert excinfo.value.payload.error_code == "SCHEMA_MISMATCH"
    assert "no measure column" in excinfo.value.payload.message


def test_row_width_mismatch_is_a_schema_error(tmp_path: Path) -> None:
    document = json.loads(YALOVA_2025_9.read_text(encoding="utf-8"))
    document["Json"]["data"]["rows"][0]["cell"] = [10001, 2025, 9]
    artifact = _write(tmp_path, "short_row.json", json.dumps(document, ensure_ascii=False))

    with pytest.raises(LakehouseError) as excinfo:
        BddkFinTurkParser().parse(_asset(artifact))

    assert excinfo.value.payload.error_code == "SCHEMA_MISMATCH"


def test_null_measure_values_are_preserved(tmp_path: Path) -> None:
    document = json.loads(YALOVA_2025_9.read_text(encoding="utf-8"))
    document["Json"]["data"]["rows"][0]["cell"][6] = None  # KonutKredisi position
    artifact = _write(tmp_path, "with_null.json", json.dumps(document, ensure_ascii=False))

    frame = BddkFinTurkParser().parse(_asset(artifact)).dataframe
    by_measure = dict(zip(frame["measure_column"], frame["value_raw"]))

    assert by_measure["KonutKredisi"] is None
    assert by_measure["TasitKredisi"] == 192843


def test_parser_applies_no_silver_semantics() -> None:
    source_text = Path("src/lakehouse/parsers/bddk_finturk.py").read_text(encoding="utf-8")
    frame = BddkFinTurkParser().parse(_asset(YALOVA_2025_9)).dataframe

    assert frame["value_raw"].dtype == object
    assert "resample" not in source_text
    assert "measure_type" not in list(frame.columns)
    assert "unit" not in list(frame.columns)


def test_fixture_directory_contains_no_secret_material() -> None:
    for fixture in sorted(FIXTURE_DIR.glob("*.json")):
        text = fixture.read_text(encoding="utf-8").lower()
        for forbidden in ("cookie", "authorization", "bearer ", "api_key", "__requestverification"):
            assert forbidden not in text
