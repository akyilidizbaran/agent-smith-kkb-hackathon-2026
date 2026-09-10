from datetime import date
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.lakehouse.contracts.models import ParsedBatch
from src.lakehouse.storage.parquet import (
    ParquetConflictError,
    ParquetIdentity,
    ParquetStorage,
    identity_for,
    read_identity,
    schema_version_key,
)
from src.lakehouse.storage.raw import sha256_bytes


def _batch() -> ParsedBatch:
    return ParsedBatch(
        source_id="fake_source",
        dataset_id="fake_dataset",
        artifact_sha256=sha256_bytes(b"parquet-fixture"),
        schema_version="fixture-v1",
        dataframe=pd.DataFrame(
            {
                "observation_date": [date(2026, 1, 31), date(2026, 2, 28)],
                "value": pd.Series([10.5, None], dtype="float64"),
                "label": pd.Series(["first", "second"], dtype="string"),
            }
        ),
    )


def test_parquet_path_is_deterministic_and_round_trip_preserves_types(tmp_path: Path) -> None:
    storage = ParquetStorage(tmp_path / "data/bronze")
    batch = _batch()

    path = storage.write(batch)
    round_tripped = storage.read(path)

    assert path == storage.path_for(batch)
    assert path == (
        tmp_path
        / "data/bronze/source_id=fake_source/dataset_id=fake_dataset/"
        f"schema_version_sha256={schema_version_key(batch.schema_version)}/"
        f"artifact_sha256={batch.artifact_sha256}.parquet"
    )
    assert read_identity(path) == identity_for(batch)
    assert list(round_tripped["observation_date"]) == [date(2026, 1, 31), date(2026, 2, 28)]
    assert round_tripped["value"].dtype == "float64"
    assert round_tripped["value"].tolist()[0] == 10.5
    assert pd.isna(round_tripped["value"].tolist()[1])
    assert round_tripped["label"].tolist() == ["first", "second"]


def test_schema_version_changes_representation_identity(tmp_path: Path) -> None:
    storage = ParquetStorage(tmp_path / "data/bronze")
    first = _batch()
    second = replace(first, schema_version="fixture-v2")

    first_path = storage.write(first)
    second_path = storage.write(second)

    assert first_path != second_path
    assert read_identity(first_path) == identity_for(first)
    assert read_identity(second_path) == identity_for(second)
    assert len(list((tmp_path / "data/bronze").rglob("*.parquet"))) == 2


def test_unsafe_schema_version_is_hashed_before_path_generation(tmp_path: Path) -> None:
    storage = ParquetStorage(tmp_path / "data/bronze")
    batch = _batch()
    unsafe = replace(batch, schema_version="../v1/../../unsafe")

    path = storage.path_for(unsafe)

    assert path.parent.name == f"schema_version_sha256={schema_version_key(unsafe.schema_version)}"
    assert ".." not in path.parent.name
    assert path == storage.path_for(unsafe)


def test_retry_reuses_path_and_different_output_conflicts(tmp_path: Path) -> None:
    storage = ParquetStorage(tmp_path / "data/bronze")
    batch = _batch()

    first_path = storage.write(batch)
    retry_path = storage.write(batch)
    assert retry_path == first_path
    assert len(list((tmp_path / "data/bronze").rglob("*.parquet"))) == 1

    changed = ParsedBatch(
        source_id=batch.source_id,
        dataset_id=batch.dataset_id,
        artifact_sha256=batch.artifact_sha256,
        schema_version=batch.schema_version,
        dataframe=batch.dataframe.assign(value=[99.0, 100.0]),
    )
    with pytest.raises(ParquetConflictError):
        storage.write(changed, overwrite=True)
    assert storage.read(first_path)["value"].tolist()[0] == 10.5


def test_generic_frame_writer_supports_the_silver_identity_layout(tmp_path: Path) -> None:
    storage = ParquetStorage(tmp_path / "data/silver/fact_observation")
    identity = ParquetIdentity(
        source_id="demo_energy",
        dataset_id="demo_energy_load",
        artifact_sha256=sha256_bytes(b"silver-fixture"),
        schema_version="demo_energy.v1",
    )
    frame = pd.DataFrame(
        {
            "series_id": ["demo_energy:load"],
            "observation_date": [date(2026, 1, 1)],
            "value": [42.5],
        }
    )

    first = storage.write_frame(frame, identity=identity)
    second = storage.write_frame(frame, identity=identity)

    assert first == second == storage.path_for_identity(identity)
    assert storage.read(first).to_dict(orient="records") == frame.to_dict(orient="records")
    assert read_identity(first) == identity

    with pytest.raises(ParquetConflictError):
        storage.write_frame(
            frame.assign(value=[99.0]),
            identity=identity,
            overwrite=True,
        )
