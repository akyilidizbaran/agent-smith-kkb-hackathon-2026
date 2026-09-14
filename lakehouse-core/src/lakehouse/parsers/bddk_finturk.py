"""BDDK FinTürk parser: local RAW JSON to a long-format ``ParsedBatch``.

Envelope captured from a live response on 2026-09-10 (tabloNo=3, Bireysel Bankacılık,
donem=2025-9, sehirList[0]=YALOVA)::

    {"success": true,
     "Json": {
       "colNames": ["Eftodu", "Yıl", "Ay", "Şehir", "Grup", "Taşıt Kredisi", "Konut Kredisi",
                    "Kredili Mevduat Hesabı", "Diğer Tüketici Kredileri",
                    "Bireysel Kredi Kartları", "Takipteki Taşıt Kredisi",
                    "Takipteki Konut Kredisi", "Takipteki Diğer Tüketici Kredileri"],
       "colModels": [{"name": "EftKodu", ...}, {"name": "Yil", ...}, {"name": "Ay", ...},
                     {"name": "Sehir", ...}, {"name": "Grup", ...},
                     {"name": "TasitKredisi", "formatter": "integer", ...},
                     {"name": "KonutKredisi", "formatter": "integer", ...}, ...],
       "data": {"page": "1", "total": "1", "records": "1",
                "rows": [{"cell": [10001, 2025, 9, "YALOVA", "SEKTÖR",
                                    192843, 2104493, 2436929, 4911508, 8316033,
                                    1614, 2295, 394348]}]}}}

Source behaviour this parser preserves instead of "fixing":

- Rows are **positional** ``cell`` arrays that must be zipped against ``colModels``, exactly
  like the monthly endpoint's grid — see ``docs/sources/bddk_monthly.md`` for why this shape is
  trusted rather than assumed to match across BDDK applications (it was verified live for each).
- One response row carries **every measure column for the table at once** (unlike the monthly
  endpoint, which the connector restricts to one ``kalemSutun`` per call). This parser therefore
  emits one output row **per measure column**, not one row per response row: a single FinTürk
  fetch legitimately produces several distinct series (``Konut Kredisi``, ``Taşıt Kredisi``, ...).
  Which of those series belong in the semantic catalog is a catalog decision (only the housing
  ones do, as of this track), not something this parser filters.
- **No unit is present anywhere in the response** — not in a column name (unlike the monthly
  endpoint's ``(milyon TL)`` suffix) and not as a separate field. The catalog entry for this
  source therefore cannot mark ``semantic_confidence: verified`` for unit; see
  ``docs/sources/bddk_finturk.md``, "Confirmation required".
- ``colModels[...].formatoptions.defaultValue`` is ``"0"`` on every measure column, the same
  display-default behaviour already documented for the monthly endpoint: a genuinely absent
  source value can render as zero in the BDDK grid. This parser never substitutes a value and
  records a warning instead.
- HTTP 200 does not mean success: the body may be ``{"success": false, "error": "..."}``, the
  same application-level failure shape as the monthly endpoint.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from ..contracts.models import FetchedAsset, ParsedBatch
from ..errors import ErrorPayload, LakehouseError


BDDK_FINTURK_SCHEMA_VERSION = "bddk_finturk_observations.v1"
"""Schema version of the long-format frame produced by this parser."""

_STRUCTURAL_COLUMNS = frozenset({"EftKodu", "Yil", "Ay", "Sehir", "Grup"})

_TR_ASCII_MAP = str.maketrans(
    {"İ": "I", "Ş": "S", "Ğ": "G", "Ü": "U", "Ö": "O", "Ç": "C", "ı": "i"}
)
"""Turkish-letter-to-ASCII map for series_id derivation only (validate_series_id forbids
non-ASCII characters). Never applied to measure_column/measure_label/entity_label, which keep
the source's exact text."""

COLUMNS = [
    "source_id",
    "dataset_id",
    "series_id",
    "measure_column",
    "measure_label",
    "entity_label",
    "party_label",
    "year_raw",
    "month_raw",
    "value_raw",
    "artifact_sha256",
    "fetched_at",
    "locator",
]


