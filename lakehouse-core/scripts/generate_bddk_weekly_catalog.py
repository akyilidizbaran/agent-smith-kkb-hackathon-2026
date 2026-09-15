"""Turn the discovered BDDK weekly items into catalog entries and a fetch-position map.

``scripts/discover_bddk_weekly_items.py`` sweeps the weekly bulletin's positional address
space and pairs every answering address with the stable item id from the bulletin's own
item tree. This script consumes that output and writes the two artefacts the ingestion path
needs, keeping each fact where it belongs:

* ``catalog/series/bddk_weekly.yml`` — what a series **means** (unit, measure type,
  frequency, names). Semantic catalog; no addressing.
* ``scripts/bddk_weekly_chart_positions.json`` — how the endpoint **addresses** it
  (positional chart id + the label to check the answer against). Fetch detail, read by
  ``scripts/ingestion_registry.py`` instead of the hand-written dict it used to carry.

Scope: tables 1 (Krediler) and 2 (Takipteki Alacaklar). Both are credit balances in
**Milyon TL** — table 1's unit is stated in the bulletin's own table header
(``docs/sources/bddk_weekly.md``), and table 2's was confirmed on 2026-09-15 by comparing
its values against the monthly bulletin's already-verified figures: weekly "Takipteki
Alacaklar" reads 595.211 on 2026-01-02 against the monthly 593.647 for 2025-12, and weekly
"Takipteki a) Konut" reads 1.149 against the monthly 1.128 — the same quantity a few days
apart. The remaining tables (securities, deposits, cash, FX position, maturity) are left
out of this pass; they are further from this project's subject and their units are not
established here.

Every entry is written ``semantic_confidence: derived``: the unit, frequency and measure
type are evidenced above, but no human has reviewed each individual line's exact
definition. ``bddk_weekly:5690_3`` keeps its hand-written ``verified`` entry untouched.

Usage (from lakehouse-core/):

    uv run python scripts/discover_bddk_weekly_items.py --json /tmp/weekly.json
    uv run python scripts/generate_bddk_weekly_catalog.py --items /tmp/weekly.json --dry-run
    uv run python scripts/generate_bddk_weekly_catalog.py --items /tmp/weekly.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = _REPO_ROOT / "catalog" / "series" / "bddk_weekly.yml"
POSITIONS_PATH = Path(__file__).resolve().parent / "bddk_weekly_chart_positions.json"

INCLUDED_TABLES = (1, 2)
TABLE_NAMES = {1: "Krediler", 2: "Takipteki Alacaklar"}
SUTUN = "3"  # Toplam; the only column verified live (docs/sources/bddk_weekly.md)

EXISTING_HAND_WRITTEN = {"bddk_weekly:5690_3"}
"""Kept as authored; the generator neither rewrites nor duplicates it."""

EMPTY_AT_SOURCE = {
    # Probed live 2026-09-15 over 2026-01-02..2026-01-30: the endpoint answers HTTP 200
    # with an empty series (XEkseni = [], YEkseni = []) for every "d) Diğer" row, while a
    # sibling row in the same table returns its five weeks. All three also share one
    # response body, so the second and third collide on artifact identity. Catalogued as
    # deprecated rather than dropped, so the reason stays visible.
    "bddk_weekly:5693_3",   # 1.0.7  — Krediler / Tüketici Kredileri / d) Diğer
    "bddk_weekly:5704_3",   # 1.0.18 — Krediler / Taksitli Ticari Krediler / d) Diğer
    "bddk_weekly:5871_3",   # 2.0.13 — Takipteki Alacaklar / d) Diğer
}
"""Rows the source publishes no observations for; Silver would refuse them anyway."""

_TR_ASCII = str.maketrans(
    {"İ": "I", "I": "I", "ı": "i", "Ş": "S", "ş": "s", "Ğ": "G", "ğ": "g",
     "Ü": "U", "ü": "u", "Ö": "O", "ö": "o", "Ç": "C", "ç": "c"}
)


def slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKC", value).translate(_TR_ASCII)
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_") or "kalem"


def clean_label(source_label: str) -> str:
    """The item's own name, without the currency and column legs the title appends."""

    return re.split(r"\s*\((?:TRY|TL|USD|EUR)\)", source_label)[0].strip()


def parent_of(items: list[dict], index: int) -> str | None:
    """The nearest preceding row whose label is not a lettered child ("a) …")."""

    for candidate in reversed(items[:index]):
        if not re.match(r"^[a-z]\)", clean_label(candidate["source_label"])):
            return clean_label(candidate["source_label"])
    return None


