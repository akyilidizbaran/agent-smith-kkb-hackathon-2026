"""Promote a draft ad-hoc series into the trusted query surface, on a human's say-so.

Programmatic registration only ever writes ``draft`` rows (:mod:`.registration`): a machine
can propose semantics, it cannot vouch for them. Promotion is the human step that was
missing between "the file landed as a draft" and "Gold can compute on it". Who the human
is does not change the rule: a reviewer editing ``catalog/series/*.yml``, or the person in
the chat saying "approve this draft" and having the agent relay it. Either way the record
says so: ``semantic_source`` becomes ``manual`` and ``semantic_confidence`` stays
``derived`` -- nobody verified the semantics against source documentation, a person
accepted the profiler's proposal. Gold therefore still asks for explicit consent
(``allow_unverified_semantics``) before combining these numbers.

What promotion does, in one transaction:

1. ``meta.series``: ``status`` ``draft`` → ``active`` (only from ``draft``; curated rows
   are never touched), ``semantic_source`` → ``manual``.
2. ``silver.fact_observation``: the series' rows are copied from ``adhoc.fact_observation``
   with their provenance untouched (artifact, run, vintage, fetched_at). Existing Silver rows
   of the same series are replaced, so promoting twice is idempotent.

The Silver rebuild (:mod:`..silver.build`) applies the same rule -- active ad-hoc series
are appended to every snapshot -- so a promotion survives ``python -m lakehouse silver``.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

ADHOC_SOURCE_ID = "adhoc"
SILVER_RELATION = "silver.fact_observation"
ADHOC_RELATION = "adhoc.fact_observation"


class PromotionError(ValueError):
    """The series cannot be promoted: missing, not a draft, not ad-hoc, or no observations."""


@dataclass(frozen=True)
class PromotionResult:
    series_id: str
    previous_status: str
    rows_promoted: int
    silver_rows_replaced: int


def ensure_silver_relation(connection: duckdb.DuckDBPyConnection) -> None:
    """Silver may not exist yet on a fresh database (the snapshot creates it). The ad-hoc
    table has the same columns in the same order by contract, so an empty copy of its layout
    is a valid Silver until the next ``silver`` rebuild replaces it through the model."""

    exists = connection.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'silver' AND table_name = 'fact_observation'"
    ).fetchone()[0]
    if not exists:
        connection.execute(f"CREATE TABLE {SILVER_RELATION} AS SELECT * FROM {ADHOC_RELATION} WHERE 1 = 0")


def copy_active_adhoc_to_silver(
    connection: duckdb.DuckDBPyConnection, *, series_id: str | None = None
) -> int:
    """Copy active ad-hoc series rows into Silver (all of them, or one series). Idempotent."""

    ensure_silver_relation(connection)
    where = "s.source_id = ? AND s.status = 'active'"
    params: list[object] = [ADHOC_SOURCE_ID]
    if series_id is not None:
        where += " AND s.series_id = ?"
        params.append(series_id)
    connection.execute(
        f"""
        DELETE FROM {SILVER_RELATION}
        WHERE series_id IN (SELECT s.series_id FROM meta.series s WHERE {where})
        """,
        params,
    )
    connection.execute(
        f"""
        INSERT INTO {SILVER_RELATION}
        SELECT a.* FROM {ADHOC_RELATION} a
        JOIN meta.series s ON s.series_id = a.series_id
        WHERE {where}
        """,
        params,
    )
    return int(
        connection.execute(
            f"SELECT count(*) FROM {SILVER_RELATION} WHERE series_id IN "
            f"(SELECT s.series_id FROM meta.series s WHERE {where})",
            params,
        ).fetchone()[0]
    )


def promote_draft_series(connection: duckdb.DuckDBPyConnection, series_id: str) -> PromotionResult:
    """Draft → active, rows → Silver; refuses anything that is not an ad-hoc draft."""

    row = connection.execute(
        "SELECT source_id, status FROM meta.series WHERE series_id = ?", [series_id]
    ).fetchone()
    if row is None:
        raise PromotionError(f"{series_id!r} is not in meta.series")
    source_id, status = row
    if source_id != ADHOC_SOURCE_ID:
        raise PromotionError(
            f"{series_id!r} is a curated series (source {source_id!r}); promotion applies to "
            "ad-hoc drafts only, curated semantics change through catalog/series/*.yml"
        )
    if status != "draft":
        raise PromotionError(f"{series_id!r} has status {status!r}; only 'draft' can be promoted")
    n_rows = int(
        connection.execute(
            f"SELECT count(*) FROM {ADHOC_RELATION} WHERE series_id = ?", [series_id]
        ).fetchone()[0]
    )
    if n_rows == 0:
        raise PromotionError(f"{series_id!r} has no observations in {ADHOC_RELATION}; nothing to promote")

    ensure_silver_relation(connection)
    connection.begin()
    try:
        replaced = int(
            connection.execute(
                f"SELECT count(*) FROM {SILVER_RELATION} WHERE series_id = ?", [series_id]
            ).fetchone()[0]
        )
        connection.execute(
            """
            UPDATE meta.series
            SET status = 'active', semantic_source = 'manual', updated_at = current_timestamp
            WHERE series_id = ?
            """,
            [series_id],
        )
        promoted = copy_active_adhoc_to_silver(connection, series_id=series_id)
        # Coverage is an operational fact derived from Silver (silver/coverage.py). Without this the promoted
        # series kept first_obs/last_obs NULL until the next full `lakehouse silver` rebuild, and the agent
        # answered "coverage unknown" for a series whose rows were already in Silver (observed 20 Sep).
        from ..silver.coverage import refresh_series_coverage

        refresh_series_coverage(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return PromotionResult(
        series_id=series_id, previous_status=status, rows_promoted=promoted, silver_rows_replaced=replaced
    )


__all__ = ["PromotionError", "PromotionResult", "copy_active_adhoc_to_silver", "ensure_silver_relation", "promote_draft_series"]