class BddkFinTurkParser:
    """Read one persisted BDDK FinTürk artifact and return a provenance-preserving batch."""

    def __init__(self, schema_version: str = BDDK_FINTURK_SCHEMA_VERSION) -> None:
        self._schema_version = schema_version

    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        """Read only ``asset.raw_path`` and flatten the grid into one row per measure value."""

        document = self._load(asset)
        payload = self._payload(asset, document)
        warnings: list[str] = []

        column_names = self._column_names(asset, payload)
        row = self._single_row(asset, payload, column_names)
        measure_indexes = [
            index
            for index, name in enumerate(column_names)
            if name not in _STRUCTURAL_COLUMNS
        ]
        if not measure_indexes:
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK FinTürk response has no measure column"
            )

        positions = {name: index for index, name in enumerate(column_names)}
        self._check_display_default(payload, measure_indexes, warnings)

        sehir = self._cell_at(row, positions.get("Sehir"))
        grup = self._cell_at(row, positions.get("Grup"))
        year_raw = self._cell_at(row, positions.get("Yil"))
        month_raw = self._cell_at(row, positions.get("Ay"))

        requested_sehir = asset.metadata.get("requested_sehir")
        if requested_sehir and sehir and str(requested_sehir).strip().upper() != str(sehir).strip().upper():
            raise self._error(
                asset,
                "SCHEMA_MISMATCH",
                f"requested sehir {requested_sehir!r} does not match response Sehir {sehir!r}",
            )

        records: list[dict[str, Any]] = []
        for index in measure_indexes:
            column_name = column_names[index]
            records.append(
                {
                    "source_id": asset.source_id,
                    "dataset_id": asset.dataset_id,
                    "series_id": f"{asset.source_id}:{self._slug(str(sehir))}_{self._slug(column_name)}",
                    "measure_column": column_name,
                    "measure_label": column_name,
                    "entity_label": sehir,
                    "party_label": grup,
                    "year_raw": year_raw,
                    "month_raw": month_raw,
                    "value_raw": row[index],
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
                asset, "PARSE_FAILED", f"BDDK FinTürk artifact could not be read: {path}"
            ) from exc

        if not text.strip():
            raise self._error(asset, "EMPTY_DATASET", f"BDDK FinTürk artifact is empty: {path}")

        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise self._error(
                asset, "PARSE_FAILED", f"BDDK FinTürk artifact is not valid JSON: {path}"
            ) from exc

        if not isinstance(document, dict):
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK FinTürk response root must be a JSON object"
            )
        return document

    def _payload(self, asset: FetchedAsset, document: dict[str, Any]) -> dict[str, Any]:
        """Reject the application-level failure that BDDK returns inside an HTTP 200."""

        if document.get("success") is not True:
            message = str(document.get("error") or "unknown BDDK application error")
            raise LakehouseError(
                ErrorPayload(
                    error_code="SOURCE_UNAVAILABLE",
                    message=f"BDDK FinTürk report was not produced: {message}",
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=True,
                )
            )

        payload = document.get("Json")
        if not isinstance(payload, dict):
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK FinTürk response has no 'Json' object"
            )
        return payload

    def _column_names(self, asset: FetchedAsset, payload: dict[str, Any]) -> list[str]:
        models = payload.get("colModels")
        if not isinstance(models, list) or not models:
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK FinTürk response has no 'colModels' array"
            )

        names: list[str] = []
        for index, model in enumerate(models):
            if not isinstance(model, dict) or not str(model.get("name", "")).strip():
                raise self._error(
                    asset, "SCHEMA_MISMATCH", f"BDDK FinTürk colModels[{index}] has no name"
                )
            names.append(str(model["name"]))
        return names

    def _single_row(
        self, asset: FetchedAsset, payload: dict[str, Any], column_names: list[str]
    ) -> list[Any]:
        """Return the one data row this endpoint's (sehir, donem, tabloNo) triple addresses.

        Unlike the monthly/weekly endpoints, a FinTürk request maps to exactly one row (one
        city, one period). More or fewer than one row is a schema surprise, not a windowing
        question — this parser does not aggregate or pick a row.
        """

        data = payload.get("data")
        if not isinstance(data, dict):
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK FinTürk response has no 'data' object"
            )
        rows = data.get("rows")
        if not isinstance(rows, list):
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK FinTürk 'data.rows' must be a JSON array"
            )
        if not rows:
            raise self._error(asset, "EMPTY_DATASET", "BDDK FinTürk response contains no rows")
        if len(rows) > 1:
            raise self._error(
                asset,
                "SCHEMA_MISMATCH",
                f"BDDK FinTürk response contains {len(rows)} rows; exactly 1 was expected "
                "for a single (sehir, donem, tabloNo) request",
            )

        row_obj = rows[0]
        if not isinstance(row_obj, dict) or not isinstance(row_obj.get("cell"), list):
            raise self._error(asset, "SCHEMA_MISMATCH", "BDDK FinTürk row 0 has no 'cell' array")
        cells = row_obj["cell"]
        if len(cells) != len(column_names):
            raise self._error(
                asset,
                "SCHEMA_MISMATCH",
                f"BDDK FinTürk row has {len(cells)} cells but {len(column_names)} columns "
                "are declared",
            )
        return cells

    @staticmethod
    def _cell_at(cells: list[Any], index: int | None) -> Any:
        return None if index is None else cells[index]

    @staticmethod
    def _slug(value: str) -> str:
        """Reduce a source token to the identifier alphabet the shared contract allows.

        series_id is restricted to [A-Za-z0-9_.-] (validate_series_id), which excludes
        Turkish letters — the response's "Sehir" field comes back as native Turkish
        uppercase (e.g. "AĞRI"), so those must be transliterated to ASCII first, not just
        stripped, or a province like AĞRI would collapse into a near-empty slug ("A_RI"
        with a naive strip) instead of a stable, catalog-matching "AGRI". This mirrors the
        transliteration used when the catalog/series/bddk_finturk.yml entries were
        generated, so the parser's derived series_id agrees with the catalog's.
        """

        transliterated = value.translate(_TR_ASCII_MAP)
        slug = re.sub(r"[^A-Za-z0-9]+", "_", transliterated).strip("_")
        return slug or "value"

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


__all__ = ["BDDK_FINTURK_SCHEMA_VERSION", "COLUMNS", "BddkFinTurkParser"]
