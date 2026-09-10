"""Deterministic EVDS request windows and conservative result reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from ..contracts.models import FetchedAsset, FetchSpec, ParsedBatch
from ..errors import ERROR_CODES, ErrorPayload, LakehouseError
from .observability import describe_exception


EVDS_MAX_WINDOW_DAYS = 365
"""Inclusive calendar-day cap used for every currently supported EVDS frequency."""

_TRUNCATION_MARKER = "reached the EVDS per-request limit"


@dataclass(frozen=True)
class DateWindow:
    """One inclusive date interval in a planned logical request."""

    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        for name, value in (("start_date", self.start_date), ("end_date", self.end_date)):
            if not isinstance(value, date) or isinstance(value, datetime):
                raise TypeError(f"{name} must be a date")
        if self.start_date > self.end_date:
            raise ValueError("window start_date must not be after end_date")


def plan_evds_windows(
    start_date: date,
    end_date: date,
    *,
    max_window_days: int = EVDS_MAX_WINDOW_DAYS,
    frequency: str | None = None,
) -> tuple[DateWindow, ...]:
    """Split an inclusive EVDS range into stable, gap-free calendar windows.

    The cap is derived from the verified 1,000-observation per-request limit and the
    worst-case supported frequency, daily. It is deliberately not an HTTP rate-limit rule.
    """

    requested = DateWindow(start_date, end_date)
    if isinstance(max_window_days, bool) or not isinstance(max_window_days, int):
        raise TypeError("max_window_days must be an int")
    if max_window_days < 1:
        raise ValueError("max_window_days must be at least 1")
    if frequency is not None and (not isinstance(frequency, str) or not frequency.strip()):
        raise ValueError("frequency must be a non-empty string when supplied")

    windows: list[DateWindow] = []
    cursor = requested.start_date
    while cursor <= requested.end_date:
        window_end = min(
            requested.end_date,
            cursor + timedelta(days=max_window_days - 1),
        )
        windows.append(DateWindow(cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return tuple(windows)


def windowed_fetch_specs(
    spec: FetchSpec,
    windows: tuple[DateWindow, ...] | list[DateWindow],
) -> tuple[FetchSpec, ...]:
    """Create immutable per-window specs while retaining the logical request context."""

    planned = tuple(windows)
    if not planned:
        raise ValueError("at least one date window is required")
    if spec.start_date is None or spec.end_date is None:
        raise ValueError("windowed FetchSpec requires logical start and end dates")
    if planned[0].start_date != spec.start_date or planned[-1].end_date != spec.end_date:
        raise ValueError("windows must cover the FetchSpec logical date range")
    for previous, current in zip(planned, planned[1:]):
        if current.start_date != previous.end_date + timedelta(days=1):
            raise ValueError("windows must be ordered, contiguous, and non-overlapping")

    result: list[FetchSpec] = []
    for index, window in enumerate(planned, start=1):
        parameters = dict(spec.parameters)
        parameters.update(
            {
                "window_index": index,
                "window_count": len(planned),
                "logical_start_date": spec.start_date.isoformat(),
                "logical_end_date": spec.end_date.isoformat(),
            }
        )
        result.append(
            replace(
                spec,
                start_date=window.start_date,
                end_date=window.end_date,
                parameters=parameters,
            )
        )
    return tuple(result)


def _window_context(spec: FetchSpec) -> tuple[DateWindow, int, int]:
    """Read validated window context added by :func:`windowed_fetch_specs`."""

    if spec.start_date is None or spec.end_date is None:
        raise ValueError("window failure context requires start and end dates")
    index = spec.parameters.get("window_index")
    count = spec.parameters.get("window_count")
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or index < 1
        or count < index
    ):
        raise ValueError("window failure context requires valid window index and count")
    return DateWindow(spec.start_date, spec.end_date), index, count


class EvdsWindowFailure(LakehouseError):
    """A safe, machine-readable failure annotated with its EVDS window."""

    def __init__(self, spec: FetchSpec, cause: Exception) -> None:
        window, index, count = _window_context(spec)
        if isinstance(cause, LakehouseError) and cause.payload.error_code in ERROR_CODES:
            error_code = cause.payload.error_code
            retryable = cause.payload.retryable
        else:
            error_code = "PARSE_FAILED"
            retryable = False
        message = (
            f"window {index}/{count} ({window.start_date.isoformat()}.."
            f"{window.end_date.isoformat()}) failed: {describe_exception(cause)}"
        )
        super().__init__(
            ErrorPayload(
                error_code=error_code,
                message=message,
                source_id=spec.source_id,
                dataset_id=spec.dataset_id,
                retryable=retryable,
            )
        )
        self.window = window
        self.index = index
        self.count = count
        self.cause = cause


class WindowedIngestionFailure(Exception):
    """Application-facing failure carrying the logical run and failed window."""

    def __init__(self, *, run_id: str, window: DateWindow, cause: Exception) -> None:
        self.run_id = run_id
        self.window = window
        self.cause = cause
        super().__init__(
            f"window {window.start_date.isoformat()}..{window.end_date.isoformat()} "
            f"failed: {describe_exception(cause)}"
        )


def wrap_window_failure(spec: FetchSpec, exception: Exception) -> EvdsWindowFailure:
    """Add safe window coordinates to an existing source or parsing exception."""

    return EvdsWindowFailure(spec, exception)


def reject_evds_truncation(asset: FetchedAsset, batch: ParsedBatch) -> None:
    """Turn the parser's existing per-request-limit warning into a hard failure."""

    warning = next(
        (message for message in batch.warnings if _TRUNCATION_MARKER in message),
        None,
    )
    if warning is None:
        return
    raise LakehouseError(
        ErrorPayload(
            error_code="OBSERVATION_COUNT_MISMATCH",
            message=(
                f"EVDS window artifact {asset.artifact_sha256} was not accepted: {warning}"
            ),
            source_id=asset.source_id,
            dataset_id=asset.dataset_id,
            retryable=False,
        )
    )


