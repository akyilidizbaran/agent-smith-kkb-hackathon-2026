"""``align_frequency`` -- move one series onto a coarser calendar period, or refuse."""

from __future__ import annotations

from statistics import fmean
from typing import Any, Final

import duckdb
import pandas as pd

from ._observations import Observation, entity_ids, lineage_of, load_observations
from ._semantics import (
    SeriesSemantics,
    load_semantics,
    require_active_status,
    require_trusted_semantics,
    resolve_aggregation,
)
from .errors import refuse
from .periods import period_bounds, require_downsampling


ALIGNED_COLUMNS: Final[tuple[str, ...]] = (
    "series_id",
    "entity_id",
    "period_start",
    "period_end",
    "value",
    "quality_flag",
    "measure_type",
    "unit",
    "aggregation",
    "source_frequency",
    "target_frequency",
    "observations",
    "missing_observations",
    "warned_observations",
    "source_observation_dates",
    "artifact_sha256_list",
    "vintage_id_list",
    "run_id_list",
)
"""Gold aligned-frame columns, in contract order."""

GOLD_QUALITY_FLAGS: Final[frozenset[str]] = frozenset(
    {"ok", "source_warning", "partial_period", "boundary_missing", "boundary_shifted", "missing_value"}
)
"""Period-level quality vocabulary.

Precedence, strongest first:

- ``missing_value`` -- every contributing observation was missing, so the period has no value.
- ``boundary_missing`` -- a boundary rule (``last``/``first``) selected an observation that
  the source published as missing. The period has readings, but not the one the rule asks
  for, so the result is NULL. This is distinct from ``missing_value``: "we have data but not
  the closing reading" is a different fact from "we have no data". Applies to ``stock``-like
  series only; see ``boundary_shifted``.
- ``boundary_shifted`` -- the boundary reading of an ``index`` or ``rate`` series was a
  calendar gap (a market holiday, a weekend the source lists as NULL) and the rule took the
  nearest published reading inside the period instead: the month's closing index is by
  definition its last trading day's close. ``source_observation_dates`` names that day.
- ``partial_period`` -- some observations were missing, so a value rule rests on fewer
  readings than the period contains.
- ``source_warning`` -- a parser warning applies to at least one contributing observation.
- ``ok``.

The counts are kept alongside the flag so a consumer never has to reverse-engineer the case.
"""

_BOUNDARY_RULES: Final[frozenset[str]] = frozenset({"first", "last"})
"""Rules that select one observation by position rather than computing over several.

These must pick from **all** observations in the period, not from the non-missing ones. A
stock whose closing reading is missing has an unknown closing balance; reaching back to an
earlier week would be carrying the previous value forward, which is exactly the interpolation
this layer promises never to do.
"""

_CALENDAR_GAP_TYPES: Final[frozenset[str]] = frozenset({"index", "rate"})
"""Measure types whose boundary reading may legitimately fall on a calendar gap.

A price index or a market rate is quoted only on trading days; the source still publishes the
holiday as a NULL row (EVDS, BIST 100: 31 March 2025 and 1 April 2025 were a public holiday,
so "March 2025" closed on the 28th). Skipping that NULL is not a forward fill of an unknown
balance -- the month's closing quote *is* the last trading day's quote. Measured 22 Sept 2026:
without this the agent reported "March 2025 missing" for an index the exchange published every
trading day. Stocks keep the strict rule above: a missing closing balance stays unknown.
"""


def _combine(values: list[float], rule: str, series_id: str) -> float:
    if rule == "sum":
        return float(sum(values))
    if rule == "avg":
        return float(fmean(values))
    if rule == "min":
        return float(min(values))
    if rule == "max":
        return float(max(values))
    if rule == "first":
        return float(values[0])
    if rule == "last":
        return float(values[-1])
    raise refuse(
        "UNSUPPORTED_AGGREGATION_RULE",
        f"aggregation rule {rule!r} is not implemented",
        series_id=series_id,
    )


