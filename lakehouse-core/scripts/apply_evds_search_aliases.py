"""Give the generated EVDS entries search phrases, so retrieval can actually find them.

``scripts/evds_catalog_generator.py`` writes what EVDS's metadata gives it: the series' own
name and nothing else. For a lot of groups that name does not say what the series measures.
``evds:TP.KFE.TR10`` is called ``TR10 (İstanbul)`` — the words "konut fiyat endeksi" appear
nowhere in the entry, so an agent asked for "İstanbul konut fiyat endeksi" cannot match it
by name, alias or tag. 1.224 of the generated entries carry no alias at all.

What is missing is the *group's* subject, which EVDS does publish, on the data group rather
than on the series (``/datagroups``: ``bie_kfe`` -> "Konut Fiyat Endeksi"). This script joins
the two: for every group it knows, it states the subject in the words a Turkish speaker would
use, works out which part of the series name distinguishes this series from its siblings, and
writes the combinations as aliases plus a few subject words as tags.

Nothing is invented about the data. The subject comes from EVDS's own group name; the
distinguishing part comes from the series' own name; ``semantic_confidence`` is untouched and
stays ``derived``. Entries that already have hand-written aliases are never rewritten.

Usage (from lakehouse-core/):

    uv run python scripts/apply_evds_search_aliases.py --dry-run
    uv run python scripts/apply_evds_search_aliases.py
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = _REPO_ROOT / "catalog" / "series" / "evds.yml"


@dataclass(frozen=True)
class GroupRule:
    """How to phrase one EVDS data group's series for search.

    ``subject`` is the group's own subject in everyday Turkish; ``shape`` says where the
    distinguishing part of the series name is; ``extra`` are further words people use for the
    same thing (an abbreviation, a synonym); ``tags`` are added to the entry's tag list.
    """

    subject: str
    shape: str
    extra: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    qualifier: str = ""


# dataset_id -> rule. Subjects are EVDS's own group names (/datagroups, fetched 2026-09-15),
# rephrased only where the official name is longer than what anyone would type.
RULES: dict[str, GroupRule] = {
    # "TR10 (İstanbul)" — the measured thing is nowhere in the name.
    "evds_bie_kfe": GroupRule(
        "konut fiyat endeksi", "parens", ("KFE", "ev fiyat endeksi"),
        ("fiyat", "endeks", "bolgesel"),
    ),
    "evds_bie_ykke": GroupRule(
        "yeni kiracı kira endeksi", "parens", ("YKKE", "kira endeksi"),
        ("kira", "endeks", "bolgesel"),
    ),
    # "Adana_Konut_Toplam Satışlar" — place and kind are underscore separated.
    "evds_bie_akonutsat1": GroupRule(
        "satışları", "underscore", ("toplam satış", "satış adedi"), ("satis", "adet"),
        qualifier="toplam",
    ),
    "evds_bie_akonutsat2": GroupRule(
        "satışları", "underscore", ("ipotekli satış", "mortgage satış"),
        ("satis", "adet", "ipotek"), qualifier="ipotekli",
    ),
    "evds_bie_akonutsat3": GroupRule(
        "satışları", "underscore", ("ilk el satış", "sıfır konut satışı"),
        ("satis", "adet"), qualifier="ilk el",
    ),
    "evds_bie_akonutsat4": GroupRule(
        "satışları", "underscore", ("ikinci el satış", "ikinci el konut satışı"),
        ("satis", "adet"), qualifier="ikinci el",
    ),
    # "İstanbul Konut Birim Fiyatları" — self-describing; add how people actually ask.
    "evds_bie_birimfiyat": GroupRule(
        "konut birim fiyatı", "prefix",
        ("metrekare fiyatı", "m2 fiyatı", "konut fiyatı TL/m2"), ("fiyat", "m2"),
    ),
    "evds_bie_bk": GroupRule(
        "konut birim kirası", "prefix",
        ("metrekare kirası", "m2 kirası", "kira TL/m2"), ("kira", "m2"),
    ),
    # "Konut Kredisi (TL, Stok, %)" — says which loan, never says "faiz".
    "evds_bie_kt210a": GroupRule(
        "kredi faiz oranı", "parens_strip", ("faiz oranı stok", "kredi faizi"),
        ("faiz", "oran", "stok"),
    ),
    "evds_bie_kt100h": GroupRule(
        "kredi faiz oranı", "parens_strip", ("faiz oranı akım", "kredi faizi"),
        ("faiz", "oran", "akim"),
    ),
    # "0111. Tahıllar Ve Tahıl Ürünleri" — a COICOP line of the CPI basket.
    "evds_bie_tukfiy2025": GroupRule(
        "tüketici fiyat endeksi", "code_prefix", ("TÜFE", "enflasyon", "fiyat endeksi"),
        ("tufe", "enflasyon", "fiyat"),
    ),
    "evds_bie_ykfe": GroupRule(
        "yeni konutlar fiyat endeksi", "whole", ("YKFE",), ("fiyat", "endeks"),
    ),
    "evds_bie_yokfend": GroupRule(
        "yeni olmayan konutlar fiyat endeksi", "whole", ("YOKFE", "ikinci el konut fiyat endeksi"),
        ("fiyat", "endeks"),
    ),
}


def distinguishing_part(name: str, shape: str) -> tuple[str, str]:
    """Return (place-or-subject part, kind part) pulled out of the series' own name."""

    name = name.strip()
    if shape == "parens":
        # "TR10 (İstanbul)" -> "İstanbul"; "TR21 (Edirne, Kırklareli, Tekirdağ)" -> as written.
        inside = re.search(r"\(([^)]*)\)", name)
        return (inside.group(1).strip() if inside else name, "")
    if shape == "underscore":
        # "Adana_Konut_Toplam Satışlar" -> ("Adana", "Konut")
        parts = [part.strip() for part in name.split("_")]
        place = parts[0] if parts else name
        kind = parts[1] if len(parts) > 1 else ""
        return (place, kind)
    if shape == "prefix":
        # "İstanbul Konut Birim Fiyatları" -> "İstanbul"
        return (name.split()[0] if name.split() else name, "")
    if shape == "parens_strip":
        # "Konut Kredisi (TL, Stok, %)" -> "Konut Kredisi"
        return (re.sub(r"\s*\([^)]*\)", "", name).strip(), "")
    if shape == "code_prefix":
        # "0111. Tahıllar Ve Tahıl Ürünleri" -> "Tahıllar Ve Tahıl Ürünleri"
        return (re.sub(r"^[\d.]+\s*", "", name).strip(), "")
    return (name, "")


