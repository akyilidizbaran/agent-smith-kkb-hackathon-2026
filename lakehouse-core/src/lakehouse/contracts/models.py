"""Small immutable models shared between connectors, storage, and parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .identifiers import (
    validate_dataset_id,
    validate_sha256,
    validate_source_id,
)


def _as_utc(value: datetime, field_name: str) -> datetime:
    """Require a timezone-aware timestamp and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class FetchSpec:
    """Describe a source retrieval request without source-specific behavior."""

    source_id: str
    dataset_id: str
    locator: str
    start_date: date | None = None
    end_date: date | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    headers_ref: str | None = None
    timeout: float = 30.0
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        validate_source_id(self.source_id)
        validate_dataset_id(self.dataset_id)
        if not self.locator.strip():
            raise ValueError("locator must not be empty")
        if self.timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        object.__setattr__(self, "requested_at", _as_utc(self.requested_at, "requested_at"))


@dataclass(frozen=True)
class FetchedAsset:
    """Metadata for exact source bytes persisted as an immutable RAW artifact."""

    source_id: str
    dataset_id: str
    locator: str
    media_type: str
    byte_size: int
    fetched_at: datetime
    artifact_sha256: str
    raw_path: Path
    http_status: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_source_id(self.source_id)
        validate_dataset_id(self.dataset_id)
        validate_sha256(self.artifact_sha256)
        if not self.locator.strip():
            raise ValueError("locator must not be empty")
        if not self.media_type.strip():
            raise ValueError("media_type must not be empty")
        if self.byte_size < 0:
            raise ValueError("byte_size must not be negative")
        if self.http_status is not None and not 200 <= self.http_status < 300:
            raise ValueError("failed HTTP responses cannot be successful FetchedAsset values")
        object.__setattr__(self, "fetched_at", _as_utc(self.fetched_at, "fetched_at"))


@dataclass(frozen=True)
class ParsedBatch:
    """Parser output with provenance retained from the originating RAW artifact."""

    source_id: str
    dataset_id: str
    artifact_sha256: str
    schema_version: str
    dataframe: pd.DataFrame
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        validate_source_id(self.source_id)
        validate_dataset_id(self.dataset_id)
        validate_sha256(self.artifact_sha256)
        if not self.schema_version.strip():
            raise ValueError("schema_version must not be empty")
        if not isinstance(self.dataframe, pd.DataFrame):
            raise TypeError("dataframe must be a pandas DataFrame")


__all__ = ["FetchedAsset", "FetchSpec", "ParsedBatch"]
