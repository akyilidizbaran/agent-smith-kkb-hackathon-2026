"""Small shared error payload contract without an exception hierarchy."""

from __future__ import annotations

from dataclasses import dataclass


ERROR_CODES = frozenset(
    {
        "SOURCE_UNAVAILABLE",
        "FETCH_TIMEOUT",
        "HTTP_ERROR",
        "UNSUPPORTED_FORMAT",
        "PARSE_FAILED",
        "SCHEMA_MISMATCH",
        "EMPTY_DATASET",
        "OBSERVATION_COUNT_MISMATCH",
        "QUALITY_FAILED",
    }
)


@dataclass(frozen=True)
class ErrorPayload:
    """Minimum machine-readable error data shared across layers."""

    error_code: str
    message: str
    source_id: str
    dataset_id: str
    retryable: bool

    def __post_init__(self) -> None:
        if self.error_code not in ERROR_CODES:
            raise ValueError(f"unsupported error_code: {self.error_code}")


class LakehouseError(Exception):
    """Single operational exception carrying the shared error payload."""

    def __init__(self, payload: ErrorPayload) -> None:
        self.payload = payload
        super().__init__(payload.message)


__all__ = ["ERROR_CODES", "ErrorPayload", "LakehouseError"]
