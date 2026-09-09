"""Repository for registering immutable RAW artifact metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import duckdb

from ..contracts.models import FetchedAsset


_SENSITIVE_METADATA_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "x-api-key",
        "token",
        "access_token",
        "password",
        "secret",
        "cookie",
    }
)


def _sanitize_metadata(value: Any) -> Any:
    """Remove credential-shaped keys while preserving JSON-compatible values."""

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("request metadata keys must be strings")
            if key.strip().casefold() in _SENSITIVE_METADATA_KEYS:
                continue
            sanitized[key] = _sanitize_metadata(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("request metadata must contain JSON-compatible values")


def _request_metadata_json(metadata: dict[str, Any]) -> str:
    """Serialize sanitized request metadata canonically without string fallbacks."""

    return json.dumps(
        _sanitize_metadata(metadata),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _sanitize_locator(locator: str) -> str:
    """Remove credential-shaped query parameters from a locator."""

    parts = urlsplit(locator)
    if not parts.query:
        return locator
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.strip().casefold() not in _SENSITIVE_METADATA_KEYS
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _request_context_json(locator: str, metadata: dict[str, Any]) -> str:
    """Serialize the complete sanitized request context deterministically."""

    return json.dumps(
        {"locator": _sanitize_locator(locator), "metadata": _sanitize_metadata(metadata)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _request_fingerprint(request_context_json: str) -> str:
    """Hash canonical request context without including any secret values."""

    return hashlib.sha256(request_context_json.encode("utf-8")).hexdigest()


def _as_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass
class ArtifactRepository:
    """Register artifacts and their separate request-level provenance."""

    connection: duckdb.DuckDBPyConnection

    def register(self, asset: FetchedAsset, *, seen_at: datetime | None = None) -> bool:
        """Register an asset and return whether a new artifact row was inserted."""

        seen = _as_utc(seen_at or datetime.now(timezone.utc), "seen_at")
        safe_locator = _sanitize_locator(asset.locator)
        request_metadata_json = _request_metadata_json(asset.metadata)
        request_context_json = _request_context_json(asset.locator, asset.metadata)
        request_fingerprint = _request_fingerprint(request_context_json)
        existing = self.connection.execute(
            """
            SELECT source_id, dataset_id, media_type, byte_size,
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
            artifact_inserted = False
        else:
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
                    safe_locator,
                    asset.media_type,
                    asset.byte_size,
                    asset.http_status,
                    asset.fetched_at,
                    str(asset.raw_path),
                    seen,
                    seen,
                ],
            )
            artifact_inserted = True
        self._register_request(
            asset.artifact_sha256,
            request_fingerprint,
            safe_locator,
            request_metadata_json,
            seen,
        )
        return artifact_inserted

    def _register_request(
        self,
        artifact_sha256: str,
        request_fingerprint: str,
        locator: str,
        request_metadata_json: str,
        seen: datetime,
    ) -> None:
        """Insert request provenance or update only its last-seen timestamp."""

        existing = self.connection.execute(
            """
            SELECT locator, request_metadata_json
            FROM meta.artifact_request
            WHERE artifact_sha256 = ? AND request_fingerprint = ?
            """,
            [artifact_sha256, request_fingerprint],
        ).fetchone()
        if existing is None:
            self.connection.execute(
                """
                INSERT INTO meta.artifact_request (
                    artifact_sha256, request_fingerprint, locator, request_metadata_json,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    artifact_sha256,
                    request_fingerprint,
                    locator,
                    request_metadata_json,
                    seen,
                    seen,
                ],
            )
            return
        if existing != (locator, request_metadata_json):
            raise ValueError(
                "request_fingerprint already exists with different request metadata"
            )
        self.connection.execute(
            """
            UPDATE meta.artifact_request
            SET last_seen_at = ?
            WHERE artifact_sha256 = ? AND request_fingerprint = ?
            """,
            [seen, artifact_sha256, request_fingerprint],
        )


__all__ = ["ArtifactRepository"]
