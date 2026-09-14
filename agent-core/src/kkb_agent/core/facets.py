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
    sources: tuple[str, ...] = ()         # kaynak ipuçları
    negatives: tuple[str, ...] = field(default_factory=tuple)

    @property
    def empty(self) -> bool:
        return not (self.provinces or self.frequency or self.sources)


def extract_facets(question: str) -> Facets:
    q = fold(question or "")
    provinces = tuple(dict.fromkeys(_PROVINCE_FOLDED[m.group(1)] for m in _PROVINCE_RE.finditer(q)))
    # "3 aylık mevduat", "1 haftalık repo": sayıyla gelen sözcük vade/pencere, frekans değil (ölçüldü:
    # hibrit koşusunda "mevduat faizi 3 aylık" aylık yüzüne takılıp haftalık seriyi geriye attı).
    freqs = [f for f, words in FREQUENCY_WORDS.items() if any(re.search(rf"(?<!\d)(?<!\d )\b{w}", q) for w in words)]
    frequency = freqs[0] if len(freqs) == 1 else None      # iki frekans sözcüğü: karar yok (guard'la aynı kural)
    sources = tuple(s for s, words in source_words().items() if any(w in q for w in words))
    return Facets(provinces=provinces, frequency=frequency, sources=sources)


def province_of(text: str) -> str | None:
    """Bir seri adı/kimliğinde geçen il (FinTürk: 'Konut Kredisi, İZMİR (…)', 'kaynak:IZMIR_…')."""
    t = fold(text or "")
    m = _PROVINCE_RE.search(t)
    return _PROVINCE_FOLDED[m.group(1)] if m else None


def frequency_rank(freq: str | None) -> int | None:
    return _FREQ_RANK.get(str(freq or "").lower())


__all__ = ["Facets", "PROVINCES", "extract_facets", "frequency_rank", "province_of"]
