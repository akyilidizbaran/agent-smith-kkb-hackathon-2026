"""Kullanıcıya dönük metinde iç kimlik ve veri mimarisi adı yok (ADR-0082).

Kanıt zinciri (sağ panel, izlenebilirlik kaydı) katman adlarını ve kimlikleri taşır. Cevap metni, grafik altyazısı ve rapor
"Kaynaklar" listesi kullanıcının diliyle yazılır: kaynak kurumun adı, "hesaplanmış tablo", "kullanıcının eklediği seri".

15 Eyl arayüz denemesi: "Elinde nasıl veriler var" sorusuna model "Hazır Gold tabloları" başlığı açtı; grafik altyazısı
"Kaynak: bddk_monthly — …; gold — …" diye iç etiketlerle yazılıyordu.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from .contracts.catalog import ColumnRole
from .domain import join_tr, series_label
from .source_hints import load_source_hints

GOLD_FUNCTIONS = {
    "align_frequency": "frekans hizalama",
    "decompose_cumulative": "birikimli seriden dönem akımı",
    "join_on_period": "dönem eşlemeli birleştirme",
}
_LAYER_REPLACEMENT = {"gold": "hesaplanmış tablolar", "silver": "kaynak verisi", "bronze": "ham kaynak dosyaları", "raw": "ham kaynak dosyaları"}
_TABLE_FORMS = {  # "Gold tablosunda" → "hesaplanmış tabloda": tamlama eki düşer, hâl eki kalır
    "tablo": "tablo", "tablosu": "tablo", "tablosunda": "tabloda", "tablosundan": "tablodan", "tablosunu": "tabloyu",
    "tablosuna": "tabloya", "tablosunun": "tablonun", "tablolar": "tablolar", "tabloları": "tablolar", "tablolarında": "tablolarda",
    "tablolarından": "tablolardan", "tablolarını": "tabloları", "tablolarına": "tablolara", "tablolarının": "tabloların",
}
_GOLD_TABLE = re.compile(r"(?<![\w.])(?:(hazır)\s+)?gold\s+(tablo\w*)", re.I)
_SILVER_OBS = re.compile(r"(?<![\w.])silver\s+(gözlem\w*)", re.I)
_LAYER = re.compile(r"(?<![\w.])(gold|silver|bronze|raw)\s+katman(ı|ında|ından|ına|ını)?(?![\w])", re.I)
_LAYER_SUFFIX = {  # "Silver katmanından" → "kaynak verisinden"
    "gold": {"": "", "ı": "", "ında": "da", "ından": "dan", "ına": "a", "ını": "ı"},
    "silver": {"": "", "ı": "", "ında": "nde", "ından": "nden", "ına": "ne", "ını": "ni"},
    "bronze": {"": "", "ı": "", "ında": "nda", "ından": "ndan", "ına": "na", "ını": "nı"},
}
_LAYER_SUFFIX["raw"] = _LAYER_SUFFIX["bronze"]
_GOLD_SUFFIX = re.compile(r"(?<![\w.])Gold'?(dan|den|da|de|a|e|ye)(?![\w])")
_GOLD_BARE = re.compile(r"(?<![\w.])Gold(?![\w.'])")
_DISPLAY_DATE_COLUMNS = frozenset({"date", "tarih", "donem", "dönem", "period_end", "observation_date"})
_DISPLAY_VALUE_SUFFIXES = {
    "value": "",
    "cumulative_value": " — birikimli değer",
    "change": " — değişim",
    "pct_change": " — yüzde değişim",
    "growth": " — büyüme",
    "difference": " — fark",
}


def _names() -> dict[str, str]:
    return dict(load_source_hints().get("source_names", {}))


def readable_source(src: str) -> str:
    """Kolon kaynağı etiketi → okunur: 'bddk_monthly — X' → 'BDDK Aylık Bülten — X'; 'gold — join_on_period' → 'hesaplanmış
    tablo — dönem eşlemeli birleştirme'; 'adhoc — acil_basvuru — dosya.csv (taslak)' → 'kullanıcının eklediği seri — acil basvuru'."""
    text = str(src or "")
    m = re.match(r"^\s*([a-z][a-z0-9_]*)\s+—\s+(.*)$", text, re.S)
    if not m:
        return text
    sid, rest = m.group(1), m.group(2).strip()
    if sid == "gold":
        return "hesaplanmış tablo — " + GOLD_FUNCTIONS.get(rest, rest)
    if sid == "adhoc":
        return "kullanıcının eklediği seri — " + re.sub(r"\s+—\s+.*$", "", rest).replace("_", " ")
    display = source_display_name(sid)
    return f"{display} — {rest}" if display != sid else text


