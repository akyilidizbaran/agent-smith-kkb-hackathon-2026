"""``decompose_cumulative`` over SYNTHETIC accumulating series.

The Git-versioned catalog holds no ``flow_ytd`` or ``flow_cumulative`` series, so every series
here is **SYNTHETIC**: a catalog row inserted into the test database and observation values
chosen to make each rule visible. None of these numbers is a real economic quantity.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.lakehouse.gold import GoldError, decompose_cumulative
from src.lakehouse.silver.foundation import materialize_fact_observation_snapshot

from ._support import SYNTHETIC_SERIES, add_synthetic_series, staging_rows


def _decompose(connection, key: str, observations, **kwargs) -> pd.DataFrame:
    spec = SYNTHETIC_SERIES[key]
    add_synthetic_series(connection, spec)
    materialize_fact_observation_snapshot(
        connection, staging_rows(spec["series_id"], observations, **kwargs)
    )
    return decompose_cumulative(connection, spec["series_id"])


def _flows(frame: pd.DataFrame) -> list[tuple[date, object, str]]:
    return [
        (
            row["period_start"],
            None if row["value"] is None or pd.isna(row["value"]) else float(row["value"]),
            row["decomposition_flag"],
        )
        for _, row in frame.iterrows()
    ]


# ==================================================================== flow_ytd


def test_ytd_differences_inside_the_year_and_resets_in_january(connection) -> None:
    """January's YTD total is January's own flow; the new year never subtracts December."""

    frame = _decompose(
        connection,
        "ytd_monthly",
        [
            (date(2025, 1, 31), "10.0"),
            (date(2025, 2, 28), "25.0"),
            (date(2025, 3, 31), "45.0"),
            (date(2026, 1, 31), "12.0"),
            (date(2026, 2, 28), "30.0"),
        ],
    )

    assert _flows(frame) == [
        (date(2025, 1, 1), 10.0, "ok"),   # January YTD is January's flow
        (date(2025, 2, 1), 15.0, "ok"),   # 25 - 10
        (date(2025, 3, 1), 20.0, "ok"),   # 45 - 25
        (date(2026, 1, 1), 12.0, "ok"),   # reset: NOT 12 - 45
        (date(2026, 2, 1), 18.0, "ok"),   # 30 - 12
    ]
    january_2026 = frame[frame["period_start"] == date(2026, 1, 1)].iloc[0]
    assert january_2026["previous_cumulative_value"] is None
    assert float(january_2026["cumulative_value"]) == 12.0


def test_a_year_starting_mid_year_is_not_attributed_to_one_month(connection) -> None:
    """A first reading in June covers January through June, so it is not June's flow."""

    frame = _decompose(
        connection,
        "ytd_monthly",
        [(date(2025, 6, 30), "60.0"), (date(2025, 7, 31), "72.0")],
    )

    june, july = frame.iloc[0], frame.iloc[1]
    assert june["decomposition_flag"] == "unattributable_year_start"
    assert june["value"] is None or pd.isna(june["value"])
    # The number is not thrown away, it is just not called a monthly flow.
    assert float(june["raw_change"]) == 60.0
    assert float(july["value"]) == 12.0
    assert july["decomposition_flag"] == "ok"


