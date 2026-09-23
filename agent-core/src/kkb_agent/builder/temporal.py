"""Generic temporal semantics and safe frequency normalization.

The parser in :mod:`builder.tabular` answers *how a file is shaped*.  This
module answers the separate question *what one row means in time*.  It is
domain-neutral by design: no provider, finance, or source-specific column name
is required.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Any

import pandas as pd

FREQUENCIES = ("daily", "weekly", "monthly", "quarterly", "yearly", "irregular", "unknown")
MEASURE_TYPES = ("FLOW", "STOCK", "RATIO", "RATE", "INDEX", "COUNT", "AVERAGE", "UNKNOWN")

# Dışa aktarımların alt toplam satırı ("Toplam", "Genel Toplam", "Total"): dönem değildir, dönüşüme girmez.
_FOOTER_LABEL = re.compile(r"^\s*(?:genel\s+)?(?:toplam|total|grand\s+total)\s*:?\s*$", re.I)

_INTERVAL = re.compile(
    r"^(?:(?P<code>\d{4})[/-](?P<week>\d{1,2})\s*)?"
    r"\(?\s*(?P<start>\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s*[-–—]\s*"
    r"(?P<end>\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s*\)?$"
)
_CODE_INTERVAL = re.compile(
    r"^(?P<code>\d{4})[/-](?P<week>\d{1,2})\s*\(\s*"
    r"(?P<start>\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s*[-–—]\s*"
    r"(?P<end>\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s*\)?$"
)
_WEEK = re.compile(r"^(?P<year>\d{4})[-/]?[Ww](?P<week>\d{1,2})$")
_QUARTER = re.compile(r"^(?P<year>\d{4})[-/]?[Qq](?P<quarter>[1-4])$")
_YEAR = re.compile(r"^(?P<year>\d{4})$")
_MONTH = re.compile(r"^(?P<year>\d{4})(?:[-/](?P<month>0?[1-9]|1[0-2]))$")
_COMPACT_MONTH = re.compile(r"^(?P<year>\d{4})(?P<month>0[1-9]|1[0-2])$")
_DATE = re.compile(r"^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}(?:[ T].*)?$")
_PERIOD_NAME = re.compile(r"tarih|dönem|donem|period|date|month|ay|week|hafta|quarter|çeyrek|yıl|yil|year", re.IGNORECASE)
_MONTH_WORD = re.compile(r"aylık|aylik|her ay|monthly|month", re.IGNORECASE)
_PERSIST = re.compile(r"lakehouse|veri\s*havuz|katalo(?:ğ|g)a|kalıcı|kalici|persist|ingest|kaydet", re.IGNORECASE)
_ENRICH = re.compile(r"zenginleştir|zenginlestir|mevcut .*birleştir|mevcut .*ekle|hizala|enrich|join", re.IGNORECASE)

# Bir akım kelimesini toplanamaz kılan niteleyiciler. `_fold_label` çıktısı üzerinde eşleşir,
# yani küçük harf ve aksansız biçimler yazılır ("başına" değil "basina").
_PER_UNIT = re.compile(r"fiyat|price|ortalama|average|\bmean\b|medyan|median|birim|unit|basina|\bper\b|\bkur\b|\bkuru\b")


class TemporalNormalizationError(ValueError):
    """A safe, user-actionable temporal decision could not be made."""

    def __init__(self, message: str, *, code: str = "TEMPORAL_NORMALIZATION_FAILED", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class PeriodValue:
    raw: str
    start: date
    end: date
    frequency: str
    period_code: str | None = None


@dataclass(frozen=True)
class TemporalSemantics:
    period_column: str | None
    frequency: str
    confidence: str
    evidence: tuple[str, ...]
    parsed: tuple[PeriodValue, ...] = ()
    coverage_start: date | None = None
    coverage_end: date | None = None


@dataclass(frozen=True)
class MeasureSemantics:
    column: str
    measure_type: str
    confidence: str
    evidence: tuple[str, ...] = ()
    additive: bool = False


@dataclass(frozen=True)
class NormalizationMetadata:
    source_frequency: str
    requested_frequency: str
    source_confidence: str
    aggregation_method: dict[str, str]
    period_parser: str
    canonical_time_key: str
    rows_before: int
    rows_after: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizationResult:
    frame: pd.DataFrame
    metadata: NormalizationMetadata
    temporal: TemporalSemantics
    measures: tuple[MeasureSemantics, ...]


@dataclass(frozen=True)
class CompletionReport:
    status: str
    missing_columns: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.status == "COMPLETE"


def _parse_dmy(value: str) -> date:
    value = value.strip().replace("/", ".").replace("-", ".")
    parts = value.split(".")
    if len(parts[-1]) == 2:
        year = int(parts[-1]) + (2000 if int(parts[-1]) < 70 else 1900)
        return date(year, int(parts[1]), int(parts[0]))
    return date(int(parts[2]), int(parts[1]), int(parts[0]))


def parse_period(value: Any) -> PeriodValue | None:
    """Parse common period/date spellings without asking an LLM."""
    # Gold tablolarının kanıt sütunları (gözlem tarihleri listesi vb.) liste/dizi taşır; bunlar dönem değildir.
    if isinstance(value, (list, tuple, set, dict)) or hasattr(value, "__array__") and not isinstance(value, (str, bytes)) \
            and getattr(value, "ndim", 0) > 0:
        return None
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    match = _CODE_INTERVAL.fullmatch(raw) or _INTERVAL.fullmatch(raw)
    if match and match.group("start") and match.group("end"):
        start, end = _parse_dmy(match.group("start")), _parse_dmy(match.group("end"))
        if end < start:
            return None
        code = match.group("code")
        week = match.group("week")
        period_code = f"{code}/{int(week):02d}" if code and week else None
        return PeriodValue(raw, start, end, "weekly", period_code)
    match = _WEEK.fullmatch(raw)
    if match:
        year, week = int(match.group("year")), int(match.group("week"))
        try:
            start = date.fromisocalendar(year, week, 1)
        except ValueError:
            return None
        return PeriodValue(raw, start, start + timedelta(days=6), "weekly", f"{year}-W{week:02d}")
    match = _QUARTER.fullmatch(raw)
    if match:
        year, quarter = int(match.group("year")), int(match.group("quarter"))
        month = (quarter - 1) * 3 + 1
        end_month = month + 2
        return PeriodValue(raw, date(year, month, 1), date(year, end_month, calendar.monthrange(year, end_month)[1]), "quarterly", raw)
    match = _COMPACT_MONTH.fullmatch(raw) or _MONTH.fullmatch(raw)
    if match:
        year, month = int(match.group("year")), int(match.group("month"))
        return PeriodValue(raw, date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]), "monthly", raw)
    match = _YEAR.fullmatch(raw)
    if match:
        year = int(match.group("year"))
        return PeriodValue(raw, date(year, 1, 1), date(year, 12, 31), "yearly", raw)
    if _DATE.fullmatch(raw):
        parsed = pd.to_datetime(raw, errors="coerce", dayfirst=not raw[:4].isdigit())
        if not pd.isna(parsed):
            point = parsed.date()
            return PeriodValue(raw, point, point, "daily", raw)
    return None


def canonical_month(value: Any) -> str | None:
    parsed = parse_period(value)
    if parsed is None:
        if isinstance(value, (pd.Timestamp, datetime, date)):
            return f"{value.year:04d}-{value.month:02d}"
        return None
    return f"{parsed.start.year:04d}-{parsed.start.month:02d}"


def _frequency_from_gaps(parsed: list[PeriodValue]) -> tuple[str, str, str]:
    if not parsed:
        return "unknown", "low", "no period values parsed"
    explicit = {p.frequency for p in parsed}
    if len(explicit) == 1 and "weekly" in explicit:
        return "weekly", "high", "interval/week representation and recurring 5–7 day periods"
    if len(explicit) == 1 and explicit != {"daily"}:
        return next(iter(explicit)), "high", f"explicit {next(iter(explicit))} period representation"
    starts = sorted({p.start for p in parsed})
    gaps = [(b - a).days for a, b in pairwise(starts)]
    if not gaps:
        return "unknown", "low", "too few distinct periods"
    median = float(pd.Series(gaps).median())
    if median <= 1.5:
        return "daily", "high", f"median date gap {median:g} day"
    if median <= 8:
        return "weekly", "high", f"median date gap {median:g} days"
    if median <= 31.5:
        return "monthly", "high", f"median date gap {median:g} days"
    if median <= 93:
        return "quarterly", "high", f"median date gap {median:g} days"
    if median <= 370:
        return "yearly", "medium", f"median date gap {median:g} days"
    return "irregular", "low", f"median date gap {median:g} days is irregular"


def infer_temporal(frame: pd.DataFrame, period_column: str | None = None) -> TemporalSemantics:
    candidates = [period_column] if period_column else []
    if not candidates:
        candidates = [str(c) for c in frame.columns if _PERIOD_NAME.search(str(c))]
    candidates += [str(c) for c in frame.columns if str(c) not in candidates]
    best: tuple[int, str, list[PeriodValue], int] | None = None
    for column in candidates:
        if column not in frame.columns:
            continue
        # Alt toplam satırı ("Toplam") dönem değildir; ekseni değerlendirirken sayılmaz.
        values = [v for v in frame[column].tolist() if not (v is not None and _FOOTER_LABEL.match(str(v)))]
        parsed = [p for p in (parse_period(v) for v in values) if p is not None]
        if not parsed:
            continue
        score = len(parsed) * 2 + (len(parsed) == len(values)) * 20 + (_PERIOD_NAME.search(str(column)) is not None) * 10
        if best is None or score > best[0]:
            best = (score, str(column), parsed, len(values))
    if best is None:
        return TemporalSemantics(period_column=None, frequency="unknown", confidence="low",
                                 evidence=("no column was parsed as a temporal axis",))
    _, column, parsed, period_rows = best
    frequency, confidence, evidence = _frequency_from_gaps(parsed)
    if len(parsed) < period_rows:
        confidence = "low"
        evidence += f"; {period_rows - len(parsed)} rows were not parsed"
    return TemporalSemantics(
        period_column=column, frequency=frequency, confidence=confidence, evidence=(evidence,),
        parsed=tuple(parsed), coverage_start=min(p.start for p in parsed), coverage_end=max(p.end for p in parsed),
    )


def requested_frequency(text: str) -> str | None:
    if _MONTH_WORD.search(text or ""):
        return "monthly"
    if re.search(r"haftal[ıi]k|weekly|her hafta", text or "", re.IGNORECASE):
        return "weekly"
    if re.search(r"günlük|gunluk|daily|her gün|her gun", text or "", re.IGNORECASE):
        return "daily"
    if re.search(r"çeyreklik|ceyreklik|quarterly|her çeyrek", text or "", re.IGNORECASE):
        return "quarterly"
    if re.search(r"yıllık|yillik|yearly|annual|her yıl|her yil", text or "", re.IGNORECASE):
        return "yearly"
    return None


def requested_months_from_text(text: str) -> list[str]:
    """Extract an explicit inclusive YYYYMM/month range when the user gives one."""
    matches = re.findall(r"(?<!\d)(\d{4})(?:[-/])?(0[1-9]|1[0-2])(?!\d)", text or "")
    if len(matches) < 2:
        return []
    start_year, start_month = map(int, matches[0])
    end_year, end_month = map(int, matches[-1])
    if (end_year, end_month) < (start_year, start_month):
        return []
    months: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def prefer_native_source(candidates: Iterable[TemporalSemantics], requested: str) -> int | None:
    """Return the first native-grain candidate, otherwise ``None``.

    The caller may then choose a safe conversion path.  Keeping this decision
    outside the parser makes the native-source preference reusable for files,
    API responses, and catalog candidates.
    """
    for index, candidate in enumerate(candidates):
        if candidate.frequency == requested and candidate.confidence != "low":
            return index
    return None


def persistence_intent(text: str) -> str:
    return "PERSIST_TO_LAKEHOUSE" if _PERSIST.search(text or "") else "SESSION_ONLY"


def enrichment_intent(text: str) -> bool:
    return bool(_ENRICH.search(text or ""))


def infer_measure_semantics(column: str, *, metadata: Mapping[str, Any] | None = None) -> MeasureSemantics:
    if metadata and column in metadata:
        value = str(metadata[column]).upper()
        if value in MEASURE_TYPES:
            return MeasureSemantics(column, value, "high", ("declared metadata",), value in {"FLOW", "COUNT"})
    label = _fold_label(column)
    if re.search(r"(?:gunluk|haftalik|daily|weekly|per\s+day|is\s+gunu)\s+(?:ortalama|average|mean|avg)|"
                 r"(?:ortalama|average|mean)\s+(?:gunluk|daily)", label):
        # "Günlük Ortalama İşlem Hacmi": zaman başına ortalama toplanmaz; aylığa iş günü ağırlıklı ortalamayla iner
        # (gün ağırlığı bu tanımda kesindir). Zaman birimi söylenmeyen "Ortalama Tutar" işlem başına olabilir; gün
        # ağırlığı yanlış olur, aşağıdaki akım kuralı onu güvenli kural yok (UNKNOWN) tarafına düşürür.
        return MeasureSemantics(column, "AVERAGE", "medium", ("column label indicates a per-time average",))
    if re.search(r"faiz|interest|%|rate", label):
        return MeasureSemantics(column, "RATE", "medium", ("column label indicates a rate",))
    if re.search(r"ratio|rasyo|payı|payi|oran", label):
        return MeasureSemantics(column, "RATIO", "medium", ("column label indicates a ratio",))
    if re.search(r"endeks|index|cpi|tüfe|tufe", label):
        return MeasureSemantics(column, "INDEX", "medium", ("column label indicates an index",))
    if re.search(r"bakiye|balance|stock|mevduat|kredi stoku", label):
        return MeasureSemantics(column, "STOCK", "medium", ("column label indicates a balance/stock",))
    if re.search(r"adet|count|sayı|sayi", label):
        return MeasureSemantics(column, "COUNT", "medium", ("column label indicates a count",), True)
    if re.search(r"hacim|volume|satış|satis|revenue|gelir|tutar|amount|işlem|islem|flow|inflow|outflow", label):
        # Akım kelimesi tek başına toplanabilirliği kanıtlamaz: "İşlem Fiyatı" da "Ortalama Tutar"
        # da bu kalıba uyar ama toplanırsa anlamsız bir sayı çıkar. Niteleyici varsa kapalı tarafa
        # düşülür; yanlış toplamaktansa "güvenli kural yok" deyip ham tabloyu göstermek yeğdir.
        if _PER_UNIT.search(label):
            return MeasureSemantics(column, "UNKNOWN", "low",
                                    ("additive keyword is qualified by a per-unit/average word",))
        return MeasureSemantics(column, "FLOW", "medium", ("column label indicates an additive flow/amount",), True)
    return MeasureSemantics(column, "UNKNOWN", "low", ("no conservative semantic label match",))


def _fold_label(value: Any) -> str:
    """Make label matching stable for Turkish dotted-I and accents."""
    text = unicodedata.normalize("NFKD", str(value).lower())
    return "".join(char for char in text if not unicodedata.combining(char))


def _number(value: Any) -> float:
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError as exc:
        # Boş ya da sayı olmayan hücre bu modülün diğer belirsizlikleri gibi ele alınır: çıplak
        # ValueError çağıranın `TemporalNormalizationError` yakalamasından kaçıp aracı düşürüyordu.
        # Eksik günü atlayıp toplamayı sürdürmek ayı olduğundan küçük gösterirdi, o yüzden kapalı
        # tarafa düşülür ve ham tablo gösterilir.
        raise TemporalNormalizationError(
            f"sayıya çevrilemeyen değer: {str(value)!r}",
            code="VALUE_PARSE_FAILED",
            details={"value": str(value)},
        ) from exc


def _canonical_key(period: PeriodValue, frequency: str) -> str:
    if frequency == "daily":
        return period.start.isoformat()
    if frequency == "weekly":
        iso = period.start.isocalendar()
        return period.period_code or f"{iso.year}-W{iso.week:02d}"
    if frequency == "monthly":
        return f"{period.start.year:04d}-{period.start.month:02d}"
    if frequency == "quarterly":
        return f"{period.start.year:04d}-Q{((period.start.month - 1) // 3) + 1}"
    if frequency == "yearly":
        return f"{period.start.year:04d}"
    return period.raw


def project_columns(frame: pd.DataFrame, *, period_column: str, requested_columns: Iterable[str] | None = None) -> pd.DataFrame:
    columns = [period_column, *(requested_columns or [c for c in frame.columns if c != period_column])]
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise TemporalNormalizationError(f"istenen kolonlar tabloda yok: {', '.join(missing)}", code="REQUESTED_COLUMN_NOT_FOUND")
    return frame.loc[:, list(dict.fromkeys(columns))].copy()


def requested_columns_from_text(frame: pd.DataFrame, text: str, *, period_column: str) -> list[str] | None:
    """Select explicitly named measures without leaking helper columns.

    Full/near-full normalized label matches are intentionally conservative. If
    the question does not name a measure, ``None`` means the caller should keep
    the source columns rather than guess what the user wanted.
    """
    normalized_text = re.sub(r"[^a-z0-9 ]+", " ", _fold_label(text))
    selected: list[str] = []
    for column in frame.columns:
        if column == period_column:
            continue
        label = re.sub(r"[^a-z0-9 ]+", " ", _fold_label(column)).strip()
        tokens = [token for token in label.split() if len(token) > 2]
        if label and label in normalized_text:
            selected.append(str(column))
            continue
        if tokens and len(tokens) >= 2 and sum(token in normalized_text for token in tokens) >= len(tokens) - 1:
            selected.append(str(column))
    return selected or None


def _business_days(start: date, end: date) -> list[date]:
    days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    weekdays = [d for d in days if d.weekday() < 5]
    return weekdays or days


def _month_allocation(period: PeriodValue) -> dict[str, int]:
    """Dönem BAŞLADIĞI aya yazılır: {'2021-03': 5} (29.03–02.04 haftası Mart'tır).

    Kaynağın kendi aylık raporu da haftayı başladığı aya sayar (TEFAS, 23 Eyl beklenen çıktı: Ocak 2021 = Ocak'ta başlayan
    dört hafta). Değer günlere bölünmez; bölüştürme kaynağın yayımlamadığı bir günlük dağılım varsayardı."""
    key = f"{period.start.year:04d}-{period.start.month:02d}"
    return {key: len(_business_days(period.start, period.end))}


def _weekdays_in_month(month: str) -> int:
    year, number = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(year, number)[1]
    return len(_business_days(date(year, number, 1), date(year, number, last)))


def normalize_frequency(
    frame: pd.DataFrame,
    *,
    temporal: TemporalSemantics | None = None,
    requested: str,
    period_column: str | None = None,
    requested_columns: Iterable[str] | None = None,
    measure_metadata: Mapping[str, Any] | None = None,
) -> NormalizationResult:
    if requested not in FREQUENCIES or requested in {"unknown", "irregular"}:
        raise TemporalNormalizationError(f"hedef frekans desteklenmiyor: {requested}", code="TEMPORAL_GRAIN_AMBIGUOUS")
    temporal = temporal or infer_temporal(frame, period_column)
    if temporal.period_column is None or temporal.confidence == "low":
        raise TemporalNormalizationError("zaman ekseni güvenle çözülemedi", code="TEMPORAL_GRAIN_AMBIGUOUS")
    if temporal.frequency == "unknown":
        raise TemporalNormalizationError("kaynak frekansı bilinmiyor", code="TEMPORAL_GRAIN_AMBIGUOUS")
    period_column = temporal.period_column
    source = project_columns(frame, period_column=period_column, requested_columns=requested_columns)
    footer = source[period_column].map(lambda v: bool(_FOOTER_LABEL.match(str(v))) if v is not None else False)
    warnings: list[str] = []
    if footer.any():
        warnings.append(f"{int(footer.sum())} alt toplam satırı (ör. 'Toplam') dönem sayılmadı ve dışarıda bırakıldı")
        source = source.loc[~footer].reset_index(drop=True)
    parsed_by_row = [parse_period(v) for v in source[period_column].tolist()]
    if any(p is None for p in parsed_by_row):
        raise TemporalNormalizationError("tüm dönem değerleri çözülemedi", code="PERIOD_PARSE_FAILED")
    parsed = [p for p in parsed_by_row if p is not None]
    keys = [_canonical_key(p, requested) for p in parsed]
    methods: dict[str, str] = {}
    measures = tuple(infer_measure_semantics(c, metadata=measure_metadata) for c in source.columns if c != period_column)
    if temporal.frequency == requested:
        if len(set(keys)) != len(keys):
            raise TemporalNormalizationError("kaynakta hedef frekansta yinelenen dönemler var", code="DUPLICATE_PERIOD_KEY")
        out = source.copy()
        key_column = "period_month" if requested == "monthly" else f"period_{requested}"
        out[key_column] = keys
        out = out[[key_column, *[c for c in out.columns if c != period_column and c != key_column]]]
        for measure in measures:
            methods[measure.column] = "native"
    else:
        if requested != "monthly":
            raise TemporalNormalizationError("yalnız güvenli aylık dönüşüm yolu etkin", code="UNSAFE_FREQUENCY_CONVERSION")
        if temporal.frequency not in {"daily", "weekly"}:
            raise TemporalNormalizationError(f"{temporal.frequency} → monthly dönüşümü için güvenli kural yok",
                                             code="UNSAFE_FREQUENCY_CONVERSION")
        # Her dönem BAŞLADIĞI aya yazılır (ör. 29.03–02.04 haftası Mart'tır; bölüştürülmez). Toplanabilir tutar
        # toplanır, ortalama/oran iş günü ağırlıklı ortalanır, stok/endeks ayın en son biten dönemidir. Aylar
        # takvim sırasıyla kurulur ve stok dönem sonuna göre seçilir; dosyanın satır sırası sonucu değiştirmez.
        allocations = [_month_allocation(period) for period in parsed]
        months = sorted({month for allocation in allocations for month in allocation})
        crossing = sum(1 for period in parsed if (period.start.year, period.start.month) != (period.end.year, period.end.month))
        if crossing:
            warnings.append(f"{crossing} dönem ay sınırını aşıyor; her dönem başladığı aya yazıldı (bölüştürülmedi), "
                            "ortalamalar iş günü ağırlıklı alındı")
        # Eksik kapsam yalnız uç aylarda anlamlıdır: dönemler başladıkları aya yazıldığı için ara aylarda gün sayısı
        # dalgalanır ama veri eksik değildir. İlk dönem ayın ilk haftasından sonra başlıyorsa ilk ay, son dönem ayın son
        # haftasından önce bitiyorsa son ay eksik sayılır.
        first, last = min(parsed, key=lambda p: p.start), max(parsed, key=lambda p: p.end)
        partial = []
        if first.start.day > 7:
            partial.append(f"{first.start.year:04d}-{first.start.month:02d}")
        last_key = f"{last.start.year:04d}-{last.start.month:02d}"
        last_day = calendar.monthrange(last.end.year, last.end.month)[1]
        if (last.end.year, last.end.month) != (last.start.year, last.start.month):
            pass   # son dönem başladığı aya yazıldı; o ayın kapsamı tamdır
        elif last.end.day < last_day - 6:
            partial.append(last_key)
        if partial:
            warnings.append("kapsamı eksik aylar (kaynak bu ayların yalnız bir kısmını içeriyor): " + ", ".join(partial))
        values: dict[str, list[Any]] = {"period_month": months}
        for measure in measures:
            series = [_number(v) if v is not None else None for v in source[measure.column].tolist()]
            column_values: list[Any] = []
            if measure.measure_type == "FLOW" or (measure.measure_type == "COUNT" and measure.additive):
                for month in months:
                    parts = [(series[i], allocation[month], sum(allocation.values()))
                             for i, allocation in enumerate(allocations) if month in allocation]
                    column_values.append(None if any(v is None for v, _, _ in parts)
                                         else sum(v * days / total for v, days, total in parts))
                methods[measure.column] = "sum_by_period_start_month" if crossing else "sum"
            elif measure.measure_type in {"AVERAGE", "RATE"}:
                for month in months:
                    parts = [(series[i], allocation[month]) for i, allocation in enumerate(allocations) if month in allocation]
                    weight = sum(days for _, days in parts)
                    column_values.append(None if any(v is None for v, _ in parts) or not weight
                                         else sum(v * days for v, days in parts) / weight)
                methods[measure.column] = "business_day_weighted_mean"
            elif measure.measure_type in {"STOCK", "INDEX"}:
                for month in months:
                    ending = [i for i, period in enumerate(parsed) if f"{period.end.year:04d}-{period.end.month:02d}" == month]
                    column_values.append(series[max(ending, key=lambda i: parsed[i].end)] if ending else None)
                methods[measure.column] = "last_period_end"
            else:
                raise TemporalNormalizationError(
                    f"'{measure.column}' için {measure.measure_type} semantiğiyle güvenli toplulaştırma yok",
                    code="MEASURE_SEMANTICS_AMBIGUOUS",
                )
            values[measure.column] = column_values
        out = pd.DataFrame(values)
    key_column = "period_month" if requested == "monthly" else f"period_{requested}"
    out.attrs["temporal_normalization"] = NormalizationMetadata(
        source_frequency=temporal.frequency, requested_frequency=requested,
        source_confidence=temporal.confidence, aggregation_method=methods,
        period_parser="deterministic_period_parser", canonical_time_key=key_column,
        rows_before=len(frame), rows_after=len(out), warnings=tuple(warnings),
    )
    return NormalizationResult(out, out.attrs["temporal_normalization"], temporal, measures)


def enrich_frames(left: pd.DataFrame, right: pd.DataFrame, *, left_period: str, right_period: str,
                  columns: Iterable[str], description: str = "temporal enrichment") -> tuple[pd.DataFrame, dict[str, Any]]:
    if left_period not in left.columns or right_period not in right.columns:
        raise TemporalNormalizationError("enrichment dönem kolonu bulunamadı", code="JOIN_KEY_NOT_FOUND")
    columns = list(columns)
    missing = [c for c in columns if c not in right.columns]
    if missing:
        raise TemporalNormalizationError(f"enrichment kolonları bulunamadı: {', '.join(missing)}", code="REQUESTED_COLUMN_NOT_FOUND")
    lkeys = [canonical_month(v) for v in left[left_period].tolist()]
    rkeys = [canonical_month(v) for v in right[right_period].tolist()]
    if any(k is None for k in lkeys + rkeys):
        raise TemporalNormalizationError("enrichment dönem anahtarı çözülemedi", code="JOIN_KEY_INVALID")
    if len(set(rkeys)) != len(rkeys):
        raise TemporalNormalizationError("sağ kaynakta yinelenen dönem anahtarı var; many-to-many join yapılmadı",
                                         code="DUPLICATE_JOIN_KEY")
    if len(set(lkeys)) != len(lkeys):
        raise TemporalNormalizationError("mevcut workspace bir dönem için birden çok satır içeriyor; otomatik enrichment durduruldu",
                                         code="DUPLICATE_WORKSPACE_KEY")
    if set(columns) & set(left.columns):
        raise TemporalNormalizationError("enrichment kolonları mevcut workspace kolonlarını eziyor", code="COLUMN_EXISTS")
    lookup = right.copy()
    canonical_column = "__canonical_period_month__"
    lookup[canonical_column] = rkeys
    lookup = lookup.set_index(canonical_column)
    out = left.copy()
    for column in columns:
        out[column] = [lookup.loc[key, column] if key in lookup.index else pd.NA for key in lkeys]
    metadata = {
        "description": description, "canonical_time_key": "YYYY-MM",
        "join_cardinality": "one_to_one", "rows_before": len(left), "rows_after": len(out),
        "matched_rows": sum(key in lookup.index for key in lkeys),
        "missing_rows": sum(key not in lookup.index for key in lkeys),
        "columns_added": columns,
    }
    out.attrs["temporal_enrichment"] = metadata
    return out, metadata


def validate_completion(*, requested_frequency: str | None, result_frequency: str | None,
                        requested_columns: Iterable[str] = (), result_columns: Iterable[str] = (),
                        requested_months: Iterable[str] = (), result_months: Iterable[str] = (),
                        enrichment_requested: bool = False, join_completed: bool = False,
                        persistence_requested: bool = False, persistence_state: str = "SESSION_ONLY") -> CompletionReport:
    failures: list[str] = []
    missing = tuple(c for c in requested_columns if c not in set(result_columns))
    if missing:
        failures.append("requested columns missing: " + ", ".join(missing))
    if requested_frequency and requested_frequency != result_frequency:
        failures.append(f"frequency mismatch: requested {requested_frequency}, result {result_frequency}")
    absent = tuple(m for m in requested_months if m not in set(result_months))
    if absent:
        failures.append("requested periods missing: " + ", ".join(absent[:5]))
    if enrichment_requested and not join_completed:
        failures.append("workspace enrichment was requested but join did not complete")
    if persistence_requested and persistence_state not in {"DRAFT", "PROMOTED", "PERSISTED"}:
        failures.append(f"persistence requested but state is {persistence_state}")
    return CompletionReport("COMPLETE" if not failures else "PARTIAL", missing, tuple(failures))


__all__ = [
    "FREQUENCIES",
    "MEASURE_TYPES",
    "CompletionReport",
    "MeasureSemantics",
    "NormalizationMetadata",
    "NormalizationResult",
    "PeriodValue",
    "TemporalNormalizationError",
    "TemporalSemantics",
    "canonical_month",
    "enrich_frames",
    "enrichment_intent",
    "infer_measure_semantics",
    "infer_temporal",
    "normalize_frequency",
    "parse_period",
    "persistence_intent",
    "prefer_native_source",
    "project_columns",
    "requested_columns_from_text",
    "requested_frequency",
    "requested_months_from_text",
    "validate_completion",
]
