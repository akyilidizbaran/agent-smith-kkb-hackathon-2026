"""İlgi kapısı — yüklenen dosya sorulan şeyle ilgili mi? (V3 §3.9, 13 Eylül; Büşra)

Profilci (ADR-0030) dosyanın BİÇİMİNE bakar: tarih kolonu %100 ayrışıyor mu, sayı kolonu
%100 okunuyor mu, birim başlıkta var mı. Dosyanın ANLAMINA bakmaz: konut kredisi sorusuna
otobüs tarifesi yüklenirse, içinde tarih ve sayı olduğu sürece taslak olarak yazılırdı.
Bu modül o boşluğu üç deterministik ölçütle kapatır; LLM yok, ağ yok:

  1. dönem   — soruda yıl geçiyorsa, dosyanın tarih aralığı o yılları kapsıyor mu
  2. terim   — sorunun içerik sözcükleri (durak sözcükler atılmış, kök ≈ ilk 5 harf)
               dosya adında ya da kolon başlıklarında geçiyor mu
  3. katalog — soru bir katalog serisine (ad/alias) işaret ediyorsa, o serinin
               sözcükleri dosyada da geçiyor mu ("enflasyon" ↔ "TÜFE" alias'ıyla)

Uygulanabilen ölçütlerin HİÇBİRİ tutmuyorsa dosya "alakasız" sayılır: yazılmaz,
kullanıcıya sorulur. Bir ölçüt bile tutuyorsa yazılır; puan karta düşer. Ölçüt
uygulanamıyorsa (soruda yıl yok, içerik sözcüğü yok) kapı sessiz kalır — "bunu ekle"
demek yeterlidir, kapı bahane üretmez. Kökleme kasıtlı olarak kaba (Türkçe çekim:
kredisi/kredileri/kredi → "kredi"); yanlış pozitif riski kullanıcı onayıyla
(`user_confirmed`) aşılır, sessiz yazmayla değil.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .profile import MappingProposal, parse_date

_YEAR = re.compile(r"\b(20[0-9]{2})\b")
_WORD = re.compile(r"[a-zçğıöşüâîû]+", re.I)
_STEM_LEN = 5

# Durak sözcükler: soruda geçen ama konu taşımayan sözcükler. Yazma niyeti sözcükleri
# (ekle/yükle) ve analiz fiilleri de burada; dosya adında geçmeleri ilgi göstermez.
_STOP = frozenset("""
bu şu o ve veya ile için gibi kadar göre olarak olan olsun mı mi mu mü ne nasıl neden hangi
bunu şunu onu bunun şunun onun bunlar bunları şunlar şunları onlar onları hepsi hepsini ikisi ikisini
burada şurada orada buraya oraya bundan şundan ondan
dosya dosyayı dosyası dosyaları dosyadan ekle ekler ekleyelim yükle yükler yükleyelim kaydet
ingest havuza taslak seri seriyi olarak sisteme veri veriyi verisi verileri tablo tabloyu
göster gösterir hesapla karşılaştır getir bul çiz grafik grafiği rapor aylık haftalık günlük
yıllık çeyreklik yıl yılı yılında yılından ay ayı ayında değişim değişimi artış azalış
toplam ortalama son ilk bugün dün önce sonra arasında itibaren bu_yana beri lütfen evet hayır
please the and for with from into data file add load
""".split())

_CONFIRM = re.compile(
    r"(yine de|doğru dosya|dosya doğru|eminim|evet,? ekle|yanlış değil|ilgili dosya)", re.I
)


def stem(word: str) -> str:
    w = word.casefold().replace("i̇", "i")
    return w[:_STEM_LEN] if len(w) > _STEM_LEN else w


def content_terms(text: str) -> set[str]:
    """Metnin konu sözcükleri: küçük harf, durak sözcükler atılmış, ≥4 harf, kaba kök."""
    out: set[str] = set()
    for m in _WORD.finditer(text or ""):
        w = m.group(0).casefold()
        if len(w) < 4 or w in _STOP:
            continue
        out.add(stem(w))
    return out


def years_in(text: str) -> set[int]:
    return {int(y) for y in _YEAR.findall(text or "")}


def file_terms(frame: pd.DataFrame, locator: str) -> set[str]:
    """Dosya adı (uzantısız, sorgu dizesiz) + kolon başlıkları."""
    name = locator.split("?")[0].replace("\\", "/").rsplit("/", 1)[-1]
    name = name.rsplit(".", 1)[0] if "." in name else name
    text = " ".join([name.replace("_", " ").replace("-", " "), *map(str, frame.columns)])
    return content_terms(text)


def file_year_range(frame: pd.DataFrame, mapping: MappingProposal | None) -> tuple[int, int] | None:
    """Tarih kolonunu önerinin biçimiyle okuyup (min yıl, max yıl); okunamıyorsa None."""
    if mapping is None or mapping.observation_date_column not in frame.columns:
        return None
    years: list[int] = []
    for raw in frame[mapping.observation_date_column].astype(str):
        try:
            years.append(parse_date(raw, mapping.date_format).year)
        except (ValueError, TypeError):
            continue
    return (min(years), max(years)) if years else None


@dataclass(frozen=True)
class CatalogEntry:
    """Katalogdan yalnız gereken: ad ve alias'lar. Adaptör tipine bağımlılık yok."""

    dataset_id: str
    name: str
    aliases: tuple[str, ...] = ()

    def terms(self) -> set[str]:
        return content_terms(" ".join([self.name, *self.aliases]))


