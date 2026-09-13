"""``join_on_period`` -- put several series on one period axis without hiding the gaps."""

from __future__ import annotations

from typing import Any, Final

import duckdb
import pandas as pd

from .align import align_frequency
from .errors import refuse


JOIN_KEY_COLUMNS: Final[tuple[str, ...]] = ("period_start", "period_end")
"""The shared axis. Every other column belongs to exactly one series."""

_PER_SERIES_FIELDS: Final[tuple[str, ...]] = (
    "value",
    "quality_flag",
    "measure_type",
    "unit",
    "aggregation",
    "observations",
    "missing_observations",
    "warned_observations",
    "source_observation_dates",
    "artifact_sha256_list",
    "vintage_id_list",
    "run_id_list",
)
"""Fields carried through per series, each prefixed with that series' column key.

``source_observation_dates`` is here so a joined cell can be traced back to the exact source
readings behind it, the same way an aligned row can.
"""

_EMPTY_LIST_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "source_observation_dates",
        "artifact_sha256_list",
        "vintage_id_list",
        "run_id_list",
    }
)
"""List-valued fields. When a series published nothing in a period these are **empty lists**,
not NULL: "this series contributed no readings here" is a fact, and an empty list says it
without a consumer having to distinguish None from a missing key."""

_ZERO_FIELDS: Final[frozenset[str]] = frozenset(
    {"observations", "missing_observations", "warned_observations"}
)
"""Counts. Absent means zero contributing readings, which is a number, not an unknown."""


def column_key(series_id: str, entity_id: str | None) -> str:
    """The prefix that identifies one aligned line in the joined frame.

    The entity is part of the key because a series can carry several populations, and merging
    the sector total with one bank group under a single column would be exactly the kind of
    silent conflation this layer exists to prevent.
    """

    return series_id if entity_id is None else f"{series_id}@{entity_id}"


def join_on_period(
    connection: duckdb.DuckDBPyConnection,
    series_ids: list[str],
    target_frequency: str,
    *,
    allow_unverified_semantics: bool = False,
) -> pd.DataFrame:
    """Align every requested series on its own catalog rule, then join on the period axis.

    Each series is aggregated with the rule its own ``meta.series`` row prescribes, so a
    weekly interest rate is averaged while a weekly loan stock takes its closing value, in the
    same call. If any series cannot be transformed safely the whole call is refused, because a
    comparison table quietly missing one of its columns is worse than no table.

    The join is an **outer** join over the union of periods: a period where only one series
    published still appears, with the other side left NULL and its ``observations`` count at
    zero. Coverage differences stay visible instead of being trimmed away by an inner join.
    """

    if not isinstance(series_ids, (list, tuple)) or not series_ids:
        raise refuse("INVALID_ARGUMENT", "series_ids must be a non-empty list")
    for position, candidate in enumerate(series_ids):
        if not isinstance(candidate, str) or not candidate.strip():
            raise refuse(
                "INVALID_ARGUMENT",
                f"series_ids[{position}] must be a non-empty string, got {candidate!r}",
            )
    if len(set(series_ids)) != len(series_ids):
        raise refuse(
            "INVALID_ARGUMENT", f"series_ids contains duplicates: {series_ids}"
        )
    if not isinstance(allow_unverified_semantics, bool):
        raise refuse(
            "INVALID_ARGUMENT",
            "allow_unverified_semantics must be a real bool, got "
            f"{type(allow_unverified_semantics).__name__}",
        )

    aligned: list[tuple[str, pd.DataFrame]] = []
    series_id_of: dict[str, str] = {}
    for series_id in series_ids:
        frame = align_frequency(
            connection,
            series_id,
            target_frequency,
            allow_unverified_semantics=allow_unverified_semantics,
        )
        for entity_id, group in frame.groupby("entity_id", dropna=False, sort=True):
            key = column_key(series_id, None if pd.isna(entity_id) else entity_id)
            series_id_of[key] = series_id
            aligned.append((key, group.reset_index(drop=True)))

    keys = [key for key, _ in aligned]
    if len(set(keys)) != len(keys):
        raise refuse(
            "INVALID_ARGUMENT",
            f"two aligned lines share the column key {sorted(keys)}",
        )

    periods = sorted(
        {
            (row["period_start"], row["period_end"])
            for _, frame in aligned
            for _, row in frame.iterrows()
        }
    )
    if not periods:
        raise refuse("NO_OBSERVATIONS", "no series produced any period")

    records: list[dict[str, Any]] = []
    for period_start, period_end in periods:
        record: dict[str, Any] = {
            "period_start": period_start,
            "period_end": period_end,
        }
        present: list[str] = []
        absent: list[str] = []
        for key, frame in aligned:
            match = frame[frame["period_start"] == period_start]
            if match.empty:
                absent.append(key)
                for field in _PER_SERIES_FIELDS:
                    if field in _ZERO_FIELDS:
                        record[f"{key}::{field}"] = 0
                    elif field in _EMPTY_LIST_FIELDS:
                        record[f"{key}::{field}"] = []
                    else:
                        record[f"{key}::{field}"] = None
                # The series is still named, so an absent cell is attributable.
                record[f"{key}::series_id"] = series_id_of[key]
            else:
                present.append(key)
                row = match.iloc[0]
                for field in _PER_SERIES_FIELDS:
                    record[f"{key}::{field}"] = row[field]
                record[f"{key}::series_id"] = row["series_id"]
        record["contributing_series"] = present
        record["absent_series"] = absent
        record["is_complete_period"] = not absent
        records.append(record)

    columns = list(JOIN_KEY_COLUMNS)
    for key, _ in aligned:
        columns.append(f"{key}::series_id")
        columns.extend(f"{key}::{field}" for field in _PER_SERIES_FIELDS)
    columns.extend(["contributing_series", "absent_series", "is_complete_period"])

    frame = pd.DataFrame.from_records(records, columns=columns)
    for key, _ in aligned:
        name = f"{key}::value"
        frame[name] = pd.Series(
            [record[name] for record in records], dtype=object, index=frame.index
        )
    return frame.reset_index(drop=True)


__all__ = ["JOIN_KEY_COLUMNS", "column_key", "join_on_period"]
