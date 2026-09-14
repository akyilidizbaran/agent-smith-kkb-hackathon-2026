"""Generic, source-driven EVDS catalog generator: enumerate EVDS's own datagroup/series
metadata (evds3.tcmb.gov.tr/tumSeriler tree) and write catalog/series/evds.yml directly from
it — no series code is ever hardcoded here.

This is a different generic mechanism than the human-curated catalogs (bddk_*.yml): those are
"nothing here is inferred from data" by design (docs/catalog-contract.md). This one is the
schema's other, equally-designed-for path: semantic_source: source_service, for "metadata the
source itself declares through an API" (src/lakehouse/catalog/series.py's own docstring). All
generated entries get semantic_confidence: derived (no human has reviewed the individual
series), never "verified".

Adding a new EVDS series to the catalog after this never means writing new code: re-running
this generator picks up whatever EVDS's own /datagroups and /serieList endpoints report next
time, because nothing about "which series exist" is hardcoded — matching the same principle
already applied to bootstrap_database() and run_catalog_ingestion.py.

Usage (from lakehouse-core/, EVDS_API_KEY set in .env):

    uv run python scripts/evds_catalog_generator.py --discover-only   # just count, write nothing
    uv run python scripts/evds_catalog_generator.py                   # write catalog/series/evds.yml
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from _env import load_dotenv_simple

load_dotenv_simple(_REPO_ROOT)

import os

API_KEY = os.environ.get("EVDS_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: EVDS_API_KEY not set.")
    raise SystemExit(2)

BASE_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis"
session = requests.Session()
session.headers.update({"key": API_KEY, "Accept": "application/json"})

_OUTPUT_PATH = _REPO_ROOT / "catalog" / "series" / "evds.yml"

# EVDS's own FREQUENCY_STR values -> this project's frequency vocabulary
# (src/lakehouse/catalog/series.py FREQUENCIES). Anything not mapped here is skipped, not
# guessed -- see _SKIPPED_FREQUENCY below.
_FREQUENCY_MAP = {
    "GÜNLÜK": "daily",
    "HAFTALIK": "weekly",
    "AYLIK": "monthly",
    "3 AYLIK": "quarterly",
    "6 AYLIK": "semiannual",
    "YILLIK": "yearly",
    "İŞ GÜNÜ": "business_daily",
}

_TR_ASCII_MAP = str.maketrans(
    {"İ": "I", "I": "I", "Ş": "S", "Ğ": "G", "Ü": "U", "Ö": "O", "Ç": "C", "ı": "i"}
)


def get_json(path: str) -> object:
    for attempt in range(3):
        response = session.get(f"{BASE_URL}{path}", timeout=30)
        if response.status_code == 200:
            return response.json()
        time.sleep(0.5 * (2**attempt))
    response.raise_for_status()


def _ascii_slug(value: str) -> str:
    import re

    transliterated = value.translate(_TR_ASCII_MAP)
    return re.sub(r"[^a-z0-9]+", "_", transliterated.lower()).strip("_") or "x"


def discover_all_series() -> list[dict]:
    """Walk every datagroup and return every series EVDS itself reports for it."""

    datagroups = get_json("/datagroups/mode=0&type=json")
    print(f"{len(datagroups)} veri grubu bulundu, her biri icin serieList sorgulanacak...")

    all_series: list[dict] = []
    for index, group in enumerate(datagroups, start=1):
        code = group.get("DATAGROUP_CODE")
        if not code:
            continue
        try:
            series = get_json(f"/serieList/type=json&code={code}")
        except Exception as exc:
            print(f"  [{index}/{len(datagroups)}] {code}: HATA, atlandi ({exc})")
            continue
        if isinstance(series, list):
            for s in series:
                s["_DATAGROUP_NAME"] = group.get("DATAGROUP_NAME", "")
                s["_DATAGROUP_BIRIMI"] = group.get("BIRIMI", "")
            all_series.extend(series)
        if index % 50 == 0 or index == len(datagroups):
            print(f"  [{index}/{len(datagroups)}] ... su ana kadar {len(all_series)} seri")
        time.sleep(0.15)
    return all_series


def build_catalog_entries(raw_series: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Turn EVDS's own series metadata into catalog entries. Returns (entries, skip_reasons)."""

    entries: list[dict] = []
    skipped: dict[str, int] = {}
    seen_ids: set[str] = set()

    for s in raw_series:
        code = s.get("SERIE_CODE")
        name = s.get("SERIE_NAME")
        freq_str = (s.get("FREQUENCY_STR") or "").strip().upper()
        if not code or not name:
            skipped["missing_code_or_name"] = skipped.get("missing_code_or_name", 0) + 1
            continue
        frequency = _FREQUENCY_MAP.get(freq_str)
        if frequency is None:
            skipped[f"unmapped_frequency:{freq_str}"] = (
                skipped.get(f"unmapped_frequency:{freq_str}", 0) + 1
            )
            continue

        series_id = f"evds:{code}"
        if series_id in seen_ids:
            skipped["duplicate_series_id"] = skipped.get("duplicate_series_id", 0) + 1
            continue
        seen_ids.add(series_id)

        dataset_id = f"evds_{_ascii_slug(s.get('DATAGROUP_CODE', code))}"
        unit = (s.get("_DATAGROUP_BIRIMI") or "").strip() or None

        entries.append(
            {
                "series_id": series_id,
                "native_code": code,
                "dataset_id": dataset_id,
                "name_tr": str(name).strip(),
                "frequency": frequency,
                "unit": unit,
                "group_name": s.get("_DATAGROUP_NAME", ""),
                "tag": s.get("TAG", ""),
            }
        )
    return entries, skipped


