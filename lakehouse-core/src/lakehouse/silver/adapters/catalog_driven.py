"""One Silver staging adapter per source, driven by the catalog instead of a series list.

The first Silver slice mapped one named series per function::

    if any(row_value != SUPPORTED_SERIES_ID for row_value in frame["series_id"]):
        raise SilverValidationError("unsupported series; only ... is mapped")

That check answers a real question — *has a human reviewed the meaning of this series?* — but it
answers it with a Python constant, so the number of publishable series is the number of
functions someone wrote. When the catalog grew to 1620 series the number of functions did not,
and 1615 of those series could never reach ``silver.fact_observation``.

Here the same question is answered by ``meta.series``, which *is* the human-authored,
git-reviewed record of what a series means. A series is publishable when the catalog defines
it and states a measure type; everything genuinely source-shaped — how the source spells a
date, where the entity lives in the row, which unit label the source declares — stays per
source, because that is what actually differs between sources.

Nothing semantic is invented here. Frequency, unit and measure type continue to come from
``meta.series`` through the generic Silver projection; this module only turns one source's row
into the source-independent staging contract.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from numbers import Integral
import re
import unicodedata

import duckdb
import pandas as pd

from ...parsers.bddk_finturk import BDDK_FINTURK_SCHEMA_VERSION
from ...parsers.bddk_monthly import BDDK_MONTHLY_SCHEMA_VERSION
from ...parsers.bddk_weekly import BDDK_WEEKLY_SCHEMA_VERSION
from ...parsers.evds import EVDS_SCHEMA_VERSION
from ..foundation import SilverValidationError
from ...storage.parquet import ParquetIdentity
from ._context import bddk_entity_code, bddk_entity_id, lineage_fields, staging_frame
from ._evds_time import evds_month_bounds, evds_point_date


@dataclass(frozen=True)
class SeriesSemantics:
    """The catalog's own statement about one series, as loaded from ``meta.series``."""

    series_id: str
    source_id: str
    frequency: str
    unit: str | None
    measure_type: str
    status: str

    @property
    def unpublishable_reason(self) -> str | None:
        """Why the catalog does not yet say enough about this series to publish it.

        These are the same conditions the generic Silver projection already enforces in SQL
        (``_validate_sql_inputs``): a missing unit or an unknown measure type makes a row
        indistinguishable from a reviewed one while carrying no meaning. Restating them here
        turns a late, whole-snapshot failure into an early, per-series explanation, so a build
        can report "this series is waiting on its unit" instead of aborting the batch.

        ``measure_type = 'unknown'`` and ``unit = NULL`` are legitimate catalog states: they are
        how a series discovered from a source's own metadata, but never given a reviewed
        meaning, is honestly recorded.
        """

        if self.status != "active":
            return f"status={self.status!r}"
        if self.measure_type in (None, "", "unknown"):
            return "measure_type is unknown"
        if self.unit is None or not str(self.unit).strip():
            return "unit is not set in the catalog"
        return None

    @property
    def is_publishable(self) -> bool:
        """Whether this series may reach ``silver.fact_observation``."""

        return self.unpublishable_reason is None


def load_series_semantics(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, SeriesSemantics]:
    """Read the semantic catalog. The only source of series meaning in this module."""

    rows = connection.execute(
        """
        SELECT series_id, source_id, frequency, unit, measure_type, status
        FROM meta.series
        """
    ).fetchall()
    return {
        row[0]: SeriesSemantics(
            series_id=row[0],
            source_id=row[1],
            frequency=row[2],
            unit=row[3],
            measure_type=row[4],
            status=row[5],
        )
        for row in rows
    }


@dataclass(frozen=True)
class _Temporal:
    observation_date: date
    period_start: date | None
    period_end: date | None


