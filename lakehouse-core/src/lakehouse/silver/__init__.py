"""Generic Silver V1 foundation."""

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
    "artifact_vintage_id",
    "materialize_fact_observation_snapshot",
    "prepare_staging_frame",
    "silver_identity_for",
    "stage_ingestion_result",
]
