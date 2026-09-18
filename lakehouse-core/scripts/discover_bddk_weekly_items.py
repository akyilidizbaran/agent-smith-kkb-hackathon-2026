"""Discover every BDDK weekly bulletin item and its positional chart address, live.

``docs/sources/bddk_weekly.md`` records one verified mapping: stable item id ``5690``
("a) Konut") is reached with the positional chart address ``1.0.4``, read out of one
rendered report. That mapping was "observed once, not proven stable", which is why
``scripts/ingestion_registry.py`` keeps a hand-written ``_WEEKLY_VERIFIED_POSITIONS``
dict: every new weekly series needed its own manual observation.

This script removes the manual step. The time-series endpoint answers **every** request
with a ``Baslik`` field carrying the item's own label, and an address that addresses
nothing answers with the placeholder ``Grafik Başlığı``. So the address space can be
enumerated and each hit verified against the label the source itself returns:

    <table>.0.<row>   table 1..N, row 1..M, both discovered by probing until a placeholder

The advanced page's item tree (``KalemToggle(<stable id>, '<label>')``) supplies the
stable item ids. Matching the two by label yields ``stable id -> positional address``
**with the source's own label as the evidence**, which is exactly what the registry's
``expected_measure_label`` guard checks at fetch time. A label that appears twice in one
table is reported rather than guessed.

Usage (from lakehouse-core/):

    uv run python scripts/discover_bddk_weekly_items.py                 # print a report
    uv run python scripts/discover_bddk_weekly_items.py --json out.json # machine-readable

Requests are paced; a full sweep is roughly 250 requests.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import requests

BASE_URL = "https://www.bddk.org.tr"
TREE_PATH = "/BultenHaftalik/tr/Gelismis"
SERIES_PATH = "/BultenHaftalik/tr/Gelismis/KiyaslamaJsonGetir"

PLACEHOLDER_TITLE = "grafik başlığı"
"""What the endpoint answers when the positional address addresses no item."""

_TREE_ITEM = re.compile(r"KalemToggle\((\d+),\s*'([^']*)'")

# One short week keeps every probe response small; the values are never read here.
PROBE_START = "2.01.2026 00:00:00"
PROBE_END = "9.01.2026 00:00:00"


def _normalize(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


@dataclass(frozen=True)
class Item:
    """One discovered weekly item: where it lives and what the source calls it."""

    chart_id: str
    table: int
    row: int
    source_label: str
    stable_item_id: str | None
    tree_label: str | None


class WeeklyExplorer:
    def __init__(self, session: requests.Session, *, pause: float = 0.2) -> None:
        self._session = session
        self._pause = pause
        self.requests_made = 0

    def tree(self) -> list[tuple[str, str]]:
        """Stable item ids and labels, in the order the advanced page renders them."""

        response = self._session.get(f"{BASE_URL}{TREE_PATH}", timeout=60)
        response.raise_for_status()
        self.requests_made += 1
        return [
            (match.group(1), html.unescape(match.group(2)).strip())
            for match in _TREE_ITEM.finditer(response.text)
        ]

    def title_at(self, chart_id: str) -> str | None:
        """Return the item's own label for this address, or None if it addresses nothing."""

        response = self._session.post(
            f"{BASE_URL}{SERIES_PATH}",
            data={
                "dil": "tr",
                "baslangicTarihi": PROBE_START,
                "bitisTarihi": PROBE_END,
                "id": chart_id,
                "parabirimi": "TRY",
                "sutun": "3",
                "tarafKodu": "10001",
            },
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
            timeout=60,
        )
        self.requests_made += 1
        time.sleep(self._pause)
        if response.status_code != 200:
            return None
        try:
            title = response.json().get("Baslik")
        except ValueError:
            return None
        if title is None or _normalize(title).startswith(PLACEHOLDER_TITLE):
            return None
        return str(title).strip()

    def sweep(self, *, max_tables: int = 30, max_rows: int = 80) -> list[Item]:
        """Enumerate every (table, row) address until each axis stops answering."""

        found: list[Item] = []
        for table in range(1, max_tables + 1):
            if self.title_at(f"{table}.0.1") is None:
                break
            for row in range(1, max_rows + 1):
                title = self.title_at(f"{table}.0.{row}")
                if title is None:
                    break
                found.append(Item(f"{table}.0.{row}", table, row, title, None, None))
        return match_tree(found, self.tree())


