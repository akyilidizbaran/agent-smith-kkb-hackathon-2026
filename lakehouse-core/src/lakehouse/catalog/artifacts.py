"""Repository for registering immutable RAW artifact metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import duckdb

from ..contracts.models import FetchedAsset


def _as_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass
class ArtifactRepository:
    """Register FetchedAsset metadata while preserving artifact identity fields."""

    connection: duckdb.DuckDBPyConnection

    def register(self, asset: FetchedAsset, *, seen_at: datetime | None = None) -> bool:
        """Register an asset and return whether a new artifact row was inserted."""

        seen = _as_utc(seen_at or datetime.now(timezone.utc), "seen_at")
        existing = self.connection.execute(
            """
            SELECT source_id, dataset_id, locator, media_type, byte_size,
                   http_status, raw_path
            FROM meta.artifact
            WHERE artifact_sha256 = ?
            """,
            [asset.artifact_sha256],
        ).fetchone()

        if existing is not None:
            expected = (
                asset.source_id,
                asset.dataset_id,
                asset.locator,
                asset.media_type,
                asset.byte_size,
                asset.http_status,
                str(asset.raw_path),
            )
            if existing != expected:
                raise ValueError(
                    "artifact_sha256 already exists with different immutable metadata"
                )
            self.connection.execute(
                "UPDATE meta.artifact SET last_seen_at = ? WHERE artifact_sha256 = ?",
                [seen, asset.artifact_sha256],
            )
            return False

        self.connection.execute(
            """
            INSERT INTO meta.artifact (
                artifact_sha256, source_id, dataset_id, locator, media_type,
                byte_size, http_status, fetched_at, raw_path,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                asset.artifact_sha256,
                asset.source_id,
                asset.dataset_id,
                asset.locator,
                asset.media_type,
                asset.byte_size,
                asset.http_status,
                asset.fetched_at,
                str(asset.raw_path),
                seen,
                seen,
            ],
        )
        return True


__all__ = ["ArtifactRepository"]
