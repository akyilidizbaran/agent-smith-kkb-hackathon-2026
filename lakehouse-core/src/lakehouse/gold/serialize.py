"""Serialize a Gold frame for a caller in another process.

The agent layer does not import this package (its contract boundary), so an on-demand Gold
call crosses a process boundary: ``python -m lakehouse gold-run`` computes the frame and
writes it here as one JSON document. JSON rather than Parquet because the consumer may not
carry an Arrow runtime, and because Gold frames are small by construction -- they are
aggregated periods, not observations.

Every Python value the Gold functions emit has one representation:

- ``date`` -> ISO string, ``datetime`` -> ISO string with offset
- ``None`` / ``NaN`` -> ``null`` (a missing value is never a zero, in JSON either)
- ``list`` -> JSON array, element-wise converted
- ``bool`` / ``int`` / ``float`` / ``str`` -> themselves
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

GOLD_DOCUMENT_VERSION = "1.0"


def json_ready(value: Any) -> Any:
    """Convert one cell to a JSON-serializable value without changing its meaning."""

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if hasattr(value, "item") and not isinstance(value, str):  # numpy scalar
        return json_ready(value.item())
    if isinstance(value, (int, str)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def frame_to_document(frame: pd.DataFrame, *, function: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """One self-describing JSON document: what was called, and the resulting rows."""

    return {
        "gold_document_version": GOLD_DOCUMENT_VERSION,
        "function": function,
        "arguments": arguments,
        "columns": [str(column) for column in frame.columns],
        "rows": [[json_ready(cell) for cell in row] for row in frame.itertuples(index=False, name=None)],
    }


def write_document(document: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


__all__ = ["GOLD_DOCUMENT_VERSION", "frame_to_document", "json_ready", "write_document"]
