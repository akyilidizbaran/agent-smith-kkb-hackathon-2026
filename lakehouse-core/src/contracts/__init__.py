"""Compatibility exports for the standardized ``src.lakehouse`` namespace."""

from src.lakehouse.contracts.models import FetchedAsset, FetchSpec, ParsedBatch

__all__ = ["FetchedAsset", "FetchSpec", "ParsedBatch"]
