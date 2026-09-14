"""Deciding what a downloaded blob actually is, without guessing.

Four signals are available and none of them is trustworthy alone: a server's ``Content-Type``
is often ``application/octet-stream`` or plain wrong, an extension is whatever the uploader
typed, magic bytes only exist for binary containers, and the caller's stated preference is a
hope rather than a fact.

The rule here is that signals may **narrow** the answer but must never be overruled silently.
When two reliable signals disagree the blob is refused with an explicit format mismatch, on
the reasoning that parsing an XLSX as CSV produces a table of mojibake rather than an error,
and a table of mojibake is the worst possible outcome for a data platform.
"""

from __future__ import annotations

import io
import zipfile
from typing import Final


CSV: Final[str] = "csv"
TSV: Final[str] = "tsv"
JSON: Final[str] = "json"
XLSX: Final[str] = "xlsx"
HTML: Final[str] = "html"

SUPPORTED_FORMATS: Final[tuple[str, ...]] = (CSV, TSV, JSON, XLSX, HTML)
"""Tabular formats this version can parse. Anything else is refused, never approximated."""

MEDIA_TYPES: Final[dict[str, str]] = {
    CSV: "text/csv",
    TSV: "text/tab-separated-values",
    JSON: "application/json",
    XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    HTML: "text/html",
}
"""The media type recorded on the artifact for each format, regardless of what a server said."""

_EXTENSIONS: Final[dict[str, str]] = {
    "csv": CSV,
    "tsv": TSV,
    "tab": TSV,
    "json": JSON,
    "xlsx": XLSX,
    "htm": HTML,
    "html": HTML,
}

_CONTENT_TYPES: Final[dict[str, str]] = {
    "text/csv": CSV,
    "application/csv": CSV,
    "text/tab-separated-values": TSV,
    "text/tsv": TSV,
    "application/json": JSON,
    "text/json": JSON,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": XLSX,
    "text/html": HTML,
    "application/xhtml+xml": HTML,
}

_REFUSED_EXTENSIONS: Final[dict[str, str]] = {
    "xls": "the legacy binary .xls format is not supported; convert it to .xlsx",
    "xlsm": "macro-enabled workbooks are refused outright; convert to .xlsx",
    "xlsb": "the binary .xlsb format is not supported; convert it to .xlsx",
    "pdf": "PDF extraction belongs to the agent layer; hand this layer a CSV instead",
    "png": "image extraction belongs to the agent layer; hand this layer a CSV instead",
    "jpg": "image extraction belongs to the agent layer; hand this layer a CSV instead",
    "jpeg": "image extraction belongs to the agent layer; hand this layer a CSV instead",
}
"""Formats refused by name with a reason, so a caller is told what to do rather than that
something failed. Note this is a courtesy, not the security boundary: an unknown extension is
refused too, and signature detection below is what actually decides binary formats."""

_ZIP_MAGIC: Final[bytes] = b"PK\x03\x04"
_OLE_MAGIC: Final[bytes] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_XLSX_MARKERS = {"xl/workbook.xml", "[Content_Types].xml"}


class FormatError(ValueError):
    """Raised when a blob's format cannot be established, or the signals disagree."""


def format_from_extension(name: str) -> str | None:
    """Map a filename or URL path suffix to a format, or None when it says nothing."""

    _, _, suffix = name.rpartition(".")
    return _EXTENSIONS.get(suffix.strip().lower())


def refusal_for_extension(name: str) -> str | None:
    """Return why a known-but-unsupported extension is refused, if it is one."""

    _, _, suffix = name.rpartition(".")
    return _REFUSED_EXTENSIONS.get(suffix.strip().lower())


def format_from_content_type(content_type: str | None) -> str | None:
    """Map a ``Content-Type`` header to a format, ignoring parameters like charset."""

    if not content_type:
        return None
    return _CONTENT_TYPES.get(content_type.split(";")[0].strip().lower())