ENTRY = """  - series_id: {series_id}
    native_code: "{native_code}"
    dataset_id: {dataset_id}
    name_tr: {name_tr}
    description: >-
      BDDK Haftalık Bülten, {table_name} tablosu, "{label}" kalemi{parent_note}, Toplam sütunu,
      Sektör tarafı. Haftalık bakiyedir (stok): dönemler toplanmaz, daha düşük frekansa
      indirilirken dönemin son değeri alınır.
      BİRİM: Milyon TL — {unit_evidence}
      KİMLİK: {native_code} kaynağın sabit kalem kimliğidir ve seri kimliğinin dayanağıdır;
      {sutun} Toplam sütunudur. Uçtaki pozisyonel adres ({chart_id}) kimlik değildir ve
      scripts/bddk_weekly_chart_positions.json içinde, kaynağın kendi etiketiyle birlikte
      tutulur; çekim sırasında etiket uyuşmazsa istek reddedilir.
      Bu giriş scripts/generate_bddk_weekly_catalog.py ile üretildi; kalem tek tek insan
      tarafından incelenmediği için semantic_confidence 'derived'.
    aliases:
{aliases}
    tags: [{tags}]
    frequency: weekly
    week_anchor: friday
    unit: TRY_mn
    measure_type: stock
    default_agg: last
    semantic_confidence: derived
    semantic_source: source_docs
    metadata_url: https://www.bddk.org.tr/BultenHaftalik/
    status: {status}
"""

UNIT_EVIDENCE = {
    1: "bültenin kendi tablo başlığı 'Krediler / Sektör … Birim: Milyon TL' diyor "
       "(docs/sources/bddk_weekly.md).",
    2: "2026-09-15 çapraz doğrulaması: haftalık 'Takipteki Alacaklar' 2026-01-02'de 595.211, "
       "aylık bültenin doğrulanmış 2025-12 değeri 593.647; aynı büyüklük.",
}


def alias_lines(label: str, parent: str | None, table: int) -> list[str]:
    """Search phrases an agent is likely to use, built from the item's own wording."""

    base = re.sub(r"^[a-z]\)\s*", "", label).strip()
    base = re.sub(r"\s*\([^)]*\)", "", base).strip()
    prefix = "takipteki " if table == 2 else ""
    phrases = [
        f"haftalık {prefix}{base.lower()}",
        f"{prefix}{base.lower()} haftalık",
        f"BDDK haftalık {prefix}{base.lower()}",
    ]
    if parent:
        parent_base = re.sub(r"\s*\([^)]*\)", "", parent).strip().lower()
        if parent_base and parent_base != base.lower():
            phrases.append(f"haftalık {parent_base} {base.lower()}")
    seen: list[str] = []
    for phrase in phrases:
        normalized = " ".join(phrase.split())
        if normalized not in seen:
            seen.append(normalized)
    return [f"      - {phrase}" for phrase in seen]


def build(items: list[dict]) -> tuple[list[str], dict[str, dict[str, str]]]:
    entries: list[str] = []
    positions: dict[str, dict[str, str]] = {}
    for table in INCLUDED_TABLES:
        rows = [item for item in items if item["table"] == table]
        for index, item in enumerate(rows):
            stable = item.get("stable_item_id")
            if not stable:
                continue
            series_id = f"bddk_weekly:{stable}_{SUTUN}"
            label = clean_label(item["source_label"])
            positions[series_id] = {
                "id": item["chart_id"],
                "expected_measure_label": label,
            }
            if series_id in EXISTING_HAND_WRITTEN:
                continue
            parent = parent_of(rows, index)
            status = "deprecated" if series_id in EMPTY_AT_SOURCE else "active"
            display_parent = f" ({parent})" if parent and parent != label else ""
            entries.append(
                ENTRY.format(
                    series_id=series_id,
                    native_code=stable,
                    dataset_id=f"bddk_weekly_{slug(label)}_{stable}",
                    name_tr=json.dumps(
                        f"{label}{display_parent} - {TABLE_NAMES[table]}, Haftalık (Sektör)",
                        ensure_ascii=False,
                    ),
                    table_name=TABLE_NAMES[table],
                    label=label,
                    parent_note=f" ({parent} altında)" if parent and parent != label else "",
                    unit_evidence=UNIT_EVIDENCE[table],
                    native_code_repeat=stable,
                    sutun=SUTUN,
                    chart_id=item["chart_id"],
                    aliases="\n".join(alias_lines(label, parent, table)),
                    tags="kredi, bankacilik, bddk, stok, haftalik"
                    + (", takip, npl" if table == 2 else ""),
                    status=status,
                )
            )
    return entries, positions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, required=True, help="discover script's --json output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    items = json.loads(args.items.read_text(encoding="utf-8"))
    entries, positions = build(items)

    existing = CATALOG_PATH.read_text(encoding="utf-8").rstrip("\n")
    marker = "\n  # --- üretilmiş: BDDK Haftalık Bülten, Krediler ve Takipteki Alacaklar tabloları ---\n"
    base = existing.split(marker)[0]
    catalog = base + marker + "\n" + "\n".join(entries)

    print(f"{len(entries)} yeni katalog girişi · {len(positions)} pozisyon eşleşmesi")
    for series_id, position in list(positions.items())[:5]:
        print(f"  {series_id:24} -> {position['id']:>8}  {position['expected_measure_label'][:40]}")
    if args.dry_run:
        print("\n--dry-run: hiçbir dosya yazılmadı.")
        return 0

    CATALOG_PATH.write_text(catalog + "\n", encoding="utf-8")
    POSITIONS_PATH.write_text(
        json.dumps(positions, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nyazıldı -> {CATALOG_PATH.name}, {POSITIONS_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
