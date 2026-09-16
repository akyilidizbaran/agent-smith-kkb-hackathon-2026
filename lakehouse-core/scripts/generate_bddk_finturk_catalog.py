"""Generate BDDK FinTürk catalog entries for the province tables, from the live source.

The catalogued FinTürk series all come from one table: ``tabloNo=3`` (Bireysel Bankacılık),
because that is the one verified to carry Konut Kredisi. The endpoint publishes six more
tables for the same 81 provinces and the same quarters, and a single request returns **every
measure column of a table at once** — so a table's breadth is free once its 81×22 requests
are paid for.

This script asks the source what each table contains instead of assuming it:

* ``GET /BultenFinTurk`` renders the table selector, and each option states the table's unit:
  "Krediler (Bin TL)", "Mevduat (Bin TL)", "Seçilmiş Sektörel Krediler (Bin TL)",
  "Şubeler (Adet) ve Nüfusa Göre Dağılım (TL)".
* ``POST /BultenFinturk/tr/Home/VeriGetir`` for one province and quarter returns the table's
  ``colModels``; everything after the five identity columns is a measure column.

Scope (chosen 2026-09-16): tables 1 (Krediler), 2 (Mevduat), 4 (Seçilmiş Sektörel Krediler)
and 6 (Şubeler / Nüfusa Göre Dağılım), party ``10001`` (Sektör). Table 3 is already
catalogued and is left untouched. Table 5 (Oranlar) is skipped because those ratios are
derivable from tables 1-4, and table 7 (Altın) is skipped as off-subject; both stay one
constant away if that changes.

Units are the source's own, per table, with the one table that mixes them split per column:
table 6's ``SubeSayisi`` and ``SubeyeDusenNufus`` are counts while its ``KisiBasi*`` columns
are TL per person. That reading is arithmetically confirmed for ANKARA 2025-09: 982 şube ×
4.867 kişi/şube = 4,78 milyon kişi, and 595.699,42 TL/kişi × 4,78 milyon = 2,85 trilyon TL,
which is table 1's ``ToplamNakdiKrediler`` for the same province and quarter (2.892.401.068
bin TL) to within the rounding the source itself publishes.

The fetch path needs one more fact the catalog cannot carry: which ``tabloNo`` a series comes
from. The endpoint takes the table number, not the column, so this script also writes
``scripts/bddk_finturk_table_map.json`` (measure column -> table number), which
``scripts/ingestion_registry.py`` reads. It is generated from the probe above, not written by
hand.

Usage (from lakehouse-core/):

    uv run python scripts/generate_bddk_finturk_catalog.py --dry-run
    uv run python scripts/generate_bddk_finturk_catalog.py
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import requests
import truststore

_REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = _REPO_ROOT / "catalog" / "series" / "bddk_finturk.yml"
TABLE_MAP_PATH = Path(__file__).resolve().parent / "bddk_finturk_table_map.json"

BASE_URL = "https://www.bddk.org.tr"
PAGE_PATH = "/BultenFinTurk"
DATA_PATH = "/BultenFinturk/tr/Home/VeriGetir"
USER_AGENT = "kkb-lakehouse/0.1 (KKB Hackathon 2026)"

PROBE_PROVINCE, PROBE_PERIOD = "ANKARA", "2025-9"
IDENTITY_COLUMNS = ("EftKodu", "Yil", "Ay", "Sehir", "Grup")

MARKER = "\n  # --- üretilmiş: BDDK FinTürk, Krediler / Mevduat / Sektörel / Şubeler tabloları ---\n"

ALREADY_CATALOGUED_TABLE = "3"
"""Bireysel Bankacılık: hand-written entries stay as they are."""


@dataclass(frozen=True)
class TableRule:
    """What a FinTürk table means. Units come from the source's own selector label."""

    number: str
    name: str
    unit: str
    measure_type: str
    default_agg: str
    tags: tuple[str, ...]
    subject: str                      # how a person would name the thing, for aliases
    column_units: dict[str, tuple[str, str, str]] = None  # column -> (unit, measure_type, agg)
    dataset_suffix: str = ""
    """One dataset per province × table, shared by every column of that table.

    A dataset is the unit one request produces, and one FinTürk request returns every column
    of a table: the ingestion runner fetches it once and the Bronze artifact carries a single
    dataset_id. Silver rejects a row whose catalog dataset_id differs from its artifact's, so
    all of a table's columns must declare the same one. Table 3 already works this way (all
    eight columns of a province share ``bddk_finturk_<il>_housing_loans``); giving each column
    its own dataset_id made the first Silver build after a one-province trial fail outright.
    """


