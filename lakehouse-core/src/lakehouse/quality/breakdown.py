"""Additive breakdown check: the children of an additive total must sum to that total.

ADR-0108 stores opening-maturity buckets as their own monthly series and lets the agent build
any maturity group from them at query time. That is only correct if the buckets really are the
parts of the published total, month by month. This check reads the relation graph
(``meta.series_relation``) and Silver, and reports every month where they disagree.

Rules:

- A month is compared only when the total and **every** child have a value. A missing child is
  reported as incomplete, never filled with zero: a zero would make the sum look plausible
  while hiding the gap.
- The tolerance comes from the source's rounding, not from a guess: BDDK prints each column
  rounded to a whole milyon TL, so ``n`` children can drift from the total by at most
  ``0.5 * n`` (six buckets: 3). Measured on 2026-09-23 the largest drift was 2.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class BreakdownIssue:
    """One month of one additive total that does not reconcile with its children."""

    parent_series_id: str
    observation_date: str
    kind: str                 # "mismatch" | "incomplete"
    total: float | None
    children_sum: float | None
    children_present: int
    children_expected: int

    @property
    def difference(self) -> float | None:
        if self.total is None or self.children_sum is None:
            return None
        return self.children_sum - self.total


@dataclass(frozen=True)
class BreakdownReport:
    parents_checked: int
    months_compared: int
    issues: tuple[BreakdownIssue, ...]

    @property
    def mismatches(self) -> tuple[BreakdownIssue, ...]:
        return tuple(issue for issue in self.issues if issue.kind == "mismatch")

    @property
    def incomplete(self) -> tuple[BreakdownIssue, ...]:
        return tuple(issue for issue in self.issues if issue.kind == "incomplete")


def check_additive_breakdowns(
    connection: duckdb.DuckDBPyConnection,
    *,
    dimension_prefix: str = "vade_ay=",
    rounding_per_child: float = 0.5,
    relation: str = "silver.fact_observation",
) -> BreakdownReport:
    """Compare every additive total with the sum of its children carrying ``dimension_prefix``.

    Only children whose ``dimension_path`` has an entry starting with ``dimension_prefix`` take
    part, so a parent whose other children are not a complete partition is not checked.
    """

    rows = connection.execute(
        f"""
        WITH kids AS (
            SELECT r.parent_series_id, r.series_id
            FROM meta.series_relation r
            JOIN meta.series_relation p ON p.series_id = r.parent_series_id
            WHERE r.relation_type = 'child_breakdown'
              AND p.additivity = 'additive'
              AND len(list_filter(r.dimension_path, d -> starts_with(d, ?))) > 0
        ),
        expected AS (
            SELECT parent_series_id, count(*) AS n FROM kids GROUP BY 1
        ),
        child_obs AS (
            SELECT k.parent_series_id, o.observation_date,
                   sum(o.value) AS children_sum,
                   count(o.value) AS present
            FROM kids k JOIN {relation} o ON o.series_id = k.series_id
            GROUP BY 1, 2
        ),
        totals AS (
            SELECT o.series_id AS parent_series_id, o.observation_date, o.value AS total
            FROM {relation} o WHERE o.series_id IN (SELECT parent_series_id FROM expected)
        ),
        months AS (
            SELECT parent_series_id, observation_date FROM totals
            UNION
            SELECT parent_series_id, observation_date FROM child_obs
        )
        SELECT m.parent_series_id, CAST(m.observation_date AS VARCHAR) AS observation_date,
               t.total, c.children_sum, coalesce(c.present, 0) AS present, e.n
        FROM months m
        JOIN expected e ON e.parent_series_id = m.parent_series_id
        LEFT JOIN totals t ON t.parent_series_id = m.parent_series_id AND t.observation_date = m.observation_date
        LEFT JOIN child_obs c ON c.parent_series_id = m.parent_series_id AND c.observation_date = m.observation_date
        ORDER BY 1, 2
        """,
        [dimension_prefix],
    ).fetchall()

    issues: list[BreakdownIssue] = []
    parents: set[str] = set()
    compared = 0
    for parent, month, total, children_sum, present, expected in rows:
        parents.add(parent)
        if total is None or present < expected:
            issues.append(BreakdownIssue(parent, month, "incomplete", total,
                                         children_sum if present == expected else None,
                                         int(present), int(expected)))
            continue
        compared += 1
        if abs(children_sum - total) > rounding_per_child * expected:
            issues.append(BreakdownIssue(parent, month, "mismatch", total, children_sum,
                                         int(present), int(expected)))
    return BreakdownReport(len(parents), compared, tuple(issues))


__all__ = ["BreakdownIssue", "BreakdownReport", "check_additive_breakdowns"]
