"""Offline generic Silver foundation vertical slice."""

from datetime import date, datetime, timezone

import pandas as pd

from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.silver.foundation import materialize_fact_observation
from src.lakehouse.storage.parquet import ParquetIdentity, ParquetStorage


def test_generic_staging_to_silver_parquet_and_duckdb(tmp_path) -> None:
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    staging = pd.DataFrame(
        {
            "series_id": ["evds:TP.KTF12"],
            "entity_id": [None],
            "observation_date": [date(2026, 1, 2)],
            "period_start": [None],
            "period_end": [None],
            "value_raw": ["18.61"],
            "source_id": ["evds"],
            "dataset_id": ["evds_housing_interest"],
            "artifact_sha256": ["a" * 64],
            "fetched_at": [datetime(2026, 9, 10, tzinfo=timezone.utc)],
            "schema_version": ["evds_observations.v1"],
            "vintage_id": [None],
            "run_id": [None],
        }
    )

    try:
        result = materialize_fact_observation(connection, staging)
        silver_path = ParquetStorage(tmp_path / "data/silver/fact_observation").write_frame(
            result,
            identity=ParquetIdentity(
                source_id="evds",
                dataset_id="evds_housing_interest",
                artifact_sha256="a" * 64,
                schema_version="evds_observations.v1",
            ),
        )

        row = connection.execute(
            "SELECT series_id, observation_date, value, frequency, unit, measure_type, "
            "quality_flag, entity_id FROM silver.fact_observation"
        ).fetchone()

        assert silver_path.is_file()
        assert isinstance(result.loc[0, "observation_date"], date)
        assert isinstance(ParquetStorage.read(silver_path).loc[0, "observation_date"], date)
        assert row == (
            "evds:TP.KTF12",
            date(2026, 1, 2),
            18.61,
            "weekly",
            "pct",
            "rate",
            "ok",
            None,
        )
    finally:
        connection.close()
