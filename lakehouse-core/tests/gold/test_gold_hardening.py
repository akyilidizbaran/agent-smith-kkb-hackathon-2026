"""Regression tests for the seven hardening findings.

Each test names the behaviour that was wrong and pins the corrected one. Every synthetic
catalog row and observation is marked SYNTHETIC in `_support.py` and lives only in the test
database.
"""

from __future__ import annotations

import inspect
from datetime import date

import pandas as pd
import pytest

from src.lakehouse.gold import (
    GoldError,
    align_frequency,
    decompose_cumulative,
    join_on_period,
)
from src.lakehouse.gold.align import GOLD_QUALITY_FLAGS
from src.lakehouse.silver.foundation import materialize_fact_observation_snapshot

from ._support import SYNTHETIC_SERIES, add_synthetic_series, staging_rows


def _series(connection, key: str, **overrides) -> str:
    spec = dict(SYNTHETIC_SERIES[key])
    spec.update(overrides)
    add_synthetic_series(connection, spec)
    return spec["series_id"]


def _value(row) -> float | None:
    return None if row["value"] is None or pd.isna(row["value"]) else float(row["value"])


# ==================================== 1. boundary rules never carry a value forward


def test_last_does_not_carry_the_previous_value_forward(connection) -> None:
    """The month's closing reading is missing, so the month's closing balance is unknown.

    Before this fix the January stock reported 10.0 -- the 02.01 reading -- even though the
    source published nothing for 30.01. That is a forward fill, and this layer promises not to
    do one.
    """

    sid = _series(
        connection,
        "stock_monthly",
        series_id="synthetic:stock_weekly",
        frequency="weekly",
        week_anchor="friday",
    )
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(sid, [(date(2026, 1, 2), "10.0"), (date(2026, 1, 30), None)]),
    )

    row = align_frequency(connection, sid, "monthly").iloc[0]

    assert _value(row) is None
    assert _value(row) != 10.0
    assert row["quality_flag"] == "boundary_missing"
    assert row["observations"] == 2
    assert row["missing_observations"] == 1


def test_first_is_symmetric_when_the_opening_reading_is_missing(connection) -> None:
    sid = _series(
        connection,
        "rate_weekly",
        series_id="synthetic:rate_first",
        default_agg="first",
    )
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(sid, [(date(2026, 1, 2), None), (date(2026, 1, 30), "20.0")]),
    )

    row = align_frequency(connection, sid, "monthly").iloc[0]

    assert _value(row) is None
    assert _value(row) != 20.0
    assert row["quality_flag"] == "boundary_missing"


def test_last_selects_the_final_reading_even_when_an_earlier_one_is_missing(
    connection,
) -> None:
    """The gap is real and reported, but it does not change which reading `last` selects."""

    sid = _series(
        connection,
        "stock_monthly",
        series_id="synthetic:stock_weekly",
        frequency="weekly",
        week_anchor="friday",
    )
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(
            sid,
            [
                (date(2026, 1, 2), "10.0"),
                (date(2026, 1, 16), None),
                (date(2026, 1, 30), "12.0"),
            ],
        ),
    )

    row = align_frequency(connection, sid, "monthly").iloc[0]

    assert _value(row) == 12.0
    assert row["quality_flag"] == "partial_period"
    assert row["missing_observations"] == 1


def test_value_rules_keep_the_partial_null_policy(connection) -> None:
    """`sum`/`avg` still compute over the readings that exist -- that policy is unchanged."""

    sid = _series(connection, "flow_weekly")
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(
            sid,
            [
                (date(2026, 1, 2), "10.0"),
                (date(2026, 1, 9), None),
                (date(2026, 1, 16), "20.0"),
            ],
        ),
    )

    row = align_frequency(connection, sid, "monthly").iloc[0]
    assert _value(row) == 30.0
    assert row["quality_flag"] == "partial_period"


def test_boundary_missing_is_part_of_the_quality_vocabulary() -> None:
    assert "boundary_missing" in GOLD_QUALITY_FLAGS


# ================================= 2. a difference carries both of its contributors


