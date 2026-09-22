from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.table_summary import deterministic_table_summary


def test_deterministic_summary_reports_generic_schema_dates_missingness_and_ranges() -> None:
    table = pd.DataFrame({
        "ilce": ["A", "A", "B"],
        "observation_date": ["2024-12-01", "2024-12-02", "2025-01-01"],
        "tmax": [19.8, None, 12.8],
        "precip": [34.1, 8.0, 0.0],
    })
    original = table.copy(deep=True)

    summary = deterministic_table_summary(table)

    assert "3 satır, 4 sütun" in summary
    assert "2024-12-01 – 2025-01-01" in summary
    assert "Eksik değer bulunan sütunlar: `tmax`" in summary
    assert "`tmax`: 12,8 – 19,8" in summary
    assert "`precip`: 0 – 34,1" in summary
    assert "neden-sonuç veya tahmin" in summary
    pd.testing.assert_frame_equal(table, original)


def test_deterministic_summary_is_bounded_for_wide_tables() -> None:
    table = pd.DataFrame({f"metric_{index}": [index, index + 1] for index in range(20)})

    summary = deterministic_table_summary(table)

    assert "ve 8 sütun daha" in summary
    assert "Özet dışında bırakılan sayısal sütun: 14" in summary
    assert "metric_19" not in summary


def test_deterministic_summary_finds_date_column_after_display_limit() -> None:
    data = {f"metric_{index}": [index, index + 1] for index in range(12)}
    data["observation_date"] = ["2024-12-31", "2025-01-31"]
    data["metric_12"] = [12, 13]
    table = pd.DataFrame(data)

    summary = deterministic_table_summary(table)

    assert "2024-12-31 – 2025-01-31" in summary
