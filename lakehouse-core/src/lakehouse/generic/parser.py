"""Turn stored ad-hoc bytes into a source-faithful Bronze frame, or refuse.

This parser reads the persisted RAW artifact and nothing else. It opens no socket, follows no
link, evaluates no formula and runs no macro. What it produces is a table of **strings** with
the source's own column names: no type inference, no date parsing, no number parsing, no
guess at what any column means. Turning those strings into observations is the job of an
explicit mapping, because that is where a human states what the file actually is.

The recurring theme in every format below is the same: when a file admits more than one
reading, this layer refuses and asks for the choice rather than taking the first one. A
silently wrong table is far more expensive than a failed parse.
"""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import io
import json
import zipfile
from typing import Any, Final

import pandas as pd

from ..contracts.models import FetchedAsset, ParsedBatch
from ..errors import ErrorPayload, LakehouseError
from ._html import HtmlTableError, extract_tables
from .formats import CSV, HTML, JSON, TSV, XLSX, FormatError
from .config import ENCODINGS, config_from_metadata


GENERIC_SCHEMA_VERSION: Final[str] = "adhoc_tabular.v1"
"""Bronze schema version for every generic tabular parse."""

MAX_ROWS: Final[int] = 1_000_000
MAX_COLUMNS: Final[int] = 4096
MAX_CELL_CHARS: Final[int] = 32_768
MAX_UNCOMPRESSED_BYTES: Final[int] = 512 * 1024 * 1024
"""Ceiling on a workbook's total uncompressed size, checked from the zip directory before any
entry is read. A 50 KB xlsx that expands to gigabytes is a zip bomb, and openpyxl would
happily start unpacking it."""

_DELIMITERS: Final[str] = ",;\t|"


def _error(asset: FetchedAsset, code: str, message: str) -> LakehouseError:
    return LakehouseError(
        ErrorPayload(
            error_code=code,
            message=message,
            source_id=asset.source_id,
            dataset_id=asset.dataset_id,
            retryable=False,
        )
    )


def _decode(asset: FetchedAsset, content: bytes, warnings: list[str], encoding: str = "auto") -> str:
    """Decode text, recording which encoding worked when it was not the obvious one."""

    if encoding != "auto":
        try:
            return content.decode(encoding)
        except UnicodeDecodeError as exc:
            raise _error(asset, "PARSE_FAILED", "bytes do not match the explicit encoding") from exc
    for index, encoding in enumerate(ENCODINGS):
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        if index >= 2:
            warnings.append(
                f"text decoded as {encoding!r} after utf-8 failed; if the source is not "
                "Turkish Windows-1254 the characters may be wrong, so pass an explicit "
                "'encoding' parameter"
            )
        return text
    raise _error(asset, "PARSE_FAILED", "the bytes could not be decoded as text")


def _check_headers(asset: FetchedAsset, header: list[str], warnings: list[str]) -> list[str]:
    """Reject a header row that pandas would otherwise rename behind our back.

    ``pandas`` turns a duplicate column into ``value.1``, and an empty one into
    ``Unnamed: 3``. Both are silent renames of data the user will later refer to by name in a
    mapping, so both are refused here instead.
    """

    if not header:
        raise _error(asset, "PARSE_FAILED", "the table has no header row")
    if len(header) > MAX_COLUMNS:
        raise _error(
            asset, "PARSE_FAILED", f"the table has more than {MAX_COLUMNS} columns"
        )

    cleaned = [str(name).strip() for name in header]
    blank = [index for index, name in enumerate(cleaned) if not name]
    if blank:
        raise _error(
            asset,
            "PARSE_FAILED",
            f"column(s) at position {blank} have a blank name; a mapping cannot refer to "
            "them, so name them in the source instead of letting this layer invent one",
        )
    counts = Counter(cleaned)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        raise _error(
            asset,
            "PARSE_FAILED",
            f"duplicate column name(s) {duplicates}; pandas would rename them silently, so "
            "the file is refused instead",
        )
    return cleaned


