"""Safe, deterministic transformations over a verified active workspace.

This module deliberately handles a small operation family. It does not infer
new data sources, resample frequencies, or choose metrics. The caller must
already have a committed follow-up context; this layer only checks that the
current request is compatible with the active table and applies a local
period-over-period calculation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..contracts.lakehouse import QueryProvenance
from .facets import extract_facets, province_of
from .follow_up import FollowUpResolution
from .workspace import AnalysisWorkspace

_DATE_NAMES = {
    "date",
    "date_column",
    "donem",
    "dönem",
    "tarih",
    "period_end",
    "observation_date",
    "time",
}
_GEO_NAMES = (
    "il",
    "şehir",
    "sehir",
    "province",
    "city",
    "district",
    "location",
    "region",
    "bölge",
    "bolge",
)
_MONTHLY_WORDS = ("aylık", "aylik", "aya", "monthly", "month")
_NATIONAL_WORDS = (
    "ulusal",
    "national",
    "türkiye geneli",
    "turkiye geneli",
    "ülke geneli",
    "ulke geneli",
)


@dataclass(frozen=True)
class WorkspaceFastPathPlan:
    operation: str
    date_column: str
    value_columns: tuple[str, ...]
    group_columns: tuple[str, ...]
    derived_columns: tuple[str, ...]
    expressions: tuple[str, ...]


@dataclass(frozen=True)
class WorkspaceFastPathResult:
    plan: WorkspaceFastPathPlan
    frame: pd.DataFrame
    validation: str


def _fold(value: Any) -> str:
    return str(value or "").casefold().replace("ı", "i")


def _date_like(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    values = series.dropna()
    return not values.empty and all(hasattr(value, "year") for value in values.head(20))


def _date_column(frame: pd.DataFrame) -> str | None:
    candidates = [str(c) for c in frame.columns if _date_like(frame[c])]
    for column in candidates:
        if column.rsplit("::", 1)[-1].casefold() in _DATE_NAMES:
            return column
    return candidates[0] if candidates else None


def _base_columns(workspace: AnalysisWorkspace) -> list[str]:
    """Return columns from the verified source table, excluding prior derivatives."""
    if workspace.history:
        first = workspace.history[0]
        if first.action == "set_table" and first.columns_added:
            return [str(column) for column in first.columns_added if column in workspace.columns()]
    return [str(column) for column in workspace.columns()]


def _active_sources(active_specs: Iterable[Any]) -> set[str]:
    return {
        str(getattr(spec, "source", "")) for spec in active_specs if getattr(spec, "source", None)
    }


def _active_frequencies(active_specs: Iterable[Any]) -> set[str]:
    out: set[str] = set()
    for spec in active_specs:
        frequency = getattr(
            getattr(spec, "frequency", None), "value", getattr(spec, "frequency", None)
        )
        if frequency:
            out.add(str(frequency))
    return out


def _active_geographies(active_specs: Iterable[Any]) -> set[str]:
    out: set[str] = set()
    for spec in active_specs:
        geography = province_of(f"{getattr(spec, 'dataset_id', '')} {getattr(spec, 'name', '')}")
        if geography:
            out.add(str(geography))
    return out


def _frame_geographies(frame: pd.DataFrame) -> set[str]:
    out: set[str] = set()
    for column in frame.columns:
        if not any(token in _fold(column) for token in _GEO_NAMES):
            continue
        if _date_like(frame[column]) or pd.api.types.is_numeric_dtype(frame[column]):
            continue
        out.update(str(value) for value in frame[column].dropna().unique())
    return out


def _monthly_cadence(frame: pd.DataFrame, date_column: str, group_columns: tuple[str, ...]) -> bool:
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    if dates.isna().any():
        return False
    keys = [*group_columns, date_column]
    ordered = frame.assign(__fast_date=dates).sort_values(keys, kind="stable")
    if group_columns:
        deltas = (
            ordered.groupby(list(group_columns), sort=False, dropna=False)["__fast_date"]
            .diff()
            .dropna()
        )
    else:
        deltas = ordered["__fast_date"].drop_duplicates().diff().dropna()
    return not deltas.empty and bool(deltas.dt.days.between(27, 32).all())


def _quote(column: str) -> str:
    return '"' + str(column).replace('"', '""') + '"'


def _window(column: str, date_column: str, group_columns: tuple[str, ...]) -> str:
    partition = ""
    if group_columns:
        partition = "PARTITION BY " + ", ".join(_quote(c) for c in group_columns) + " "
    return f"LAG({_quote(column)}) OVER ({partition}ORDER BY {_quote(date_column)})"


def _compatible_scope(
    question: str,
    resolution: FollowUpResolution,
    frame: pd.DataFrame,
    active_specs: list[Any],
) -> bool:
    if not resolution.is_follow_up or resolution.clarification_required:
        return False
    if not resolution.context.metric and not resolution.context.series:
        return False

    # A follow-up may say "monthly" when that is already the active table's
    # frequency, but it may not introduce a new metric, date range, aggregate,
    # series, entity, or comparison target. Those need normal reasoning.
    explicit = resolution.explicit
    if any(
        (
            explicit.metric,
            explicit.series,
            explicit.entity,
            explicit.date_range,
            explicit.aggregation,
        )
    ):
        return False
    if explicit.comparison_target and explicit.comparison_target != ("previous_period",):
        return False
    if set(resolution.overridden + resolution.cleared) & {
        "domain",
        "source",
        "metric",
        "series",
        "entity",
        "geography",
        "date_range",
        "frequency",
        "aggregation",
        "comparison_target",
    } - {"frequency"}:
        return False

    facets = extract_facets(question)
    sources = _active_sources(active_specs)
    frequencies = _active_frequencies(active_specs)
    geographies = _active_geographies(active_specs) or _frame_geographies(frame)

    requested_sources = set(facets.sources)
    if explicit.source:
        requested_sources.add(str(explicit.source))
    if requested_sources:
        if not sources or not all(
            any(_fold(want) == _fold(have) for have in sources) for want in requested_sources
        ):
            return False
        if any(
            not any(_fold(want) == _fold(have) for want in requested_sources) for have in sources
        ):
            return False
    if (
        resolution.context.source
        and sources
        and not any(_fold(resolution.context.source) == _fold(source) for source in sources)
    ):
        return False

    requested_geo = set(facets.provinces) | set(explicit.geography)
    if requested_geo:
        # Explicit geography is safe only when the active table is exactly for
        # that geography. National/provincial substitution is never allowed.
        if not geographies or {_fold(value) for value in geographies} != {
            _fold(value) for value in requested_geo
        }:
            return False
    elif any(word in _fold(question) for word in _NATIONAL_WORDS) and geographies:
        return False

    requested_frequency = facets.frequency or explicit.frequency
    if requested_frequency:
        if frequencies and frequencies != {requested_frequency}:
            return False
        if not frequencies and requested_frequency == "monthly":
            date_column = _date_column(frame)
            if date_column is None:
                return False
            base = _base_columns_for_groups(frame, date_column)
            if not _monthly_cadence(frame, date_column, base[1]):
                return False
    return not (
        resolution.context.frequency
        and frequencies
        and frequencies != {resolution.context.frequency}
    )


def _base_columns_for_groups(
    frame: pd.DataFrame, date_column: str
) -> tuple[list[str], tuple[str, ...]]:
    groups = tuple(
        str(column)
        for column in frame.columns
        if str(column) != date_column
        and not _date_like(frame[column])
        and not pd.api.types.is_numeric_dtype(frame[column])
    )
    return list(frame.columns), groups


def plan_verified_workspace_transform(
    question: str,
    resolution: FollowUpResolution | None,
    workspace: AnalysisWorkspace,
    *,
    active_specs: Iterable[Any] = (),
) -> WorkspaceFastPathPlan | None:
    """Return a plan only when all semantic and table-shape checks pass."""
    if resolution is None or not workspace.has_table or not workspace.history:
        return None
    if not _compatible_scope(question, resolution, workspace.table, list(active_specs)):
        return None
    operation = resolution.operation
    if operation not in {"period_change", "percent_change"}:
        return None

    frame = workspace.table
    assert frame is not None
    date_column = _date_column(frame)
    if date_column is None or frame.index.has_duplicates:
        return None
    date_values = pd.to_datetime(frame[date_column], errors="coerce")
    if date_values.isna().any():
        return None

    base = _base_columns(workspace)
    value_columns = [
        column
        for column in base
        if column != date_column
        and pd.api.types.is_numeric_dtype(frame[column])
        and not str(getattr(workspace.column_provenance(column), "sql", "") or "").startswith(
            "türetilmiş:"
        )
    ]
    if not value_columns:
        return None
    provenance = [workspace.column_provenance(column) for column in value_columns]
    if any(p is None or not getattr(p, "dataset_ids", None) for p in provenance):
        return None

    groups = _base_columns_for_groups(frame, date_column)[1]
    if operation == "period_change" and any(word in _fold(question) for word in _MONTHLY_WORDS):
        frequencies = _active_frequencies(list(active_specs))
        if (frequencies and frequencies != {"monthly"}) or (
            not frequencies and not _monthly_cadence(frame, date_column, groups)
        ):
            return None
    if groups:
        keys = frame[[*groups, date_column]].copy()
        if keys.duplicated().any():
            return None
    elif frame[date_column].duplicated().any():
        return None

    suffix = "_pct_change" if operation == "percent_change" else "_change"
    derived = tuple(f"{column}{suffix}" for column in value_columns)
    if any(column in frame.columns for column in derived):
        return None
    expressions = tuple(
        (
            f"(({_quote(column)} - {_window(column, date_column, groups)}) / "
            f"NULLIF({_window(column, date_column, groups)}, 0)) * 100"
            if operation == "percent_change"
            else f"{_quote(column)} - {_window(column, date_column, groups)}"
        )
        for column in value_columns
    )
    return WorkspaceFastPathPlan(
        operation=operation,
        date_column=date_column,
        value_columns=tuple(value_columns),
        group_columns=groups,
        derived_columns=derived,
        expressions=expressions,
    )


def execute_verified_workspace_transform(
    workspace: AnalysisWorkspace,
    plan: WorkspaceFastPathPlan,
) -> WorkspaceFastPathResult | None:
    """Apply and verify one local transformation, or return ``None`` safely."""
    frame = workspace.table
    if frame is None:
        return None
    dates = pd.to_datetime(frame[plan.date_column], errors="coerce")
    ordered = frame.assign(__fast_date=dates).sort_values(
        [*plan.group_columns, "__fast_date"], kind="stable"
    )
    values: dict[str, pd.Series] = {}
    expected: dict[str, pd.Series] = {}
    for source, target in zip(plan.value_columns, plan.derived_columns):
        if plan.group_columns:
            previous = ordered.groupby(list(plan.group_columns), sort=False, dropna=False)[
                source
            ].shift(1)
        else:
            previous = ordered[source].shift(1)
        if plan.operation == "percent_change":
            derived = (ordered[source] - previous) / previous.replace(0, np.nan) * 100
        else:
            derived = ordered[source] - previous
        values[target] = pd.Series(derived.to_numpy(), index=ordered.index).reindex(frame.index)
        expected[target] = values[target]

    try:
        provenance_by_column: dict[str, QueryProvenance] = {}
        for source, target, expression in zip(
            plan.value_columns, plan.derived_columns, plan.expressions
        ):
            base_provenance = workspace.column_provenance(source)
            assert base_provenance is not None
            provenance_by_column[target] = QueryProvenance(
                sql=f"türetilmiş: {expression}",
                dataset_ids=list(dict.fromkeys(base_provenance.dataset_ids)),
                sources=list(base_provenance.sources),
                row_count=len(frame),
            )
        workspace.add_columns(
            values,
            description=(
                "Dönemsel yüzde değişim"
                if plan.operation == "percent_change"
                else "Dönemsel mutlak değişim"
            )
            + " [deterministik doğrulanmış workspace fast path]",
            provenance_by_column=provenance_by_column,
        )
    except (AssertionError, ValueError, KeyError, TypeError):
        return None

    updated = workspace.table
    assert updated is not None
    if len(updated) != len(frame) or list(updated.columns[-len(plan.derived_columns) :]) != list(
        plan.derived_columns
    ):
        workspace.revert()
        return None
    for column in plan.derived_columns:
        actual = pd.to_numeric(updated[column], errors="coerce").to_numpy(dtype=float)
        want = pd.to_numeric(expected[column], errors="coerce").to_numpy(dtype=float)
        if not np.allclose(actual, want, equal_nan=True, rtol=1e-12, atol=1e-12):
            workspace.revert()
            return None
    return WorkspaceFastPathResult(
        plan=plan,
        frame=updated.copy(),
        validation="row_count, ordering, lag arithmetic, and NULL-first-period invariants passed",
    )


__all__ = [
    "WorkspaceFastPathPlan",
    "WorkspaceFastPathResult",
    "execute_verified_workspace_transform",
    "plan_verified_workspace_transform",
]