def tr_lower(value: str) -> str:
    """Lowercase the Turkish way.

    ``"İSTANBUL".lower()`` gives ``"i̇stanbul"`` in Python — a plain ``i`` followed by a
    combining dot — because the dotted capital has no single-codepoint lowercase in the
    default mapping. An alias spelled that way never matches a user typing "istanbul".
    """

    return value.replace("İ", "i").replace("I", "ı").lower()


def phrases_for(name: str, rule: GroupRule) -> list[str]:
    """Search phrases for one series: what it measures, combined with what sets it apart."""

    part, kind = distinguishing_part(name, rule.shape)
    part = part.strip()
    if not part:
        return []

    subject = rule.subject
    if rule.shape == "underscore":
        # "Adana" + kind "Konut"/"İş Yeri" + qualifier "ipotekli" -> "Adana ipotekli konut satışları"
        thing = f"{tr_lower(kind)} {subject}".strip() if kind else subject
        subject = f"{rule.qualifier} {thing}".strip() if rule.qualifier else thing

    if rule.shape == "whole":
        out = [subject, *(tr_lower(alternative) for alternative in rule.extra)]
    else:
        # A regional aggregate names several provinces ("Edirne, Kırklareli, Tekirdağ"). One
        # comma-joined alias matches none of them on their own, so each province also gets
        # its own phrase while the aggregate keeps a combined one.
        places = [piece.strip() for piece in part.split(",") if piece.strip()]
        out = []
        for place in places:
            lowered = tr_lower(place)
            # "Konut Kredisi" + "kredi faiz oranı" would read "konut kredisi kredi faiz
            # oranı". Turkish suffixes make an equality test useless ("kredisi" != "kredi"),
            # so the overlap is caught by prefix: drop the subject's leading word when a word
            # of the name already starts with it.
            head, _, tail = subject.partition(" ")
            if tail and any(word.startswith(head) for word in lowered.split()):
                subject = tail
            out.append(f"{lowered} {subject}")
            for alternative in rule.extra:
                out.append(f"{lowered} {tr_lower(alternative)}")
        if len(places) == 1:
            out.append(f"{subject} {tr_lower(places[0])}")

    deduped: list[str] = []
    for phrase in out:
        cleaned = " ".join(phrase.split())
        if cleaned and cleaned != tr_lower(name.strip()) and cleaned not in deduped:
            deduped.append(cleaned)
    # A single place keeps its handful of phrasings; an aggregate of n provinces needs room
    # for each of them, so the cap grows with the number of places rather than being fixed.
    return deduped[: max(5, 3 * len(part.split(",")))]


