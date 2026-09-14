"""Assign reviewed semantics to the auto-generated EVDS catalog entries, per data group.

scripts/evds_catalog_generator.py writes every EVDS series with ``measure_type: unknown``
because EVDS's metadata does not say whether a number is a stock, a flow, a rate or an
index. Silver refuses to publish an ``unknown`` series (correctly), so the generated
catalog was ~70% unusable. This script closes that gap the only honest way available:
a human reviews each EVDS *data group* once (a group's series share one meaning — e.g.
every ``bie_akonutsat2`` series is "mortgaged house sales, count per month") and records
the decision here. The table is data, not inference; nothing is guessed from values.

Only entries still marked ``unknown`` are touched; hand-curated rows keep their fields.
Groups marked ``deprecated`` are EVDS "(Arşiv)" series the source no longer produces
(they return empty or byte-identical bodies and cannot land in Bronze).

Usage (from lakehouse-core/):

    uv run python scripts/apply_evds_group_semantics.py --dry-run
    uv run python scripts/apply_evds_group_semantics.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = _REPO_ROOT / "catalog" / "series" / "evds.yml"


@dataclass(frozen=True)
class GroupSemantics:
    measure_type: str
    unit: str | None
    default_agg: str | None
    note: str


DEPRECATE = GroupSemantics("unknown", None, None, "EVDS (Arşiv): source no longer publishes")

# dataset_id (evds_<datagroup>) -> reviewed semantics. Reviewed 2026-09-14 against the
# group names EVDS itself reports (tumSeriler tree) and the series name patterns.
GROUP_SEMANTICS: dict[str, GroupSemantics] = {
    # TÜFE alt kalemleri (2025=100). Endeks seviyesi; aya indirgemede son değer.
    "evds_bie_tukfiy2025": GroupSemantics("index", "index", "last", "TÜFE alt kalem endeksleri"),
    # Konut ve iş yeri satış istatistikleri (il + Türkiye toplamı + mevsimsellikten
    # arındırılmış): dönem içi satış adedi -> akım, toplanır.
    "evds_bie_akonutsat1": GroupSemantics("flow_periodic", "adet", "sum", "Toplam satışlar (konut, iş yeri)"),
    "evds_bie_akonutsat2": GroupSemantics("flow_periodic", "adet", "sum", "İpotekli satışlar (konut, iş yeri)"),
    "evds_bie_akonutsat3": GroupSemantics("flow_periodic", "adet", "sum", "İlk el satışlar (konut, iş yeri)"),
    "evds_bie_akonutsat4": GroupSemantics("flow_periodic", "adet", "sum", "İkinci el satışlar (konut, iş yeri)"),
    # Birim fiyat / kira: TL/m² seviyesi; dönem sonu değeri alınır.
    "evds_bie_birimfiyat": GroupSemantics("stock", "TRY_per_m2", "last", "Konut birim fiyatları (TL/m²)"),
    "evds_bie_bk": GroupSemantics("stock", "TRY_per_m2", "last", "Konut birim kiraları (TL/m²)"),
    # Endeksler.
    "evds_bie_ykke": GroupSemantics("index", "index", "last", "Yeni kiracı kira endeksi"),
    "evds_bie_kfe": GroupSemantics("index", "index", "last", "Bölgesel konut fiyat endeksleri"),
    "evds_bie_ykfe": GroupSemantics("index", "index", "last", "Yeni konutlar fiyat endeksi"),
    "evds_bie_yokfend": GroupSemantics("index", "index", "last", "Yeni olmayan konutlar fiyat endeksi"),
    # Faiz oranları (%): ortalama.
    "evds_bie_kt210a": GroupSemantics("rate", "pct", "avg", "Kredi faiz oranları, stok (%)"),
    "evds_bie_kt100h": GroupSemantics("rate", "pct", "avg", "Kredi faiz oranları, akım (%)"),
    # Arşiv grupları.
    "evds_bie_tukkre": DEPRECATE,
    "evds_bie_vdkre": DEPRECATE,
    "evds_bie_kybtkttk": DEPRECATE,
}


def _entries(lines: list[str]) -> list[tuple[int, int]]:
    starts = [i for i, line in enumerate(lines) if line.startswith("  - series_id:")]
    starts.append(len(lines))
    return [(starts[i], starts[i + 1]) for i in range(len(starts) - 1)]


def _field(block: list[str], name: str) -> str | None:
    for line in block:
        if line.startswith(f"    {name}:"):
            return line.split(":", 1)[1].strip()
    return None


def _set_field(block: list[str], name: str, value: str) -> None:
    for index, line in enumerate(block):
        if line.startswith(f"    {name}:"):
            block[index] = f"    {name}: {value}\n"
            return
    # Insert after measure_type so the block stays readable.
    for index, line in enumerate(block):
        if line.startswith("    measure_type:"):
            block.insert(index + 1, f"    {name}: {value}\n")
            return
    raise ValueError(f"entry has no measure_type line to anchor {name}")


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    lines = CATALOG.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    first_start = _entries(lines)[0][0]
    out.extend(lines[:first_start])

    counts: dict[str, int] = {}
    untouched_unknown: dict[str, int] = {}
    for start, end in _entries(lines):
        block = lines[start:end]
        dataset_id = _field(block, "dataset_id")
        if _field(block, "measure_type") == "unknown" and dataset_id in GROUP_SEMANTICS:
            semantics = GROUP_SEMANTICS[dataset_id]
            if semantics is DEPRECATE:
                _set_field(block, "status", "deprecated")
            else:
                _set_field(block, "measure_type", semantics.measure_type)
                _set_field(block, "unit", semantics.unit or "null")
                if semantics.default_agg:
                    _set_field(block, "default_agg", semantics.default_agg)
            counts[dataset_id] = counts.get(dataset_id, 0) + 1
        elif _field(block, "measure_type") == "unknown":
            untouched_unknown[dataset_id or "?"] = untouched_unknown.get(dataset_id or "?", 0) + 1
        out.extend(block)

    for dataset_id, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        s = GROUP_SEMANTICS[dataset_id]
        label = "deprecated" if s is DEPRECATE else f"{s.measure_type}/{s.unit}/{s.default_agg}"
        print(f"{dataset_id:28} {n:>5}  -> {label}")
    if untouched_unknown:
        print("\nstill unknown (no reviewed group):")
        for dataset_id, n in untouched_unknown.items():
            print(f"  {dataset_id}: {n}")
    print(f"\n{sum(counts.values())} entries updated" + (" (dry run, nothing written)" if dry_run else ""))
    if not dry_run:
        CATALOG.write_text("".join(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
