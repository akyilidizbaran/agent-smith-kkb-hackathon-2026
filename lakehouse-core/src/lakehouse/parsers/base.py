"""Parser boundary: local RAW artifact to parsed batch, without network access."""

from __future__ import annotations

from typing import Protocol

from ..contracts.models import FetchedAsset, ParsedBatch


class BaseParser(Protocol):
    """Structural contract for parsers that operate only on persisted RAW files."""

    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        """Read one RAW artifact and return a provenance-preserving parsed batch."""
        ...


__all__ = ["BaseParser"]
