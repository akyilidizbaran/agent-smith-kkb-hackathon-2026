"""Turn the discovered BDDK monthly items into catalog entries.

Input is the unit-probed item list (``scripts/discover_bddk_monthly_items.py`` ->
``scripts/probe_bddk_monthly_units.py``). Everything about *addressing* comes from the
source: the stable item id, the exact ``kalemSutun`` value for each column, the item's own
name, and the unit printed in the report header. Nothing here is guessed.

What this script adds is *meaning*, and only at the level the bulletin's own table groups
justify:

* Balance-sheet style tables (Bilanço, Krediler, Mevduat, Menkul Kıymetler, Likidite,
  Sermaye Yeterliliği, Yabancı Para Pozisyonu, Bilanço Dışı, Sektörel Kredi Dağılımı, KOBİ)
  are **balances**: ``stock`` / ``last``. They are month-end positions, so they are never
  summed across periods.
* ``Kar Zarar`` is **year-to-date cumulative** and resets every January — measured live on
  2026-09-14 and recorded in ``docs/sources/bddk_monthly.md`` (2025-01 47.347 →
  2025-12 940.183 → 2026-01 87.249). Those items get ``flow_ytd`` with
  ``cumulative_reset: yearly`` so Gold can difference them back to monthly flows.
* ``Rasyolar`` and ``Yurt Dışı Şube Rasyoları`` are ratios in percent: ``ratio`` / ``last``.
* Counts (``Diğer Bilgiler``, and any column whose own label says "Sayısı") are ``count``.

Units are never assumed: each entry's unit is the one the source printed for that item
(``milyon TL`` → ``TRY_mn``, ``bin TL`` → ``TRY_th``, ``%`` → ``pct``, ``Adet`` → ``adet``).
Sektörel Kredi Dağılımı really is published in **bin TL** while the rest of the bulletin is
in **milyon TL**; an item whose unit could not be read is written ``status: deprecated``
with the reason, because Silver refuses a series with no unit and a silent wrong unit is
worse than a missing series.

Two schema groups ("Haziran 2010 öncesi", "Eylül 2011 öncesi") answer with no rows at all
inside this project's 2021→ window; they are catalogued ``deprecated`` so the reason stays
visible instead of the items simply being absent.

Every entry is ``semantic_confidence: derived``: the unit, frequency and measure type are
evidenced above, but no human reviewed each individual line's exact definition.

Usage (from lakehouse-core/):

    uv run python scripts/generate_bddk_monthly_catalog.py --items items_units.json --dry-run
    uv run python scripts/generate_bddk_monthly_catalog.py --items items_units.json
    uv run python scripts/generate_bddk_monthly_catalog.py --items items_units.json --columns all

Adding one group's non-primary columns without regenerating anything else (ADR-0108):

    uv run python scripts/discover_bddk_monthly_items.py --group "Mevduat Vade İtibarıyla" --json vade.json
    uv run python scripts/probe_bddk_monthly_units.py --items vade.json --out vade_units.json
    uv run python scripts/generate_bddk_monthly_catalog.py --items vade_units.json \
        --group "Mevduat Vade İtibarıyla" --add-columns --probed-on 2026-09-23

``--add-columns`` inserts each item's missing columns directly after that item's existing
primary entry and leaves every other byte of the catalog as it was. An item whose primary
entry is not ``active`` (an old schema version, a source failure) gets nothing added.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = _REPO_ROOT / "catalog" / "series" / "bddk_monthly.yml"

MARKER = "\n  # --- üretilmiş: BDDK Aylık Bülten, tüm tablo grupları ---\n"
"""Everything after this line is regenerated; hand-written entries above are untouched."""

def hand_written_ids(catalog_text: str) -> set[str]:
    """The kalemSutun values of the entries a person wrote, read from the file itself.

    They sit above MARKER and must never be regenerated or duplicated. Reading them back
    beats keeping a list in this file: the list drifted once already and the catalog loader
    caught it as a duplicate series_id.
    """

    head = catalog_text.split(MARKER)[0]
    return set(re.findall(r'native_code:\s*"?([\w.]+\?\w+)"?', head))

DEAD_SCHEMA_GROUPS = ("Haziran 2010 öncesi", "Eylül 2011 öncesi")

BROKEN_AT_SOURCE: dict[str, str] = {
    # Item 1453: the Nakdi column answered with the endpoint's own failure message twice
    # (2026-09-15 23:37 UTC, 2026-09-16 14:20 UTC); the ToplamNakdi column's response is
    # byte-identical to another item's already stored artifact (2026-09-16).
    "1453?ToplamNakdi": "kaynak Nakdi sütununda iki denemede de 'Gelişmiş Rapor üretilirken "
                        "hata oluştu!' döndürdü, ToplamNakdi sütununda başka bir kalemle bayt "
                        "bayt aynı yanıt verdi (2026-09-15/16); kendi verisini döndürmüyor",
    # Item 1492: both columns answered with a body byte-identical to another item's, so the
    # artifact store refuses them as identity conflicts — the same failure mode as the weekly
    # bulletin's empty "d) Diğer" rows.
    "1492?ToplamNakdi": "kaynağın yanıtı hem Nakdi hem ToplamNakdi sütununda başka bir kalemin "
                        "yanıtıyla bayt bayt aynı (artifact kimlik çakışması, 2026-09-15/16); "
                        "kendi verisini döndürmüyor",
}
"""Items the bulletin lists but does not actually serve. Catalogued deprecated, with evidence."""


@dataclass(frozen=True)
class GroupRule:
    """How one bulletin table group is read."""

    measure_type: str
    default_agg: str
    tags: tuple[str, ...]
    primary_labels: tuple[str, ...] = ("Toplam",)
    cumulative_reset: str | None = None
    note: str = ""


BALANCE = ("stok", "bankacilik", "bddk", "aylik")

GROUP_RULES: dict[str, GroupRule] = {
    "Bilanço": GroupRule("stock", "last", BALANCE + ("bilanco",)),
    "Kar Zarar": GroupRule(
        "flow_ytd", "sum", ("kar", "gelir", "gider", "bankacilik", "bddk", "aylik"),
        cumulative_reset="yearly",
        note="Yıl başından itibaren birikimlidir ve Ocak'ta sıfırlanır "
             "(2026-09-14 canlı ölçümü, docs/sources/bddk_monthly.md).",
    ),
    "Krediler": GroupRule("stock", "last", BALANCE + ("kredi",)),
    "Tüketici Kredileri": GroupRule("stock", "last", BALANCE + ("kredi", "tuketici")),
    "Sektörel Kredi Dağılımı": GroupRule(
        "stock", "last", BALANCE + ("kredi", "sektorel"),
        primary_labels=("Toplam Nakdi Krediler", "Nakdi Krediler"),
    ),
    "KOBİ Kredileri": GroupRule(
        "stock", "last", BALANCE + ("kredi", "kobi"),
        primary_labels=("Toplam Nakdi Krediler",),
    ),
    "Sendikasyon Seküritizasyon Kredileri": GroupRule("stock", "last", BALANCE + ("kredi",)),
    "Menkul Kıymetler": GroupRule("stock", "last", BALANCE + ("menkul",)),
    "Mevduat Türler İtibarıyla": GroupRule("stock", "last", BALANCE + ("mevduat",)),
    "Mevduat Vade İtibarıyla": GroupRule("stock", "last", BALANCE + ("mevduat", "vade")),
    "Likidite Durumu": GroupRule("stock", "last", BALANCE + ("likidite",)),
    "Sermaye Yeterliliği": GroupRule("stock", "last", BALANCE + ("sermaye",)),
    "Yabancı Para Pozisyonu": GroupRule("stock", "last", BALANCE + ("doviz", "pozisyon")),
    "Bilanço Dışı İşlemler": GroupRule("stock", "last", BALANCE + ("bilanco_disi",)),
    "Rasyolar": GroupRule("ratio", "last", ("rasyo", "oran", "bankacilik", "bddk", "aylik"),
                          primary_labels=("Rasyo",)),
    "Yurt Dışı Şube Rasyoları": GroupRule("ratio", "last", ("rasyo", "oran", "sube", "bddk"),
                                          primary_labels=("Rasyo",)),
    "Diğer Bilgiler": GroupRule("count", "last", ("adet", "bankacilik", "bddk", "aylik"),
                                primary_labels=("Adet",)),
}

COUNT_COLUMN = re.compile(r"say[ıi]s[ıi]|adet", re.I)
"""A column whose own label counts things: written, but never published as money.

