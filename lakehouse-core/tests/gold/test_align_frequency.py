"""``align_frequency`` over real fixtures and clearly-marked synthetic catalog rows.

The two mandatory examples run against the committed BDDK weekly fixture and the committed
EVDS KTF12 fixture through the real connector, parser, Silver adapter and materialization, so
the aggregation is proved on the same bytes the demo will use.

Cases the catalog cannot supply -- there is no `ratio`, `flow_periodic`, `count` or `unknown`
series in `catalog/series/*.yml` -- use **synthetic** catalog rows inserted into the test
database only. They are marked `SYNTHETIC` at every definition and are never written to the
Git-versioned catalog.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.lakehouse.gold import GoldError, align_frequency
from src.lakehouse.silver.foundation import materialize_fact_observation_snapshot

from ._support import (
    SYNTHETIC_SERIES,
    add_synthetic_series,
    ingest_bddk_weekly,
    ingest_evds_ktf12,
    staging_rows,
)


# ============================================================ mandatory examples


def test_ktf12_weekly_rate_becomes_a_monthly_average(tmp_path: Path, monkeypatch: Any) -> None:
    """Mandatory example 1: catalog says ``default_agg=avg`` for this rate."""

    connection, silver = ingest_evds_ktf12(tmp_path, monkeypatch)
    try:
        aligned = align_frequency(connection, "evds:TP.KTF12", "monthly")

        january = aligned[aligned["period_start"] == date(2021, 1, 1)].iloc[0]
        weekly = silver[
            (silver["observation_date"] >= date(2021, 1, 1))
            & (silver["observation_date"] <= date(2021, 1, 31))
        ]
        expected = sum(float(v) for v in weekly["value"]) / len(weekly)

        assert january["aggregation"] == "avg"
        assert january["measure_type"] == "rate"
        assert january["unit"] == "pct"
        assert january["observations"] == 4
        assert float(january["value"]) == pytest.approx(expected)
        assert january["period_end"] == date(2021, 1, 31)
        assert january["quality_flag"] == "ok"
    finally:
        connection.close()


def test_bddk_weekly_stock_becomes_the_last_observation_of_the_month(
    tmp_path: Path,
) -> None:
    """Mandatory example 2: a stock takes the month's closing reading, never a sum."""

    connection, _ = ingest_bddk_weekly(tmp_path)
    try:
        aligned = align_frequency(connection, "bddk_weekly:5690_3", "monthly")

        march = aligned[aligned["period_start"] == date(2026, 3, 1)].iloc[0]
        # March holds 13.03 (Friday), 19.03 (Thursday) and 27.03 (Friday).
        assert march["observations"] == 3
        assert march["aggregation"] == "last"
        assert float(march["value"]) == 740789.871  # the 27.03 reading
        # The sum of the three would be this; a stock must never produce it.
        assert float(march["value"]) != pytest.approx(731311.768 + 734860.422 + 740789.871)
        assert march["entity_id"] == "bddk:10001"
    finally:
        connection.close()


def test_the_holiday_thursday_stays_in_march_with_its_own_date(tmp_path: Path) -> None:
    """The fixture's 19.03.2026 is a Thursday; it must be boxed by its real date."""

    connection, _ = ingest_bddk_weekly(tmp_path)
    try:
        thursday = date(2026, 3, 19)
        assert thursday.weekday() == 3, "fixture precondition"

        aligned = align_frequency(connection, "bddk_weekly:5690_3", "monthly")
        march = aligned[aligned["period_start"] == date(2026, 3, 1)].iloc[0]

        assert thursday in list(march["source_observation_dates"])
        # It was neither moved to the following Friday nor pushed out of March.
        assert date(2026, 3, 20) not in list(march["source_observation_dates"])
        assert len(march["source_observation_dates"]) == 3
    finally:
        connection.close()


def test_quarterly_alignment_uses_calendar_quarters(tmp_path: Path) -> None:
    connection, _ = ingest_bddk_weekly(tmp_path)
    try:
        aligned = align_frequency(connection, "bddk_weekly:5690_3", "quarterly")

        first = aligned[aligned["period_start"] == date(2026, 1, 1)].iloc[0]
        assert first["period_end"] == date(2026, 3, 31)
        assert first["observations"] == 4  # 02.01, 13.03, 19.03, 27.03
        assert float(first["value"]) == 740789.871

        second = aligned[aligned["period_start"] == date(2026, 4, 1)].iloc[0]
        assert second["period_end"] == date(2026, 6, 30)
        assert float(second["value"]) == 800464.007
    finally:
        connection.close()


# ================================================================ identity path


def test_same_frequency_returns_the_source_values_unchanged(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["stock_monthly"])
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(
            "synthetic:stock_monthly",
            [(date(2026, 1, 31), "10.5"), (date(2026, 2, 28), "11.5")],
        ),
    )

    aligned = align_frequency(connection, "synthetic:stock_monthly", "monthly")

    assert aligned["aggregation"].tolist() == ["identity", "identity"]
    assert [float(value) for value in aligned["value"]] == [10.5, 11.5]
    assert aligned["period_end"].tolist() == [date(2026, 1, 31), date(2026, 2, 28)]
    assert aligned["observations"].tolist() == [1, 1]


