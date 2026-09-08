"""Compatibility exports for the standardized ``src.lakehouse`` namespace."""

from src.lakehouse.connectors.base import BaseConnector
from src.lakehouse.contracts.models import FetchedAsset, FetchSpec

__all__ = ["BaseConnector", "FetchedAsset", "FetchSpec"]