@dataclass
class Block:
    lines: list[str] = field(default_factory=list)

    def value(self, key: str) -> str | None:
        for line in self.lines:
            # series_id sits on the entry's own "  - series_id:" line; the rest are indented.
            if line.startswith(f"    {key}:") or line.startswith(f"  - {key}:"):
                return line.split(":", 1)[1].strip()
        return None

    def has(self, key: str) -> bool:
        return any(line.startswith(f"    {key}:") for line in self.lines)


def split_entries(lines: list[str]) -> tuple[list[str], list[Block]]:
    starts = [index for index, line in enumerate(lines) if line.startswith("  - series_id:")]
    header = lines[: starts[0]] if starts else lines
    bounds = starts + [len(lines)]
    return header, [Block(lines[bounds[i] : bounds[i + 1]]) for i in range(len(starts))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    lines = CATALOG.read_text(encoding="utf-8").splitlines(keepends=True)
    header, blocks = split_entries(lines)

    touched = 0
    skipped_no_rule: dict[str, int] = {}
    samples: list[tuple[str, list[str]]] = []

    for block in blocks:
        dataset_id = block.value("dataset_id")
        name = block.value("name_tr")
        if block.has("aliases") or not dataset_id or not name:
            continue
        rule = RULES.get(dataset_id)
        if rule is None:
            skipped_no_rule[dataset_id] = skipped_no_rule.get(dataset_id, 0) + 1
            continue
        clean_name = name.strip().strip('"')
        phrases = phrases_for(clean_name, rule)
        if not phrases:
            continue

        alias_lines = ["    aliases:\n"] + [f"      - {phrase}\n" for phrase in phrases]
        for index, line in enumerate(block.lines):
            if line.startswith("    tags:"):
                existing = re.findall(r"[\w-]+", line.split(":", 1)[1])
                merged = list(dict.fromkeys(existing + list(rule.tags)))
                block.lines[index] = f"    tags: [{', '.join(merged)}]\n"
                block.lines[index:index] = alias_lines
                break
        else:
            continue
        touched += 1
        if len(samples) < 6:
            samples.append((block.value("series_id") or "?", phrases))

    print(f"{touched} girişe alias yazıldı")
    if skipped_no_rule:
        print("kuralı olmayan gruplar (dokunulmadı):")
        for dataset_id, count in sorted(skipped_no_rule.items(), key=lambda kv: -kv[1]):
            print(f"  {dataset_id}: {count}")
    print()
    for series_id, phrases in samples:
        print(f"  {series_id}")
        for phrase in phrases:
            print(f"      - {phrase}")

    if args.dry_run:
        print("\n--dry-run: dosya yazılmadı.")
        return 0

    out = list(header)
    for block in blocks:
        out.extend(block.lines)
    CATALOG.write_text("".join(out), encoding="utf-8")
    print(f"\nyazıldı -> {CATALOG.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
