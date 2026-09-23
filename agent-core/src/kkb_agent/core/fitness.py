"""Uygunluk kapısı — "soru ne istiyor × veri ne sunuyor", tablo aktif olmadan ÖNCE (V3 §3.9; Büşra, 15 Eyl).

Neden var (ölçüldü, 14 Eyl UEB, docs/HUMAN_ERROR_RESEARCH_2026-09-14.md PART 14/19–22): profilci
biçime bakar (tarih kolonu var mı, sayı okunuyor mu), 13 Eylül ilgi kapısı sözcük örtüşmesine bakar;
ikisi de "konut fiyat endeksi" dosyasını "konut kredisi bakiyesi" sorusuna geçirdi (anlamca yakın
yanlış dosya: repo kapısı hard-negative'lerin %6'sını, bu modülün ablation kolu %98'ini reddetti;
BM25/embedding ayıramadı: R_min 0,51 < H_max 0,79). Sonuç: matematiksel olarak doğru, niyet
açısından yanlış cevaplar — sessiz (B07: "faiz ortalaması 459.904").

Ne yapar: sorudan GEREKLİ kavramları, veri imzasından (ad + başlıklar + tarih aralığı + frekans +
kolon medyanları + tek değerli boyutlar) MEVCUT kavramları çıkarır; altı boyutta karşılaştırır
(ölçüm, varlık/segment, dönem, granülarite, birim/makullük, kalite) ve tek karar verir:
  accept  — gerekli her şey var → tablo yüklenir, kart "uygunluk: kabul" der
  partial — gereksinim çıkarılamadı / ölçümlerin bir kısmı var / alt kümeye kısıtlı → yüklenir, UYARI satırı
  reject  — dönem/granülarite dışı ya da aranan ölçüm/varlık yok → tablo YÜKLENMEZ, kart dosyada ne olduğunu söyler
Kullanıcı "yine de yükle / doğru dosya bu" derse (relevance.user_confirmed) ret aşılır; model bayrağı tek başına yetmez.

Alan bilgisi kodda değil: kavramlar `config_data/concepts.json`'dan (CONCEPTS_FILE ile değiştirilir) ve
katalog kolon alias'larından (`Lexicon.with_catalog`) gelir. Katalogdan türeyen kavram "gevşek"tir:
eksikse ret değil "kısmen" (sözlük hatası yanlış STOP üretmesin; PART 35 red team). Boş sözlükte
kavram kararı "kısmen"dir; dönem/granülarite/makullük yine deterministik çalışır.

LLM yok, ağ yok, DB yok: saf fonksiyon; ablation'da 336 çift 83 ms.
"""

from __future__ import annotations

import json
import os
import re
import warnings
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

DEFAULT_CONCEPTS_PATH = Path(__file__).resolve().parent.parent / "config_data" / "concepts.json"

_TOK = re.compile(r"[a-zçğıöşüâîû0-9]+", re.I)
_YEAR = re.compile(r"\b(20[0-9]{2}|19[0-9]{2})\b")
_MONTH_NAME = re.compile(r"(ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|"
                         r"aralık|aralik|jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sep(tember)?|"
                         r"oct(ober)?|nov(ember)?|dec(ember)?)\.?", re.I)
#: İlişki sorusu: iki özne — tek özneyi taşıyan dosya "kısmen"dir, ret değil (ikinci kaynak gerekir).
_RELATION = re.compile(r"ilişki|etki|düştüğünde|arttığında|yükseldiğinde|karşılaştır|arasında|birlikte|öncül|korelasyon|"
                       r"relationship|when |versus|\bvs\b", re.I)
