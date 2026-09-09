"""BDDK weekly parser tests. Every test reads a local file; none touches the network."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.lakehouse.contracts.models import FetchedAsset
from src.lakehouse.errors import LakehouseError
from src.lakehouse.parsers.bddk_weekly import (
    BDDK_WEEKLY_SCHEMA_VERSION,
    COLUMNS,
    BddkWeeklyParser,
    split_title,
)
from src.lakehouse.storage.raw import sha256_bytes


FIXTURE_DIR = Path("tests/fixtures/raw/bddk_weekly")
HOUSING = FIXTURE_DIR / "bddk_weekly_housing_loans.json"
UNKNOWN_ITEM = FIXTURE_DIR / "bddk_weekly_unknown_item.json"
EMPTY_RANGE = FIXTURE_DIR / "bddk_weekly_empty_range.json"

FETCHED_AT = datetime(2026, 9, 10, 6, 15, 42, tzinfo=timezone.utc)
LOCATOR = "https://www.bddk.org.tr/BultenHaftalik/tr/Gelismis/KiyaslamaJsonGetir"

BASE_METADATA: dict[str, Any] = {
    "requested_chart_id": "1.0.4",
    "requested_kalem_id": "5690",
    "requested_currency": "TRY",
    "requested_column": "3",
    "requested_taraf": "10001",
}


def _asset(path: Path, **metadata_overrides: Any) -> FetchedAsset:
    content = path.read_bytes()
    metadata = {**BASE_METADATA, **metadata_overrides}
    for key, value in list(metadata.items()):
        if value is _ABSENT:
            metadata.pop(key)
    return FetchedAsset(
        source_id="bddk_weekly",
        dataset_id="bddk_weekly_housing_loans",
        locator=LOCATOR,
        media_type="application/json",
        byte_size=len(content),
        fetched_at=FETCHED_AT,
        artifact_sha256=sha256_bytes(content),
        raw_path=path,
        http_status=200,
        metadata=metadata,
    )


_ABSENT = object()


def _write(tmp_path: Path, payload: str) -> Path:
    """Write a synthetic payload for a code path no real capture demonstrates."""

    path = tmp_path / "synthetic.json"
    path.write_text(payload, encoding="utf-8")
    return path


# --------------------------------------------------------------- happy path


def test_parser_reads_only_the_local_raw_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any attempt to open a socket fails the test."""

    import socket

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("parser attempted network access")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)

    batch = BddkWeeklyParser().parse(_asset(HOUSING))

    assert len(batch.dataframe) == 5


def test_parser_produces_the_expected_batch_shape() -> None:
    asset = _asset(HOUSING)

    batch = BddkWeeklyParser().parse(asset)

    assert batch.schema_version == BDDK_WEEKLY_SCHEMA_VERSION
    assert list(batch.dataframe.columns) == COLUMNS
    assert len(batch.dataframe) == 5


def test_provenance_is_carried_through_unchanged() -> None:
    asset = _asset(HOUSING)

    batch = BddkWeeklyParser().parse(asset)

    assert batch.source_id == asset.source_id == "bddk_weekly"
    assert batch.dataset_id == asset.dataset_id == "bddk_weekly_housing_loans"
    assert batch.artifact_sha256 == asset.artifact_sha256
    frame = batch.dataframe
    assert set(frame["source_id"]) == {"bddk_weekly"}
    assert set(frame["dataset_id"]) == {"bddk_weekly_housing_loans"}
    assert set(frame["artifact_sha256"]) == {asset.artifact_sha256}
    assert set(frame["fetched_at"]) == {FETCHED_AT}
    assert set(frame["locator"]) == {LOCATOR}


def test_series_id_uses_the_stable_native_item_id() -> None:
    """`5690` is the item tree's stable id; `1.0.4` is a positional chart address."""

    batch = BddkWeeklyParser().parse(_asset(HOUSING))

    assert set(batch.dataframe["series_id"]) == {"bddk_weekly:5690_3"}
    assert set(batch.dataframe["kalem_id"]) == {"5690"}
    assert set(batch.dataframe["chart_id"]) == {"1.0.4"}
    assert batch.warnings == []


