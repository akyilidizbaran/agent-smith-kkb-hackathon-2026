"""Resolve an EVDS observation's calendar date without trusting the field order of ``Tarih``.

EVDS spells ``Tarih`` differently depending on which of its endpoints answered, and the two
spellings are indistinguishable for the first twelve days of a month:

===================== ===================== =====================
frequency             web application       documented keyed API
===================== ===================== =====================
weekly / daily        ``01-08-2021``        ``08-01-2021``
monthly               ``01-2021``           ``2021-1``
quarterly             (not captured)        ``2021-Q1``
===================== ===================== =====================

The quarterly row was read from real Bronze rows of ``TP.BIRIMFIYAT.TR`` and ``TP.BK.TR``
fetched from the keyed endpoint on 2026-09-10: ``Tarih`` is ``YYYY-Qn`` and ``UNIXTIME`` is
the first day of that quarter (``2021-Q1`` ↔ ``1609455600`` = 2021-01-01 Istanbul). Only that
spelling is accepted; the web application's quarterly spelling has never been observed.

Both rows are the same observation — 8 January 2021 and January 2021. The committed fixtures
came from the web application, because no API key existed when they were captured; their
README says so and asks for a re-capture once a key is available. When the keyed endpoint was
finally called live, the monthly shape failed loudly — and the weekly shape did not. Read as
``%m-%d-%Y``, ``08-01-2021`` is a perfectly valid 1 August 2021, so every weekly observation
after the twelfth of a month would have silently landed on the wrong date.

``UNIXTIME`` is carried in the same payload and has no field-order ambiguity, so it decides.
``Tarih`` is still read — not to produce the date, but to be checked against it, so a future
third spelling is a failure rather than a surprise.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from ..foundation import SilverValidationError


ISTANBUL = timezone(timedelta(hours=3))
"""Türkiye observes UTC+3 year-round; daylight saving was abolished in 2016."""

_ACCEPTED_DATE_FORMATS = ("%d-%m-%Y", "%m-%d-%Y")
_ACCEPTED_MONTH_FORMATS = ("%Y-%m", "%m-%Y")


_EARLIEST_PLAUSIBLE_YEAR = 1900
"""Python's ``%Y`` happily reads ``25`` as the year 25, so ``02-25`` would otherwise parse as
February of year 25 rather than being refused. EVDS publishes nothing before the twentieth
century, so a year below this is a malformed field, not a date."""


def _parse_candidates(raw: str, formats: tuple[str, ...]) -> set[date]:
    parsed: set[date] = set()
    for fmt in formats:
        try:
            value = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        if value.year < _EARLIEST_PLAUSIBLE_YEAR:
            continue
        parsed.add(value.replace(day=1) if fmt in _ACCEPTED_MONTH_FORMATS else value)
    return parsed


def _unixtime_date(raw: object) -> date | None:
    if raw is None or raw is pd.NA:
        return None
    try:
        if pd.isna(raw):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromtimestamp(int(str(raw).strip()), ISTANBUL).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _resolve(raw_date: object, raw_unixtime: object, row_number: int, *, monthly: bool) -> date:
    formats = _ACCEPTED_MONTH_FORMATS if monthly else _ACCEPTED_DATE_FORMATS
    text = str(raw_date).strip() if isinstance(raw_date, str) else None
    candidates = _parse_candidates(text, formats) if text else set()

    from_unixtime = _unixtime_date(raw_unixtime)
    if from_unixtime is not None:
        anchor = from_unixtime.replace(day=1) if monthly else from_unixtime
        if candidates and anchor not in candidates:
            raise SilverValidationError(
                f"EVDS date_raw {raw_date!r} at row {row_number} disagrees with UNIXTIME "
                f"({anchor.isoformat()}); the source changed a field this mapping relies on"
            )
        if not candidates and text:
            raise SilverValidationError(
                f"EVDS date_raw {raw_date!r} at row {row_number} is in no recognised shape; "
                f"UNIXTIME reads {anchor.isoformat()} but the two must agree before publishing"
            )
        return anchor

    if len(candidates) == 1:
        return next(iter(candidates))
    if not candidates:
        raise SilverValidationError(
            f"invalid EVDS date_raw at row {row_number}: {raw_date!r}"
        )
    raise SilverValidationError(
        f"ambiguous EVDS date_raw at row {row_number}: {raw_date!r} could be "
        + " or ".join(sorted(candidate.isoformat() for candidate in candidates))
        + ", and no UNIXTIME is present to decide"
    )


def evds_point_date(row: pd.Series, row_number: int) -> date:
    """The calendar date of a daily or weekly EVDS observation."""

    return _resolve(
        row.get("date_raw"), row.get("unixtime"), row_number, monthly=False
    )


def evds_month_bounds(row: pd.Series, row_number: int) -> tuple[date, date]:
    """The first and last calendar day of a monthly EVDS observation's month."""

    period_start = _resolve(
        row.get("date_raw"), row.get("unixtime"), row_number, monthly=True
    )
    last_day = monthrange(period_start.year, period_start.month)[1]
    return period_start, period_start.replace(day=last_day)


_QUARTER_RE = re.compile(r"^(?P<year>\d{4})-Q(?P<quarter>[1-4])$")


def evds_quarter_bounds(row: pd.Series, row_number: int) -> tuple[date, date]:
    """The first and last calendar day of a quarterly EVDS observation's quarter.

    ``Tarih`` must be ``YYYY-Qn`` and, when ``UNIXTIME`` is present, it must fall inside that
    quarter (the keyed endpoint sends the quarter's first day). Any other spelling is refused
    so that a new one is a failure rather than a silently wrong period.
    """

    raw_date = row.get("date_raw")
    text = str(raw_date).strip() if isinstance(raw_date, str) else ""
    match = _QUARTER_RE.match(text)
    if match is None:
        raise SilverValidationError(
            f"invalid EVDS quarterly date_raw at row {row_number}: {raw_date!r}; "
            "expected 'YYYY-Qn' as the keyed endpoint publishes it"
        )
    year, quarter = int(match["year"]), int(match["quarter"])
    if year < _EARLIEST_PLAUSIBLE_YEAR:
        raise SilverValidationError(
            f"invalid EVDS quarterly date_raw at row {row_number}: {raw_date!r}"
        )
    period_start = date(year, 3 * quarter - 2, 1)
    end_month = 3 * quarter
    period_end = date(year, end_month, monthrange(year, end_month)[1])

    from_unixtime = _unixtime_date(row.get("unixtime"))
    if from_unixtime is not None and not (period_start <= from_unixtime <= period_end):
        raise SilverValidationError(
            f"EVDS date_raw {raw_date!r} at row {row_number} disagrees with UNIXTIME "
            f"({from_unixtime.isoformat()}); the source changed a field this mapping relies on"
        )
    return period_start, period_end


__all__ = ["ISTANBUL", "evds_month_bounds", "evds_point_date", "evds_quarter_bounds"]
