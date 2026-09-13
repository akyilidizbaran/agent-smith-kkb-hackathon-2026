"""Canonical scalar types shared by future normalized contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import TypeAlias


CanonicalDate: TypeAlias = date
"""Observation dates use Python ``date`` without a timezone."""

CanonicalTimestamp: TypeAlias = datetime
"""Operational timestamps are timezone-aware and normalized to UTC."""

CanonicalValue: TypeAlias = float | None
"""Measured values use ``float`` and preserve source nulls as ``None``."""
