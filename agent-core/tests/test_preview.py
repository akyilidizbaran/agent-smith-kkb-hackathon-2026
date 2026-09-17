"""Kart önizleme kuralı (core/preview): ≤24 satır tamamı; üstünde baş + açık kesme işareti + son + toplam (PART 41)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.grounding import grounding_check  # noqa: E402
from kkb_agent.core.preview import FULL_ROWS, preview_table, span_summary  # noqa: E402


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


# --- span_summary: ilk → son farkını harness hesaplar (16 Eyl canlı ölçüm: "166.711 / %32,5" geri gönderilmişti) ---

def _konut_2025() -> pd.DataFrame:
    """Canlı koşudaki tablonun aynısı: lakehouse_query 13 satır, ilk satırın farkı NaN."""
    d = pd.date_range("2024-12-31", periods=13, freq="ME").strftime("%Y-%m-%d")
    value = [512259.0, 523455.0, 535029.0, 548385.0, 561793.0, 575453.0, 583265.0,
             594607.0, 608694.0, 623765.0, 642144.0, 658770.0, 678970.0]
    degisim = [None] + [round(b - a, 1) for a, b in zip(value, value[1:])]
    yuzde = [None] + [round((b / a - 1) * 100, 2) for a, b in zip(value, value[1:])]
    return pd.DataFrame({"observation_date": d, "value": value, "degisim": degisim, "aylik_degisim_yuzde": yuzde})


def test_span_ilk_son_fark_ve_yuzde() -> None:
    text = span_summary(_konut_2025())
    assert text.startswith("Harness hesabı — ilk → son")
    assert "value: 2024-12-31 512259 → 2025-12-31 678970 · fark +166711 · değişim +32.54%" in text


def test_span_modelin_yazdigi_sayilar_artik_havuzda() -> None:
    # Geri gönderilen anlatıdaki iki sayı: kart metni araç çıktısı havuzuna girince guard OK der.
    card = "Sorgu başarılı: 13 satır.\n" + preview_table(_konut_2025()) + "\n" + span_summary(_konut_2025())
    cevap = "2025'te konut kredisi bakiyesi 166.711 milyon TL (%32,5) arttı: 512.259'dan 678.970'e."
    assert grounding_check("2025'te konut kredisi nasıl değişti?", cevap, [card]) == "OK"
    # Kontrol: kart olmadan aynı cevap MISS'ti (canlı koşudaki durum).
    kartsiz = "Sorgu başarılı: 13 satır.\n" + preview_table(_konut_2025())
    assert grounding_check("2025'te konut kredisi nasıl değişti?", cevap, [kartsiz]).startswith("MISS:166.711")


def test_span_ilk_bos_deger_atlanir_yuzde_sutununda_oran_yazilmaz() -> None:
    text = span_summary(_konut_2025())
    # degisim sütununun ilk değeri NaN: ilk dolu değerden (Ocak) başlar.
    assert "degisim: 2025-01-31 11196 → 2025-12-31 20200 · fark +9004" in text
    # Yüzde sütununda fark var, "değişim %" yok (yüzdenin yüzdesi yanıltır).
    yuzde_satiri = next(l for l in text.splitlines() if l.strip().startswith("aylik_degisim_yuzde"))
    assert "fark +0.88" in yuzde_satiri and "değişim" not in yuzde_satiri


def test_span_cok_varlikli_uzun_tabloda_yazilmaz() -> None:
    # il × ay: tarih tekrar eder, ilk-son anlamsız.
    df = pd.DataFrame({"observation_date": ["2025-01-31", "2025-01-31", "2025-02-28", "2025-02-28"],
                       "il": ["ISTANBUL", "ANKARA", "ISTANBUL", "ANKARA"], "value": [1.0, 2.0, 3.0, 4.0]})
    assert span_summary(df) == ""


def test_span_tarih_yoksa_veya_tek_satirsa_bos() -> None:
    assert span_summary(pd.DataFrame({"kalem": ["a", "b"], "value": [1.0, 2.0]})) == ""
    assert span_summary(_konut_2025().head(1)) == ""


def test_span_en_fazla_dort_sutun() -> None:
    df = _months(6)
    for k in range(6):
        df[f"k{k}"] = [float(i + k) for i in range(6)]
    text = span_summary(df)
    assert sum(1 for l in text.splitlines() if l.startswith("  ")) == 4