Silver reconciles a series' catalog unit against the unit the source prints in the Bronze
row's column name, and BDDK prints the *item's* unit there — so ``KOBİ Kredileri - Toplam
KOBİ Kredileri (milyon TL)-NetMusteri`` would let a customer count publish as milyon TL.
The counting columns are catalogued ``deprecated`` with that conflict recorded, rather than
published under a unit the source contradicts. ``Diğer Bilgiler`` lands in the same place
for the opposite reason: ``Diğer Bilgiler - Banka Sayısı-Adet`` carries no parenthesised
unit at all, so there is nothing for Silver to reconcile against.
"""

_TR_ASCII = str.maketrans(
    {"İ": "I", "I": "I", "ı": "i", "Ş": "S", "ş": "s", "Ğ": "G", "ğ": "g",
     "Ü": "U", "ü": "u", "Ö": "O", "ö": "o", "Ç": "C", "ç": "c"}
)


def slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKC", value).translate(_TR_ASCII)
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_") or "kalem"


def item_name(source_name: str, group: str) -> str:
    """The line's own name, without the group prefix the source repeats in it."""

    name = re.sub(r"\s*\((?:milyon|bin)\s*TL\)|\s*\(%\)|\s*\(Adet\)", "", source_name).strip()
    prefix = f"{group} -"
    if name.lower().startswith(prefix.lower()):
        name = name[len(prefix):].strip()
    return re.sub(r"^\d+\s+", "", name).strip()


