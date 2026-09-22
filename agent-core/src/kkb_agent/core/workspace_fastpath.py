"""Safe, deterministic transformations over a verified active workspace.

This module deliberately handles a small operation family. It does not infer
new data sources, resample frequencies, or choose metrics. The caller must
already have a committed follow-up context; this layer only checks that the
current request is compatible with the active table and applies a local
period-over-period calculation.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..contracts.lakehouse import QueryProvenance
from .facets import extract_facets, province_of
from .follow_up import FollowUpResolution
from .period_intent import parse_period_intent
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
_PROVENANCE_SUFFIXES = (
    "::series_id",
    "::quality_flag",
    "::measure_type",
    "::unit",
    "::aggregation",
    "::observations",
    "::missing_observations",
    "::warned_observations",
    "::source_observation_dates",
    "::artifact_sha256_list",
    "::vintage_id_list",
    "::run_id_list",
)
_PROVENANCE_COLUMNS = frozenset({
    "quality_flag", "observations", "missing_observations", "warned_observations",
    "source_observation_dates", "artifact_sha256_list", "vintage_id_list", "run_id_list",
    "contributing_series", "absent_series", "is_complete_period", "gold_metric_id", "gold_function",
    "gold_build_id", "gold_built_at", "gold_catalog_content_sha256", "silver_fingerprint",
})


@dataclass(frozen=True)
class WorkspaceFastPathPlan:
    operation: str
    date_column: str
    value_columns: tuple[str, ...]
    group_columns: tuple[str, ...]
    derived_columns: tuple[str, ...]
    expressions: tuple[str, ...]
    period_start: pd.Timestamp | None = None
    period_end: pd.Timestamp | None = None


@dataclass(frozen=True)
class WorkspaceFastPathResult:
    plan: WorkspaceFastPathPlan
    frame: pd.DataFrame
    validation: str


@dataclass(frozen=True)
class WorkspaceTransformSatisfaction:
    """Proof that a requested transformation is already present on the active table."""

    operation: str
    date_column: str
    source_columns: tuple[str, ...]
    derived_columns: tuple[str, ...]
    series_ids: tuple[str, ...]
    period_start: pd.Timestamp | None = None
    period_end: pd.Timestamp | None = None
    validation: str = ""


def requested_month_range(
    question: str, resolution: FollowUpResolution | None
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Return an explicit current-turn monthly output range, if one exists."""
    if resolution is None or not resolution.explicit.date_range:
        return None
    intent = parse_period_intent(question)
    if not intent.outer_bounds_explicit or not intent.outer_start or not intent.outer_end:
        return None
    # A range nested inside a larger ``N aylık`` request is an anchor, not a
    # safe local filter. That request must go through normal retrieval.
    if intent.anchor_start or intent.anchor_end:
        return None
    if not any(word in _fold(question) for word in _MONTHLY_WORDS):
        return None
    return pd.Timestamp(intent.outer_start), pd.Timestamp(intent.outer_end)


def _fold(value: Any) -> str:
    return str(value or "").casefold().replace("ı", "i")