# Reviewed correspondences between a unit label the source prints and a catalog unit. This is
# deliberately a short explicit table rather than a parser: an unreviewed label must fail, not
# be guessed into a unit. It reproduces the mapping the first BDDK monthly adapter enforced.
_SOURCE_UNIT_TO_CATALOG_UNIT: dict[str, str] = {
    "milyon tl": "TRY_mn",
    "bin tl": "TRY_th",
    "tl": "TRY",
}


def _normalize_label(raw: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(raw)).casefold().split())


def _check_declared_unit(
    raw: object, *, semantics: SeriesSemantics, row_number: int
) -> None:
    """Refuse to publish when the source's own unit label and the catalog unit disagree.

    Fail-closed in both directions. An unreviewed label is not mapped, and a label that does
    map but maps to a different unit than the catalog claims is a semantic conflict, not a
    rounding detail.
    """

    if raw is None or raw is pd.NA or pd.isna(raw):
        raise SilverValidationError(
            f"{semantics.source_id} unit_label must not be NULL at row {row_number}"
        )
    label = _normalize_label(raw)
    mapped = _SOURCE_UNIT_TO_CATALOG_UNIT.get(label)
    if mapped is None:
        raise SilverValidationError(
            f"{semantics.source_id} source unit {raw!r} at row {row_number} has no reviewed "
            f"catalog mapping; add it to the reviewed unit table before publishing"
        )
    if semantics.unit != mapped:
        raise SilverValidationError(
            f"{semantics.series_id} source unit {raw!r} maps to {mapped!r} but the catalog "
            f"declares {semantics.unit!r} at row {row_number}"
        )


def _month_bounds(year_raw: object, month_raw: object, row_number: int) -> tuple[date, date]:
    if (
        isinstance(year_raw, bool)
        or isinstance(month_raw, bool)
        or not isinstance(year_raw, Integral)
        or not isinstance(month_raw, Integral)
    ):
        raise SilverValidationError(
            f"year_raw/month_raw must be integer values at row {row_number}"
        )
    try:
        year, month = int(year_raw), int(month_raw)
        return date(year, month, 1), date(year, month, monthrange(year, month)[1])
    except (TypeError, ValueError, OverflowError) as exc:
        raise SilverValidationError(
            f"invalid year_raw/month_raw at row {row_number}: {year_raw!r}/{month_raw!r}"
        ) from exc


_QUARTER_END_MONTHS = (3, 6, 9, 12)


def _quarter_bounds(year_raw: object, month_raw: object, row_number: int) -> tuple[date, date]:
    """Expand a quarter-end month into the full quarter it closes.

    BDDK FinTürk publishes quarterly while spelling the period as a year and a month; the
    source's own server refuses every non-quarter-end month (see
    ``docs/sources/bddk_finturk.md``). A month outside that set is a contract violation rather
    than a value to reinterpret, so it is refused instead of being rounded to a quarter.
    """

    _, period_end = _month_bounds(year_raw, month_raw, row_number)
    if period_end.month not in _QUARTER_END_MONTHS:
        raise SilverValidationError(
            f"BDDK FinTürk month {period_end.month} at row {row_number} is not a quarter end; "
            "the source publishes only March, June, September and December"
        )
    period_start = date(period_end.year, period_end.month - 2, 1)
    return period_start, period_end


_BDDK_WEEKLY_DATE = re.compile(r"^\d{1,2}\.\d{2}\.\d{4}$")
_EVDS_MONTH = re.compile(r"^\d{2}-\d{4}$")


def _bddk_weekly_date(raw: object, row_number: int) -> date:
    if not isinstance(raw, str) or _BDDK_WEEKLY_DATE.fullmatch(raw) is None:
        raise SilverValidationError(
            f"invalid BDDK weekly date_raw at row {row_number}: {raw!r}"
        )
    try:
        return datetime.strptime(raw, "%d.%m.%Y").date()
    except ValueError as exc:
        raise SilverValidationError(
            f"invalid BDDK weekly date_raw at row {row_number}: {raw!r}"
        ) from exc


# ------------------------------------------------------------------- source mappings