def _period_row(
    semantics: SeriesSemantics,
    *,
    entity_id: str | None,
    period_start: Any,
    period_end: Any,
    members: list[Observation],
    rule: str,
    target_frequency: str,
    identity: bool,
) -> dict[str, Any]:
    """Reduce one period's observations to a single Gold row."""

    present = [item for item in members if not item.is_missing]
    missing = len(members) - len(present)
    warned = sum(1 for item in members if item.quality_flag == "source_warning")

    if identity and len(members) != 1:
        raise refuse(
            "PERIOD_GRAIN_CONFLICT",
            f"a {semantics.frequency} series must publish exactly one observation per "
            f"{target_frequency} period, but {period_start}..{period_end} holds {len(members)}",
            series_id=semantics.series_id,
        )

    value: float | None
    if not present:
        # Every contributing observation was missing. The period has no value; producing 0
        # here would turn "the source did not publish" into "the source published a zero".
        value = None
        flag = "missing_value"
    elif identity:
        value = members[0].value
        flag = "source_warning" if warned else "ok"
    elif rule in _BOUNDARY_RULES:
        # Select by position over *every* observation, then take that observation's value as
        # published. `members` is chronological, so `last` really is the period's final
        # reading and `first` its opening one.
        selected = members[0] if rule == "first" else members[-1]
        shifted = False
        if selected.is_missing and semantics.measure_type in _CALENDAR_GAP_TYPES:
            # Calendar gap on a quoted series: the nearest published reading inside the
            # period is the boundary quote (see _CALENDAR_GAP_TYPES). `present` is non-empty
            # here because the all-missing case returned above.
            selected = present[0] if rule == "first" else present[-1]
            shifted = True
        value = selected.value
        if selected.is_missing:
            flag = "boundary_missing"
        elif shifted:
            flag = "boundary_shifted"
        elif missing:
            flag = "partial_period"
        elif warned:
            flag = "source_warning"
        else:
            flag = "ok"
    else:
        # Value rules (`sum`, `avg`, `min`, `max`) compute over the readings that exist. The
        # partial-null policy applies here and only here.
        value = _combine([item.value for item in present], rule, semantics.series_id)
        if missing:
            flag = "partial_period"
        elif warned:
            flag = "source_warning"
        else:
            flag = "ok"

    return {
        "series_id": semantics.series_id,
        "entity_id": entity_id,
        "period_start": period_start,
        "period_end": period_end,
        "value": value,
        "quality_flag": flag,
        "measure_type": semantics.measure_type,
        "unit": semantics.unit,
        "aggregation": "identity" if identity else rule,
        "source_frequency": semantics.frequency,
        "target_frequency": target_frequency,
        "observations": len(members),
        "missing_observations": missing,
        "warned_observations": warned,
        **lineage_of(members),
    }


def align_frequency(
    connection: duckdb.DuckDBPyConnection,
    series_id: str,
    target_frequency: str,
    *,
    allow_unverified_semantics: bool = False,
) -> pd.DataFrame:
    """Aggregate one Silver series onto ``monthly`` or ``quarterly`` calendar periods.

    How the observations are combined is decided by ``meta.series`` alone: ``measure_type``
    picks the rule, and where a measure type does not determine one on its own the catalog's
    ``default_agg`` does. Neither the caller nor a model can supply or override those values;
    the only knob is ``allow_unverified_semantics``, which relaxes the confidence gate and
    nothing else.

    Refuses, rather than guessing, when: the series is not catalogued, its semantics are not
    verified, its measure type has no safe rule, the request is upsampling, or more than one
    reading exists for the same period.

    Rows are labelled by period end and carry the full provenance of every observation that
    contributed to them.
    """

    semantics = load_semantics(connection, series_id)
    require_active_status(semantics)
    require_trusted_semantics(
        semantics, allow_unverified_semantics=allow_unverified_semantics
    )
    require_downsampling(
        semantics.frequency, target_frequency, series_id=series_id
    )
    rule = resolve_aggregation(semantics)
    identity = semantics.frequency == target_frequency

    records: list[dict[str, Any]] = []
    for entity in entity_ids(connection, series_id):
        observations = load_observations(connection, series_id, entity_id=entity)
        grouped: dict[tuple[Any, Any], list[Observation]] = {}
        for item in observations:
            key = period_bounds(item.observation_date, target_frequency)
            grouped.setdefault(key, []).append(item)
        for (period_start, period_end), members in sorted(grouped.items()):
            # `load_observations` already returns oldest first, so "last" really is the
            # chronologically final reading in the period.
            records.append(
                _period_row(
                    semantics,
                    entity_id=entity,
                    period_start=period_start,
                    period_end=period_end,
                    members=members,
                    rule=rule,
                    target_frequency=target_frequency,
                    identity=identity,
                )
            )

    frame = pd.DataFrame.from_records(records, columns=ALIGNED_COLUMNS)
    frame["value"] = pd.Series(
        [record["value"] for record in records], dtype=object, index=frame.index
    )
    return frame.sort_values(
        ["series_id", "entity_id", "period_start"], na_position="first"
    ).reset_index(drop=True)


__all__ = ["ALIGNED_COLUMNS", "GOLD_QUALITY_FLAGS", "align_frequency"]