def _date_like(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    values = series.dropna()
    return not values.empty and all(hasattr(value, "year") for value in values.head(20))


def _monthly_periods(series: pd.Series) -> pd.PeriodIndex | None:
    """Parse a period label without guessing when any value is ambiguous."""
    values = series.astype("string").str.strip()
    if values.empty or values.isna().any():
        return None
    if values.str.fullmatch(r"(?:19|20)\d{4}").all():
        parsed = pd.to_datetime(values, format="%Y%m", errors="coerce")
    elif values.str.fullmatch(r"(?:19|20)\d{2}[-/](?:0?[1-9]|1[0-2])").all():
        normalized = values.str.replace("/", "-", regex=False)
        parsed = pd.to_datetime(normalized + "-01", format="mixed", errors="coerce")
    else:
        parsed = pd.to_datetime(values, errors="coerce")
    if parsed.isna().any():
        return None
    return pd.PeriodIndex(parsed.dt.to_period("M"))


def _is_redundant_month_key(frame: pd.DataFrame, column: str, date_column: str) -> bool:
    """Exclude a text month key when it encodes the primary date axis row-for-row.

    Lakehouse results may carry both a DATE (`observation_date`) and a text
    label (`ay`, `202201`, etc.). Treating that label as a panel dimension
    partitions every month into a one-row group, making every LAG NULL.
    Real dimensions such as province/product remain grouping keys because
    they do not exactly track the primary month axis.
    """
    candidate = frame[column]
    if pd.api.types.is_numeric_dtype(candidate) or _date_like(candidate):
        return False
    candidate_months = _monthly_periods(candidate)
    date_values = pd.to_datetime(frame[date_column], errors="coerce")
    if candidate_months is None or date_values.isna().any():
        return False
    date_months = pd.PeriodIndex(date_values.dt.to_period("M"))
    return len(candidate_months) == len(date_months) and bool(
        (candidate_months == date_months).all()
    )


def _date_column(frame: pd.DataFrame) -> str | None:
    candidates = [str(c) for c in frame.columns if _date_like(frame[c])]
    for column in candidates:
        if column.rsplit("::", 1)[-1].casefold() in _DATE_NAMES:
            return column
    return candidates[0] if candidates else None


def _is_provenance_column(column: object) -> bool:
    name = str(column)
    return name in _PROVENANCE_COLUMNS or name.endswith(_PROVENANCE_SUFFIXES)


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
    # frequency. An explicit monthly output range is safe when it is only a
    # view of the verified active table; new semantic identities still fall
    # back to normal retrieval.
    explicit = resolution.explicit
    period_range = requested_month_range(question, resolution)
    if any(
        (
            explicit.metric,
            explicit.series,
            explicit.entity,
            explicit.aggregation,
        )
    ):
        return False
    if explicit.comparison_target and explicit.comparison_target != ("previous_period",):
        return False
    if explicit.date_range and period_range is None:
        return False
    if set(resolution.overridden + resolution.cleared) & {
        "domain",
        "source",
        "metric",
        "series",
        "entity",
        "geography",
        "frequency",
        "aggregation",
        "comparison_target",
    } - {"frequency"}:
        return False
    if "date_range" in resolution.overridden + resolution.cleared and period_range is None:
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
        and not _is_provenance_column(column)
        and not _date_like(frame[column])
        and not _is_redundant_month_key(frame, str(column), date_column)
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
        and not pd.api.types.is_bool_dtype(frame[column])
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

    period_range = requested_month_range(question, resolution)
    period_start, period_end = period_range or (None, None)
    if period_start is not None and period_end is not None:
        # The requested output months must be present. The preceding month is
        # used automatically when available; when it is outside the active
        # table the first delta remains NULL rather than triggering a new
        # catalog search that could select unrelated sibling series.
        expected = pd.period_range(period_start, period_end, freq="M")
        active_periods = pd.PeriodIndex(date_values.dt.to_period("M")).unique()
        if not set(expected).issubset(set(active_periods)):
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
        period_start=period_start,
        period_end=period_end,
    )


