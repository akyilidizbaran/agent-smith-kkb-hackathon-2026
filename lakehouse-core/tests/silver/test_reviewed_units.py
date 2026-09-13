"""Reviewed source-unit table: BDDK Aylık ratio items print "(%)"; the catalog says pct (2026-09-13)."""

from __future__ import annotations

import pytest

from src.lakehouse.silver.adapters.catalog_driven import SeriesSemantics, _check_declared_unit
from src.lakehouse.silver.foundation import SilverValidationError


def _sem(unit: str) -> SeriesSemantics:
    return SeriesSemantics(series_id="bddk_monthly:544_Rasyo", source_id="bddk_monthly",
                           frequency="monthly", unit=unit, measure_type="ratio", status="active")


def test_percent_label_maps_to_pct() -> None:
    _check_declared_unit("%", semantics=_sem("pct"), row_number=0)


def test_percent_label_against_try_catalog_is_a_conflict() -> None:
    with pytest.raises(SilverValidationError, match="maps to 'pct'"):
        _check_declared_unit("%", semantics=_sem("TRY_mn"), row_number=0)


def test_unreviewed_label_still_refused() -> None:
    with pytest.raises(SilverValidationError, match="no reviewed"):
        _check_declared_unit("adet", semantics=_sem("count"), row_number=3)
