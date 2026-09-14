"""``decompose_cumulative`` -- turn an accumulating series into per-period flows, or say why not.

A cumulative series states a running total. The per-period flow is the change between two
readings, and that subtraction is only valid when both readings are known and the two periods
are adjacent. Every case where it is not, this module marks explicitly instead of producing a
number that looks like a flow but is not one.
"""

from __future__ import annotations

from typing import Any, Final

import duckdb
import pandas as pd

from ._observations import Observation, entity_ids, lineage_of, load_observations
from ._semantics import (
    SeriesSemantics,
    load_semantics,
    require_active_status,
    require_decomposable,
    require_trusted_semantics,
)
from .errors import refuse
from .periods import is_first_period_of_year, period_bounds, previous_period_start


DECOMPOSABLE_SOURCE_FREQUENCIES: Final[frozenset[str]] = frozenset(
    {"monthly", "quarterly"}
)
"""Source frequencies whose period adjacency this version can decide reliably.

A difference is only a single period's flow when the two readings sit in adjacent periods, so
decomposition needs a trustworthy "is the previous reading the previous period?" test. Calendar
months and quarters give one. Weekly and daily series do not: BDDK's own weekly bulletin shifts
to a Thursday on a holiday week, so a 6- or 8-day step is normal publishing rather than a gap,
and treating either as evidence one way would be a guess. Those frequencies are refused with
``UNSUPPORTED_SOURCE_FREQUENCY`` instead of being decomposed on an assumption.
"""

DECOMPOSED_COLUMNS: Final[tuple[str, ...]] = (
    "series_id",
    "entity_id",
    "period_start",
    "period_end",
    "value",
    "decomposition_flag",
    "quality_flag",
    "cumulative_value",
    "previous_cumulative_value",
    "previous_observation_date",
    "raw_change",
    "measure_type",
    "unit",
    "source_frequency",
    "contributor_count",
    "artifact_sha256",
    "vintage_id",
    "run_id",
    "previous_artifact_sha256",
    "previous_vintage_id",
    "previous_run_id",
    "artifact_sha256_list",
    "vintage_id_list",
    "run_id_list",
    "source_observation_dates",
)
"""Decomposed-frame columns, in contract order.

A difference is derived from **two** observations, so both are represented. The current
reading keeps the unprefixed columns, the base keeps the ``previous_*`` ones, and the
``*_list`` columns plus ``contributor_count`` give the same information as a set for callers
that would rather not special-case the single-contributor rows.
"""

DECOMPOSITION_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "ok",
        "no_prior_base",
        "unattributable_year_start",
        "spans_multiple_periods",
        "negative_change",
        "missing_value",
    }
)
"""Why a decomposed row does or does not carry a per-period flow.

- ``ok`` -- the change is between two known, adjacent readings.
- ``no_prior_base`` -- the first reading of a ``flow_cumulative`` series. Its base is whatever
  accumulated before the series starts, which is unknown, so no flow is emitted.
- ``unattributable_year_start`` -- a ``flow_ytd`` year whose first reading is not the year's
  opening period. The value covers every period from January, so attributing it to this one
  period would overstate it. ``raw_change`` keeps the number.
- ``spans_multiple_periods`` -- the previous reading is not the immediately preceding period.
  The change is real but covers the gap too, so it is kept in ``raw_change`` and not published
  as this period's flow.
- ``negative_change`` -- the change is below zero. That is either a genuine negative flow or a
  revision of the running total, and nothing in Silver says which, so the number is emitted
  and flagged rather than silently reinterpreted.
- ``missing_value`` -- this reading or the one it would be measured against is missing.
"""


def _derived_quality(contributors: list[Observation]) -> str:
    """Quality of a derived value, taken from **every** observation that produced it.

    A difference inherits the weakest of its inputs. If the base reading carried a parser
    warning, the flow computed from it is not clean either, even though the current reading
    looks fine on its own.
    """

    if any(item.is_missing for item in contributors):
        return "missing_value"
    if any(item.quality_flag == "source_warning" for item in contributors):
        return "source_warning"
    if any(item.quality_flag == "missing_value" for item in contributors):
        return "missing_value"
    return "ok"


def _row(
    semantics: SeriesSemantics,
    observation: Observation,
    *,
    period_start: Any,
    period_end: Any,
    value: float | None,
    flag: str,
    previous: Observation | None,
    raw_change: float | None,
) -> dict[str, Any]:
    contributors = [observation] if previous is None else [previous, observation]
    return {
        "series_id": semantics.series_id,
        "entity_id": observation.entity_id,
        "period_start": period_start,
        "period_end": period_end,
        "value": value,
        "decomposition_flag": flag,
        "quality_flag": _derived_quality(contributors),
        "cumulative_value": observation.value,
        "previous_cumulative_value": None if previous is None else previous.value,
        "previous_observation_date": None if previous is None else previous.observation_date,
        "raw_change": raw_change,
        "measure_type": semantics.measure_type,
        "unit": semantics.unit,
        "source_frequency": semantics.frequency,
        "contributor_count": len(contributors),
        "artifact_sha256": observation.artifact_sha256,
        "vintage_id": observation.vintage_id,
        "run_id": observation.run_id,
        "previous_artifact_sha256": None if previous is None else previous.artifact_sha256,
        "previous_vintage_id": None if previous is None else previous.vintage_id,
        "previous_run_id": None if previous is None else previous.run_id,
        **lineage_of(contributors),
    }


