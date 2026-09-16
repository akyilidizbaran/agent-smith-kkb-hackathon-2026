"""Tablo kalitesi (builder/quality): boşluk, mükerrer, toplam satırı, kısmi yıl, birim, etiket-değer — engellemez, bayrak üretir."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.builder.quality import table_quality  # noqa: E402
from kkb_agent.core.fitness import signature_of  # noqa: E402


def _frame(dates, values, col="bakiye"):
    return pd.DataFrame({"donem": dates, col: [str(v) for v in values]})


def _dates(year=2024, n=12):
    return [d.isoformat() for d in pd.date_range(f"{year}-01-31", periods=n, freq="ME").date]


def test_temiz_aylik_tablo_bayrak_yok() -> None:
    f = _frame(_dates(), range(12))
    assert table_quality(f, signature_of(f, "temiz.csv"), "2024 bakiye trendi") == []


def test_eksik_donem_ve_mukerrer_donem() -> None:
    d = _dates()
    gap = d[:5] + d[7:]                       # Haziran-Temmuz yok
    f = _frame(gap, range(len(gap)))
    flags = table_quality(f, signature_of(f, "eksik.csv"), "2024 nasıl değişti")
    assert any(fl.startswith("eksik dönem") and "2 ay" in fl for fl in flags)
    dup = d + [d[3]]
    f2 = _frame(dup, range(len(dup)))
    assert any("mükerrer dönem: ['2024-04']" in fl for fl in table_quality(f2, signature_of(f2, "dup.csv"), ""))


def test_toplam_satiri_tarih_kolonunda_metin() -> None:
    f = _frame(_dates() + ["Toplam"], list(range(12)) + [66])
    flags = table_quality(f, signature_of(f, "toplamli.csv"), "2024 toplam")
    assert any("tarih olmayan satır: ['Toplam']" in fl for fl in flags)


def test_kismi_yil_ve_kucuk_orneklem() -> None:
    f = _frame(_dates(2025, 8), range(8))
    flags = table_quality(f, signature_of(f, "2025_8ay.csv"), "2025 yıllık büyüme ne kadar?")
    assert any("kısmi yıl: 2025 için 8 ay" in fl for fl in flags)
    g = _frame(_dates(2024, 4), range(4))
    assert any(fl.startswith("küçük örneklem: 4 satır") for fl in table_quality(g, signature_of(g, "kisa.csv"), "trend nasıl"))


def test_birim_beyani_ve_etiket_deger() -> None:
    f = _frame(_dates(), [450000 + i for i in range(12)], col="faiz")
    flags = table_quality(f, signature_of(f, "adsiz.csv"), "2024 faiz kaç milyon TL?")
    assert any(fl.startswith("birim beyanı yok") for fl in flags)
    assert any("etiket-değer uyuşmazlığı: 'faiz'" in fl for fl in flags)
    g = _frame(_dates(), [1000] * 12, col="bakiye_milyon_tl")
    assert not any(fl.startswith("birim beyanı yok") for fl in table_quality(g, signature_of(g, "birimli.csv"), "kaç milyon TL"))


def test_birim_olcek_uyusmazligi_dosya_adindan() -> None:
    # UEB B06: dosya adı "bin_tl", soru "milyon TL olarak" → ×1000 riski; ipucu var diye susulmaz, uyuşmazlık söylenir.
    f = _frame(_dates(), [436_688_000 + i for i in range(12)])
    flags = table_quality(f, signature_of(f, "konut_kredisi_bin_tl.csv"), "2024 Aralık bakiyesi milyon TL olarak kaç?")
    assert any(fl.startswith("birim uyuşmazlığı: soru 'milyon' istiyor, veri adı/başlığı 'bin' beyan ediyor") for fl in flags)
    assert not any(fl.startswith("birim beyanı yok") for fl in flags)
    same = table_quality(f, signature_of(f, "konut_kredisi_bin_tl.csv"), "2024 Aralık bakiyesi bin TL olarak kaç?")
    assert not any(fl.startswith("birim uyuşmazlığı") for fl in same)
    h = _frame(_dates(), [1] * 12, col="HSG_LN_BAL_TRYMN")   # D08: 'TRYMN' tek belirteç, ölçek sözcüğü değil → bayrak yok
    assert not any(fl.startswith("birim uyuşmazlığı") for fl in table_quality(h, signature_of(h, "hsg_ln_2024.csv"), "milyon TL olarak kaç?"))


def test_yillik_tablo_ve_okunamayan_tablo() -> None:
    y = pd.DataFrame({"yil": ["2022", "2023", "2024"], "deger": ["1", "2", "3"]})
    assert table_quality(y, signature_of(y, "yillik.csv"), "2024 yıllık") == []
    bad = pd.DataFrame({"a": ["x", "y", "z"], "b": ["1", "2", "3"]})
    assert table_quality(bad, signature_of(bad, "bozuk.csv"), "") == ["tarih+değer kolonu bulunamadı (okunamayan/yanlış sayfa ya da tarih biçimi)"]
