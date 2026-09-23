"""Deterministic, user-facing provenance summaries.

Source questions are a poor fit for free-form narration: the model tends to
mix catalog names, derived columns and implementation identifiers into one
paragraph.  This module turns verified workspace metadata into a compact
structured answer.  It never infers a source or a measurement; missing
metadata is simply omitted.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

import pandas as pd

from ..labels import display_column_labels, readable_source, spec_origin
from .table_summary import _date_values


# A provenance question asks where the CURRENT result comes from.  Turkish
# inflects the noun ("kaynağı", "kaynağını", "verinin kaynağı"), so bare
# ``\bkaynak\b`` missed the common phrasings.  Conversely "hangi seriler X'i
# gösteriyor", "hangi kaynaktan X alabiliriz" and "bu artış neye dayanıyor"
# are a catalog search, a new retrieval and an interpretation request; they
# must not be answered from the active table's metadata.
_PAST_OR_PROGRESSIVE = (
    r"(?:geliyor|geldi|gelmiş|gelmis|alındı|alindi|alınıyor|aliniyor|alınmış|alinmis|aldın|aldin|aldınız|aldiniz|"
    r"çekildi|cekildi|çekilmiş|cekilmis|çektin|cektin|çektiniz|cektiniz|buldun|bulundu|elde\s+edildi|üretildi|uretildi)"
)
_SOURCE_INTENT = re.compile(
    r"kayna(?:k|ğı|gi|ğın[ıi]?|gin[ıi]?|kları|klari|kların[ıi]?|klarin[ıi]?)\s+(?:tam\s+olarak\s+)?"
    r"(?:ne\b|nedir|neresi|hangisi|hangileri|kim\b|hangi\s+kurum)"
    r"|kayna(?:ğı|gi|ğını|gini|kları|klari|klarını|klarini)\s+(?:söyle|soyle|göster|goster|belirt|açıkla|acikla|yaz)"
    r"|\b(?:bu|şu|su|o)\b[^?.!]{0,40}?kayna[kğg]"
    r"|(?:veri|tablo|sonuç|sonuc|seri|rakam|sayı|sayi|grafik|cevap|cevab|bilgi)\w*\s+kayna[kğg]"
    r"|nereden\s+" + _PAST_OR_PROGRESSIVE +
    r"|hangi\s+kaynak(?:tan|lardan)\s+" + _PAST_OR_PROGRESSIVE +
    r"|dayandığı\s+(?:seri|kaynak|veri)|dayandigi\s+(?:seri|kaynak|veri)"
    r"|(?:hangi|ne)\s+seri\w*\s+(?:dayan|kullan)\w*"
    # "provenance" alone is usually a constraint ("provenance kolonlarını katma", "provenance ile yaz"),
    # not a request for the source; only an explicit question about it counts.
    r"|\b(?:what|which)\s+(?:is\s+the\s+)?provenance\b|\bprovenance\s+(?:nedir|ne\b|of\s+(?:this|the))"
    r"|\bwhat\s+(?:is\s+the\s+)?source\b|\bsource\s+of\s+(?:this|the|these)\b"
    r"|\bwhere\s+(?:did|does|do)\s+(?:this|these|the)?\s*(?:data|numbers?|figures?)\s+come\s+from"
    r"|\bwhich\s+series\s+(?:is|are)\s+(?:this|it|these)\s+based\s+on",
    re.IGNORECASE,
)
# Asking for something NEW (fetch, find, compare, another source, "can we ...")
# is a retrieval request even when it mentions a source.
_NEW_REQUEST = re.compile(
    r"\b(?:getir|bul|ara|araştır|arastir|indir|çek|cek|listele|yükle|yukle|ekle|karşılaştır|karsilastir)\b"
    r"|\w+(?:abil|ebil)(?:ir|iriz|irim|irsin|ir\s*mi|ecek|ecegim|eceğim)\w*"
    r"|\b(?:başka|baska|farklı|farkli|yeni|alternatif|diğer|diger)\s+(?:bir\s+)?kayna"
    # catalog question ("elimizde hangi veri kaynakları var?"), not this table's provenance
    r"|\belimizde\b|\bhangi\s+(?:veri\s+)?kaynak\w*\s+(?:var|mevcut)",
    re.IGNORECASE,
)

_FREQUENCY_TR = {
    "daily": "günlük",
    "weekly": "haftalık",
    "monthly": "aylık",
    "quarterly": "çeyreklik",
    "yearly": "yıllık",
    "irregular": "düzensiz",
}
_SEMANTIC_TR = {
    "stock": "dönem sonu bakiyesi (stok)",
    "flow": "dönem içi akım",
    "rate": "oran",
    "index": "endeks",
    "ratio": "pay/oran",
    "count": "adet",
}
_UNIT_TR = {
    "TRY_mn": "milyon TL",
    "TRY_thousand": "bin TL",
    "TRY": "TL",
    "USD_mn": "milyon USD",
    "EUR_mn": "milyon EUR",
    "percent": "%",
    "yüzde": "%",
}
_DERIVED_SUFFIXES = (
    ("_pct_change", "yüzde değişim"),
    ("_percent_change", "yüzde değişim"),
    ("_change", "mutlak değişim"),
    ("_growth", "büyüme"),
    ("_difference", "fark"),
)


def is_source_question(question: str) -> bool:
    """Whether a request asks where the current result comes from (not a new search or interpretation)."""
    text = str(question or "").replace("İ", "i")
    return bool(_SOURCE_INTENT.search(text)) and not _NEW_REQUEST.search(text)


def _unit(value: Any) -> str:
    raw = str(value or "").strip()
    return _UNIT_TR.get(raw, raw.replace("_", " ")) if raw else ""


def _friendly_column(column: str, labels: dict[str, str]) -> str:
    if column in labels:
        return labels[column]
    text = str(column).replace("`", "").replace("_", " ").strip()
    for suffix, description in _DERIVED_SUFFIXES:
        if str(column).endswith(suffix):
            base = str(column)[: -len(suffix)].replace("_", " ").strip()
            return f"{base} — {description}" if base else description
    return text


def _derived_description(column: str, provenance: object | None) -> str:
    sql = str(getattr(provenance, "sql", "") or "")
    if not sql.startswith("türetilmiş:"):
        return "hesaplanmış kolon"
    upper = sql.upper()
    if "LAG" in upper and ("/" in sql or "PCT" in upper or "YÜZDE" in upper):
        return "önceki döneme göre yüzde değişim"
    if "LAG" in upper and "-" in sql:
        return "önceki döneme göre mutlak değişim"
    return "hesaplanmış kolon"


def _measure_metadata(specs: list[object]) -> tuple[list[str], list[str], list[str]]:
    units: list[str] = []
    kinds: list[str] = []
    frequencies: list[str] = []
    for spec in specs:
        frequency = getattr(getattr(spec, "frequency", None), "value", getattr(spec, "frequency", None))
        if frequency:
            frequencies.append(_FREQUENCY_TR.get(str(frequency), str(frequency)))
        for column in getattr(spec, "columns", []) or []:
            role = getattr(getattr(column, "role", None), "value", getattr(column, "role", None))
            if role != "measure":
                continue
            if getattr(column, "unit", None):
                units.append(_unit(getattr(column, "unit", None)))
            semantic = getattr(getattr(column, "semantic_type", None), "value", getattr(column, "semantic_type", None))
            if semantic:
                kinds.append(_SEMANTIC_TR.get(str(semantic), str(semantic)))
    return list(dict.fromkeys(frequencies)), list(dict.fromkeys(units)), list(dict.fromkeys(kinds))


def build_source_summary(
    frame: pd.DataFrame,
    *,
    workspace: object | None = None,
    specs: Iterable[object] = (),
) -> str | None:
    """Build a structured provenance answer from verified table metadata.

    ``None`` means there is no usable verified table.  Callers should then
    retain the normal narration/recovery path, especially for web-only turns.
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    specs = list(specs or [])
    labels = display_column_labels(frame, workspace=workspace, specs=specs)
    lines = ["**Veri kaynağı**"]

    origins: list[str] = []
    for spec in specs:
        origin = spec_origin(spec)
        if origin:
            origins.append(origin)
    if workspace is not None and hasattr(workspace, "column_provenance"):
        for column in frame.columns:
            provenance = workspace.column_provenance(str(column))
            for source in getattr(provenance, "sources", []) or []:
                readable = readable_source(str(source))
                if " — " in readable:
                    head, detail = readable.split(" — ", 1)
                    if head.casefold() == detail.casefold():
                        readable = head
                    elif any(head.casefold() == origin.casefold() or (
                        head.casefold().startswith("hesaplanmış tablo")
                        and origin.casefold().startswith("hesaplanmış tablo")
                    ) for origin in origins):
                        # The catalog already provides the human source and
                        # series names; repeating ``source — series`` here
                        # makes the answer look like a raw provenance dump.
                        continue
                if readable:
                    origins.append(readable)
    origins = list(dict.fromkeys(origins))
    if origins:
        lines.append("- **Kaynak:** " + "; ".join(origins) + ".")

    source_urls: list[str] = []
    for spec in specs:
        url = str(getattr(spec, "source_url", "") or "").strip()
        if url:
            source_urls.append(url)
    if workspace is not None and hasattr(workspace, "column_provenance"):
        for column in frame.columns:
            provenance = workspace.column_provenance(str(column))
            source_urls.extend(
                str(url).strip()
                for url in (getattr(provenance, "source_urls", []) or [])
                if str(url).strip()
            )
    source_urls = list(dict.fromkeys(source_urls))
    if source_urls:
        lines.append("- **Kaynak adresi:** " + "; ".join(source_urls[:4]) + ".")

    series = [str(getattr(spec, "name", "") or "").strip() for spec in specs]
    series = list(dict.fromkeys(name for name in series if name))
    if series:
        lines.append("- **Dayandığı seriler:**")
        lines.extend(f"  - {name}" for name in series)

    frequencies, units, kinds = _measure_metadata(specs)
    dates: list[pd.Series] = []
    for column in frame.columns:
        parsed = _date_values(frame[column], column)
        if parsed is not None:
            dates.append(parsed)
    if dates:
        values = dates[0]
        if frequencies and set(frequencies) == {"aylık"}:
            start = values.min().strftime("%Y-%m")
            end = values.max().strftime("%Y-%m")
        else:
            start = values.min().date().isoformat()
            end = values.max().date().isoformat()
        lines.append(f"- **Dönem:** {start} – {end}.")
    if frequencies:
        lines.append("- **Frekans:** " + ", ".join(frequencies) + ".")
    if units:
        lines.append("- **Birim:** " + ", ".join(units) + ".")
    if kinds:
        lines.append("- **Ölçüm türü:** " + ", ".join(kinds) + ".")

    derived: list[tuple[str, str]] = []
    if workspace is not None and hasattr(workspace, "column_provenance"):
        for column in frame.columns:
            provenance = workspace.column_provenance(str(column))
            if str(getattr(provenance, "sql", "") or "").startswith("türetilmiş:"):
                derived.append((
                    _friendly_column(str(column), labels),
                    _derived_description(str(column), provenance),
                ))
    if derived:
        lines.append("- **Hesaplanan kolonlar:**")
        lines.extend(f"  - {name}: {description}." for name, description in dict.fromkeys(derived))

    lines.append(f"- **Kanıt kapsamı:** {len(frame)} satır, {len(frame.columns)} sütun; özet doğrulanmış aktif tablodan üretildi.")
    lines.append("")
    lines.append("Teknik seri kimlikleri ve sorgu izi kanıt panelinde tutulur; kullanıcı tablosunda yalnız okunur adlar gösterilir.")
    return "\n".join(lines)


__all__ = ["build_source_summary", "is_source_question"]