def _is_null(value: Any) -> bool:
    """Treat source nulls and scalar missing values as null without array ambiguity."""

    if value is None or value is pd.NA:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return isinstance(result, bool) and result


def _same_raw_value(left: Any, right: Any) -> bool:
    if _is_null(left) or _is_null(right):
        return _is_null(left) and _is_null(right)
    try:
        result = left == right
    except (TypeError, ValueError):
        return False
    return isinstance(result, bool) and result


def _key_value(value: Any) -> str | None:
    return None if _is_null(value) else str(value)


def _observation_key(row: Any) -> tuple[str | None, str | None, tuple[str, str | None]]:
    """Build identity from series, optional entity and the parser's canonical time fields."""

    series_id = _key_value(row.get("series_id"))
    entity_id = _key_value(row.get("entity_id")) if "entity_id" in row else None
    if not _is_null(row.get("unixtime")):
        time_key = ("unixtime", _key_value(row.get("unixtime")))
    else:
        time_key = ("date_raw", _key_value(row.get("date_raw")))
    return series_id, entity_id, time_key


@dataclass
class EvdsWindowReconciler:
    """Validate, deduplicate, and order parsed EVDS windows without fabricating provenance."""

    _frames: list[tuple[int, pd.DataFrame]]
    _seen_values: dict[tuple[str | None, str | None, tuple[str, str | None]], Any]

    def __init__(self) -> None:
        self._frames = []
        self._seen_values = {}

    def validate_batch(self, asset: FetchedAsset, batch: ParsedBatch) -> None:
        """Reject truncation/conflicts, then retain the first deterministic row."""

        reject_evds_truncation(asset, batch)
        frame = batch.dataframe
        candidate_values = dict(self._seen_values)
        retained_indices: list[Any] = []
        for row_index, (_, row) in enumerate(frame.iterrows()):
            identity = _observation_key(row)
            value = row.get("value_raw")
            if identity in candidate_values:
                previous = candidate_values[identity]
                if not _same_raw_value(previous, value):
                    series_id, entity_id, time_key = identity
                    raise LakehouseError(
                        ErrorPayload(
                            error_code="REVISION_CONFLICT",
                            message=(
                                "conflicting EVDS boundary observation for "
                                f"series={series_id!r}, entity={entity_id!r}, "
                                f"{time_key[0]}={time_key[1]!r}: "
                                f"{previous!r} versus {value!r}"
                            ),
                            source_id=asset.source_id,
                            dataset_id=asset.dataset_id,
                            retryable=False,
                        )
                    )
                continue
            candidate_values[identity] = value
            retained_indices.append(row_index)

        self._seen_values = candidate_values
        if retained_indices:
            retained = frame.iloc[retained_indices].copy()
            self._frames.append((len(self._frames), retained))

    def combined(self) -> pd.DataFrame:
        """Return stable chronological observations with the first artifact's provenance."""

        if not self._frames:
            return pd.DataFrame()
        pieces: list[pd.DataFrame] = []
        for window_order, frame in self._frames:
            prepared = frame.copy()
            prepared["__window_order"] = window_order
            prepared["__row_order"] = range(len(prepared))
            pieces.append(prepared)
        combined = pd.concat(pieces, ignore_index=True)

        if "unixtime" in combined.columns:
            combined["__sort_unixtime"] = pd.to_numeric(
                combined["unixtime"], errors="coerce"
            )
        else:
            combined["__sort_unixtime"] = pd.NA
        combined["__sort_missing"] = combined["__sort_unixtime"].isna()
        sort_columns = ["__sort_missing", "__sort_unixtime"]
        for column in ("series_id", "entity_id", "date_raw", "__window_order", "__row_order"):
            if column in combined.columns:
                sort_columns.append(column)
        combined = combined.sort_values(
            sort_columns,
            kind="mergesort",
            na_position="last",
        )
        helper_columns = {
            "__window_order",
            "__row_order",
            "__sort_unixtime",
            "__sort_missing",
        }
        return combined.drop(columns=helper_columns).reset_index(drop=True)


__all__ = [
    "DateWindow",
    "EVDS_MAX_WINDOW_DAYS",
    "EvdsWindowFailure",
    "EvdsWindowReconciler",
    "WindowedIngestionFailure",
    "plan_evds_windows",
    "reject_evds_truncation",
    "windowed_fetch_specs",
    "wrap_window_failure",
]
