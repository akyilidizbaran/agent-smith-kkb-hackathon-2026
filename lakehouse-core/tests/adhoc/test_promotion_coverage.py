"""Promotion refreshes catalog coverage: a promoted series carries first_obs/last_obs immediately.

Observed 20 Sep 2026: after ``promote-draft`` the series sat in Silver with 11 rows while
``meta.series.first_obs``/``last_obs`` stayed NULL until the next full Silver rebuild, so the
agent answered "coverage unknown" for data it could already query.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from src.lakehouse.catalog.promotion import promote_draft_series
from src.lakehouse.db.bootstrap import bootstrap_database


def _draft(connection, series_id: str = "adhoc:sicaklik", rows: int = 3) -> None:
    connection.execute(
        """
        INSERT INTO meta.series (series_id, source_id, native_code, dataset_id, name_tr, description,
            frequency, unit, measure_type, default_agg, semantic_confidence, semantic_source, status,
            catalog_content_sha256)
        VALUES (?, 'adhoc', ?, 'adhoc_test', 'Sıcaklık (taslak)', 'test', 'daily', '°C', 'index', 'avg',
                'derived', 'profiler', 'draft', ?)
        """,
        [series_id, series_id.split(":", 1)[1], "0" * 64],
    )
    for i in range(rows):
        connection.execute(
            """
            INSERT INTO adhoc.fact_observation VALUES (?, NULL, ?, NULL, ?, ?, 'daily', '°C', 'index', 'ok',
                'adhoc', 'adhoc_test', ?, ?, 'adhoc.v1', ?, 'run-1')
            """,
            [series_id, date(2025, 1, i + 1), date(2025, 1, i + 1), 20.0 + i, "a" * 64,
             datetime(2026, 9, 12, tzinfo=timezone.utc), "artifact:" + "a" * 64],
        )


def test_promotion_fills_first_and_last_observation(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "lh.duckdb")
    try:
        _draft(connection)
        assert connection.execute(
            "SELECT first_obs, last_obs FROM meta.series WHERE series_id = 'adhoc:sicaklik'"
        ).fetchone() == (None, None), "a draft has no Silver rows, so no coverage yet"
        promote_draft_series(connection, "adhoc:sicaklik")
        assert connection.execute(
            "SELECT first_obs, last_obs FROM meta.series WHERE series_id = 'adhoc:sicaklik'"
        ).fetchone() == (date(2025, 1, 1), date(2025, 1, 3))
    finally:
        connection.close()
