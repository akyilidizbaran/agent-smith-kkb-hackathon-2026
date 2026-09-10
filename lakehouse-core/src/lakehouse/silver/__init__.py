"""Generic Silver V1 foundation."""

from .coverage import COVERAGE_SOURCE_RELATION, CoverageError, refresh_series_coverage
from .foundation import (
    FACT_OBSERVATION_COLUMNS,
    QUALITY_FLAGS,
    SILVER_SCHEMA_VERSION,
    SILVER_STAGING_COLUMNS,
    SilverValidationError,
    artifact_vintage_id,
    materialize_fact_observation_snapshot,
    prepare_staging_frame,
    silver_identity_for,
)
from .pipeline import SilverAdapter, stage_ingestion_result

__all__ = [
    "FACT_OBSERVATION_COLUMNS",
    "QUALITY_FLAGS",
    "SILVER_SCHEMA_VERSION",
    "SILVER_STAGING_COLUMNS",
    "SilverValidationError",
    "SilverAdapter",
    "COVERAGE_SOURCE_RELATION",
    "CoverageError",
    "refresh_series_coverage",
    "artifact_vintage_id",
    "materialize_fact_observation_snapshot",
    "prepare_staging_frame",
    "silver_identity_for",
    "stage_ingestion_result",
]