def spec_origin(spec: object) -> str:
    """Arama kartı için tablonun kaynağı: kurum adı, 'kullanıcının eklediği seri' ya da 'hesaplanmış tablo (… verisinden)'."""
    source = str(getattr(spec, "source", "") or "")
    if source == "gold":
        ids = re.findall(r"(?<![\w.])([a-z][a-z0-9_]*):[\w.@-]+", str(getattr(spec, "source_detail", "") or ""))
        labels = list(dict.fromkeys("kullanıcının eklediği seri" if i == "adhoc" else source_display_name(i) for i in ids))
        return "hesaplanmış tablo" + (f" ({join_tr(labels)} verisinden)" if labels else "")
    if source == "adhoc":
        return "kullanıcının eklediği seri"
    return source_display_name(source, [spec])


def _cased(original: str, replacement: str, text: str, start: int) -> str:
    """Satır/cümle/madde başındaki büyük harfli ifade büyük harfle değişir; cümle içinde küçük."""
    at_start = start == 0 or re.search(r"(^|[\n.!?:]\s*|\*\*\s*|\d+\.\s+|[-•]\s+)$", text[:start]) is not None
    return replacement[:1].upper() + replacement[1:] if original[:1].isupper() and at_start else replacement


def humanize_internal(text: str, specs: Iterable[object] = ()) -> tuple[str, list[str]]:
    """Son cevaptaki tablo/seri kimliklerini ve mimari katman adlarını kullanıcı diline çevirir; (metin, değişenler)."""
    if not text:
        return text, []
    specs = list(specs or [])
    names = _names()
    by_id = {str(getattr(s, "dataset_id", "")): (s.name if getattr(s, "source", "") == "gold" else series_label(s)) for s in specs}
    prefixes = sorted({*names, "adhoc", *(str(getattr(s, "dataset_id", "")).split(":", 1)[0] for s in specs if ":" in str(getattr(s, "dataset_id", "")))},
                      key=len, reverse=True)
    id_re = re.compile(r"`?(?<![\w.])(gold\.[a-z0-9_]+|(?:" + "|".join(map(re.escape, prefixes)) + r"):[\w.@-]*\w)(?:::\w+)?`?")
    changed: list[str] = []

    def ident(m: re.Match) -> str:
        key = m.group(1)
        changed.append(key)
        if key in by_id:
            return by_id[key]
        if key.startswith("gold."):
            return "hesaplanmış tablo"
        prefix = key.split(":", 1)[0]
        if prefix == "adhoc":
            return "kullanıcının eklediği seri"
        label = names.get(prefix, prefix)
        follows = m.string[m.end():m.end() + 10].lstrip().lower()
        return label if follows.startswith("seri") else f"{label} serisi"   # "evds:X serisi" → "TCMB EVDS serisi", tekrar yok

    out = id_re.sub(ident, text)

    def sub(pattern: re.Pattern, make) -> None:
        nonlocal out
        parts, last = [], 0
        for m in pattern.finditer(out):
            parts.append(out[last:m.start()])
            parts.append(_cased(m.group(0), make(m), out, m.start()))
            changed.append(m.group(0))
            last = m.end()
        if parts:
            parts.append(out[last:])
            out = "".join(parts)

    sub(_GOLD_TABLE, lambda m: "hesaplanmış " + _TABLE_FORMS.get(m.group(2).lower(), "tablo"))
    sub(_SILVER_OBS, lambda m: m.group(1).lower())
    sub(_LAYER, lambda m: _LAYER_REPLACEMENT[m.group(1).lower()] + _LAYER_SUFFIX[m.group(1).lower()][(m.group(2) or "").lower()])
    sub(_GOLD_SUFFIX, lambda m: {"dan": "hesaplanmış tablolardan", "den": "hesaplanmış tablolardan", "da": "hesaplanmış tablolarda",
                                 "de": "hesaplanmış tablolarda"}.get(m.group(1), "hesaplanmış tablolara"))
    sub(_GOLD_BARE, lambda m: "hesaplanmış tablo")
    return out, list(dict.fromkeys(changed))


def _display_unit(unit: object) -> str:
    """Catalog unit code → short user-facing unit, with a safe generic fallback."""
    value = str(unit or "").strip()
    if not value:
        return ""
    known = {
        "TRY_mn": "milyon TL",
        "TRY_thousand": "bin TL",
        "TRY": "TL",
        "USD_mn": "milyon USD",
        "EUR_mn": "milyon EUR",
        "percent": "%",
        "yüzde": "%",
    }
    return known.get(value, value.replace("_", " "))


