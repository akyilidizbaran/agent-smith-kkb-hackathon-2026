"""Tamamlanma sözleşmesi — istek neyi bekliyor, teslim edilen tablo onu karşılıyor mu? (22 Eylül)

Ölçülen boşluk (benchmark P02/P04, 21–22 Eyl): model 24 aylık bir aralığın 23 ayını getirip "tamam" dedi; istenen
fark kolonu yoktu; iki serilik karşılaştırmada tek seri geldi. Anlatı denetimi (`grounding`) yalnız "cevaptaki sayı
araç çıktısında var mı" diye bakar; "istenen kapsam geldi mi" diye bakan yoktu.

Bu modül soruya özel kural taşımaz. Beklenti soru metninden DETERMİNİSTİK türetilir:

  dönem penceresi  — "2023-01–2024-12", "202301–202412", "2021Q3–2025Q2", "2021-2025", "2024 takvim yılı",
                     "Ocak 2023 – Aralık 2024"; frekans soru sözcüğünden ya da pencerenin tanesinden
  türetim          — "önceki aya göre fark" (fark kolonu), "yüzde değişim" (oran kolonu)
  seri kimlikleri  — soruda açıkça geçen katalog kimlikleri (1357_Toplam, TP.KTF12, bddk_monthly:…)
  aday listesi     — "listele / eşleşen serileri / adayları" → tam aday tablosu beklenir (search_ledger ile)

Kontrol tabloya bakar: dönem kapsamı (eksik dönemler sayılır ve adlandırılır), seri kimliklerinin korunması
(tablonun kaynak kimlikleri ya da başarılı sorguların SQL'i), türetilmiş kolonun girdisiyle tutarlılığı
(fark = değer − önceki değer, yüzde = fark / önceki). Anlatıdaki sayılar zaten `grounding` ile denetlenir.

Sonuç `CompletionReport`: boşluk yoksa sessiz; varsa ajan bir kez modele geri gönderir ("araçlarla tamamla"),
ikinci kez de eksikse cevabın sonuna deterministik "Kapsam kontrolü" notu düşer. Cevap asla sessizce eksik
teslim edilmez; asla soruya özel kural eklenmez.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

import pandas as pd

from .claim_check import _date_column, _to_dt

_MONTHS = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5, "haziran": 6, "temmuz": 7,
    "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9, "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
}
_SEP = r"\s*(?:–|—|-|/|→|->|ile|ve|'den|'dan|dan|den|ten|tan)\s*"
#: Ay adı / çeyrek yazımlarında ayraç boşluk da olabilir ("2021 3. çeyrekten 2025 2. çeyreğe", "Ocak 2023 Aralık 2024");
#: yıl çiftinde olamaz (iki yıl yan yana başka anlam taşır).
_SEP_LOOSE = r"\s*(?:–|—|-|/|→|->|ile|ve|'den|'dan|dan|den|ten|tan|kadar)?\s*"
_Y = r"(19\d{2}|20\d{2})"
_MONTH_PAIR = re.compile(rf"\b{_Y}[-/.](0?[1-9]|1[0-2])\b{_SEP}\b{_Y}[-/.](0?[1-9]|1[0-2])\b")
_COMPACT_PAIR = re.compile(rf"\b{_Y}(0[1-9]|1[0-2])\b{_SEP}\b{_Y}(0[1-9]|1[0-2])\b")
_QUARTER_PAIR = re.compile(rf"\b{_Y}\s*[Qç]\s*([1-4])\b{_SEP}\b{_Y}\s*[Qç]\s*([1-4])\b", re.I)
_QUARTER_TR_PAIR = re.compile(rf"\b{_Y}\s+([1-4])\.?\s*çeyre[kğ]\w*{_SEP_LOOSE}\b{_Y}\s+([1-4])\.?\s*çeyre[kğ]\w*", re.I)
_NAMED_PAIR = re.compile(
    r"\b(ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)\s+"
    rf"{_Y}{_SEP_LOOSE}(ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)\s+{_Y}",
    re.I,
)
_YEAR_PAIR = re.compile(rf"\b{_Y}{_SEP}{_Y}\b")
_CALENDAR_YEAR = re.compile(rf"\b{_Y}\s+(?:takvim\s+)?yıl\w*", re.I)
_HALF_YEAR = re.compile(rf"\b{_Y}\s+(ilk|birinci|ikinci|son)\s+yarı\w*", re.I)
_FREQ_WORDS = {
    "monthly": ("aylık", "aylik", "ay ay", "ay sonu", "her ay"),
    "quarterly": ("çeyreklik", "ceyreklik", "çeyrek", "ceyrek"),
    "weekly": ("haftalık", "haftalik"),
    "yearly": ("yıllık", "yillik"),
    "daily": ("günlük", "gunluk"),
}
#: Türetim istekleri: (etiket, kalıp). Etiket denetimde kullanılır, soruya özel değil.
_DERIVATIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("diff", re.compile(r"(önceki|bir önceki|geçen)\s+(aya|döneme|yıla|çeyreğe|haftaya)\s+göre[^.;]*?(mutlak\s+)?fark|mutlak\s+fark|aylık\s+fark", re.I)),
    ("pct", re.compile(r"yüzde\s+değişim|yüzdelik\s+değişim|%\s*değişim|yüzde\s+(fark|artış|azalış)", re.I)),
)
_SERIES_ID = re.compile(r"\b(?:bddk_\w+|evds|gold|adhoc):[\w.\-]+|\b\d{3,4}_[A-Za-z]+\b|\bTP\.[A-Z0-9.]+\b")
_LISTING = re.compile(r"\blistele|adaylar[ıi]|eşleşen\s+(aktif\s+)?seril|hangi\s+(\w+\s+)?seriler|mevcut\s+serileri", re.I)


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _quarter_end(y: int, q: int) -> date:
    return _month_end(y, q * 3)


@dataclass(frozen=True)
class Expectation:
    """Sorudan türetilen beklenti; alan boşsa o boyut denetlenmez (bilinmeyen zorlanmaz)."""

    start: date | None = None
    end: date | None = None
    frequency: str | None = None          # monthly | quarterly | weekly | yearly | daily | None
    derivations: tuple[str, ...] = ()     # "diff", "pct"
    series_ids: tuple[str, ...] = ()      # soruda açıkça geçen kimlikler
    listing: bool = False                 # aday listesi istendi
    source: str = ""                      # hangi kalıp yakaladı (iz için)

    @property
    def expected_periods(self) -> list[date] | None:
        """Frekans ve pencere biliniyorsa dönem sonları; aksi hâlde None (sayı zorlanmaz)."""
        if self.start is None or self.end is None:
            return None
        if self.frequency == "monthly":
            out, y, m = [], self.start.year, self.start.month
            while (y, m) <= (self.end.year, self.end.month):
                out.append(_month_end(y, m))
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            return out
        if self.frequency == "quarterly":
            out, y, q = [], self.start.year, (self.start.month - 1) // 3 + 1
            while (y, q) <= (self.end.year, (self.end.month - 1) // 3 + 1):
                out.append(_quarter_end(y, q))
                y, q = (y + 1, 1) if q == 4 else (y, q + 1)
            return out
        if self.frequency == "yearly":
            return [date(y, 12, 31) for y in range(self.start.year, self.end.year + 1)]
        return None

    @property
    def enforceable(self) -> bool:
        return bool(self.start or self.derivations or self.series_ids or self.listing)

    def describe(self) -> str:
        parts = []
        if self.start and self.end:
            parts.append(f"dönem {self.start:%Y-%m} → {self.end:%Y-%m}" + (f" ({self.frequency})" if self.frequency else ""))
            if self.expected_periods is not None:
                parts[-1] += f", {len(self.expected_periods)} dönem"
        if self.derivations:
            parts.append("türetim: " + ", ".join(self.derivations))
        if self.series_ids:
            parts.append("seri: " + ", ".join(self.series_ids))
        if self.listing:
            parts.append("aday listesi")
        return "; ".join(parts)


def _frequency_word(question: str) -> str | None:
    q = question.lower()
    hits = [f for f, words in _FREQ_WORDS.items() if any(re.search(rf"(?<!\d)(?<!\d )\b{w}", q) for w in words)]
    return hits[0] if len(hits) == 1 else None


def derive_expectation(question: str) -> Expectation:
    """Soru metninden beklenti. Kalıplar genel (tarih dilbilgisi, türetim sözcükleri, katalog kimliği biçimi)."""
    q = question or ""
    start = end = None
    gran: str | None = None
    src = ""
    if m := _MONTH_PAIR.search(q):
        y1, m1, y2, m2 = map(int, m.groups()); start, end, gran, src = date(y1, m1, 1), _month_end(y2, m2), "monthly", "ay-çifti"
    elif m := _COMPACT_PAIR.search(q):
        y1, m1, y2, m2 = map(int, m.groups()); start, end, gran, src = date(y1, m1, 1), _month_end(y2, m2), "monthly", "YYYYMM"
    elif m := _QUARTER_PAIR.search(q):
        y1, q1, y2, q2 = map(int, m.groups()); start, end, gran, src = date(y1, (q1 - 1) * 3 + 1, 1), _quarter_end(y2, q2), "quarterly", "çeyrek"
    elif m := _QUARTER_TR_PAIR.search(q):
        y1, q1, y2, q2 = map(int, m.groups()); start, end, gran, src = date(y1, (q1 - 1) * 3 + 1, 1), _quarter_end(y2, q2), "quarterly", "çeyrek-tr"
    elif m := _NAMED_PAIR.search(q):
        m1, y1, m2, y2 = _MONTHS[m.group(1).lower()], int(m.group(2)), _MONTHS[m.group(3).lower()], int(m.group(4))
        start, end, gran, src = date(y1, m1, 1), _month_end(y2, m2), "monthly", "ay-adı"
    elif m := _YEAR_PAIR.search(q):
        y1, y2 = int(m.group(1)), int(m.group(2))
        if 1990 <= y1 <= y2 <= 2100:
            start, end, gran, src = date(y1, 1, 1), date(y2, 12, 31), None, "yıl-çifti"
    elif m := _HALF_YEAR.search(q):
        y, first = int(m.group(1)), m.group(2).lower() in ("ilk", "birinci")
        start, end = (date(y, 1, 1), date(y, 6, 30)) if first else (date(y, 7, 1), date(y, 12, 31))
        gran, src = None, "yarıyıl"
    elif m := _CALENDAR_YEAR.search(q):
        y = int(m.group(1)); start, end, gran, src = date(y, 1, 1), date(y, 12, 31), None, "takvim-yılı"
    freq = _frequency_word(q) or gran
    derivations = tuple(tag for tag, pat in _DERIVATIONS if pat.search(q))
    ids = tuple(dict.fromkeys(_SERIES_ID.findall(q)))
    return Expectation(start=start, end=end, frequency=freq, derivations=derivations, series_ids=ids,
                       listing=bool(_LISTING.search(q)), source=src)


@dataclass
class CompletionReport:
    expectation: Expectation
    gaps: list[str] = field(default_factory=list)
    expected_periods: int | None = None
    found_periods: int | None = None
    missing_periods: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)      # hangi boyutlar denetlendi

    @property
    def ok(self) -> bool:
        return not self.gaps

    def note(self) -> str:
        """Cevabın sonuna deterministik kapanış: eksik ne, sayıyla."""
        if not self.gaps:
            return ""
        return "(Kapsam kontrolü: " + "; ".join(self.gaps) + ".)"

    def to_dict(self) -> dict[str, Any]:
        return {"expectation": self.expectation.describe(), "gaps": list(self.gaps), "expected_periods": self.expected_periods,
                "found_periods": self.found_periods, "missing_periods": list(self.missing_periods), "checked": list(self.checked)}


def _period_key(d: date, frequency: str | None) -> tuple:
    if frequency == "quarterly":
        return (d.year, (d.month - 1) // 3 + 1)
    if frequency == "yearly":
        return (d.year,)
    return (d.year, d.month)


def _table_dates(table: pd.DataFrame) -> list[date]:
    col = _date_column(table)
    if col is None:
        return []
    return [d.date() for d in _to_dt(table[col]).dropna()]


def _numeric_columns(table: pd.DataFrame) -> list[str]:
    return [str(c) for c in table.columns if pd.api.types.is_numeric_dtype(table[c]) and not pd.api.types.is_bool_dtype(table[c])]


def _derivation_present(table: pd.DataFrame, tag: str) -> bool:
    """`diff`: bir kolon başka bir kolonun ardışık farkı mı; `pct`: yüzde/oran değişimi mi (ilk satır boş olabilir)."""
    cols = _numeric_columns(table)
    if len(cols) < 2 or len(table) < 3:
        return False
    for base in cols:
        s = pd.to_numeric(table[base], errors="coerce")
        if tag == "diff":
            target = s.diff()
        else:
            prev = s.shift(1)
            target = (s - prev) / prev
        for cand in cols:
            if cand == base:
                continue
            c = pd.to_numeric(table[cand], errors="coerce")
            mask = target.notna() & c.notna()
            if mask.sum() < max(2, int(0.8 * (len(table) - 1))):
                continue
            t, v = target[mask].to_numpy(dtype=float), c[mask].to_numpy(dtype=float)
            scale = abs(t).max() or 1.0
            if tag == "pct":
                # yüzde 100 ölçeğinde ya da oran olarak yazılmış olabilir
                if (abs(v - t * 100).max() <= 0.01 * max(1.0, abs(t * 100).max())) or (abs(v - t).max() <= 0.01 * max(1e-9, scale)):
                    return True
            elif abs(v - t).max() <= 1e-6 * max(1.0, scale):
                return True
    return False


def check_completion(
    expectation: Expectation,
    table: pd.DataFrame | None,
    *,
    provenance_ids: Iterable[str] = (),
    sql_texts: Iterable[str] = (),
    candidate_count: int | None = None,
) -> CompletionReport:
    """Teslim edilen tablo beklentiyi karşılıyor mu. Bilinmeyen boyut denetlenmez, eksik boyut adlandırılır."""
    report = CompletionReport(expectation=expectation)
    if not expectation.enforceable:
        return report
    exp_periods = expectation.expected_periods
    if expectation.listing:
        report.checked.append("aday listesi")
        if candidate_count is None:
            report.gaps.append("aday listesi istendi ama arama adayları tablo olarak sunulmadı")
    if table is None or len(table) == 0:
        if expectation.start or expectation.derivations or expectation.series_ids:
            report.gaps.append("istenen veri için tablo yok")
        return report
    if expectation.start and expectation.end:
        report.checked.append("dönem kapsamı")
        dates = _table_dates(table)
        if not dates:
            report.gaps.append("tabloda tarih kolonu bulunamadı, dönem kapsamı doğrulanamadı")
        elif exp_periods is not None:
            have = {_period_key(d, expectation.frequency) for d in dates}
            want = [(_period_key(p, expectation.frequency), p) for p in exp_periods]
            missing = [p for key, p in want if key not in have]
            report.expected_periods, report.found_periods = len(want), len(want) - len(missing)
            if missing:
                report.missing_periods = [p.strftime("%Y-%m") if expectation.frequency != "yearly" else str(p.year) for p in missing]
                shown = ", ".join(report.missing_periods[:6]) + (" …" if len(missing) > 6 else "")
                report.gaps.append(f"istenen {len(want)} dönemin {len(missing)} tanesi tabloda yok ({shown})")
        else:
            # Frekans bilinmiyor (yalnız yıl aralığı / "2025 yılında"): dönem sayısı zorlanmaz; yalnız istenen pencerede
            # HİÇ gözlem yoksa boşluktur. Kısmi yıl (veri Haziran'da bitiyor) meşru, model bunu zaten söyler.
            lo, hi = min(dates), max(dates)
            inside = [d for d in dates if expectation.start <= d <= expectation.end]
            if not inside:
                report.gaps.append(f"tablo {lo:%Y-%m} → {hi:%Y-%m} kapsıyor, istenen {expectation.start:%Y-%m} → {expectation.end:%Y-%m} penceresinde gözlem yok")
    for tag in expectation.derivations:
        report.checked.append(f"türetim:{tag}")
        if not _derivation_present(table, tag):
            label = "önceki döneme göre fark kolonu" if tag == "diff" else "yüzde değişim kolonu"
            report.gaps.append(f"istenen {label} tabloda yok ya da girdisiyle tutarlı değil")
    if expectation.series_ids:
        report.checked.append("seri kimlikleri")
        prov = " ".join(provenance_ids)
        sql = " ".join(sql_texts)
        for sid in expectation.series_ids:
            key = sid.split(":", 1)[1] if ":" in sid else sid
            if key not in prov and key not in sql:
                report.gaps.append(f"istenen seri {sid} tabloya girmedi")
    return report


__all__ = ["CompletionReport", "Expectation", "check_completion", "derive_expectation"]
