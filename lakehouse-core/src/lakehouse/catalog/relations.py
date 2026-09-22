"""Canonical relationships between semantic series.

The source catalog describes one series at a time.  That is enough to answer a direct
lookup, but it is not enough to distinguish a total from one of its breakdowns when a
source publishes the same concept in several shapes.  This module turns the per-series
catalog into a small, source-independent relation graph.  Connectors and parsers keep
their existing ``series_id`` contract; the graph is metadata about those ids.

The inference rules are deliberately conservative.  A relationship is recorded only when
the source identity or a stable source naming convention supports it.  Unknown relations
remain ``standalone`` instead of being guessed from an embedding or from a single user
question.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


RELATION_TYPES = frozenset(
    {"standalone", "parent_total", "child_breakdown", "dimension_member", "variant", "derived"}
)
ADDITIVITY = frozenset({"additive", "non_additive", "unknown"})
RELATION_CONFIDENCE = frozenset({"verified", "derived", "unknown"})

# The BDDK item tree is part of the source's stable semantic contract.  The map covers
# the families needed by the demo and the equivalent credit/card families in the live
# weekly bulletin.  Other items are still represented in the graph as standalone series.
_BDDK_MONTHLY_PARENTS: dict[int, tuple[int, ...]] = {
    1533: (1532, 1534, 1535, 1536),
    1539: (1541, 1542),
    1543: (1533, 1539),
    1544: (1545, 1546, 1547, 1548),
}
_BDDK_WEEKLY_PARENTS: dict[int, tuple[int, ...]] = {
    5687: (5688,),
    5688: (5689, 5694),
    5689: (5690, 5691, 5692, 5693),
    5694: (5695, 5696),
    5699: (5700, 5705),
    5700: (5701, 5702, 5703, 5704),
    5705: (5706, 5707),
    5709: (5710, 5711),
}
_ADDITIVE_PARENTS = {
    ("bddk_monthly", 1533),
    ("bddk_monthly", 1539),
    ("bddk_monthly", 1543),
    ("bddk_monthly", 1544),
}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("ı", "i")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "unknown"


def _native_number(value: str) -> int | None:
    match = re.match(r"\s*(\d+)", value)
    return int(match.group(1)) if match else None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


@dataclass(frozen=True)
class SeriesRelationRecord:
    """One canonical relation row, keyed by ``series_id``."""

    series_id: str
    concept_id: str
    parent_series_id: str | None
    relation_type: str
    dimension_path: tuple[str, ...]
    additivity: str
    relation_confidence: str
    relation_source: str
    content_sha256: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "concept_id": self.concept_id,
            "parent_series_id": self.parent_series_id,
            "relation_type": self.relation_type,
            "dimension_path": list(self.dimension_path),
            "additivity": self.additivity,
            "relation_confidence": self.relation_confidence,
            "relation_source": self.relation_source,
        }


@dataclass(frozen=True)
class _Series:
    series_id: str
    source_id: str
    native_code: str
    dataset_id: str | None
    name_tr: str
    description: str
    aliases: tuple[str, ...]
    tags: tuple[str, ...]
    explicit_concept_id: str | None = None
    explicit_parent_series_id: str | None = None
    explicit_relation_type: str | None = None
    explicit_dimension_path: tuple[str, ...] = ()
    explicit_additivity: str | None = None
    explicit_confidence: str | None = None
    explicit_source: str | None = None

    @property
    def number(self) -> int | None:
        return _native_number(self.native_code)


def _coerce(row: Mapping[str, Any] | object) -> _Series:
    def get(name: str, default: Any = None) -> Any:
        if isinstance(row, Mapping):
            return row.get(name, default)
        return getattr(row, name, default)

    return _Series(
        series_id=_text(get("series_id") or get("dataset_id")),
        source_id=_text(get("source_id")),
        native_code=_text(get("native_code")),
        dataset_id=_text(get("dataset_id")) or None,
        name_tr=_text(get("name_tr") or get("name")),
        description=_text(get("description")),
        aliases=tuple(_as_list(get("aliases"))),
        tags=tuple(_as_list(get("tags"))),
        explicit_concept_id=_text(get("concept_id")) or None,
        explicit_parent_series_id=_text(get("parent_series_id")) or None,
        explicit_relation_type=_text(get("relation_type")) or None,
        explicit_dimension_path=tuple(_as_list(get("dimension_path"))),
        explicit_additivity=_text(get("additivity")) or None,
        explicit_confidence=_text(get("relation_confidence")) or None,
        explicit_source=_text(get("relation_source")) or None,
    )


def _monthly_concept(item: _Series) -> str:
    number = item.number
    family = {
        1532: "tuketici_kredileri_doviz_endeksli",
        1533: "tuketici_kredileri",
        1534: "konut_kredileri",
        1535: "tasit_kredileri",
        1536: "ihtiyac_kredileri",
        1539: "bireysel_kredi_kartlari",
        1541: "bireysel_kredi_kartlari",
        1542: "bireysel_kredi_kartlari",
        1543: "tuketici_kredileri_ve_bireysel_kredi_kartlari",
        1544: "takipteki_tuketici_kredileri",
        1545: "takipteki_tuketici_kredileri",
        1546: "takipteki_tuketici_kredileri",
        1547: "takipteki_tuketici_kredileri",
        1548: "takipteki_tuketici_kredileri",
    }.get(number)
    if family:
        return f"bddk_monthly:{family}"
    # Keep unrelated bulletin sections separate.  The source item number prevents two
    # similarly named sections (for example balance sheet and ratios) from collapsing.
    prefix = item.name_tr.split("(", 1)[0].strip().rstrip(",")
    return f"bddk_monthly:{_slug(prefix)}:{number or _slug(item.native_code)}"


def _finturk_metric(item: _Series) -> tuple[str, str | None]:
    tail = item.series_id.split(":", 1)[-1]
    province, separator, metric = tail.partition("_")
    if not separator:
        # The name is the safer fallback for a future native-id format.
        province = item.name_tr.split(",", 1)[1].split("(", 1)[0].strip() if "," in item.name_tr else ""
        metric = item.name_tr.split(",", 1)[0]
    return _slug(metric), (_slug(province) if province else None)


def _evds_dimension(item: _Series) -> tuple[str, ...]:
    # EVDS names use either a region code (TR10) or a human-readable parenthesized
    # region.  Keeping the original text in the dimension path is useful evidence.
    code = item.native_code or item.series_id.split(":", 1)[-1]
    return (f"region={code}",)


def _weekly_core(name: str) -> str:
    text = _slug(name)
    # The suffix identifies the report and frequency rather than the semantic node.
    text = re.sub(r"_krediler_haftalik.*$", "", text)
    text = re.sub(r"_haftalik.*$", "", text)
    text = re.sub(r"^[a-d]_", "", text)
    return text.strip("_")


def _content_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def infer_series_relations(rows: Iterable[Mapping[str, Any] | object]) -> list[SeriesRelationRecord]:
    """Build the relation graph for catalog rows from all four source families.

    Explicit relation fields win.  Source adapters then add only stable relationships:
    BDDK item-tree ids, BDDK weekly parenthesized paths, FinTürk province dimensions and
    EVDS dataset/region dimensions.  The output is deterministic and safe to upsert.
    """

    items = [item for item in (_coerce(row) for row in rows) if item.series_id]
    by_id = {item.series_id: item for item in items}
    parent_by_child: dict[str, str] = {}
    additivity_by_parent: dict[str, str] = {}

    def ids_by_number(source: str, numbers: Iterable[int]) -> dict[int, str]:
        wanted = set(numbers)
        return {item.number: item.series_id for item in items if item.source_id == source and item.number in wanted}

    monthly_numbers = ids_by_number("bddk_monthly", {n for pair in _BDDK_MONTHLY_PARENTS.items() for n in (pair[0], *pair[1])})
    for parent, children in _BDDK_MONTHLY_PARENTS.items():
        parent_id = monthly_numbers.get(parent)
        if not parent_id:
            continue
        for child in children:
            child_id = monthly_numbers.get(child)
            if child_id:
                parent_by_child[child_id] = parent_id
        if ("bddk_monthly", parent) in _ADDITIVE_PARENTS:
            additivity_by_parent[parent_id] = "additive"

    weekly_numbers = ids_by_number("bddk_weekly", {n for pair in _BDDK_WEEKLY_PARENTS.items() for n in (pair[0], *pair[1])})
    for parent, children in _BDDK_WEEKLY_PARENTS.items():
        parent_id = weekly_numbers.get(parent)
        if parent_id:
            for child in children:
                child_id = weekly_numbers.get(child)
                if child_id:
                    parent_by_child[child_id] = parent_id

    # For future weekly additions, use an explicitly written parenthetical path when it
    # names another catalog node exactly.  Longest match wins and avoids shallow matches.
    weekly_items = [item for item in items if item.source_id == "bddk_weekly"]
    for child in weekly_items:
        if child.series_id in parent_by_child:
            continue
        child_core = _weekly_core(child.name_tr)
        candidates = [
            parent for parent in weekly_items
            if parent.series_id != child.series_id
            and len(_weekly_core(parent.name_tr)) >= 12
            and _weekly_core(parent.name_tr) in child_core
        ]
        if candidates:
            parent = max(candidates, key=lambda value: len(_weekly_core(value.name_tr)))
            parent_by_child[child.series_id] = parent.series_id

    # Explicit YAML metadata is authoritative and may add a relation not covered by a
    # source adapter.  It is validated below instead of silently creating dangling edges.
    for item in items:
        if item.explicit_parent_series_id in by_id:
            parent_by_child[item.series_id] = item.explicit_parent_series_id  # type: ignore[assignment]

    concept_by_id: dict[str, str] = {}
    dimension_by_id: dict[str, tuple[str, ...]] = {}
    source_confidence: dict[str, tuple[str, str]] = {}
    for item in items:
        source = item.source_id.lower()
        if item.explicit_concept_id:
            concept = item.explicit_concept_id
        elif source == "bddk_monthly":
            concept = _monthly_concept(item)
        elif source == "bddk_weekly":
            concept = f"bddk_weekly:series:{item.number or _slug(item.name_tr)}"
        elif source == "bddk_finturk":
            metric, province = _finturk_metric(item)
            concept = f"bddk_finturk:{metric}"
            if province:
                dimension_by_id[item.series_id] = (f"province={province}",)
        elif source == "evds":
            concept = f"evds:{item.dataset_id or _slug(item.name_tr)}"
            dimension_by_id[item.series_id] = _evds_dimension(item)
        else:
            concept = f"{source or 'unknown'}:{_slug(item.name_tr)}"
        concept_by_id[item.series_id] = concept
        source_confidence[item.series_id] = (
            item.explicit_confidence or ("verified" if item.explicit_relation_type else "derived"),
            item.explicit_source or ("catalog" if item.explicit_relation_type else "source_adapter"),
        )

    # Weekly tree nodes share the root concept even when a node has no textual parent.
    def root(series_id: str) -> str:
        seen: set[str] = set()
        current = series_id
        while current in parent_by_child and current not in seen:
            seen.add(current)
            current = parent_by_child[current]
        return current

    for item in weekly_items:
        root_item = by_id.get(root(item.series_id))
        if root_item:
            concept_by_id[item.series_id] = f"bddk_weekly:tree:{root_item.number or _slug(root_item.name_tr)}"

    # EVDS groups are dimensions of one indicator when a dataset has multiple series.  A
    # national ``.TR`` series is treated as the parent only for groups that actually have
    # regional children; this avoids inventing parentage for unrelated maturity buckets.
    evds_groups: dict[str, list[_Series]] = {}
    for item in items:
        if item.source_id == "evds":
            evds_groups.setdefault(concept_by_id[item.series_id], []).append(item)
    for group in evds_groups.values():
        national = next((x for x in group if x.native_code.endswith(".TR")), None)
        if national and len(group) > 1:
            for item in group:
                if item.series_id != national.series_id:
                    parent_by_child.setdefault(item.series_id, national.series_id)

    children_by_parent: dict[str, list[str]] = {}
    for child, parent in parent_by_child.items():
        children_by_parent.setdefault(parent, []).append(child)

    out: list[SeriesRelationRecord] = []
    for item in sorted(items, key=lambda value: value.series_id):
        parent = parent_by_child.get(item.series_id)
        explicit_type = item.explicit_relation_type
        if explicit_type and explicit_type not in RELATION_TYPES:
            explicit_type = None
        if explicit_type:
            relation_type = explicit_type
        elif parent:
            relation_type = "child_breakdown"
        elif item.series_id in children_by_parent:
            relation_type = "parent_total"
        elif item.source_id == "bddk_finturk" or (
            item.source_id == "evds" and len(evds_groups.get(concept_by_id[item.series_id], [])) > 1
        ):
            relation_type = "dimension_member"
        else:
            relation_type = "standalone"

        # An EVDS national series and explicitly curated parents are totals; source-derived
        # nodes without a known additive identity remain unknown to prevent silent sums.
        if item.series_id in children_by_parent:
            relation_type = explicit_type or "parent_total"
        additivity = item.explicit_additivity or additivity_by_parent.get(item.series_id, "unknown")
        if additivity not in ADDITIVITY:
            additivity = "unknown"
        confidence, relation_source = source_confidence[item.series_id]
        if confidence not in RELATION_CONFIDENCE:
            confidence = "unknown"
        dimension_path = item.explicit_dimension_path or dimension_by_id.get(item.series_id, ())
        record = SeriesRelationRecord(
            series_id=item.series_id,
            concept_id=concept_by_id[item.series_id],
            parent_series_id=parent,
            relation_type=relation_type,
            dimension_path=tuple(dimension_path),
            additivity=additivity,
            relation_confidence=confidence,
            relation_source=relation_source,
        )
        object.__setattr__(record, "content_sha256", _content_hash(record.payload()))
        out.append(record)
    return out


__all__ = [
    "ADDITIVITY",
    "RELATION_CONFIDENCE",
    "RELATION_TYPES",
    "SeriesRelationRecord",
    "infer_series_relations",
]
