"""Read series semantics from ``meta.series`` and gate what Gold is allowed to do with them.

Nothing in this module accepts a measure type, aggregation rule, frequency, week anchor or
confidence level from a caller. Every one of those is read from the catalog at call time. That
is the whole point: the model decides *which* question to ask, the catalog decides *how* the
numbers may be combined, and the two must never swap places.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import duckdb

from .errors import refuse


AGGREGATION_RULES: Final[frozenset[str]] = frozenset(
    {"avg", "sum", "min", "max", "first", "last"}
)
"""Catalog aggregation vocabulary, mirrored from ``catalog.series.AGGREGATIONS``."""

_RATE_LIKE_RULES: Final[frozenset[str]] = frozenset({"avg", "min", "max", "first", "last"})
"""Summing a rate or an index is meaningless, so ``sum`` is refused for those types."""

TRUSTED_CONFIDENCE: Final[frozenset[str]] = frozenset({"verified"})
"""Only a fully evidenced series is transformed without an explicit human decision."""

ACTIVE_STATUS: Final[str] = "active"
"""The only catalog status Gold will transform automatically."""


@dataclass(frozen=True)
class SeriesSemantics:
    """The catalog's word on one series. Built only from ``meta.series``."""

    series_id: str
    frequency: str
    measure_type: str
    default_agg: str | None
    week_anchor: str | None
    cumulative_reset: str | None
    semantic_confidence: str
    unit: str | None
    status: str


def load_semantics(
    connection: duckdb.DuckDBPyConnection, series_id: str
) -> SeriesSemantics:
    """Read one series' semantics. ``series_id`` is bound, never interpolated."""

    if not isinstance(series_id, str) or not series_id.strip():
        raise refuse("INVALID_ARGUMENT", "series_id must be a non-empty string")

    row = connection.execute(
        """
        SELECT series_id, frequency, measure_type, default_agg, week_anchor,
               cumulative_reset, semantic_confidence, unit, status
        FROM meta.series
        WHERE series_id = ?
        """,
        [series_id],
    ).fetchone()
    if row is None:
        raise refuse(
            "SERIES_NOT_CATALOGUED",
            "series has no meta.series row, so no aggregation rule exists for it",
            series_id=series_id,
        )
    return SeriesSemantics(*row)


def require_active_status(semantics: SeriesSemantics) -> None:
    """Refuse a series the catalog has not published for use.

    ``draft`` means the semantics are still being written and ``deprecated`` means they were
    withdrawn. Neither is a judgement about evidence, so this gate is **not** relaxed by
    ``allow_unverified_semantics``: consenting to an under-evidenced series is a different
    decision from using one the catalog has taken out of service.
    """

    if semantics.status != ACTIVE_STATUS:
        raise refuse(
            "INACTIVE_SERIES",
            f"catalog status is {semantics.status!r}; only {ACTIVE_STATUS!r} series are "
            "transformed, and this gate is not relaxed by any override",
            series_id=semantics.series_id,
        )


def require_trusted_semantics(
    semantics: SeriesSemantics, *, allow_unverified_semantics: bool
) -> None:
    """Refuse to transform a series whose meaning is not fully established.

    ``allow_unverified_semantics`` is the **only** override this layer offers and it is off by
    default. It relaxes exactly one thing: the confidence gate. It never supplies a measure
    type, an aggregation rule or a frequency, so an agent that flips it still cannot choose how
    the numbers are combined -- it can only accept responsibility for a series the catalog
    itself marks as not fully evidenced. The intended caller is a human answering "yes, use the
    unverified series anyway", not a model deciding on its own.
    """

    if not isinstance(allow_unverified_semantics, bool):
        # A truthy string such as "false" must never open this gate.
        raise refuse(
            "INVALID_ARGUMENT",
            "allow_unverified_semantics must be a real bool, got "
            f"{type(allow_unverified_semantics).__name__}",
            series_id=semantics.series_id,
        )
    if semantics.semantic_confidence in TRUSTED_CONFIDENCE:
        return
    if allow_unverified_semantics:
        return
    raise refuse(
        "UNVERIFIED_SEMANTICS",
        f"semantic_confidence is {semantics.semantic_confidence!r}; automatic transformation "
        "is refused. Ask the user to confirm, then pass allow_unverified_semantics=True",
        series_id=semantics.series_id,
    )


