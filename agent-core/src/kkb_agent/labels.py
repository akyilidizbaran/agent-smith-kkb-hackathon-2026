"""Kullanıcıya dönük metinde iç kimlik ve veri mimarisi adı yok (ADR-0082).

Kanıt zinciri (sağ panel, izlenebilirlik kaydı) katman adlarını ve kimlikleri taşır. Cevap metni, grafik altyazısı ve rapor
"Kaynaklar" listesi kullanıcının diliyle yazılır: kaynak kurumun adı, "hesaplanmış tablo", "kullanıcının eklediği seri".

15 Eyl arayüz denemesi: "Elinde nasıl veriler var" sorusuna model "Hazır Gold tabloları" başlığı açtı; grafik altyazısı
"Kaynak: bddk_monthly — …; gold — …" diye iç etiketlerle yazılıyordu.
"""

from __future__ import annotations

import re
from typing import Iterable

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
    names = _names()
    return f"{names[sid]} — {rest}" if sid in names else text


def spec_origin(spec: object) -> str:
    """Arama kartı için tablonun kaynağı: kurum adı, 'kullanıcının eklediği seri' ya da 'hesaplanmış tablo (… verisinden)'."""
    source = str(getattr(spec, "source", "") or "")
    names = _names()
    if source == "gold":
        ids = re.findall(r"(?<![\w.])([a-z][a-z0-9_]*):[\w.@-]+", str(getattr(spec, "source_detail", "") or ""))
        labels = list(dict.fromkeys(names.get(i, "kullanıcının eklediği seri" if i == "adhoc" else i) for i in ids))
        return "hesaplanmış tablo" + (f" ({join_tr(labels)} verisinden)" if labels else "")
    if source == "adhoc":
        return "kullanıcının eklediği seri"
    return names.get(source, source)


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


__all__ = ["GOLD_FUNCTIONS", "humanize_internal", "readable_source", "spec_origin"]