TABLES: tuple[TableRule, ...] = (
    TableRule("1", "Krediler", "TRY_th", "stock", "last",
              ("kredi", "bankacilik", "bddk", "il", "stok"), "kredi",
              dataset_suffix="krediler"),
    TableRule("2", "Mevduat", "TRY_th", "stock", "last",
              ("mevduat", "bankacilik", "bddk", "il", "stok"), "mevduat",
              dataset_suffix="mevduat"),
    TableRule("4", "Seçilmiş Sektörel Krediler", "TRY_th", "stock", "last",
              ("kredi", "sektorel", "bankacilik", "bddk", "il", "stok"), "sektör kredisi",
              dataset_suffix="sektorel_krediler"),
    TableRule("6", "Şubeler ve Nüfusa Göre Dağılım", "TRY", "ratio", "last",
              ("sube", "nufus", "bankacilik", "bddk", "il"), "şube ve kişi başı",
              column_units={
                  "SubeSayisi": ("adet", "count", "last"),
                  "SubeyeDusenNufus": ("adet", "count", "last"),
              },
              dataset_suffix="subeler_nufus"),
)

_TR_ASCII = str.maketrans(
    {"İ": "I", "I": "I", "ı": "i", "Ş": "S", "ş": "s", "Ğ": "G", "ğ": "g",
     "Ü": "U", "ü": "u", "Ö": "O", "ö": "o", "Ç": "C", "ç": "c"}
)

_PARSER_TR_ASCII = str.maketrans({"İ": "I", "Ş": "S", "Ğ": "G", "Ü": "U", "Ö": "O", "Ç": "C", "ı": "i"})
"""The parser's own map (src/lakehouse/parsers/bddk_finturk.py); series_id must match it."""

# Column name -> everyday Turkish, so search phrases read like a question, not a field name.
COLUMN_WORDS: dict[str, str] = {
    "ToplamNakdiKrediler": "toplam nakdi kredi", "NakdiKrediler": "nakdi kredi",
    "TakiptekiAlacaklar": "takipteki alacak", "GayrinakdiKrediler": "gayrinakdi kredi",
    "TasarrufMevduati": "tasarruf mevduatı", "ToplamMevduat": "toplam mevduat",
    "DigerMevduat": "diğer mevduat",
    "SubeSayisi": "şube sayısı", "SubeyeDusenNufus": "şubeye düşen nüfus",
    "KisiBasiNakdiKredi": "kişi başı nakdi kredi",
    "KisiBasiTakiptekiAlacak": "kişi başı takipteki alacak",
    "KisiBasiTasarrufMevduati": "kişi başı tasarruf mevduatı",
    "KisiBasiToplamMevduat": "kişi başı toplam mevduat",
}


def slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKC", value).translate(_TR_ASCII)
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_") or "x"


def series_key(province: str, column: str) -> str:
    """The identifier the parser will derive for this row, character for character.

    ``native_code`` keeps the source's own Turkish spelling (ÇORUM), but ``series_id`` is
    restricted to ASCII by the shared contract, and the parser transliterates the response's
    ``Sehir`` field with exactly this map before matching a catalog row. Generating the key
    any other way produces entries the parser can never match.
    """

    transliterated = f"{province}_{column}".translate(_PARSER_TR_ASCII)
    return re.sub(r"[^A-Za-z0-9]+", "_", transliterated).strip("_")