#: Soruda istenen granülarite (yalnız açık sözcükler; "yıllık büyüme" granülarite isteği değildir).
_GRAN_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("daily", re.compile(r"\bgünlük\b|\bgunluk\b|\bdaily\b", re.I)),
    ("weekly", re.compile(r"\bhaftalık\b|\bhaftalik\b|\bweekly\b", re.I)),
    ("monthly", re.compile(r"\bayl[ıi]k\b|\bmonthly\b|ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık|"
                           r"january|february|march|april|\bjune\b|july|august|september|october|november|december", re.I)),
    ("quarterly", re.compile(r"çeyrek|ceyrek|quarter", re.I)),
)
_GRAN_RANK = {"daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3, "yearly": 4}
#: Katalogdan türeyen kavramlarda ayırt edici olmayan kökler: "sayısı", "tutarı", "değeri" her ölçümde geçer;
#: kavram olsalar otobüs "sefer_sayisi" hastane "yatış sayısı"na uyar (ölçüldü, test_fitness).
_GENERIC_ROOTS = frozenset({"sayis", "sayıs", "adet", "adedi", "tutar", "deger", "değer", "topla", "oran", "orani", "oranı",
                            "mikta", "seri", "veri", "value", "count", "total", "amoun", "numbe"})
_UNIT_HINT = re.compile(r"milyon|milyar|\bbin\b|\bmn\b|\bth\b|\btry\b|\btl\b|%|yüzde|pct|adet|endeks|index|oran|kişi|ton|usd|eur", re.I)


def toks(text: str) -> set[str]:
    """Küçük harf belirteçler (İ→i, I→ı; Türkçe casefold tuzağı), ≥2 karakter."""
    return {t.replace("İ", "i").replace("I", "ı").casefold() for t in _TOK.findall(text or "") if len(t) >= 2}


_LOCATOR = re.compile(r"\S+://\S+|\S*[\\/]\S*|\S+\.(?:csv|tsv|xlsx?|json|pdf|png|jpe?g|txt|html?)\b", re.I)


def strip_locators(question: str) -> str:
    """Soru metninden adres ve dosya adlarını çıkarır: 'https://…/tufe' ya da 'konut.csv' sözcükleri soruya
    gereksinim eklemesin (ölçüldü: TÜFE sayfasından konut kredisi isteyen soruda 'tufe' de istenmiş sayıldı)."""
    return _LOCATOR.sub(" ", question or "")


def _match(tokens: Iterable[str], roots: Iterable[str]) -> bool:
    """Önek eşleşmesi: 'kartı' ~ 'kart', 'kredileri' ~ 'kredi'; kök ≤2 harfse tam eşleşme ister (ln, ev)."""
    rs = list(roots)
    return any((t == r) if len(r) <= 2 else t.startswith(r) for t in tokens for r in rs)


# ----------------------------------------------------------------------------- sözlük
@dataclass(frozen=True)
class Concept:
    id: str
    roots: frozenset[str]                 # dosya tarafı (ad + başlık); kısaltmalar dahil
    triggers: frozenset[str]              # soru tarafı; boşsa soruda aranmaz
    measure: bool = False                 # analizin üzerinde çalıştığı ölçüm mü (eksikse ret)
    supersedes: frozenset[str] = frozenset()
    max_abs_median: float | None = None   # bu adla etiketli kolonun medyanı sınırı aşarsa etiket güvenilmez
    strict: bool = True                   # False: katalogdan türedi — eksikse "kısmen", ret değil
    source: str = "config"


@dataclass(frozen=True)
class Lexicon:
    concepts: dict[str, Concept] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Lexicon":
        return _load(str(path or os.getenv("CONCEPTS_FILE") or DEFAULT_CONCEPTS_PATH))

    @classmethod
    def empty(cls) -> "Lexicon":
        return cls({})

    def with_catalog(self, specs: Iterable[object]) -> "Lexicon":
        """Katalog kolon alias'larını gevşek kavram olarak ekler (ColumnSpec.aliases; ADR-0030 sözleşmesi).

        Kavram kimliği kolon adıdır; kökler alias sözcüklerinin ilk 5 harfi (4+ harfli sözcükler; 'tp',
        'yp', 'toplam' gibi genel adlar kavram olmaz — soruda 'toplam' geçince dosyayı reddetmesin).
        Yapılandırmada aynı kimlik varsa yapılandırma kazanır."""
        from ..builder.relevance import content_terms

        merged = dict(self.concepts)
        # Yapılandırmadaki kavramların kökleri katalog kavramına girmez: 'toplam' kolonunun alias'ı "kredi bakiyesi" ise
        # 'kredi'/'bakiy' zaten 'kredi'/'bakiye' kavramıdır; ikinci bir kavram olarak istenirse doğru dosya "eksik toplam"
        # diye kısmen kalır (ölçüldü, UEB D08 duman koşusu: "eksik kalem" uyarısı). Katalog yalnız YENİ sözcük ekler.
        taken = {r for c in self.concepts.values() for r in c.roots}
        for s in specs:
            for c in getattr(s, "columns", ()) or ():
                aliases = tuple(getattr(c, "aliases", ()) or ())
                if not aliases:
                    continue
                cid = str(getattr(c, "name", "") or "").strip()
                if not cid or cid in merged:
                    continue
                role = str(getattr(getattr(c, "role", None), "value", getattr(c, "role", "")) or "")
                roots = frozenset(content_terms(" ".join([cid.replace("_", " "), *aliases])))
                roots = frozenset(r for r in roots if len(r) >= 4 and r not in _GENERIC_ROOTS
                                  and not any(r.startswith(t) or t.startswith(r) for t in taken))
                if not roots:
                    continue
                merged[cid] = Concept(id=cid, roots=roots, triggers=roots, measure=(role == "measure"),
                                      strict=False, source=f"katalog:{getattr(s, 'dataset_id', '')}")
        return Lexicon(merged)

    # ---- soru tarafı
    def required(self, question: str) -> set[str]:
        qt = toks(question)
        req = {c.id for c in self.concepts.values() if c.triggers and _match(qt, c.triggers)}
        for cid in list(req):
            req -= set(self.concepts[cid].supersedes) - {cid}
        return req

    # ---- veri tarafı
    def present(self, sig: "DataSignature") -> tuple[set[str], list[str]]:
        """Dosya adı + başlıklarda geçen kavramlar; makullük ihlali olan etiket düşer ve gerekçe döner."""
        ft = toks(sig.name.replace("_", " ") + " " + " ".join(sig.headers))
        have: set[str] = set()
        notes: list[str] = []
        for c in self.concepts.values():
            if not _match(ft, c.roots):
                continue
            if c.max_abs_median is not None:
                bad = [(col, m) for col, m in sig.numeric_median.items()
                       if _match(toks(col), c.roots) and abs(m) > c.max_abs_median]
                if bad:
                    col, m = bad[0]
                    notes.append(f"etiket-değer uyuşmazlığı: '{col}' {c.id} gibi adlandırılmış, medyan {m:,.0f}".replace(",", "."))
                    continue
            have.add(c.id)
        return have, notes


@lru_cache(maxsize=4)
def _load(path: str) -> Lexicon:
    p = Path(path)
    if not p.is_file():
        return Lexicon.empty()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Lexicon.empty()
    out: dict[str, Concept] = {}
    for cid, spec in (data.get("concepts") or {}).items():
        roots = frozenset(str(r).casefold() for r in spec.get("roots") or ())
        trig = spec.get("triggers")
        out[str(cid)] = Concept(
            id=str(cid), roots=roots,
            triggers=roots if trig is None else frozenset(str(t).casefold() for t in trig),
            measure=bool(spec.get("measure", False)),
            supersedes=frozenset(str(x) for x in spec.get("supersedes") or ()),
            max_abs_median=(float(spec["max_abs_median"]) if spec.get("max_abs_median") is not None else None),
        )
    return Lexicon(out)


def clear_cache() -> None:
    _load.cache_clear()


# ----------------------------------------------------------------------------- veri imzası
@dataclass(frozen=True)
class DataSignature:
    """Bir tablonun kapıya giren özeti — dosya, web tablosu ya da OCR tablosu fark etmez."""

    name: str                                   # dosya/tablo adı (uzantısız)
    headers: tuple[str, ...]
    rows: int
    years: tuple[int, int] | None = None        # tarih kolonundan (min, max) yıl
    frequency: str | None = None                # daily|weekly|monthly|quarterly|yearly|None
    date_column: str | None = None
    numeric_median: dict[str, float] = field(default_factory=dict)
    scoped: tuple[str, ...] = ()                # "kolon=değer": tek değerli metin kolonları (alt küme)
    unit_hint: bool = False                     # ad/başlıkta birim ipucu var mı

    def coverage(self) -> str:
        """Kapsam beyanı için kısa biçim: ad, dönem, frekans, satır."""
        yrs = f"{self.years[0]}–{self.years[1]}" if self.years else "dönem okunamadı"
        return f"{self.name} — {yrs}, {self.frequency or 'frekans bilinmiyor'}, {self.rows} satır"

    def describe(self) -> str:
        yrs = f"{self.years[0]}–{self.years[1]}" if self.years else "tarih okunamadı"
        return (f"{self.name}: {self.rows} satır; kolonlar {', '.join(self.headers)}; dönem {yrs}; "
                f"frekans {self.frequency or 'bilinmiyor'}" + (f"; kısıt {', '.join(self.scoped)}" if self.scoped else ""))


def _tr_number(s: pd.Series) -> pd.Series:
    """Metin hücreleri Türkçe (binlik '.', ondalık ',') ya da İngiliz biçiminde olabilir; sayısal dtype olduğu gibi."""
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    txt = s.astype(str).str.strip()
    tr = txt.str.contains(",", regex=False) | txt.str.fullmatch(r"-?\d{1,3}(\.\d{3})+")
    conv = txt.where(~tr, txt.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(conv, errors="coerce")


def _to_dt(s: pd.Series) -> pd.Series:
    """pd.to_datetime, 'biçim çıkarılamadı' uyarısı olmadan (her kolon denenir; uyarı gürültüdür, hata değil)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(s, errors="coerce")
    if len(parsed) and parsed.isna().all():
        # Dönem + tarih aralığı hücreleri ("2021/01 (04.01.21-08.01.21)"): aralığın bitiş günü (23 Eyl, dış rapor haftalık).
        from ..builder.profile import range_end_date
        ends = s.map(lambda v: range_end_date(str(v)) if v is not None else None)
        if ends.notna().any():
            return pd.to_datetime(ends, errors="coerce")
    return parsed


def _infer_frequency(dates: pd.Series) -> str | None:
    good = dates.dropna().sort_values().drop_duplicates()
    if len(good) < 3:
        return None
    med = good.diff().dt.days.dropna().median()
    for name, hi in (("daily", 1.5), ("weekly", 8), ("monthly", 31.5), ("quarterly", 93), ("yearly", 370)):
        if med <= hi:
            return name
    return None


def signature_of(frame: pd.DataFrame, locator: str, *, mapping: Any = None, semantics: Any = None) -> DataSignature:
    """Tablodan imza. `mapping`/`semantics` (builder.profile önerisi) varsa tarih kolonu ve frekans oradan;
    yoksa toleranslı eşleme: ≥%80 tarihe ayrışan kolon (profilci %100 ister; toplam satırı bozar), yıl kolonu
    (yil/yıl/year) → yıllık tablo."""
    name = str(locator or "").split("?")[0].replace("\\", "/").rsplit("/", 1)[-1]
    name = name.rsplit(".", 1)[0] if "." in name else name
    # Yinelenen ya da sayısal kolon etiketi (TCMB today.xml, başlıksız Excel): `frame[c]` DataFrame döner ve tarih/yıl
    # taraması "cannot assemble with duplicate keys" ile patlar; kapı sessizce atlanıyordu (22 Eyl, arkadaş bulgusu).
    # İmza için etiketler tekil dizeye çevrilir; çağıranın tablosu değişmez.
    if len(set(map(str, frame.columns))) != len(frame.columns) or any(not isinstance(c, str) for c in frame.columns):
        seen: dict[str, int] = {}
        labels = []
        for c in map(str, frame.columns):
            n = seen.get(c, 0)
            labels.append(c if n == 0 else f"{c}_{n}")
            seen[c] = n + 1
        frame = frame.copy()
        frame.columns = labels
    headers = tuple(str(c) for c in frame.columns)
    years: tuple[int, int] | None = None
    freq: str | None = getattr(semantics, "frequency", None) if semantics is not None else None
    date_col: str | None = None

    dcol = getattr(mapping, "observation_date_column", None) if mapping is not None else None
    if dcol is not None and dcol in frame.columns:
        date_col = str(dcol)
        from ..builder.relevance import file_year_range
        years = file_year_range(frame, mapping)
        if freq is None:
            freq = _infer_frequency(_to_dt(frame[dcol]))
    else:
        year_col = next((c for c in frame.columns if re.fullmatch(r"y[ıi]l|year", str(c), re.I)), None)
        if year_col is not None:
            ys = pd.to_numeric(frame[year_col], errors="coerce").dropna()
            ys = ys[(ys >= 1900) & (ys <= 2100)]
            if len(ys):
                # Geniş tablo (Yıl | Ocak | Şubat …): satır başına bir yıl ama ay kolonları var → aylık veri. Yıllık sayılınca
                # "2025 Ocak" sorusu granülarite ile reddediliyordu (PR #4 CI, test_vision OCR belgesi).
                months = sum(bool(_MONTH_NAME.match(h.strip())) for h in headers)
                years, freq, date_col = (int(ys.min()), int(ys.max())), freq or ("monthly" if months >= 2 else "yearly"), str(year_col)
        if years is None and len(frame):
            best, best_ratio = None, 0.0
            for c in frame.columns:
                if pd.api.types.is_numeric_dtype(frame[c]) and not pd.api.types.is_datetime64_any_dtype(frame[c]):
                    continue
                parsed = _to_dt(frame[c])
                ratio = float(parsed.notna().mean())
                if ratio > best_ratio:
                    best, best_ratio = c, ratio
            if best is not None and best_ratio >= 0.8:
                parsed = _to_dt(frame[best]).dropna()
                years, date_col = (int(parsed.dt.year.min()), int(parsed.dt.year.max())), str(best)
                freq = freq or _infer_frequency(parsed)
        if years is None:
            # Scan every cell as text for 4-digit years. Coerce each value with str():
            # duplicate/float column labels make frame[c] a DataFrame and leak non-str
            # into the join (e.g. TCMB XML tables), so .astype(str) alone is not safe.
            cells = " ".join(str(v) for v in frame.to_numpy().ravel().tolist())
            ys = sorted({int(y) for y in _YEAR.findall(cells)})
            years = (ys[0], ys[-1]) if ys else None

    med: dict[str, float] = {}
    scoped: list[str] = []
    for c in frame.columns:
        vals = _tr_number(frame[c]).dropna()
        if len(vals) >= 3 and str(c) != date_col:
            med[str(c)] = float(vals.median())
            continue
        s = frame[c].astype(str).str.strip()
        distinct = set(s[s != ""])
        if len(distinct) == 1 and len(frame) >= 3 and str(c) != date_col and not _YEAR.search(next(iter(distinct))):
            scoped.append(f"{c}={next(iter(distinct))}")
    return DataSignature(name=name, headers=headers, rows=int(len(frame)), years=years, frequency=freq, date_column=date_col,
                         numeric_median=med, scoped=tuple(scoped),
                         unit_hint=bool(_UNIT_HINT.search(" ".join(headers) + " " + name.replace("_", " "))))


# ----------------------------------------------------------------------------- karar
@dataclass(frozen=True)
class Fitness:
    decision: str                       # accept | partial | reject
    score: float
    reasons: tuple[str, ...]
    dims: dict[str, str]                # measure/entity/period/granularity/unit/quality → ok|fail|partial|n/a
    required: tuple[str, ...]
    present: tuple[str, ...]
    signature: DataSignature

    @property
    def label(self) -> str:
        return {"accept": "kabul", "partial": "kısmen", "reject": "RET"}[self.decision]

    def lines(self) -> list[str]:
        head = f"uygunluk: {self.label} ({self.score:.2f}) — " + ("; ".join(self.reasons) if self.reasons else "gerekli kavramlar var")
        return [head, "  soru istiyor: " + _short_list(self.required) + " | veride: " + _short_list(self.present)]

    def stop_message(self) -> str:
        """Ret kartı: modelin ne söyleyeceği — dosyada NE VAR, ne YOK; suçlamayan dil."""
        sig = self.signature
        return (f"'{sig.name}' bu soru için uygun görünmüyor: {'; '.join(self.reasons)}. "
                f"Dosyada olan: kolonlar {', '.join(sig.headers)}"
                + (f"; dönem {sig.years[0]}–{sig.years[1]}" if sig.years else "")
                + (f"; frekans {sig.frequency}" if sig.frequency else "") + ".")


def _short_list(items: set[str] | list[str], limit: int = 6) -> str:
    """Uyarıda veri terimleri: teknik sütun adları (`<seri>@<varlık>::<ölçü>`) çıkarılır, en çok `limit` terim yazılır.
    Canlı koşu (23 Eyl): birleşik tablonun teknik adları insan diline çevrilince aynı ad onlarca kez tekrarlandı."""
    clean = sorted({str(item) for item in items if "::" not in str(item)})
    if not clean:
        return "—"
    return ", ".join(clean[:limit]) + (f" (+{len(clean) - limit})" if len(clean) > limit else "")


def assess(question: str, sig: DataSignature, lexicon: Lexicon | None = None) -> Fitness:
    """Karar sırası (ablation H kolu, PART 14): (1) gereksinim çıkarılamadı → kısmen; (2) dönem/granülarite dışı →
    ret; (3) aranan ÖLÇÜM hiç yok → ret (ilişki sorusunda özne varsa kısmen); (4) niteleyici/varlık eksik → ret;
    (5) ölçümlerin bir kısmı var → kısmen; (6) tek değerli boyut soruda geçmiyor → kısmen; (7) hepsi var → kabul.
    Gevşek (katalog) kavram eksikse (3)/(4) ret değil kısmen."""
    lex = lexicon if lexicon is not None else Lexicon.load()
    dims = {"measure": "n/a", "entity": "n/a", "period": "n/a", "granularity": "n/a", "unit": "n/a", "quality": "n/a"}
    question = strip_locators(question)
    req = lex.required(question)
    have, notes = lex.present(sig)
    reasons: list[str] = list(notes)
    if notes:
        dims["unit"] = "fail"
    elif sig.unit_hint:
        dims["unit"] = "ok"

    def out(decision: str, score: float) -> Fitness:
        return Fitness(decision, score, tuple(reasons), dims, tuple(sorted(req)), tuple(sorted(have)), sig)

    # dönem
    qy = {int(y) for y in _YEAR.findall(question or "")}
    if qy and sig.years:
        ok = any(sig.years[0] <= y <= sig.years[1] for y in qy)
        dims["period"] = "ok" if ok else "fail"
        if not ok:
            reasons.append(f"dönem: soru {', '.join(map(str, sorted(qy)))} istiyor, veri {sig.years[0]}–{sig.years[1]}")
    # granülarite
    asked = next((g for g, pat in _GRAN_WORDS if pat.search(question or "")), None)
    if asked and sig.frequency in _GRAN_RANK:
        fine = _GRAN_RANK[asked] < _GRAN_RANK[sig.frequency]
        dims["granularity"] = "fail" if fine else "ok"
        if fine:
            reasons.append(f"granülarite: {asked} istendi, veri {sig.frequency}")
    if dims["period"] == "fail" or dims["granularity"] == "fail":
        return out("reject", 0.0)

    if not req:
        reasons.append("sorudan gereksinim çıkarılamadı")
        return out("partial", 0.5)

    measures = {c for c in req if lex.concepts[c].measure}
    m_have = {c for c in have if c in lex.concepts and lex.concepts[c].measure}
    qualifiers = req - measures
    strict = lambda cs: {c for c in cs if lex.concepts[c].strict}  # noqa: E731
    if notes and measures and not (measures & m_have):
        # Etiket-değer çelişkisi var ve aranan ölçüm başka bir kolonda da yok: "adsız" değil "güvenilmez" (B07: 459.904'lük faiz).
        dims["measure"] = "fail"
        reasons.append(f"aranan ölçüm ({', '.join(sorted(measures))}) güvenilir bir kolonda yok; etiketi çelişen tablo bu ölçüm için kullanılmaz")
        return out("reject", 0.0)
    if not (req & have):
        # Ortak hiçbir kavram yok: ilgisiz (otobüs tarifesi). Gevşek (katalog) kavramlar tek başına ret vermez.
        dims["measure"] = "fail" if measures else "n/a"
        dims["entity"] = "fail" if qualifiers else "n/a"
        reasons.append(f"soru {_short_list(req)} istiyor; veride bunların hiçbiri yok" + (f" (veride: {_short_list(have)})" if have else ""))
        return out("reject" if strict(req) else "partial", 0.0 if strict(req) else 0.4)
    if measures and m_have and not (measures & m_have):
        # Dosya BAŞKA bir ölçümü taşıyor (fiyat endeksi ≠ bakiye): niyet açısından yanlış veri.
        dims["measure"] = "fail"
        if _RELATION.search(question or "") and qualifiers and qualifiers <= have:
            dims["measure"] = "partial"
            reasons.append(f"ilişki sorusu: veri {', '.join(sorted(qualifiers))} öznesini taşıyor ama {', '.join(sorted(measures))} ölçümü yok — ikinci kaynak gerekir")
            return out("partial", 0.55)
        reasons.append(f"aranan ölçüm yok: {', '.join(sorted(measures))}; veride: {', '.join(sorted(m_have))}")
        return out("reject" if strict(measures) else "partial", 0.0 if strict(measures) else 0.4)
    missing_q = qualifiers - have
    if missing_q:
        # Niteleyici eksik. Dosya etiketli (ölçüm kavramı taşıyor: 'tüketici kredisi bakiyesi') ya da başka bir varlık
        # taşıyorsa ('ihtiyaç') → farklı segment, ret. Hiçbir ölçüm/varlık etiketi yoksa ('deger' kolonu) yanlış olduğu
        # kanıtlanamaz → kısmen, uyarıyla yüklenir (ölçüldü: 'konut.csv' + 'deger' kolonu için yanlış STOP).
        competing = strict(have - req)
        labeled = bool(m_have) or bool(competing)
        dims["entity"] = "fail" if (labeled and strict(missing_q)) else "partial"
        reasons.append(f"varlık/segment {'farklı' if labeled else 'belirsiz'}: eksik {', '.join(sorted(missing_q))}; "
                       f"veride {_short_list(have)}")
        return out("reject" if dims["entity"] == "fail" else "partial", 0.2 if labeled else 0.45)
    dims["entity"] = "ok" if qualifiers else "n/a"
    if measures and not m_have:
        dims["measure"] = "partial"
        reasons.append(f"ölçüm adı belirsiz: veride {', '.join(sorted(measures))} adıyla kolon yok (kolonlar: {', '.join(sig.headers)}); "
                       "kullanıcıya hangi kolonun bu ölçüm olduğunu sor")
        return out("partial", 0.5)
    if measures - m_have:
        dims["measure"] = "partial"
        reasons.append(f"ölçümlerin bir kısmı var ({', '.join(sorted(m_have))}), eksik {', '.join(sorted(measures - m_have))} — ikinci dosya/seri gerekir")
        return out("partial", 0.6)
    dims["measure"] = "ok" if measures else "n/a"
    for scope in sig.scoped:
        val = scope.split("=", 1)[1].replace("İ", "i").replace("I", "ı").casefold()
        if not _match(toks(question), {val[:5]}):
            dims["entity"] = "partial"
            reasons.append(f"veri bir alt kümeye kısıtlı ({scope}); soru bunu söylemiyor")
            return out("partial", 0.7)
    return out("accept", 1.0)


__all__ = ["Concept", "DEFAULT_CONCEPTS_PATH", "DataSignature", "Fitness", "Lexicon", "assess", "clear_cache",
           "signature_of", "strip_locators", "toks"]