def _frame(
    asset: FetchedAsset, header: list[str], rows: list[list[Any]], warnings: list[str]
) -> pd.DataFrame:
    """Build the Bronze frame, keeping every cell as the source's own text."""

    if len(rows) > MAX_ROWS:
        raise _error(asset, "PARSE_FAILED", f"the table has more than {MAX_ROWS} rows")

    width = len(header)
    ragged = 0
    normalized: list[list[str | None]] = []
    for row in rows:
        if len(row) != width:
            ragged += 1
        trimmed: list[str | None] = []
        for index in range(width):
            value = row[index] if index < len(row) else None
            if value is None:
                trimmed.append(None)
                continue
            text = value if isinstance(value, str) else str(value)
            if len(text) > MAX_CELL_CHARS:
                raise _error(
                    asset,
                    "PARSE_FAILED",
                    f"a cell is longer than {MAX_CELL_CHARS} characters",
                )
            # A source NULL stays NULL. An empty string is a value the source wrote, and the
            # two are not the same thing, so they are not merged.
            trimmed.append(text)
        normalized.append(trimmed)

    if ragged:
        warnings.append(
            f"{ragged} row(s) did not have {width} fields; short rows were padded with NULL "
            "and long rows were truncated to the header width"
        )
    if not normalized:
        raise _error(asset, "EMPTY_DATASET", "the table has a header but no data rows")

    # dtype=object throughout: a source NULL must stay None rather than becoming NaN, and a
    # numeric-looking string must stay a string until an explicit mapping converts it.
    frame = pd.DataFrame(normalized, columns=header, dtype=object)
    for position, column in enumerate(header):
        frame[column] = pd.Series(
            [row[position] for row in normalized], dtype=object, index=frame.index
        )
    return frame


# ---------------------------------------------------------------------- CSV/TSV


def _parse_delimited(
    asset: FetchedAsset, content: bytes, parameters: dict[str, Any], warnings: list[str]
) -> pd.DataFrame:
    text = _decode(asset, content, warnings, parameters["encoding"])
    delimiter = parameters.get("delimiter")
    if delimiter is not None:
        if not isinstance(delimiter, str) or len(delimiter) != 1:
            raise _error(asset, "UNSUPPORTED_FORMAT", "'delimiter' must be a single character")
    else:
        delimiter = _sniff_delimiter(asset, text, expected=parameters.get("_default_delimiter"))

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        rows = [row for row in reader]
    except csv.Error as exc:
        raise _error(asset, "PARSE_FAILED", f"the delimited file is malformed: {exc}") from exc
    if not rows:
        raise _error(asset, "EMPTY_DATASET", "the file holds no rows")

    header = _check_headers(asset, rows[0], warnings)
    return _frame(asset, header, rows[1:], warnings)


def _sniff_delimiter(asset: FetchedAsset, text: str, *, expected: str | None) -> str:
    """Compare real CSV parses so delimiters inside quoted fields do not count.

    Header width identifies candidates; ragged data is still preserved with the existing
    source warning. More than one parseable candidate always needs an explicit choice.
    """
    candidates = []
    for candidate in _DELIMITERS:
        try:
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=candidate, strict=True)
            header = next(reader, [])
            if len(header) <= 1:
                continue
            for _ in reader:
                pass
        except csv.Error:
            continue
        candidates.append(candidate)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates and expected is not None:
        return expected
    raise _error(
        asset, "UNSUPPORTED_FORMAT",
        "no unique parse-aware delimiter; pass an explicit 'delimiter'",
    )


# -------------------------------------------------------------------------- JSON


