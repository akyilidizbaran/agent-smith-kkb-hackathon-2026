"""Calendar period boxing for the Gold layer.

A Gold row is labelled by the **period end**, the same convention Silver already uses for
month-labelled observations. The period a source observation belongs to is decided by its
``observation_date`` and nothing else: a BDDK weekly bulletin published on a holiday Thursday
falls in the month that Thursday belongs to, and is never moved to the following Friday first.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Final

from .errors import refuse


TARGET_FREQUENCIES: Final[tuple[str, ...]] = ("monthly", "quarterly")
"""Target frequencies this version can produce. Anything else is refused, not approximated."""

_FREQUENCY_ORDER: Final[dict[str, int]] = {
    "daily": 1,
    "business_daily": 1,
    "weekly": 2,
    "biweekly": 3,
    "monthly": 4,
    "quarterly": 5,
    "semiannual": 6,
    "yearly": 7,
}
"""Coarseness ranking. Only used to refuse upsampling; never to invent a conversion."""


def frequency_rank(frequency: str, *, series_id: str | None = None) -> int:
    """Return the coarseness rank of a catalog frequency."""

    try:
        return _FREQUENCY_ORDER[frequency]
    except KeyError:
        raise refuse(
            "UNSUPPORTED_SOURCE_FREQUENCY",
            f"frequency {frequency!r} has no defined coarseness ordering",
            series_id=series_id,
        ) from None


def require_downsampling(
    source_frequency: str, target_frequency: str, *, series_id: str | None = None
) -> None:
    """Refuse anything that would invent observations the source never published.

    Equal frequencies are allowed and mean "identity"; going from coarser to finer is
    upsampling and is always refused, because the only way to fill the gap is to make data up.
    """

    if target_frequency not in TARGET_FREQUENCIES:
        raise refuse(
            "UNSUPPORTED_TARGET_FREQUENCY",
            f"target frequency must be one of {list(TARGET_FREQUENCIES)}, got "
            f"{target_frequency!r}",
            series_id=series_id,
        )
    source_rank = frequency_rank(source_frequency, series_id=series_id)
    target_rank = frequency_rank(target_frequency, series_id=series_id)
    if source_rank > target_rank:
        raise refuse(
            "UPSAMPLING_REFUSED",
            f"cannot produce {target_frequency} data from a {source_frequency} series; "
            "upsampling would invent observations the source never published",
            series_id=series_id,
        )


def period_bounds(observation_date: date, target_frequency: str) -> tuple[date, date]:
    """Return the calendar period ``observation_date`` falls in."""

    if target_frequency == "monthly":
        start = observation_date.replace(day=1)
        end = observation_date.replace(
            day=monthrange(observation_date.year, observation_date.month)[1]
        )
        return start, end
    if target_frequency == "quarterly":
        quarter_index = (observation_date.month - 1) // 3
        first_month = quarter_index * 3 + 1
        last_month = first_month + 2
        start = date(observation_date.year, first_month, 1)
        end = date(
            observation_date.year,
            last_month,
            monthrange(observation_date.year, last_month)[1],
        )
        return start, end
    raise refuse(
        "UNSUPPORTED_TARGET_FREQUENCY",
        f"target frequency must be one of {list(TARGET_FREQUENCIES)}, got "
        f"{target_frequency!r}",
    )


def is_first_period_of_year(period_start: date, target_frequency: str) -> bool:
    """Whether a period is the first one of its calendar year.

    ``flow_ytd`` decomposition needs this: only the year's opening period can have its
    year-to-date value read as that period's own flow.
    """

    if target_frequency == "monthly":
        return period_start.month == 1
    if target_frequency == "quarterly":
        return period_start.month == 1
    raise refuse(
        "UNSUPPORTED_TARGET_FREQUENCY",
        f"target frequency must be one of {list(TARGET_FREQUENCIES)}, got "
        f"{target_frequency!r}",
    )


def previous_period_start(period_start: date, target_frequency: str) -> date:
    """The period immediately before ``period_start``, used only to detect gaps."""

    if target_frequency == "monthly":
        if period_start.month == 1:
            return date(period_start.year - 1, 12, 1)
        return date(period_start.year, period_start.month - 1, 1)
    if target_frequency == "quarterly":
        if period_start.month == 1:
            return date(period_start.year - 1, 10, 1)
        return date(period_start.year, period_start.month - 3, 1)
    raise refuse(
        "UNSUPPORTED_TARGET_FREQUENCY",
        f"target frequency must be one of {list(TARGET_FREQUENCIES)}, got "
        f"{target_frequency!r}",
    )


__all__ = [
    "TARGET_FREQUENCIES",
    "frequency_rank",
    "is_first_period_of_year",
    "period_bounds",
    "previous_period_start",
    "require_downsampling",
]
