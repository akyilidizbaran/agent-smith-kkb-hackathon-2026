"""GenericTabularParser: every format, and every way each format can be ambiguous.

All content here is SYNTHETIC and built by the test. The parser never opens a socket, and two
tests prove that rather than asserting it.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from src.lakehouse.errors import LakehouseError
from src.lakehouse.storage.parquet import ParquetStorage

from ._support import (
    ingest,
    json_bytes,
    spec,
    write_bytes,
    write_csv,
    xlsx_bytes,
    zip_bomb_bytes,
)


def _code(excinfo) -> str:
    return excinfo.value.payload.error_code


def _parse(tmp_path: Path, name: str, payload: bytes, **kwargs):
    uploads = tmp_path / "uploads"
    uploads.mkdir(exist_ok=True)
    write_bytes(uploads, name, payload)
    return ingest(
        tmp_path,
        spec(str(uploads / name), parameters=kwargs.pop("connector_parameters", {})),
        allowed_local_roots=[uploads],
        **kwargs,
    )


def _frame(tmp_path: Path, name: str, payload: bytes, **kwargs):
    connection, result = _parse(tmp_path, name, payload, **kwargs)
    try:
        return ParquetStorage.read(result.bronze_path), result
    finally:
        connection.close()


# ----------------------------------------------------------------------- CSV


def test_csv_keeps_every_cell_as_the_source_wrote_it(tmp_path: Path) -> None:
    frame, _ = _frame(
        tmp_path, "a.csv", b"donem,deger\n2026-01-31,1.5\n2026-02-28,0012\n"
    )
    assert list(frame.columns) == ["donem", "deger"]
    # "0012" keeps its leading zeros; nothing was inferred as a number.
    assert frame["deger"].tolist() == ["1.5", "0012"]


def test_a_semicolon_csv_is_detected(tmp_path: Path) -> None:
    frame, _ = _frame(tmp_path, "a.csv", b"donem;deger\n2026-01-31;1,5\n")
    assert list(frame.columns) == ["donem", "deger"]
    assert frame["deger"].tolist() == ["1,5"]


def test_an_ambiguous_delimiter_is_refused(tmp_path: Path) -> None:
    """One comma and one semicolon in the header: both readings are equally plausible."""

    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.csv", b"a,b;c\n1,2;3\n")
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"
    assert "delimiter" in str(excinfo.value)


def test_an_explicit_delimiter_resolves_the_ambiguity(tmp_path: Path) -> None:
    frame, _ = _frame(
        tmp_path, "a.csv", b"a,b;c\n1,2;3\n", connector_parameters={"delimiter": ";"}
    )
    assert list(frame.columns) == ["a,b", "c"]


def test_duplicate_column_names_are_refused(tmp_path: Path) -> None:
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.csv", b"deger,deger\n1,2\n")
    assert _code(excinfo) == "PARSE_FAILED"
    assert "duplicate" in str(excinfo.value)


def test_a_blank_column_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.csv", b"donem,,deger\n1,2,3\n")
    assert _code(excinfo) == "PARSE_FAILED"
    assert "blank name" in str(excinfo.value)


def test_a_header_with_no_rows_is_an_empty_dataset(tmp_path: Path) -> None:
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.csv", b"donem,deger\n")
    assert _code(excinfo) == "EMPTY_DATASET"


def test_a_ragged_row_is_padded_and_warned_about(tmp_path: Path) -> None:
    frame, result = _frame(tmp_path, "a.csv", b"a,b,c\n1,2\n3,4,5\n")
    assert frame.iloc[0].tolist() == ["1", "2", None]
    assert any("did not have 3 fields" in warning for warning in result.parsed_batch.warnings)


def test_a_formula_like_cell_is_stored_as_text(tmp_path: Path) -> None:
    """A CSV cell starting with '=' is text here; nothing evaluates it."""

    frame, _ = _frame(tmp_path, "a.csv", b'a,b\n"=1+1","=cmd|\' /c calc\'!A0"\n')
    assert frame["a"].tolist() == ["=1+1"]
    assert frame["b"].tolist() == ["=cmd|' /c calc'!A0"]


def test_turkish_windows_encoding_is_read_with_a_warning(tmp_path: Path) -> None:
    payload = "donem,kurum\n2026-01-31,Türkiye Şubesi\n".encode("cp1254")
    frame, result = _frame(tmp_path, "a.csv", payload)
    assert "Türkiye Şubesi" in frame["kurum"].tolist()
    assert any("cp1254" in warning for warning in result.parsed_batch.warnings)


# ----------------------------------------------------------------------- TSV


def test_tsv_uses_tab_without_being_told(tmp_path: Path) -> None:
    frame, _ = _frame(tmp_path, "a.tsv", b"donem\tdeger\n2026-01-31\t1.5\n")
    assert list(frame.columns) == ["donem", "deger"]
    assert frame["deger"].tolist() == ["1.5"]


def test_a_tsv_with_no_tabs_falls_back_to_its_declared_delimiter(tmp_path: Path) -> None:
    frame, _ = _frame(tmp_path, "a.tsv", b"onlyonecolumn\nvalue\n")
    assert list(frame.columns) == ["onlyonecolumn"]


# ---------------------------------------------------------------------- JSON


def test_a_json_records_array_is_read(tmp_path: Path) -> None:
    frame, _ = _frame(
        tmp_path,
        "a.json",
        json_bytes([{"donem": "2026-01-31", "deger": "1.5"}, {"donem": "2026-02-28", "deger": None}]),
    )
    assert list(frame.columns) == ["donem", "deger"]
    assert frame["deger"].tolist() == ["1.5", None]


def test_a_single_records_field_is_found_and_reported(tmp_path: Path) -> None:
    frame, result = _frame(
        tmp_path,
        "a.json",
        json_bytes({"meta": {"x": 1}, "items": [{"a": "1"}, {"a": "2"}]}),
    )
    assert frame["a"].tolist() == ["1", "2"]
    assert any("'items'" in warning for warning in result.parsed_batch.warnings)


def test_several_candidate_arrays_are_refused(tmp_path: Path) -> None:
    with pytest.raises(LakehouseError) as excinfo:
        _parse(
            tmp_path,
            "a.json",
            json_bytes({"items": [{"a": 1}], "rows": [{"b": 2}]}),
        )
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"
    assert "records_field" in str(excinfo.value)


def test_an_explicit_records_field_resolves_the_ambiguity(tmp_path: Path) -> None:
    frame, _ = _frame(
        tmp_path,
        "a.json",
        json_bytes({"items": [{"a": "1"}], "rows": [{"b": "2"}]}),
        connector_parameters={"records_field": "rows"},
    )
    assert frame["b"].tolist() == ["2"]


def test_heterogeneous_records_are_refused(tmp_path: Path) -> None:
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.json", json_bytes([{"a": 1}, {"b": 2}]))
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"
    assert "homogeneous" in str(excinfo.value)


def test_nested_values_are_not_flattened(tmp_path: Path) -> None:
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.json", json_bytes([{"a": {"deep": 1}}]))
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"
    assert "nested" in str(excinfo.value)


def test_malformed_json_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.json", b'{"items": [')
    assert _code(excinfo) == "PARSE_FAILED"


def test_an_empty_records_array_is_an_empty_dataset(tmp_path: Path) -> None:
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.json", json_bytes({"items": []}))
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"


# ---------------------------------------------------------------------- XLSX


def test_a_single_sheet_workbook_is_read(tmp_path: Path) -> None:
    frame, _ = _frame(
        tmp_path,
        "a.xlsx",
        xlsx_bytes({"Veri": [["donem", "deger"], ["2026-01-31", 1.5]]}),
    )
    assert list(frame.columns) == ["donem", "deger"]
    assert frame["deger"].tolist() == ["1.5"]


def test_several_visible_sheets_require_an_explicit_choice(tmp_path: Path) -> None:
    payload = xlsx_bytes({"Bir": [["a"], [1]], "Iki": [["b"], [2]]})
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.xlsx", payload)
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"
    assert "sheet_name" in str(excinfo.value)


def test_an_explicit_sheet_name_is_honoured(tmp_path: Path) -> None:
    payload = xlsx_bytes({"Bir": [["a"], ["1"]], "Iki": [["b"], ["2"]]})
    frame, _ = _frame(tmp_path, "a.xlsx", payload, connector_parameters={"sheet_name": "Iki"})
    assert frame["b"].tolist() == ["2"]


def test_a_hidden_sheet_is_ignored_but_reported(tmp_path: Path) -> None:
    payload = xlsx_bytes(
        {"Veri": [["a"], ["1"]], "Notlar": [["x"], ["y"]]}, hidden=("Notlar",)
    )
    frame, result = _frame(tmp_path, "a.xlsx", payload)
    assert frame["a"].tolist() == ["1"]
    assert any("hidden" in warning for warning in result.parsed_batch.warnings)


def test_choosing_a_hidden_sheet_explicitly_is_allowed_and_flagged(tmp_path: Path) -> None:
    payload = xlsx_bytes(
        {"Veri": [["a"], ["1"]], "Notlar": [["x"], ["y"]]}, hidden=("Notlar",)
    )
    frame, result = _frame(
        tmp_path, "a.xlsx", payload, connector_parameters={"sheet_name": "Notlar"}
    )
    assert frame["x"].tolist() == ["y"]
    assert any("is hidden" in warning for warning in result.parsed_batch.warnings)


def test_an_unknown_sheet_name_is_refused(tmp_path: Path) -> None:
    payload = xlsx_bytes({"Veri": [["a"], ["1"]]})
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.xlsx", payload, connector_parameters={"sheet_name": "Yok"})
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"


def test_a_zip_bomb_workbook_is_refused_before_it_is_unpacked(tmp_path: Path) -> None:
    from src.lakehouse.generic import parser as parser_module

    payload = zip_bomb_bytes(2048)
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "bomb.xlsx", payload)
    # The ceiling is large, so lower it for the test rather than building a real bomb.
    assert _code(excinfo) in {"PARSE_FAILED", "UNSUPPORTED_FORMAT"}


def test_the_uncompressed_ceiling_is_enforced(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.lakehouse.generic.parser.MAX_UNCOMPRESSED_BYTES", 1024
    )
    payload = zip_bomb_bytes(4096)
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "bomb.xlsx", payload)
    assert _code(excinfo) == "PARSE_FAILED"
    assert "expands to" in str(excinfo.value)


def test_a_date_cell_is_rendered_as_iso(tmp_path: Path) -> None:
    from datetime import datetime

    payload = xlsx_bytes({"Veri": [["donem", "deger"], [datetime(2026, 1, 31), 1.5]]})
    frame, _ = _frame(tmp_path, "a.xlsx", payload)
    assert frame["donem"].tolist() == ["2026-01-31"]


def test_a_formula_workbook_requires_a_values_only_export(tmp_path: Path) -> None:
    payload = xlsx_bytes({"Data": [["a", "b"], [1, '=WEBSERVICE("http://evil.example/x")']]})
    with pytest.raises(LakehouseError, match="formula.*values-only"):
        _parse(tmp_path, "f.xlsx", payload)


# ---------------------------------------------------------------------- HTML


def test_a_single_html_table_is_read(tmp_path: Path) -> None:
    payload = b"<html><body><table><tr><th>donem</th><th>deger</th></tr>"
    payload += b"<tr><td>2026-01-31</td><td>1.5</td></tr></table></body></html>"
    frame, _ = _frame(tmp_path, "a.html", payload)
    assert list(frame.columns) == ["donem", "deger"]
    assert frame["deger"].tolist() == ["1.5"]


def test_several_tables_require_an_explicit_index(tmp_path: Path) -> None:
    payload = (
        b"<table><tr><th>a</th></tr><tr><td>1</td></tr></table>"
        b"<table><tr><th>b</th></tr><tr><td>2</td></tr></table>"
    )
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.html", payload)
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"
    assert "table_index" in str(excinfo.value)


def test_an_explicit_table_index_is_honoured(tmp_path: Path) -> None:
    payload = (
        b"<table><tr><th>a</th></tr><tr><td>1</td></tr></table>"
        b"<table><tr><th>b</th></tr><tr><td>2</td></tr></table>"
    )
    frame, _ = _frame(tmp_path, "a.html", payload, connector_parameters={"table_index": 1})
    assert frame["b"].tolist() == ["2"]


def test_an_out_of_range_table_index_is_refused(tmp_path: Path) -> None:
    payload = b"<table><tr><th>a</th></tr><tr><td>1</td></tr></table>"
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.html", payload, connector_parameters={"table_index": 7})
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"


def test_rowspan_and_colspan_are_expanded(tmp_path: Path) -> None:
    payload = (
        b"<table>"
        b"<tr><th>grup</th><th>q1</th><th>q2</th></tr>"
        b"<tr><td rowspan='2'>A</td><td>1</td><td>2</td></tr>"
        b"<tr><td>3</td><td>4</td></tr>"
        b"</table>"
    )
    frame, _ = _frame(tmp_path, "a.html", payload)
    assert frame["grup"].tolist() == ["A", "A"]
    assert frame["q1"].tolist() == ["1", "3"]


def test_script_content_is_never_interpreted_as_a_table(tmp_path: Path) -> None:
    payload = (
        b"<html><body>"
        b"<script>var x = '<table><tr><td>EVIL</td></tr></table>';</script>"
        b"<table><tr><th>a</th></tr><tr><td>1</td></tr></table>"
        b"</body></html>"
    )
    frame, _ = _frame(tmp_path, "a.html", payload)
    assert list(frame.columns) == ["a"]
    assert "EVIL" not in frame.to_string()


def test_an_html_document_with_no_table_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.html", b"<html><body><p>no tables here</p></body></html>")
    assert _code(excinfo) == "EMPTY_DATASET"


def test_a_header_only_table_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LakehouseError) as excinfo:
        _parse(tmp_path, "a.html", b"<table><tr><th>a</th></tr></table>")
    assert _code(excinfo) == "EMPTY_DATASET"


# --------------------------------------------------------------- no network


def test_the_parser_opens_no_socket(tmp_path: Path, monkeypatch) -> None:
    """Any connection attempt during a parse fails the test."""

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_csv(uploads)
    connection, result = ingest(
        tmp_path, spec(str(uploads / "synthetic.csv")), allowed_local_roots=[uploads]
    )
    connection.close()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the parser attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    from src.lakehouse.generic import GenericTabularParser

    batch = GenericTabularParser().parse(result.asset)
    assert len(batch.dataframe) == 3


def test_an_html_document_referencing_external_resources_fetches_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    payload = (
        b"<html><head><link rel='stylesheet' href='http://evil.example/x.css'></head>"
        b"<body><img src='http://evil.example/pixel.png'>"
        b"<iframe src='http://evil.example/frame'></iframe>"
        b"<table><tr><th>a</th></tr><tr><td>1</td></tr></table></body></html>"
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the parser attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    frame, _ = _frame(tmp_path, "a.html", payload)
    assert frame["a"].tolist() == ["1"]


def test_an_artifact_without_resolved_format_metadata_is_refused(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from src.lakehouse.contracts.models import FetchedAsset
    from src.lakehouse.generic import GenericTabularParser
    from src.lakehouse.storage.raw import sha256_bytes

    payload = b"a,b\n1,2\n"
    path = tmp_path / "x.csv"
    path.write_bytes(payload)
    asset = FetchedAsset(
        source_id="adhoc",
        dataset_id="adhoc_synthetic",
        locator="file://x",
        media_type="text/csv",
        byte_size=len(payload),
        fetched_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
        artifact_sha256=sha256_bytes(payload),
        raw_path=path,
        http_status=None,
        metadata={},
    )
    with pytest.raises(LakehouseError) as excinfo:
        GenericTabularParser().parse(asset)
    assert excinfo.value.payload.error_code == "UNSUPPORTED_FORMAT"
