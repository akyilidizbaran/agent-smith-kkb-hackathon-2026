"""BDDK Monthly Bulletin parser: local RAW JSON to a long-format ``ParsedBatch``.

Envelope captured from a live response on 2026-09-08::

    {"success": true,
     "Json": {
       "colNames": ["Banka", "Yıl", "Ay", "Toplam", "Sira"],
       "colModels": [{"name": "BankaAdi", ...}, {"name": "Yil", ...}, {"name": "Ay", ...},
                     {"name": "Tüketici Kredileri - Tüketici Kredileri - Konut (milyon TL)-Toplam",
                      "formatter": "integer",
                      "formatoptions": {"thousandsSeparator": ".", "defaultValue": "0"}},
                     {"name": "Sira", ...}],
       "groupHeaders": [{"startColumnName": "...", "numberOfColumns": "1",
                         "titleText": "Tüketici Kredileri - Tüketici Kredileri - Konut (milyon TL)"}],
       "data": {"page": "1", "total": "1", "records": "66",
                "rows": [{"cell": ["Sektör", 2026, 6, 801438, 1]}]},
       "caption": null}}

Source behaviour this parser preserves instead of "fixing":

- Rows are **positional** ``cell`` arrays that must be zipped against ``colModels``.
- The measure's **unit is embedded in the column name** (``(milyon TL)``); BDDK exposes no
  separate unit field.
- Rows arrive in **descending period order**; the parser keeps source order and also keeps the
  source's own ``Sira`` rank.
- ``colModels[...].formatoptions.defaultValue`` is ``"0"``. That is a *display* default in the
  BDDK grid, so a genuinely absent value can be shown as zero in the UI. This parser never
  substitutes a value, and records the presence of that display default as a warning.
- **Subtotal rows are not marked on this endpoint.** The simple-report endpoint exposes a
  ``BasitFont`` display-style field, but the advanced time-series endpoint used here does not.
  No speculative, always-NULL style columns and no derived ``is_subtotal`` are added to this
  V1 Bronze schema.
- HTTP 200 does not mean success: the body may be ``{"success": false, "error": "..."}``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from ..contracts.models import FetchedAsset, ParsedBatch
from ..errors import ErrorPayload, LakehouseError


BDDK_MONTHLY_SCHEMA_VERSION = "bddk_monthly_observations.v1"
"""Schema version of the long-format frame produced by this parser."""

_STRUCTURAL_COLUMNS = frozenset({"BankaAdi", "Yil", "Ay", "Sira", "BasitFont", "parent"})

_UNIT_RE = re.compile(r"\(([^()]*)\)\s*(?:-[^-]*)?$")

COLUMNS = [
    "source_id",
    "dataset_id",
    "series_id",
    "measure_column",
    "measure_label",
    "unit_label",
    "entity_label",
    "year_raw",
    "month_raw",
    "value_raw",
    "source_order",
    "artifact_sha256",
    "fetched_at",
    "locator",
]


def unit_label_from_column(column_name: str) -> str | None:
    """Extract the unit BDDK embeds in a column name, e.g. ``(milyon TL)``."""

    match = _UNIT_RE.search(column_name)
    return match.group(1).strip() if match else None


class BddkMonthlyParser:
    """Read one persisted BDDK monthly artifact and return a provenance-preserving batch."""

    def __init__(self, schema_version: str = BDDK_MONTHLY_SCHEMA_VERSION) -> None:
        self._schema_version = schema_version

    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        """Read only ``asset.raw_path`` and flatten the grid into one row per measure value."""

        document = self._load(asset)
        payload = self._payload(asset, document)
        warnings: list[str] = []

        column_names = self._column_names(asset, payload)
        rows = self._rows(asset, payload)
        measure_indexes = [
            index
            for index, name in enumerate(column_names)
            if name not in _STRUCTURAL_COLUMNS
        ]
        if not measure_indexes:
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK monthly response has no measure column"
            )

        positions = {name: index for index, name in enumerate(column_names)}
        series_keys = self._series_keys(asset, column_names, measure_indexes, warnings)
        self._check_display_default(payload, measure_indexes, warnings)
        self._check_period_count(asset, rows, warnings)

        records: list[dict[str, Any]] = []
        for row_index, row in enumerate(rows):
            cells = self._cells(asset, row, row_index, len(column_names))
            for index in measure_indexes:
                column_name = column_names[index]
                records.append(
                    {
                        "source_id": asset.source_id,
                        "dataset_id": asset.dataset_id,
                        "series_id": f"{asset.source_id}:{series_keys[index]}",
                        "measure_column": column_name,
                        "measure_label": column_name,
                        "unit_label": unit_label_from_column(column_name),
                        "entity_label": self._cell_at(cells, positions.get("BankaAdi")),
                        "year_raw": self._cell_at(cells, positions.get("Yil")),
                        "month_raw": self._cell_at(cells, positions.get("Ay")),
                        "value_raw": cells[index],
                        "source_order": self._cell_at(cells, positions.get("Sira")),
                        "artifact_sha256": asset.artifact_sha256,
                        "fetched_at": asset.fetched_at,
                        "locator": asset.locator,
                    }
                )

        # ``dtype=object`` keeps a source ``null`` as ``None`` rather than ``NaN`` and keeps
        # raw values exactly as BDDK returned them.
        dataframe = pd.DataFrame(records, columns=COLUMNS, dtype=object)
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
                asset, "PARSE_FAILED", f"BDDK monthly artifact could not be read: {path}"
            ) from exc

        if not text.strip():
            raise self._error(asset, "EMPTY_DATASET", f"BDDK monthly artifact is empty: {path}")

        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise self._error(
                asset, "PARSE_FAILED", f"BDDK monthly artifact is not valid JSON: {path}"
            ) from exc

        if not isinstance(document, dict):
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK monthly response root must be a JSON object"
            )
        return document

    def _payload(self, asset: FetchedAsset, document: dict[str, Any]) -> dict[str, Any]:
        """Reject the application-level failure that BDDK returns inside an HTTP 200."""

        if document.get("success") is not True:
            message = str(document.get("error") or "unknown BDDK application error")
            raise LakehouseError(
                ErrorPayload(
                    error_code="SOURCE_UNAVAILABLE",
                    message=f"BDDK monthly report was not produced: {message}",
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=True,
                )
            )

        payload = document.get("Json")
        if not isinstance(payload, dict):
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK monthly response has no 'Json' object"
            )
        return payload

    def _column_names(self, asset: FetchedAsset, payload: dict[str, Any]) -> list[str]:
        models = payload.get("colModels")
        if not isinstance(models, list) or not models:
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK monthly response has no 'colModels' array"
            )

        names: list[str] = []
        for index, model in enumerate(models):
            if not isinstance(model, dict) or not str(model.get("name", "")).strip():
                raise self._error(
                    asset, "SCHEMA_MISMATCH", f"BDDK monthly colModels[{index}] has no name"
                )
            names.append(str(model["name"]))
        return names

    def _rows(self, asset: FetchedAsset, payload: dict[str, Any]) -> list[Any]:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK monthly response has no 'data' object"
            )
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK monthly 'data.rows' must be a JSON array"
            )
        if not rows:
            raise self._error(
                asset, "EMPTY_DATASET", "BDDK monthly response contains no rows"
            )
        return rows

    def _cells(
        self, asset: FetchedAsset, row: Any, row_index: int, expected: int
    ) -> list[Any]:
        if not isinstance(row, dict) or not isinstance(row.get("cell"), list):
            raise self._error(
                asset, "SCHEMA_MISMATCH", f"BDDK monthly row {row_index} has no 'cell' array"
            )
        cells = row["cell"]
        if len(cells) != expected:
            raise self._error(
                asset,
                "SCHEMA_MISMATCH",
                (
                    f"BDDK monthly row {row_index} has {len(cells)} cells "
                    f"but {expected} columns are declared"
                ),
            )
        return cells

    @staticmethod
    def _cell_at(cells: list[Any], index: int | None) -> Any:
        return None if index is None else cells[index]

    def _series_keys(
        self,
        asset: FetchedAsset,
        column_names: list[str],
        measure_indexes: list[int],
        warnings: list[str],
    ) -> dict[int, str]:
        """Prefer the stable ``kalemSutun`` ids the connector requested.

        BDDK column names are Turkish labels that lose characters when reduced to the
        identifier alphabet the shared contract allows, and they change whenever BDDK
        rewords a bulletin line. The requested item ids are stable, so they are used when
        the response returns exactly as many measure columns as ids were requested.
        """

        override = asset.metadata.get("requested_series_key")
        if override and len(measure_indexes) == 1:
            # A historical schema id of a catalogued item: the response is keyed by the OLD id, the
            # catalog knows the item by its current one. The connector recorded which series this
            # request was made for; one measure column, so the mapping is unambiguous.
            return {measure_indexes[0]: self._slug(str(override))}
        if override:
            warnings.append(
                f"'requested_series_key' ({override}) ignored: the response has "
                f"{len(measure_indexes)} measure columns, the override is only unambiguous for one"
            )
        requested = asset.metadata.get("requested_kalem_sutun")
        if isinstance(requested, (list, tuple)) and len(requested) == len(measure_indexes):
            return {
                index: self._slug(str(requested[position]))
                for position, index in enumerate(measure_indexes)
            }

        warnings.append(
            "series_id derived from the BDDK column label because the artifact metadata "
            "carries no matching 'requested_kalem_sutun' list; the label is not a stable key"
        )
        return {index: self._slug(column_names[index]) for index in measure_indexes}

    @staticmethod
    def _slug(value: str) -> str:
        """Reduce a source token to the identifier alphabet the shared contract allows."""

        slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
        return slug or "measure"

    @staticmethod
    def _check_display_default(
        payload: dict[str, Any], measure_indexes: list[int], warnings: list[str]
    ) -> None:
        models = payload.get("colModels") or []
        for index in measure_indexes:
            options = models[index].get("formatoptions")
            if isinstance(options, dict) and str(options.get("defaultValue", "")) == "0":
                warnings.append(
                    f"column '{models[index].get('name')}' declares a grid display "
                    "defaultValue of '0'; an absent source value can appear as zero in the "
                    "BDDK UI and must not be treated as a measured zero"
                )

    @staticmethod
    def _check_period_count(
        asset: FetchedAsset, rows: list[Any], warnings: list[str]
    ) -> None:
        expected = asset.metadata.get("expected_period_count")
        if isinstance(expected, int) and expected > 0 and len(rows) != expected:
            warnings.append(
                f"{len(rows)} periods returned but {expected} were requested; an "
                "OBSERVATION_COUNT_MISMATCH check applies upstream"
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
    "BDDK_MONTHLY_SCHEMA_VERSION",
    "COLUMNS",
    "BddkMonthlyParser",
    "unit_label_from_column",
]