def _parse_json(
    asset: FetchedAsset, content: bytes, parameters: dict[str, Any], warnings: list[str]
) -> pd.DataFrame:
    text = _decode(asset, content, warnings, parameters["encoding"])
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _error(asset, "PARSE_FAILED", f"the file is not valid JSON: {exc.msg}") from exc

    records_field = parameters.get("records_field")
    if isinstance(document, list):
        if records_field is not None:
            raise _error(
                asset,
                "UNSUPPORTED_FORMAT",
                f"'records_field' was given as {records_field!r} but the document is already "
                "a list of records",
            )
        records = document
        chosen = None
    elif isinstance(document, dict):
        records, chosen = _select_records(asset, document, records_field)
    else:
        raise _error(
            asset, "UNSUPPORTED_FORMAT", "the JSON root must be a list or an object"
        )

    if not records:
        raise _error(asset, "EMPTY_DATASET", "the selected records array is empty")

    header: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise _error(
                asset, "UNSUPPORTED_FORMAT", f"record {index} is not a JSON object"
            )
        for key in record:
            if key not in header:
                header.append(str(key))

    # Every record must describe the same thing. A heterogeneous array is usually two
    # different tables in one file, and flattening it would invent a shape the source never
    # published.
    for index, record in enumerate(records):
        missing = [name for name in header if name not in record]
        if missing:
            raise _error(
                asset,
                "UNSUPPORTED_FORMAT",
                f"record {index} is missing field(s) {missing}; the records are not "
                "homogeneous, so no single table describes them",
            )

    rows: list[list[Any]] = []
    for index, record in enumerate(records):
        row: list[Any] = []
        for name in header:
            value = record[name]
            if isinstance(value, (dict, list)):
                raise _error(
                    asset,
                    "UNSUPPORTED_FORMAT",
                    f"field {name!r} in record {index} is nested; this layer does not flatten "
                    "nested JSON, because the flattened column names would be invented here "
                    "rather than published by the source",
                )
            row.append(None if value is None else _scalar_text(value))
        rows.append(row)

    if chosen is not None:
        warnings.append(f"records were read from the {chosen!r} field")
    header = _check_headers(asset, header, warnings)
    return _frame(asset, header, rows, warnings)


def _select_records(
    asset: FetchedAsset, document: dict[str, Any], records_field: Any
) -> tuple[list[Any], str | None]:
    if records_field is not None:
        if not isinstance(records_field, str):
            raise _error(asset, "UNSUPPORTED_FORMAT", "'records_field' must be a string")
        if records_field not in document:
            raise _error(
                asset,
                "UNSUPPORTED_FORMAT",
                f"'records_field' {records_field!r} is not present in the document",
            )
        value = document[records_field]
        if not isinstance(value, list):
            raise _error(
                asset,
                "UNSUPPORTED_FORMAT",
                f"field {records_field!r} is not an array of records",
            )
        return value, records_field

    candidates = [
        name
        for name, value in document.items()
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value)
    ]
    if len(candidates) == 1:
        return document[candidates[0]], candidates[0]
    if not candidates:
        raise _error(
            asset,
            "UNSUPPORTED_FORMAT",
            "the object holds no array of records; pass 'records_field' to name one",
        )
    raise _error(
        asset,
        "UNSUPPORTED_FORMAT",
        f"the object holds several candidate record arrays {sorted(candidates)}; pass "
        "'records_field' to choose one",
    )


def _scalar_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# -------------------------------------------------------------------------- XLSX