def aliases_for(name: str, group: str, column_label: str, is_primary: bool) -> list[str]:
    base = name.lower()
    if not is_primary:
        # A breakdown column must not answer the item's bare name: seven series sharing
        # "tp mevduat / ..." would let a question about the total land on one bucket.
        label = " ".join(column_label.lower().split())
        out = [f"{base} {label}", f"{base} {label} bddk", f"aylık {base} {label}"]
        if group == "Mevduat Vade İtibarıyla":
            out.append(f"{label} vadeli {base}")
        return out[:6]
    out = [base, f"{base} bddk", f"aylık {base}"]
    if not is_primary:
        out.append(f"{base} {column_label.lower()}")
    if group == "Sektörel Kredi Dağılımı":
        out.append(f"{base} sektörüne açılan kredi")
        out.append(f"{base} kredileri")
    if group == "Mevduat Vade İtibarıyla":
        out.append(f"{base} vade")
    seen: list[str] = []
    for phrase in out:
        cleaned = " ".join(phrase.split())
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen[:6]


ENTRY = """  - series_id: {series_id}
    native_code: "{native_code}"
    dataset_id: {dataset_id}
    name_tr: {name_tr}
    description: >-
      BDDK Aylık Bülten, {group} tablosu, "{item}" kalemi, {column_label} sütunu, Sektör tarafı.
      {shape_note}
      BİRİM: {unit} — kaynağın kendi rapor başlığı "{title}" diyor ({probed_on} canlı yoklaması).
      KİMLİK: kalemSutun={native_code}; {id_note}
      Bu giriş scripts/generate_bddk_monthly_catalog.py ile üretildi; kalem tek tek insan
      tarafından incelenmediği için semantic_confidence 'derived'.{extra_note}
    aliases:
{aliases}
    tags: [{tags}]
    frequency: monthly
    unit: {unit}
    measure_type: {measure_type}
    default_agg: {default_agg}
{cumulative}    semantic_confidence: derived
    semantic_source: source_docs
    metadata_url: https://www.bddk.org.tr/BultenAylik
    status: {status}
"""

