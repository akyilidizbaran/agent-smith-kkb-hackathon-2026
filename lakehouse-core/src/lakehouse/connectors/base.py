"""Connector boundary for retrieving source data."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts.models import FetchedAsset, FetchSpec


class BaseConnector(ABC):
    """Minimal interface implemented by every external source connector."""

    @abstractmethod
    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        """Fetch source bytes, persist exact RAW artifacts, and return their metadata."""
        raise NotImplementedError


__all__ = ["BaseConnector", "FetchedAsset", "FetchSpec"]
