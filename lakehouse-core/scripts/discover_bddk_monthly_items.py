"""Discover every BDDK monthly bulletin item and the columns it can be requested with.

``docs/sources/bddk_monthly.md`` records how a single series is addressed:
``kalemSutun = "<stable item id>?<column>"`` (e.g. ``1534?Toplam``). The 22 catalogued
monthly series were read off the advanced page by hand, one at a time. This script
removes the manual step, because the bulletin publishes both halves of that address:

* ``GET /BultenAylik/tr/Home/Gelismis`` renders the item tree as ``<optgroup>`` (the
  bulletin's own table groups) and ``<option value="<ids>">`` entries. The option value
  carries the item's schema-version ids, newest first (``1534,288,219,238``), and the
  first id is the one this project uses as ``native_code``.
* ``GET /BultenAylik/tr/Home/KalemSutunGetir?kalemNoList=<id>`` answers with the item's
  own name and **its available columns**, each as a complete ``kalemSutun`` value with a
  human label (``1160?Tp`` "TP", ``1160?Toplam`` "Toplam", ``544?Rasyo`` "Rasyo",
  ``1425?KisaVadeliNakdi`` "Kısa Vadeli Nakdi Krediler").

So which columns exist per item is a fact the source states, not something to guess. The
one thing this script does NOT decide is meaning: a column's unit and measure type come
from the table group it belongs to, and that mapping lives in
``scripts/generate_bddk_monthly_catalog.py`` where it can be reviewed.

Usage (from lakehouse-core/):

    uv run python scripts/discover_bddk_monthly_items.py                  # report
    uv run python scripts/discover_bddk_monthly_items.py --json out.json  # machine-readable

One request per item, paced; a full sweep is roughly 600 requests (~3 minutes).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests
import truststore

BASE_URL = "https://www.bddk.org.tr"
TREE_PATH = "/BultenAylik/tr/Home/Gelismis"
COLUMNS_PATH = "/BultenAylik/tr/Home/KalemSutunGetir"
USER_AGENT = "kkb-lakehouse/0.1 (KKB Hackathon 2026)"

SKIP_GROUPS = {
    # Not bulletin items: this optgroup holds the party (taraf) selector's own values
    # (10002 "Mevduat", …), which the report form sends as `taraf`, not as `kalemSutun`.
    "Fonksiyon / Sahiplik",
}


@dataclass
class Item:
    """One bulletin line: where it sits, how it is addressed, what columns it offers."""

    group: str
    native_code: str                      # first id in the option value — the stable one
    all_ids: tuple[str, ...]              # every schema-version id the option carries
    option_label: str                     # "<group>-<item>" as the select renders it
    source_name: str = ""                 # the item's own name, from KalemSutunGetir
    columns: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (kalemSutun, label)
    note: str = ""


def session() -> requests.Session:
    """A session that trusts the OS store: BDDK omits an intermediate certificate."""

    truststore.inject_into_ssl()
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def parse_tree(page: str) -> list[Item]:
    """Item tree out of the advanced page's ``<optgroup>``/``<option>`` markup."""

    items: list[Item] = []
    for group, body in re.findall(r'<optgroup label="([^"]*)"[^>]*>(.*?)</optgroup>', page, re.S):
        group = html.unescape(group).strip()
        if group in SKIP_GROUPS:
            continue
        for value, label in re.findall(r'<option value="([^"]*)"[^>]*>(.*?)</option>', body, re.S):
            ids = tuple(part.strip() for part in value.split(",") if part.strip())
            if not ids:
                continue
            items.append(Item(
                group=group,
                native_code=ids[0],
                all_ids=ids,
                option_label=html.unescape(re.sub(r"<[^>]+>", "", label)).strip(),
            ))
    return items


def fill_columns(items: list[Item], client: requests.Session, *, pause: float = 0.15) -> None:
    """Ask the source which columns each item offers; record its own name alongside."""

    for index, item in enumerate(items, start=1):
        try:
            response = client.get(
                f"{BASE_URL}{COLUMNS_PATH}",
                params={"kalemNoList": list(item.all_ids)},
                timeout=60,
            )
            response.raise_for_status()
            nodes = response.json()
        except Exception as exc:  # noqa: BLE001 — a failure is recorded, never guessed around
            item.note = f"sütunlar alınamadı: {type(exc).__name__}: {exc}"
            continue

        node = next((n for n in nodes if str(n.get("id")) == item.native_code), None)
        if node is None:
            item.note = f"yanıtta {item.native_code} düğümü yok"
            continue
        item.source_name = str(node.get("text") or "").strip()
        item.columns = tuple(
            (str(child.get("id")), str(child.get("text") or "").strip())
            for child in (node.get("items") or [])
            if child.get("id")
        )
        if not item.columns:
            item.note = "kaynak bu kalem için sütun bildirmiyor"
        if index % 50 == 0:
            print(f"  … {index}/{len(items)} kalem", file=sys.stderr)
        time.sleep(pause)


def report(items: list[Item]) -> None:
    by_group: dict[str, list[Item]] = {}
    for item in items:
        by_group.setdefault(item.group, []).append(item)

    print(f"{len(by_group)} tablo grubu · {len(items)} kalem\n")
    total_series = 0
    for group, rows in by_group.items():
        columns = sum(len(r.columns) for r in rows)
        total_series += columns
        labels = sorted({label for r in rows for _, label in r.columns})
        print(f"  {group[:42]:44} {len(rows):>4} kalem · {columns:>5} kalem×sütun")
        print(f"       sütunlar: {', '.join(labels[:8])}{' …' if len(labels) > 8 else ''}")
    print(f"\nTOPLAM kalem×sütun (= çekilebilecek seri sayısı): {total_series}")

    failed = [item for item in items if item.note]
    if failed:
        print(f"\nsorunlu {len(failed)} kalem:")
        for item in failed[:20]:
            print(f"  {item.native_code:>14}  {item.group[:26]:28} {item.note[:60]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="makine okunur çıktı dosyası")
    parser.add_argument("--pause", type=float, default=0.15, help="istekler arası bekleme (sn)")
    parser.add_argument("--limit", type=int, help="yalnız ilk N kalem (deneme için)")
    args = parser.parse_args()

    client = session()
    page = client.get(f"{BASE_URL}{TREE_PATH}", timeout=60)
    page.raise_for_status()
    items = parse_tree(page.text)
    if args.limit:
        items = items[: args.limit]
    print(f"kalem ağacı okundu: {len(items)} kalem; sütunlar sorulacak…", file=sys.stderr)

    fill_columns(items, client, pause=args.pause)
    report(items)

    if args.json:
        args.json.write_text(
            json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nyazıldı -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
