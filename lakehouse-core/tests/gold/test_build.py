"""Materialization: reviewed calls cached as ``gold.*`` tables, refusals recorded, staleness visible.

Real data where the catalog has it (the committed BDDK weekly fixture through the real
pipeline); SYNTHETIC series only for the join, because two real series never share one test
database here. Nothing synthetic reaches ``catalog/``.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.lakehouse.gold import (
    GoldCatalogError,
    align_frequency,
    build_gold_tables,
    load_gold_catalog_files,
    silver_fingerprint,
)
from src.lakehouse.gold.build import PROVENANCE_COLUMNS, sql_type_for
from src.lakehouse.gold.serialize import frame_to_document, json_ready
from src.lakehouse.silver.foundation import materialize_fact_observation_snapshot

from ._support import SYNTHETIC_SERIES, add_synthetic_series, ingest_bddk_weekly, staging_rows

HEADER = 'gold_catalog_schema_version: "1.0"\nmetrics:\n'

ALIGN_WEEKLY = HEADER + """\
  - metric_id: haftalik_konut_aylik
    name_tr: Haftalık konut kredisi, ay sonu
    description: test metric over the real weekly fixture
    aliases: [aylık konut haftalık]
    tags: [test]
    function: align_frequency
    series_ids: [bddk_weekly:5690_3]
    target_frequency: monthly
"""

DECOMPOSE_STOCK = HEADER + """\
  - metric_id: haftalik_konut_akim
    name_tr: refused on purpose
    description: a stock handed to decompose_cumulative
    function: decompose_cumulative
    series_ids: [bddk_weekly:5690_3]
