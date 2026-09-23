"""Publish an ad-hoc Bronze frame into ``adhoc.fact_observation`` through an explicit mapping.

The generic parser deliberately refuses to guess what a column means. This module is where
somebody says it: *this column is the date, that one is the value, dates look like this,
numbers look like that*. Everything about the **semantics** of the resulting series still
comes from ``meta.series`` -- frequency, unit and measure type are read from the catalog and
cannot be supplied here, because a mapping is a statement about a file's layout, not about
what the numbers mean.

The distinction matters most for numbers. ``"1,5"`` is one-and-a-half in Turkish and fifteen
hundred in English, and no amount of inspection settles it: a file of ``"1,5"``, ``"2,7"`` is
consistent with both readings. So a non-ISO date or a non-plain number requires the caller to
state the format, and an unstated one is refused rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import math
import re
import json
from typing import Any, Final

import duckdb

from ..ingestion.observability import datetime_from_epoch_us, epoch_us
from ..ingestion.pipeline import IngestionResult
from ..storage.parquet import ParquetStorage, identity_for, read_identity
from ..generic.config import config_from_metadata
from ..generic.formats import FormatError


ADHOC_SOURCE_ID: Final[str] = "adhoc"
ADHOC_RELATION: Final[str] = "adhoc.fact_observation"

FACT_COLUMNS: Final[tuple[str, ...]] = (
    "series_id",
    "entity_id",
    "observation_date",
    "period_start",
    "period_end",
    "value",
    "frequency",
    "unit",
    "measure_type",
    "quality_flag",
    "source_id",
    "dataset_id",
    "artifact_sha256",
    "fetched_at",
    "schema_version",
    "vintage_id",
    "run_id",
)
"""Same columns, same order and same meanings as ``silver.fact_observation``."""

_ISO_FORMATS: Final[tuple[str, ...]] = ("%Y-%m-%d",)
"""The only date shape accepted without an explicit ``date_format``. ISO is unambiguous;
``01/02/2026`` is not, and there is no honest way to choose between January 2nd and February
1st from the data alone."""


class AdhocPublicationError(ValueError):
    """Raised when an ad-hoc frame cannot be published as mapped."""


class AdhocPublicationConflict(AdhocPublicationError):
    """Raised when the same identity already holds a different value."""


@dataclass(frozen=True)
class AdhocObservationMapping:
    """How one series is read out of an ad-hoc Bronze frame.

    Only layout lives here. There is deliberately no ``measure_type``, ``frequency``, ``unit``
    or aggregation field: those are catalog facts, and letting a mapping carry them would let
    the same file mean two different things depending on who published it.
    """

    series_id: str
    observation_date_column: str
    value_column: str
    entity_id_column: str | None = None
    date_format: str | None = None
    decimal_separator: str = "."
    thousands_separator: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.series_id, str) or not self.series_id.strip():
            raise AdhocPublicationError("series_id must be a non-empty string")
        for name in ("observation_date_column", "value_column"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise AdhocPublicationError(f"{name} must be a non-empty string")
        if self.entity_id_column is not None and not str(self.entity_id_column).strip():
            raise AdhocPublicationError("entity_id_column must be None or a column name")
        if self.decimal_separator not in {".", ","}:
            raise AdhocPublicationError("decimal_separator must be '.' or ','")
        if self.thousands_separator is not None:
            if self.thousands_separator not in {".", ",", " ", " ", "'"}:
                raise AdhocPublicationError(
                    "thousands_separator must be one of '.', ',', a space or an apostrophe"
                )
            if self.thousands_separator == self.decimal_separator:
                raise AdhocPublicationError(
                    "thousands_separator and decimal_separator must differ"
                )


@dataclass(frozen=True)
class AdhocPublicationResult:
    """What one publication wrote."""

    rows_written: int
    rows_unchanged: int
    series_ids: tuple[str, ...]
    artifact_sha256: str


# ------------------------------------------------------------------ conversion


def _parse_date(raw: Any, mapping: AdhocObservationMapping, row_number: int) -> date:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        raise AdhocPublicationError(
            f"{mapping.series_id}: observation_date is NULL at row {row_number}; a row with "
            "no date cannot be placed on a timeline"
        )
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        raise AdhocPublicationError(
            f"{mapping.series_id}: observation_date is blank at row {row_number}"
        )

    formats = (mapping.date_format,) if mapping.date_format else _ISO_FORMATS
    for candidate in formats:
        try:
            return datetime.strptime(text, candidate).date()
        except ValueError:
            continue

    if mapping.date_format:
        raise AdhocPublicationError(
            f"{mapping.series_id}: {text!r} at row {row_number} does not match the declared "
            f"date_format {mapping.date_format!r}"
        )
    raise AdhocPublicationError(
        f"{mapping.series_id}: {text!r} at row {row_number} is not an ISO date. Day-first and "
        "month-first cannot be told apart from the data, so pass an explicit date_format "
        "such as '%d.%m.%Y'"
    )


def _parse_value(raw: Any, mapping: AdhocObservationMapping, row_number: int) -> float | None:
    """Convert one cell to a finite float, or keep it NULL. Never guess a separator."""

    if raw is None:
        return None
    if isinstance(raw, bool):
        raise AdhocPublicationError(
            f"{mapping.series_id}: value at row {row_number} is a boolean, not a measurement"
        )
    if isinstance(raw, (int, float)):
        number = float(raw)
        if not math.isfinite(number):
            raise AdhocPublicationError(
                f"{mapping.series_id}: value at row {row_number} is {raw!r}; NaN and Infinity "
                "are not measurements and are never stored as NULL either"
            )
        return number

    text = str(raw).strip()
    if not text:
        # An empty cell is the source saying nothing, which stays NULL rather than becoming 0.
        return None

    normalized = text
    if mapping.thousands_separator and mapping.thousands_separator in text:
        group = re.escape(mapping.thousands_separator)
        decimal = re.escape(mapping.decimal_separator)
        # Grouped integers have 1-3 leading digits followed by exact triplets. Grouping
        # is never allowed in the fractional part or exponent.
        pattern = rf"[+-]?[0-9]{{1,3}}(?:{group}[0-9]{{3}})+(?:{decimal}[0-9]+)?(?:[eE][+-]?[0-9]+)?"
        if re.fullmatch(pattern, text) is None:
            raise AdhocPublicationError(
                f"{mapping.series_id}: invalid thousands grouping at row {row_number}"
            )
        normalized = normalized.replace(mapping.thousands_separator, "")
    if mapping.decimal_separator == ",":
        if "." in normalized and mapping.thousands_separator != ".":
            raise AdhocPublicationError(
                f"{mapping.series_id}: {text!r} at row {row_number} holds a '.' while the "
                "decimal separator is ','; declare thousands_separator='.' if that is what "
                "it means"
            )
        normalized = normalized.replace(",", ".")
    elif "," in normalized:
        raise AdhocPublicationError(
            f"{mapping.series_id}: {text!r} at row {row_number} holds a ',' while the decimal "
            "separator is '.'; declare decimal_separator=',' or thousands_separator=','"
        )

    try:
        number = float(normalized)
    except ValueError as exc:
        raise AdhocPublicationError(
            f"{mapping.series_id}: {text!r} at row {row_number} is not a number under the "
            f"declared format (decimal {mapping.decimal_separator!r}, thousands "
            f"{mapping.thousands_separator!r})"
        ) from exc
    if not math.isfinite(number):
        raise AdhocPublicationError(
            f"{mapping.series_id}: {text!r} at row {row_number} resolves to a non-finite "
            "number"
        )
    return number


def _entity(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


# -------------------------------------------------------------------- catalog


def _catalog_semantics(
    connection: duckdb.DuckDBPyConnection, series_id: str, dataset_id: str
) -> tuple[str, str | None, str]:
    row = connection.execute(
        """
        SELECT source_id, dataset_id, frequency, unit, measure_type
        FROM meta.series
        WHERE series_id = ?
        """,
        [series_id],
    ).fetchone()
    if row is None:
        raise AdhocPublicationError(
            f"{series_id!r} has no meta.series row; register it first, so the published rows "
            "carry a frequency, a unit and a measure type that somebody stated"
        )
    catalog_source, catalog_dataset, frequency, unit, measure_type = row
    if catalog_source != ADHOC_SOURCE_ID:
        raise AdhocPublicationError(
            f"{series_id!r} belongs to source {catalog_source!r}; only {ADHOC_SOURCE_ID!r} "
            "series may be published into the ad-hoc table"
        )
    if catalog_dataset != dataset_id:
        raise AdhocPublicationError(
            f"{series_id!r} is catalogued under dataset {catalog_dataset!r} but the artifact "
            f"was ingested as {dataset_id!r}; one of the two is wrong"
        )
    return frequency, unit, measure_type


# ----------------------------------------------------------- run-artifact link


def _verified_run_artifact_fetched_at(
    connection: duckdb.DuckDBPyConnection, result: IngestionResult
) -> datetime:
    """Require the durable ``meta.run_artifact`` link and return its ``fetched_at``.

    The run row alone only proves that a run over this source/dataset completed; it does not
    prove that *this* run fetched *this* artifact. The link does. Every identity on the link
    must equal what the in-memory result claims -- source, dataset, ``fetched_at`` to the
    microsecond and the parser configuration digest -- and the link's source/dataset must
    also equal the artifact's own registration. The value returned here, not
    ``result.asset.fetched_at``, is what gets published.
    """

    asset = result.asset
    link = connection.execute(
        """
        SELECT source_id, dataset_id, epoch_us(fetched_at), parser_config_sha256
        FROM meta.run_artifact
        WHERE run_id = ? AND artifact_sha256 = ?
        """,
        [result.run_id, asset.artifact_sha256],
    ).fetchone()
    if link is None:
        raise AdhocPublicationError(
            f"run {result.run_id} did not fetch artifact {asset.artifact_sha256}: there is no "
            "durable meta.run_artifact link, so this run cannot vouch for this artifact"
        )
    link_source, link_dataset, link_fetched_us, link_parser_config = link
    if (link_source, link_dataset) != (asset.source_id, asset.dataset_id):
        raise AdhocPublicationError(
            f"run-artifact link records {link_source}/{link_dataset} but the result claims "
            f"{asset.source_id}/{asset.dataset_id} (source/dataset mismatch)"
        )
    artifact = connection.execute(
        "SELECT source_id, dataset_id FROM meta.artifact WHERE artifact_sha256 = ?",
        [asset.artifact_sha256],
    ).fetchone()
    if artifact is None:
        raise AdhocPublicationError(
            f"artifact {asset.artifact_sha256} is not registered in meta.artifact; the run-artifact "
            f"link {link_source}/{link_dataset} points at bytes the catalog never recorded"
        )
    # Artifact identity is the bytes (catalog/artifacts.py, 17 Sep): ``meta.artifact`` keeps the
    # *first* fetch's source/dataset as context, and the per-run ``meta.run_artifact`` link carries
    # this run's dataset. Requiring the two to be equal made byte-identical content unpublishable
    # under any second series: the same CSV uploaded for a new series key, or re-uploaded after a
    # refused attempt, failed with "not registered under the link's source/dataset" while the run
    # was already recorded as success (observed 20 Sep, Architect drive). The link, verified above
    # against the in-memory result, is the authority for this publication.
    if link_fetched_us != epoch_us(asset.fetched_at):
        raise AdhocPublicationError(
            "asset fetched_at does not match the durable run-artifact link; the in-memory "
            "value is not trusted and the publication is refused"
        )
    if link_parser_config != result.parsed_batch.parser_config_sha256:
        raise AdhocPublicationError(
            "parsed_batch parser_config_sha256 does not match the durable run-artifact link"
        )
    return datetime_from_epoch_us(link_fetched_us)


# ---------------------------------------------------------------- publication


def publish_adhoc_observations(
    connection: duckdb.DuckDBPyConnection,
    result: IngestionResult,
    mappings: list[AdhocObservationMapping],
) -> AdhocPublicationResult:
    """Write the mapped observations of one ingested artifact into ``adhoc.fact_observation``.

    Provenance is taken from ``result`` and cannot be supplied by the caller:
    ``artifact_sha256``, ``schema_version``, ``run_id`` and the ``vintage_id`` derived from
    the artifact digest all come from what the ingestion actually did, and ``fetched_at`` is
    read from the durable ``meta.run_artifact`` link that the pipeline wrote when it fetched
    the artifact -- the in-memory asset must agree with that link or the publication is
    refused. A mapping describes a file's layout; it does not get to say where the data came
    from.

    Everything is validated before a single row is inserted, and the insert runs in one
    transaction, so a mapping that fails halfway leaves nothing behind.

    Re-publishing the same artifact with the same mapping is a no-op. The same identity with a
    *different* value raises :class:`AdhocPublicationConflict` rather than overwriting: a
    revision arriving as a new artifact keeps both rows, and Gold refuses that ambiguity until
    a revision policy exists.
    """

    if not isinstance(mappings, (list, tuple)) or not mappings:
        raise AdhocPublicationError("at least one mapping is required")
    for mapping in mappings:
        if not isinstance(mapping, AdhocObservationMapping):
            raise AdhocPublicationError(
                "every mapping must be an AdhocObservationMapping"
            )
    series_ids = [mapping.series_id for mapping in mappings]
    if len(set(series_ids)) != len(series_ids):
        raise AdhocPublicationError(f"mappings repeat a series_id: {sorted(series_ids)}")

    asset = result.asset
    if asset.source_id != ADHOC_SOURCE_ID:
        raise AdhocPublicationError(
            f"only {ADHOC_SOURCE_ID!r} artifacts may be published here, got "
            f"{asset.source_id!r}"
        )

    batch = result.parsed_batch
    if (asset.source_id, asset.dataset_id, asset.artifact_sha256) != (
        batch.source_id, batch.dataset_id, batch.artifact_sha256
    ):
        raise AdhocPublicationError("asset and parsed_batch identities do not match")
    try:
        config_from_metadata(asset.metadata)
    except (FormatError, TypeError, ValueError) as exc:
        raise AdhocPublicationError("asset parser configuration is invalid") from exc
    if batch.parser_config_sha256 != asset.metadata["parser_config_sha256"]:
        raise AdhocPublicationError("asset and parsed_batch parser configuration identities do not match")
    if not result.run_id:
        raise AdhocPublicationError("run_id is required")
    run = connection.execute(
        "SELECT source_id, dataset_id, status FROM meta.run WHERE run_id = ?",
        [result.run_id],
    ).fetchone()
    if run is None or run[:2] != (asset.source_id, asset.dataset_id) or run[2] not in {"success", "warning"}:
        raise AdhocPublicationError("run must exist, match source/dataset and have completed successfully")
    durable_fetched_at = _verified_run_artifact_fetched_at(connection, result)
    requests = connection.execute(
        "SELECT request_metadata_json FROM meta.artifact_request WHERE artifact_sha256 = ?",
        [asset.artifact_sha256],
    ).fetchall()
    request_metadata = [json.loads(row[0]) for row in requests]
    if not any(
        metadata.get("parser_config") == asset.metadata["parser_config"]
        and metadata.get("parser_config_sha256") == batch.parser_config_sha256
        for metadata in request_metadata
    ):
        raise AdhocPublicationError("parser configuration is absent from durable artifact request provenance")
    try:
        if read_identity(result.bronze_path) != identity_for(batch):
            raise AdhocPublicationError("Bronze identity does not match asset and parsed_batch")
        frame = ParquetStorage.read(result.bronze_path)
    except AdhocPublicationError:
        raise
    except Exception as exc:
        raise AdhocPublicationError("durable Bronze file could not be read or verified") from exc
    # Quality comes from durable ingestion warnings, never a mutable in-memory list.
    warnings = connection.execute(
        "SELECT count(*) FROM meta.ingest_warning WHERE run_id = ? AND artifact_sha256 = ?",
        [result.run_id, asset.artifact_sha256],
    ).fetchone()[0]
    quality_default = "source_warning" if warnings else "ok"
    vintage_id = f"artifact:{asset.artifact_sha256}"

    rows: list[list[Any]] = []
    for mapping in mappings:
        frequency, unit, measure_type = _catalog_semantics(
            connection, mapping.series_id, asset.dataset_id
        )

        # Column names are looked up in the frame, never interpolated into SQL.
        required = [mapping.observation_date_column, mapping.value_column]
        if mapping.entity_id_column:
            required.append(mapping.entity_id_column)
        missing = [name for name in required if name not in frame.columns]
        if missing:
            raise AdhocPublicationError(
                f"{mapping.series_id}: column(s) {missing} are not in the parsed table, which "
                f"holds {list(frame.columns)}"
            )

        seen: set[tuple[str | None, date]] = set()
        for row_number, (_, row) in enumerate(frame.iterrows()):
            observation_date = _parse_date(
                row[mapping.observation_date_column], mapping, row_number
            )
            value = _parse_value(row[mapping.value_column], mapping, row_number)
            entity_id = (
                _entity(row[mapping.entity_id_column])
                if mapping.entity_id_column
                else None
            )

            identity = (entity_id, observation_date)
            if identity in seen:
                raise AdhocPublicationError(
                    f"{mapping.series_id}: {observation_date} appears more than once for "
                    f"entity {entity_id!r} in one artifact; a single file cannot state two "
                    "readings for one period"
                )
            seen.add(identity)

            rows.append(
                [
                    mapping.series_id,
                    entity_id,
                    observation_date,
                    None,
                    None,
                    value,
                    frequency,
                    unit,
                    measure_type,
                    "missing_value" if value is None else quality_default,
                    ADHOC_SOURCE_ID,
                    asset.dataset_id,
                    asset.artifact_sha256,
                    durable_fetched_at,
                    result.parsed_batch.schema_version,
                    vintage_id,
                    result.run_id,
                ]
            )

    if not rows:
        raise AdhocPublicationError("the mappings produced no observations")

    return _insert(connection, rows, tuple(series_ids), asset.artifact_sha256)


def _insert(
    connection: duckdb.DuckDBPyConnection,
    rows: list[list[Any]],
    series_ids: tuple[str, ...],
    artifact_sha256: str,
) -> AdhocPublicationResult:
    """Insert what is new, refuse what conflicts, ignore what is already identical."""

    written = 0
    unchanged = 0
    placeholders = ", ".join("?" for _ in FACT_COLUMNS)

    connection.execute("BEGIN TRANSACTION")
    try:
        for row in rows:
            series_id, entity_id, observation_date, value = row[0], row[1], row[2], row[5]
            existing = connection.execute(
                f"""
                SELECT value
                FROM {ADHOC_RELATION}
                WHERE series_id = ?
                  AND entity_id IS NOT DISTINCT FROM ?
                  AND observation_date = ?
                  AND artifact_sha256 = ?
                """,
                [series_id, entity_id, observation_date, artifact_sha256],
            ).fetchone()
            if existing is not None:
                stored = existing[0]
                same = (stored is None and value is None) or (
                    stored is not None and value is not None and float(stored) == float(value)
                )
                if same:
                    unchanged += 1
                    continue
                raise AdhocPublicationConflict(
                    f"{series_id}: {observation_date} already holds {stored!r} for this "
                    f"artifact and the new value is {value!r}; an artifact is immutable, so "
                    "this is a mapping mistake rather than a revision"
                )
            connection.execute(
                f"INSERT INTO {ADHOC_RELATION} ({', '.join(FACT_COLUMNS)}) "
                f"VALUES ({placeholders})",
                row,
            )
            written += 1
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    return AdhocPublicationResult(
        rows_written=written,
        rows_unchanged=unchanged,
        series_ids=series_ids,
        artifact_sha256=artifact_sha256,
    )


__all__ = [
    "ADHOC_RELATION",
    "ADHOC_SOURCE_ID",
    "FACT_COLUMNS",
    "AdhocObservationMapping",
    "AdhocPublicationConflict",
    "AdhocPublicationError",
    "AdhocPublicationResult",
    "publish_adhoc_observations",
]