def _spec_measure_label(spec: object) -> tuple[str, str]:
    """Return a catalog-backed measure label and unit without inventing semantics."""
    measures = [c for c in getattr(spec, "columns", []) or []
                if getattr(getattr(c, "role", None), "value", getattr(c, "role", None)) == "measure"]
    measure = measures[0] if measures else None
    aliases = [str(alias).strip() for alias in (getattr(measure, "aliases", []) or []) if str(alias).strip()]
    raw_name = str(getattr(measure, "name", "") or "")
    label = next((alias for alias in aliases if alias.casefold() != raw_name.casefold()), "")
    label = label or str(getattr(spec, "name", "") or getattr(spec, "dataset_id", ""))
    return label.strip(), _display_unit(getattr(measure, "unit", None))


def display_column_labels(
    frame: Any,
    *,
    workspace: object | None = None,
    specs: Iterable[object] = (),
) -> dict[str, str]:
    """Map technical lakehouse columns to stable human labels for UI/export only.

    The DataFrame and provenance remain untouched. Labels are resolved from the
    catalog and column provenance, so the rule works for any source using the
    shared ``<series>@<entity>::<measure>`` Gold naming contract.
    """
    if frame is None or not hasattr(frame, "columns"):
        return {}
    specs = list(specs or [])
    by_id = {str(getattr(spec, "dataset_id", "")): spec for spec in specs}
    technical_frame = any("::" in str(column) for column in frame.columns)
    labels: dict[str, str] = {}
    used: dict[str, int] = {}
    for column in frame.columns:
        raw = str(column)
        provenance = None
        if workspace is not None and hasattr(workspace, "column_provenance"):
            provenance = workspace.column_provenance(raw)
        ids = [str(value) for value in (getattr(provenance, "dataset_ids", []) or [])]
        prefix, separator, tail = raw.rpartition("::")
        series_id = prefix.split("@", 1)[0] if prefix else ""
        structured = bool(separator and prefix)
        spec = by_id.get(series_id) if structured else None
        if spec is None:
            spec = next((by_id[dataset_id] for dataset_id in ids if dataset_id in by_id), None) if structured else None

        label = ""
        unit = ""
        if spec is not None and (prefix or ids):
            label, unit = _spec_measure_label(spec)
        elif technical_frame and raw.casefold() in _DISPLAY_DATE_COLUMNS:
            label = "Dönem"

        suffix = tail if structured else ""
        display_suffix = suffix.removeprefix("value_")
        if label and display_suffix in _DISPLAY_VALUE_SUFFIXES:
            label += _DISPLAY_VALUE_SUFFIXES[display_suffix]
            if unit:
                label += f" ({unit})"
        elif label and suffix:
            # Preserve an explicitly named derived measure while removing the
            # machine-only separators and series id.
            label += " — " + suffix.replace("_", " ")
        if not label or label == raw:
            continue
        count = used.get(label, 0) + 1
        used[label] = count
        labels[raw] = label if count == 1 else f"{label} ({count})"
    return labels


def rename_frame_columns(frame: Any, labels: Mapping[str, str] | None = None):
    """Return a copy with display labels, keeping names unique and values intact."""
    if frame is None or not hasattr(frame, "columns") or not labels:
        return frame.copy() if hasattr(frame, "copy") else frame
    out = frame.copy()
    out.columns = [str(labels.get(str(column), column)) for column in frame.columns]
    return out


# ---------------------------------------------------------------- kaynak adı ve konu özeti (15 Eyl, kullanıcı kararı)
# "Elimizde hangi veriler var" cevabı içeriği her soruda canlı katalogdan okur. İki sınır kullanıcıyla konuşuldu:
# (1) source_hints.json'da okunur adı olmayan yeni kaynak ham kimlikle görünüyordu ("tuik: 5 seri");
# (2) cevap yalnız kaynak, sayı ve dönem veriyordu, konu başlıkları yoktu. İkisi de ayar dosyası güncellenmeden katalogdan çözülür.

_HOST_NOISE = {"www", "data", "veri", "api", "gov", "org", "com", "net", "edu", "tr"}
_ACRONYM = re.compile(r"(?<![\w])[A-ZÇĞİÖŞÜ0-9]{2,}(?![\w])")