"""


def _catalog(tmp_path: Path, *documents: str) -> Path:
    root = tmp_path / "gold_catalog"
    root.mkdir(exist_ok=True)
    for index, text in enumerate(documents):
        (root / f"{index:02d}_metrics.yml").write_text(text, encoding="utf-8")
    return root


def _tables(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'gold'"
        ).fetchall()
    }


def _ledger(connection, metric_id: str) -> list[tuple[Any, ...]]:
    return connection.execute(
        "SELECT status, row_count, is_current, refusal_reason, silver_fingerprint "
        "FROM meta.gold_build WHERE metric_id = ? ORDER BY built_at",
        [metric_id],
    ).fetchall()


# ================================================================ catalog validation


@pytest.mark.parametrize(
    "document, needle",
    [
        (HEADER + "  - metric_id: m_1\n    name_tr: a\n    description: b\n    function: align_frequency\n    series_ids: [bddk_weekly:5690_3]\n", "requires 'target_frequency'"),
        (HEADER + "  - metric_id: m_1\n    name_tr: a\n    description: b\n    function: decompose_cumulative\n    series_ids: [bddk_weekly:5690_3]\n    target_frequency: monthly\n", "must be absent"),
        (HEADER + "  - metric_id: m_1\n    name_tr: a\n    description: b\n    function: join_on_period\n    series_ids: [bddk_weekly:5690_3]\n    target_frequency: monthly\n", "at least two series"),
        (HEADER + "  - metric_id: m_1\n    name_tr: a\n    description: b\n    function: rebase_index\n    series_ids: [bddk_weekly:5690_3]\n    target_frequency: monthly\n", "not one of"),
        (HEADER + "  - metric_id: Gold-1\n    name_tr: a\n    description: b\n    function: align_frequency\n    series_ids: [bddk_weekly:5690_3]\n    target_frequency: monthly\n", "plain table name"),
        (HEADER + "  - metric_id: m_1\n    name_tr: a\n    description: b\n    function: align_frequency\n    series_ids: [bddk_weekly:5690_3]\n    target_frequency: yearly\n", "target_frequency 'yearly'"),
        (HEADER + "  - metric_id: m_1\n    name_tr: a\n    description: b\n    function: align_frequency\n    series_ids: [bddk_weekly:5690_3]\n    target_frequency: monthly\n    allow_unverified_semantics: true\n", "unverified_reason"),
        (HEADER + "  - metric_id: m_1\n    name_tr: a\n    description: b\n    function: align_frequency\n    series_ids: [not a series id]\n    target_frequency: monthly\n", "series_ids entry"),
    ],
)
def test_malformed_metrics_are_rejected_before_anything_is_built(
    tmp_path: Path, document: str, needle: str
) -> None:
    with pytest.raises(GoldCatalogError, match=needle):
        load_gold_catalog_files(_catalog(tmp_path, document))


def test_duplicate_metric_ids_across_files_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(GoldCatalogError, match="already defined"):
        load_gold_catalog_files(_catalog(tmp_path, ALIGN_WEEKLY, ALIGN_WEEKLY))


def test_a_missing_catalog_directory_is_an_error_not_an_empty_catalog(tmp_path: Path) -> None:
    with pytest.raises(GoldCatalogError, match="does not exist"):
        load_gold_catalog_files(tmp_path / "nowhere")


def test_the_committed_metric_catalog_is_valid() -> None:
    records = load_gold_catalog_files()
    assert {r.metric_id for r in records} >= {"konut_kredisi_ceyreklik", "konut_faizi_aylik"}
    assert all(r.content_sha256 for r in records)


# ================================================================ materialization


def test_a_built_table_is_the_function_call_plus_build_provenance(tmp_path: Path) -> None:
    connection, _ = ingest_bddk_weekly(tmp_path)
    try:
        report = build_gold_tables(connection, catalog_root=_catalog(tmp_path, ALIGN_WEEKLY))

        assert [o.status for o in report.outcomes] == ["built"]
        assert "haftalik_konut_aylik" in _tables(connection)

        expected = align_frequency(connection, "bddk_weekly:5690_3", "monthly")
        table = connection.execute(
            "SELECT * FROM gold.haftalik_konut_aylik ORDER BY period_start"
        ).fetch_df()
        assert len(table) == len(expected) == report.outcomes[0].row_count
        assert table["value"].tolist() == pytest.approx([float(v) for v in expected["value"]])
        assert [stamp.date() for stamp in table["period_end"]] == expected["period_end"].tolist()
        assert table["artifact_sha256_list"].iloc[0].tolist() == expected["artifact_sha256_list"].iloc[0]

        for column in PROVENANCE_COLUMNS:
            assert column in table.columns
        assert set(table["gold_build_id"]) == {report.build_id}
        assert set(table["silver_fingerprint"]) == {report.silver_fingerprint}
        assert set(table["gold_function"]) == {"align_frequency"}

        types = {
            row[0]: row[1]
            for row in connection.execute("DESCRIBE gold.haftalik_konut_aylik").fetchall()
        }
        assert types["value"] == "DOUBLE"
        assert types["period_end"] == "DATE"
        assert types["observations"] == "INTEGER"
        assert types["source_observation_dates"] == "DATE[]"
        assert types["artifact_sha256_list"] == "VARCHAR[]"

        (status, rows, current, reason, fingerprint) = _ledger(connection, "haftalik_konut_aylik")[0]
        assert (status, rows, current, reason) == ("built", len(expected), True, None)
        assert fingerprint == report.silver_fingerprint
        assert "tables built           : 1" in report.render()
    finally:
        connection.close()


def test_a_refused_metric_has_no_table_and_a_recorded_reason(tmp_path: Path) -> None:
    """A stock handed to ``decompose_cumulative`` is refused; a stale table is dropped."""

    connection, _ = ingest_bddk_weekly(tmp_path)
    try:
        connection.execute("CREATE TABLE gold.haftalik_konut_akim AS SELECT 1 AS stale")

        report = build_gold_tables(connection, catalog_root=_catalog(tmp_path, DECOMPOSE_STOCK))

        outcome = report.outcomes[0]
        assert outcome.status == "refused"
        assert outcome.refusal_reason == "NOT_DECOMPOSABLE"
        assert outcome.dropped_stale_table is True
        assert "haftalik_konut_akim" not in _tables(connection)
        (status, rows, current, reason, _) = _ledger(connection, "haftalik_konut_akim")[0]
        assert (status, rows, current, reason) == ("refused", None, True, "NOT_DECOMPOSABLE")
        rendered = report.render()
        assert "metrics refused        : 1" in rendered
        assert "NOT_DECOMPOSABLE" in rendered and "[stale table dropped]" in rendered
    finally:
        connection.close()


def test_a_rebuild_is_idempotent_and_keeps_the_ledger_history(tmp_path: Path) -> None:
    connection, _ = ingest_bddk_weekly(tmp_path)
    try:
        catalog = _catalog(tmp_path, ALIGN_WEEKLY)
        first = build_gold_tables(connection, catalog_root=catalog)
        second = build_gold_tables(connection, catalog_root=catalog)

        assert first.silver_fingerprint == second.silver_fingerprint
        assert first.outcomes[0].row_count == second.outcomes[0].row_count
        ledger = _ledger(connection, "haftalik_konut_aylik")
        assert len(ledger) == 2
        assert [row[2] for row in ledger] == [False, True]  # only the latest is current
        build_ids = connection.execute(
            "SELECT DISTINCT gold_build_id FROM gold.haftalik_konut_aylik"
        ).fetchall()
        assert build_ids == [(second.build_id,)]
    finally:
        connection.close()


def test_the_silver_fingerprint_moves_when_silver_moves(tmp_path: Path) -> None:
    """After a Silver rebuild the recorded fingerprint no longer matches the live one."""

    connection, _ = ingest_bddk_weekly(tmp_path)
    try:
        report = build_gold_tables(connection, catalog_root=_catalog(tmp_path, ALIGN_WEEKLY))
        before, rows_before = silver_fingerprint(connection)
        assert before == report.silver_fingerprint

        connection.execute(
            "UPDATE silver.fact_observation SET value = value + 1 "
            "WHERE observation_date = (SELECT max(observation_date) FROM silver.fact_observation)"
        )
        after, rows_after = silver_fingerprint(connection)

        assert after != before and rows_after == rows_before
        recorded = connection.execute(
            "SELECT DISTINCT silver_fingerprint FROM gold.haftalik_konut_aylik"
        ).fetchone()[0]
        assert recorded == before  # the table still says which snapshot it came from
    finally:
        connection.close()


def test_a_metric_removed_from_the_catalog_loses_its_table(tmp_path: Path) -> None:
    connection, _ = ingest_bddk_weekly(tmp_path)
    try:
        build_gold_tables(connection, catalog_root=_catalog(tmp_path, ALIGN_WEEKLY))
        connection.execute("CREATE TABLE gold.not_ours AS SELECT 1 AS x")

        replacement = ALIGN_WEEKLY.replace("haftalik_konut_aylik", "haftalik_konut_aylik_v2")
        report = build_gold_tables(connection, catalog_root=_catalog(tmp_path, replacement))

        assert report.orphan_tables_dropped == ("haftalik_konut_aylik",)
        tables = _tables(connection)
        assert "haftalik_konut_aylik" not in tables
        assert "haftalik_konut_aylik_v2" in tables
        assert "not_ours" in tables  # a table the build never wrote is not its to drop
        assert _ledger(connection, "haftalik_konut_aylik")[-1][2] is False
    finally:
        connection.close()


def test_a_join_metric_materializes_one_prefixed_column_group_per_series(
    connection, tmp_path: Path
) -> None:
    stock = add_synthetic_series(connection, SYNTHETIC_SERIES["stock_monthly"])
    flow = add_synthetic_series(connection, SYNTHETIC_SERIES["flow_weekly"])
    staging = pd.concat(
        [
            staging_rows(stock, [(date(2026, 1, 31), "100"), (date(2026, 2, 28), "110")]),
            staging_rows(flow, [(date(2026, 1, 9), "1"), (date(2026, 1, 16), "2"), (date(2026, 2, 6), "5")], digest="b"),
        ],
        ignore_index=True,
    )
    materialize_fact_observation_snapshot(connection, staging)
    catalog = HEADER + f"""\
  - metric_id: sentetik_birlesim
    name_tr: synthetic join
    description: two synthetic lines on one axis
    function: join_on_period
    series_ids: [{stock}, {flow}]
    target_frequency: monthly
