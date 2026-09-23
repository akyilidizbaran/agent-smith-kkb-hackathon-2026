"""Semantic series catalog: validate Git-versioned YAML and load it into ``meta.series``.

The catalog is the human-authored half of the metadata story. ``meta.artifact``,
``meta.run`` and ``meta.dataset_version`` record what an ingestion actually did and are
written automatically; ``meta.series`` records what a series *means* and is only ever written
from ``catalog/series/*.yml``, which is reviewed and versioned in Git.

Loading rules that matter:

- **All files are validated before anything is written.** A single bad file aborts the whole
  load, so a partially-applied catalog is not a reachable state.
- **The load runs in one transaction**, so an error mid-write rolls back.
- **Re-loading an unchanged catalog is a no-op.** Each record carries a content hash of its
  semantic payload; a row whose hash is unchanged is left alone, so ``updated_at`` does not
  churn on every bootstrap.
- **``first_obs`` and ``last_obs`` are never written by the loader.** They describe observed
  coverage, are computed operationally, and are not the catalog's business.
- **Rows this catalog did not author are never deleted.** The loader upserts what it knows
  about and leaves everything else alone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import duckdb
import yaml

from ..contracts.identifiers import validate_dataset_id, validate_series_id, validate_source_id
from .relations import SeriesRelationRecord, infer_series_relations


CATALOG_SCHEMA_VERSION = "1.0"
"""Catalog file format version this loader understands."""

_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
"""Safe YAML loader; libyaml's C implementation when PyYAML was built with it.

Same safe subset as ``yaml.safe_load``. The catalog is ~150k lines, and every database
bootstrap parses all of it: measured 8,8 s pure Python vs 1,3 s with libyaml on 6.692
entries. The test suite bootstraps hundreds of databases, so this is what keeps a CI run
inside its time limit as the catalog grows.
"""

DEFAULT_CATALOG_ROOT = Path(__file__).resolve().parents[3] / "catalog" / "series"
"""``lakehouse-core/catalog/series`` — the Git-versioned catalog source of truth."""


MEASURE_TYPES = frozenset(
    {
        "stock",
        "flow_periodic",
        "flow_ytd",
        "flow_cumulative",
        "rate",
        "ratio",
        "index",
        "count",
        "unknown",
    }
)
"""Matches ``schemas/fact_observation.yml``'s ``measure_type_vocabulary``."""

SEMANTIC_CONFIDENCES = frozenset({"verified", "derived", "unknown"})

SEMANTIC_SOURCES = frozenset({"manual", "source_docs", "source_service", "profiler"})
"""How the semantics were established.

``manual``, ``source_docs`` and ``profiler`` are the agent layer's requested vocabulary.
``source_service`` is added for metadata the source itself declares through an API (EVDS's
``serieList``), which is stronger evidence than a human reading a document.
"""

FREQUENCIES = frozenset(
    {
        "daily",
        "business_daily",
        "weekly",
        "biweekly",
        "monthly",
        "quarterly",
        "semiannual",
        "yearly",
    }
)
"""Catalog frequency vocabulary.

Covers the EVDS frequency list; the shared terms match the vocabulary the agent layer
asked for in ``LAKEHOUSE_BUILD_PLAN.md`` (``daily|weekly|monthly|quarterly|yearly``).
"""

