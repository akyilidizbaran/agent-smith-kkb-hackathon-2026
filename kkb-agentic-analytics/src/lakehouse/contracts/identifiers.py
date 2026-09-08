"""Validation helpers for stable lakehouse identifiers."""

from __future__ import annotations

import re
from uuid import UUID, uuid4


_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_SERIES_ID_RE = re.compile(
    r"^(?P<source>[a-z][a-z0-9]*(?:_[a-z0-9]+)*)"
    r"(?:[:.]([A-Za-z0-9][A-Za-z0-9_.-]*))$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_slug(value: str, field_name: str) -> str:
    if _SLUG_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be lowercase snake_case and start with a letter")
    return value


def validate_source_id(source_id: str) -> str:
    """Validate and return a stable lowercase snake_case source identifier."""

    return _validate_slug(source_id, "source_id")


def validate_dataset_id(dataset_id: str) -> str:
    """Validate and return a stable lowercase snake_case dataset identifier."""

    return _validate_slug(dataset_id, "dataset_id")


def validate_series_id(series_id: str, source_id: str | None = None) -> str:
    """Validate a namespaced series identifier such as ``evds:TP.KTF12``."""

    match = _SERIES_ID_RE.fullmatch(series_id)
    if match is None:
        raise ValueError(
            "series_id must be '<source_id>:<native series key>' or the legacy dotted form"
        )

    namespace = match.group("source")
    if source_id is not None and namespace != validate_source_id(source_id):
        raise ValueError("series_id namespace must match source_id")
    return series_id


def validate_sha256(digest: str) -> str:
    """Validate and return a lowercase 64-character SHA-256 digest."""

    if _SHA256_RE.fullmatch(digest) is None:
        raise ValueError("artifact_sha256 must be a lowercase 64-character hexadecimal digest")
    return digest


def validate_run_id(run_id: str | UUID) -> str:
    """Validate a UUID run identifier and return its canonical string form."""

    try:
        return str(UUID(str(run_id)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("run_id must be a valid UUID") from exc


def new_run_id() -> str:
    """Create a new UUID run identifier."""

    return str(uuid4())


__all__ = [
    "new_run_id",
    "validate_dataset_id",
    "validate_run_id",
    "validate_series_id",
    "validate_sha256",
    "validate_source_id",
]
