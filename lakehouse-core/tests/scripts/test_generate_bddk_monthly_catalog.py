"""`generate_bddk_monthly_catalog.py --add-columns` (ADR-0108): one group's columns are inserted
after each item's primary entry; nothing already in the catalog changes; a second run adds nothing."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import generate_bddk_monthly_catalog as gen  # noqa: E402

GROUP = "Mevduat Vade İtibarıyla"
COLUMNS = [["520?Vadesiz", "Vadesiz"], ["520?BirAyaKadar", "1 Aya Kadar"], ["520?BirYil", "1  Yıl Üzeri"],
           ["520?Toplam", "Toplam"]]


def _item(code: str, columns: list[list[str]]) -> dict:
    return {
        "group": GROUP, "native_code": code, "all_ids": [code],
        "option_label": f"{GROUP}-1 Test Kalemi {code}",
        "source_name": f"{GROUP} - 1   Test Kalemi {code} (milyon TL)",
        "columns": [[c.replace("520", code), label] for c, label in columns],
        "probe": {"ok": True, "unit": "TRY_mn", "title": f"{GROUP} - Test (milyon TL)", "empty": False},
    }


def _catalog(items: list[dict], statuses: dict[str, str]) -> str:
    entries, _ = gen.build(items, columns_mode="primary", existing_ids=set())
    entries = [re.sub(r"status: \w+", f"status: {statuses.get(e.split('series_id: ')[1].split(chr(10))[0], 'active')}", e)
               for e in entries]
    head = 'catalog_schema_version: "1.0"\nsource_id: bddk_monthly\n\nseries:\n  - series_id: bddk_monthly:1_Toplam\n'
    return head + gen.MARKER + "\n" + "\n".join(entries) + "\n"


def test_add_columns_inserts_only_new_entries_after_their_primary() -> None:
    items = [_item("520", COLUMNS), _item("521", COLUMNS)]
    original = _catalog(items, {})

    updated, stats = gen.add_group_columns(original, items, group=GROUP, probed_on="2026-09-23")

    assert stats == {"eklendi": 6, "zaten_var": 0, "ana_giris_aktif_degil": 0}
    order = re.findall(r"^  - series_id: (\S+)", updated, re.M)
    assert order[order.index("bddk_monthly:520_Toplam") + 1:order.index("bddk_monthly:521_Toplam")] == [
        "bddk_monthly:520_Vadesiz", "bddk_monthly:520_BirAyaKadar", "bddk_monthly:520_BirYil"]
    # Removing the inserted entries gives back the original, byte for byte.
    spans = gen._blocks(updated)
    stripped = updated
    for sid in sorted((s for s in spans if s not in gen._blocks(original)), key=lambda s: spans[s][0], reverse=True):
        start, end = spans[sid]
        stripped = stripped[:start] + stripped[end:]
    assert stripped == original
    block = updated[spans["bddk_monthly:520_BirYil"][0]:spans["bddk_monthly:520_BirYil"][1]]
    assert "2026-09-23 canlı yoklaması" in block and "VADE KOVASI" in block
    assert "- test kalemi 520\n" not in block, "kova, kalemin çıplak adını takma ad olarak almaz"

    again, stats = gen.add_group_columns(updated, items, group=GROUP, probed_on="2026-09-23")
    assert again == updated and stats["eklendi"] == 0 and stats["zaten_var"] == 6


def test_add_columns_skips_items_whose_primary_is_not_active() -> None:
    items = [_item("729", COLUMNS)]
    original = _catalog(items, {"bddk_monthly:729_Toplam": "deprecated"})

    updated, stats = gen.add_group_columns(original, items, group=GROUP, probed_on="2026-09-23")

    assert updated == original and stats["ana_giris_aktif_degil"] == 1


def test_add_columns_refuses_when_primary_entry_is_missing() -> None:
    original = _catalog([_item("520", COLUMNS)], {})
    with pytest.raises(SystemExit):
        gen.add_group_columns(original, [_item("999", COLUMNS)], group=GROUP, probed_on="2026-09-23")