WEEK_ANCHORS = frozenset(
    {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
)

AGGREGATIONS = frozenset({"avg", "sum", "min", "max", "first", "last"})
"""EVDS's own aggregation vocabulary, reused so a source-declared value maps directly."""

CUMULATIVE_RESETS = frozenset({"yearly", "none"})
"""``since_inception`` is deliberately absent: that case is ``measure_type=flow_cumulative``,
so encoding it twice would let the two disagree."""

STATUSES = frozenset({"active", "deprecated", "draft"})

_REQUIRED_FIELDS = (
    "series_id",
    "native_code",
    "name_tr",
    "description",
    "frequency",
    "measure_type",
    "semantic_confidence",
    "semantic_source",
)

_SEMANTIC_PAYLOAD_FIELDS = (
    "series_id",
    "source_id",
    "native_code",
    "dataset_id",
    "name_tr",
    "description",
    "aliases",
    "tags",
    "frequency",
    "week_anchor",
    "unit",
    "measure_type",
    "default_agg",
    "cumulative_reset",
    "semantic_confidence",
    "semantic_source",
    "metadata_url",
    "status",
)
"""Fields whose change means the catalog record changed. Excludes first_obs/last_obs."""


class CatalogError(ValueError):
    """A catalog file is invalid. Raised before anything is written."""


@dataclass(frozen=True)
class SeriesRecord:
    """One validated catalog entry, ready to upsert into ``meta.series``."""

    series_id: str
    source_id: str
    native_code: str
    dataset_id: str | None
    name_tr: str
    description: str
    aliases: list[str]
    tags: list[str]
    frequency: str
    week_anchor: str | None
    unit: str | None
    measure_type: str
    default_agg: str | None
    cumulative_reset: str | None
    semantic_confidence: str
    semantic_source: str
    metadata_url: str | None
    status: str
    content_sha256: str = field(compare=False, default="")

    def payload(self) -> dict[str, Any]:
        """Return the semantic payload used for the content hash."""

        return {name: getattr(self, name) for name in _SEMANTIC_PAYLOAD_FIELDS}


def _content_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _text(value: Any) -> str | None:
    """Normalize a scalar to a stripped string, mapping blank and null to ``None``."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any, field_name: str, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CatalogError(f"{where}: '{field_name}' must be a list")
    items: list[str] = []
    for item in value:
        text = _text(item)
        if text is None:
            raise CatalogError(f"{where}: '{field_name}' must not contain blank entries")
        items.append(text)
    if len(set(items)) != len(items):
        raise CatalogError(f"{where}: '{field_name}' contains duplicate entries")
    return items


def _enum(value: Any, allowed: frozenset[str], field_name: str, where: str) -> str:
    text = _text(value)
    if text is None:
        raise CatalogError(f"{where}: '{field_name}' must not be empty")
    if text not in allowed:
        raise CatalogError(
            f"{where}: '{field_name}' value {text!r} is not one of "
            f"{sorted(allowed)}"
        )
    return text


def _optional_enum(
    value: Any, allowed: frozenset[str], field_name: str, where: str
) -> str | None:
    text = _text(value)
    if text is None:
        return None
    if text not in allowed:
        raise CatalogError(
            f"{where}: '{field_name}' value {text!r} is not one of {sorted(allowed)}"
        )
    return text


def parse_catalog_file(path: Path) -> list[SeriesRecord]:
    """Parse and fully validate one catalog file. Raises before producing partial output."""

    try:
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=_YAML_LOADER)
    except yaml.YAMLError as exc:
        raise CatalogError(f"{path.name}: file is not valid YAML: {exc}") from exc
    except OSError as exc:
        raise CatalogError(f"{path.name}: file could not be read: {exc}") from exc

    if not isinstance(document, dict):
        raise CatalogError(f"{path.name}: top level must be a mapping")

    version = _text(document.get("catalog_schema_version"))
    if version != CATALOG_SCHEMA_VERSION:
        raise CatalogError(
            f"{path.name}: catalog_schema_version must be {CATALOG_SCHEMA_VERSION!r}, "
            f"got {version!r}"
        )

    source_id = _text(document.get("source_id"))
    if source_id is None:
        raise CatalogError(f"{path.name}: 'source_id' is required")
    try:
        validate_source_id(source_id)
    except ValueError as exc:
        raise CatalogError(f"{path.name}: {exc}") from exc

    entries = document.get("series")
    if not isinstance(entries, list) or not entries:
        raise CatalogError(f"{path.name}: 'series' must be a non-empty list")

    records: list[SeriesRecord] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"{path.name}[{index}]"
        if not isinstance(entry, dict):
            raise CatalogError(f"{where}: each series entry must be a mapping")
        record = _parse_entry(entry, source_id, where)
        if record.series_id in seen:
            raise CatalogError(f"{where}: duplicate series_id {record.series_id!r}")
        seen.add(record.series_id)
        records.append(record)
    return records


def _parse_entry(entry: dict[str, Any], source_id: str, where: str) -> SeriesRecord:
    unknown_keys = set(entry) - set(_SEMANTIC_PAYLOAD_FIELDS)
    if unknown_keys:
        raise CatalogError(f"{where}: unsupported field(s) {sorted(unknown_keys)}")

    for name in _REQUIRED_FIELDS:
        if _text(entry.get(name)) is None:
            raise CatalogError(f"{where}: '{name}' is required and must not be empty")

    series_id = str(entry["series_id"]).strip()
    try:
        validate_series_id(series_id, source_id)
    except ValueError as exc:
        raise CatalogError(f"{where}: {exc}") from exc

    if "source_id" in entry and _text(entry["source_id"]) != source_id:
        raise CatalogError(
            f"{where}: entry source_id {_text(entry['source_id'])!r} does not match the "
            f"file's source_id {source_id!r}"
        )

    dataset_id = _text(entry.get("dataset_id"))
    if dataset_id is not None:
        try:
            validate_dataset_id(dataset_id)
        except ValueError as exc:
            raise CatalogError(f"{where}: {exc}") from exc

    frequency = _enum(entry.get("frequency"), FREQUENCIES, "frequency", where)
    week_anchor = _optional_enum(entry.get("week_anchor"), WEEK_ANCHORS, "week_anchor", where)
    measure_type = _enum(entry.get("measure_type"), MEASURE_TYPES, "measure_type", where)
    default_agg = _optional_enum(entry.get("default_agg"), AGGREGATIONS, "default_agg", where)
    cumulative_reset = _optional_enum(
        entry.get("cumulative_reset"), CUMULATIVE_RESETS, "cumulative_reset", where
    )
    semantic_confidence = _enum(
        entry.get("semantic_confidence"), SEMANTIC_CONFIDENCES, "semantic_confidence", where
    )
    semantic_source = _enum(
        entry.get("semantic_source"), SEMANTIC_SOURCES, "semantic_source", where
    )
    status = _optional_enum(entry.get("status"), STATUSES, "status", where) or "active"
    unit = _text(entry.get("unit"))

    # --- cross-field rules -------------------------------------------------------------
    if frequency == "weekly" and week_anchor is None:
        raise CatalogError(
            f"{where}: weekly series must declare 'week_anchor'; without it the week's "
            "period end is undefined"
        )
    if frequency != "weekly" and week_anchor is not None:
        raise CatalogError(
            f"{where}: 'week_anchor' is only meaningful for weekly series, but frequency "
            f"is {frequency!r}"
        )

    if measure_type == "flow_ytd":
        if cumulative_reset is None:
            raise CatalogError(
                f"{where}: flow_ytd requires 'cumulative_reset'; decomposing a "
                "year-to-date series without knowing where it resets produces wrong periods"
            )
        if cumulative_reset == "none":
            raise CatalogError(
                f"{where}: flow_ytd cannot declare cumulative_reset='none'; a "
                "year-to-date series resets by definition"
            )
    elif cumulative_reset is not None:
        raise CatalogError(
            f"{where}: 'cumulative_reset' is only meaningful for flow_ytd, but "
            f"measure_type is {measure_type!r}"
        )

    unsafe_agg = semantic_confidence == "unknown" or measure_type == "unknown"
    if unsafe_agg and default_agg is not None:
        raise CatalogError(
            f"{where}: 'default_agg' must not be set when semantic_confidence or "
            "measure_type is 'unknown'; an unclassified series has no safe aggregation"
        )

    if dataset_id is None and status != "draft":
        raise CatalogError(
            f"{where}: a series with no 'dataset_id' has nothing to fetch it and must be "
            f"status 'draft', not {status!r}"
        )

    if semantic_confidence == "verified" and unit is None:
        raise CatalogError(
            f"{where}: semantic_confidence='verified' requires a 'unit'; a series whose "
            "unit is unestablished is at most 'derived'"
        )

    record = SeriesRecord(
        series_id=series_id,
        source_id=source_id,
        native_code=str(entry["native_code"]).strip(),
        dataset_id=dataset_id,
        name_tr=str(entry["name_tr"]).strip(),
        description=str(entry["description"]).strip(),
        aliases=_string_list(entry.get("aliases"), "aliases", where),
        tags=_string_list(entry.get("tags"), "tags", where),
        frequency=frequency,
        week_anchor=week_anchor,
        unit=unit,
        measure_type=measure_type,
        default_agg=default_agg,
        cumulative_reset=cumulative_reset,
        semantic_confidence=semantic_confidence,
        semantic_source=semantic_source,
        metadata_url=_text(entry.get("metadata_url")),
        status=status,
    )
    return SeriesRecord(**{**record.__dict__, "content_sha256": _content_sha256(record.payload())})


def build_series_record(entry: dict[str, Any], source_id: str, *, where: str) -> SeriesRecord:
    """Validate one catalog entry and return it as a record.

    This is the single validation surface for the whole catalog. ``parse_catalog_file`` uses
    it for YAML, and :mod:`lakehouse.catalog.registration` uses it for programmatic drafts, so
    the eighteen rules cannot drift apart between the two paths. ``where`` names the origin in
    error messages -- a file and line for YAML, the caller for a programmatic record.
    """

    return _parse_entry(entry, source_id, where)


def load_catalog_files(root: Path = DEFAULT_CATALOG_ROOT) -> list[SeriesRecord]:
    """Parse every catalog file under ``root`` and reject duplicates across files.

    A missing or empty directory is an **error**, not an empty catalog. Starting with no
    semantics because a path was wrong or a deployment shipped without ``catalog/`` is the
    failure this guards against: every downstream layer would then see ``meta.series`` as
    legitimately empty. Turning the catalog off is spelled ``catalog_root=None``.
    """

    if not root.exists():
        raise CatalogError(
            f"catalog directory {root} does not exist; pass catalog_root=None to load no "
            "catalog on purpose"
        )
    if not root.is_dir():
        raise CatalogError(f"catalog path {root} is not a directory")

    paths = sorted(root.glob("*.yml"))
    if not paths:
        raise CatalogError(
            f"catalog directory {root} contains no .yml files; pass catalog_root=None to "
            "load no catalog on purpose"
        )

    records: list[SeriesRecord] = []
    origin: dict[str, str] = {}
    for path in paths:
        for record in parse_catalog_file(path):
            if record.series_id in origin:
                raise CatalogError(
                    f"{path.name}: series_id {record.series_id!r} is already defined in "
                    f"{origin[record.series_id]}"
                )
            origin[record.series_id] = path.name
            records.append(record)
    return records


@dataclass(frozen=True)
class CatalogLoadResult:
    """What one catalog load changed."""

    inserted: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


def load_series_catalog(
    connection: duckdb.DuckDBPyConnection,
    root: Path = DEFAULT_CATALOG_ROOT,
) -> CatalogLoadResult:
    """Validate every catalog file, then upsert them into ``meta.series`` in one transaction.

    Records whose content hash is unchanged are left untouched, so ``updated_at`` stays put.
    Rows in ``meta.series`` that this catalog does not define are never deleted.
    """

    records = load_catalog_files(root)
    existing = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT series_id, catalog_content_sha256 FROM meta.series"
        ).fetchall()
    }

    inserted = updated = unchanged = 0
    connection.execute("BEGIN TRANSACTION")
    try:
        for record in records:
            current = existing.get(record.series_id)
            if current == record.content_sha256:
                unchanged += 1
                continue
            if current is None:
                _insert(connection, record)
                inserted += 1
            else:
                _update(connection, record)
                updated += 1
        _upsert_series_relations(connection, records)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    return CatalogLoadResult(inserted, updated, unchanged)


_RELATION_WRITE_COLUMNS = (
    "series_id",
    "concept_id",
    "parent_series_id",
    "relation_type",
    "dimension_path",
    "additivity",
    "relation_confidence",
    "relation_source",
    "relation_content_sha256",
)


def _upsert_series_relations(
    connection: duckdb.DuckDBPyConnection,
    rows: list[SeriesRecord] | list[Mapping[str, Any]],
) -> int:
    """Synchronize only changed relation rows, using one prepared batch statement.

    ``bootstrap_database`` is intentionally safe to call from every CLI operation and test.
    The catalog often contains thousands of records, so rewriting every relation on every
    bootstrap would make an unchanged catalog increasingly expensive. The content hash covers
    every persisted semantic field; matching hashes are therefore a safe no-op.
    """

    relations = infer_series_relations(rows)
    if not relations:
        return 0
    existing = dict(
        connection.execute(
            "SELECT series_id, relation_content_sha256 FROM meta.series_relation"
        ).fetchall()
    )
    changed = [
        relation
        for relation in relations
        if existing.get(relation.series_id) != relation.content_sha256
    ]
    if not changed:
        return len(relations)

    # Tek toplu ekleme: satır satır `executemany` + `INSERT OR REPLACE` DuckDB'de süperlineer büyüyor
    # (ölçüldü 22 Eyl, Windows, DuckDB 1.5.5: 100 satır 1,2 sn, 300 satır 5,9 sn; tam katalog 6.694 satır
    # dakikalar → bootstrap çağıran her test/CLI o kadar bekliyordu). Aynı satırlar DataFrame'den 0,2 sn.
    import pandas as pd

    columns = ", ".join(_RELATION_WRITE_COLUMNS)
    sql = (
        f"INSERT OR REPLACE INTO meta.series_relation ({columns}, updated_at) "
        f"SELECT {columns}, current_timestamp FROM changed_relations"
    )
    values = [
        [
            relation.series_id,
            relation.concept_id,
            relation.parent_series_id,
            relation.relation_type,
            list(relation.dimension_path),
            relation.additivity,
            relation.relation_confidence,
            relation.relation_source,
            relation.content_sha256,
        ]
        for relation in changed
    ]
    changed_relations = pd.DataFrame(values, columns=list(_RELATION_WRITE_COLUMNS))
    connection.register("changed_relations", changed_relations)
    try:
        connection.execute(sql)
    finally:
        connection.unregister("changed_relations")
    return len(relations)


_WRITE_COLUMNS = (
    "series_id",
    "source_id",
    "native_code",
    "dataset_id",
    "name_tr",
    "description",
    "aliases",
    "tags",
    "frequency",
    "week_anchor",
    "unit",
    "measure_type",
    "default_agg",
    "cumulative_reset",
    "semantic_confidence",
    "semantic_source",
    "metadata_url",
    "status",
    "catalog_content_sha256",
)
"""Columns the catalog owns. first_obs, last_obs and updated_at are handled separately."""


def _values(record: SeriesRecord) -> list[Any]:
    payload = record.payload()
    return [payload[name] for name in _WRITE_COLUMNS[:-1]] + [record.content_sha256]


def _insert(connection: duckdb.DuckDBPyConnection, record: SeriesRecord) -> None:
    placeholders = ", ".join("?" for _ in _WRITE_COLUMNS)
    connection.execute(
        f"INSERT INTO meta.series ({', '.join(_WRITE_COLUMNS)}, updated_at) "
        f"VALUES ({placeholders}, current_timestamp)",
        _values(record),
    )


def _update(connection: duckdb.DuckDBPyConnection, record: SeriesRecord) -> None:
    # first_obs and last_obs are deliberately absent: they are operational coverage, not
    # catalog content, and the loader must not clear a value someone else computed.
    assignments = ", ".join(f"{name} = ?" for name in _WRITE_COLUMNS[1:])
    connection.execute(
        f"UPDATE meta.series SET {assignments}, updated_at = current_timestamp "
        f"WHERE series_id = ?",
        _values(record)[1:] + [record.series_id],
    )


__all__ = [
    "AGGREGATIONS",
    "build_series_record",
    "CATALOG_SCHEMA_VERSION",
    "CUMULATIVE_RESETS",
    "CatalogError",
    "CatalogLoadResult",
    "DEFAULT_CATALOG_ROOT",
    "FREQUENCIES",
    "MEASURE_TYPES",
    "SEMANTIC_CONFIDENCES",
    "SEMANTIC_SOURCES",
    "STATUSES",
    "SeriesRecord",
    "_upsert_series_relations",
    "WEEK_ANCHORS",
    "load_catalog_files",
    "load_series_catalog",
    "parse_catalog_file",
]
