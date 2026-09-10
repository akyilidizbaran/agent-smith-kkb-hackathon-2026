"""Minimal source-to-Bronze ingestion orchestration."""

from .observability import (
    RUN_STATUSES,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    RUN_STATUS_WARNING,
    IngestionWarning,
    RunLifecycleError,
    RunRepository,
    WarningIntegrityError,
)
from .pipeline import IngestionPipeline, IngestionResult

__all__ = [
    "RUN_STATUSES",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_RUNNING",
    "RUN_STATUS_SUCCESS",
    "RUN_STATUS_WARNING",
    "IngestionPipeline",
    "IngestionResult",
    "IngestionWarning",
    "RunLifecycleError",
    "RunRepository",
    "WarningIntegrityError",
]
