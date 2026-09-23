"""Enrich-join güvenliği (P5): join YAPILAMAZSA mevcut tablo ASLA ezilmez; açık hata döner.

Tarih anahtarı yalnız GEÇERLİ YYYYMM üretir (parasal büyük değer tarih sanılmaz); ortak ay yoksa,
tarih kolonu yoksa, duplicate ay varsa join reddedilir. Kaynak adına özel davranış yoktur.
"""
from __future__ import annotations

import pandas as pd

from kkb_agent.tools.web import _month_key_one, monthly_enrich_join


def test_valid_monthly_join_preserves_base_and_adds_columns():
    left = pd.DataFrame({"Tarih": ["2024-11-01", "2023-03-01", "2022-05-01"], "TP Mevduat": [500000, 300000, -8000]})
    right = pd.DataFrame({"Dönem": ["2024-11", "2023-03"], "TEFAS Hacim": [12000, 34000]})
    merged, err = monthly_enrich_join(left, right)
    assert err is None and merged is not None
    assert list(merged.columns) == ["Tarih", "TP Mevduat", "TEFAS Hacim"]
    assert len(merged) == len(left)                       # taban satırlar korundu
    assert merged.loc[merged["Tarih"] == "2024-11-01", "TEFAS Hacim"].iloc[0] == 12000
    assert pd.isna(merged.loc[merged["Tarih"] == "2022-05-01", "TEFAS Hacim"].iloc[0])  # eşleşmeyen ay boş


def test_monetary_value_is_not_treated_as_date():
    # Büyük parasal değer geçerli yıl+ay deseni taşımaz → '' (tarih anahtarı üretmez).
    assert _month_key_one("1572692395037,49") == ""
    assert _month_key_one("98293274689,84") == ""
    assert _month_key_one("Toplam") == ""
    assert _month_key_one("2026-09") == "202609"
    assert _month_key_one("2024-11-01") == "202411"
    assert _month_key_one("202205") == "202205"


def test_join_fails_explicitly_when_no_date_column():
    left = pd.DataFrame({"Tarih": ["2024-11-01"], "TP": [1]})
    right = pd.DataFrame({"Değer": [5], "Başka": [6]})   # tarih yok
    merged, err = monthly_enrich_join(left, right)
    assert merged is None and "tarih" in err.lower()


def test_join_fails_explicitly_when_no_common_month():
    left = pd.DataFrame({"Tarih": ["2024-11-01"], "TP": [1]})
    right = pd.DataFrame({"Dönem": ["2019-01"], "Hacim": [9]})
    merged, err = monthly_enrich_join(left, right)
    assert merged is None and "ortak" in err.lower()


def test_join_fails_explicitly_on_duplicate_months():
    left = pd.DataFrame({"Tarih": ["2024-11-01"], "TP": [1]})
    right = pd.DataFrame({"Dönem": ["2024-11", "2024-11"], "Hacim": [10, 11]})
    merged, err = monthly_enrich_join(left, right)
    assert merged is None and "duplicate" in err.lower()


def test_measurement_column_not_misread_as_date_column():
    # Sağ tabloda tarih 'Dönem'; parasal 'Hacim' yanlışlıkla tarih seçilmemeli.
    left = pd.DataFrame({"Tarih": ["2024-11-01"], "TP": [1]})
    right = pd.DataFrame({"Dönem": ["2024-11"], "Hacim": [1572692395037]})
    merged, err = monthly_enrich_join(left, right)
    assert err is None and merged is not None
    assert merged.loc[merged["Tarih"] == "2024-11-01", "Hacim"].iloc[0] == 1572692395037