def resolve_aggregation(semantics: SeriesSemantics) -> str:
    """Return how this series' observations may be combined into a coarser period.

    The rule comes from ``measure_type`` and, where the measure type alone does not decide it,
    from the catalog's ``default_agg``. Nothing is inferred from the values themselves.
    """

    measure_type = semantics.measure_type

    if measure_type == "stock":
        # A stock is a level at a point in time. The period's stock is its closing value; a
        # sum would add the same balance to itself once per week.
        return "last"

    if measure_type == "flow_periodic":
        # Each observation covers its own period, so the periods add up.
        return "sum"

    if measure_type in {"rate", "index"}:
        rule = semantics.default_agg
        if rule is None:
            raise refuse(
                "MISSING_AGGREGATION_RULE",
                f"measure_type {measure_type!r} has no single correct aggregation; the "
                "catalog must declare default_agg for this series",
                series_id=semantics.series_id,
            )
        if rule not in _RATE_LIKE_RULES:
            raise refuse(
                "UNSUPPORTED_AGGREGATION_RULE",
                f"default_agg {rule!r} is not meaningful for measure_type {measure_type!r}",
                series_id=semantics.series_id,
            )
        return rule

    if measure_type == "ratio":
        raise refuse(
            "UNSUPPORTED_MEASURE_TYPE",
            "a ratio must be recomputed from its numerator and denominator over the target "
            "period; averaging the ratios is not the same number, and Silver does not carry "
            "the two components",
            series_id=semantics.series_id,
        )

    if measure_type in {"flow_ytd", "flow_cumulative"}:
        raise refuse(
            "DECOMPOSITION_REQUIRED",
            f"measure_type {measure_type!r} accumulates, so adding the observations would "
            "count earlier periods again; call decompose_cumulative first",
            series_id=semantics.series_id,
        )

    if measure_type == "count":
        raise refuse(
            "UNSUPPORTED_MEASURE_TYPE",
            "a count may be a point-in-time population or a number of events in the period, "
            "and those aggregate differently; no verified rule exists for this repository",
            series_id=semantics.series_id,
        )

    if measure_type == "unknown":
        raise refuse(
            "UNSUPPORTED_MEASURE_TYPE",
            "measure_type is 'unknown', which is the catalog saying the meaning was never "
            "established; no automatic transformation is applied",
            series_id=semantics.series_id,
        )

    raise refuse(
        "UNSUPPORTED_MEASURE_TYPE",
        f"measure_type {measure_type!r} has no Gold rule",
        series_id=semantics.series_id,
    )


def require_decomposable(semantics: SeriesSemantics) -> str:
    """Return the cumulative kind, or refuse a series that does not accumulate."""

    if semantics.measure_type == "flow_ytd":
        if semantics.cumulative_reset != "yearly":
            raise refuse(
                "MISSING_CUMULATIVE_RESET",
                "a flow_ytd series must declare cumulative_reset='yearly'; without it the "
                "reset boundary is unknown",
                series_id=semantics.series_id,
            )
        return "flow_ytd"
    if semantics.measure_type == "flow_cumulative":
        return "flow_cumulative"
    raise refuse(
        "NOT_DECOMPOSABLE",
        f"measure_type {semantics.measure_type!r} does not accumulate, so there is nothing to "
        "decompose; use align_frequency instead",
        series_id=semantics.series_id,
    )


__all__ = [
    "ACTIVE_STATUS",
    "AGGREGATION_RULES",
    "TRUSTED_CONFIDENCE",
    "SeriesSemantics",
    "load_semantics",
    "require_active_status",
    "require_decomposable",
    "require_trusted_semantics",
    "resolve_aggregation",
]
