"""Deterministic multi-turn intent hints for the Agent harness.

The LLM remains responsible for choosing a catalog-backed tool call.  This
module only records explicit constraints from the current question and
selectively carries forward confirmed constraints from the same agent
session.  It never creates SQL, performs resampling, or invents a series id.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

CONTEXT_FIELDS = (
    "domain",
    "source",
    "metric",
    "series",
    "entity",
    "geography",
    "date_range",
    "frequency",
    "aggregation",
    "comparison_target",
)

_YEAR = re.compile(
    r"\b((?:19\d{2}|20\d{2}))(?:['’]?(?:döneminde|doneminde|yılında|yilinda|"
    r"yılı|yili|den|dan|ten|tan|de|da|te|ta))?\b",
    re.IGNORECASE,
)
# Compact month ranges (for example ``YYYYMM–YYYYMM``) are an explicit
# current-turn scope.  They must override a previous workspace's date range;
# otherwise the verified-workspace fast path would reuse the stale table.
_COMPACT_MONTH_RANGE = re.compile(
    r"\b((?:19|20)\d{2})(0[1-9]|1[0-2])\s*(?:[-–—→]|->|ile|ve)\s*"
    r"((?:19|20)\d{2})(0[1-9]|1[0-2])\b",
    re.IGNORECASE,
)
_COMPARISON = re.compile(r"karşılaştır|karsilastir|kıyasla|kiyasla|\bvs\b|\bgöre\b|gore", re.IGNORECASE)
_FOLLOW_UP = re.compile(
    r"\b(peki|aynı|ayni|bunu|buna|onu|şunu|sunu|diğeri|digeri|ikisini|önceki|onceki|"
    r"burada|böyle|boyle|yap|çevir|cevir|değiştir|degistir)\b|"
    r"karşılaştır|karsilastir|kıyasla|kiyasla|\bhaftalık\b|\baylık\b|\bçeyreklik\b|\byıllık\b|"
    r"\bweekly\b|\bmonthly\b|\bquarterly\b|\byearly\b|\bchanges?\b|\bdiffs?\b",
    re.IGNORECASE,
)
_REFERENCE = re.compile(r"\b(onu|bunu|şunu|sunu|diğerini|digerini|diğerine|digerine|"
                        r"diğeri|digeri|aynısını|aynisini)\b", re.IGNORECASE)
_FREQUENCY = (
    ("weekly", re.compile(r"\bhaftalık|hafta bazında|weekly\b", re.IGNORECASE)),
    ("monthly", re.compile(r"\baylık|ay bazında|monthly\b", re.IGNORECASE)),
    ("quarterly", re.compile(r"\bçeyreklik|ceyrek|quarterly\b", re.IGNORECASE)),
    ("yearly", re.compile(r"\byıllık|yillik|yıl bazında|yil bazinda|yearly\b", re.IGNORECASE)),
    ("daily", re.compile(r"\bgünlük|gunluk|daily\b", re.IGNORECASE)),
)
_AGGREGATION = (
    ("average", re.compile(r"(?:ortalama|average|mean)\b", re.IGNORECASE)),
    ("sum", re.compile(r"(?:toplam|sum)\b", re.IGNORECASE)),
    # `min`/`max` must be whole words: an unbounded `min` matched the
    # `min` in Turkish words such as `döneminde`, turning a plain follow-up
    # into a false minimum request.
    ("minimum", re.compile(r"(?:en düşük|en dusuk|minimum|min)\b", re.IGNORECASE)),
    ("maximum", re.compile(r"(?:en yüksek|en yuksek|maksimum|max)\b", re.IGNORECASE)),
)
_DOMAIN_TERMS = {
    "finance": ("finans", "finansal", "kredi", "banka", "döviz", "doviz", "kur", "faiz"),
    "health": ("sağlık", "saglik", "hastane", "muayene", "acil", "doktor"),
    "transport": ("ulaşım", "ulasim", "trafik", "taşıt", "tasit", "sefer", "otobüs", "otobus"),
}
_GENERIC_METRICS = (
    "konut kredisi",
    "konut kredileri",
    "dolar",
    "usd",
    "tüfe",
    "tufe",
    "enflasyon",
    "başvuru",
    "basvuru",
    "hastane",
    "kredi",
)
_GEO_COLUMN = re.compile(r"il|şehir|sehir|province|district|location|region|bölge|bolge", re.IGNORECASE)
_PERCENT_CHANGE = re.compile(r"%|yüzde|yuzde|percent(?:age)?|pct|growth\s+rate|büyüme\s+hızı|buyume\s+hizi", re.IGNORECASE)
_NON_SERIES_TERMS = frozenset({
    "daily",
    "günlük",
    "gunluk",
    "monthly",
    "aylık",
    "aylik",
    "quarterly",
    "çeyreklik",
    "ceyreklik",
    "weekly",
    "haftalık",
    "haftalik",
    "yearly",
    "yıllık",
    "yillik",
})
_PERIOD_CHANGE = re.compile(
    r"bir\s+önceki\s+(?:aya|döneme|doneme|haftaya|çeyreğe|ceyrege|yıla|yila)\s+göre|"
    r"önceki\s+(?:aya|döneme|doneme|haftaya|çeyreğe|ceyrege|yıla|yila)|"
    r"aylık\s+(?:değişim|degisim)|period[-\s]+over[-\s]+period|"
    r"(?:monthly|weekly|quarterly|yearly)\s+changes?|"
    r"değişim(?:i|ini|leri|lerini)?|degisim(?:i|ini|leri|lerini)?|"
    r"fark(?:ı|i|ını|ini)?|\bchanges?\b|\bdiffs?\b|\bgrowth\b",
    re.IGNORECASE,
)

# Catalog tags and column aliases often contain standalone frequency/schema
# words. They are useful facets, but never identify a concrete series by
# themselves; allowing them into `_best_match` makes a follow-up containing
# "aylık" bind to the first monthly Gold table in catalog order.
_GENERIC_SERIES_TERMS = frozenset({
    "ay", "aylik", "monthly", "hafta", "haftalik", "weekly", "ceyrek", "ceyreklik", "quarterly",
    "yil", "yillik", "yearly", "donem", "tarih", "date", "veri", "veriler", "seri", "seriler",
    "degisim", "degisimleri", "bakiye", "bakiyeler", "analiz", "tablo", "tablolar",
})
_ACTIVE_TABLE_REFERENCE = re.compile(
    r"\b(?:mevcut|aktif|önceki|onceki|bu)\s+(?:(?:aktif|analiz)\s+)?tablo(?:ya|yu|daki|dan|nun|da|de)?\b",
    re.IGNORECASE,
)
_TABLE_COMPOSITION = re.compile(
    r"ekle|kat|birleştir|birlestir|eşleştir|eslestir|join|hizala|yan yana|append|merge",
    re.IGNORECASE,
)


def _specific_series_term(value: object) -> bool:
    folded = _fold(str(value or "")).strip()
    return bool(folded) and folded not in _GENERIC_SERIES_TERMS


def _fold(text: str) -> str:
    text = (text or "").casefold().translate(str.maketrans({"ı": "i"}))
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _has_term(text: str, term: str) -> bool:
    needle = _fold(term).strip()
    if len(needle) < 3:
        return False
    return needle in _fold(text)


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = str(value).strip()
        key = _fold(value)
        if value and key not in seen:
            out.append(value)
            seen.add(key)
    return tuple(out)


@dataclass(frozen=True)
class FollowUpContext:
    """Confirmed semantic hints for one Agent session."""

    domain: str | None = None
    source: str | None = None
    metric: str | None = None
    series: str | None = None
    entity: str | None = None
    geography: tuple[str, ...] = ()
    date_range: str | None = None
    frequency: str | None = None
    aggregation: str | None = None
    comparison_target: tuple[str, ...] = ()

    def value(self, field: str) -> Any:
        return getattr(self, field)

    def non_empty(self, field: str) -> bool:
        value = self.value(field)
        return bool(value)

    def as_dict(self) -> dict[str, Any]:
        return {field: self.value(field) for field in CONTEXT_FIELDS}


@dataclass(frozen=True)
class FollowUpResolution:
    """A proposed transition, with an audit trail for the harness and UI."""

    question: str
    is_follow_up: bool
    context: FollowUpContext
    #: Deterministic operation hint for safe workspace-local transformations.
    #: It is intentionally not part of FollowUpContext: an operation belongs to
    #: the current request, not to the semantic identity of the active data.
    operation: str | None = None
    #: Explicit fields extracted from the current question. Keeping this
    #: structured avoids making a second LLM call just to detect conflicts.
    explicit: FollowUpContext = field(default_factory=FollowUpContext)
    inherited: tuple[str, ...] = ()
    overridden: tuple[str, ...] = ()
    cleared: tuple[str, ...] = ()
    extended: tuple[str, ...] = ()
    ambiguous: tuple[str, ...] = ()
    clarification_required: bool = False
    committed: bool = False
    #: Complete set of source identities on a compatible, provenance-backed
    #: active workspace. `context.series` remains the linguistic hint; this
    #: field prevents a multi-series table from being reduced to one ID.
    active_series_ids: tuple[str, ...] = ()

    def mark_committed(self) -> FollowUpResolution:
        return replace(self, committed=True)

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "is_follow_up": self.is_follow_up,
            "context": self.context.as_dict(),
            "operation": self.operation,
            "explicit": self.explicit.as_dict(),
            "inherited": list(self.inherited),
            "overridden": list(self.overridden),
            "cleared": list(self.cleared),
            "extended": list(self.extended),
            "ambiguous": list(self.ambiguous),
            "clarification_required": self.clarification_required,
            "committed": self.committed,
            "active_series_ids": list(self.active_series_ids),
        }

    def prompt(self) -> str:
        """Render a model-facing hint without pretending it is catalog proof."""
        if not self.is_follow_up and not any(self.context.value(f) for f in CONTEXT_FIELDS):
            return ""

        def show(value: Any) -> str:
            if isinstance(value, tuple):
                return ", ".join(value) or "yok"
            return str(value) if value else "yok"

        lines = [
            "ÇOK TURLU İSTEK ÇÖZÜMLEMESİ (harness ipucu; katalog ve araç çıktısı yerine geçmez):",
            f"- Soru tipi: {'takip sorusu' if self.is_follow_up else 'yeni soru'}",
        ]
        if self.active_series_ids:
            lines.append(
                "- Doğrulanmış aktif tablodaki tüm kaynak seri kimlikleri: "
                + ", ".join(self.active_series_ids)
                + ". Bu kimlikler mevcut tablonun provenance'ından gelir."
            )
        for label, fields in (
            ("Devralınan", self.inherited),
            ("Değiştirilen", self.overridden),
            ("Genişletilen", self.extended),
            ("Temizlenen", self.cleared),
        ):
            if fields:
                lines.append(f"- {label}: " + ", ".join(fields))
        current = ", ".join(
            f"{field}={show(self.context.value(field))}"
            for field in CONTEXT_FIELDS
            if self.context.non_empty(field)
        )
        if current:
            lines.append(f"- Güvenli çalışma ipuçları: {current}")
        if self.operation:
            lines.append(f"- Deterministik işlem ipucu: {self.operation}")
        if self.ambiguous:
            lines.append("- Belirsiz alanlar: " + ", ".join(self.ambiguous))
            lines.append("- Bu alanları tahmin etme; uygun netleştirme yolunu kullan veya açıkça eksik olduğunu söyle.")
        lines += [
            "- Yeni soruda açıkça yazılan kısıt önceki kısıtı geçersiz kılar; çelişen eski değerleri taşıma.",
            "- Seri ve ölçüm ipuçlarını lakehouse_search/describe ile doğrula; id veya kolon tahmin etme.",
            "- Frekans değişiminde yalnız mevcut katalog/Gold araçlarını kullan; SQL içinde yeniden örnekleme yapma.",
        ]
        return "\n".join(lines)


def _spec_attr(spec: object, name: str, default: Any = None) -> Any:
    return getattr(spec, name, default)


def _catalog_hints(catalog: Iterable[object]) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    """Return series candidates, source candidates, and dimension values."""
    series: list[tuple[str, str]] = []
    sources: list[tuple[str, str]] = []
    dimensions: list[str] = []
    for spec in catalog:
        dataset_id = str(_spec_attr(spec, "dataset_id", ""))
        tags = list(_spec_attr(spec, "tags", []) or [])
        for raw in (_spec_attr(spec, "name", ""), dataset_id, *tags):
            if _specific_series_term(raw):
                series.append((str(raw), dataset_id or str(raw)))
        for raw in (_spec_attr(spec, "source", ""), _spec_attr(spec, "source_detail", "")):
            if raw:
                sources.append((str(raw), str(raw)))
        for column in _spec_attr(spec, "columns", []) or []:
            role = str(_spec_attr(column, "role", "")).casefold()
            # Time/metadata aliases describe the schema (`dönem`, `tarih`,
            # `ay`); they are not series names. Treating them as candidates
            # made any follow-up containing "döneminde" bind to the first
            # catalog series (often an Adana FinTürk series).
            is_time_or_metadata = "time" in role or "metadata" in role
            is_geo = bool(_GEO_COLUMN.search(str(_spec_attr(column, "name", ""))))
            values = list(_spec_attr(column, "example_values", []) or [])
            if is_time_or_metadata:
                continue
            for value in values:
                if is_geo:
                    dimensions.append(str(value))
                elif _specific_series_term(value):
                    series.append((str(value), dataset_id or str(value)))
            if is_geo:
                dimensions.extend(str(v) for v in values)
            elif "dimension" in role:
                # Entity examples are useful only when explicitly mentioned.
                series.extend((str(v), dataset_id or str(v)) for v in values)
            for alias in _spec_attr(column, "aliases", []) or []:
                if _specific_series_term(alias):
                    series.append((str(alias), dataset_id or str(alias)))
    return series, sources, list(_unique(dimensions))


def _best_match(question: str, candidates: Iterable[tuple[str, str]]) -> tuple[str, str] | None:
    matches = [
        (term, value)
        for term, value in candidates
        if term.casefold() not in _NON_SERIES_TERMS and _has_term(question, term)
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: len(_fold(item[0])))


def _extract(question: str, catalog: Iterable[object]) -> FollowUpContext:
    series_candidates, source_candidates, dimensions = _catalog_hints(catalog)
    domain = next(
        (name for name, terms in _DOMAIN_TERMS.items() if any(_has_term(question, term) for term in terms)),
        None,
    )
    source_match = _best_match(question, source_candidates)
    series_match = _best_match(question, series_candidates)

    metric = None
    for term in _GENERIC_METRICS:
        if _has_term(question, term):
            metric = term
            break
    series = None
    if series_match:
        series = series_match[1]
    elif _has_term(question, "alış") or _has_term(question, "alis"):
        series = "buying"
    elif _has_term(question, "satış") or _has_term(question, "satis"):
        series = "selling"

    geography = tuple(value for value in dimensions if _has_term(question, value))
    entity = None
    if geography:
        entity = geography[0]

    compact_range = _COMPACT_MONTH_RANGE.search(question or "")
    years = _YEAR.findall(question)
    date_range = None
    if compact_range:
        y1, m1, y2, m2 = compact_range.groups()
        date_range = f"{int(y1):04d}-{int(m1):02d}–{int(y2):04d}-{int(m2):02d}"
    elif years:
        date_range = years[0] if len(set(years)) == 1 else "-".join(dict.fromkeys(years))
    elif re.search(r"son\s+\d+\s+ay", _fold(question)):
        match = re.search(r"son\s+(\d+)\s+ay", _fold(question))
        date_range = f"last_{match.group(1)}_months" if match else None

    frequency = next((value for value, pattern in _FREQUENCY if pattern.search(question)), None)
    aggregation = next((value for value, pattern in _AGGREGATION if pattern.search(question)), None)

    comparison_target: tuple[str, ...] = ()
    if _COMPARISON.search(question):
        comparison_target = geography or (("previous_period",) if "önceki" in question.casefold() else ())

    return FollowUpContext(
        domain=domain,
        source=source_match[1] if source_match else None,
        metric=metric,
        series=series,
        entity=entity,
        geography=_unique(geography),
        date_range=date_range,
        frequency=frequency,
        aggregation=aggregation,
        comparison_target=comparison_target,
    )


def _looks_like_follow_up(question: str, explicit: FollowUpContext, previous: FollowUpContext) -> bool:
    words = _fold(question).split()
    if _FOLLOW_UP.search(question) or _PERIOD_CHANGE.search(question) or _PERCENT_CHANGE.search(question):
        return True
    if len(words) <= 6 and previous.non_empty("series") and not any(
        explicit.value(field) for field in ("domain", "source", "metric", "series")
    ):
        return True
    return bool(
        explicit.date_range
        and len(words) <= 4
        and previous.non_empty("metric")
        and not any(explicit.value(field) for field in ("domain", "source", "metric", "series"))
    )


def _clear_context(context: FollowUpContext, fields: Iterable[str]) -> FollowUpContext:
    values = {field: () if field in ("geography", "comparison_target") else None for field in fields}
    return replace(context, **values)


def resolve_follow_up(
    question: str,
    previous: FollowUpContext | None = None,
    catalog: Iterable[object] = (),
) -> FollowUpResolution:
    """Resolve one question against confirmed session context.

    Explicit current constraints always win. A domain/source switch clears
    source-specific fields before applying new explicit values. Ambiguous
    pronouns are surfaced instead of being silently bound to stale context.
    """
    previous = previous or FollowUpContext()
    explicit = _extract(question, catalog)
    if explicit.series in ("buying", "selling") and previous.metric:
        variant = "alış" if explicit.series == "buying" else "satış"
        candidates, _, _ = _catalog_hints(catalog)
        matches = [
            (term, value)
            for term, value in candidates
            if _has_term(term, previous.metric) and _has_term(term, variant)
        ]
        if matches:
            selected = max(matches, key=lambda item: len(_fold(item[0])))
            explicit = replace(explicit, metric=previous.metric, series=selected[1])
    has_previous = any(previous.non_empty(field) for field in CONTEXT_FIELDS)
    is_follow_up = has_previous and _looks_like_follow_up(question, explicit, previous)
    if not has_previous and (_REFERENCE.search(question) or (
        _FOLLOW_UP.search(question)
        and not any(explicit.value(field) for field in ("domain", "source", "metric"))
    )):
        is_follow_up = True
    inherited: list[str] = []
    overridden: list[str] = []
    cleared: list[str] = []
    extended: list[str] = []
    ambiguous: list[str] = []

    if not is_follow_up:
        context = explicit
        cleared = [field for field in CONTEXT_FIELDS if previous.non_empty(field) and not explicit.non_empty(field)]
    else:
        context = previous
        switches = []
        if explicit.domain and previous.domain and _fold(explicit.domain) != _fold(previous.domain):
            switches.append("domain")
        if explicit.source and previous.source and _fold(explicit.source) != _fold(previous.source):
            switches.append("source")
        if switches:
            clear_fields = ("source", "metric", "series", "entity", "geography", "frequency", "aggregation", "comparison_target")
            context = _clear_context(context, clear_fields)
            cleared.extend(clear_fields)

        for field in CONTEXT_FIELDS:
            value = explicit.value(field)
            if not value:
                if context.non_empty(field):
                    inherited.append(field)
                continue
            old = context.value(field)
            if field == "geography" and old and _COMPARISON.search(question):
                combined = _unique((*old, *value))
                if combined != old:
                    context = replace(context, geography=combined, entity=combined[-1])
                    extended.append(field)
                continue
            if field == "date_range" and old and old != value and not context.comparison_target:
                # A concrete month-to-month output window is a view change,
                # not an implicit comparison request. Keep the historical
                # year-only comparison behavior for short prompts such as
                # "2024'te?".
                month_window = re.fullmatch(r"(?:19|20)\d{2}-\d{2}–(?:19|20)\d{2}-\d{2}", str(value))
                if not month_window:
                    context = replace(context, comparison_target=(str(old), str(value)))
            if old and old != value:
                overridden.append(field)
            context = replace(context, **{field: value})

        if _REFERENCE.search(question):
            can_resolve = bool(context.metric or context.series or context.entity or context.comparison_target)
            if not can_resolve:
                ambiguous.append("reference")
        if explicit.frequency and not (context.metric or context.series):
            ambiguous.append("series")
        if "diğer" in _fold(question) and not context.comparison_target and len(context.geography) < 2:
            ambiguous.append("comparison_target")

    return FollowUpResolution(
        question=question,
        is_follow_up=is_follow_up,
        context=context,
        operation=("percent_change" if _PERCENT_CHANGE.search(question) else
                   "period_change" if _PERIOD_CHANGE.search(question) else None),
        explicit=explicit,
        inherited=_unique(inherited),
        overridden=_unique(overridden),
        cleared=_unique(cleared),
        extended=_unique(extended),
        ambiguous=_unique(ambiguous),
        clarification_required=bool(ambiguous),
    )


def is_active_table_composition(question: str, resolution: FollowUpResolution | None) -> bool:
    """Whether an explicit request composes a new semantic target with this table.

    This does not authorize answering from the old table alone. The agent uses
    the old table as a provenance-backed anchor while it retrieves and joins
    the explicitly named additional target.
    """
    if resolution is None or resolution.clarification_required:
        return False
    if not _ACTIVE_TABLE_REFERENCE.search(question or "") or not _TABLE_COMPOSITION.search(question or ""):
        return False
    explicit = resolution.explicit
    new_target_fields = ("source", "metric", "series", "entity", "geography")
    return any(explicit.non_empty(field) for field in new_target_fields)


__all__ = ["CONTEXT_FIELDS", "FollowUpContext", "FollowUpResolution", "is_active_table_composition",
           "resolve_follow_up"]