def item_name(source_label: str) -> str:
    """The item's own name, without the currency and column legs the title appends.

    ``"a) Konut (TRY) [Toplam]"`` -> ``"a) Konut"``.
    """

    return re.split(r"\s*\((?:TRY|TL|USD|EUR)\)", source_label)[0].strip()


def match_tree(items: list[Item], tree: list[tuple[str, str]]) -> list[Item]:
    """Attach stable item ids by matching each table's rows inside that table's tree window.

    Two facts make a naive match wrong. Labels repeat **across** tables — "a) Konut" is a
    credit balance in table 1 and a non-performing balance in table 2 — so a global label
    lookup is ambiguous. And the chart lists a table's rows flat while the tree nests them,
    so the two orders differ **within** a table and a sequential walk derails.

    What does hold: the tree presents the tables in the same order the chart numbers them.
    So each table's rows are located in the tree first (its window runs from its own first
    row's label to the next table's), and inside that window a label is unique, which makes
    label matching exact. A row whose label is absent from the window (the chart renders a
    few rows the tree has no toggle for) is left unmatched rather than paired with a
    neighbour.
    """

    normalized_tree = [(stable_id, label, _normalize(label)) for stable_id, label in tree]
    by_table: dict[int, list[Item]] = {}
    for item in items:
        by_table.setdefault(item.table, []).append(item)
    tables = sorted(by_table)

    anchors: dict[int, int] = {}
    search_from = 0
    for table in tables:
        first = _normalize(item_name(by_table[table][0].source_label))
        anchor = next(
            (
                index
                for index in range(search_from, len(normalized_tree))
                if normalized_tree[index][2] == first
            ),
            None,
        )
        if anchor is None:
            continue
        anchors[table] = anchor
        search_from = anchor + 1

    matched: list[Item] = []
    for position, table in enumerate(tables):
        start = anchors.get(table)
        if start is None:
            matched.extend(by_table[table])
            continue
        following = [anchors[t] for t in tables[position + 1 :] if t in anchors]
        end = following[0] if following else len(normalized_tree)

        window: dict[str, list[tuple[str, str]]] = {}
        for stable_id, label, normalized in normalized_tree[start:end]:
            window.setdefault(normalized, []).append((stable_id, label))

        # A label can repeat inside one table: "b) Taşıt" is both a consumer loan and a
        # commercial one. Both listings order those repeats the same way (they hang off
        # successive parents), so the n-th occurrence in the chart is the n-th in the tree.
        seen: dict[str, int] = {}
        for item in by_table[table]:
            key = _normalize(item_name(item.source_label))
            occurrence = seen.get(key, 0)
            seen[key] = occurrence + 1
            candidates = window.get(key, [])
            if occurrence < len(candidates):
                stable_id, tree_label = candidates[occurrence]
                matched.append(
                    Item(
                        item.chart_id,
                        item.table,
                        item.row,
                        item.source_label,
                        stable_id,
                        tree_label,
                    )
                )
            else:
                matched.append(item)
    return matched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None, help="write the full map here")
    parser.add_argument("--pause", type=float, default=0.2, help="seconds between requests")
    parser.add_argument("--filter", default=None, help="only report labels matching this regex")
    args = parser.parse_args()

    explorer = WeeklyExplorer(requests.Session(), pause=args.pause)
    items = explorer.sweep()

    matched = [item for item in items if item.stable_item_id]
    print(f"{len(items)} adres yanıtladı · {len(matched)} tanesi ağaçtaki tek bir kalemle eşleşti")
    print(f"{explorer.requests_made} istek yapıldı\n")

    pattern = re.compile(args.filter, re.IGNORECASE) if args.filter else None
    print(f"{'adres':>10}  {'kalem':>6}  etiket")
    for item in items:
        if pattern and not pattern.search(item.source_label):
            continue
        print(f"{item.chart_id:>10}  {item.stable_item_id or '—':>6}  {item.source_label[:66]}")

    if args.json:
        args.json.write_text(
            json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n{len(items)} kayıt yazıldı -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