def test_two_observations_in_one_identity_period_is_a_grain_conflict(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["stock_monthly"])
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(
            "synthetic:stock_monthly",
            [(date(2026, 1, 15), "10.5"), (date(2026, 1, 31), "11.5")],
        ),
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, "synthetic:stock_monthly", "monthly")
    assert excinfo.value.refusal.reason == "PERIOD_GRAIN_CONFLICT"


# ==================================================================== refusals


def test_upsampling_is_refused(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["stock_quarterly"])
    materialize_fact_observation_snapshot(
        connection,
        staging_rows("synthetic:stock_quarterly", [(date(2026, 3, 31), "1.0")]),
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, "synthetic:stock_quarterly", "monthly")
    assert excinfo.value.refusal.reason == "UPSAMPLING_REFUSED"
    assert "invent" in str(excinfo.value)


def test_ratio_is_refused(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["ratio_weekly"])
    materialize_fact_observation_snapshot(
        connection, staging_rows("synthetic:ratio_weekly", [(date(2026, 1, 2), "0.4")])
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, "synthetic:ratio_weekly", "monthly")
    assert excinfo.value.refusal.reason == "UNSUPPORTED_MEASURE_TYPE"
    assert "numerator" in str(excinfo.value)


@pytest.mark.parametrize("key", ["count_weekly", "unknown_weekly"])
def test_measure_types_without_a_verified_rule_are_refused(connection, key: str) -> None:
    """Refused at the semantics gate, before a single Silver row is read.

    Silver independently refuses ``measure_type='unknown'`` at materialization, so these two
    series can never reach the fact table anyway. Gold still has to refuse them on its own,
    because a catalog row is all it takes to ask.
    """

    add_synthetic_series(connection, SYNTHETIC_SERIES[key])
    series_id = SYNTHETIC_SERIES[key]["series_id"]

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, series_id, "monthly")
    assert excinfo.value.refusal.reason == "UNSUPPORTED_MEASURE_TYPE"


