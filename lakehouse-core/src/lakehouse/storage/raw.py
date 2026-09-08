"""Content-addressed, immutable RAW artifact storage."""

from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..contracts.identifiers import validate_dataset_id, validate_sha256, validate_source_id
from ..contracts.models import FetchedAsset
from ..errors import ErrorPayload, LakehouseError


def sha256_bytes(content: bytes) -> str:
    """Return the deterministic lowercase SHA-256 digest for ``content``."""

    return hashlib.sha256(content).hexdigest()


def raw_artifact_path(
    raw_root: Path,
    source_id: str,
    fetch_date: date,
    artifact_sha256: str,
    extension: str,
) -> Path:
    """Build ``data/raw/{source_id}/{fetch_date}/{sha256}.{ext}``."""

    validate_source_id(source_id)
    validate_sha256(artifact_sha256)
    normalized_extension = extension.removeprefix(".").lower()
    if not normalized_extension.isalnum():
        raise ValueError("extension must contain only letters and digits")

    return (
        raw_root
        / source_id
        / fetch_date.strftime("%Y-%m-%d")
        / f"{artifact_sha256}.{normalized_extension}"
    )


class RawStorage:
    """Persist exact bytes once and return their artifact metadata."""

    def __init__(self, root: Path = Path("data/raw")) -> None:
        self.root = root

    def store(
        self,
        *,
        source_id: str,
        dataset_id: str,
        locator: str,
        content: bytes,
        media_type: str,
        fetched_at: datetime,
        extension: str,
        http_status: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FetchedAsset:
        """Write exact source bytes atomically, reusing an existing identical artifact."""

        validate_source_id(source_id)
        validate_dataset_id(dataset_id)
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")
        if not locator.strip():
            raise ValueError("locator must not be empty")
        if not media_type.strip():
            raise ValueError("media_type must not be empty")
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        fetched_at = fetched_at.astimezone(timezone.utc)
        if http_status is not None and not 200 <= http_status < 300:
            retryable = http_status in {408, 429} or http_status >= 500
            raise LakehouseError(
                ErrorPayload(
                    error_code="HTTP_ERROR",
                    message=f"HTTP response {http_status} cannot be stored as a RAW artifact",
                    source_id=source_id,
                    dataset_id=dataset_id,
                    retryable=retryable,
                )
            )

        digest = sha256_bytes(content)
        path = self._find_existing(source_id, digest, content)
        if path is None:
            path = raw_artifact_path(
                self.root,
                source_id,
                fetched_at.date(),
                digest,
                extension,
            )
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            if path.read_bytes() != content:
                raise ValueError("existing RAW path contains different bytes for the same SHA-256")
        else:
            temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                temporary_path.write_bytes(content)
                os.replace(temporary_path, path)
            finally:
                temporary_path.unlink(missing_ok=True)

        return FetchedAsset(
            source_id=source_id,
            dataset_id=dataset_id,
            locator=locator,
            media_type=media_type,
            byte_size=len(content),
            fetched_at=fetched_at,
            artifact_sha256=digest,
            raw_path=path,
            http_status=http_status,
            metadata=metadata or {},
        )

    def _find_existing(self, source_id: str, digest: str, content: bytes) -> Path | None:
        """Find an identical artifact regardless of the date of a later fetch."""

        source_root = self.root / source_id
        if not source_root.exists():
            return None

        for candidate in sorted(source_root.rglob(f"{digest}.*")):
            if candidate.is_file() and candidate.read_bytes() == content:
                return candidate
        return None


__all__ = ["RawStorage", "raw_artifact_path", "sha256_bytes"]
