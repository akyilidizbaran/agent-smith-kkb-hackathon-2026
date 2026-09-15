"""Kart önizleme kuralı (core/preview): ≤24 satır tamamı; üstünde baş + açık kesme işareti + son + toplam (PART 41)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.preview import FULL_ROWS, preview_table  # noqa: E402


def _months(n: int) -> pd.DataFrame:
    d = pd.date_range("2024-01-31", periods=n, freq="ME")
    return pd.DataFrame({"donem": d.strftime("%Y-%m-%d"), "toplam": [1000 + i for i in range(n)]})


def test_on_iki_satir_tamami_gosterilir_son_ay_dahil() -> None:
    # A15/A06/A24 kök nedeni: 12 satırın 10'u gösterilince model Kasım–Aralık'ı "yok" sanıyordu.
    text = preview_table(_months(12))
    assert text.startswith("Satırlar (12, tamamı):") and "2024-12-31" in text and "GÖSTERİLMEDİ" not in text


def test_yirmi_dort_satir_sinir_dahil() -> None:
    text = preview_table(_months(FULL_ROWS))
    assert "tamamı" in text and "2025-12-31" in text


def test_buyuk_tablo_bas_son_ve_acik_kesme_isareti() -> None:
    text = preview_table(_months(60), where="bu sorgunun sonucunda")
    assert "İlk 10 satır:" in text and "Son 5 satır:" in text and "Toplam 60 satır." in text
    assert "… (45 satır GÖSTERİLMEDİ; tamamı bu sorgunun sonucunda" in text
    assert "2024-01-31" in text and "2028-12-31" in text            # baş ve son satır görünür
    assert "2026-06-30" not in text                                   # orta satır gösterilmez


def test_ozel_bicimleyici_kullanilir() -> None:
    text = preview_table(_months(3), render=lambda f: "|".join(map(str, f["toplam"])))
    assert text.endswith("1000|1001|1002")