def spaced(column: str) -> str:
    """"TasarrufMevduatiTurkLirasi" -> "tasarruf mevduati turk lirasi" for search phrases."""

    if column in COLUMN_WORDS:
        return COLUMN_WORDS[column]
    return re.sub(r"(?<!^)(?=[A-Z])", " ", column).lower()


def session() -> requests.Session:
    truststore.inject_into_ssl()
    client = requests.Session()
    client.headers["User-Agent"] = USER_AGENT
    return client


def selector_labels(client: requests.Session) -> dict[str, str]:
    """tabloNo -> the source's own label, which states the table's unit."""

    page = client.get(f"{BASE_URL}{PAGE_PATH}", timeout=60)
    page.raise_for_status()
    labels: dict[str, str] = {}
    for number, raw in re.findall(r'<option[^>]*value="(\d)"[^>]*>(.*?)</option>', page.text, re.S):
        label = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        if label:
            labels[number] = label
    return labels


def measure_columns(client: requests.Session, tablo_no: str) -> list[str]:
    """Measure columns of one table, as the source lists them."""

    response = client.post(
        f"{BASE_URL}{DATA_PATH}",
        data={"sehirList[0]": PROBE_PROVINCE, "tarafList[0]": "10001",
              "tabloNo": tablo_no, "donem": PROBE_PERIOD},
        timeout=90,
    )
    response.raise_for_status()
    body = response.json().get("Json") or response.json()
    names = [str(c.get("name")) for c in (body.get("colModels") or [])]
    return [n for n in names if n not in IDENTITY_COLUMNS]


def provinces() -> list[str]:
    """The 81 provinces already proven fetchable (81/81, docs/sources/bddk_finturk.md)."""

    text = CATALOG_PATH.read_text(encoding="utf-8")
    found = {m.rsplit("_", 1)[0] for m in re.findall(r"native_code:\s*([A-ZÇĞİÖŞÜ_]+_\w+)", text)}
    return sorted(found)


ENTRY = """  - series_id: bddk_finturk:{series_key}
    native_code: {native_code}
    dataset_id: {dataset_id}
    name_tr: {name_tr}
    description: >-
      BDDK FinTürk (İllere Göre), {table_name} tablosu (tabloNo={tablo_no}), "{column}" sütunu,
      {province} ili, Sektör tarafı. {shape_note}
      FREKANS NÜANSI: kaynak çeyreklik yayınlanıyor (Mart/Haziran/Eylül/Aralık), aylık değil —
      bkz. docs/sources/bddk_finturk.md.
      BİRİM: {unit} — kaynağın kendi tablo seçicisi bu tabloyu "{selector_label}" diye
      etiketliyor.{unit_extra}
      KİMLİK: sütun adı kaynağın kendi kolon adıdır; tabloNo eşlemesi
      scripts/bddk_finturk_table_map.json içinde üretilmiş olarak tutulur.
      Bu giriş scripts/generate_bddk_finturk_catalog.py ile üretildi; kalem tek tek insan
      tarafından incelenmediği için semantic_confidence 'derived'.
    aliases:
{aliases}
    tags: [{tags}]
    frequency: quarterly
    unit: {unit}
    measure_type: {measure_type}
    default_agg: {default_agg}
    semantic_confidence: derived
    semantic_source: source_docs
    metadata_url: https://www.bddk.org.tr/BultenFinTurk
    status: active
"""

SHAPE_NOTES = {
    "stock": "Dönem sonu bakiyesidir (stok): dönemler toplanmaz, daha düşük frekansa "
             "indirilirken dönemin son değeri alınır.",
    "count": "Dönem sonu sayımıdır: dönemler toplanmaz, son değer alınır.",
    "ratio": "Kişi başına düşen tutardır: dönemler toplanmaz, iller de toplanmaz; "
             "son değer alınır.",
}