def format_from_signature(content: bytes) -> str | None:
    """Identify a format from its leading bytes.

    Only binary containers have a signature worth trusting. Text formats deliberately return
    ``None`` here rather than being sniffed: a CSV whose first cell happens to start with
    ``{`` is not JSON, and guessing from content is how a delimiter mistake becomes a silent
    one-column table.
    """

    if content.startswith(_OLE_MAGIC):
        # Legacy .xls / OLE2 compound document.
        return "xls"
    if content.startswith(_ZIP_MAGIC):
        # Every OOXML file is a zip. Look for the workbook part before claiming it is a
        # spreadsheet, so a plain zip is not mistaken for one.
        try:
            # Inspect names only: no extraction, decompression or path traversal.
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise FormatError("duplicate ZIP entry names are refused")
                if any(name.lower().endswith("vbaproject.bin") for name in names):
                    raise FormatError("macro-enabled workbooks are refused; export values to xlsx")
                if _XLSX_MARKERS <= set(names):
                    return XLSX
        except zipfile.BadZipFile as exc:
            raise FormatError("the ZIP directory is not readable") from exc
        return "zip"
    return None


def resolve_format(
    *,
    content: bytes,
    locator_name: str,
    content_type: str | None = None,
    explicit_format: str | None = None,
) -> str:
    """Decide the format, or refuse.

    Precedence and the reasoning behind it:

    1. A **signature** wins when it exists. It is the only signal derived from the bytes
       themselves, so a server mislabelling an XLSX as ``text/csv`` cannot make it one.
    2. An **explicit format** from the caller is honoured next, but is checked against the
       signature first. Asking for CSV when the bytes are an XLSX is a mistake worth surfacing.
    3. ``Content-Type`` and the **extension** are consulted last, and only to name a text
       format. When both are present and disagree, the blob is refused rather than resolved by
       precedence -- one of the two is wrong and this layer cannot tell which.
    """

    if explicit_format is not None:
        explicit_format = explicit_format.strip().lower()
        if explicit_format not in SUPPORTED_FORMATS:
            raise FormatError(
                f"requested format {explicit_format!r} is not supported; expected one of "
                f"{list(SUPPORTED_FORMATS)}"
            )

    signature = format_from_signature(content)
    if signature == "xls":
        raise FormatError(
            "the bytes are a legacy OLE2/.xls workbook, which is not supported; convert it "
            "to .xlsx"
        )
    if signature == "zip":
        raise FormatError(
            "the bytes are a zip archive that does not contain a workbook; this layer does "
            "not unpack archives"
        )
    if signature is not None:
        if explicit_format is not None and explicit_format != signature:
            raise FormatError(
                f"requested format {explicit_format!r} contradicts the file signature, which "
                f"says {signature!r}"
            )
        return signature

    if explicit_format is not None:
        if explicit_format == XLSX:
            raise FormatError(
                "xlsx was requested but the bytes carry no workbook signature"
            )
        return explicit_format

    refusal = refusal_for_extension(locator_name)
    if refusal is not None:
        raise FormatError(refusal)

    by_extension = format_from_extension(locator_name)
    by_content_type = format_from_content_type(content_type)

    if by_extension is not None and by_content_type is not None:
        if by_extension != by_content_type:
            raise FormatError(
                f"format signals disagree: the name says {by_extension!r} and Content-Type "
                f"says {by_content_type!r}. Pass an explicit format to resolve it"
            )
        return by_extension

    resolved = by_extension or by_content_type
    if resolved is None:
        raise FormatError(
            "the format could not be established from the file signature, the name or "
            "Content-Type; pass an explicit format"
        )
    if resolved == XLSX:
        raise FormatError(
            f"{resolved!r} was indicated by name or Content-Type but the bytes carry no "
            "workbook signature"
        )
    return resolved


__all__ = [
    "CSV",
    "HTML",
    "JSON",
    "MEDIA_TYPES",
    "SUPPORTED_FORMATS",
    "TSV",
    "XLSX",
    "FormatError",
    "format_from_content_type",
    "format_from_extension",
    "format_from_signature",
    "refusal_for_extension",
    "resolve_format",
]
