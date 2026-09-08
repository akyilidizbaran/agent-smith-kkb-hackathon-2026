from datetime import datetime, timezone
from pathlib import Path

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.contracts.models import FetchedAsset
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.storage.raw import sha256_bytes


def _asset(raw_path: Path, fetched_at: datetime) -> FetchedAsset:
    return FetchedAsset(
        source_id="fake_source",
        dataset_id="fake_dataset",
        locator="fixture://sample.csv",
        media_type="text/csv",
        byte_size=4,
        fetched_at=fetched_at,
        artifact_sha256=sha256_bytes(b"data"),
        raw_path=raw_path,
        http_status=200,
    )


def test_register_is_idempotent_and_tracks_first_and_last_seen(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    repository = ArtifactRepository(connection)
    fetched_at = datetime(2026, 9, 8, 10, tzinfo=timezone.utc)
    first_seen = datetime(2026, 9, 8, 11, tzinfo=timezone.utc)
    last_seen = datetime(2026, 9, 9, 11, tzinfo=timezone.utc)
    asset = _asset(tmp_path / "data/raw/fake_source/2026-09-08/data.csv", fetched_at)

    assert repository.register(asset, seen_at=first_seen) is True
    assert repository.register(asset, seen_at=last_seen) is False

    row = connection.execute(
        """
        SELECT source_id, dataset_id, epoch_ms(fetched_at), raw_path,
               epoch_ms(first_seen_at), epoch_ms(last_seen_at), count(*) OVER ()
        FROM meta.artifact
        WHERE artifact_sha256 = ?
        """,
        [asset.artifact_sha256],
    ).fetchone()
    assert row is not None
    assert row[0:2] == ("fake_source", "fake_dataset")
    assert row[2] == int(fetched_at.timestamp() * 1000)
    assert row[3] == str(asset.raw_path)
    assert row[4] == int(first_seen.timestamp() * 1000)
    assert row[5] == int(last_seen.timestamp() * 1000)
    assert row[6] == 1
    connection.close()
