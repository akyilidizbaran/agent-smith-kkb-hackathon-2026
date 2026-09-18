"""Read each BDDK monthly item's unit from the source, one probe per item.

The item tree (``scripts/discover_bddk_monthly_items.py``) gives names and column ids but
not units: 576 of 613 item names carry no unit at all. The unit is stated by the report
endpoint itself, in the response's ``Json.groupHeaders[0].titleText``:

    "Bilanço - Krediler (milyon TL)"
    "Sektörel Kredi Dağılımı - Tarım, Avcılık ve Ormancılık (bin TL)"
    "Rasyolar - Takipteki Alacaklar (Brüt) / Toplam Nakdi Krediler (%)"

That difference is not cosmetic. Sektörel Kredi Dağılımı is published in **bin TL** while
the Bilanço tables are in **milyon TL**; assuming one unit for the whole bulletin would put
every sectoral figure out by a factor of 1000. So every item is asked, and an item whose
unit cannot be read is recorded as unknown rather than guessed — Silver refuses to publish
a series with no unit, which is the behaviour we want here.

The probe requests a single month, so it is also a liveness check: the pre-2010 and
pre-2011 schema groups answer with an empty row set, which is how this project learns they
are dead in the 2021→ window rather than assuming it.

Usage (from lakehouse-core/):

    uv run python scripts/discover_bddk_monthly_items.py --json items.json
    uv run python scripts/probe_bddk_monthly_units.py --items items.json --out items_units.json

One request per item (~613), paced; roughly half an hour.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
import truststore

BASE_URL = "https://www.bddk.org.tr"
REPORT_PATH = "/BultenAylik/tr/Home/GelismisRaporGetir"
USER_AGENT = "kkb-lakehouse/0.1 (KKB Hackathon 2026)"

PROBE_YEAR, PROBE_MONTH = "2025", "12"
"""One month inside the project's window; every live item must answer for it."""

UNIT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\(milyon\s*TL\)", "TRY_mn"),
    (r"\(bin\s*TL\)", "TRY_th"),
    (r"\(%\)", "pct"),
    (r"\(Adet\)", "adet"),
)
"""Source wording -> this project's unit code. Anything else stays unknown."""


def unit_from_title(title: str) -> str | None:
    for pattern, unit in UNIT_PATTERNS:
        if re.search(pattern, title, re.I):
            return unit
    return None


def probe(client: requests.Session, kalem_sutun: str) -> dict:
    """One month for one item; returns what the source said about it."""

    response = client.post(
        f"{BASE_URL}{REPORT_PATH}",
        data={
            "baslangicYil": PROBE_YEAR, "baslangicAy": PROBE_MONTH,
            "bitisYil": PROBE_YEAR, "bitisAy": PROBE_MONTH,
            "periyot": "1", "paraBirimi": "TL", "taraf": "10001",
            "kalemSutun": kalem_sutun, "gosterimTuru": "grid",
        },
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        return {"ok": False, "note": "kaynak success=false döndü"}
    body = payload.get("Json") or {}
    headers = body.get("groupHeaders") or [{}]
    title = str(headers[0].get("titleText") or "").strip()
    rows = ((body.get("data") or {}).get("rows")) or []
    sample = rows[0]["cell"][3] if rows and len(rows[0].get("cell", [])) > 3 else None
    return {
        "ok": True,
        "title": title,
        "unit": unit_from_title(title),
        "sample_value": sample,
        "empty": not rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, required=True, help="keşif script'inin --json çıktısı")
    parser.add_argument("--out", type=Path, required=True, help="birimlerle zenginleştirilmiş çıktı")
    parser.add_argument("--pause", type=float, default=0.2)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    items = json.loads(args.items.read_text(encoding="utf-8"))
    if args.limit:
        items = items[: args.limit]

    truststore.inject_into_ssl()
    client = requests.Session()
    client.headers["User-Agent"] = USER_AGENT

    for index, item in enumerate(items, start=1):
        columns = item.get("columns") or []
        if not columns:
            item["probe"] = {"ok": False, "note": "sütunu yok"}
            continue
        try:
            item["probe"] = probe(client, columns[0][0])
        except Exception as exc:  # noqa: BLE001 — recorded, never guessed around
            item["probe"] = {"ok": False, "note": f"{type(exc).__name__}: {exc}"}
        if index % 25 == 0:
            done = sum(1 for i in items[:index] if (i.get("probe") or {}).get("unit"))
            print(f"  … {index}/{len(items)} · birimi okunan {done}", file=sys.stderr, flush=True)
        time.sleep(args.pause)

    args.out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    units: dict[str, int] = {}
    empty = 0
    for item in items:
        p = item.get("probe") or {}
        units[str(p.get("unit"))] = units.get(str(p.get("unit")), 0) + 1
        empty += 1 if p.get("empty") else 0
    print("\nbirim dağılımı:")
    for unit, count in sorted(units.items(), key=lambda kv: -kv[1]):
        print(f"   {unit:16} {count:>4} kalem")
    print(f"kaynakta boş dönen kalem: {empty}")
    print(f"yazıldı -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