def _bddk_monthly_row(row: pd.Series, row_number: int, semantics: SeriesSemantics):
    _check_declared_unit(row["unit_label"], semantics=semantics, row_number=row_number)
    period_start, period_end = _month_bounds(
        row["year_raw"], row["month_raw"], row_number
    )
    return (
        _Temporal(period_end, period_start, period_end),
        bddk_entity_id(row["entity_label"], row_number=row_number),
    )


def _bddk_weekly_row(row: pd.Series, row_number: int, semantics: SeriesSemantics):
    if (
        not isinstance(row["currency_label"], str)
        or row["currency_label"].strip() != "TRY"
    ):
        raise SilverValidationError(
            f"BDDK weekly currency_label must be 'TRY' at row {row_number}"
        )
    return (
        _Temporal(_bddk_weekly_date(row["date_raw"], row_number), None, None),
        bddk_entity_code(row["entity_code"], row_number=row_number),
    )


def _bddk_finturk_row(row: pd.Series, row_number: int, semantics: SeriesSemantics):
    """Map one FinTürk province/measure cell.

    The province is already part of ``series_id`` — BDDK publishes one grid per province, so
    two provinces can never collapse into one series. ``entity_id`` therefore carries the other
    dimension the grid distinguishes, the party (``Grup``: sector, participation banks, …),
    through the same BDDK entity vocabulary the monthly source uses, so ``Sektör`` is the same
    entity across all three BDDK sources.
    """

    period_start, period_end = _quarter_bounds(
        row["year_raw"], row["month_raw"], row_number
    )
    return (
        _Temporal(period_end, period_start, period_end),
        bddk_entity_id(row["party_label"], row_number=row_number),
    )


def _evds_row(row: pd.Series, row_number: int, semantics: SeriesSemantics):
    """Choose the EVDS date policy from the catalog frequency, never from the value's shape.

    Whether an observation is a point in time or a whole month is a property of the series, and
    the catalog is where that property is recorded. The *spelling* of the date is not trusted at
    all — see :mod:`._evds_time`. A frequency this module has not been shown a real response for
    is refused rather than guessed.
    """

    if semantics.frequency in {"daily", "weekly", "business_daily"}:
        return _Temporal(evds_point_date(row, row_number), None, None), None
    if semantics.frequency == "monthly":
        period_start, period_end = evds_month_bounds(row, row_number)
        return _Temporal(period_end, period_start, period_end), None
    raise SilverValidationError(
        f"{semantics.series_id}: no reviewed EVDS date policy for frequency "
        f"{semantics.frequency!r}; the response format for this frequency has not been "
        "verified against a real payload"
    )


@dataclass(frozen=True)
class SourceMapping:
    """Everything that is genuinely source-shaped about reaching Silver from Bronze."""

    source_id: str
    schema_version: str
    required_columns: frozenset[str]
    row_mapper: Callable[
        [pd.Series, int, SeriesSemantics], tuple[_Temporal, str | None]
    ]


_COMMON_COLUMNS = frozenset(
    {"source_id", "dataset_id", "series_id", "value_raw", "artifact_sha256", "fetched_at"}
)

SOURCE_MAPPINGS: dict[str, SourceMapping] = {
    "bddk_monthly": SourceMapping(
        source_id="bddk_monthly",
        schema_version=BDDK_MONTHLY_SCHEMA_VERSION,
        required_columns=_COMMON_COLUMNS
        | {"unit_label", "entity_label", "year_raw", "month_raw"},
        row_mapper=_bddk_monthly_row,
    ),
    "bddk_weekly": SourceMapping(
        source_id="bddk_weekly",
        schema_version=BDDK_WEEKLY_SCHEMA_VERSION,
        required_columns=_COMMON_COLUMNS | {"entity_code", "currency_label", "date_raw"},
        row_mapper=_bddk_weekly_row,
    ),
    "bddk_finturk": SourceMapping(
        source_id="bddk_finturk",
        schema_version=BDDK_FINTURK_SCHEMA_VERSION,
        required_columns=_COMMON_COLUMNS | {"party_label", "year_raw", "month_raw"},
        row_mapper=_bddk_finturk_row,
    ),
    "evds": SourceMapping(
        source_id="evds",
        schema_version=EVDS_SCHEMA_VERSION,
        required_columns=_COMMON_COLUMNS | {"date_raw", "unixtime"},
        row_mapper=_evds_row,
    ),
}


