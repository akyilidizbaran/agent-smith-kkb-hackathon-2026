"""Deterministic period-window intent parsing.

Natural-language questions sometimes mention a shorter anchor period inside a
larger result window (for example, ``60 aylık`` while requiring that
``2022-2023`` is included). The two constraints are compatible, but the
outer window is not unique unless its bounds are given. This module records
that distinction without choosing dates on the user's behalf.
"""

from __future__ import annotations

import calendar
import random
import re
from dataclasses import dataclass
from datetime import date


_MONTH_WINDOW = re.compile(r"(?<!\d)(\d{1,3})\s*ay(?:lık|lik)\b", re.IGNORECASE)
_MONTH_PAIR = re.compile(
    r"\b(19\d{2}|20\d{2})[-/.](0?[1-9]|1[0-2])\s*"
    r"(?:ile|ve|–|—|-|/|→|->)\s*"
    r"(19\d{2}|20\d{2})[-/.](0?[1-9]|1[0-2])\b",
    re.IGNORECASE,
)
_YEAR_PAIR_SIMPLE = re.compile(
    r"\b(19\d{2}|20\d{2})\s*(?:[-–—]|ile|ve)\s*(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
_CONTAINMENT = re.compile(
    r"kaps\w*|içer\w*|icer\w*|içinde|icinde|dahil|içine|icine|"
    r"barındır\w*|barindir\w*",
    re.IGNORECASE,
)


def _month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _month_delta(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + (value.month - 1) + months
    year, month0 = divmod(absolute, 12)
    return date(year, month0 + 1, 1)


def _fmt_month(value: date | None) -> str:
    return value.strftime("%Y-%m") if value else "?"


@dataclass(frozen=True)
class PeriodIntent:
    """Explicit period constraints found in one question."""

    window_months: int | None = None
    anchor_start: date | None = None
    anchor_end: date | None = None
    outer_start: date | None = None
    outer_end: date | None = None
    containment: bool = False

    @property
    def anchor_months(self) -> int | None:
        if self.anchor_start is None or self.anchor_end is None:
            return None
        return _month_delta(self.anchor_start, self.anchor_end)

    @property
    def outer_bounds_explicit(self) -> bool:
        return self.outer_start is not None and self.outer_end is not None

    @property
    def ambiguous_containment(self) -> bool:
        """Whether a larger window is requested but has no unique bounds."""
        return bool(
            self.containment
            and self.window_months
            and self.anchor_months
            and self.window_months > self.anchor_months
            and not self.outer_bounds_explicit
        )

    @property
    def incompatible_containment(self) -> bool:
        """Whether the requested window is shorter than its required anchor."""
        return bool(
            self.containment
            and self.window_months
            and self.anchor_months
            and self.window_months < self.anchor_months
        )

    @property
    def effective_window_months(self) -> int | None:
        """Minimum valid window; an anchor can widen a too-short request."""
        if self.window_months is None:
            return None
        return max(self.window_months, self.anchor_months or 0)

    def selection_note(self, selected: tuple[date, date]) -> str:
        """Render the harness decision that is passed to the model and evidence."""
        start, end = selected
        assert self.window_months
        anchor = ""
        if self.anchor_start and self.anchor_end:
            anchor = f" Anchor: {_fmt_month(self.anchor_start)}–{_fmt_month(self.anchor_end)}."
        widening = " Anchor'ı korumak için minimum pencere genişletildi." if self.incompatible_containment else ""
        return (
            "DÖNEM ÇÖZÜMLEMESİ: Kullanıcı daha geniş bir ay penceresi istedi ve açık bir dış sınır vermedi. "
            f"Veri kapsamı içinden otomatik seçilen sonuç penceresi {_fmt_month(start)}–{_fmt_month(end)} "
            f"({self.effective_window_months} ay).{anchor}{widening} "
            "Sorgu ve cevap bu pencereyi kullanmalı; seçilen aralığı cevapta belirt. "
            f"Aylık isteklerde her YYYY-MM dönemi için bir satır üret (beklenen en az "
            f"{self.effective_window_months} farklı ay); yalnızca anchor yıllarını gruplayıp "
            "iki yıllık satır döndürme."
        )


def containing_windows(
    intent: PeriodIntent,
    coverages: list[tuple[date, date]],
) -> list[tuple[date, date]]:
    """Return every contiguous valid window in the common catalog coverage."""
    if not intent.containment or not intent.window_months or not intent.anchor_start or not intent.anchor_end:
        return []
    months = intent.effective_window_months
    if months is None:
        return []
    # A broad source/frequency facet can contain unrelated series with a
    # shorter or later publication history. They must not shrink the common
    # window of the series that can actually contain the requested anchor.
    # Keep only coverages that individually contain the anchor and the desired
    # outer window; otherwise one unrelated child series (or a newly added
    # dataset) makes every valid 60-month window disappear.
    required_months = intent.effective_window_months
    anchor_start = date(intent.anchor_start.year, intent.anchor_start.month, 1)
    anchor_end = date(intent.anchor_end.year, intent.anchor_end.month, 1)
    valid = []
    for c1, c2 in coverages:
        start, end = date(c1.year, c1.month, 1), date(c2.year, c2.month, 1)
        if start > end or start > anchor_start or end < anchor_end:
            continue
        if required_months and _month_delta(start, end) < required_months:
            continue
        valid.append((start, end))
    if not valid:
        return []
    common_start = max(c1 for c1, _ in valid)
    common_end = min(c2 for _, c2 in valid)
    lower = max(common_start, _add_months(date(intent.anchor_end.year, intent.anchor_end.month, 1), -(months - 1)))
    upper = min(date(intent.anchor_start.year, intent.anchor_start.month, 1), _add_months(common_end, -(months - 1)))
    if lower > upper:
        return []
    out: list[tuple[date, date]] = []
    cursor = lower
    while cursor <= upper:
        end_month = _add_months(cursor, months - 1)
        out.append((cursor, _month_end(end_month.year, end_month.month)))
        cursor = _add_months(cursor, 1)
    return out


def choose_containing_window(
    intent: PeriodIntent,
    coverages: list[tuple[date, date]],
    *,
    rng: random.Random | random.SystemRandom | None = None,
) -> tuple[date, date] | None:
    """Choose one valid window without asking the user for missing bounds."""
    windows = containing_windows(intent, coverages)
    return (rng or random.SystemRandom()).choice(windows) if windows else None


def _year_anchor(question: str) -> tuple[date, date] | None:
    matches = list(_YEAR_PAIR_SIMPLE.finditer(question or ""))
    if not matches:
        return None
    first, last = matches[0].groups()
    y1, y2 = int(first), int(last)
    if y1 > y2:
        y1, y2 = y2, y1
    return date(y1, 1, 1), _month_end(y2, 12)


def parse_period_intent(question: str) -> PeriodIntent:
    """Parse a month window and an optional contained year/month anchor."""
    q = question or ""
    window_match = _MONTH_WINDOW.search(q)
    window_months = int(window_match.group(1)) if window_match else None

    month_pairs = list(_MONTH_PAIR.finditer(q))
    anchor_start = anchor_end = outer_start = outer_end = None
    if month_pairs:
        m = month_pairs[0]
        y1, mo1, y2, mo2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        start, end = _month_start(y1, mo1), _month_end(y2, mo2)
        if start > end:
            start, end = _month_start(y2, mo2), _month_end(y1, mo1)
        if window_months is None:
            outer_start, outer_end = start, end
        elif _month_delta(start, end) == window_months:
            outer_start, outer_end = start, end
        else:
            anchor_start, anchor_end = start, end
    else:
        anchor = _year_anchor(q)
        if anchor:
            anchor_start, anchor_end = anchor

    # A five-year year-level range is an explicit outer window when the user
    # also says "60 months"; a two-year range remains the contained anchor.
    year_anchor = _year_anchor(q)
    if year_anchor and window_months:
        span = _month_delta(*year_anchor)
        if span == window_months:
            outer_start, outer_end = year_anchor
            anchor_start = anchor_end = None

    containment = bool(_CONTAINMENT.search(q))
    return PeriodIntent(
        window_months=window_months,
        anchor_start=anchor_start,
        anchor_end=anchor_end,
        outer_start=outer_start,
        outer_end=outer_end,
        containment=containment,
    )


__all__ = ["PeriodIntent", "parse_period_intent", "containing_windows", "choose_containing_window"]
