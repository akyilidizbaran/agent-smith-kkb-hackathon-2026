"""Additive breakdown check (ADR-0108): buckets must sum to their total; gaps are reported, not zero-filled."""

from __future__ import annotations

from datetime import date

import duckdb

from src.lakehouse.quality.breakdown import check_additive_breakdowns


def _db() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE SCHEMA meta; CREATE SCHEMA silver;")
    con.execute("""CREATE TABLE meta.series_relation (series_id VARCHAR, parent_series_id VARCHAR,
                   relation_type VARCHAR, dimension_path VARCHAR[], additivity VARCHAR)""")
    con.execute("CREATE TABLE silver.fact_observation (series_id VARCHAR, observation_date DATE, value DOUBLE)")
    con.execute("INSERT INTO meta.series_relation VALUES ('T', NULL, 'parent_total', [], 'additive')")
    for child, interval in (("A", "[0,0]"), ("B", "(0,1]"), ("C", "(1,inf)")):
        con.execute("INSERT INTO meta.series_relation VALUES (?, 'T', 'child_breakdown', ?, 'unknown')",
                    [child, [f"vade={child}", f"vade_ay={interval}"]])
    # A non-maturity child of the same total must not join the partition.
    con.execute("INSERT INTO meta.series_relation VALUES ('X', 'T', 'child_breakdown', [], 'unknown')")
    return con


def _obs(con, series_id: str, month: int, value: float | None) -> None:
    con.execute("INSERT INTO silver.fact_observation VALUES (?, ?, ?)", [series_id, date(2025, month, 28), value])


def test_reconciles_within_source_rounding_and_flags_real_mismatch() -> None:
    con = _db()
    for month, (a, b, c, total) in {1: (10, 20, 70, 101), 2: (10, 20, 70, 105)}.items():
        for sid, value in (("A", a), ("B", b), ("C", c), ("T", total), ("X", 999)):
            _obs(con, sid, month, value)

    report = check_additive_breakdowns(con)

    assert report.parents_checked == 1 and report.months_compared == 2
    assert [(i.observation_date, i.kind, i.difference) for i in report.issues] == [("2025-02-28", "mismatch", -5.0)]


def test_missing_bucket_or_total_is_incomplete_not_zero() -> None:
    con = _db()
    for sid, value in (("A", 10), ("B", 20), ("T", 100)):     # C missing in month 1
        _obs(con, sid, 1, value)
    for sid, value in (("A", 10), ("B", 20), ("C", 70)):      # total missing in month 2
        _obs(con, sid, 2, value)

    report = check_additive_breakdowns(con)

    assert report.months_compared == 0 and not report.mismatches
    assert [(i.observation_date, i.children_present, i.total) for i in report.incomplete] == [
        ("2025-01-28", 2, 100.0), ("2025-02-28", 3, None)]
