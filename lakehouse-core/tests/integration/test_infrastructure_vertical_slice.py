from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.contracts.models import ParsedBatch
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.db.connection import connect_untrusted
from src.lakehouse.query.executor import QueryExecutor, TrustedConnectionError
from src.lakehouse.security.sql_guard import SqlGuardError
from src.lakehouse.storage.parquet import ParquetStorage, read_identity
from src.lakehouse.storage.raw import RawStorage, sha256_bytes


def test_offline_infrastructure_vertical_slice(tmp_path: Path) -> None:
    raw_storage = RawStorage(tmp_path / "data/raw")
    asset = raw_storage.store(
        source_id="fake_source",
        dataset_id="fake_dataset",
        locator="fixture://sample.csv",
        content=b"date,value\n2026-01-31,10.5\n2026-02-28,11.0\n",
        media_type="text/csv",
        fetched_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
        extension="csv",
        http_status=200,
    )
    batch = ParsedBatch(
        source_id=asset.source_id,
        dataset_id=asset.dataset_id,
        artifact_sha256=asset.artifact_sha256,
        schema_version="fixture-v1",
        dataframe=pd.DataFrame(
            {
                "observation_date": [date(2026, 1, 31), date(2026, 2, 28)],
                "value": [10.5, 11.0],
            }
        ),
    )
    parquet_path = ParquetStorage(tmp_path / "data/bronze").write(batch)

    # --- Trusted / internal operations: bootstrap, register, persist Bronze table ---
    db_path = tmp_path / "data/lakehouse.duckdb"
    connection = bootstrap_database(db_path)
    repository = ArtifactRepository(connection)

    assert repository.register(asset, seen_at=datetime(2026, 9, 8, tzinfo=timezone.utc)) is True
    assert repository.register(asset, seen_at=datetime(2026, 9, 9, tzinfo=timezone.utc)) is False

    assert read_identity(parquet_path).schema_version == batch.schema_version
    parquet_storage = ParquetStorage(tmp_path / "data/bronze")
    parquet_storage.register_local_parquet(connection, parquet_path, "fixture_relation")
    # Internal, trusted persistence so the read-only agent connection can query it.
    connection.execute(
        "CREATE TABLE bronze.fixture AS "
        "SELECT * FROM fixture_relation ORDER BY observation_date"
    )
    assert connection.execute("SELECT count(*) FROM meta.artifact").fetchone() == (1,)

    # The trust boundary is enforced in code: agent SQL must NOT run on a
    # trusted/writable connection.
    with pytest.raises(TrustedConnectionError):
        QueryExecutor(connection)
    connection.close()

    # --- Untrusted / agent path: read-only, hardened, guarded, bounded SQL ---
    untrusted = connect_untrusted(db_path)
    executor = QueryExecutor(untrusted)

    result = executor.execute(
        "SELECT observation_date, value FROM bronze.fixture ORDER BY observation_date"
    )
    assert result.columns == ["observation_date", "value"]
    assert result.rows == [(date(2026, 1, 31), 10.5), (date(2026, 2, 28), 11.0)]
    assert result.row_count == 2
    assert result.truncated is False

    limited = executor.execute(
        "SELECT observation_date, value FROM bronze.fixture ORDER BY observation_date",
        max_rows=1,
    )
    assert limited.rows == [(date(2026, 1, 31), 10.5)]
    assert limited.row_count == 1
    assert limited.truncated is True

    assert executor.execute("SELECT count(*) FROM meta.artifact").rows == [(1,)]
    assert asset.artifact_sha256 == batch.artifact_sha256 == sha256_bytes(
        asset.raw_path.read_bytes()
    )

    # Guard denials on the agent connection.
    with pytest.raises(SqlGuardError):
        executor.execute(
            "INSERT INTO meta.artifact VALUES (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)"
        )
    with pytest.raises(SqlGuardError):
        executor.execute("SELECT * FROM read_parquet('outside.parquet')")
    with pytest.raises(SqlGuardError):
        executor.execute("SELECT * FROM query('SELECT 1')")
    with pytest.raises(SqlGuardError):
        executor.execute("DROP TABLE meta.artifact")

    # Even bypassing the guard, external access is disabled at the runtime layer.
    with pytest.raises(Exception):
        untrusted.execute("SELECT * FROM read_parquet(?)", [str(parquet_path)]).fetchall()
    untrusted.close()