def inspect_existing_verified_transform(
    question: str,
    resolution: FollowUpResolution | None,
    workspace: AnalysisWorkspace,
    *,
    active_specs: Iterable[Any] = (),
) -> WorkspaceTransformSatisfaction | None:
    """Prove a compatible transformation already exists without recomputing it.

    This is intentionally stricter than checking column suffixes. The derived
    columns must be recorded as a workspace operation, carry generated LAG
    provenance, align with the requested monthly axis, and retain a source
    identity for each input measure.
    """
    if resolution is None or not workspace.has_table or not workspace.history:
        return None
    if not _compatible_scope(question, resolution, workspace.table, list(active_specs)):
        return None
    operation = resolution.operation
    if operation not in {"period_change", "percent_change"}:
        return None

    frame = workspace.table
    assert frame is not None
    if frame.index.has_duplicates:
        return None
    date_column = _date_column(frame)
    if date_column is None:
        return None
    date_values = pd.to_datetime(frame[date_column], errors="coerce")
    if date_values.isna().any():
        return None

    base = _base_columns(workspace)
    source_columns = tuple(
        column
        for column in base
        if column != date_column
        and not _is_provenance_column(column)
        and pd.api.types.is_numeric_dtype(frame[column])
        and not pd.api.types.is_bool_dtype(frame[column])
        and not str(getattr(workspace.column_provenance(column), "sql", "") or "").startswith(
            "türetilmiş:"
        )
    )
    if not source_columns:
        return None

    suffix = "_pct_change" if operation == "percent_change" else "_change"
    derived_columns = tuple(f"{column}{suffix}" for column in source_columns)
    if any(column not in frame.columns or not pd.api.types.is_numeric_dtype(frame[column])
           for column in derived_columns):
        return None

    # A user file could itself contain a column named `*_change`; accept it
    # only when the workspace records that exact derived-column operation.
    recorded = {
        str(column)
        for step in workspace.history
        if step.action in {"add_column", "transform"}
        for column in step.columns_added
    }
    if not set(derived_columns).issubset(recorded):
        return None

    series_ids: list[str] = []
    for source, derived in zip(source_columns, derived_columns):
        source_provenance = workspace.column_provenance(source)
        derived_provenance = workspace.column_provenance(derived)
        source_ids = list(getattr(source_provenance, "dataset_ids", []) or [])
        if source_provenance is None or not (
            source_ids or getattr(source_provenance, "sources", None)
        ):
            return None
        sql = str(getattr(derived_provenance, "sql", "") or "")
        folded_sql = _fold(sql)
        if (derived_provenance is None or not folded_sql.startswith("türetilmiş:")
                or "lag(" not in folded_sql or _fold(source) not in folded_sql
                or _fold(date_column) not in folded_sql):
            return None
        if operation == "percent_change" and "/" not in sql:
            return None
        for series_id in source_ids:
            if str(series_id) not in series_ids:
                series_ids.append(str(series_id))

    groups = _base_columns_for_groups(frame, date_column)[1]
    if groups:
        if frame[[*groups, date_column]].duplicated().any():
            return None
    elif frame[date_column].duplicated().any():
        return None
    if operation == "period_change" and any(word in _fold(question) for word in _MONTHLY_WORDS):
        frequencies = _active_frequencies(list(active_specs))
        if (frequencies and frequencies != {"monthly"}) or (
            not frequencies and not _monthly_cadence(frame, date_column, groups)
        ):
            return None

    # Column names and a SQL string containing LAG are not enough to certify a
    # saved transformation. Recheck its values against the active source data;
    # this catches degenerate partitions such as PARTITION BY a unique month
    # label, where every result is silently NULL.
    ordered = frame.assign(__fast_date=date_values).sort_values(
        [*groups, "__fast_date"], kind="stable"
    )
    for source, derived in zip(source_columns, derived_columns):
        values = pd.to_numeric(ordered[source], errors="coerce")
        actual = pd.to_numeric(ordered[derived], errors="coerce")
        if groups:
            grouped = ordered.groupby(list(groups), sort=False, dropna=False)
            previous = grouped[source].shift(1)
            first_in_group = grouped.cumcount().eq(0)
        else:
            previous = ordered[source].shift(1)
            first_in_group = pd.Series(False, index=ordered.index)
            if len(first_in_group):
                first_in_group.iloc[0] = True
        expected = values - pd.to_numeric(previous, errors="coerce")
        if operation == "percent_change":
            denominator = pd.to_numeric(previous, errors="coerce").replace(0, np.nan)
            expected = expected / denominator * 100
        # The first visible row in a filtered view may have a valid LAG from
        # the source window that is no longer visible. Validate every later
        # observation, where both operands are still present in this frame.
        comparable = ~first_in_group
        if not comparable.any():
            return None
        got = actual.loc[comparable].to_numpy(dtype=float)
        want = expected.loc[comparable].to_numpy(dtype=float)
        if not np.allclose(got, want, equal_nan=True, rtol=1e-12, atol=1e-12):
            return None

    period_range = requested_month_range(question, resolution)
    period_start, period_end = period_range or (None, None)
    if period_start is not None and period_end is not None:
        expected = pd.period_range(period_start, period_end, freq="M")
        group_frames = (
            [part for _, part in frame.groupby(list(groups), sort=False, dropna=False)]
            if groups else [frame]
        )
        for part in group_frames:
            periods = pd.PeriodIndex(pd.to_datetime(part[date_column]).dt.to_period("M")).unique()
            # The active table keeps its full window; the requested months
            # only need to be present in it.
            if not set(expected).issubset(set(periods)):
                return None

    return WorkspaceTransformSatisfaction(
        operation=operation,
        date_column=date_column,
        source_columns=source_columns,
        derived_columns=derived_columns,
        series_ids=tuple(series_ids),
        period_start=period_start,
        period_end=period_end,
        validation=(
            "workspace operation, derived LAG provenance, source identity, and monthly coverage passed"
        ),
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
        description = (
            "Dönemsel yüzde değişim"
            if plan.operation == "percent_change"
            else "Dönemsel mutlak değişim"
        ) + " [deterministik doğrulanmış workspace fast path]"
        if plan.period_start is not None and plan.period_end is not None:
            # The requested months are an output view, not a new table: the
            # derived columns are added to the full verified window so the
            # user's table (and the LAG base) survive; the answer carries the
            # filtered rows. Replacing the table shrank a 60-row workspace to
            # the 3 requested rows and lost the original.
            window_dates = pd.to_datetime(frame[plan.date_column], errors="coerce")
            if not window_dates.between(plan.period_start, plan.period_end, inclusive="both").any():
                return None
            description += f"; çıktı aralığı {plan.period_start:%Y-%m}–{plan.period_end:%Y-%m}"
        workspace.add_columns(
            values,
            description=description,
            provenance_by_column=provenance_by_column,
        )
    except (AssertionError, ValueError, KeyError, TypeError):
        return None

    updated = workspace.table
    assert updated is not None
    if len(updated) != len(frame) or list(updated.columns[-len(plan.derived_columns) :]) != list(plan.derived_columns):
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
        frame=period_view(updated, plan.date_column, plan.period_start, plan.period_end),
        validation="row_count, ordering, lag arithmetic, and NULL-first-period invariants passed",
    )