@pytest.mark.parametrize("key", ["ytd_monthly", "cumulative_monthly"])
def test_accumulating_series_must_be_decomposed_first(connection, key: str) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES[key])
    series_id = SYNTHETIC_SERIES[key]["series_id"]
    materialize_fact_observation_snapshot(
        connection, staging_rows(series_id, [(date(2026, 1, 31), "5.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, series_id, "monthly")
    assert excinfo.value.refusal.reason == "DECOMPOSITION_REQUIRED"
    assert "decompose_cumulative" in str(excinfo.value)


def test_a_series_missing_from_the_catalog_is_refused(connection) -> None:
    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, "evds:NOT.CATALOGUED", "monthly")
    assert excinfo.value.refusal.reason == "SERIES_NOT_CATALOGUED"


def test_an_unsupported_target_frequency_is_refused(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["stock_monthly"])
    materialize_fact_observation_snapshot(
        connection, staging_rows("synthetic:stock_monthly", [(date(2026, 1, 31), "1.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, "synthetic:stock_monthly", "yearly")
    assert excinfo.value.refusal.reason == "UNSUPPORTED_TARGET_FREQUENCY"


def test_a_rate_without_a_default_agg_is_refused(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["rate_no_agg_weekly"])
    materialize_fact_observation_snapshot(
        connection, staging_rows("synthetic:rate_no_agg", [(date(2026, 1, 2), "1.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, "synthetic:rate_no_agg", "monthly")
    assert excinfo.value.refusal.reason == "MISSING_AGGREGATION_RULE"


def test_summing_a_rate_is_refused_even_if_the_catalog_asks_for_it(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["rate_sum_weekly"])
    materialize_fact_observation_snapshot(
        connection, staging_rows("synthetic:rate_sum", [(date(2026, 1, 2), "1.0")])
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, "synthetic:rate_sum", "monthly")
    assert excinfo.value.refusal.reason == "UNSUPPORTED_AGGREGATION_RULE"


# ================================================= unverified semantics gate


def test_derived_semantics_are_refused_by_default(tmp_path: Path, monkeypatch: Any) -> None:
    """TÜFE and KFE are both ``derived`` today, so neither converts automatically."""

    from ._support import ingest_evds_cpi

    connection, _ = ingest_evds_cpi(tmp_path, monkeypatch)
    try:
        with pytest.raises(GoldError) as excinfo:
            align_frequency(connection, "evds:TP.FG.J0", "quarterly")
        assert excinfo.value.refusal.reason == "UNVERIFIED_SEMANTICS"
        assert "allow_unverified_semantics" in str(excinfo.value)
    finally:
        connection.close()


def test_the_override_only_relaxes_confidence_and_never_supplies_a_rule(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """With explicit consent TÜFE aligns -- using the catalog's own ``default_agg=last``."""

    from ._support import ingest_evds_cpi

    connection, _ = ingest_evds_cpi(tmp_path, monkeypatch)
    try:
        aligned = align_frequency(
            connection, "evds:TP.FG.J0", "quarterly", allow_unverified_semantics=True
        )
        assert aligned["aggregation"].tolist() == ["last"]
        assert aligned["measure_type"].tolist() == ["index"]

        # The override cannot be used to smuggle a different rule in: the signature has no
        # parameter for one, and the value still came from meta.series.
        import inspect

        parameters = set(inspect.signature(align_frequency).parameters)
        assert parameters == {
            "connection",
            "series_id",
            "target_frequency",
            "allow_unverified_semantics",
        }
    finally:
        connection.close()


# ==================================================== nulls, warnings, vintages


def test_an_all_null_period_is_never_zero(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["flow_weekly"])
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(
            "synthetic:flow_weekly",
            [(date(2026, 1, 2), None), (date(2026, 1, 9), None)],
        ),
    )

    aligned = align_frequency(connection, "synthetic:flow_weekly", "monthly")
    row = aligned.iloc[0]

    assert row["value"] is None or pd.isna(row["value"])
    assert row["value"] != 0
    assert row["quality_flag"] == "missing_value"
    assert row["observations"] == 2
    assert row["missing_observations"] == 2


def test_a_partially_null_period_is_flagged_and_counted(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["flow_weekly"])
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(
            "synthetic:flow_weekly",
            [
                (date(2026, 1, 2), "10.0"),
                (date(2026, 1, 9), None),
                (date(2026, 1, 16), "20.0"),
            ],
        ),
    )

    row = align_frequency(connection, "synthetic:flow_weekly", "monthly").iloc[0]

    # The sum uses the two real observations and does not treat the gap as a zero.
    assert float(row["value"]) == 30.0
    assert row["quality_flag"] == "partial_period"
    assert row["observations"] == 3
    assert row["missing_observations"] == 1


def test_a_source_warning_survives_aggregation(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["flow_weekly"])
    materialize_fact_observation_snapshot(
        connection,
        staging_rows(
            "synthetic:flow_weekly",
            [(date(2026, 1, 2), "10.0"), (date(2026, 1, 9), "20.0")],
            source_warning='["SYNTHETIC parser warning"]',
        ),
    )

    row = align_frequency(connection, "synthetic:flow_weekly", "monthly").iloc[0]

    assert row["quality_flag"] == "source_warning"
    assert row["warned_observations"] == 2
    assert float(row["value"]) == 30.0


def test_two_vintages_for_one_period_are_refused(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["stock_monthly"])
    materialize_fact_observation_snapshot(
        connection,
        pd.concat(
            [
                staging_rows(
                    "synthetic:stock_monthly", [(date(2026, 1, 31), "10.0")], digest="a"
                ),
                staging_rows(
                    "synthetic:stock_monthly", [(date(2026, 1, 31), "11.0")], digest="b"
                ),
            ],
            ignore_index=True,
        ),
    )

    with pytest.raises(GoldError) as excinfo:
        align_frequency(connection, "synthetic:stock_monthly", "monthly")
    assert excinfo.value.refusal.reason == "AMBIGUOUS_VINTAGE"
    assert "2026-01-31" in str(excinfo.value)


def test_provenance_reaches_every_aligned_row(tmp_path: Path) -> None:
    connection, silver = ingest_bddk_weekly(tmp_path)
    try:
        aligned = align_frequency(connection, "bddk_weekly:5690_3", "monthly")
        row = aligned[aligned["period_start"] == date(2026, 3, 1)].iloc[0]

        assert row["artifact_sha256_list"] == sorted(set(silver["artifact_sha256"]))
        assert row["vintage_id_list"] == sorted(set(silver["vintage_id"]))
        assert row["run_id_list"] == sorted(set(silver["run_id"]))
        assert len(row["source_observation_dates"]) == 3
    finally:
        connection.close()


def test_different_entities_stay_on_separate_lines(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["stock_monthly"])
    materialize_fact_observation_snapshot(
        connection,
        pd.concat(
            [
                staging_rows(
                    "synthetic:stock_monthly",
                    [(date(2026, 1, 31), "10.0")],
                    entity_id="synthetic:sector",
                    digest="a",
                ),
                staging_rows(
                    "synthetic:stock_monthly",
                    [(date(2026, 1, 31), "4.0")],
                    entity_id="synthetic:one_bank",
                    digest="b",
                ),
            ],
            ignore_index=True,
        ),
    )

    aligned = align_frequency(connection, "synthetic:stock_monthly", "monthly")

    assert len(aligned) == 2
    assert sorted(aligned["entity_id"]) == ["synthetic:one_bank", "synthetic:sector"]
    assert sorted(float(value) for value in aligned["value"]) == [4.0, 10.0]