"""
    report = build_gold_tables(connection, catalog_root=_catalog(tmp_path, catalog))

    assert report.outcomes[0].status == "built"
    table = connection.execute("SELECT * FROM gold.sentetik_birlesim ORDER BY period_start").fetch_df()
    assert len(table) == 2
    assert table[f"{stock}::value"].tolist() == [100.0, 110.0]
    assert table[f"{flow}::value"].tolist() == [3.0, 5.0]  # flow_periodic sums
    assert table["is_complete_period"].tolist() == [True, True]
    assert set(table["gold_metric_id"]) == {"sentetik_birlesim"}


# ================================================================ serialization


def test_json_ready_keeps_missing_missing_and_dates_iso() -> None:
    assert json_ready(None) is None
    assert json_ready(math.nan) is None
    assert json_ready(date(2026, 3, 31)) == "2026-03-31"
    assert json_ready(datetime(2026, 3, 31, 8, tzinfo=timezone.utc)) == "2026-03-31T08:00:00+00:00"
    assert json_ready([date(2026, 1, 8), None]) == ["2026-01-08", None]
    assert json_ready(np.int64(3)) == 3 and isinstance(json_ready(np.int64(3)), int)
    assert json_ready(True) is True


def test_frame_to_document_is_self_describing() -> None:
    frame = pd.DataFrame({"period_end": [date(2026, 1, 31)], "value": [None], "l": [["a"]]})
    frame["value"] = pd.Series([None], dtype=object)
    document = frame_to_document(frame, function="align_frequency", arguments={"x": 1})
    assert document["columns"] == ["period_end", "value", "l"]
    assert document["rows"] == [["2026-01-31", None, ["a"]]]
    assert document["function"] == "align_frequency" and document["arguments"] == {"x": 1}


def test_sql_type_for_reads_the_base_name_after_the_series_prefix() -> None:
    assert sql_type_for("value") == "DOUBLE"
    assert sql_type_for("evds:TP.KTF12@bddk:10001::value") == "DOUBLE"
    assert sql_type_for("x::source_observation_dates") == "DATE[]"
    assert sql_type_for("contributing_series") == "VARCHAR[]"
    assert sql_type_for("is_complete_period") == "BOOLEAN"
    assert sql_type_for("quality_flag") == "VARCHAR"