def period_view(
    frame: pd.DataFrame,
    date_column: str,
    period_start: pd.Timestamp | None,
    period_end: pd.Timestamp | None,
) -> pd.DataFrame:
    """Rows of ``frame`` inside the requested window (a copy); the whole frame when no window."""
    if period_start is None or period_end is None:
        return frame.copy()
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    mask = dates.between(period_start, period_end, inclusive="both")
    return frame.loc[mask].copy().reset_index(drop=True)


def repair_invalid_previous_transform(
    question: str,
    resolution: FollowUpResolution | None,
    workspace: AnalysisWorkspace,
    *,
    active_specs: Iterable[Any] = (),
) -> WorkspaceFastPathResult | None:
    """Recompute a failed generated transform from its immediately prior snapshot.

    This is deliberately limited to a last workspace transform whose exact
    generated output columns and LAG provenance match the current request. It
    lets the harness repair persisted bad output without reusing untrusted
    values or searching the catalog again.
    """
    history = workspace.history
    current = workspace.table
    snapshots = workspace.previous_tables()
    if (
        resolution is None
        or not isinstance(current, pd.DataFrame)
        or not history
        or history[-1].action != "transform"
        or not snapshots
    ):
        return None

    previous = snapshots[0]
    temporary = copy.deepcopy(workspace)
    temporary._table = previous.copy()
    temporary._history = history[:-1]
    temporary._snapshots = []

    plan = plan_verified_workspace_transform(
        question, resolution, temporary, active_specs=active_specs
    )
    if plan is None or not set(plan.derived_columns).issubset(history[-1].columns_added):
        return None
    if any(column not in current.columns or column in previous.columns for column in plan.derived_columns):
        return None
    for source, derived in zip(plan.value_columns, plan.derived_columns):
        provenance = workspace.column_provenance(derived)
        sql = _fold(getattr(provenance, "sql", "") or "")
        if (
            provenance is None
            or not sql.startswith("türetilmiş:")
            or "lag(" not in sql
            or _fold(source) not in sql
            or _fold(plan.date_column) not in sql
        ):
            return None

    result = execute_verified_workspace_transform(temporary, plan)
    if result is None:
        return None
    provenance = {
        column: temporary.column_provenance(column) for column in plan.derived_columns
    }
    description = (
        "Dönemsel yüzde değişim" if plan.operation == "percent_change" else "Dönemsel mutlak değişim"
    ) + " [doğrulama sonrası yeniden hesaplandı]"
    if plan.period_start is not None and plan.period_end is not None:
        description += f"; çıktı aralığı {plan.period_start:%Y-%m}–{plan.period_end:%Y-%m}"
    repaired = temporary.table
    if repaired is None:
        return None
    try:
        workspace.replace_table(
            repaired.copy(),
            description=description,
            column_provenance=provenance,
            columns_added=list(plan.derived_columns),
        )
    except (AssertionError, KeyError, TypeError, ValueError):
        return None
    return WorkspaceFastPathResult(
        plan=plan,
        frame=result.frame.copy(),
        validation="önceki snapshot'tan yeniden hesaplandı; " + result.validation,
    )


__all__ = [
    "period_view",
    "WorkspaceFastPathPlan",
    "WorkspaceFastPathResult",
    "WorkspaceTransformSatisfaction",
    "execute_verified_workspace_transform",
    "inspect_existing_verified_transform",
    "plan_verified_workspace_transform",
    "repair_invalid_previous_transform",
    "requested_month_range",
]
