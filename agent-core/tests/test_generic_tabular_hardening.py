"""Synthetic, source-neutral coverage for the generic CSV/XLSX reader."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.builder.read import ReadRefused, _table_from_bytes, read_tabular_bytes
from kkb_agent.builder.tabular import parse_csv_bytes, parse_xlsx_bytes


def _xlsx(sheets: dict[str, list[list[object]]], *, hidden: set[str] | None = None) -> bytes:
    hidden = hidden or set()
    book = Workbook()
    first = True
    for name, rows in sheets.items():
        ws = book.active if first else book.create_sheet()
        first = False
        ws.title = name
        if name in hidden:
            ws.sheet_state = "hidden"
        for row in rows:
            ws.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_csv_utf8_bom_semicolon_european_numbers_and_preamble() -> None:
    content = "Rapor başlığı\n\nTarih;TP Mevduat;Kod\n2025-01;1.234,56;001234\n2025-02;2.345,67;10-001\n".encode("utf-8-sig")
    result = parse_csv_bytes(content, source_name="mevduat.csv")

    assert list(result.raw_frame.columns) == ["Tarih", "TP Mevduat", "Kod"]
    assert result.raw_frame.iloc[0, 1] == "1.234,56"
    assert result.quality.encoding == "utf-8-sig"
    assert result.quality.delimiter == ";"
    assert result.quality.header_row == 3
    assert result.quality.inferred_types["TP Mevduat"] == "float"
    assert result.quality.inferred_types["Kod"] == "categorical"
    assert result.provenance["source_rows"] == [4, 5]


def test_preamble_text_survives_into_frame_attrs() -> None:
    # Önsözü tablodan ayırmak yetmez: "Dışa Aktarım Tarihi" verinin ne zaman çekildiğini
    # söyleyen kanıttır, kanıt zincirine ulaşmalı. Ayrıştırıcı ile okuyucu arasındaki bu
    # köprü bir kez sessizce koptu (rapor `skipped_rows=()` sabitiyle kuruluyordu, kimse
    # fark etmedi çünkü testler yalnızca `header_row`'a bakıyordu) — bu test o kopuğu tutar.
    content = "Dışa Aktarım Tarihi: 23.09.2026\nKaynak: TCMB EVDS\n\nTarih;Deger\n2025-01;10\n2025-02;12\n".encode("utf-8")

    quality = parse_csv_bytes(content, source_name="rapor.csv").quality
    assert quality.skipped_rows == (1, 2)
    assert quality.skipped_text == ("Dışa Aktarım Tarihi: 23.09.2026", "Kaynak: TCMB EVDS")
    assert quality.to_dict()["skipped_text"] == ["Dışa Aktarım Tarihi: 23.09.2026", "Kaynak: TCMB EVDS"]

    frame = _table_from_bytes(content, "rapor.csv")
    assert frame.attrs["preamble"] == ["Dışa Aktarım Tarihi: 23.09.2026", "Kaynak: TCMB EVDS"]
    # Önsöz veri değil: tabloya sütun ya da satır olarak sızmamalı.
    assert list(frame.columns) == ["Tarih", "Deger"]
    assert len(frame) == 2


def test_table_without_preamble_tags_nothing() -> None:
    content = "Tarih;Deger\n2025-01;10\n".encode("utf-8")
    quality = parse_csv_bytes(content, source_name="temiz.csv").quality

    assert quality.skipped_rows == ()
    assert quality.skipped_text == ()
    assert "preamble" not in _table_from_bytes(content, "temiz.csv").attrs


def test_csv_cp1254_quotes_multiline_pipe_and_duplicate_headers() -> None:
    content = 'Not;ignored\n"Ürün|adı"|Değer|Değer\n"İzmir\nşubesi"|1,25|2,50\n'.encode("cp1254")
    result = parse_csv_bytes(content, source_name="veri.txt")

    assert result.quality.encoding == "cp1254"
    assert result.quality.delimiter == "|"
    assert list(result.raw_frame.columns) == ["Ürün|adı", "Değer", "Değer__2"]
    assert "İzmir\nşubesi" == result.raw_frame.iloc[0, 0]
    assert result.quality.duplicate_headers == 1
    assert result.quality.status == "PASS_WITH_WARNINGS"


def test_csv_malformed_width_is_retained_and_reported() -> None:
    result = parse_csv_bytes(b"date,value\n2025-01,10\n2025-02,20,unexpected\n", source_name="x.csv")

    assert len(result.raw_frame) == 2
    assert result.quality.malformed_rows == 1
    assert "__extra_1" in result.raw_frame.columns
    assert result.raw_frame.iloc[1]["__extra_1"] == "unexpected"
    assert result.quality.status == "PASS_WITH_WARNINGS"


def test_xlsx_selects_one_clear_tabular_sheet_and_keeps_cached_values() -> None:
    content = _xlsx({
        "Summary": [["last refresh", "today"]],
        "Data": [["Tarih", "3 Aya Kadar TP Mevduat"], ["2025-01", 123], ["2025-02", 456]],
    }, hidden={"Summary"})
    result = parse_xlsx_bytes(content, source_name="report.xlsx")

    assert result.quality.sheet == "Data"
    assert result.raw_frame.columns.tolist() == ["Tarih", "3 Aya Kadar TP Mevduat"]
    assert result.raw_frame.iloc[1, 1] == "456"
    assert any("otomatik seçildi" in warning for warning in result.quality.warnings)


def test_xlsx_two_meaningful_sheets_requires_clarification() -> None:
    content = _xlsx({
        "A": [["date", "value"], ["2025-01", 1], ["2025-02", 2]],
        "B": [["date", "value"], ["2025-01", 3], ["2025-02", 4]],
    })
    with pytest.raises(ReadRefused) as exc:
        read_tabular_bytes(content, "two.xlsx")
    assert exc.value.code == "XLSX_SHEET_UNDETERMINED"
    assert exc.value.details["candidates"] == ["B", "A"]


def test_xlsx_preamble_merged_cells_and_duplicate_headers() -> None:
    book = Workbook()
    ws = book.active
    ws.title = "Veri"
    ws.merge_cells("A1:C1")
    ws["A1"] = "Mevduat raporu"
    ws.append([])
    ws.append(["Tarih", "TP", "TP"])
    ws.append(["2025-01", 10, 20])
    out = io.BytesIO()
    book.save(out)

    result = parse_xlsx_bytes(out.getvalue(), source_name="merged.xlsx")
    assert result.quality.header_row == 3
    assert result.quality.duplicate_headers == 1
    assert result.raw_frame.columns.tolist() == ["Tarih", "TP", "TP__2"]


def test_security_rejects_macro_and_xls() -> None:
    with pytest.raises(ReadRefused) as xlsm:
        read_tabular_bytes(b"not an xlsx", "report.xlsm")
    assert xlsm.value.code == "MACRO_REFUSED"
    with pytest.raises(ReadRefused) as xls:
        read_tabular_bytes(b"not an xls", "report.xls")
    assert xls.value.code == "XLS_UNSUPPORTED"