UNIT_EXTRA = {
    "6": (" Tablo iki birim taşıyor: şube ve nüfus sütunları adet, kişi başı sütunları TL. "
          "2025-09 ANKARA aritmetiği bunu doğruluyor: 982 şube × 4.867 kişi = 4,78 milyon "
          "kişi ve 595.699,42 TL/kişi × 4,78 milyon = 2,85 trilyon TL, tablo 1'in aynı il ve "
          "çeyrek için verdiği toplam nakdi krediyle örtüşüyor."),
}


def aliases_for(province: str, column: str, rule: TableRule) -> list[str]:
    place = province.translate(_TR_ASCII).lower() if province.isupper() else province.lower()
    place = province.lower().replace("i̇", "i")
    thing = spaced(column)
    out = [f"{place} {thing}", f"{place} ili {thing}", f"{thing} {place}"]
    if rule.number == "4":
        out.append(f"{place} {thing} sektörüne açılan kredi")
    if rule.number == "2":
        out.append(f"{place} mevduat")
    seen: list[str] = []
    for phrase in out:
        cleaned = " ".join(phrase.split())
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen[:5]


def build(client: requests.Session) -> tuple[list[str], dict[str, str], dict[str, int]]:
    labels = selector_labels(client)
    province_list = provinces()
    entries: list[str] = []
    table_map: dict[str, str] = {}
    stats = {"tablo": 0, "sutun": 0, "giris": 0, "il": len(province_list)}

    for rule in TABLES:
        columns = measure_columns(client, rule.number)
        stats["tablo"] += 1
        stats["sutun"] += len(columns)
        selector = labels.get(rule.number, rule.name)
        print(f"  tabloNo={rule.number} «{selector}» · {len(columns)} ölçü sütunu", file=sys.stderr)
        for column in columns:
            table_map[column] = rule.number
            unit, measure_type, default_agg = (rule.column_units or {}).get(
                column, (rule.unit, rule.measure_type, rule.default_agg))
            for province in province_list:
                native = f"{province}_{column}"
                entries.append(ENTRY.format(
                    native_code=native,
                    series_key=series_key(province, column),
                    dataset_id=f"bddk_finturk_{slug(province)}_{rule.dataset_suffix}",
                    name_tr=json.dumps(
                        f"{spaced(column).capitalize()}, {province} ({rule.name}, Sektör)",
                        ensure_ascii=False),
                    table_name=rule.name,
                    tablo_no=rule.number,
                    column=column,
                    province=province,
                    shape_note=SHAPE_NOTES.get(measure_type, ""),
                    unit=unit,
                    selector_label=selector,
                    unit_extra=UNIT_EXTRA.get(rule.number, ""),
                    aliases="\n".join(f"      - {a}" for a in aliases_for(province, column, rule)),
                    tags=", ".join(rule.tags),
                    measure_type=measure_type,
                    default_agg=default_agg,
                ))
                stats["giris"] += 1
        time.sleep(0.3)
    return entries, table_map, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = session()
    entries, table_map, stats = build(client)

    print(f"\n{stats['giris']} katalog girişi · {stats['tablo']} tablo × {stats['sutun']} sütun "
          f"× {stats['il']} il")
    print(f"tablo eşlemesi: {len(table_map)} sütun")

    existing = CATALOG_PATH.read_text(encoding="utf-8").rstrip("\n")
    catalog = existing.split(MARKER)[0] + MARKER + "\n" + "\n".join(entries)

    if args.dry_run:
        print("\n--dry-run: dosya yazılmadı. İlk giriş:\n")
        print(entries[0] if entries else "(giriş yok)")
        return 0

    CATALOG_PATH.write_text(catalog + "\n", encoding="utf-8")
    TABLE_MAP_PATH.write_text(
        json.dumps(table_map, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"\nyazıldı -> {CATALOG_PATH.name}, {TABLE_MAP_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