def decompose_cumulative(
    connection: duckdb.DuckDBPyConnection,
    series_id: str,
    *,
    allow_unverified_semantics: bool = False,
) -> pd.DataFrame:
    """Convert a ``flow_ytd`` or ``flow_cumulative`` series into per-period flows.

    The kind of accumulation, and for ``flow_ytd`` the reset boundary, are read from
    ``meta.series``; neither is a parameter. Output keeps the source frequency -- this function
    changes what a value *means*, not which period it belongs to.

    Every row states its own status in ``decomposition_flag`` and keeps the untouched
    cumulative reading, so a caller can always see what the number was derived from.

    **The result cannot be fed to** :func:`~lakehouse.gold.align.align_frequency`. That
    function reads Silver by ``series_id``; it does not accept a frame, and asking it for this
    series again would return the same ``DECOMPOSITION_REQUIRED`` refusal. Downsampling a
    decomposed series is deliberately out of scope for V1 -- summing per-period flows across a
    quarter is only correct when every period in that quarter produced an attributable flow,
    and rows flagged ``no_prior_base``, ``unattributable_year_start`` or
    ``spans_multiple_periods`` carry no value, so a naive sum would silently understate the
    quarter. See ``docs/gold-contract.md`` for what a safe composition path would need.
    """

    semantics = load_semantics(connection, series_id)
    require_active_status(semantics)
    require_trusted_semantics(
        semantics, allow_unverified_semantics=allow_unverified_semantics
    )
    kind = require_decomposable(semantics)
    frequency = semantics.frequency
    if frequency not in DECOMPOSABLE_SOURCE_FREQUENCIES:
        raise refuse(
            "UNSUPPORTED_SOURCE_FREQUENCY",
            f"decomposition needs a reliable period-adjacency test and this version has one "
            f"only for {sorted(DECOMPOSABLE_SOURCE_FREQUENCIES)}, not {frequency!r}; a "
            "multi-period difference must never be published as one period's flow",
            series_id=series_id,
        )

    records: list[dict[str, Any]] = []
    for entity in entity_ids(connection, series_id):
        observations = load_observations(connection, series_id, entity_id=entity)

        # Frequency is monthly or quarterly here, so every observation maps to exactly one
        # period and two readings in one period is a grain problem, not a gap.
        seen_periods: dict[Any, Any] = {}
        for observation in observations:
            start, _ = period_bounds(observation.observation_date, frequency)
            if start in seen_periods:
                raise refuse(
                    "PERIOD_GRAIN_CONFLICT",
                    f"a {frequency} cumulative series must publish once per period, but "
                    f"{start} holds readings on {seen_periods[start]} and "
                    f"{observation.observation_date}; differencing them would compare a "
                    "period against itself",
                    series_id=series_id,
                )
            seen_periods[start] = observation.observation_date

        previous: Observation | None = None
        for observation in observations:
            period_start, period_end = period_bounds(
                observation.observation_date, frequency
            )

            if observation.is_missing:
                records.append(
                    _row(
                        semantics,
                        observation,
                        period_start=period_start,
                        period_end=period_end,
                        value=None,
                        flag="missing_value",
                        previous=previous,
                        raw_change=None,
                    )
                )
                # A missing reading cannot become the base for the next difference.
                previous = None
                continue

            starts_new_year = (
                kind == "flow_ytd"
                and previous is not None
                and previous.observation_date.year != observation.observation_date.year
            )
            base: Observation | None = None if starts_new_year else previous

            if base is None:
                if kind == "flow_ytd" and is_first_period_of_year(period_start, frequency):
                    # January's year-to-date total is January's own flow, and it rests on this
                    # single reading -- contributor_count reflects that.
                    flag, value, raw_change = "ok", observation.value, observation.value
                elif kind == "flow_ytd":
                    flag, value = "unattributable_year_start", None
                    raw_change = observation.value
                else:
                    flag, value, raw_change = "no_prior_base", None, None
                records.append(
                    _row(
                        semantics,
                        observation,
                        period_start=period_start,
                        period_end=period_end,
                        value=value,
                        flag=flag,
                        previous=None,
                        raw_change=raw_change,
                    )
                )
                previous = observation
                continue

            change = observation.value - base.value
            base_start, _ = period_bounds(base.observation_date, frequency)
            adjacent = base_start == previous_period_start(period_start, frequency)

            if not adjacent:
                flag, value = "spans_multiple_periods", None
            elif change < 0:
                flag, value = "negative_change", change
            else:
                flag, value = "ok", change

            records.append(
                _row(
                    semantics,
                    observation,
                    period_start=period_start,
                    period_end=period_end,
                    value=value,
                    flag=flag,
                    previous=base,
                    raw_change=change,
                )
            )
            previous = observation

    frame = pd.DataFrame.from_records(records, columns=DECOMPOSED_COLUMNS)
    for column in ("value", "cumulative_value", "previous_cumulative_value", "raw_change"):
        frame[column] = pd.Series(
            [record[column] for record in records], dtype=object, index=frame.index
        )
    return frame.sort_values(
        ["series_id", "entity_id", "period_start"], na_position="first"
    ).reset_index(drop=True)


__all__ = ["DECOMPOSED_COLUMNS", "DECOMPOSITION_FLAGS", "decompose_cumulative"]
