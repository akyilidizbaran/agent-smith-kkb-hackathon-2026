"""BDDK Weekly Bulletin parser: local RAW JSON to a long-format ``ParsedBatch``.

Envelope captured from a live response on 2026-09-09::

    {"Baslik": "a) Konut (TRY) [Toplam]",
     "XEkseni": ["2.01.2026", "9.01.2026", ..., "26.06.2026"],
     "YEkseni": [679216.118, 682408.729, ..., 800464.007]}

Source behaviour this parser preserves instead of "fixing":

- The payload is **two parallel arrays**, not records. Position is the only link between a date
  and its value, so a length mismatch is a hard schema error rather than something to zip-and-
  truncate.
- Dates arrive **oldest first**, the opposite of the monthly grid, and as raw ``d.MM.yyyy``
  strings with a **non-padded day**. They are kept verbatim; no Friday anchoring, no
  ``date_key`` and no canonical date is produced here.
- Weeks are **not evenly spaced**. The live series steps 13.03 → 19.03 → 27.03, i.e. 6 then 8
  days. Nothing here regularizes that.
- The response carries **no unit field**. ``(TRY)`` inside ``Baslik`` is the currency leg, not
  the magnitude. The unit is published on the source's own page instead — the ``Krediler`` /
  ``Sektör`` table header at ``https://www.bddk.org.tr/BultenHaftalik/`` reads
  ``Birim: Milyon TL`` and ``a) Konut`` is a row of that table — but it does not travel inside
  this payload, so no unit column is produced here. Attaching ``unit = milyon TL`` on the
  strength of that table header is a Silver mapping decision, not a parsing one.
- There is **no ``success`` flag**. An unresolved item still answers HTTP 200, with the
  placeholder title ``"Grafik Başlığı"`` and empty arrays. That is an application failure and
  must not become a successful batch.
- An in-range request that covers no published week also answers HTTP 200 with empty arrays but
  keeps the real title. That is an empty dataset, which is a different condition.

``series_id`` is built **only** from the stable ``requested_kalem_id`` recorded by the
connector. The positional chart id is carried as data but is never an identity fallback.

Because the endpoint is addressed positionally, the parsed title is also checked against the
``expected_measure_label`` / ``expected_currency`` / ``expected_column`` the connector
recorded. A reordered bulletin returns HTTP 200 with a plausible payload for the *wrong*
series; that mismatch is a ``SCHEMA_MISMATCH``, not data.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from ..contracts.models import FetchedAsset, ParsedBatch
from ..errors import ErrorPayload, LakehouseError


BDDK_WEEKLY_SCHEMA_VERSION = "bddk_weekly_observations.v1"
"""Schema version of the long-format frame produced by this parser."""

BDDK_WEEKLY_PLACEHOLDER_TITLE = "Grafik Başlığı"
"""Title the endpoint returns when it cannot resolve the requested chart id."""

_TITLE_RE = re.compile(r"^(?P<label>.*?)\s*\((?P<currency>[^()]*)\)\s*(?:\[(?P<column>[^\]]*)\])?\s*$")

COLUMNS = [
    "source_id",
    "dataset_id",
    "series_id",
    "chart_id",
    "kalem_id",
    "series_title",
    "measure_label",
    "currency_label",
    "column_label",
    "entity_code",
    "date_raw",
    "value_raw",
    "source_order",
    "artifact_sha256",
    "fetched_at",
    "locator",
]


def _normalize(value: str | None) -> str | None:
    """Collapse internal whitespace and trim. Nothing else — no case folding, no fuzziness."""

    if value is None:
        return None
    collapsed = " ".join(str(value).split())
    return collapsed or None


def split_title(title: str) -> tuple[str | None, str | None, str | None]:
    """Split ``a) Konut (TRY) [Toplam]`` into label, currency and column.

    Returns ``(None, None, None)`` components that do not match rather than guessing, because
    the title is a display string and BDDK can reword it.
    """

    match = _TITLE_RE.match(title.strip())
    if match is None:
        return None, None, None
    label = (match.group("label") or "").strip() or None
    currency = (match.group("currency") or "").strip() or None
    column = (match.group("column") or "").strip() or None
    return label, currency, column


class BddkWeeklyParser:
    """Read one persisted BDDK weekly artifact and return a provenance-preserving batch."""

    def __init__(self, schema_version: str = BDDK_WEEKLY_SCHEMA_VERSION) -> None:
        self._schema_version = schema_version

    def parse(self, asset: FetchedAsset) -> ParsedBatch:
        """Read only ``asset.raw_path`` and pair the parallel arrays into one row per week."""

        document = self._load(asset)
        title = document.get("Baslik")
        title_text = "" if title is None else str(title)
        dates = self._array(asset, document, "XEkseni")
        values = self._array(asset, document, "YEkseni")

        self._reject_unsuccessful(asset, title_text, dates, values)
        if len(dates) != len(values):
            raise self._error(
                asset,
                "SCHEMA_MISMATCH",
                (
                    f"BDDK weekly arrays are not parallel: XEkseni has {len(dates)} entries "
                    f"but YEkseni has {len(values)}; position is the only link between a "
                    "date and its value"
                ),
            )

        measure_label, currency_label, column_label = split_title(title_text)
        self._verify_identity(asset, measure_label, currency_label, column_label)
        series_id = self._series_id(asset)
        chart_id = asset.metadata.get("requested_chart_id")
        kalem_id = asset.metadata.get("requested_kalem_id")
        entity_code = asset.metadata.get("requested_taraf")

        records: list[dict[str, Any]] = []
        for order, (date_raw, value_raw) in enumerate(zip(dates, values)):
            records.append(
                {
                    "source_id": asset.source_id,
                    "dataset_id": asset.dataset_id,
                    "series_id": series_id,
                    "chart_id": chart_id,
                    "kalem_id": kalem_id,
                    "series_title": title_text,
                    "measure_label": measure_label,
                    "currency_label": currency_label,
                    "column_label": column_label,
                    "entity_code": entity_code,
                    "date_raw": date_raw,
                    "value_raw": value_raw,
                    "source_order": order,
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
            warnings=[],
        )

    # ----------------------------------------------------------------- helpers

    def _load(self, asset: FetchedAsset) -> dict[str, Any]:
        path = Path(asset.raw_path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise self._error(
                asset, "PARSE_FAILED", f"BDDK weekly artifact could not be read: {path}"
            ) from exc

        if not text.strip():
            raise self._error(asset, "EMPTY_DATASET", f"BDDK weekly artifact is empty: {path}")

        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise self._error(
                asset, "PARSE_FAILED", f"BDDK weekly artifact is not valid JSON: {path}"
            ) from exc

        if not isinstance(document, dict):
            raise self._error(
                asset, "SCHEMA_MISMATCH", "BDDK weekly response root must be a JSON object"
            )
        return document

    def _array(self, asset: FetchedAsset, document: dict[str, Any], key: str) -> list[Any]:
        value = document.get(key)
        if not isinstance(value, list):
            raise self._error(
                asset, "SCHEMA_MISMATCH", f"BDDK weekly response has no '{key}' array"
            )
        return value

    def _reject_unsuccessful(
        self, asset: FetchedAsset, title: str, dates: list[Any], values: list[Any]
    ) -> None:
        """Separate an unresolved chart id from a genuinely empty range.

        Both answer HTTP 200 with empty arrays, so the title is the only signal that tells
        them apart. Neither may become a successful batch.
        """

        if dates or values:
            return
        if title.strip() == BDDK_WEEKLY_PLACEHOLDER_TITLE:
            raise LakehouseError(
                ErrorPayload(
                    error_code="SOURCE_UNAVAILABLE",
                    message=(
                        "BDDK weekly endpoint returned the placeholder title "
                        f"{BDDK_WEEKLY_PLACEHOLDER_TITLE!r} with empty arrays; the requested "
                        "chart id was not resolved"
                    ),
                    source_id=asset.source_id,
                    dataset_id=asset.dataset_id,
                    retryable=False,
                )
            )
        raise self._error(
            asset,
            "EMPTY_DATASET",
            f"BDDK weekly series {title.strip()!r} returned no observations for the "
            "requested range",
        )

    def _verify_identity(
        self,
        asset: FetchedAsset,
        measure_label: str | None,
        currency_label: str | None,
        column_label: str | None,
    ) -> None:
        """Refuse a response whose title is not the series the caller asked for.

        The weekly endpoint is addressed by a **positional** chart id (``1.0.4``). If BDDK
        reorders the bulletin, that address can start returning a different line and the HTTP
        exchange gives no sign of it: status 200, same shape, plausible numbers, wrong series.
        The only in-band signal is ``Baslik``, so the connector records what the caller
        expected and this compares the two.

        The comparison is deterministic: exact string equality after collapsing internal
        whitespace and trimming. No case folding, no fuzzy or model-based matching — a
        near-match here would defeat the check it is meant to perform.
        """

        expected = {
            "measure label": (
                asset.metadata.get("expected_measure_label"), measure_label
            ),
            "currency": (asset.metadata.get("expected_currency"), currency_label),
            "column": (asset.metadata.get("expected_column"), column_label),
        }
        missing = [name for name, (want, _) in expected.items() if not _normalize(want)]
        if missing:
            raise self._error(
                asset,
                "SCHEMA_MISMATCH",
                (
                    "BDDK weekly artifact metadata carries no "
                    f"{', '.join(sorted(missing))} expectation; the positional chart id "
                    "cannot be verified and the response must not be trusted"
                ),
            )

        for name, (want, got) in expected.items():
            if _normalize(want) != _normalize(got):
                raise self._error(
                    asset,
                    "SCHEMA_MISMATCH",
                    (
                        f"BDDK weekly {name} mismatch: expected {_normalize(want)!r} but the "
                        f"response title says {_normalize(got)!r}. The chart id is positional, "
                        "so this is how a reordered bulletin returns a different series."
                    ),
                )

    def _series_id(self, asset: FetchedAsset) -> str:
        """Build the series id from the stable native item id, or fail.

        The weekly endpoint addresses a series by a **positional** chart id (``1.0.4``), which
        can point at a different bulletin line after a layout change. There is deliberately no
        fallback to it: a series identified by a positional address is not a stable series, and
        silently producing one would let a relabelled line inherit another line's identity. The
        item tree's ``Kalem-<id>`` value (``5690``) is the only accepted source of identity.
        """

        kalem_id = asset.metadata.get("requested_kalem_id")
        if kalem_id is None or not str(kalem_id).strip():
            raise self._error(
                asset,
                "SCHEMA_MISMATCH",
                "BDDK weekly artifact metadata carries no 'requested_kalem_id'; a stable "
                "series_id cannot be built and the positional chart id is not a substitute",
            )

        key = self._slug(str(kalem_id))
        column = asset.metadata.get("requested_column")
        if column is not None and str(column).strip():
            key = f"{key}_{self._slug(str(column))}"
        return f"{asset.source_id}:{key}"

    @staticmethod
    def _slug(value: str) -> str:
        """Reduce a source token to the identifier alphabet the shared contract allows."""

        slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
        return slug or "series"

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
    "BDDK_WEEKLY_PLACEHOLDER_TITLE",
    "BDDK_WEEKLY_SCHEMA_VERSION",
    "COLUMNS",
    "BddkWeeklyParser",
    "split_title",
]