def test_a_flow_ytd_series_without_a_declared_reset_is_refused(connection) -> None:
    spec = SYNTHETIC_SERIES["ytd_no_reset_monthly"]
    add_synthetic_series(connection, spec)
    materialize_fact_observation_snapshot(
        connection, staging_rows(spec["series_id"], [(date(2025, 1, 31), "1.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        decompose_cumulative(connection, spec["series_id"])
    assert excinfo.value.refusal.reason == "MISSING_CUMULATIVE_RESET"


# ============================================================== flow_cumulative


def test_the_first_cumulative_reading_has_no_known_base(connection) -> None:
    """Whatever accumulated before the series starts is unknown, so no flow is invented."""

    frame = _decompose(
        connection,
        "cumulative_monthly",
        [
            (date(2025, 1, 31), "100.0"),
            (date(2025, 2, 28), "130.0"),
            (date(2025, 3, 31), "160.0"),
        ],
    )

    assert _flows(frame) == [
        (date(2025, 1, 1), None, "no_prior_base"),
        (date(2025, 2, 1), 30.0, "ok"),
        (date(2025, 3, 1), 30.0, "ok"),
    ]
    assert frame.iloc[0]["raw_change"] is None


def test_a_cumulative_series_does_not_reset_at_the_year_boundary(connection) -> None:
    frame = _decompose(
        connection,
        "cumulative_monthly",
        [(date(2025, 12, 31), "500.0"), (date(2026, 1, 31), "530.0")],
    )

    january = frame[frame["period_start"] == date(2026, 1, 1)].iloc[0]
    assert january["decomposition_flag"] == "ok"
    assert float(january["value"]) == 30.0


# =============================================================== gaps and signs


def test_a_gap_is_not_attributed_to_a_single_period(connection) -> None:
    """February is missing, so the March change covers two months and is not March's flow."""

    frame = _decompose(
        connection,
        "cumulative_monthly",
        [
            (date(2025, 1, 31), "100.0"),
            (date(2025, 3, 31), "160.0"),
            (date(2025, 4, 30), "180.0"),
        ],
    )

    march = frame[frame["period_start"] == date(2025, 3, 1)].iloc[0]
    assert march["decomposition_flag"] == "spans_multiple_periods"
    assert march["value"] is None or pd.isna(march["value"])
    # The change and the period it really covers stay visible.
    assert float(march["raw_change"]) == 60.0
    assert march["previous_observation_date"] == date(2025, 1, 31)

    april = frame[frame["period_start"] == date(2025, 4, 1)].iloc[0]
    assert april["decomposition_flag"] == "ok"
    assert float(april["value"]) == 20.0


def test_a_negative_change_is_emitted_but_flagged(connection) -> None:
    """A falling running total is either a real outflow or a revision; Gold will not guess."""

    frame = _decompose(
        connection,
        "cumulative_monthly",
        [(date(2025, 1, 31), "100.0"), (date(2025, 2, 28), "90.0")],
    )

    february = frame.iloc[1]
    assert february["decomposition_flag"] == "negative_change"
    assert float(february["value"]) == -10.0
    assert float(february["raw_change"]) == -10.0


def test_a_missing_reading_breaks_the_chain_without_inventing_a_flow(connection) -> None:
    frame = _decompose(
        connection,
        "cumulative_monthly",
        [
            (date(2025, 1, 31), "100.0"),
            (date(2025, 2, 28), None),
            (date(2025, 3, 31), "160.0"),
        ],
    )

    assert frame.iloc[1]["decomposition_flag"] == "missing_value"
    assert frame.iloc[1]["value"] is None or pd.isna(frame.iloc[1]["value"])
    # March cannot be measured against a missing February.
    assert frame.iloc[2]["decomposition_flag"] == "no_prior_base"
    assert frame.iloc[2]["value"] is None or pd.isna(frame.iloc[2]["value"])


# ==================================================================== refusals


def test_a_non_accumulating_series_is_refused(connection) -> None:
    spec = SYNTHETIC_SERIES["stock_monthly"]
    add_synthetic_series(connection, spec)
    materialize_fact_observation_snapshot(
        connection, staging_rows(spec["series_id"], [(date(2025, 1, 31), "1.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        decompose_cumulative(connection, spec["series_id"])
    assert excinfo.value.refusal.reason == "NOT_DECOMPOSABLE"
    assert "align_frequency" in str(excinfo.value)


def test_derived_semantics_are_refused_by_default(connection) -> None:
    spec = SYNTHETIC_SERIES["ytd_derived_monthly"]
    add_synthetic_series(connection, spec)
    materialize_fact_observation_snapshot(
        connection, staging_rows(spec["series_id"], [(date(2025, 1, 31), "1.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        decompose_cumulative(connection, spec["series_id"])
    assert excinfo.value.refusal.reason == "UNVERIFIED_SEMANTICS"

    allowed = decompose_cumulative(
        connection, spec["series_id"], allow_unverified_semantics=True
    )
    assert allowed.iloc[0]["decomposition_flag"] == "ok"


def test_two_vintages_for_one_period_are_refused(connection) -> None:
    spec = SYNTHETIC_SERIES["cumulative_monthly"]
    add_synthetic_series(connection, spec)
    materialize_fact_observation_snapshot(
        connection,
        pd.concat(
            [
                staging_rows(spec["series_id"], [(date(2025, 1, 31), "100.0")], digest="a"),
                staging_rows(spec["series_id"], [(date(2025, 1, 31), "101.0")], digest="b"),
            ],
            ignore_index=True,
        ),
    )

    with pytest.raises(GoldError) as excinfo:
        decompose_cumulative(connection, spec["series_id"])
    assert excinfo.value.refusal.reason == "AMBIGUOUS_VINTAGE"


def test_provenance_survives_decomposition(connection) -> None:
    frame = _decompose(
        connection,
        "cumulative_monthly",
        [(date(2025, 1, 31), "100.0"), (date(2025, 2, 28), "130.0")],
    )

    assert set(frame["artifact_sha256"]) == {"a" * 64}
    assert set(frame["vintage_id"]) == {f"artifact:{'a' * 64}"}
    assert frame["cumulative_value"].notna().all()