SHAPE_NOTES = {
    "stock": "Dönem sonu bakiyesidir (stok): dönemler toplanmaz, daha düşük frekansa "
             "indirilirken dönemin son değeri alınır.",
    "flow_ytd": "Yıl içi birikimli akımdır: Ocak'ta sıfırlanır, aylık değer için ardışık "
                "farkı alınır (Gold'da decompose_cumulative).",
    "ratio": "Dönem sonu oranıdır: dönemler toplanmaz, son değer alınır.",
    "count": "Dönem sonu sayımıdır: dönemler toplanmaz, son değer alınır.",
}


MATURITY_GROUP = "Mevduat Vade İtibarıyla"
"""The bulletin table whose non-primary columns are opening-maturity buckets (ADR-0108)."""


def build(items: list[dict], *, columns_mode: str, existing_ids: set[str],
          probed_on: str = "2026-09-16") -> tuple[list[str], dict[str, int]]:
    entries: list[str] = []
    stats = {"yazildi": 0, "atlandi_elle": 0, "deprecated_bos": 0, "deprecated_birimsiz": 0,
             "deprecated_adet": 0, "deprecated_kaynak_hatasi": 0, "kural_yok": 0,
             "tekrar": 0}
    # The source lists some items twice — the pre-2010 schema groups repeat an item id, and
    # KalemSutunGetir can return a column node more than once for a multi-id option. One
    # series_id may only be defined once, so the first definition wins.
    written: set[str] = set()

    for item in items:
        group = item["group"]
        rule = GROUP_RULES.get(group)
        probe = item.get("probe") or {}
        dead_schema = any(mark in group for mark in DEAD_SCHEMA_GROUPS)

        if rule is None and not dead_schema:
            stats["kural_yok"] += 1
            continue

        name = item_name(item.get("source_name") or item["option_label"], group)
        columns = item.get("columns") or []
        if not columns:
            continue

        # primary_labels is a priority order, not a set: Sektörel Kredi Dağılımı lists "Nakdi
        # Krediler" before "Toplam Nakdi Krediler", and the two differ by exactly the item's
        # Takipteki column (1425, 2025-12: 1.224.625.879 + 14.822.126 = 1.239.448.005). Taking
        # the first label the source happens to list published the performing-only figure.
        primary_labels = rule.primary_labels if rule else ("Toplam",)
        by_label = {label: column for column in columns for label in [column[1]]}
        primary = next(
            (by_label[label] for label in primary_labels if label in by_label),
            by_label.get("Toplam", columns[0]),
        )
        chosen = columns if columns_mode == "all" else [primary]

        for kalem_sutun, column_label in chosen:
            if kalem_sutun in existing_ids:
                stats["atlandi_elle"] += 1
                continue
            column_suffix = kalem_sutun.split("?", 1)[1] if "?" in kalem_sutun else "Toplam"
            series_id = f"bddk_monthly:{item['native_code']}_{column_suffix}"
            if series_id in written:
                stats["tekrar"] += 1
                continue
            written.add(series_id)

            is_count = bool(COUNT_COLUMN.search(column_label))
            unit = "adet" if is_count else probe.get("unit")
            measure_type = "count" if is_count else (rule.measure_type if rule else "stock")
            default_agg = "last" if is_count else (rule.default_agg if rule else "last")

            status = "active"
            extra = ""
            if kalem_sutun in BROKEN_AT_SOURCE:
                status, unit = "deprecated", unit or "TRY_mn"
                extra = f"\n      DURUM: {BROKEN_AT_SOURCE[kalem_sutun]}."
                stats["deprecated_kaynak_hatasi"] += 1
            elif is_count:
                status = "deprecated"
                extra = ("\n      DURUM: bu sütun adet sayıyor, ama kaynak Bronze satırına "
                         "kalemin para birimini yazıyor; Silver birim uzlaşmasını geçemez. "
                         "Birim çelişkisi çözülene kadar yayımlanmaz.")
                stats["deprecated_adet"] += 1
            elif dead_schema:
                status, unit = "deprecated", unit or "TRY_mn"
                extra = ("\n      DURUM: bu tablo grubu eski şema sürümüdür; 2021→ penceresinde "
                         "kaynak hiç satır döndürmüyor (2026-09-16 yoklaması).")
            elif probe.get("empty"):
                status, unit = "deprecated", unit or "TRY_mn"
                extra = ("\n      DURUM: kaynak bu kalem için 2025-12'de satır döndürmedi "
                         "(2026-09-16 yoklaması).")
                stats["deprecated_bos"] += 1
            elif not unit:
                status, unit = "deprecated", "TRY_mn"
                extra = ("\n      DURUM: kaynağın rapor başlığından birim okunamadı; birimi "
                         "doğrulanmadan yayımlanmaz.")
                stats["deprecated_birimsiz"] += 1

            cumulative = ""
            if rule and rule.cumulative_reset and not is_count:
                cumulative = f"    cumulative_reset: {rule.cumulative_reset}\n"

            is_primary = kalem_sutun == primary[0]
            display = name if is_primary else f"{name} - {' '.join(column_label.split())}"
            if group == MATURITY_GROUP and not is_primary:
                extra += ("\n      VADE KOVASI: açılış vadesine göre kırılımdır ve aynı kalemin Toplam sütununun "
                          "toplanabilir parçasıdır; altı kovanın toplamı Toplam'a eşittir (kaynak her sütunu "
                          "yuvarladığı için en çok ±3 milyon TL fark, 2026-09-23 ölçümü; ADR-0108).")
            entries.append(ENTRY.format(
                series_id=series_id,
                native_code=kalem_sutun,
                dataset_id=f"bddk_monthly_{slug(name)[:40].rstrip('_')}_{item['native_code']}_{slug(column_suffix)}",
                name_tr=json.dumps(f"{display} ({group}, Sektör)", ensure_ascii=False),
                group=group,
                item=name,
                column_label=" ".join(column_label.split()),
                shape_note=SHAPE_NOTES.get(measure_type, ""),
                unit=unit,
                title=(probe.get("title") or "—").replace('"', "'")[:110],
                probed_on=probed_on,
                id_note=("kaynağın kendi kalem kimliği ve sütun adıdır, seri kimliğinin "
                         "dayanağıdır. taraf=10001 (Sektör), paraBirimi=TL, periyot=1."),
                extra_note=(extra + (f"\n      {rule.note}" if rule and rule.note else "")),
                aliases="\n".join(f"      - {a}" for a in
                                  aliases_for(name, group, column_label, is_primary)),
                tags=", ".join(rule.tags if rule else BALANCE),
                measure_type=measure_type,
                default_agg=default_agg,
                cumulative=cumulative,
                status=status,
            ))
            stats["yazildi"] += 1

    return entries, stats