def _parse_xlsx(
    asset: FetchedAsset, content: bytes, parameters: dict[str, Any], warnings: list[str]
) -> pd.DataFrame:
    import openpyxl

    _assert_not_a_zip_bomb(asset, content)

    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(content),
            read_only=True,
            # Inspect inert formula cells; cached values may be missing or stale.
            data_only=False,
            keep_links=False,
        )
    except zipfile.BadZipFile as exc:
        raise _error(asset, "PARSE_FAILED", "the workbook is not a readable xlsx") from exc
    except Exception as exc:  # noqa: BLE001 - openpyxl raises a wide family
        raise _error(asset, "PARSE_FAILED", f"the workbook could not be opened: {exc}") from exc

    try:
        # Reject formulas throughout the workbook, including hidden/unselected sheets and
        # headers. openpyxl never evaluates them and keep_links=False follows no links.
        for candidate in workbook.worksheets:
            if (candidate.max_column or 0) > MAX_COLUMNS or (candidate.max_row or 0) > MAX_ROWS + 1:
                raise _error(asset, "PARSE_FAILED", "workbook sheet exceeds row/column limits")
            for row_number, row in enumerate(candidate.iter_rows()):
                if row_number > MAX_ROWS or len(row) > MAX_COLUMNS:
                    raise _error(asset, "PARSE_FAILED", "workbook sheet exceeds row/column limits")
                if any(cell.data_type == "f" for cell in row):
                    raise _error(
                        asset, "UNSUPPORTED_FORMAT",
                        "workbook contains a formula; calculate it in your spreadsheet app "
                        "and export a values-only XLSX or CSV before ingestion",
                    )
        visible = [
            name
            for name in workbook.sheetnames
            if workbook[name].sheet_state == "visible"
        ]
        hidden = [name for name in workbook.sheetnames if name not in visible]
        requested = parameters.get("sheet_name")

        if requested is not None:
            if not isinstance(requested, str):
                raise _error(asset, "UNSUPPORTED_FORMAT", "'sheet_name' must be a string")
            if requested not in workbook.sheetnames:
                raise _error(
                    asset,
                    "UNSUPPORTED_FORMAT",
                    f"sheet {requested!r} is not in the workbook; it holds "
                    f"{workbook.sheetnames}",
                )
            if requested in hidden:
                # Allowed, but never silently: a hidden sheet is usually working notes.
                warnings.append(f"sheet {requested!r} is hidden in the workbook")
            sheet_name = requested
        elif len(visible) == 1:
            sheet_name = visible[0]
            if hidden:
                warnings.append(
                    f"the workbook also holds hidden sheet(s) {hidden}, which were ignored"
                )
        elif not visible:
            raise _error(
                asset,
                "UNSUPPORTED_FORMAT",
                f"the workbook has no visible sheet; pass 'sheet_name' to choose one of "
                f"{workbook.sheetnames}",
            )
        else:
            raise _error(
                asset,
                "UNSUPPORTED_FORMAT",
                f"the workbook holds {len(visible)} visible sheets {visible}; pass "
                "'sheet_name' to choose one rather than letting this layer pick",
            )

        if len(workbook.sheetnames) > 1 and requested is None:
            warnings.append(
                f"sheet {sheet_name!r} was the only visible sheet in the workbook and was used"
            )

        sheet = workbook[sheet_name]
        rows_iter = sheet.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            raise _error(asset, "EMPTY_DATASET", f"sheet {sheet_name!r} is empty") from None

        header = _check_headers(
            asset, ["" if cell is None else str(cell) for cell in header_row], warnings
        )
        rows: list[list[Any]] = []
        for row in rows_iter:
            if len(rows) >= MAX_ROWS:
                raise _error(asset, "PARSE_FAILED", f"sheet holds more than {MAX_ROWS} rows")
            if all(cell is None for cell in row):
                continue
            rows.append([None if cell is None else _cell_text(cell) for cell in row])
    finally:
        workbook.close()

    return _frame(asset, header, rows, warnings)


def _assert_not_a_zip_bomb(asset: FetchedAsset, content: bytes) -> None:
    """Read the zip directory and refuse a workbook that expands beyond the ceiling."""

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            total = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise _error(asset, "PARSE_FAILED", "the workbook is not a readable xlsx") from exc
    if total > MAX_UNCOMPRESSED_BYTES:
        raise _error(
            asset,
            "PARSE_FAILED",
            f"the workbook expands to {total} bytes, over the "
            f"{MAX_UNCOMPRESSED_BYTES} byte ceiling",
        )


def _cell_text(value: Any) -> str:
    """Render a cell as the text the source shows, without inventing a format.

    Dates are the one case worth care: openpyxl hands back a ``datetime`` for a date-formatted
    cell, and rendering it in ISO form is the only choice that cannot be misread. Everything
    else is stringified as-is; the mapping decides what it means.
    """

    from datetime import date, datetime, time

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0, 0) else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# -------------------------------------------------------------------------- HTML


