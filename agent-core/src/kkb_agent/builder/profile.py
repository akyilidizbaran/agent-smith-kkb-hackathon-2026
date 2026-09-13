"""Profilci — bir metin tablosuna bakıp eşleme ve anlam ÖNERİR, kanıtıyla.

Girdi, generic parser'ın ürettiği şeydir: kaynağın kendi kolon adlarıyla bir
**metin** tablosu. Tip çıkarımı yok, tarih yok, sayı yok — ad-hoc yol bunları
bilerek bir insanın beyan etmesini istiyor (`AdhocObservationMapping`, 7 alan;
`_adhoc_record`, 8 alan). Jüri elinde CSV ile geldiğinde o 15 alanı kimse
dolduramaz. Bu modül doldurur — ve her alanın yanına *neden* öyle dediğini yazar.

Kurallar deterministik. Bir kolonun tarih olduğunu söylemek için o kolonun
satırlarının %100'ünün tek bir biçimle ayrışması gerekir; gün/ay ayrımının
veriden yapılamadığı durumda (01/02/2026) öneri BELİRSİZ diye işaretlenir,
tahmin edilmez. Sayı ayrıştırma dilbilgisi yayınlama katmanınınkiyle aynı
(`lakehouse.adhoc.publication._parse_value`): burada geçen, orada da geçer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import median

import pandas as pd

# Tarih biçimleri: ISO önce (belirsizlik yok), sonra Türkçe ve Anglosakson yazımlar.
# Sıra kanıt sırası değil; hangi biçimlerin %100 ayrıştırdığı ölçülür, sonra karar.
DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d", "%Y-%m", "%Y%m%d",
    "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y",
    "%m/%d/%Y", "%m-%d-%Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S",
)
#: Aynı metnin iki farklı tarihe ayrıştığı çiftler: biri doğruysa diğeri yanlış.
AMBIGUOUS_PAIRS: tuple[tuple[str, str], ...] = (("%d/%m/%Y", "%m/%d/%Y"), ("%d-%m-%Y", "%m-%d-%Y"))

SEPARATOR_COMBOS: tuple[tuple[str, str | None], ...] = (
    (".", None), (",", None), (".", ","), (",", "."), (".", " "), (",", " "),
)
"""(ondalık, binlik) adayları. Yayınlama katmanı ayraç TAHMİN ETMEZ; burada
ölçülüp beyan edilir."""

#: Başlıktan birim ipucu — kanıt kaynağı "kolon adı", veri değil.
_UNIT_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"milyon\s*tl|mn\s*tl|try_mn", re.I), "TRY_mn"),
    (re.compile(r"\bbin\s*tl|thousand\s*tl|try_th", re.I), "TRY_th"),
    (re.compile(r"%|yüzde|yuzde|pct|percent", re.I), "pct"),
    (re.compile(r"endeks|index", re.I), "index"),
    (re.compile(r"\badet\b|count|sayısı|sayisi", re.I), "count"),
)


def _parse_number(text: str, decimal: str, thousands: str | None) -> float | None:
    """`_parse_value` dilbilgisinin birebir kopyası. Değişirse burası da değişmeli."""

    text = text.strip()
    if not text:
        return None
    normalized = text
    if thousands and thousands in text:
        group, dec = re.escape(thousands), re.escape(decimal)
        pattern = rf"[+-]?[0-9]{{1,3}}(?:{group}[0-9]{{3}})+(?:{dec}[0-9]+)?(?:[eE][+-]?[0-9]+)?"
        if re.fullmatch(pattern, text) is None:
            raise ValueError("binlik gruplama geçersiz")
        normalized = normalized.replace(thousands, "")
    if decimal == ",":
        if "." in normalized and thousands != ".":
            raise ValueError("ondalık ',' iken '.' var")
        normalized = normalized.replace(",", ".")
    elif "," in normalized:
        raise ValueError("ondalık '.' iken ',' var")
    number = float(normalized)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("sonlu değil")
    return number


def parse_date(text: str, fmt: str) -> date:
    return datetime.strptime(text.strip(), fmt).date()


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    rows: int
    non_empty: int
    distinct: int
    sample: tuple[str, ...]
    #: %100 ayrıştıran tarih biçimleri
    date_formats: tuple[str, ...] = ()
    #: %100 ayrıştıran (ondalık, binlik) çiftleri
    numeric_under: tuple[tuple[str, str | None], ...] = ()
    monotonic_dates: bool = False
    unique_dates: bool = False

    @property
    def null_rate(self) -> float:
        return 0.0 if self.rows == 0 else 1 - self.non_empty / self.rows

    @property
    def date_ambiguous(self) -> bool:
        """Gün/ay ayrımı veriden yapılamıyor: iki karşıt biçim de %100 ayrışıyor."""
        return any(a in self.date_formats and b in self.date_formats for a, b in AMBIGUOUS_PAIRS)


@dataclass(frozen=True)
class TableProfile:
    rows: int
    columns: tuple[ColumnProfile, ...]

    def column(self, name: str) -> ColumnProfile | None:
        return next((c for c in self.columns if c.name == name), None)

    @property
    def date_candidates(self) -> tuple[ColumnProfile, ...]:
        return tuple(c for c in self.columns if c.date_formats and c.non_empty == c.rows)

    @property
    def value_candidates(self) -> tuple[ColumnProfile, ...]:
        return tuple(c for c in self.columns if c.numeric_under and not c.date_formats)

    @property
    def entity_candidates(self) -> tuple[ColumnProfile, ...]:
        """Az kardinaliteli, tarih ve sayı olmayan metin kolonları. Tek değerli olan sabittir."""
        return tuple(
            c for c in self.columns
            if not c.date_formats and not c.numeric_under and 1 < c.distinct <= max(2, self.rows // 2)
        )


def profile_table(frame: pd.DataFrame, *, max_sample: int = 5) -> TableProfile:
    """Her kolonu ölçer. Hiçbir şey yorumlamaz; yalnız 'hangi kurallarla %100 ayrışıyor'."""

    columns: list[ColumnProfile] = []
    rows = int(len(frame))
    for name in frame.columns:
        raw = frame[name]
        texts = [("" if v is None or (isinstance(v, float) and v != v) else str(v).strip()) for v in raw.tolist()]
        non_empty = [t for t in texts if t]
        sample = tuple(dict.fromkeys(non_empty))[:max_sample]

        fmts: list[str] = []
        parsed_dates: list[date] = []
        for fmt in DATE_FORMATS:
            try:
                parsed = [parse_date(t, fmt) for t in non_empty]
            except ValueError:
                continue
            if non_empty:
                fmts.append(fmt)
                if not parsed_dates:
                    parsed_dates = parsed
        # Tamamı boş bir kolon tarih adayı değildir.
        if not non_empty:
            fmts = []

        combos: list[tuple[str, str | None]] = []
        for decimal, thousands in SEPARATOR_COMBOS:
            try:
                for t in non_empty:
                    _parse_number(t, decimal, thousands)
            except ValueError:
                continue
            if non_empty:
                combos.append((decimal, thousands))

        mono = bool(parsed_dates) and all(a < b for a, b in zip(parsed_dates, parsed_dates[1:]))
        uniq = bool(parsed_dates) and len(set(parsed_dates)) == len(parsed_dates)
        columns.append(ColumnProfile(
            name=str(name), rows=rows, non_empty=len(non_empty), distinct=len(set(non_empty)),
            sample=sample, date_formats=tuple(fmts), numeric_under=tuple(combos),
            monotonic_dates=mono, unique_dates=uniq,
        ))
    return TableProfile(rows=rows, columns=tuple(columns))


# ------------------------------------------------------------------------ öneri
@dataclass(frozen=True)
class Evidence:
    field: str
    value: object
    reason: str
    confidence: str  # "strong" | "weak" | "none"


@dataclass(frozen=True)
class MappingProposal:
    """`AdhocObservationMapping` ile aynı alan adları — doğrudan geçirilebilsin diye."""

    series_id: str
    observation_date_column: str
    value_column: str
    date_format: str
    decimal_separator: str
    thousands_separator: str | None
    entity_id_column: str | None
    evidence: tuple[Evidence, ...]
    alternatives: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def ambiguous(self) -> tuple[str, ...]:
        return tuple(e.field for e in self.evidence if e.confidence == "none")


@dataclass(frozen=True)
class SemanticsProposal:
    """`_adhoc_record` alanları. Kanıtsız alan `unknown` / None kalır — dürüst kayıt."""

    frequency: str
    measure_type: str
    unit: str | None
    default_agg: str | None
    week_anchor: str | None
    cumulative_reset: str | None
    evidence: tuple[Evidence, ...]


def _infer_frequency(dates: list[date]) -> tuple[str, str, str]:
    """Ardışık tarih farklarının medyanından frekans. (değer, gerekçe, güven)."""

    if len(dates) < 3:
        return "irregular", f"{len(dates)} tarih; aralık ölçülemez", "none"
    ordered = sorted(set(dates))
    gaps = [(b - a).days for a, b in zip(ordered, ordered[1:])]
    med = median(gaps)
    spread = max(gaps) - min(gaps)
    table = (
        (1, 1, "daily"), (5, 9, "weekly"), (28, 31, "monthly"), (89, 92, "quarterly"), (365, 366, "yearly"),
    )
    for lo, hi, name in table:
        if lo <= med <= hi:
            conf = "strong" if spread <= max(3, hi - lo + 2) else "weak"
            return name, f"ardışık tarih farkı medyanı {med:.0f} gün (min {min(gaps)}, max {max(gaps)})", conf
    return "irregular", f"medyan aralık {med:.0f} gün hiçbir düzenli frekansa oturmuyor", "weak"


def _infer_measure_type(values: list[float], dates: list[date], header: str) -> tuple[str, str, str]:
    """Yalnız veriden görülebilenler; kalanı `unknown`. Katalog sözlüğü: stock, flow_*, rate, ratio, index, count."""

    if not values:
        return "unknown", "sayısal değer yok", "none"
    if re.search(r"endeks|index", header, re.I):
        return "index", "kolon adı endeks diyor", "weak"
    if re.search(r"%|yüzde|yuzde|oran|faiz|rate", header, re.I) and all(-100 <= v <= 1000 for v in values):
        return "rate", "kolon adı oran/faiz diyor ve değerler yüzde ölçeğinde", "weak"
    non_neg = all(v >= 0 for v in values)
    signs_change = any(a > b for a, b in zip(values, values[1:])) and any(a < b for a, b in zip(values, values[1:]))
    if non_neg and all(float(v).is_integer() for v in values) and re.search(r"adet|sayı|count", header, re.I):
        return "count", "tamsayı, negatif yok, kolon adı adet/sayı diyor", "weak"
    if non_neg and not signs_change and len(values) >= 6:
        return "stock", "negatif yok, tek yönlü seyir — bakiye gibi görünüyor; akım da olabilir, onaylanmalı", "weak"
    return "unknown", "veriden ölçüm tipi ayırt edilemiyor (stok mu akım mı)", "none"


def propose(profile: TableProfile, frame: pd.DataFrame, *, series_id: str) -> tuple[MappingProposal | None, SemanticsProposal | None]:
    """Profilden eşleme ve anlam önerisi. Aday yoksa None; belirsizlik varsa işaretli."""

    ev: list[Evidence] = []
    alternatives: dict[str, tuple[str, ...]] = {}

    # --- tarih kolonu
    dates = [c for c in profile.date_candidates]
    if not dates:
        return None, None
    ranked = sorted(dates, key=lambda c: (c.unique_dates, c.monotonic_dates, c.distinct), reverse=True)
    dcol = ranked[0]
    if len(ranked) > 1:
        alternatives["observation_date_column"] = tuple(c.name for c in ranked[1:])
    if dcol.date_ambiguous:
        # İki karşıt biçim de geçiyor: gün ≤ 12. Veriden karar verilemez.
        fmt = dcol.date_formats[0]
        ev.append(Evidence("date_format", fmt, "gün/ay ayrımı veriden yapılamıyor (tüm günler ≤ 12); "
                           f"adaylar {', '.join(f for f in dcol.date_formats)} — kullanıcıya sorulmalı", "none"))
    else:
        fmt = dcol.date_formats[0]
        ev.append(Evidence("date_format", fmt, f"{dcol.non_empty}/{dcol.rows} satır bu biçimle ayrışıyor", "strong"))
    ev.append(Evidence("observation_date_column", dcol.name,
                       f"%100 tarih; {'artan sırada' if dcol.monotonic_dates else 'sıralı değil'}, "
                       f"{'tekil' if dcol.unique_dates else 'tekrarlı tarihler var'}", "strong" if dcol.unique_dates else "weak"))

    # --- değer kolonu
    values = [c for c in profile.value_candidates if c.name != dcol.name]
    if not values:
        return None, None
    ranked_v = sorted(values, key=lambda c: (c.non_empty, c.distinct), reverse=True)
    vcol = ranked_v[0]
    if len(ranked_v) > 1:
        alternatives["value_column"] = tuple(c.name for c in ranked_v[1:])
        ev.append(Evidence("value_column", vcol.name, f"{len(ranked_v)} sayısal kolon var; en dolu olanı seçildi, "
                           f"diğerleri: {', '.join(c.name for c in ranked_v[1:])}", "weak"))
    else:
        ev.append(Evidence("value_column", vcol.name, "tek sayısal kolon", "strong"))
    decimal, thousands = vcol.numeric_under[0]
    if len(vcol.numeric_under) > 1:
        # Birden çok ayraç çifti geçiyorsa (ör. tamsayılar): en sade olanı, gerekçesiyle.
        ev.append(Evidence("decimal_separator", decimal, f"{len(vcol.numeric_under)} ayraç çifti de ayrıştırıyor "
                           "(değerlerde ayraç yok); en sade olan seçildi", "weak"))
    else:
        ev.append(Evidence("decimal_separator", decimal, f"yalnız ondalık={decimal!r} binlik={thousands!r} ile %100 ayrışıyor", "strong"))

    # --- entity
    ents = [c for c in profile.entity_candidates if c.name not in (dcol.name, vcol.name)]
    entity = ents[0].name if len(ents) == 1 else None
    if len(ents) == 1:
        ev.append(Evidence("entity_id_column", entity, f"{ents[0].distinct} farklı değer, metin; tarih başına birden çok satır varsa boyut bu", "weak"))
    elif len(ents) > 1:
        alternatives["entity_id_column"] = tuple(c.name for c in ents)
        ev.append(Evidence("entity_id_column", None, f"birden çok aday: {', '.join(c.name for c in ents)} — seçilmedi", "none"))

    mapping = MappingProposal(
        series_id=series_id, observation_date_column=dcol.name, value_column=vcol.name,
        date_format=fmt, decimal_separator=decimal, thousands_separator=thousands,
        entity_id_column=entity, evidence=tuple(ev), alternatives=alternatives,
    )

    # --- anlam
    parsed_dates = [parse_date(str(t), fmt) for t in frame[dcol.name].tolist() if str(t).strip()]
    parsed_vals: list[float] = []
    for t in frame[vcol.name].tolist():
        n = _parse_number("" if t is None else str(t), decimal, thousands)
        if n is not None:
            parsed_vals.append(n)
    sev: list[Evidence] = []
    freq, why, conf = _infer_frequency(parsed_dates)
    sev.append(Evidence("frequency", freq, why, conf))
    mt, why, conf = _infer_measure_type(parsed_vals, parsed_dates, vcol.name)
    sev.append(Evidence("measure_type", mt, why, conf))
    unit = next((u for pat, u in _UNIT_HINTS if pat.search(vcol.name)), None)
    sev.append(Evidence("unit", unit, "kolon adından" if unit else "birim veriden çıkarılamaz; kaynak belgesi ya da kullanıcı söylemeli", "weak" if unit else "none"))
    default_agg = {"stock": "last", "count": "last", "rate": "avg", "index": "last"}.get(mt)
    semantics = SemanticsProposal(
        frequency=freq, measure_type=mt, unit=unit, default_agg=default_agg,
        week_anchor=None, cumulative_reset=None, evidence=tuple(sev),
    )
    return mapping, semantics


__all__ = [
    "AMBIGUOUS_PAIRS", "DATE_FORMATS", "SEPARATOR_COMBOS",
    "ColumnProfile", "Evidence", "MappingProposal", "SemanticsProposal", "TableProfile",
    "parse_date", "profile_table", "propose",
]