def _fold(text: str) -> str:
    """Harf ve aksan duyarsız anahtar: 'TÜİK' ~ 'tuik', 'İSTANBUL' ~ 'istanbul'."""
    s = unicodedata.normalize("NFKD", str(text or "").replace("ı", "i").replace("I", "i").replace("İ", "i"))
    return "".join(ch for ch in s if not unicodedata.combining(ch)).casefold()


def source_display_name(source_id: str, specs: Iterable[object] = ()) -> str:
    """Kaynağın okunur adı. Sıra: source_hints.source_names → kurum adı (source_hints.institutions; kaynağın adresindeki ya da
    kimliğindeki bir parçayla eşleşen) → adresin alan adı → kimlik. Yeni kaynak için ayar dosyası güncellenmesi gerekmez."""
    sid = str(source_id or "")
    hints = load_source_hints()
    names = hints.get("source_names", {}) or {}
    if sid in names:
        return names[sid]
    urls = [str(getattr(s, "source_url", "") or "") for s in specs if str(getattr(s, "source", "") or "") == sid]
    hosts = [h for h in (urlparse(u).hostname or "" for u in urls if u) if h]
    tokens = [t for h in hosts for t in h.split(".") if t not in _HOST_NOISE] + [t for t in re.split(r"[\W_]+", sid) if t]
    for inst in hints.get("institutions", ()) or ():
        if any(_fold(inst) == _fold(t) for t in tokens):
            return inst
    if hosts:
        return hosts[0].removeprefix("www.")
    return sid


def _entity(name: str) -> str | None:
    """Varlık parçası: 'Konut Kredisi, ADANA (Bireysel Bankacılık, Sektör)' → 'ADANA' (virgülden sonra tamamı büyük harf, ≥3 harf)."""
    parts = [p.strip() for p in re.sub(r"\([^)]*\)", "", name or "").split(",")]
    return next((p for p in parts[1:] if len(p) >= 3 and p == p.upper() and re.search(r"[A-ZÇĞİÖŞÜ]{3,}", p)), None)


def topic_of(spec: object) -> tuple[str, str | None]:
    """(konu, varlık). Konu ölçüm kolonunun ilk takma adıdır (katalogda kısa okunur ad: 'konut kredisi', 'tüfe'); varlık adı
    ('adana ...') atılır, kısaltmalar serinin tam adındaki yazımla döner ('TÜFE', 'M3'). Takma ad yoksa ad sadeleştirilir."""
    name = str(getattr(spec, "name", "") or "")
    entity = _entity(name)
    measure = next((c for c in getattr(spec, "columns", None) or [] if getattr(c, "role", None) == ColumnRole.MEASURE), None)
    alias = next(iter(getattr(measure, "aliases", None) or []), "") if measure is not None else ""
    if alias:
        drop = set(_fold(entity).split()) if entity else set()
        topic = " ".join(w for w in alias.split() if _fold(w) not in drop and not (drop and _fold(w) == "ili"))
    else:
        base = re.sub(r"\([^)]*\)", "", name)
        topic = ", ".join(p.strip() for p in base.split(",") if p.strip() and p.strip() != entity and _fold(p.strip()) != "toplam")
    acronyms = {a.upper(): a for a in _ACRONYM.findall(name)}
    topic = " ".join(acronyms.get(w.upper(), w) for w in topic.split())
    return topic.strip(), entity


def topics_summary(specs: Iterable[object], limit: int = 6) -> str:
    """'81 il × 8 konu: konut kredisi, taşıt kredisi, … ve 2 konu daha' ya da 'konular: politika faizi, dolar kuru, TÜFE, …'."""
    topics: list[str] = []
    seen: set[str] = set()
    entities: set[str] = set()
    entity_is_il = True
    for spec in specs:
        topic, entity = topic_of(spec)
        if entity:
            entities.add(_fold(entity))
            entity_is_il = entity_is_il and "il" in (getattr(spec, "tags", None) or [])
        if topic and _fold(topic) not in seen:
            seen.add(_fold(topic))
            topics.append(topic)
    if not topics:
        return ""
    listed = ", ".join(topics[:limit]) + (f" ve {len(topics) - limit} konu daha" if len(topics) > limit else "")
    if len(entities) > 1:
        return f"{len(entities)} {'il' if entity_is_il else 'varlık'} × {len(topics)} konu: {listed}"
    return ("konu: " if len(topics) == 1 else "konular: ") + listed


__all__ = ["GOLD_FUNCTIONS", "display_column_labels", "humanize_internal", "readable_source", "rename_frame_columns",
           "source_display_name", "spec_origin", "topic_of", "topics_summary"]