def _parse_html(
    asset: FetchedAsset, content: bytes, parameters: dict[str, Any], warnings: list[str]
) -> pd.DataFrame:
    text = _decode(asset, content, warnings, parameters["encoding"])
    try:
        tables = [table for table in extract_tables(text) if table]
    except HtmlTableError as exc:
        raise _error(asset, "PARSE_FAILED", str(exc)) from exc

    if not tables:
        raise _error(asset, "EMPTY_DATASET", "the document holds no non-empty table")

    index = parameters.get("table_index")
    if index is not None:
        if isinstance(index, bool) or not isinstance(index, int):
            raise _error(asset, "UNSUPPORTED_FORMAT", "'table_index' must be an integer")
        if not 0 <= index < len(tables):
            raise _error(
                asset,
                "UNSUPPORTED_FORMAT",
                f"'table_index' {index} is out of range; the document holds "
                f"{len(tables)} non-empty tables",
            )
    elif len(tables) == 1:
        index = 0
    else:
        raise _error(
            asset,
            "UNSUPPORTED_FORMAT",
            f"the document holds {len(tables)} non-empty tables; pass 'table_index' to "
            "choose one rather than letting this layer take the first",
        )

    grid = tables[index]
    if len(grid) < 2:
        raise _error(
            asset, "EMPTY_DATASET", f"table {index} has a header but no data rows"
        )
    header = _check_headers(asset, grid[0], warnings)
    return _frame(asset, header, grid[1:], warnings)


# ------------------------------------------------------------------------ parser


_PARSERS = {
    CSV: _parse_delimited,
    TSV: _parse_delimited,
    JSON: _parse_json,
    XLSX: _parse_xlsx,
    HTML: _parse_html,
}


class GenericTabularParser:
    """Parse a stored ad-hoc artifact into a source-faithful Bronze frame.

    The format comes from the artifact's own metadata, which the connector resolved from the
    bytes -- not from anything the caller says at parse time. That makes a parse deterministic:
    the same artifact always parses the same way.

    All selection and encoding choices come exclusively from canonical artifact metadata.
    Supply them in FetchSpec.parameters before fetching; there is no parse-time override.
    """

    def __init__(
        self,
        *,
        schema_version: str = GENERIC_SCHEMA_VERSION,
    ) -> None:
        self._schema_version = schema_version

    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        resolved = asset.metadata.get("resolved_format")
        if resolved not in _PARSERS:
            raise _error(
                asset,
                "UNSUPPORTED_FORMAT",
                f"artifact metadata carries no supported 'resolved_format' (got "
                f"{resolved!r}); the generic connector records it when the bytes are stored",
            )

        try:
            content = asset.raw_path.read_bytes()
        except OSError as exc:
            raise _error(
                asset, "PARSE_FAILED", f"the RAW artifact could not be read: {asset.raw_path}"
            ) from exc

        if hashlib.sha256(content).hexdigest() != asset.artifact_sha256:
            raise _error(asset, "PARSE_FAILED", "RAW bytes do not match artifact SHA")
        try:
            parameters = config_from_metadata(asset.metadata)
        except FormatError as exc:
            raise _error(asset, "UNSUPPORTED_FORMAT", str(exc)) from exc
        if resolved == TSV:
            parameters.setdefault("_default_delimiter", "\t")

        warnings: list[str] = []
        frame = _PARSERS[resolved](asset, content, parameters, warnings)

        return ParsedBatch(
            source_id=asset.source_id,
            dataset_id=asset.dataset_id,
            artifact_sha256=asset.artifact_sha256,
            schema_version=self._schema_version,
            dataframe=frame,
            warnings=warnings,
            parser_config_sha256=asset.metadata["parser_config_sha256"],
        )


__all__ = [
    "GENERIC_SCHEMA_VERSION",
    "MAX_CELL_CHARS",
    "MAX_COLUMNS",
    "MAX_ROWS",
    "MAX_UNCOMPRESSED_BYTES",
    "GenericTabularParser",
]