def catalog_entries(specs: Iterable[object]) -> list[CatalogEntry]:
    """`LakehouseClient.list_datasets()` çıktısından; alias'lar kolon düzeyinde (ColumnSpec)."""
    out: list[CatalogEntry] = []
    for s in specs:
        aliases: list[str] = []
        for c in getattr(s, "columns", ()) or ():
            aliases.extend(getattr(c, "aliases", ()) or ())
        out.append(CatalogEntry(str(getattr(s, "dataset_id", "")), str(getattr(s, "name", "")), tuple(aliases)))
    return out


@dataclass(frozen=True)
class RelevanceReport:
    score: int                       # tutan ölçüt sayısı
    applicable: int                  # uygulanabilen ölçüt sayısı
    period_ok: bool | None           # None: soruda yıl yok ya da dosya tarihi okunamadı
    question_years: tuple[int, ...]
    file_years: tuple[int, int] | None
    term_hits: tuple[str, ...]       # soru ∩ dosya kökleri
    question_terms: tuple[str, ...]
    catalog_hits: tuple[str, ...]    # soruya da dosyaya da uyan katalog serileri (ad)
    catalog_hit_ids: tuple[str, ...] = ()  # aynı serilerin dataset_id'si (çapraz kontrol için)

    @property
    def irrelevant(self) -> bool:
        return self.applicable >= 1 and self.score == 0

    def lines(self) -> list[str]:
        yrs = f"{self.file_years[0]}–{self.file_years[1]}" if self.file_years else "okunamadı"
        if self.period_ok is None:
            period = "dönem: ölçülmedi (soruda yıl yok)" if not self.question_years else f"dönem: dosya {yrs}, soru yılı okunamadı"
        else:
            period = (f"dönem: dosya {yrs}, soru {', '.join(map(str, self.question_years))} → "
                      + ("kapsıyor" if self.period_ok else "KAPSAMIYOR"))
        terms = ("terim: " + (", ".join(self.term_hits) if self.term_hits else "eşleşme yok")
                 + f" (soru: {', '.join(self.question_terms) or '—'})")
        cat = "katalog: " + (", ".join(self.catalog_hits) if self.catalog_hits else "eşleşme yok")
        return [f"ilgi puanı: {self.score}/{self.applicable}", period, terms, cat]


def assess(
    question: str,
    user_text: str,
    locator: str,
    frame: pd.DataFrame,
    mapping: MappingProposal | None,
    catalog: Iterable[CatalogEntry] = (),
) -> RelevanceReport:
    """Üç ölçütü uygula; yalnız uygulanabilenleri say."""
    q_text = question or user_text or ""
    q_terms = content_terms(q_text) or content_terms(user_text)
    q_years = years_in(question) or years_in(user_text)
    f_terms = file_terms(frame, locator)
    f_years = file_year_range(frame, mapping)

    applicable = 0
    score = 0

    period_ok: bool | None = None
    if q_years and f_years:
        applicable += 1
        lo, hi = f_years
        period_ok = any(lo <= y <= hi for y in q_years)
        score += int(period_ok)

    term_hits: tuple[str, ...] = ()
    if q_terms:
        applicable += 1
        term_hits = tuple(sorted(q_terms & f_terms))
        score += int(bool(term_hits))

    catalog_hits: list[str] = []
    catalog_ids: list[str] = []
    entries = list(catalog)
    if q_terms and entries:
        applicable += 1
        for e in entries:
            t = e.terms()
            if t and (t & q_terms) and (t & f_terms):
                catalog_hits.append(e.name or e.dataset_id)
                catalog_ids.append(e.dataset_id)
        score += int(bool(catalog_hits))

    return RelevanceReport(
        score=score, applicable=applicable, period_ok=period_ok,
        question_years=tuple(sorted(q_years)), file_years=f_years,
        term_hits=term_hits, question_terms=tuple(sorted(q_terms)),
        catalog_hits=tuple(catalog_hits), catalog_hit_ids=tuple(catalog_ids),
    )


def user_confirmed(user_text: str) -> bool:
    """Kullanıcı 'yine de ekle / doğru dosya bu' dedi mi — modelin bayrağı tek başına yetmez."""
    return bool(_CONFIRM.search(user_text or ""))


__all__ = [
    "CatalogEntry", "RelevanceReport", "assess", "catalog_entries", "content_terms",
    "file_terms", "file_year_range", "stem", "user_confirmed", "years_in",
]
