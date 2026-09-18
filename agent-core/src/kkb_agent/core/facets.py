"""Soru yüzleri (facet): frekans, il, kaynak — sıralama puanı değil, eleme/öncelik kriteri (ADR-0043).

Ölçüldü: 648 ilçe-serisi kataloğa girince "konut kredisi bakiyesi" sorusunda BM25'in ilk 8'i
81 ilin konut serisiyle doldu, ulusal seri geride kaldı; "İzmir taşıt kredisi" sorusunda
Ankara'nın serisi İzmir'inkiyle aynı puanı aldı (sözcükler aynı, il adı tek sözcük). Yüzler
soruda geçiyorsa katalog o yüze göre daraltılır; geçmiyorsa il-ölçekli seriler ulusal
serilerin arkasına alınır. Deterministik, model yok.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .lexical import fold

# 81 il, resmî ad; katlanmış biçimleri eşleşmede kullanılır (İSTANBUL, Istanbul, istanbul).
PROVINCES = (
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Aksaray", "Amasya", "Ankara", "Antalya", "Ardahan",
    "Artvin", "Aydın", "Balıkesir", "Bartın", "Batman", "Bayburt", "Bilecik", "Bingöl", "Bitlis", "Bolu",
    "Burdur", "Bursa", "Çanakkale", "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Düzce", "Edirne", "Elazığ",
    "Erzincan", "Erzurum", "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari", "Hatay", "Iğdır",
    "Isparta", "İstanbul", "İzmir", "Kahramanmaraş", "Karabük", "Karaman", "Kars", "Kastamonu", "Kayseri",
    "Kırıkkale", "Kırklareli", "Kırşehir", "Kilis", "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa",
    "Mardin", "Mersin", "Muğla", "Muş", "Nevşehir", "Niğde", "Ordu", "Osmaniye", "Rize", "Sakarya", "Samsun",
    "Siirt", "Sinop", "Sivas", "Şanlıurfa", "Şırnak", "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Uşak", "Van",
    "Yalova", "Yozgat", "Zonguldak",
)
_PROVINCE_FOLDED = {fold(p): p for p in PROVINCES}
# Türkçe ekler: "İzmir'de", "İzmir'in", "Ankara'daki" → kök il adı; kesme işareti olsun olmasın.
_PROVINCE_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(fold(p)) for p in PROVINCES), key=len, reverse=True)) + r")(?:'?(?:d[ae]ki|d[ae]|nin|nın|in|ın|de|da|ye|ya|e|a)?)\b"
)

FREQUENCY_WORDS = {
    "daily": ("gunluk", "gunlukk"), "weekly": ("haftalik",), "monthly": ("aylik",),
    "quarterly": ("ceyreklik", "uc aylik", "ceyrek"), "yearly": ("yillik",),
}
_FREQ_RANK = {"daily": 0, "business_daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3, "yearly": 4}
def source_words() -> dict[str, tuple[str, ...]]:
    """Kaynak yüzü sözcükleri yapılandırmadan (M03-T04): kaynak adı çekirdek kodda yazılı değil."""
    from ..source_hints import load_source_hints
    return load_source_hints()["source_words"]


@dataclass(frozen=True)
class Facets:
    provinces: tuple[str, ...] = ()       # resmî ad(lar), soruda geçtiği gibi
    frequency: str | None = None          # tek frekans sözcüğü geçiyorsa
    window_frequency: str | None = None   # "60 aylık dönem": pencere granülaritesi
    sources: tuple[str, ...] = ()         # kaynak ipuçları
    negatives: tuple[str, ...] = field(default_factory=tuple)
    national: bool = False                # Türkiye geneli/ülke geneli gibi açık ulusal istek

    @property
    def empty(self) -> bool:
        return not (self.provinces or self.frequency or self.window_frequency or self.sources or self.national)


def extract_facets(question: str) -> Facets:
    q = fold(question or "")
    provinces = tuple(dict.fromkeys(_PROVINCE_FOLDED[m.group(1)] for m in _PROVINCE_RE.finditer(q)))
    # "3 aylık mevduat", "1 haftalık repo": sayıyla gelen sözcük vade/pencere, frekans değil (ölçüldü:
    # hibrit koşusunda "mevduat faizi 3 aylık" aylık yüzüne takılıp haftalık seriyi geriye attı).
    freqs = [f for f, words in FREQUENCY_WORDS.items() if any(re.search(rf"(?<!\d)(?<!\d )\b{w}", q) for w in words)]
    frequency = freqs[0] if len(freqs) == 1 else None      # iki frekans sözcüğü: karar yok (guard'la aynı kural)
    sources = tuple(s for s, words in source_words().items() if any(w in q for w in words))
    # A numeric month window is not a publication-frequency word by itself.
    # When it is explicitly a data period, monthly records are the natural
    # retrieval target. Maturity phrases ("3 aylık mevduat") stay excluded.
    window_frequency = None
    if re.search(r"(?<!\d)\d{1,3}\s*aylik\b", q) and re.search(r"donem|pencere|veri|gozlem|seri|cek|getir", q):
        if not re.search(r"vade|mevduat|repo", q):
            window_frequency = "monthly"
    national = bool(re.search(
        r"\bturkiye(?:['’ ]?(?:deki|geneli|genelindeki))?\b|"
        r"\bulke(?:['’ ]?(?:deki|geneli|genelindeki))?\b|\bulusal\b|\bnational\b",
        q,
    ))
    return Facets(provinces=provinces, frequency=frequency, window_frequency=window_frequency,
                  sources=sources, national=national)


def source_matches(actual: str | None, requested: tuple[str, ...]) -> bool:
    """Match exact sources and configured source families (e.g. ``bddk``)."""
    value = str(actual or "")
    return any(value == source or value.startswith(source + "_") for source in requested)


def province_of(text: str) -> str | None:
    """Bir seri adı/kimliğinde geçen il (FinTürk: 'Konut Kredisi, İZMİR (…)', 'kaynak:IZMIR_…')."""
    t = fold(text or "")
    m = _PROVINCE_RE.search(t)
    return _PROVINCE_FOLDED[m.group(1)] if m else None


def frequency_rank(freq: str | None) -> int | None:
    return _FREQ_RANK.get(str(freq or "").lower())


__all__ = ["Facets", "PROVINCES", "extract_facets", "frequency_rank", "province_of", "source_matches"]
