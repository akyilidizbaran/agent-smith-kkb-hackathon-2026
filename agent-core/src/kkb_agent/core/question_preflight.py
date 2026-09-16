"""Soru ön-koşulu — soru, katalog ve kayıtlı araçlarla cevaplanabilir mi? (V3 §3.9; Büşra, 15 Eyl)

Model araç çağırmadan önce, deterministik: sorunun istediği ölçüm katalogda var mı, istenen kırılım
(il, banka grubu…) var mı, istenen frekans katalogdan ince mi, tahmin/öngörü istendi ama tahmin aracı
yok mu, soru bir öncül (yön) varsayıyor mu. Bulgular tek satır olarak modele gider ("ÖN-KOŞUL: …");
model cevabın ilk cümlesinde bunu söyler. Hiçbir şey engellenmez, soru düşmez.

Ölçüldü (14 Eyl UEB, çevrimdışı G3): A04–A08/A10/A11/A13/A14/A17/A19/A21/A22 vakalarında doğru bayrak,
D kontrollerinde 0. A17 (yetki dışı SQL tahmini, iki koşuda sessiz) ve A09/A10 (yanlış öncül, modele
bağlı) bu satırın hedefi. Kavramlar `config_data/concepts.json`'dan (+ katalog alias'ları); kırılım
istekleri aynı dosyanın `dimension_requests` bölümünden — kodda alan adı yok.

Bu, Baran'ın `kkb_agent/preflight.py`'si (ortam ön kontrolü: DB/CLI/anahtar) DEĞİLDİR; o kurulum
zamanında koşar, bu her soruda.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .fitness import DEFAULT_CONCEPTS_PATH, Lexicon, _GRAN_RANK, _GRAN_WORDS, _match, toks

_FORECAST = re.compile(r"tahmin|öngörü|ongoru|projeksiyon|forecast|gelecek yıl|önümüzdeki|olacak mı|ne olur", re.I)
#: Öncül kalıbı: "X düştüğü için / arttığı için / neden arttı" — soru bir yön varsayıyor.
_PREMISE_RE = re.compile(r"(düştüğü|azaldığı|arttığı|yükseldiği|gerilediği)\s+(için|halde|hâlde)|"
                         r"(düştüğü|azaldığı|arttığı|yükseldiği)ne göre|neden\s+(arttı|azaldı|geriledi|düştü|yükseldi)|"
                         r"(düşüş|artış|gerileme|yükseliş)ün(ün|ü)?\s+(nedeni|sebebi)", re.I)
#: "X düştüğü halde Y artmadığı dönemler olmuş mu?" bir yön VARSAYMAZ; koşulu sağlayan dönemi arar (K02 A06 bulgusu, 15 Eyl:
#: PR #4 entegrasyonunda bu soru check_premise'e zorlanıyordu). "halde" kalıbı dönem/zaman araması içindeyse öncül sayılmaz;
#: "düştüğü için" ve "neden arttı" öncül kalır.
_CONDITIONAL_SEARCH = re.compile(r"(dönem|aylar|yıllar|haftalar|zaman|tarih)\w*\s+(ol(?:muş|du|mış)|var)\s*m[ıiuü]|"
                                 r"hangi\s+(dönem|ay|yıl|hafta|tarih)|ne\s+zaman", re.I)


class _PremisePattern:
    """`re.Pattern` gibi kullanılır (agent ve tool_gate `.search` çağırır); koşullu dönem aramasını öncül saymaz."""

    pattern = _PREMISE_RE.pattern

    def finditer(self, text: str):
        for m in _PREMISE_RE.finditer(text or ""):
            if (m.group(2) or "").casefold() in ("halde", "hâlde") and _CONDITIONAL_SEARCH.search(text or ""):
                continue
            yield m

    def search(self, text: str):
        return next(self.finditer(text), None)


_PREMISE = _PremisePattern()
_FREQ_VALUE = {"daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3, "yearly": 4}
#: "kaç puan arttı" — yüzde puanı yalnız oran/yüzde/endeks serileri için tanımlıdır; bir tutar/bakiye için sorulursa model
#: ya tutar farkı verip "puan"a hiç değinmiyor ya da keyfi yorumluyor (UEB A08: üç koşuda 2 SAFE / 1 SILENT, modele bağlı).
_POINT_ASK = re.compile(r"\bpuan\b", re.I)
_RATE_WORD = re.compile(r"oran|faiz|yüzde|yuzde|\brate\b|endeks|index|pay[ıi]\b", re.I)


@dataclass(frozen=True)
class DimensionRequest:
    id: str
    triggers: frozenset[str]        # soruda geçince bu kırılım istenmiş sayılır
    catalog_roots: frozenset[str]   # katalog kolon adı/alias'ında bu köklerden biri varsa kırılım var


@lru_cache(maxsize=4)
def _dimension_requests(path: str) -> tuple[DimensionRequest, ...]:
    p = Path(path)
    if not p.is_file():
        return ()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    out = []
    for did, spec in (data.get("dimension_requests") or {}).items():
        out.append(DimensionRequest(str(did), frozenset(str(t).casefold() for t in spec.get("triggers") or ()),
                                    frozenset(str(t).casefold() for t in spec.get("catalog_roots") or ())))
    return tuple(out)


def dimension_requests() -> tuple[DimensionRequest, ...]:
    return _dimension_requests(os.getenv("CONCEPTS_FILE") or str(DEFAULT_CONCEPTS_PATH))


@dataclass(frozen=True)
class CatalogFacts:
    """Katalogdan ön-koşul için gereken kadarı; adaptör tipine bağımlılık yok."""

    text: str                              # ad + açıklama + kolon adları + alias'lar (kavram eşlemesi için)
    dimension_text: str                    # yalnız kırılım kolon adları + alias'ları
    frequencies: frozenset[str]

    @classmethod
    def from_specs(cls, specs: Iterable[object]) -> "CatalogFacts":
        parts: list[str] = []
        dims: list[str] = []
        freqs: set[str] = set()
        for s in specs:
            parts += [str(getattr(s, "name", "")), str(getattr(s, "dataset_id", "")).replace("_", " ").replace(":", " ")]
            f = getattr(s, "frequency", None)
            if f is not None:
                freqs.add(str(getattr(f, "value", f)))
            for c in getattr(s, "columns", ()) or ():
                cname = str(getattr(c, "name", "")).replace("_", " ")
                aliases = " ".join(getattr(c, "aliases", ()) or ())
                parts += [cname, aliases]
                role = str(getattr(getattr(c, "role", None), "value", getattr(c, "role", "")) or "")
                if role == "dimension":
                    dims += [cname, aliases, " ".join(getattr(c, "example_values", ()) or ())]
        return cls(" ".join(parts), " ".join(dims), frozenset(freqs))


@dataclass(frozen=True)
class PreflightReport:
    flags: tuple[str, ...]
    premise: bool = False

    def note(self) -> str:
        if not self.flags:
            return ""
        return "ÖN-KOŞUL (deterministik, araç çağrılmadan): " + " | ".join(self.flags)


def preflight(question: str, catalog: CatalogFacts | None, *, tools: Iterable[str] = (), has_table: bool = False,
              lexicon: Lexicon | None = None) -> PreflightReport:
    q = question or ""
    lex = lexicon if lexicon is not None else Lexicon.load()
    flags: list[str] = []
    tool_names = set(tools)

    if catalog is not None and not has_table:
        ct = toks(catalog.text)
        need = sorted(c for c in lex.required(q)
                      if lex.concepts[c].measure and lex.concepts[c].strict and not _match(ct, lex.concepts[c].roots))
        if need:
            flags.append(f"katalogda olmayan ölçüm istendi: {', '.join(need)} — bu ölçüm için sayı üretilemez; kullanıcıya söyle")
        dt = toks(catalog.dimension_text)
        qt = toks(q)
        for d in dimension_requests():
            if _match(qt, d.triggers) and not _match(dt, d.catalog_roots):
                flags.append(f"'{d.id}' kırılımı istendi; katalogda bu kırılım yok — toplam/ülke geneli verilecekse bunu söyle")
        asked = next((g for g, pat in _GRAN_WORDS if pat.search(q)), None)
        if asked and catalog.frequencies:
            finest = min((_FREQ_VALUE.get(f, 9) for f in catalog.frequencies), default=9)
            if _GRAN_RANK[asked] < finest:
                flags.append(f"{asked} frekans istendi; katalogdaki en ince frekans daha kaba — ince frekans üretilemez")
    if _FORECAST.search(q) and not (tool_names & {"forecast", "forecast_series"}):
        flags.append("tahmin/öngörü istendi; tahmin aracı yok — SQL/aritmetikle projeksiyon YAPMA, geçmiş veriyi ver ve tahmin üretmediğini söyle")
    if _POINT_ASK.search(q) and not _RATE_WORD.search(q):
        flags.append("'puan' (yüzde puanı) yalnız oran/yüzde serileri için tanımlı; soru bir tutar için puan istiyor — "
                     "yüzde değişimi ve tutar farkını ver, 'puan' olarak ifade edilemeyeceğini ilk cümlede söyle")
    premise = bool(_PREMISE.search(q))
    if premise:
        how = "check_premise aracıyla" if "check_premise" in tool_names else "veriden"
        flags.append(f"soru bir yön varsayıyor (öncül); cevap yazmadan önce o yönü {how} doğrula, çelişiyorsa cevabın ilk cümlesi bu olsun")
    return PreflightReport(tuple(flags), premise=premise)


__all__ = ["CatalogFacts", "DimensionRequest", "PreflightReport", "dimension_requests", "preflight"]
