"""Discovery-only utility: enumerate EVDS's category/data-group/series tree via its own
metadata endpoints, to find out how large "tüm seriler" actually is before deciding how much
of it to add to the semantic catalog.

This does NOT write anything to the catalog or the database. It only prints counts and a
sample, so a human can decide scope — consistent with catalog/series/*.yml being
human-authored and reviewed, not auto-generated (see docs/catalog-contract.md).

Usage (from lakehouse-core/, EVDS_API_KEY set in .env or the environment):

    uv run python scripts/discover_evds_series.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from _env import load_dotenv_simple

load_dotenv_simple(_REPO_ROOT)

API_KEY = os.environ.get("EVDS_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: EVDS_API_KEY not set (checked environment and .env). Set it and rerun.")
    raise SystemExit(2)

BASE_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis"
session = requests.Session()
session.headers.update({"key": API_KEY, "Accept": "application/json"})


def get_json(path: str) -> object:
    response = session.get(f"{BASE_URL}{path}", timeout=30)
    response.raise_for_status()
    return response.json()


print("=== Kategoriler (categories) ===")
categories = get_json("/categories/type=json")
print(f"Toplam kategori: {len(categories)}")
for cat in categories:
    print(f"  {cat}")

print("\n=== Veri grupları (datagroups, mode=0) ===")
datagroups = get_json("/datagroups/mode=0&type=json")
print(f"Toplam veri grubu: {len(datagroups)}")
for group in datagroups[:10]:
    print(f"  {group}")
if len(datagroups) > 10:
    print(f"  ... ve {len(datagroups) - 10} tane daha")

print("\n=== Örnek: ilk veri grubunun içindeki seriler (serieList) ===")
if datagroups:
    first_group = datagroups[0]
    group_code = first_group.get("DATAGROUP_CODE") or first_group.get("code") or list(first_group.values())[0]
    print(f"Grup kodu deneniyor: {group_code}")
    try:
        series_in_group = get_json(f"/serieList/type=json&code={group_code}")
        print(f"Bu gruptaki seri sayısı: {len(series_in_group)}")
        for s in series_in_group[:5]:
            print(f"  {s}")
    except Exception as exc:
        print(f"  HATA: {exc}")

print("\n=== TAHMİNİ TOPLAM ===")
print(f"{len(datagroups)} veri grubu var. Her grupta ortalama birkaç ile onlarca seri olabilir.")
print("Gerçek toplam seri sayısını görmek için her grubun serieList'ine tek tek bakmak gerekir")
print("(bu script bunu YAPMADI, sadece 1 örnek grup denedi) -- bu, onlarca-yuzlerce ekstra istek demek.")
