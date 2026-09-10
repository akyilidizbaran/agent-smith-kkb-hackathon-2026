"""``join_on_period`` -- several series on one axis, each with its own catalog rule.

This is the demo shape: the housing-loan stock and the housing-loan interest rate side by
side, monthly. The stock must take month-end and the rate must take the monthly average, in
the same table, from the same call.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.lakehouse.gold import GoldError, column_key, join_on_period
from src.lakehouse.silver.foundation import materialize_fact_observation_snapshot

from ._support import (
    SYNTHETIC_SERIES,
    add_synthetic_series,
    ingest_bddk_weekly,
    staging_rows,
)


STOCK = "synthetic:stock_monthly"
RATE = "synthetic:rate_weekly"
FLOW = "synthetic:flow_weekly"


def _prepare(connection, frames: list[pd.DataFrame], keys: list[str]) -> None:
    for key in keys:
        add_synthetic_series(connection, SYNTHETIC_SERIES[key])
    materialize_fact_observation_snapshot(
        connection, pd.concat(frames, ignore_index=True)
    )


# ================================================== each series keeps its own rule


def test_each_series_is_aggregated_by_its_own_catalog_rule(connection) -> None:
    """A stock takes month-end while a rate is averaged, in one call."""

    _prepare(
        connection,
        [
            staging_rows(STOCK, [(date(2026, 1, 31), "100.0")], digest="a"),
            staging_rows(
                RATE,
                [(date(2026, 1, 2), "10.0"), (date(2026, 1, 30), "20.0")],
                digest="b",
            ),
        ],
        ["stock_monthly", "rate_weekly"],
    )

    joined = join_on_period(connection, [STOCK, RATE], "monthly")
    row = joined.iloc[0]

    assert row["period_start"] == date(2026, 1, 1)
    assert row["period_end"] == date(2026, 1, 31)
    assert float(row[f"{STOCK}::value"]) == 100.0
    assert row[f"{STOCK}::aggregation"] == "identity"
    assert float(row[f"{RATE}::value"]) == 15.0  # the average, not the sum
    assert row[f"{RATE}::aggregation"] == "avg"
    assert bool(row["is_complete_period"]) is True


def test_the_real_demo_pair_joins_on_one_monthly_axis(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """BDDK weekly loan stock plus the EVDS weekly rate, both from real fixtures."""

    from ._support import _FixtureSession, FETCHED_AT, FIXTURE_ROOT, REQUESTED_AT
    from src.lakehouse.connectors.evds import EVDS_API_KEY_ENV, EvdsConnector
    from src.lakehouse.contracts.models import FetchSpec
    from src.lakehouse.parsers.evds import EvdsParser
    from src.lakehouse.silver.adapters.evds import evds_ktf12_to_staging
    from src.lakehouse.silver.pipeline import stage_ingestion_result
    from src.lakehouse.catalog.artifacts import ArtifactRepository
    from src.lakehouse.ingestion.pipeline import IngestionPipeline
    from src.lakehouse.storage.parquet import ParquetStorage
    from src.lakehouse.storage.raw import RawStorage

    connection, _ = ingest_bddk_weekly(tmp_path)
    try:
        # Add the EVDS rate to the same database and republish one combined snapshot.
        monkeypatch.setenv(EVDS_API_KEY_ENV, "gold-test-only-key")
        evds_pipeline = IngestionPipeline(
            connector=EvdsConnector(
                RawStorage(tmp_path / "data/raw"),
                session=_FixtureSession(
                    (FIXTURE_ROOT / "evds/evds_ktf12_weekly.json").read_bytes()
                ),
                max_attempts=1,
                clock=lambda: FETCHED_AT,
            ),
            parser=EvdsParser(),
            artifact_repository=ArtifactRepository(connection),
            parquet_storage=ParquetStorage(tmp_path / "data/bronze"),
        )
        evds_result = evds_pipeline.run(
            FetchSpec(
                source_id="evds",
                dataset_id="evds_housing_interest",
                locator="fixture://evds",
                start_date=date(2021, 1, 1),
                end_date=date(2026, 6, 30),
                parameters={"series": "TP.KTF12", "type": "json"},
                requested_at=REQUESTED_AT,
            )
        )[0]
        evds_staging, _ = stage_ingestion_result(
            evds_result, adapter=evds_ktf12_to_staging
        )
        bddk_rows = connection.execute(
            "SELECT * FROM silver.fact_observation"
        ).fetchdf()

        # Rebuild the snapshot from the Silver rows already published plus the new staging.
        combined = pd.concat(
            [
                pd.DataFrame(
                    {
                        "series_id": bddk_rows["series_id"],
                        "entity_id": bddk_rows["entity_id"],
                        "observation_date": bddk_rows["observation_date"],
                        "period_start": bddk_rows["period_start"],
                        "period_end": bddk_rows["period_end"],
                        "value_raw": bddk_rows["value"].astype(object),
                        "source_id": bddk_rows["source_id"],
                        "dataset_id": bddk_rows["dataset_id"],
                        "artifact_sha256": bddk_rows["artifact_sha256"],
                        "fetched_at": bddk_rows["fetched_at"],
                        "schema_version": bddk_rows["schema_version"],
                        "vintage_id": bddk_rows["vintage_id"],
                        "run_id": bddk_rows["run_id"],
                        "source_warning": None,
                    }
                ),
                evds_staging,
            ],
            ignore_index=True,
        )
        materialize_fact_observation_snapshot(connection, combined)

        joined = join_on_period(
            connection, ["bddk_weekly:5690_3", "evds:TP.KTF12"], "monthly"
        )

        stock_key = column_key("bddk_weekly:5690_3", "bddk:10001")
        rate_key = "evds:TP.KTF12"
        assert f"{stock_key}::value" in joined.columns
        assert f"{rate_key}::value" in joined.columns
        assert set(joined[f"{stock_key}::aggregation"].dropna()) == {"last"}
        assert set(joined[f"{rate_key}::aggregation"].dropna()) == {"avg"}
    finally:
        connection.close()


# =========================================================== coverage stays visible


def test_periods_covered_by_only_one_series_are_kept(connection) -> None:
    """An outer join: a month where only one side published still appears."""

    _prepare(
        connection,
        [
            staging_rows(
                STOCK,
                [(date(2026, 1, 31), "100.0"), (date(2026, 2, 28), "110.0")],
                digest="a",
            ),
            staging_rows(RATE, [(date(2026, 2, 6), "20.0")], digest="b"),
        ],
        ["stock_monthly", "rate_weekly"],
    )

    joined = join_on_period(connection, [STOCK, RATE], "monthly")

    assert len(joined) == 2
    january = joined[joined["period_start"] == date(2026, 1, 1)].iloc[0]
    assert float(january[f"{STOCK}::value"]) == 100.0
    assert january[f"{RATE}::value"] is None or pd.isna(january[f"{RATE}::value"])
    assert january[f"{RATE}::observations"] == 0
    assert january["absent_series"] == [RATE]
    assert bool(january["is_complete_period"]) is False
    assert january["contributing_series"] == [STOCK]

    february = joined[joined["period_start"] == date(2026, 2, 1)].iloc[0]
    assert bool(february["is_complete_period"]) is True


def test_quality_and_lineage_reach_the_joined_row(connection) -> None:
    _prepare(
        connection,
        [
            staging_rows(STOCK, [(date(2026, 1, 31), "100.0")], digest="a"),
            staging_rows(
                FLOW,
                [(date(2026, 1, 2), "10.0"), (date(2026, 1, 9), None)],
                digest="b",
            ),
        ],
        ["stock_monthly", "flow_weekly"],
    )

    row = join_on_period(connection, [STOCK, FLOW], "monthly").iloc[0]

    assert row[f"{FLOW}::quality_flag"] == "partial_period"
    assert row[f"{FLOW}::missing_observations"] == 1
    assert float(row[f"{FLOW}::value"]) == 10.0  # the gap was not read as a zero
    assert row[f"{STOCK}::artifact_sha256_list"] == ["a" * 64]
    assert row[f"{FLOW}::artifact_sha256_list"] == ["b" * 64]
    assert row[f"{STOCK}::vintage_id_list"] == [f"artifact:{'a' * 64}"]


def test_entities_get_their_own_columns(connection) -> None:
    add_synthetic_series(connection, SYNTHETIC_SERIES["stock_monthly"])
    materialize_fact_observation_snapshot(
        connection,
        pd.concat(
            [
                staging_rows(
                    STOCK,
                    [(date(2026, 1, 31), "100.0")],
                    entity_id="synthetic:sector",
                    digest="a",
                ),
                staging_rows(
                    STOCK,
                    [(date(2026, 1, 31), "40.0")],
                    entity_id="synthetic:one_bank",
                    digest="b",
                ),
            ],
            ignore_index=True,
        ),
    )

    joined = join_on_period(connection, [STOCK], "monthly")

    sector = column_key(STOCK, "synthetic:sector")
    bank = column_key(STOCK, "synthetic:one_bank")
    assert float(joined.iloc[0][f"{sector}::value"]) == 100.0
    assert float(joined.iloc[0][f"{bank}::value"]) == 40.0


# ==================================================================== refusals


def test_one_unsafe_series_refuses_the_whole_join(connection) -> None:
    """A comparison table quietly missing a column is worse than no table."""

    _prepare(
        connection,
        [staging_rows(STOCK, [(date(2026, 1, 31), "100.0")], digest="a")],
        ["stock_monthly", "ratio_weekly"],
    )

    with pytest.raises(GoldError) as excinfo:
        join_on_period(connection, [STOCK, "synthetic:ratio_weekly"], "monthly")
    assert excinfo.value.refusal.reason == "UNSUPPORTED_MEASURE_TYPE"


def test_duplicate_series_ids_are_refused(connection) -> None:
    with pytest.raises(GoldError) as excinfo:
        join_on_period(connection, [STOCK, STOCK], "monthly")
    assert excinfo.value.refusal.reason == "INVALID_ARGUMENT"


def test_an_empty_series_list_is_refused(connection) -> None:
    with pytest.raises(GoldError) as excinfo:
        join_on_period(connection, [], "monthly")
    assert excinfo.value.refusal.reason == "INVALID_ARGUMENT"