@pytest.mark.parametrize("bad_kalem_id", [_ABSENT, None, "", "   "])
def test_missing_kalem_id_fails_instead_of_using_the_chart_id(
    bad_kalem_id: object,
) -> None:
    """A positional chart id must never become a series identity, even as a fallback.

    Silently identifying a series by ``1.0.4`` would let a relabelled bulletin line inherit
    another line's identity after a layout change.
    """

    with pytest.raises(LakehouseError) as excinfo:
        BddkWeeklyParser().parse(_asset(HOUSING, requested_kalem_id=bad_kalem_id))

    payload = excinfo.value.payload
    assert payload.error_code == "SCHEMA_MISMATCH"
    assert "requested_kalem_id" in payload.message
    assert "not a substitute" in payload.message


def test_no_chart_derived_series_id_is_ever_produced() -> None:
    """Guards against the removed ``bddk_weekly:chart_...`` fallback coming back."""

    frame = BddkWeeklyParser().parse(_asset(HOUSING)).dataframe

    assert not any(str(value).startswith("bddk_weekly:chart") for value in frame["series_id"])


# ------------------------------------------------------- raw value preservation


def test_dates_and_values_are_kept_raw_and_in_source_order() -> None:
    """Oldest first, raw `d.MM.yyyy` strings, unrounded values, no canonical date."""

    frame = BddkWeeklyParser().parse(_asset(HOUSING)).dataframe

    assert list(frame["date_raw"]) == [
        "2.01.2026",
        "13.03.2026",
        "19.03.2026",
        "27.03.2026",
        "26.06.2026",
    ]
    assert list(frame["value_raw"]) == [
        679216.118,
        731311.768,
        734860.422,
        740789.871,
        800464.007,
    ]
    assert list(frame["source_order"]) == [0, 1, 2, 3, 4]
    assert "date_key" not in frame.columns
    assert "frequency" not in frame.columns
    assert "measure_type" not in frame.columns


def test_raw_values_match_the_fixture_exactly() -> None:
    document = json.loads(HOUSING.read_text(encoding="utf-8"))
    frame = BddkWeeklyParser().parse(_asset(HOUSING)).dataframe

    assert list(frame["date_raw"]) == document["XEkseni"]
    assert list(frame["value_raw"]) == document["YEkseni"]


def test_title_is_split_without_inventing_a_unit() -> None:
    frame = BddkWeeklyParser().parse(_asset(HOUSING)).dataframe

    assert set(frame["series_title"]) == {"a) Konut (TRY) [Toplam]"}
    assert set(frame["measure_label"]) == {"a) Konut"}
    assert set(frame["currency_label"]) == {"TRY"}
    assert set(frame["column_label"]) == {"Toplam"}
    # `(TRY)` is the currency leg. The unit (milyon TL) is published on the BDDK table
    # header, not in this payload, so the parser emits no unit column.
    assert "unit_label" not in frame.columns


def test_split_title_returns_none_for_an_unrecognised_shape() -> None:
    assert split_title("a) Konut (TRY) [Toplam]") == ("a) Konut", "TRY", "Toplam")
    assert split_title("a) Konut (TRY) ") == ("a) Konut", "TRY", None)
    assert split_title("no parentheses here") == (None, None, None)


def test_unrecognised_title_warns_instead_of_guessing(tmp_path: Path) -> None:
    """Synthetic payload: no live capture shows a title outside the observed shape."""

    path = _write(
        tmp_path,
        '{"Baslik":"totally different","XEkseni":["2.01.2026"],"YEkseni":[1.0]}',
    )
    batch = BddkWeeklyParser().parse(_asset(path))

    assert set(batch.dataframe["measure_label"]) == {None}
    assert set(batch.dataframe["currency_label"]) == {None}
    assert any("does not match the observed" in w for w in batch.warnings)


