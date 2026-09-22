"""Deterministic, model-free summary for a verified workspace table.

The summary is a safe final fallback when narration is unavailable. It reports
only facts computed directly from the active DataFrame and never infers causes.
"""

from __future__ import annotations

import re

import pandas as pd

_DATE_NAME = re.compile(
    r"(?:^|[_\s])(?:date|tarih|dönem|donem|period|time|zaman|year|yıl|yil|ay)(?:$|[_\s])|"
    r"^(?:date|tarih|dönem|donem|period|time|zaman|year|yıl|yil|ay)$",
    re.IGNORECASE,
)
_MAX_DISPLAY_COLUMNS = 12
_MAX_NUMERIC_RANGES = 6


def _display_name(value: object) -> str:
    return str(value).replace("`", "'").replace("\n", " ").replace("\r", " ")[:80]


def _number(value: object) -> str:
    number = float(value)
    if number.is_integer():
        rendered = f"{int(number):,}"
    else:
        rendered = f"{number:,.4f}".rstrip("0").rstrip(".")
    return rendered.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _count(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _date_values(series: pd.Series, name: object) -> pd.Series | None:
    if pd.api.types.is_datetime64_any_dtype(series):
        parsed = pd.to_datetime(series, errors="coerce", utc=True)
    elif _DATE_NAME.search(str(name)) and not pd.api.types.is_numeric_dtype(series):
        parsed = pd.to_datetime(series, errors="coerce", utc=True)
        nonempty = int(series.notna().sum())
        if nonempty and int(parsed.notna().sum()) / nonempty < 0.8:
            return None
    else:
        return None
    return parsed.dropna() if parsed.notna().any() else None


def deterministic_table_summary(frame: pd.DataFrame) -> str:
    """Return a compact factual summary without calling an LLM.

    The active table remains unchanged. Numeric ranges use existing cell values;
    the function deliberately omits averages, causal claims, and forecasts.
    """
    if frame.empty:
        return "Yerel otomatik özet: tablo boş."

    rows, column_count = len(frame), len(frame.columns)
    shown_columns = list(frame.columns[:_MAX_DISPLAY_COLUMNS])
    parts = [
        "Yerel otomatik veri özeti (LLM yorumu değildir):",
        f"- Boyut: {_count(rows)} satır, {_count(column_count)} sütun.",
    ]

    date_columns = [
        (column, parsed)
        for column in frame.columns
        if (parsed := _date_values(frame[column], column)) is not None
    ]
    column_descriptions = []
    for column in shown_columns:
        values = frame[column]
        if any(column == date_column for date_column, _ in date_columns):
            kind = "tarih"
        elif pd.api.types.is_numeric_dtype(values) and not pd.api.types.is_bool_dtype(values):
            kind = "sayısal"
        elif pd.api.types.is_bool_dtype(values):
            kind = "mantıksal"
        else:
            kind = "metin/kategori"
        column_descriptions.append(f"`{_display_name(column)}` ({kind})")
    omitted_columns = column_count - len(shown_columns)
    if omitted_columns:
        column_descriptions.append(f"ve {omitted_columns} sütun daha")
    parts.append("- Sütunlar: " + ", ".join(column_descriptions) + ".")

    if date_columns:
        column, values = date_columns[0]
        start = values.min().date().isoformat()
        end = values.max().date().isoformat()
        parts.append(f"- Tarih kapsamı (`{_display_name(column)}`): {start} – {end}.")

    missing_columns = [_display_name(column) for column in frame.columns if frame[column].isna().any()]
    if missing_columns:
        shown_missing = missing_columns[:_MAX_DISPLAY_COLUMNS]
        suffix = " ve diğer sütunlarda" if len(missing_columns) > len(shown_missing) else ""
        parts.append("- Eksik değer bulunan sütunlar: " + ", ".join(f"`{name}`" for name in shown_missing) + suffix + ".")
    else:
        parts.append("- Eksik değer görünmüyor.")

    numeric_columns = [
        column for column in frame.columns
        if pd.api.types.is_numeric_dtype(frame[column])
        and not pd.api.types.is_bool_dtype(frame[column])
        and not any(column == date_column for date_column, _ in date_columns)
    ]
    ranges = []
    for column in numeric_columns[:_MAX_NUMERIC_RANGES]:
        values = frame[column].dropna()
        if values.empty:
            continue
        low, high = values.min(), values.max()
        ranges.append(f"`{_display_name(column)}`: {_number(low)} – {_number(high)}")
    if ranges:
        parts.append("- Sayısal sütun aralıkları (tablodaki en küçük–en büyük değer): " + "; ".join(ranges) + ".")
    omitted_ranges = len(numeric_columns) - _MAX_NUMERIC_RANGES
    if omitted_ranges > 0:
        parts.append(f"- Özet dışında bırakılan sayısal sütun: {omitted_ranges}.")

    parts.append("Bu özet tanımlayıcıdır; tek başına neden-sonuç veya tahmin göstermez.")
    return "\n".join(parts)


__all__ = ["deterministic_table_summary"]