_BLOCK_START = re.compile(r"^  - series_id: (\S+)\s*$", re.M)


def _blocks(catalog_text: str) -> dict[str, tuple[int, int]]:
    """series_id -> (start, end) character span of its entry in the catalog text."""

    starts = [(m.group(1), m.start()) for m in _BLOCK_START.finditer(catalog_text)]
    spans: dict[str, tuple[int, int]] = {}
    for index, (series_id, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(catalog_text)
        spans[series_id] = (start, end)
    return spans


def add_group_columns(catalog_text: str, items: list[dict], *, group: str,
                      probed_on: str) -> tuple[str, dict[str, int]]:
    """Insert one group's missing non-primary columns after each item's primary entry.

    Nothing that is already in the catalog changes: the result minus the inserted entries is
    the input byte for byte, which the caller re-checks. Idempotent: a second run adds nothing.
    """

    stats = {"eklendi": 0, "zaten_var": 0, "ana_giris_aktif_degil": 0}
    spans = _blocks(catalog_text)
    existing = set(spans)
    insertions: list[tuple[int, str]] = []
    for item in (it for it in items if it.get("group") == group):
        entries, _ = build([item], columns_mode="all", existing_ids=set(), probed_on=probed_on)
        by_id = {e.split("\n", 1)[0].split("series_id:", 1)[1].strip(): e for e in entries}
        # The primary column is the group rule's, exactly as the primary-only catalog chose it.
        primary, _ = build([item], columns_mode="primary", existing_ids=set(), probed_on=probed_on)
        primary_id = primary[0].split("\n", 1)[0].split("series_id:", 1)[1].strip() if primary else None
        if primary_id is None or primary_id not in existing:
            raise SystemExit(f"{item['native_code']}: ana giriş {primary_id} katalogda yok; "
                             "tahmin edilmez, durduruldu.")
        start, end = spans[primary_id]
        if not re.search(r"^    status: active\s*$", catalog_text[start:end], re.M):
            stats["ana_giris_aktif_degil"] += 1
            continue
        new = [e for sid, e in by_id.items() if sid not in existing]
        stats["zaten_var"] += len(by_id) - 1 - len(new)
        if new:
            # Keep the source's column order after the primary: insert after the last existing
            # column of this item, so a partial earlier run is completed in place.
            present = [spans[sid] for sid in by_id if sid in existing]
            end = max(span_end for _, span_end in present)
        if new:
            # Generated entries are separated by one blank line; the new ones keep that shape.
            insertions.append((end, "".join(e.rstrip("\n") + "\n\n" for e in new)))
            stats["eklendi"] += len(new)
    out = catalog_text
    for position, text in sorted(insertions, reverse=True):
        head = out[:position]
        if not head.endswith("\n\n"):
            head = head.rstrip("\n") + "\n\n"
        tail = out[position:]
        out = head + (text if tail else text.rstrip("\n") + "\n") + tail
    return out, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, required=True, help="probe script'inin --out çıktısı")
    parser.add_argument("--columns", choices=("primary", "all"), default="primary",
                        help="primary: kalem başına ana sütun; all: kaynağın bildirdiği her sütun")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--group", help="--add-columns ile: yalnız bu tablo grubu")
    parser.add_argument("--add-columns", action="store_true",
                        help="grubun eksik sütunlarını ana girişin arkasına ekle; başka hiçbir şeyi değiştirme")
    parser.add_argument("--probed-on", default="2026-09-16", help="birim yoklamasının tarihi (YYYY-AA-GG)")
    args = parser.parse_args()

    if args.add_columns:
        if not args.group:
            parser.error("--add-columns için --group gerekli")
        items = json.loads(args.items.read_text(encoding="utf-8"))
        original = CATALOG_PATH.read_text(encoding="utf-8")
        updated, stats = add_group_columns(original, items, group=args.group, probed_on=args.probed_on)
        for key, value in stats.items():
            print(f"   {key:22} {value}")
        # Invariant: every original byte survives, in order; only whole entries were inserted.
        before, after = _blocks(original), _blocks(updated)
        for series_id, (start, end) in before.items():
            new_start, new_end = after[series_id]
            if updated[new_start:new_end].rstrip("\n") != original[start:end].rstrip("\n"):
                raise SystemExit(f"değişmemesi gereken giriş değişti: {series_id}; yazılmadı")
        if updated.split(MARKER)[0] != original.split(MARKER)[0]:
            raise SystemExit("elle yazılmış bölüm değişti; yazılmadı")
        if args.dry_run:
            print("\n--dry-run: dosya yazılmadı.")
            return 0
        CATALOG_PATH.write_text(updated, encoding="utf-8")
        print(f"\nyazıldı -> {CATALOG_PATH.relative_to(_REPO_ROOT)}")
        return 0

    items = json.loads(args.items.read_text(encoding="utf-8"))
    existing_text = CATALOG_PATH.read_text(encoding="utf-8")
    entries, stats = build(items, columns_mode=args.columns,
                           existing_ids=hand_written_ids(existing_text))

    print(f"{len(entries)} katalog girişi üretildi ({args.columns} sütun kipi)")
    for key, value in stats.items():
        print(f"   {key:22} {value}")

    existing = CATALOG_PATH.read_text(encoding="utf-8").rstrip("\n")
    catalog = existing.split(MARKER)[0] + MARKER + "\n" + "\n".join(entries)

    if args.dry_run:
        print("\n--dry-run: dosya yazılmadı. İlk giriş:\n")
        print(entries[0] if entries else "(giriş yok)")
        return 0

    CATALOG_PATH.write_text(catalog + "\n", encoding="utf-8")
    print(f"\nyazıldı -> {CATALOG_PATH.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
