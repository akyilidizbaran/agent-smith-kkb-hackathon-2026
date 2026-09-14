"""Operational coverage for ``meta.series``, computed from the Silver snapshot.

``meta.series.first_obs`` / ``last_obs`` describe *observed* coverage. The catalog contract
is explicit that they are operational, not catalog fields, and that the YAML loader must
never write or clear them. This module is the operational half of that split: it derives
them from ``silver.fact_observation`` and from nothing else.

Why it lives under ``silver/`` rather than ``catalog/``: the values are defined entirely by
what the current Silver snapshot contains, so the operation belongs to the layer that
produces that snapshot. The ``catalog`` package stays purely about loading human-authored
semantics.
"""

from __future__ import annotations

import duckdb


COVERAGE_SOURCE_RELATION = "silver.fact_observation"
"""The only relation coverage may be derived from."""


class CoverageError(RuntimeError):
    """Raised when coverage cannot be derived from a usable Silver snapshot."""


def _silver_snapshot_exists(connection: duckdb.DuckDBPyConnection) -> bool:
    return (
        connection.execute(
            """
            SELECT count(*)
            FROM information_schema.tables
            WHERE table_schema = 'silver' AND table_name = 'fact_observation'
            """
        ).fetchone()[0]
        > 0
    )


def refresh_series_coverage(connection: duckdb.DuckDBPyConnection) -> int:
    """Recompute ``first_obs`` / ``last_obs`` for **every** catalogued series.

    Returns the number of series that ended up with a non-NULL coverage window.

    Behaviour that matters:

    - Coverage is derived only from ``silver.fact_observation``. No source name, series id or
      frequency is hard-coded, so a series added to the catalog tomorrow is covered with no
      code change.
    - Because Silver materialization is a **whole-snapshot replacement**, a series that is not
      in the current snapshot must not keep a stale window. Every catalogued series is
      recomputed in one statement, and ``MIN``/``MAX`` over no matching rows yields ``NULL``,
      so disappearing from the snapshot clears the window rather than freezing it.
    - An empty snapshot is a legitimate state: every series gets ``NULL`` coverage and the
      function returns ``0``.
    - A **missing** snapshot is not the same thing as an empty one and raises
      :class:`CoverageError`. Silently NULLing the whole catalog because nobody materialized
      Silver yet would look identical to a real "we have no data" answer.

    The statement is a single ``UPDATE``, so it either applies to every series or to none.
    """

    if not _silver_snapshot_exists(connection):
        raise CoverageError(
            f"{COVERAGE_SOURCE_RELATION} does not exist; materialize a Silver snapshot "
            "before refreshing catalog coverage"
        )

    connection.execute(
        f"""
        UPDATE meta.series AS m
        SET first_obs = (
                SELECT MIN(f.observation_date)
                FROM {COVERAGE_SOURCE_RELATION} AS f
                WHERE f.series_id = m.series_id
            ),
            last_obs = (
                SELECT MAX(f.observation_date)
                FROM {COVERAGE_SOURCE_RELATION} AS f
                WHERE f.series_id = m.series_id
            )
        """
    )

    return connection.execute(
        "SELECT count(*) FROM meta.series WHERE first_obs IS NOT NULL"
    ).fetchone()[0]


__all__ = ["COVERAGE_SOURCE_RELATION", "CoverageError", "refresh_series_coverage"]
