"""Minimal source-to-Bronze ingestion orchestration."""

from .pipeline import IngestionPipeline, IngestionResult

__all__ = ["IngestionPipeline", "IngestionResult"]