def test_a_difference_names_both_artifacts(connection) -> None:
    """Two consecutive readings from different artifacts both have to be visible."""

    sid = _series(connection, "cumulative_monthly")
    materialize_fact_observation_snapshot(
        connection,
        pd.concat(
            [
                staging_rows(sid, [(date(2025, 1, 31), "100.0")], digest="a"),
                staging_rows(sid, [(date(2025, 2, 28), "130.0")], digest="b"),
            ],
            ignore_index=True,
        ),
    )

    february = decompose_cumulative(connection, sid).iloc[1]

    assert _value(february) == 30.0
    assert february["artifact_sha256"] == "b" * 64
    assert february["previous_artifact_sha256"] == "a" * 64
    assert february["previous_observation_date"] == date(2025, 1, 31)
    assert february["artifact_sha256_list"] == sorted({"a" * 64, "b" * 64})
    assert february["vintage_id_list"] == sorted(
        {f"artifact:{'a' * 64}", f"artifact:{'b' * 64}"}
    )
    assert february["source_observation_dates"] == [date(2025, 1, 31), date(2025, 2, 28)]
    assert february["contributor_count"] == 2


def test_a_warning_on_the_base_reading_taints_the_derived_flow(connection) -> None:
    """Only the *previous* reading is warned; the flow computed from it is not clean."""

    sid = _series(connection, "cumulative_monthly")
    materialize_fact_observation_snapshot(
        connection,
        pd.concat(
            [
                staging_rows(
                    sid,
                    [(date(2025, 1, 31), "100.0")],
                    digest="a",
                    source_warning='["SYNTHETIC warning on the base reading"]',
                ),
                staging_rows(sid, [(date(2025, 2, 28), "130.0")], digest="b"),
            ],
            ignore_index=True,
        ),
    )

    frame = decompose_cumulative(connection, sid)
    february = frame.iloc[1]

    assert february["decomposition_flag"] == "ok"
    assert february["quality_flag"] == "source_warning"
    assert february["quality_flag"] != "ok"


def test_the_first_ytd_period_reports_a_single_contributor(connection) -> None:
    sid = _series(connection, "ytd_monthly")
    materialize_fact_observation_snapshot(
        connection, staging_rows(sid, [(date(2025, 1, 31), "10.0")])
    )

    january = decompose_cumulative(connection, sid).iloc[0]

    assert january["decomposition_flag"] == "ok"
    assert _value(january) == 10.0
    assert january["contributor_count"] == 1
    assert january["previous_artifact_sha256"] is None
    assert january["source_observation_dates"] == [date(2025, 1, 31)]


# ============================ 3. non-monthly cumulative adjacency is not guessed


@pytest.mark.parametrize("frequency", ["weekly", "daily", "business_daily", "biweekly"])
def test_cumulative_decomposition_refuses_frequencies_without_a_reliable_adjacency_test(
    connection, frequency: str
) -> None:
    """A weekly bulletin shifting to a Thursday is normal, not a gap -- so do not guess."""

    sid = _series(
        connection,
        "cumulative_monthly",
        series_id="synthetic:cum_other_freq",
        frequency=frequency,
        week_anchor="friday" if frequency == "weekly" else None,
    )
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(sid, [(date(2026, 1, 2), "100.0"), (date(2026, 1, 23), "130.0")]),
    )

    with pytest.raises(GoldError) as excinfo:
        decompose_cumulative(connection, sid)
    assert excinfo.value.refusal.reason == "UNSUPPORTED_SOURCE_FREQUENCY"


def test_a_three_week_gap_is_never_published_as_one_period_flow(connection) -> None:
    """The exact case that used to return ok/30.0."""

    sid = _series(
        connection,
        "cumulative_monthly",
        series_id="synthetic:cum_weekly",
        frequency="weekly",
        week_anchor="friday",
    )
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(sid, [(date(2026, 1, 2), "100.0"), (date(2026, 1, 23), "130.0")]),
    )

    with pytest.raises(GoldError) as excinfo:
        decompose_cumulative(connection, sid)
    assert excinfo.value.refusal.reason == "UNSUPPORTED_SOURCE_FREQUENCY"
    assert "multi-period difference" in str(excinfo.value)


def test_two_cumulative_readings_in_one_month_are_a_grain_conflict(connection) -> None:
    """Differencing a period against itself is not a gap; it is bad grain."""

    sid = _series(connection, "cumulative_monthly")
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(sid, [(date(2026, 1, 10), "100.0"), (date(2026, 1, 31), "130.0")]),
    )

    with pytest.raises(GoldError) as excinfo:
        decompose_cumulative(connection, sid)
    assert excinfo.value.refusal.reason == "PERIOD_GRAIN_CONFLICT"


# =========================================== 4. catalog status is actually enforced


