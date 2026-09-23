"""Generic, deterministic CSV/XLSX intake.

This module deliberately does not ask an LLM to identify file structure.  It
keeps a lossless string frame for the existing profiling/publishing contract,
and also exposes a conservative typed frame for callers that want a canonical
representation.  Parsing warnings are data, not log-only side effects.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

_DELIMITERS = (",", ";", "\t", "|")
_MISSING = {"", "-", "—", "n/a", "na", "null", "none", "nan"}
_YEAR_OR_CODE = re.compile(r"^(?:0\d+|19\d{2}|20\d{2}|\d{4,})$")
_ID_SHAPE = re.compile(r"^(?:\d{2,}[-/]\d+|0\d+)$")
_NUMBER_SHAPE = re.compile(r"^[+\-]?\(?\s*[0-9][0-9 .,'\u00a0]*\)?\s*%?$")
_DATE_SHAPE = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}(?:[ T]\d{1,2}:\d{2}.*)?$")
MAX_ROWS_DEFAULT = 1_000_000
MAX_COLUMNS_DEFAULT = 10_000


@dataclass(frozen=True)
class ColumnQuality:
    original_label: str
    display_label: str
    internal_name: str
    inferred_type: str
    null_ratio: float
    suspicious_coercions: tuple[str, ...] = ()


@dataclass(frozen=True)
class TabularQualityReport:
    parser: str
    encoding: str | None
    delimiter: str | None
    sheet: str | None
    header_row: int | None
    row_count: int
    column_count: int
    null_ratios: dict[str, float] = field(default_factory=dict)
    duplicate_rows: int = 0
    duplicate_headers: int = 0
    malformed_rows: int = 0
    skipped_rows: tuple[int, ...] = ()
    inferred_types: dict[str, str] = field(default_factory=dict)
    suspicious_coercions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    confidence: float = 0.0
    status: str = "PARSE_FAILED"
    error_code: str | None = None
    temporal_frequency: str | None = None
    temporal_confidence: str | None = None
    temporal_evidence: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parser": self.parser, "encoding": self.encoding,
            "delimiter": self.delimiter, "sheet": self.sheet,
            "header_row": self.header_row, "row_count": self.row_count,
            "column_count": self.column_count, "null_ratios": dict(self.null_ratios),
            "duplicate_rows": self.duplicate_rows, "duplicate_headers": self.duplicate_headers,
            "malformed_rows": self.malformed_rows, "skipped_rows": list(self.skipped_rows),
            "inferred_types": dict(self.inferred_types),
            "suspicious_coercions": {k: list(v) for k, v in self.suspicious_coercions.items()},
            "warnings": list(self.warnings), "confidence": self.confidence,
            "status": self.status, "error_code": self.error_code,
            "temporal_frequency": self.temporal_frequency,
            "temporal_confidence": self.temporal_confidence,
            "temporal_evidence": list(self.temporal_evidence),
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class TabularParseResult:
    """Both lossless and normalized views of one uploaded table."""

    raw_frame: pd.DataFrame
    frame: pd.DataFrame
    quality: TabularQualityReport
    column_quality: tuple[ColumnQuality, ...]
    provenance: dict[str, Any]


class TabularParseError(ValueError):
    def __init__(self, message: str, *, code: str = "PARSE_FAILED", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _text_score(text: str) -> float:
    if not text:
        return 0.0
    good = sum(ch.isprintable() or ch in "\r\n\t" for ch in text)
    controls = sum(ord(ch) < 32 and ch not in "\r\n\t" for ch in text)
    return max(0.0, good / len(text) - controls / max(1, len(text)))


def detect_encoding(content: bytes) -> tuple[str, str]:
    """Strictly decode common encodings; never replace undecodable bytes."""

    candidates: list[tuple[str, str]] = []
    if content.startswith(b"\xef\xbb\xbf"):
        candidates.append(("utf-8-sig", content.decode("utf-8-sig")))
    else:
        for name in ("utf-8", "cp1254", "cp1252", "latin-1"):
            try:
                candidates.append((name, content.decode(name)))
            except UnicodeDecodeError:
                continue
    if not candidates:
        raise TabularParseError("dosya metin kodlamasıyla çözülemedi", code="ENCODING_UNSUPPORTED")

    def score(item: tuple[str, str]) -> tuple[float, int, int]:
        name, text = item
        turkish = sum(text.count(c) for c in "çğıöşüÇĞİÖŞÜ")
        utf_bonus = 0 if name == "latin-1" else 1
        return (_text_score(text), turkish, utf_bonus)

    name, text = max(candidates, key=score)
    if _text_score(text) < 0.92:
        raise TabularParseError("dosya metin olarak güvenli biçimde çözülemedi", code="ENCODING_UNSUPPORTED")
    return text, name


def _row_width_score(rows: list[list[str]], delimiter: str) -> tuple[float, int]:
    if not rows:
        return 0.0, 0
    widths = [len(r) for r in rows[:80]]
    useful = [w for w in widths if w > 1]
    if not useful:
        return 0.0, 0
    mode = max(set(useful), key=useful.count)
    consistent = sum(w == mode for w in useful) / len(useful)
    return consistent * min(1.0, len(useful) / 3) * mode, mode


def detect_delimiter(text: str, *, suffix: str = "") -> tuple[str, float]:
    candidates: list[tuple[float, str]] = []
    for delimiter in _DELIMITERS:
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter, strict=False))
        except csv.Error:
            continue
        score, mode = _row_width_score(rows, delimiter)
        if suffix == ".tsv" and delimiter == "\t":
            score += 0.5
        if mode > 1:
            candidates.append((score, delimiter))
    if not candidates:
        raise TabularParseError("CSV/TSV ayıracı güvenle saptanamadı", code="DELIMITER_UNDETERMINED")
    candidates.sort(reverse=True)
    best, delimiter = candidates[0]
    second = candidates[1][0] if len(candidates) > 1 else 0.0
    if best < 0.8 or (best - second < 0.12 and best < 1.8):
        raise TabularParseError("CSV ayıracı belirsiz; virgül, noktalı virgül, sekme veya dikey çizgiyi belirtin",
                                code="DELIMITER_UNDETERMINED")
    return delimiter, min(1.0, best / 2.0)


def _empty(value: Any) -> bool:
    return value is None or str(value).strip().lower() in _MISSING


def _numeric(value: str) -> tuple[float | None, bool]:
    text = value.strip().replace("\u00a0", " ")
    if not text or text.lower() in _MISSING:
        return None, True
    if _ID_SHAPE.fullmatch(text):
        return None, False
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("() ")
    text = text.replace(" ", "")
    if not re.fullmatch(r"[+\-]?\d[\d.,]*", text):
        return None, False
    commas, dots = text.count(","), text.count(".")
    if commas and dots:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        parts = text.split(decimal)
        if len(parts) != 2 or not re.fullmatch(r"\d{1,3}(?:" + re.escape(thousands) + r"\d{3})+", parts[0]):
            return None, False
        normalized = parts[0].replace(thousands, "") + "." + parts[1]
    elif commas or dots:
        sep = "," if commas else "."
        count = text.count(sep)
        tail = text.rsplit(sep, 1)[1]
        if count > 1:
            groups = text.split(sep)
            if not all(g.isdigit() for g in groups) or not all(len(g) == 3 for g in groups[1:]):
                return None, False
            normalized = "".join(groups)
        elif len(tail) == 3 and len(text.split(sep, 1)[0]) <= 3:
            # One separator with three trailing digits is ambiguous.  Keep it
            # as text unless the column has a stronger header/type signal.
            return None, False
        else:
            normalized = text.replace(sep, ".")
    else:
        normalized = text
    try:
        result = float(normalized)
    except ValueError:
        return None, False
    if negative:
        result = -result
    return result, True


def _infer_column(values: list[str], label: str) -> tuple[str, list[Any], tuple[str, ...]]:
    nonempty = [v.strip() for v in values if not _empty(v)]
    if not nonempty:
        return "empty", [None] * len(values), ()
    lower = {v.lower() for v in nonempty}
    if lower <= {"true", "false", "yes", "no", "evet", "hayır", "hayir"}:
        mapped = [None if _empty(v) else v.strip().lower() in {"true", "yes", "evet"} for v in values]
        return "bool", mapped, ()
    if all(_DATE_SHAPE.fullmatch(v) for v in nonempty) or all(re.fullmatch(r"\d{4}-\d{2}", v) for v in nonempty):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(pd.Series(nonempty), errors="coerce", dayfirst=True)
        if parsed.notna().all() and (not all(re.fullmatch(r"\d{4}-\d{2}", v) for v in nonempty)) \
                and not (parsed.dt.day <= 12).all() and len(set(parsed.dt.strftime("%Y-%m-%d"))) > 1:
            out = []
            for value in values:
                if _empty(value):
                    out.append(None)
                    continue
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    out.append(pd.to_datetime(value, dayfirst=not value[:4].isdigit()).to_pydatetime())
            return "datetime", out, ()
        if parsed.notna().all() and all(re.fullmatch(r"\d{4}-\d{2}", v) for v in nonempty):
            out = [None if _empty(v) else pd.to_datetime(v + "-01").to_pydatetime() for v in values]
            return "date", out, ()
    id_header = bool(re.search(r"id|kod|code|identifier|kimlik|year|yıl|yil", label, re.IGNORECASE))
    all_years = all(v.isdigit() and len(v) == 4 and 1900 <= int(v) <= 2100 for v in nonempty)
    if (id_header and all(_YEAR_OR_CODE.fullmatch(v) for v in nonempty)) or all_years \
            or any(v.startswith("0") and len(v) > 1 for v in nonempty) \
            or any(_ID_SHAPE.fullmatch(v) for v in nonempty):
        return "categorical", values, ("year/code-looking values kept as text",)
    parsed: list[float | None] = []
    valid = True
    for value in values:
        number, ok = _numeric(value)
        parsed.append(number)
        if not ok and not _empty(value):
            valid = False
    numeric_header = bool(re.search(r"%|oran|faiz|rate|tutar|miktar|değer|deger|value|amount", label, re.IGNORECASE))
    strong_numeric = any(re.search(r"[,.]", v) for v in nonempty) or any(v.endswith("%") for v in nonempty)
    if all(v.endswith("%") for v in nonempty):
        return "percentage", parsed, ("percentage values retained as numeric percentage points",)
    if valid and sum(v is not None for v in parsed) == len(nonempty) and (numeric_header or len(nonempty) >= 3 or strong_numeric):
        if all(float(v).is_integer() for v in parsed if v is not None):
            return "int", parsed, ()
        return "float", parsed, ()
    suspicious = () if valid else ("some values did not satisfy the same numeric grammar",)
    return "categorical", values, suspicious


def _safe_internal_name(label: str, position: int, seen: set[str]) -> str:
    normalized = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9_]+", "_", normalized).strip("_").lower() or f"column_{position + 1}"
    if base[0].isdigit():
        base = f"column_{base}"
    candidate = base
    suffix = 2
    while candidate in seen:
        candidate = f"{base}_{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def _safe_columns(labels: list[str]) -> tuple[list[str], int, list[str]]:
    names: list[str] = []
    seen: dict[str, int] = {}
    internal_seen: set[str] = set()
    internal_names: list[str] = []
    duplicates = 0
    for idx, label in enumerate(labels):
        display = str(label).strip() or f"column_{idx + 1}"
        n = seen.get(display, 0) + 1
        seen[display] = n
        if n > 1:
            duplicates += 1
            names.append(f"{display}__{n}")
        else:
            names.append(display)
        internal_names.append(_safe_internal_name(display, idx, internal_seen))
    return names, duplicates, internal_names


def _header_candidate(rows: list[list[str]], index: int) -> float:
    row = rows[index]
    width = len(row)
    nonempty = [str(v).strip() for v in row if not _empty(v)]
    if width < 2 or len(nonempty) < 2:
        return -1.0
    unique = len(set(nonempty)) / len(nonempty)
    textual = sum(not _NUMBER_SHAPE.fullmatch(v) and not _DATE_SHAPE.fullmatch(v) for v in nonempty) / len(nonempty)
    next_rows = rows[index + 1:index + 6]
    rectangular = sum(abs(len(r) - width) <= 1 for r in next_rows) / max(1, len(next_rows))
    return 0.35 * unique + 0.35 * textual + 0.30 * rectangular - index * 0.015


def _parse_rows(rows: list[list[str]], *, source_name: str, parser: str, encoding: str | None,
                delimiter: str | None, sheet: str | None, header_row_offset: int = 0,
                warnings: list[str] | None = None, source_rows: list[int] | None = None) -> TabularParseResult:
    warnings = list(warnings or [])
    if len(rows) > MAX_ROWS_DEFAULT + 100:
        raise TabularParseError("tablo satır sınırını aşıyor", code="ROW_LIMIT")
    nonempty_indexes = [i for i, r in enumerate(rows) if any(not _empty(v) for v in r)]
    if not nonempty_indexes:
        raise TabularParseError("tabloda hiç veri yok", code="EMPTY_TABLE")
    candidates = sorted((( _header_candidate(rows, i), i) for i in nonempty_indexes[:30]), reverse=True)
    best_score, header = candidates[0]
    second = candidates[1][0] if len(candidates) > 1 else 0.0
    if best_score < 0.52 and all(len(rows[i]) <= 1 for i in nonempty_indexes):
        # A one-column export is still a valid table; there is no delimiter
        # evidence, so the first populated row is the only defensible header.
        header = nonempty_indexes[0]
        best_score = 0.6
        second = 0.0
    elif best_score < 0.52:
        raise TabularParseError("tablo başlığı güvenle saptanamadı", code="HEADER_UNDETERMINED")
    if best_score - second < 0.04 and header != nonempty_indexes[0]:
        warnings.append("birden fazla olası başlık satırı var; ilk güçlü aday seçildi")
    labels = [str(v).strip() for v in rows[header]]
    if len(labels) > MAX_COLUMNS_DEFAULT:
        raise TabularParseError("tablo sütun sınırını aşıyor", code="COLUMN_LIMIT")
    columns, duplicate_headers, internal_names = _safe_columns(labels)
    data: list[list[str]] = []
    row_numbers: list[int] = []
    malformed: list[int] = []
    max_width = len(columns)
    blanks_after_data = 0
    for idx in range(header + 1, len(rows)):
        row = ["" if v is None else str(v) for v in rows[idx]]
        if not any(v.strip() for v in row):
            if data:
                blanks_after_data += 1
                if blanks_after_data >= 1:
                    break
            continue
        blanks_after_data = 0
        # A non-rectangular row is retained and reported.  Extra cells are
        # retained in deterministic extra columns rather than dropped.
        if len(row) != max_width:
            malformed.append(idx + header_row_offset + 1)
            max_width = max(max_width, len(row))
        data.append(row)
        row_numbers.append(idx + header_row_offset + 1)
    if not data:
        raise TabularParseError("başlık satırından sonra veri yok", code="EMPTY_TABLE")
    if max_width > len(columns):
        if max_width > MAX_COLUMNS_DEFAULT:
            raise TabularParseError("tablo sütun sınırını aşıyor", code="COLUMN_LIMIT")
        columns.extend(f"__extra_{i}" for i in range(1, max_width - len(columns) + 1))
    padded = [r + [""] * (max_width - len(r)) for r in data]
    raw = pd.DataFrame(padded, columns=columns).fillna("")
    typed_columns: dict[str, list[Any]] = {}
    column_quality: list[ColumnQuality] = []
    inferred: dict[str, str] = {}
    suspicious: dict[str, tuple[str, ...]] = {}
    null_ratios: dict[str, float] = {}
    for pos, column in enumerate(raw.columns):
        original = labels[pos] if pos < len(labels) else column
        kind, typed, notes = _infer_column(raw[column].tolist(), original)
        typed_columns[column] = typed
        inferred[column] = kind
        suspicious[column] = notes
        null_ratios[column] = sum(_empty(v) for v in raw[column]) / max(1, len(raw))
        internal = internal_names[pos] if pos < len(internal_names) else _safe_internal_name(column, pos, set())
        column_quality.append(ColumnQuality(original, original or column, internal, kind, null_ratios[column], notes))
    typed = pd.DataFrame(typed_columns, columns=raw.columns)
    duplicate_rows = int(raw.duplicated().sum())
    if malformed:
        warnings.append(f"{len(malformed)} satır beklenen sütun sayısından farklı; satırlar korunarak dolduruldu")
    if duplicate_headers:
        warnings.append(f"{duplicate_headers} yinelenen başlık deterministik iç adla ayrıştırıldı")
    status = "PASS_WITH_WARNINGS" if warnings or malformed or duplicate_headers else "PASS"
    confidence = max(0.0, min(1.0, 0.55 + best_score * 0.45 - (0.1 if malformed else 0)))
    provenance = {
        "original_filename": Path(source_name.split("?")[0]).name,
        "file_type": Path(source_name.split("?")[0]).suffix.lower().lstrip("."),
        "sheet": sheet,
        "header_source_row": header + header_row_offset + 1,
        "source_rows": row_numbers,
        "columns": [
            {"original_label": c.original_label, "display_label": c.display_label,
             "internal_name": c.internal_name}
            for c in column_quality
        ],
    }
    quality = TabularQualityReport(
        parser=parser, encoding=encoding, delimiter=delimiter, sheet=sheet,
        header_row=header + header_row_offset + 1, row_count=len(raw), column_count=len(raw.columns),
        null_ratios=null_ratios, duplicate_rows=duplicate_rows, duplicate_headers=duplicate_headers,
        malformed_rows=len(malformed), skipped_rows=(), inferred_types=inferred,
        suspicious_coercions=suspicious, warnings=tuple(warnings), confidence=confidence,
        status=status, provenance=provenance,
    )
    from .temporal import infer_temporal
    temporal = infer_temporal(raw)
    quality = TabularQualityReport(
        **{**quality.__dict__, "temporal_frequency": temporal.frequency,
           "temporal_confidence": temporal.confidence, "temporal_evidence": temporal.evidence}
    )
    raw.attrs.update({"tabular_quality": quality, "tabular_provenance": provenance,
                      "column_quality": tuple(column_quality), "temporal_semantics": temporal,
                      "raw_frame": raw.copy()})
    typed.attrs.update(raw.attrs)
    return TabularParseResult(raw, typed, quality, tuple(column_quality), provenance)


def parse_csv_bytes(content: bytes, *, source_name: str = "upload.csv") -> TabularParseResult:
    text, encoding = detect_encoding(content)
    delimiter, _ = detect_delimiter(text, suffix=Path(source_name).suffix.lower())
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter, strict=True))
    except csv.Error as exc:
        # Re-parse leniently only to preserve rows and report the malformed
        # structure; never silently discard the offending record.
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter, strict=False))
        return _parse_rows(rows, source_name=source_name, parser="csv", encoding=encoding,
                           delimiter=delimiter, sheet=None,
                           warnings=[f"CSV alıntı/kaçış sözdizimi bozuk: {exc}"], source_rows=None)
    return _parse_rows(rows, source_name=source_name, parser="csv", encoding=encoding,
                       delimiter=delimiter, sheet=None)


def _validate_xlsx(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > 2000:
                raise TabularParseError("XLSX çok fazla ZIP girdisi içeriyor", code="XLSX_ZIP_LIMIT")
            total = sum(max(0, i.file_size) for i in infos)
            if total > 100 * 1024 * 1024:
                raise TabularParseError("XLSX açılmış boyut sınırını aşıyor", code="XLSX_ZIP_LIMIT")
            for info in infos:
                if info.compress_size and info.file_size / info.compress_size > 100:
                    raise TabularParseError("XLSX sıkıştırma oranı güvenli sınırı aşıyor", code="XLSX_ZIP_LIMIT")
    except zipfile.BadZipFile as exc:
        raise TabularParseError("XLSX paketi bozuk veya uzantısı yanlış", code="XLSX_CORRUPT") from exc


def _sheet_rows(ws) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in ws.iter_rows(values_only=True):
        rows.append(["" if value is None else str(value) for value in row])
    while rows and not any(v.strip() for v in rows[-1]):
        rows.pop()
    return rows


def parse_xlsx_bytes(content: bytes, *, source_name: str = "upload.xlsx", sheet: str | int | None = None) -> TabularParseResult:
    _validate_xlsx(content)
    try:
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
    except TabularParseError:
        raise
    except Exception as exc:
        raise TabularParseError(f"XLSX okunamadı: {type(exc).__name__}", code="XLSX_CORRUPT") from exc
    names = list(workbook.sheetnames)
    if not names:
        raise TabularParseError("XLSX dosyasında sayfa yok", code="XLSX_NO_SHEET")
    candidates: list[tuple[float, str, list[list[str]]]] = []
    for name in names:
        rows = _sheet_rows(workbook[name])
        if not rows:
            continue
        nonempty = [r for r in rows if any(v.strip() for v in r)]
        width = max((len(r) for r in nonempty), default=0)
        score = min(1.0, len(nonempty) / 10) * min(1.0, width / 4)
        if width >= 2 and len(nonempty) >= 2:
            score += max(0.0, _header_candidate(rows, next(i for i, r in enumerate(rows) if any(v.strip() for v in r))))
        candidates.append((score, name, rows))
    if sheet is None:
        if not candidates:
            raise TabularParseError("XLSX içinde dolu tablo sayfası yok", code="XLSX_NO_TABLE")
        candidates.sort(reverse=True)
        if len(candidates) > 1 and (candidates[0][0] - candidates[1][0] < 0.18 or len(candidates[0][2]) < 3):
            raise TabularParseError("Excel dosyasında birden çok sayfa var: " + ", ".join(names) + " — `sheet` ile birini seç",
                                    code="XLSX_SHEET_UNDETERMINED",
                                    details={"candidates": [n for _, n, _ in candidates]})
        _, selected, rows = candidates[0]
        warning = [f"tek güçlü tablo sayfası otomatik seçildi: {selected}"] if len(names) > 1 else []
    else:
        selected = int(sheet) if isinstance(sheet, int) or str(sheet).isdigit() else str(sheet)
        if isinstance(selected, int):
            if selected < 0 or selected >= len(names):
                raise TabularParseError(f"sayfa indeksi {selected} yok", code="XLSX_SHEET_NOT_FOUND")
            selected = names[selected]
        if selected not in names:
            raise TabularParseError(f"sayfa '{selected}' yok; sayfalar: {', '.join(names)}", code="XLSX_SHEET_NOT_FOUND")
        rows = _sheet_rows(workbook[selected])
        warning = []
    result = _parse_rows(rows, source_name=source_name, parser="xlsx", encoding=None,
                         delimiter=None, sheet=selected, warnings=warning)
    return result


def parse_tabular_bytes(content: bytes, *, source_name: str = "upload.csv", sheet: str | int | None = None) -> TabularParseResult:
    suffix = Path(source_name.split("?")[0]).suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        if suffix == ".xlsm":
            raise TabularParseError("makro içeren XLSM kabul edilmiyor; makrosuz XLSX yükleyin", code="MACRO_REFUSED")
        return parse_xlsx_bytes(content, source_name=source_name, sheet=sheet)
    if suffix == ".xls":
        raise TabularParseError("eski Excel (.xls) desteklenmiyor; dosyayı .xlsx olarak kaydedin", code="XLS_UNSUPPORTED")
    return parse_csv_bytes(content, source_name=source_name)


__all__ = [
    "MAX_COLUMNS_DEFAULT", "MAX_ROWS_DEFAULT", "ColumnQuality", "TabularParseError", "TabularParseResult", "TabularQualityReport",
    "detect_delimiter", "detect_encoding", "parse_csv_bytes", "parse_tabular_bytes", "parse_xlsx_bytes",
]
