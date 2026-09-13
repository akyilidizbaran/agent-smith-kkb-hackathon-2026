"""BDDK monthly parser tests. Every test reads a committed fixture; none touches the network."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.lakehouse.contracts.models import FetchedAsset
from src.lakehouse.errors import LakehouseError
from src.lakehouse.parsers.bddk_monthly import (
    BDDK_MONTHLY_SCHEMA_VERSION,
    COLUMNS,
    BddkMonthlyParser,
    unit_label_from_column,
)
from src.lakehouse.storage.raw import sha256_bytes


FIXTURE_DIR = Path("tests/fixtures/raw/bddk_monthly")
REPORT = FIXTURE_DIR / "bddk_monthly_housing_loans.json"
APPLICATION_ERROR = FIXTURE_DIR / "bddk_monthly_application_error.json"
MEASURE_COLUMN = "Tüketici Kredileri - Tüketici Kredileri - Konut (milyon TL)-Toplam"


def _asset(path: Path, **overrides: object) -> FetchedAsset:
    content = path.read_bytes()
    defaults: dict[str, object] = {
        "source_id": "bddk_monthly",
        "dataset_id": "bddk_monthly_housing_loans",
        "locator": "https://www.bddk.org.tr/BultenAylik/tr/Home/GelismisRaporGetir",
        "media_type": "application/json",
        "byte_size": len(content),
        "fetched_at": datetime(2026, 9, 8, 7, tzinfo=timezone.utc),
        "artifact_sha256": sha256_bytes(content),
        "raw_path": path,
        "http_status": 200,
        "metadata": {"expected_period_count": 5, "requested_currency": "TL"},
    }
    defaults.update(overrides)
    return FetchedAsset(**defaults)  # type: ignore[arg-type]


def test_parser_reads_only_the_local_raw_file() -> None:
    source_text = Path("src/lakehouse/parsers/bddk_monthly.py").read_text(encoding="utf-8")

    assert "requests" not in source_text
    assert "httpx" not in source_text
    assert "urllib" not in source_text
    assert "connectors" not in source_text


def test_parser_produces_parsed_batch_with_preserved_provenance() -> None:
    asset = _asset(REPORT)

    parsed = BddkMonthlyParser().parse(asset)

    assert parsed.schema_version == BDDK_MONTHLY_SCHEMA_VERSION
    assert list(parsed.dataframe.columns) == COLUMNS
    assert parsed.source_id == asset.source_id
    assert parsed.dataset_id == asset.dataset_id
    assert parsed.artifact_sha256 == asset.artifact_sha256
    frame = parsed.dataframe
    assert set(frame["artifact_sha256"]) == {asset.artifact_sha256}
    assert set(frame["fetched_at"]) == {asset.fetched_at}
    assert set(frame["locator"]) == {asset.locator}


def test_positional_cells_are_zipped_against_column_models() -> None:
    frame = BddkMonthlyParser().parse(_asset(REPORT)).dataframe

    assert len(frame) == 5
    assert list(frame["year_raw"]) == [2026, 2026, 2026, 2021, 2021]
    assert list(frame["month_raw"]) == [6, 5, 4, 2, 1]
    assert list(frame["value_raw"]) == [801438, 782918, 767314, 276263, 276785]
    assert set(frame["entity_label"]) == {"Sektör"}
    assert list(frame["source_order"]) == [1, 2, 3, 65, 66]


def test_verified_golden_values_from_the_live_response() -> None:
    """2021-01 and 2026-06 housing loan stock, in milyon TL, as BDDK returned them."""

    frame = BddkMonthlyParser().parse(_asset(REPORT)).dataframe
    by_period = {
        (int(row.year_raw), int(row.month_raw)): row.value_raw
        for row in frame.itertuples()
    }

    assert by_period[(2021, 1)] == 276785
    assert by_period[(2026, 6)] == 801438


def test_unit_is_recovered_from_the_column_name() -> None:
    frame = BddkMonthlyParser().parse(_asset(REPORT)).dataframe

    assert set(frame["measure_column"]) == {MEASURE_COLUMN}
    assert set(frame["unit_label"]) == {"milyon TL"}
    assert unit_label_from_column("Krediler (Bin TL)-Toplam") == "Bin TL"
    assert unit_label_from_column("Rasyolar-Toplam") is None


def test_series_id_uses_the_namespaced_contract_form() -> None:
    frame = BddkMonthlyParser().parse(_asset(REPORT)).dataframe

    series_ids = set(frame["series_id"])
    assert len(series_ids) == 1
    series_id = series_ids.pop()
    assert series_id.startswith("bddk_monthly:")
    assert "?" not in series_id and " " not in series_id


def test_source_order_and_row_order_are_preserved_not_sorted() -> None:
    """BDDK returns newest first; the parser must not silently reorder the source."""

    frame = BddkMonthlyParser().parse(_asset(REPORT)).dataframe

    assert list(frame["source_order"]) == sorted(frame["source_order"])
    assert frame["year_raw"].iloc[0] == 2026
    assert frame["year_raw"].iloc[-1] == 2021


def test_grid_display_default_of_zero_is_reported_as_a_warning() -> None:
    parsed = BddkMonthlyParser().parse(_asset(REPORT))

    assert any("defaultValue" in warning for warning in parsed.warnings)
    assert any("must not be treated as a measured zero" in w for w in parsed.warnings)


def test_period_count_shortfall_is_reported() -> None:
    parsed = BddkMonthlyParser().parse(
        _asset(REPORT, metadata={"expected_period_count": 66})
    )

    assert any("5 periods returned but 66 were requested" in w for w in parsed.warnings)


def test_application_error_inside_http_200_is_rejected() -> None:
    """BDDK answers HTTP 200 with success:false; that must not become a parsed batch."""

    with pytest.raises(LakehouseError) as excinfo:
        BddkMonthlyParser().parse(_asset(APPLICATION_ERROR))

    assert excinfo.value.payload.error_code == "SOURCE_UNAVAILABLE"
    assert excinfo.value.payload.retryable is True
    assert "Gelişmiş Rapor üretilirken hata oluştu!" in excinfo.value.payload.message


def test_null_measure_values_are_preserved(tmp_path: Path) -> None:
    document = json.loads(REPORT.read_text(encoding="utf-8"))
    document["Json"]["data"]["rows"][0]["cell"][3] = None
    artifact = tmp_path / "with_null.json"
    artifact.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    frame = BddkMonthlyParser().parse(_asset(artifact)).dataframe

    assert frame["value_raw"].iloc[0] is None
    assert frame["value_raw"].iloc[1] == 782918


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        ("", "EMPTY_DATASET"),
        ("not json", "PARSE_FAILED"),
        ("[]", "SCHEMA_MISMATCH"),
        ('{"success": true}', "SCHEMA_MISMATCH"),
        ('{"success": true, "Json": {"colModels": []}}', "SCHEMA_MISMATCH"),
        (
            '{"success": true, "Json": {"colModels": [{"name": "Yil"}], "data": {"rows": []}}}',
            "EMPTY_DATASET",
        ),
    ],
)
def test_malformed_responses_raise_the_shared_error_contract(
    tmp_path: Path, body: str, expected_code: str
) -> None:
    artifact = tmp_path / "broken.json"
    artifact.write_text(body, encoding="utf-8")

    with pytest.raises(LakehouseError) as excinfo:
        BddkMonthlyParser().parse(_asset(artifact))

    assert excinfo.value.payload.error_code == expected_code
    assert excinfo.value.payload.source_id == "bddk_monthly"


def test_row_width_mismatch_is_a_schema_error(tmp_path: Path) -> None:
    document = json.loads(REPORT.read_text(encoding="utf-8"))
    document["Json"]["data"]["rows"][0]["cell"] = ["Sektör", 2026, 6]
    artifact = tmp_path / "short_row.json"
    artifact.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(LakehouseError) as excinfo:
        BddkMonthlyParser().parse(_asset(artifact))

    assert excinfo.value.payload.error_code == "SCHEMA_MISMATCH"


def test_parser_applies_no_silver_semantics() -> None:
    source_text = Path("src/lakehouse/parsers/bddk_monthly.py").read_text(encoding="utf-8")
    frame = BddkMonthlyParser().parse(_asset(REPORT)).dataframe

    assert frame["value_raw"].dtype == object
    assert "resample" not in source_text
    assert "date_key" not in list(frame.columns)
    assert "measure_type" not in list(frame.columns)


def test_fixture_directory_contains_no_secret_material() -> None:
    for fixture in sorted(FIXTURE_DIR.glob("*.json")):
        text = fixture.read_text(encoding="utf-8").lower()
        for forbidden in ("cookie", "authorization", "bearer ", "api_key", "__requestverification"):
            assert forbidden not in text


def test_series_id_satisfies_the_shared_identifier_contract() -> None:
    from src.lakehouse.contracts.identifiers import validate_series_id

    frame = BddkMonthlyParser().parse(_asset(REPORT)).dataframe

    for series_id in set(frame["series_id"]):
        assert validate_series_id(series_id, source_id="bddk_monthly") == series_id


def test_series_id_prefers_the_stable_requested_item_id() -> None:
    """The Turkish column label loses characters and changes wording; the item id does not."""

    parsed = BddkMonthlyParser().parse(
        _asset(
            REPORT,
            metadata={"expected_period_count": 5, "requested_kalem_sutun": ["1534?Toplam"]},
        )
    )

    assert set(parsed.dataframe["series_id"]) == {"bddk_monthly:1534_Toplam"}
    assert not any("column label" in warning for warning in parsed.warnings)


def test_series_id_falls_back_to_the_label_with_a_warning() -> None:
    parsed = BddkMonthlyParser().parse(_asset(REPORT, metadata={}))

    assert any("not a stable key" in warning for warning in parsed.warnings)
    assert set(parsed.dataframe["series_id"]) == {
        "bddk_monthly:T_ketici_Kredileri_T_ketici_Kredileri_Konut_milyon_TL_Toplam"
    }


# ------------------------------------- source style facts (no is_subtotal here)


SIMPLE_REPORT = Path(
    "tests/fixtures/raw/bddk_monthly/bddk_monthly_simple_report_basitfont.json"
)


def test_advanced_report_has_no_style_columns_and_v1_does_not_invent_them() -> None:
    """Verified against the live endpoint: the advanced report declares no BasitFont/parent."""

    document = json.loads(REPORT.read_text(encoding="utf-8"))
    names = [model["name"] for model in document["Json"]["colModels"]]
    assert "BasitFont" not in names
    assert "parent" not in names

    frame = BddkMonthlyParser().parse(_asset(REPORT)).dataframe

    assert "source_font" not in frame.columns
    assert "source_parent" not in frame.columns
    assert "source_is_bold" not in frame.columns


def test_no_is_subtotal_column_is_produced() -> None:
    """Deriving a financial subtotal flag is Silver's call, not the parser's."""

    frame = BddkMonthlyParser().parse(_asset(REPORT)).dataframe

    assert "is_subtotal" not in frame.columns


def test_cell_index_three_is_a_value_not_a_style_token() -> None:
    """Guards against a positional `cell[3] == "bold"` reading of the advanced report."""

    document = json.loads(REPORT.read_text(encoding="utf-8"))
    for row in document["Json"]["data"]["rows"]:
        assert isinstance(row["cell"][3], (int, float))
        assert row["cell"][3] != "bold"


def test_committed_simple_report_capture_carries_the_real_bold_signal() -> None:
    """Evidence fixture: the signal exists, on an endpoint this connector does not use."""

    document = json.loads(SIMPLE_REPORT.read_text(encoding="utf-8"))
    payload = document["Json"]
    names = [model["name"] for model in payload["colModels"]]

    assert document["success"] is True
    assert names == ["BankaAdi", "BasitSira", "Ad", "BasitFont", "Tp", "Yp", "Toplam"]
    font_index = names.index("BasitFont")
    label_index = names.index("Ad")
    rows = payload["data"]["rows"]

    marked = {
        row["cell"][label_index]: row["cell"][font_index] for row in rows
    }
    assert marked["Tüketici Kredileri (2+3+4)"] == "bold"
    assert marked["Tüketici Kredileri - Konut"] == ""