def test_null_values_are_preserved_and_never_coerced_to_zero(tmp_path: Path) -> None:
    """Synthetic payload: no live capture contained a null, so the guard is proven here.

    This file is deliberately **not** a fixture under ``tests/fixtures/raw/bddk_weekly`` —
    fixtures there are real captures only.
    """

    path = _write(
        tmp_path,
        '{"Baslik":"a) Konut (TRY) [Toplam]",'
        '"XEkseni":["2.01.2026","9.01.2026","16.01.2026"],'
        '"YEkseni":[679216.118,null,684418.509]}',
    )

    frame = BddkWeeklyParser().parse(_asset(path)).dataframe

    values = list(frame["value_raw"])
    assert values[1] is None
    assert values[1] != 0
    assert values == [679216.118, None, 684418.509]
    assert frame["value_raw"].isna().sum() == 1


# ----------------------------------------------------- unsuccessful responses


def test_unresolved_chart_id_is_not_a_successful_batch() -> None:
    """Real capture: HTTP 200, placeholder title, empty arrays."""

    with pytest.raises(LakehouseError) as excinfo:
        BddkWeeklyParser().parse(_asset(UNKNOWN_ITEM))

    payload = excinfo.value.payload
    assert payload.error_code == "SOURCE_UNAVAILABLE"
    assert payload.retryable is False
    assert "Grafik Başlığı" in payload.message


def test_empty_range_is_reported_as_an_empty_dataset() -> None:
    """Real capture: HTTP 200, real title, empty arrays — a different condition."""

    with pytest.raises(LakehouseError) as excinfo:
        BddkWeeklyParser().parse(_asset(EMPTY_RANGE))

    payload = excinfo.value.payload
    assert payload.error_code == "EMPTY_DATASET"
    assert "a) Konut (TRY)" in payload.message


def test_unparallel_arrays_are_a_schema_mismatch(tmp_path: Path) -> None:
    """Synthetic payload: position is the only date-to-value link, so this must not zip."""

    path = _write(
        tmp_path,
        '{"Baslik":"a) Konut (TRY) [Toplam]",'
        '"XEkseni":["2.01.2026","9.01.2026"],"YEkseni":[1.0]}',
    )

    with pytest.raises(LakehouseError) as excinfo:
        BddkWeeklyParser().parse(_asset(path))

    assert excinfo.value.payload.error_code == "SCHEMA_MISMATCH"
    assert "not parallel" in excinfo.value.payload.message


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ("", "EMPTY_DATASET"),
        ("   ", "EMPTY_DATASET"),
        ("{not json", "PARSE_FAILED"),
        ("[1, 2, 3]", "SCHEMA_MISMATCH"),
        ('{"Baslik":"a) Konut (TRY) [Toplam]","YEkseni":[1.0]}', "SCHEMA_MISMATCH"),
        ('{"Baslik":"a) Konut (TRY) [Toplam]","XEkseni":["2.01.2026"]}', "SCHEMA_MISMATCH"),
    ],
)
def test_malformed_payloads_raise_typed_errors(
    tmp_path: Path, payload: str, expected_code: str
) -> None:
    path = _write(tmp_path, payload)

    with pytest.raises(LakehouseError) as excinfo:
        BddkWeeklyParser().parse(_asset(path))

    assert excinfo.value.payload.error_code == expected_code
    assert excinfo.value.payload.source_id == "bddk_weekly"


def test_missing_raw_file_raises_parse_failed(tmp_path: Path) -> None:
    path = _write(tmp_path, '{"Baslik":"x","XEkseni":[],"YEkseni":[]}')
    asset = _asset(path)
    path.unlink()

    with pytest.raises(LakehouseError) as excinfo:
        BddkWeeklyParser().parse(asset)

    assert excinfo.value.payload.error_code == "PARSE_FAILED"
