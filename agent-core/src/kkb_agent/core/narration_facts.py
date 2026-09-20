"""Compact, deterministic evidence projection for final model narration.

The full table remains in the workspace and UI artifact. This module exposes
only metadata and values that can be checked directly against that table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd

from .table_summary import _count, _date_values, _display_name, _number


@dataclass(frozen=True)
class NarrationFacts:
    """Small fact packet used by narration and deterministic outage fallback."""

    text: str
    row_count: int
    column_count: int
    source_names: tuple[str, ...] = ()
    date_column: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    omitted_numeric_columns: int = 0


def build_narration_facts(
    frame: pd.DataFrame,
    *,
    sources: Iterable[str] = (),
    column_labels: Mapping[str, str] | None = None,
    units: Mapping[str, str] | None = None,
    verified_notes: Iterable[str] = (),
    max_numeric_columns: int = 10,
    max_notes: int = 6,
) -> NarrationFacts:
    """Project a verified table to bounded facts without adding assumptions.

    For each numeric column the packet contains missingness, chronological or
    row-order endpoints, and observed minimum/maximum. It does not calculate
    averages, causality, forecasts, or a frequency absent from metadata.
    """
    if frame.empty:
        return NarrationFacts("Doğrulanmış sonuç tablosu boş.", 0, len(frame.columns))

    labels = dict(column_labels or {})
    unit_map = dict(units or {})
    source_names = tuple(dict.fromkeys(str(value).strip() for value in sources if str(value).strip()))
    parts = [
        "DOĞRULANMIŞ ANLATIM OLGULARI (tam tablo arayüz artifact'inde; yalnız aşağıdaki olguları kullan):",
        "Yerel otomatik veri özeti (LLM yorumu değildir):",
        f"- Tablo boyutu: {_count(len(frame))} satır, {_count(len(frame.columns))} sütun.",
    ]
    if source_names:
        parts.append("- Kaynak: " + "; ".join(source_names[:8]) + ".")

    date_columns = [
        (str(column), parsed)
        for column in frame.columns
        if (parsed := _date_values(frame[column], column)) is not None
    ]
    date_column: str | None = None
    parsed_dates: pd.Series | None = None
    if date_columns:
        date_column, parsed_dates = date_columns[0]
        period_start = parsed_dates.min().date().isoformat()
        period_end = parsed_dates.max().date().isoformat()
        parts.append(
            f"- Dönem kolonu: {_display_name(labels.get(date_column, date_column))}; "
            f"kapsam: {period_start}–{period_end}."
        )
    else:
        period_start = period_end = None

    numeric_columns = [
        str(column)
        for column in frame.columns
        if pd.api.types.is_numeric_dtype(frame[column])
        and not pd.api.types.is_bool_dtype(frame[column])
        and column != date_column
    ]
    for column in numeric_columns[:max_numeric_columns]:
        values = frame[column]
        non_null = values.dropna()
        name = _display_name(labels.get(column, column))
        unit = str(unit_map.get(column) or "").strip()
        unit_suffix = f" ({_display_name(unit)})" if unit else ""
        missing = int(values.isna().sum())
        parts.append(
            f"- {name}{unit_suffix}: {_count(len(non_null))} dolu, {_count(missing)} eksik değer."
        )
        if non_null.empty:
            continue

        if parsed_dates is not None:
            aligned = pd.DataFrame({"period": parsed_dates, "value": values}, index=frame.index).dropna()
            aligned = aligned.sort_values("period", kind="stable").reset_index(drop=True)
        else:
            aligned = pd.DataFrame({"period": range(len(frame)), "value": values.to_numpy()}).dropna()
            aligned = aligned.reset_index(drop=True)

        if not aligned.empty:
            first = aligned.iloc[0]
            last = aligned.iloc[-1]
            if parsed_dates is not None:
                first_period = pd.Timestamp(first["period"]).date().isoformat()
                last_period = pd.Timestamp(last["period"]).date().isoformat()
                period_text = f"{first_period}: {_number(first['value'])}; {last_period}: {_number(last['value'])}"
            else:
                period_text = f"ilk: {_number(first['value'])}; son: {_number(last['value'])}"
            low = aligned.loc[aligned["value"].idxmin()]
            high = aligned.loc[aligned["value"].idxmax()]
            if parsed_dates is not None:
                low_period = pd.Timestamp(low["period"]).date().isoformat()
                high_period = pd.Timestamp(high["period"]).date().isoformat()
                extremes = (
                    f"min {_number(low['value'])} ({low_period}); "
                    f"max {_number(high['value'])} ({high_period})"
                )
            else:
                extremes = f"min {_number(low['value'])}; max {_number(high['value'])}"
            parts.append(f"  Gözlenen uçlar: {period_text}; {extremes}.")

    omitted_numeric = max(0, len(numeric_columns) - max_numeric_columns)
    if omitted_numeric:
        parts.append(f"- Olgu paketinde ayrıntılandırılmayan sayısal sütun: {_count(omitted_numeric)}.")

    missing = [(str(column), int(frame[column].isna().sum())) for column in frame.columns if frame[column].isna().any()]
    if missing:
        parts.append("- Eksik değer sayıları: " + "; ".join(
            f"{_display_name(labels.get(column, column))}={_count(count)}" for column, count in missing[:10]
        ) + ".")

    note_values = list(dict.fromkeys(str(note).strip() for note in verified_notes if str(note).strip()))
    for note in note_values[:max_notes]:
        parts.append("- Doğrulanmış araç bulgusu: " + _display_name(note)[:280])
    if len(note_values) > max_notes:
        parts.append(f"- Diğer doğrulanmış araç bulgusu: {_count(len(note_values) - max_notes)} adet.")
    parts.append("Bu olgular betimseldir; kaynakta olmayan açıklama, nedensellik veya tahmin ekleme.")
    return NarrationFacts(
        text="\n".join(parts),
        row_count=len(frame),
        column_count=len(frame.columns),
        source_names=source_names,
        date_column=date_column,
        period_start=period_start,
        period_end=period_end,
        omitted_numeric_columns=omitted_numeric,
    )


__all__ = ["NarrationFacts", "build_narration_facts"]
