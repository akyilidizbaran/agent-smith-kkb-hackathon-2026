"""Promotion: an ad-hoc draft becomes active on a human's say-so and its rows enter Silver.

Curated rows and non-drafts are refused; promoting twice is idempotent; a Silver rebuild
keeps promoted rows (they are appended after the Bronze-derived snapshot).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.lakehouse.catalog.promotion import PromotionError, promote_draft_series
from src.lakehouse.cli import main
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.silver.build import build_silver_snapshot


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


def test_draft_becomes_active_and_rows_enter_silver(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "lh.duckdb")
    try:
        _draft(connection)
        result = promote_draft_series(connection, "adhoc:sicaklik")
        assert result.previous_status == "draft" and result.rows_promoted == 3 and result.silver_rows_replaced == 0
        status, source, confidence = connection.execute(
            "SELECT status, semantic_source, semantic_confidence FROM meta.series WHERE series_id = 'adhoc:sicaklik'"
        ).fetchone()
        assert (status, source, confidence) == ("active", "manual", "derived")   # onaylandı, doğrulanmadı
        assert connection.execute(
            "SELECT count(*), min(artifact_sha256) FROM silver.fact_observation WHERE series_id = 'adhoc:sicaklik'"
        ).fetchone() == (3, "a" * 64)
        # idempotent
        again = promote_draft_series.__wrapped__ if hasattr(promote_draft_series, "__wrapped__") else None
        with pytest.raises(PromotionError, match="only 'draft'"):
            promote_draft_series(connection, "adhoc:sicaklik")
    finally:
        connection.close()


def test_curated_and_missing_series_are_refused(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "lh.duckdb")
    try:
        with pytest.raises(PromotionError, match="curated"):
            promote_draft_series(connection, "bddk_monthly:1534_Toplam")
        with pytest.raises(PromotionError, match="not in meta.series"):
            promote_draft_series(connection, "adhoc:yok")
        connection.execute(
            """
            INSERT INTO meta.series (series_id, source_id, native_code, dataset_id, name_tr, description,
                frequency, measure_type, semantic_confidence, semantic_source, status, catalog_content_sha256)
            VALUES ('adhoc:bos', 'adhoc', 'bos', 'adhoc_bos', 'boş', 'x', 'daily', 'unknown', 'derived', 'profiler', 'draft', ?)
            """, ["0" * 64],
        )
        with pytest.raises(PromotionError, match="no observations"):
            promote_draft_series(connection, "adhoc:bos")
    finally:
        connection.close()


def test_silver_rebuild_keeps_promoted_rows(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "lh.duckdb")
    try:
        _draft(connection)
        promote_draft_series(connection, "adhoc:sicaklik")
        report = build_silver_snapshot(connection, bronze_root=tmp_path / "bronze")   # Bronze yok: yalnız terfi
        assert report.promoted_adhoc_rows == 3 and "adhoc:sicaklik" in report.series_published
        assert "promoted ad-hoc rows   : 3" in report.render()
        assert connection.execute(
            "SELECT count(*) FROM silver.fact_observation WHERE series_id = 'adhoc:sicaklik'"
        ).fetchone()[0] == 3
    finally:
        connection.close()


def test_cli_promote_draft_reports_and_refuses(tmp_path: Path, capsys) -> None:
    db = tmp_path / "data" / "lakehouse.duckdb"
    connection = bootstrap_database(db)
    _draft(connection)
    connection.close()

    code = main(["promote-draft", "--database", str(db), "--data-root", str(tmp_path / "data"), "--series", "adhoc:sicaklik"])
    out = capsys.readouterr().out
    assert code == 0 and "status: success" in out and "rows_promoted: 3" in out and "semantic_confidence: derived" in out

    code = main(["promote-draft", "--database", str(db), "--data-root", str(tmp_path / "data"), "--series", "adhoc:sicaklik"])
    err = capsys.readouterr().err
    assert code == 2 and "only 'draft'" in err