_HEADER = '''# Semantic series catalog — EVDS (TCMB Electronic Data Delivery System)
#
# GENERATED, not hand-authored, by scripts/evds_catalog_generator.py from EVDS's own
# /datagroups and /serieList metadata endpoints (evds3.tcmb.gov.tr/tumSeriler tree) — this is
# the schema's source_service path (see docs/catalog-contract.md and
# src/lakehouse/catalog/series.py's SEMANTIC_SOURCES docstring), not the human-authored path
# the bddk_*.yml files use. Every entry below is semantic_confidence: derived — EVDS declares
# the name/frequency/unit itself, but no human has individually verified each series.
#
# Re-running the generator, not hand-editing, is how this file should be updated: it reflects
# whatever EVDS's own API reports at generation time, so no series code is ever hardcoded
# either here or in the ingestion path (ingestion_registry.py's _evds_spec derives everything
# from native_code alone — see comment there).

catalog_schema_version: "1.0"
source_id: evds

series:
'''

_ENTRY_TEMPLATE = '''  - series_id: {series_id}
    native_code: {native_code}
    dataset_id: {dataset_id}
    name_tr: {name_tr}
    description: >-
      TCMB EVDS, "{group_name}" veri grubu. Kaynağın kendi API metadata'sından otomatik
      üretildi (scripts/evds_catalog_generator.py); insan tarafından tek tek doğrulanmadı.
      Etiketler (kaynak): {tag}
    tags: [evds, otomatik]
    frequency: {frequency}
    unit: {unit}
    measure_type: unknown
    semantic_confidence: derived
    semantic_source: source_service
    metadata_url: https://evds3.tcmb.gov.tr/igmevdsms-dis/serieList/type=json&code={native_code}
    status: active
'''


def _yaml_str(value: str) -> str:
    escaped = value.replace('"', '\\"').replace("\n", " ")
    return f'"{escaped}"'


def write_catalog(entries: list[dict]) -> None:
    parts = [_HEADER]
    for e in entries:
        parts.append(
            _ENTRY_TEMPLATE.format(
                series_id=e["series_id"],
                native_code=_yaml_str(e["native_code"]),
                dataset_id=e["dataset_id"],
                name_tr=_yaml_str(e["name_tr"]),
                group_name=e["group_name"].replace('"', "'"),
                tag=e["tag"].replace('"', "'").replace("\n", " "),
                frequency=e["frequency"],
                unit=_yaml_str(e["unit"]) if e["unit"] else "null",
            )
        )
    _OUTPUT_PATH.write_text("\n".join(parts), encoding="utf-8")
    print(f"\n{len(entries)} seri yazildi -> {_OUTPUT_PATH}")


def main() -> int:
    discover_only = "--discover-only" in sys.argv
    raw = discover_all_series()
    entries, skipped = build_catalog_entries(raw)

    print(f"\n=== SONUC ===")
    print(f"Ham seri sayisi (tum datagroup'lardan): {len(raw)}")
    print(f"Katalog girisine donusen: {len(entries)}")
    print(f"Atlanan: {sum(skipped.values())}")
    for reason, count in sorted(skipped.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {reason}: {count}")

    if discover_only:
        print("\n--discover-only: hicbir dosya yazilmadi.")
        return 0

    write_catalog(entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
