"""Gold metric catalog: validate Git-versioned YAML naming the tables ``gold`` may build.

Gold stays a set of **functions**; a materialized table is a *named, reviewed call* of one
of them. Which calls deserve a table is a human decision, so it lives where the series
semantics live: in YAML under ``catalog/gold/``, reviewed and versioned in Git. Nothing here
infers a metric from data, and nothing here lets a metric override how numbers combine --
the function still reads ``meta.series`` at build time.

Loading rules mirror the series catalog on purpose:

- **All files are validated before anything is built.** One bad file aborts the load.
- **A missing or empty directory is an error**, not an empty catalog; turning the Gold
  catalog off is spelled ``catalog_root=None`` by the caller.
- **Duplicate metric ids across files are rejected.**
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml

from ..contracts.identifiers import validate_series_id
from .periods import TARGET_FREQUENCIES

GOLD_CATALOG_SCHEMA_VERSION: Final[str] = "1.0"
"""Metric catalog file format version this loader understands."""

DEFAULT_GOLD_CATALOG_ROOT: Final[Path] = (
    Path(__file__).resolve().parents[3] / "catalog" / "gold"
)
"""``lakehouse-core/catalog/gold`` -- the Git-versioned metric catalog."""

GOLD_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {"align_frequency", "decompose_cumulative", "join_on_period"}
)
"""The only functions a metric may name. Anything else is not a Gold transformation."""

_METRIC_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
"""``gold.<metric_id>`` must be a plain identifier so the table name is never quoted."""


class GoldCatalogError(ValueError):
    """The metric catalog is malformed, inconsistent, or missing."""


@dataclass(frozen=True)
class GoldMetricRecord:
    """One reviewed metric: which function, over which series, onto which period."""

    metric_id: str
    function: str
    series_ids: tuple[str, ...]
    target_frequency: str | None
    name_tr: str
    description: str
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    allow_unverified_semantics: bool = False
    unverified_reason: str | None = None
    content_sha256: str = field(default="", compare=False)

    @property
    def table_name(self) -> str:
        return f"gold.{self.metric_id}"

    def payload(self) -> dict[str, Any]:
        """The semantic payload whose hash tells "same metric" from "changed metric"."""

        return {
            "metric_id": self.metric_id,
            "function": self.function,
            "series_ids": list(self.series_ids),
            "target_frequency": self.target_frequency,
            "name_tr": self.name_tr,
            "description": self.description,
            "aliases": list(self.aliases),
            "tags": list(self.tags),
            "allow_unverified_semantics": self.allow_unverified_semantics,
            "unverified_reason": self.unverified_reason,
        }


def _content_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _text(value: Any, field_name: str, where: str, *, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise GoldCatalogError(f"{where}: '{field_name}' is required")
        return None
    if not isinstance(value, str) or not value.strip():
        raise GoldCatalogError(f"{where}: '{field_name}' must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field_name: str, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise GoldCatalogError(f"{where}: '{field_name}' must be a list of non-empty strings")
    return tuple(v.strip() for v in value)


def _parse_metric(entry: dict[str, Any], where: str) -> GoldMetricRecord:
    metric_id = _text(entry.get("metric_id"), "metric_id", where) or ""
    if not _METRIC_ID_RE.fullmatch(metric_id):
        raise GoldCatalogError(
            f"{where}: metric_id {metric_id!r} must match {_METRIC_ID_RE.pattern} so that "
            "gold.<metric_id> is a plain table name"
        )
    where = f"{where} [{metric_id}]"

    function = _text(entry.get("function"), "function", where) or ""
    if function not in GOLD_FUNCTIONS:
        raise GoldCatalogError(
            f"{where}: function {function!r} is not one of {sorted(GOLD_FUNCTIONS)}"
        )

    series_ids = _string_list(entry.get("series_ids"), "series_ids", where)
    if not series_ids:
        raise GoldCatalogError(f"{where}: 'series_ids' must name at least one series")
    for series_id in series_ids:
        try:
            validate_series_id(series_id)
        except ValueError as exc:
            raise GoldCatalogError(f"{where}: series_ids entry {series_id!r}: {exc}") from exc
    if len(set(series_ids)) != len(series_ids):
        raise GoldCatalogError(f"{where}: 'series_ids' contains duplicates")
    if function in {"align_frequency", "decompose_cumulative"} and len(series_ids) != 1:
        raise GoldCatalogError(f"{where}: {function} takes exactly one series")
    if function == "join_on_period" and len(series_ids) < 2:
        raise GoldCatalogError(f"{where}: join_on_period needs at least two series")

    target = _text(entry.get("target_frequency"), "target_frequency", where, required=False)
    if function == "decompose_cumulative":
        if target is not None:
            raise GoldCatalogError(
                f"{where}: decompose_cumulative keeps the source frequency; "
                "'target_frequency' must be absent"
            )
    else:
        if target is None:
            raise GoldCatalogError(f"{where}: '{function}' requires 'target_frequency'")
        if target not in TARGET_FREQUENCIES:
            raise GoldCatalogError(
                f"{where}: target_frequency {target!r} is not one of {TARGET_FREQUENCIES}"
            )

    allow = entry.get("allow_unverified_semantics", False)
    if not isinstance(allow, bool):
        raise GoldCatalogError(f"{where}: 'allow_unverified_semantics' must be a real bool")
    reason = _text(entry.get("unverified_reason"), "unverified_reason", where, required=False)
    if allow and reason is None:
        raise GoldCatalogError(
            f"{where}: allow_unverified_semantics=true needs 'unverified_reason' -- the "
            "consent the Gold contract asks a human for must be written down"
        )
    if reason is not None and not allow:
        raise GoldCatalogError(
            f"{where}: 'unverified_reason' is set but allow_unverified_semantics is false"
        )

    record = GoldMetricRecord(
        metric_id=metric_id,
        function=function,
        series_ids=series_ids,
        target_frequency=target,
        name_tr=_text(entry.get("name_tr"), "name_tr", where) or "",
        description=_text(entry.get("description"), "description", where) or "",
        aliases=_string_list(entry.get("aliases"), "aliases", where),
        tags=_string_list(entry.get("tags"), "tags", where),
        allow_unverified_semantics=allow,
        unverified_reason=reason,
    )
    return GoldMetricRecord(
        **{**record.__dict__, "content_sha256": _content_sha256(record.payload())}
    )


def parse_gold_catalog_file(path: Path) -> list[GoldMetricRecord]:
    """Parse and validate one metric catalog file."""

    where = str(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise GoldCatalogError(f"{where}: invalid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise GoldCatalogError(f"{where}: top level must be a mapping")
    version = document.get("gold_catalog_schema_version")
    if str(version) != GOLD_CATALOG_SCHEMA_VERSION:
        raise GoldCatalogError(
            f"{where}: gold_catalog_schema_version must be {GOLD_CATALOG_SCHEMA_VERSION!r}, "
            f"got {version!r}"
        )
    metrics = document.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise GoldCatalogError(f"{where}: 'metrics' must be a non-empty list")
    records: list[GoldMetricRecord] = []
    for position, entry in enumerate(metrics):
        if not isinstance(entry, dict):
            raise GoldCatalogError(f"{where}: metrics[{position}] must be a mapping")
        records.append(_parse_metric(entry, f"{where} metrics[{position}]"))
    return records


def load_gold_catalog_files(
    root: Path = DEFAULT_GOLD_CATALOG_ROOT,
) -> list[GoldMetricRecord]:
    """Parse every metric file under ``root`` and reject duplicates across files."""

    if not root.exists():
        raise GoldCatalogError(
            f"gold catalog directory {root} does not exist; a deployment without a metric "
            "catalog builds no Gold tables on purpose, not by accident"
        )
    if not root.is_dir():
        raise GoldCatalogError(f"gold catalog path {root} is not a directory")
    paths = sorted(root.glob("*.yml"))
    if not paths:
        raise GoldCatalogError(f"gold catalog directory {root} contains no .yml files")

    records: list[GoldMetricRecord] = []
    origin: dict[str, Path] = {}
    for path in paths:
        for record in parse_gold_catalog_file(path):
            if record.metric_id in origin:
                raise GoldCatalogError(
                    f"{path}: metric_id {record.metric_id!r} already defined in "
                    f"{origin[record.metric_id]}"
                )
            origin[record.metric_id] = path
            records.append(record)
    return records


__all__ = [
    "DEFAULT_GOLD_CATALOG_ROOT",
    "GOLD_CATALOG_SCHEMA_VERSION",
    "GOLD_FUNCTIONS",
    "GoldCatalogError",
    "GoldMetricRecord",
    "load_gold_catalog_files",
    "parse_gold_catalog_file",
]
