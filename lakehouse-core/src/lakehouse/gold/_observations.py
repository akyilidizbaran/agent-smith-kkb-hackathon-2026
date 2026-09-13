"""Read Silver observations for one series, with the vintage gate applied.

Gold never reads Bronze, never reads a Parquet file, and never writes anything. It issues
parameterized ``SELECT`` statements against ``silver.fact_observation`` and ``meta.series``
only, so it runs unchanged on the hardened read-only connection the agent uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb

from .errors import refuse


SILVER_RELATION = "silver.fact_observation"
"""The only fact relation Gold reads."""


@dataclass(frozen=True)
class Observation:
    """One Silver row, reduced to what a Gold transformation needs."""

    observation_date: date
    value: float | None
    quality_flag: str
    entity_id: str | None
    artifact_sha256: str
    vintage_id: str | None
    run_id: str | None

    @property
    def is_missing(self) -> bool:
        return self.value is None


def _assert_no_ambiguous_vintage(
    connection: duckdb.DuckDBPyConnection, series_id: str, entity_id: str | None
) -> None:
    """Refuse a series whose grain carries more than one reading for the same date.

    Silver deliberately keeps every vintage: its duplicate gate includes
    ``artifact_sha256``, so two artifacts reporting the same period both survive. That is
    correct for an append-only fact table and wrong to resolve silently here. There is no
    current-vintage policy in this repository yet, so Gold fails closed and names the
    conflict rather than picking the newest, the largest or the first.
    """

    conflicts = connection.execute(
        f"""
        SELECT observation_date,
               count(*) AS readings,
               count(DISTINCT artifact_sha256) AS artifacts
        FROM {SILVER_RELATION}
        WHERE series_id = ?
          AND entity_id IS NOT DISTINCT FROM ?
        GROUP BY observation_date
        HAVING count(*) > 1
        ORDER BY observation_date
        LIMIT 3
        """,
        [series_id, entity_id],
    ).fetchall()
    if conflicts:
        detail = ", ".join(
            f"{row[0].isoformat()} ({row[1]} readings from {row[2]} artifacts)"
            for row in conflicts
        )
        raise refuse(
            "AMBIGUOUS_VINTAGE",
            "more than one reading exists for the same period and no revision policy is "
            f"defined, so Gold will not choose one: {detail}",
            series_id=series_id,
        )


def entity_ids(connection: duckdb.DuckDBPyConnection, series_id: str) -> list[str | None]:
    """Distinct entities this series carries in Silver, in a stable order.

    A series that covers several populations -- the sector total and one bank group, say --
    must not have them merged into one line, so every Gold function works per entity.
    """

    rows = connection.execute(
        f"""
        SELECT DISTINCT entity_id
        FROM {SILVER_RELATION}
        WHERE series_id = ?
        ORDER BY entity_id NULLS FIRST
        """,
        [series_id],
    ).fetchall()
    if not rows:
        # A catalogued series with no rows in the current snapshot is a real answer -- "we
        # hold nothing for this" -- and must be said out loud. Returning an empty frame would
        # let a caller render an empty chart as though the period genuinely had no activity.
        raise refuse(
            "NO_OBSERVATIONS",
            "the series is catalogued but the current Silver snapshot holds no observations "
            "for it",
            series_id=series_id,
        )
    return [row[0] for row in rows]


def load_observations(
    connection: duckdb.DuckDBPyConnection,
    series_id: str,
    *,
    entity_id: str | None,
) -> list[Observation]:
    """Return every Silver observation for one series and entity, oldest first."""

    _assert_no_ambiguous_vintage(connection, series_id, entity_id)

    rows = connection.execute(
        f"""
        SELECT observation_date, value, quality_flag, entity_id,
               artifact_sha256, vintage_id, run_id
        FROM {SILVER_RELATION}
        WHERE series_id = ?
          AND entity_id IS NOT DISTINCT FROM ?
        ORDER BY observation_date
        """,
        [series_id, entity_id],
    ).fetchall()
    if not rows:
        raise refuse(
            "NO_OBSERVATIONS",
            "the Silver snapshot holds no observations for this series and entity",
            series_id=series_id,
        )
    return [
        Observation(
            observation_date=row[0],
            value=None if row[1] is None else float(row[1]),
            quality_flag=row[2],
            entity_id=row[3],
            artifact_sha256=row[4],
            vintage_id=row[5],
            run_id=row[6],
        )
        for row in rows
    ]


def lineage_of(observations: list[Observation]) -> dict[str, Any]:
    """Collapse the provenance of a group of observations without losing any of it."""

    return {
        "artifact_sha256_list": sorted({item.artifact_sha256 for item in observations}),
        "vintage_id_list": sorted(
            {item.vintage_id for item in observations if item.vintage_id is not None}
        ),
        "run_id_list": sorted(
            {item.run_id for item in observations if item.run_id is not None}
        ),
        "source_observation_dates": [item.observation_date for item in observations],
    }


__all__ = [
    "SILVER_RELATION",
    "Observation",
    "entity_ids",
    "lineage_of",
    "load_observations",
]