def catalog_driven_to_staging(
    frame: pd.DataFrame,
    *,
    identity: ParquetIdentity,
    semantics: dict[str, SeriesSemantics],
    run_id: str | None = None,
    source_warnings: Sequence[str] = (),
    vintage_id: str | None = None,
) -> pd.DataFrame:
    """Map any Bronze frame from a known source to the generic Silver staging contract.

    Every row's ``series_id`` must be present in ``semantics`` and publishable. Callers that
    expect a Bronze artifact to carry measures nobody catalogued — BDDK FinTürk returns a whole
    grid, of which one column is registered — must drop those rows themselves and say how many
    they dropped. Dropping is never this function's silent default.
    """

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    mapping = SOURCE_MAPPINGS.get(identity.source_id)
    if mapping is None:
        raise SilverValidationError(
            f"no Silver mapping for source {identity.source_id!r}; known sources are "
            f"{sorted(SOURCE_MAPPINGS)}"
        )
    missing = sorted(mapping.required_columns - set(frame.columns))
    if missing:
        raise SilverValidationError(
            f"{mapping.source_id} Bronze frame is missing columns: {missing}"
        )
    if frame.empty:
        raise SilverValidationError(f"{mapping.source_id} Bronze frame must not be empty")
    if identity.schema_version != mapping.schema_version:
        raise SilverValidationError(
            f"{mapping.source_id} Bronze schema_version mismatch: expected "
            f"{mapping.schema_version!r}, got {identity.schema_version!r}"
        )
    for column in ("source_id", "dataset_id", "artifact_sha256"):
        expected = getattr(identity, column)
        if any(value != expected for value in frame[column].tolist()):
            raise SilverValidationError(
                f"{mapping.source_id} Bronze {column} conflicts with Parquet identity"
            )

    lineage = lineage_fields(
        identity,
        run_id=run_id,
        source_warnings=source_warnings,
        vintage_id=vintage_id,
    )
    records: list[dict[str, object]] = []
    for row_number, (_, row) in enumerate(frame.iterrows()):
        series_id = row["series_id"]
        series = semantics.get(series_id)
        if series is None:
            raise SilverValidationError(
                f"series {series_id!r} at row {row_number} is not in meta.series; a series "
                "reaches Silver only after it is catalogued"
            )
        reason = series.unpublishable_reason
        if reason is not None:
            raise SilverValidationError(
                f"series {series_id!r} at row {row_number} is not publishable: {reason}"
            )
        if series.source_id != identity.source_id:
            raise SilverValidationError(
                f"series {series_id!r} belongs to source {series.source_id!r} but the Bronze "
                f"artifact is from {identity.source_id!r}"
            )
        temporal, entity_id = mapping.row_mapper(row, row_number, series)
        records.append(
            {
                "series_id": series_id,
                "entity_id": entity_id,
                "observation_date": temporal.observation_date,
                "period_start": temporal.period_start,
                "period_end": temporal.period_end,
                "value_raw": row["value_raw"],
                "source_id": row["source_id"],
                "dataset_id": row["dataset_id"],
                "artifact_sha256": row["artifact_sha256"],
                "fetched_at": row["fetched_at"],
                **lineage,
            }
        )
    return staging_frame(records)


__all__ = [
    "SOURCE_MAPPINGS",
    "SeriesSemantics",
    "SourceMapping",
    "catalog_driven_to_staging",
    "load_series_semantics",
]
