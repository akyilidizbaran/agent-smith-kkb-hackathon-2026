"""EVDS response parser: local RAW JSON to a long-format ``ParsedBatch``.

The response envelope below was captured from live EVDS3 responses on 2026-09-08::

    {
      "totalCount": 5,
      "items": [
        {"Tarih": "01-01-2021", "YEARWEEK": "2021-1",
         "TP_KTF12": "18.61", "UNIXTIME": {"$numberLong": "1609455600"}}
      ],
      "transposedItems": [...], "transposedColumns": [...],
      "seriesNames": {"TP_KTF12": "Housing Loans (TRY) (Flow, %)"},
      "frequencyConversion": {"TP.KTF12": true}
    }

Source behaviour this parser deliberately preserves instead of "fixing":

- ``Tarih`` is **not** a single stable format. Live captures show ``MM-DD-YYYY`` for daily and
  weekly frequencies and ``MM-YYYY`` for monthly. It is therefore kept verbatim as
  ``date_raw`` and never converted here. ``UNIXTIME`` is retained as the unambiguous field a
  later semantic layer should use to derive ``date_key``.
- Values arrive as **strings** whose decimal separator is chosen by the request. They are kept
  verbatim in ``value_raw``; no numeric casting happens in this layer.
- Missing observations arrive as JSON ``null`` and stay ``None``. They are never turned into 0.
- A series code's dots become underscores in the response column name
  (``TP.KFE.TR`` -> ``TP_KFE_TR``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ..contracts.models import FetchedAsset, ParsedBatch
from ..errors import ErrorPayload, LakehouseError


EVDS_SCHEMA_VERSION = "evds_observations.v1"
"""Schema version of the long-format frame produced by this parser."""

EVDS_OBSERVATION_LIMIT = 1000
"""Documented per-request observation cap; reaching it may mean silent truncation."""

DATE_FIELD = "Tarih"
UNIXTIME_FIELD = "UNIXTIME"
_NON_SERIES_FIELDS = frozenset({DATE_FIELD, UNIXTIME_FIELD, "YEARWEEK"})

COLUMNS = [
    "source_id",
    "dataset_id",
    "series_id",
    "series_column",
    "series_name",
    "date_raw",
    "unixtime",
    "value_raw",
    "artifact_sha256",
    "fetched_at",
    "locator",
]


def series_id_for_column(column: str, requested_series: list[str] | None) -> tuple[str, bool]:
    """Map a response column back to its native series code.

    Prefers an exact match against the codes the connector actually requested. Falls back to
    replacing underscores with dots, which is lossy for codes containing a real underscore;
    the caller records a warning in that case.
    """

    for code in requested_series or []:
        if code.replace(".", "_") == column:
            return code, True
    return column.replace("_", "."), False


def _unixtime_value(raw: Any) -> str | None:
    """Return the epoch-second string, unwrapping the ``{"$numberLong": "..."}`` form."""

    if raw is None:
        return None
    if isinstance(raw, dict):
        inner = raw.get("$numberLong")
        return None if inner is None else str(inner)
    return str(raw)


class EvdsParser:
    """Read one persisted EVDS JSON artifact and return a provenance-preserving batch."""

    def __init__(self, schema_version: str = EVDS_SCHEMA_VERSION) -> None:
        self._schema_version = schema_version

    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        """Read only ``asset.raw_path`` and flatten the response into one row per value."""

        document = self._load(asset)
        items = self._items(asset, document)
        warnings: list[str] = []

        requested_series = self._requested_series(asset)
        series_names = document.get("seriesNames") or {}
        self._check_counts(asset, document, items, warnings)

        rows: list[dict[str, Any]] = []
        unmapped: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise self._error(
                    asset,
                    "SCHEMA_MISMATCH",
                    f"EVDS item {index} is not a JSON object",
                )
            if DATE_FIELD not in item:
                raise self._error(
                    asset,
                    "SCHEMA_MISMATCH",
                    f"EVDS item {index} has no '{DATE_FIELD}' field",
                )

            date_raw = item[DATE_FIELD]
            unixtime = _unixtime_value(item.get(UNIXTIME_FIELD))
            value_columns = [key for key in item if key not in _NON_SERIES_FIELDS]
            if not value_columns:
                raise self._error(
                    asset,
                    "SCHEMA_MISMATCH",
                    f"EVDS item {index} carries no series value column",
                )

            for column in value_columns:
                series_id, exact = series_id_for_column(column, requested_series)
                if not exact:
                    unmapped.add(column)
                raw_value = item[column]
                rows.append(
                    {
                        "source_id": asset.source_id,
                        "dataset_id": asset.dataset_id,
                        "series_id": f"{asset.source_id}:{series_id}",
                        "series_column": column,
                        "series_name": series_names.get(column),
                        "date_raw": date_raw,
                        "unixtime": unixtime,
                        "value_raw": raw_value if raw_value is not None else None,
                        "artifact_sha256": asset.artifact_sha256,
                        "fetched_at": asset.fetched_at,
                        "locator": asset.locator,
                    }
                )

        if unmapped:
            warnings.append(
                "series_id derived by replacing underscores with dots for column(s) "
                + ", ".join(sorted(unmapped))
                + "; the request did not record a matching series code"
            )

        # ``dtype=object`` keeps a source ``null`` as ``None`` instead of letting pandas
        # coerce it to ``NaN``, and keeps raw date and value strings unconverted.
        dataframe = pd.DataFrame(rows, columns=COLUMNS, dtype=object)
        return ParsedBatch(
            source_id=asset.source_id,
            dataset_id=asset.dataset_id,
            artifact_sha256=asset.artifact_sha256,
            schema_version=self._schema_version,
            dataframe=dataframe,
            warnings=warnings,
        )

    # ----------------------------------------------------------------- helpers

    def _load(self, asset: FetchedAsset) -> dict[str, Any]:
        path = Path(asset.raw_path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise self._error(
                asset, "PARSE_FAILED", f"EVDS artifact could not be read: {path}"
            ) from exc

        if not text.strip():
            raise self._error(asset, "EMPTY_DATASET", f"EVDS artifact is empty: {path}")

        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise self._error(
                asset, "PARSE_FAILED", f"EVDS artifact is not valid JSON: {path}"
            ) from exc

        if not isinstance(document, dict):
            raise self._error(
                asset, "SCHEMA_MISMATCH", "EVDS response root must be a JSON object"
            )
        return document

    def _items(self, asset: FetchedAsset, document: dict[str, Any]) -> list[Any]:
        items = document.get("items")
        if items is None:
            raise self._error(
                asset, "SCHEMA_MISMATCH", "EVDS response has no 'items' array"
            )
        if not isinstance(items, list):
            raise self._error(
                asset, "SCHEMA_MISMATCH", "EVDS 'items' must be a JSON array"
            )
        if not items:
            raise self._error(
                asset, "EMPTY_DATASET", "EVDS response contains no observations"
            )
        return items

    @staticmethod
    def _requested_series(asset: FetchedAsset) -> list[str]:
        requested = asset.metadata.get("requested_series")
        if isinstance(requested, (list, tuple)):
            return [str(code) for code in requested]
        if isinstance(requested, str):
            return [code for code in requested.split("-") if code]
        return []

    def _check_counts(
        self,
        asset: FetchedAsset,
        document: dict[str, Any],
        items: list[Any],
        warnings: list[str],
    ) -> None:
        """Surface the documented silent-truncation risk without inventing calendar logic."""

        reported = document.get("totalCount")
        if isinstance(reported, int) and reported != len(items):
            warnings.append(
                f"totalCount {reported} does not match {len(items)} returned observations"
            )

        limit = asset.metadata.get("observation_limit", EVDS_OBSERVATION_LIMIT)
        if isinstance(limit, int) and limit > 0 and len(items) >= limit:
            warnings.append(
                f"{len(items)} observations reached the EVDS per-request limit of {limit}; "
                "the response may be silently truncated and the request range should be "
                "windowed before an OBSERVATION_COUNT_MISMATCH is raised upstream"
            )

    @staticmethod
    def _error(asset: FetchedAsset, error_code: str, message: str) -> LakehouseError:
        return LakehouseError(
            ErrorPayload(
                error_code=error_code,
                message=message,
                source_id=asset.source_id,
                dataset_id=asset.dataset_id,
                retryable=False,
            )
        )


__all__ = [
    "COLUMNS",
    "EVDS_SCHEMA_VERSION",
    "EvdsParser",
    "series_id_for_column",
]