@pytest.mark.parametrize("status", ["draft", "deprecated"])
def test_align_refuses_a_non_active_series(connection, status: str) -> None:
    sid = _series(connection, "stock_monthly")
    connection.execute(
        "UPDATE meta.series SET status = ? WHERE series_id = ?", [status, sid]
    )
    materialize_fact_observation_snapshot(
        connection, staging_rows(sid, [(date(2026, 1, 31), "10.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, sid, "monthly")
    assert excinfo.value.refusal.reason == "INACTIVE_SERIES"


@pytest.mark.parametrize("status", ["draft", "deprecated"])
def test_decompose_refuses_a_non_active_series(connection, status: str) -> None:
    sid = _series(connection, "cumulative_monthly")
    connection.execute(
        "UPDATE meta.series SET status = ? WHERE series_id = ?", [status, sid]
    )
    materialize_fact_observation_snapshot(
        connection, staging_rows(sid, [(date(2025, 1, 31), "10.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        decompose_cumulative(connection, sid)
    assert excinfo.value.refusal.reason == "INACTIVE_SERIES"


@pytest.mark.parametrize("status", ["draft", "deprecated"])
def test_the_override_does_not_reopen_the_status_gate(connection, status: str) -> None:
    """Consenting to weak evidence is a different decision from using a withdrawn series."""

    sid = _series(connection, "stock_monthly")
    connection.execute(
        "UPDATE meta.series SET status = ? WHERE series_id = ?", [status, sid]
    )
    materialize_fact_observation_snapshot(
        connection, staging_rows(sid, [(date(2026, 1, 31), "10.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, sid, "monthly", allow_unverified_semantics=True)
    assert excinfo.value.refusal.reason == "INACTIVE_SERIES"


def test_join_refuses_when_any_series_is_inactive(connection) -> None:
    active = _series(connection, "stock_monthly")
    inactive = _series(connection, "flow_weekly")
    connection.execute(
        "UPDATE meta.series SET status = 'draft' WHERE series_id = ?", [inactive]
    )
    materialize_fact_observation_snapshot(
        connection,
        pd.concat(
            [
                staging_rows(active, [(date(2026, 1, 31), "10.0")], digest="a"),
                staging_rows(inactive, [(date(2026, 1, 2), "1.0")], digest="b"),
            ],
            ignore_index=True,
        ),
    )

    with pytest.raises(GoldError) as excinfo:
        join_on_period(connection, [active, inactive], "monthly")
    assert excinfo.value.refusal.reason == "INACTIVE_SERIES"


# ============================== 5. a catalogued series with no rows is said out loud


def test_align_refuses_a_series_with_no_observations(connection) -> None:
    empty = _series(connection, "stock_monthly")
    other = _series(connection, "flow_weekly")
    materialize_fact_observation_snapshot(
        connection, staging_rows(other, [(date(2026, 1, 2), "1.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, empty, "monthly")
    assert excinfo.value.refusal.reason == "NO_OBSERVATIONS"


def test_decompose_refuses_a_series_with_no_observations(connection) -> None:
    empty = _series(connection, "cumulative_monthly")
    other = _series(connection, "flow_weekly")
    materialize_fact_observation_snapshot(
        connection, staging_rows(other, [(date(2026, 1, 2), "1.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        decompose_cumulative(connection, empty)
    assert excinfo.value.refusal.reason == "NO_OBSERVATIONS"


def test_join_does_not_silently_drop_a_series_with_no_observations(connection) -> None:
    """A missing column is invisible; a refusal is not."""

    empty = _series(connection, "stock_monthly")
    other = _series(connection, "flow_weekly")
    materialize_fact_observation_snapshot(
        connection, staging_rows(other, [(date(2026, 1, 2), "1.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        join_on_period(connection, [empty, other], "monthly")
    assert excinfo.value.refusal.reason == "NO_OBSERVATIONS"


# ================================ 6. join keeps the source dates behind every cell


def test_join_carries_the_real_contributor_dates(connection) -> None:
    stock = _series(connection, "stock_monthly")
    flow = _series(connection, "flow_weekly")
    materialize_fact_observation_snapshot(
        connection,
        pd.concat(
            [
                staging_rows(stock, [(date(2026, 1, 31), "10.0")], digest="a"),
                staging_rows(
                    flow,
                    [(date(2026, 1, 2), "1.0"), (date(2026, 1, 16), "2.0")],
                    digest="b",
                ),
            ],
            ignore_index=True,
        ),
    )

    row = join_on_period(connection, [stock, flow], "monthly").iloc[0]

    assert row[f"{stock}::source_observation_dates"] == [date(2026, 1, 31)]
    assert row[f"{flow}::source_observation_dates"] == [
        date(2026, 1, 2),
        date(2026, 1, 16),
    ]


def test_an_absent_period_reports_empty_contributor_lists(connection) -> None:
    """Absent means "contributed nothing here", which an empty list states precisely."""

    stock = _series(connection, "stock_monthly")
    flow = _series(connection, "flow_weekly")
    materialize_fact_observation_snapshot(
        connection,
        pd.concat(
            [
                staging_rows(
                    stock,
                    [(date(2026, 1, 31), "10.0"), (date(2026, 2, 28), "11.0")],
                    digest="a",
                ),
                staging_rows(flow, [(date(2026, 2, 6), "1.0")], digest="b"),
            ],
            ignore_index=True,
        ),
    )

    january = join_on_period(connection, [stock, flow], "monthly").iloc[0]

    assert january[f"{flow}::source_observation_dates"] == []
    assert january[f"{flow}::artifact_sha256_list"] == []
    assert january[f"{flow}::vintage_id_list"] == []
    assert january[f"{flow}::observations"] == 0
    # The absent cell is still attributable to its series.
    assert january[f"{flow}::series_id"] == flow


# ============================================ 7. composition claim matches reality


def test_align_frequency_still_refuses_a_decomposed_series(connection) -> None:
    """The documented limitation, pinned: there is no composition path in V1."""

    sid = _series(connection, "cumulative_monthly")
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(sid, [(date(2025, 1, 31), "100.0"), (date(2025, 2, 28), "130.0")]),
    )

    decomposed = decompose_cumulative(connection, sid)
    assert not decomposed.empty

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, sid, "quarterly")
    assert excinfo.value.refusal.reason == "DECOMPOSITION_REQUIRED"

    # align_frequency takes a series id, not a frame, so the result cannot be piped into it.
    assert "frame" not in inspect.signature(align_frequency).parameters


def test_the_docstring_no_longer_promises_a_composition_path() -> None:
    assert "Feed the result to" not in (decompose_cumulative.__doc__ or "")
    assert "cannot be fed to" in (decompose_cumulative.__doc__ or "")


# ================================================= extra input validation


@pytest.mark.parametrize("bogus", ["false", "true", 1, 0, [], "yes"])
def test_a_non_bool_override_never_opens_the_confidence_gate(connection, bogus) -> None:
    sid = _series(connection, "stock_monthly", semantic_confidence="derived")
    materialize_fact_observation_snapshot(
        connection, staging_rows(sid, [(date(2026, 1, 31), "10.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, sid, "monthly", allow_unverified_semantics=bogus)
    assert excinfo.value.refusal.reason == "INVALID_ARGUMENT"


@pytest.mark.parametrize("bogus", ["false", 1, None])
def test_join_validates_the_override_type(connection, bogus) -> None:
    sid = _series(connection, "stock_monthly")
    materialize_fact_observation_snapshot(
        connection, staging_rows(sid, [(date(2026, 1, 31), "10.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        join_on_period(connection, [sid], "monthly", allow_unverified_semantics=bogus)
    assert excinfo.value.refusal.reason == "INVALID_ARGUMENT"


@pytest.mark.parametrize("bogus", ["", "   ", None, 42, ["nested"]])
def test_join_validates_every_series_id_element(connection, bogus) -> None:
    sid = _series(connection, "stock_monthly")
    materialize_fact_observation_snapshot(
        connection, staging_rows(sid, [(date(2026, 1, 31), "10.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        join_on_period(connection, [sid, bogus], "monthly")
    assert excinfo.value.refusal.reason == "INVALID_ARGUMENT"


def test_every_gold_failure_uses_the_closed_refusal_vocabulary(connection) -> None:
    from src.lakehouse.gold import GOLD_REFUSAL_REASONS

    sid = _series(connection, "stock_monthly")
    materialize_fact_observation_snapshot(
        connection, staging_rows(sid, [(date(2026, 1, 31), "10.0")])
    )

    attempts = [
        lambda: align_frequency(connection, "nope:missing", "monthly"),
        lambda: align_frequency(connection, sid, "yearly"),
        lambda: align_frequency(connection, sid, "monthly", allow_unverified_semantics="x"),
        lambda: decompose_cumulative(connection, sid),
        lambda: join_on_period(connection, [], "monthly"),
        lambda: join_on_period(connection, [sid, ""], "monthly"),
    ]
    for attempt in attempts:
        with pytest.raises(GoldError) as excinfo:
            attempt()
        assert excinfo.value.refusal.reason in GOLD_REFUSAL_REASONS
