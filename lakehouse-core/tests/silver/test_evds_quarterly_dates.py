"""Quarterly EVDS observations: ``Tarih`` is ``YYYY-Qn``, ``UNIXTIME`` is the quarter's first day.

Shape read from real Bronze rows of ``TP.BIRIMFIYAT.TR`` / ``TP.BK.TR`` (keyed endpoint,
2026-09-10). No network here; the values below are those rows.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.lakehouse.silver.adapters._evds_time import evds_quarter_bounds
from src.lakehouse.silver.foundation import SilverValidationError


def _row(date_raw: object, unixtime: object) -> pd.Series:
    return pd.Series({"date_raw": date_raw, "unixtime": unixtime, "value_raw": "4144.9"})


@pytest.mark.parametrize(
    ("date_raw", "unixtime", "start", "end"),
    [
        ("2021-Q1", "1609455600", date(2021, 1, 1), date(2021, 3, 31)),
        ("2021-Q2", "1617224400", date(2021, 4, 1), date(2021, 6, 30)),
        ("2021-Q3", "1625086800", date(2021, 7, 1), date(2021, 9, 30)),
        ("2024-Q4", "1727730000", date(2024, 10, 1), date(2024, 12, 31)),
        ("2024-Q1", None, date(2024, 1, 1), date(2024, 3, 31)),  # leap year, no UNIXTIME
    ],
)
def test_quarter_bounds_follow_the_keyed_endpoint_shape(
    date_raw: str, unixtime: str | None, start: date, end: date
) -> None:
    assert evds_quarter_bounds(_row(date_raw, unixtime), 1) == (start, end)


@pytest.mark.parametrize("date_raw", ["Q1-2021", "2021-1", "2021Q1", "01-2021", "", None])
def test_unreviewed_quarter_spellings_are_refused(date_raw: object) -> None:
    with pytest.raises(SilverValidationError, match="quarterly date_raw"):
        evds_quarter_bounds(_row(date_raw, "1609455600"), 7)


def test_unixtime_outside_the_stated_quarter_is_a_source_change() -> None:
    # 1617224400 is 2021-04-01, which is not inside 2021-Q1.
    with pytest.raises(SilverValidationError, match="disagrees with UNIXTIME"):
        evds_quarter_bounds(_row("2021-Q1", "1617224400"), 3)
