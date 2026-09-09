from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.contracts.models import FetchedAsset
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.storage.raw import sha256_bytes


def _asset(
    raw_path: Path,
    fetched_at: datetime,
    *,
    locator: str = "fixture://sample.csv",
) -> FetchedAsset:
    return FetchedAsset(
        source_id="fake_source",
        dataset_id="fake_dataset",
        locator=locator,
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
    request_row = connection.execute(
        """
        SELECT epoch_ms(first_seen_at), epoch_ms(last_seen_at), count(*) OVER ()
        FROM meta.artifact_request
        WHERE artifact_sha256 = ?
        """,
        [asset.artifact_sha256],
    ).fetchone()
    assert request_row == (
        int(first_seen.timestamp() * 1000),
        int(last_seen.timestamp() * 1000),
        1,
    )
    connection.close()


def test_register_persists_canonical_metadata_and_redacts_nested_secrets(
    tmp_path: Path,
) -> None:
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    repository = ArtifactRepository(connection)
    asset = replace(
        _asset(
            tmp_path / "data/raw/fake_source/2026-09-08/data.csv",
            datetime(2026, 9, 8, tzinfo=timezone.utc),
        ),
        metadata={
            "requested_currency": "TL",
            "nested": {"period": "2026-09", "api_key": "not-a-secret"},
            "authorization": "not-a-secret",
        },
    )

    assert repository.register(asset) is True
    stored = connection.execute(
        """
        SELECT locator, request_metadata_json, request_fingerprint
        FROM meta.artifact_request
        WHERE artifact_sha256 = ?
        """,
        [asset.artifact_sha256],
    ).fetchone()
    assert stored is not None
    assert stored[0] == asset.locator
    assert stored[1] == '{"nested":{"period":"2026-09"},"requested_currency":"TL"}'
    request_context = (
        '{"locator":"fixture://sample.csv","metadata":'
        '{"nested":{"period":"2026-09"},"requested_currency":"TL"}}'
    )
    assert stored[2] == hashlib.sha256(request_context.encode("utf-8")).hexdigest()
    assert json.loads(stored[1]) == {
        "nested": {"period": "2026-09"},
        "requested_currency": "TL",
    }
    connection.close()


def test_register_accepts_same_sha_with_different_request_metadata(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    repository = ArtifactRepository(connection)
    asset = _asset(
        tmp_path / "data/raw/fake_source/2026-09-08/data.csv",
        datetime(2026, 9, 8, tzinfo=timezone.utc),
    )
    first = replace(asset, metadata={"period": "2026-09"})
    second = replace(asset, metadata={"period": "2026-10"})

    assert repository.register(first) is True
    assert repository.register(second) is False
    assert connection.execute("SELECT count(*) FROM meta.artifact").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM meta.artifact_request").fetchone() == (2,)
    connection.close()


def test_secret_only_metadata_difference_reuses_request_fingerprint(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    repository = ArtifactRepository(connection)
    asset = _asset(
        tmp_path / "data/raw/fake_source/2026-09-08/data.csv",
        datetime(2026, 9, 8, tzinfo=timezone.utc),
    )
    first = replace(
        asset, metadata={"period": "2026-09", "api_key": "first"}
    )
    second = replace(
        asset, metadata={"period": "2026-09", "api_key": "second"}
    )

    assert repository.register(first) is True
    assert repository.register(second) is False
    rows = connection.execute(
        "SELECT locator, request_metadata_json, request_fingerprint "
        "FROM meta.artifact_request"
    ).fetchall()
    assert rows == [
        (
            "fixture://sample.csv",
            '{"period":"2026-09"}',
            hashlib.sha256(
                b'{"locator":"fixture://sample.csv",'
                b'"metadata":{"period":"2026-09"}}'
            ).hexdigest(),
        )
    ]
    assert "first" not in str(rows[0]) and "second" not in str(rows[0])
    connection.close()


def test_same_sha_with_different_locator_creates_two_request_rows(
    tmp_path: Path,
) -> None:
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    repository = ArtifactRepository(connection)
    fetched_at = datetime(2026, 9, 8, tzinfo=timezone.utc)
    first = replace(
        _asset(
            tmp_path / "data/raw/fake_source/2026-09-08/data.csv",
            fetched_at,
            locator="https://example.test/data?startDate=01-01-2026&endDate=05-01-2026",
        ),
        metadata={"series": "TP.KTF12"},
    )
    second = replace(
        first,
        locator="https://example.test/data?startDate=01-01-2026&endDate=06-01-2026",
    )

    assert repository.register(first) is True
    assert repository.register(second) is False
    assert connection.execute("SELECT count(*) FROM meta.artifact").fetchone() == (1,)
    rows = connection.execute(
        """
        SELECT locator, request_fingerprint
        FROM meta.artifact_request
        WHERE artifact_sha256 = ?
        ORDER BY locator
        """,
        [first.artifact_sha256],
    ).fetchall()
    assert [row[0] for row in rows] == [first.locator, second.locator]
    assert len({row[1] for row in rows}) == 2
    connection.close()


def test_locator_query_secret_is_not_persisted_or_fingerprinted(
    tmp_path: Path,
) -> None:
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    repository = ArtifactRepository(connection)
    asset = _asset(
        tmp_path / "data/raw/fake_source/2026-09-08/data.csv",
        datetime(2026, 9, 8, tzinfo=timezone.utc),
        locator="https://example.test/data?api_key=not-a-secret&series=TP.KTF12",
    )

    assert repository.register(asset) is True
    row = connection.execute(
        "SELECT locator, request_metadata_json FROM meta.artifact_request"
    ).fetchone()
    assert row == (
        "https://example.test/data?series=TP.KTF12",
        "{}",
    )
    assert "not-a-secret" not in str(row)
    connection.close()
