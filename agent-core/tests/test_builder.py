"""Architect'in LLM'siz çekirdeği: profilci + doğrulayıcı.

Girdi generic parser'ın ürettiği şey — metin tablosu. Her test şu soruyu sorar:
öneri kanıt taşıyor mu, belirsizlikte tahmin ediyor mu, doğrulama sessiz düşmeyi
yakalıyor mu.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.builder import profile_table, propose, verify_mapping  # noqa: E402


def _frame(rows: list[dict[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, dtype=object)


ISO = _frame([
    {"donem": "2026-01-31", "deger": "100.5", "kurum": "SYNTHETIC-A"},
    {"donem": "2026-02-28", "deger": "", "kurum": "SYNTHETIC-A"},
    {"donem": "2026-03-31", "deger": "120.25", "kurum": "SYNTHETIC-A"},
])

TR = _frame([  # Türkçe yazım: gün.ay.yıl, binlik '.', ondalık ','
    {"Tarih": "31.01.2025", "Konut Kredisi (milyon TL)": "1.234,5"},
    {"Tarih": "28.02.2025", "Konut Kredisi (milyon TL)": "1.300,0"},
    {"Tarih": "31.03.2025", "Konut Kredisi (milyon TL)": "1.402,75"},
    {"Tarih": "30.04.2025", "Konut Kredisi (milyon TL)": "1.450,1"},
    {"Tarih": "31.05.2025", "Konut Kredisi (milyon TL)": "1.500,0"},
    {"Tarih": "30.06.2025", "Konut Kredisi (milyon TL)": "1.560,9"},
])


# ---------------------------------------------------------------- profilleme
def test_profil_yorumlamaz_olcer() -> None:
    p = profile_table(ISO)
    donem = p.column("donem"); deger = p.column("deger"); kurum = p.column("kurum")
    assert donem and "%Y-%m-%d" in donem.date_formats and donem.monotonic_dates and donem.unique_dates
    assert deger and (".", None) in deger.numeric_under and deger.non_empty == 2 and deger.null_rate == pytest.approx(1 / 3)
    assert kurum and not kurum.date_formats and not kurum.numeric_under and kurum.distinct == 1


def test_turkce_yazim_tek_biçimle_ayrisir() -> None:
    p = profile_table(TR)
    tarih = p.column("Tarih"); deger = p.column("Konut Kredisi (milyon TL)")
    assert tarih.date_formats == ("%d.%m.%Y",), "yalnız gün.ay.yıl geçmeli; 31 > 12 olduğu için ay.gün elenir"
    assert deger.numeric_under == ((",", "."),), "yalnız ondalık ',' binlik '.' geçmeli"


# --------------------------------------------------------------------- öneri
def test_oneri_kanit_tasir_ve_yayinlama_alanlariyla_birebir() -> None:
    p = profile_table(TR)
    mapping, semantics = propose(p, TR, series_id="adhoc:konut_test")

    assert mapping is not None and semantics is not None
    assert mapping.observation_date_column == "Tarih" and mapping.date_format == "%d.%m.%Y"
    assert mapping.value_column == "Konut Kredisi (milyon TL)"
    assert (mapping.decimal_separator, mapping.thousands_separator) == (",", ".")
    assert mapping.entity_id_column is None
    assert not mapping.ambiguous
    # her alanın gerekçesi var
    assert {e.field for e in mapping.evidence} >= {"observation_date_column", "value_column", "date_format", "decimal_separator"}
    # anlam: aylık, stok (zayıf), birim başlıktan
    assert semantics.frequency == "monthly"
    assert semantics.unit == "TRY_mn"
    assert semantics.measure_type == "stock" and semantics.default_agg == "last"
    assert next(e for e in semantics.evidence if e.field == "measure_type").confidence == "weak"


def test_gun_ay_belirsizliginde_tahmin_yok() -> None:
    """01/02/2026 hem 1 Şubat hem 2 Ocak: iki biçim de %100 geçer. Öneri belirsiz işaretlenir,
    doğrulama yayınlamayı durdurur."""
    amb = _frame([
        {"d": "01/02/2026", "v": "1"}, {"d": "03/04/2026", "v": "2"}, {"d": "05/06/2026", "v": "3"},
    ])
    mapping, _ = propose(profile_table(amb), amb, series_id="adhoc:belirsiz")
    assert mapping is not None
    assert "date_format" in mapping.ambiguous
    report = verify_mapping(amb, mapping)
    assert not report.ok
    assert any("belirsiz" in c.name and not c.ok for c in report.checks)


def test_birden_cok_sayisal_kolon_alternatif_olarak_verilir() -> None:
    f = _frame([
        {"donem": "2026-01-31", "tp": "10", "yp": "5", "toplam": "15"},
        {"donem": "2026-02-28", "tp": "11", "yp": "5", "toplam": "16"},
        {"donem": "2026-03-31", "tp": "12", "yp": "6", "toplam": "18"},
    ])
    mapping, _ = propose(profile_table(f), f, series_id="adhoc:x")
    assert mapping is not None
    assert set(mapping.alternatives.get("value_column", ())) | {mapping.value_column} == {"tp", "yp", "toplam"}
    assert next(e for e in mapping.evidence if e.field == "value_column").confidence == "weak"


def test_entity_kolonu_boyutsa_onerilir_sabitse_onerilmez() -> None:
    boyut = _frame([
        {"d": "2026-01-31", "il": "ISTANBUL", "v": "1"}, {"d": "2026-01-31", "il": "ANKARA", "v": "2"},
        {"d": "2026-02-28", "il": "ISTANBUL", "v": "3"}, {"d": "2026-02-28", "il": "ANKARA", "v": "4"},
    ])
    mapping, _ = propose(profile_table(boyut), boyut, series_id="adhoc:il")
    assert mapping is not None and mapping.entity_id_column == "il"
    mapping_iso, _ = propose(profile_table(ISO), ISO, series_id="adhoc:iso")
    assert mapping_iso is not None and mapping_iso.entity_id_column is None, "tek değerli 'kurum' boyut değil, sabit"


def test_tarih_kolonu_yoksa_oneri_yok() -> None:
    f = _frame([{"a": "x", "b": "1"}, {"a": "y", "b": "2"}])
    assert propose(profile_table(f), f, series_id="adhoc:yok") == (None, None)


def test_olcum_tipi_kanitsizsa_unknown() -> None:
    """İnişli çıkışlı seri stok mu akım mı veriden bilinemez — unknown, tahmin değil."""
    f = _frame([{"d": f"2026-{m:02d}-01", "v": v} for m, v in zip(range(1, 8), ("5", "3", "9", "2", "8", "1", "7"))])
    _, semantics = propose(profile_table(f), f, series_id="adhoc:z")
    assert semantics is not None and semantics.measure_type == "unknown"
    assert next(e for e in semantics.evidence if e.field == "measure_type").confidence == "none"


# ---------------------------------------------------------------- doğrulama
def test_dogrulama_gecer_ve_bos_degeri_korur() -> None:
    mapping, _ = propose(profile_table(ISO), ISO, series_id="adhoc:iso")
    report = verify_mapping(ISO, mapping)
    assert report.ok, report.render()
    assert report.rows_mapped == 3 and report.rows_null_value == 1


def test_dogrulama_sessiz_dusmeyi_yakalar() -> None:
    """Öneri doğru ama bir satır bozuk: yayınlama o satırı düşürmez, HATA verir. Biz de."""
    mapping, _ = propose(profile_table(TR), TR, series_id="adhoc:konut")
    bozuk = TR.copy(); bozuk.loc[2, "Konut Kredisi (milyon TL)"] = "1.402.75"   # ondalık için '.' — geçersiz
    report = verify_mapping(bozuk, mapping)
    assert not report.ok
    assert any("ayrışıyor" in c.name and not c.ok and "1.402.75" in c.detail for c in report.checks)
    assert any(c.name == "hiçbir satır sessizce düşmüyor" and not c.ok for c in report.checks)


def test_dogrulama_ayni_tarihi_iki_kez_gorunce_durur() -> None:
    """Aynı (tarih, entity) iki kez: yayınlamada revizyon çatışması. Entity eksik olabilir."""
    f = _frame([{"d": "2026-01-31", "v": "1"}, {"d": "2026-01-31", "v": "2"}, {"d": "2026-02-28", "v": "3"}])
    mapping, _ = propose(profile_table(f), f, series_id="adhoc:dup")
    report = verify_mapping(f, mapping)
    assert not report.ok
    assert any("yalnız bir kez" in c.name and not c.ok and "entity" in c.detail for c in report.checks)


def test_dogrulama_series_id_alanini_ve_cakismayi_kontrol_eder() -> None:
    mapping, _ = propose(profile_table(ISO), ISO, series_id="adhoc:iso")
    report = verify_mapping(ISO, mapping, existing_series_ids=["adhoc:iso"])
    assert not report.ok and any("çakışmıyor" in c.name and not c.ok for c in report.checks)
    kotu = verify_mapping(ISO, mapping.__class__(**{**mapping.__dict__, "series_id": "bddk_monthly:1534_Toplam"}))
    assert any("'adhoc:' alanında" in c.name and not c.ok for c in kotu.checks)


def test_rapor_okunabilir() -> None:
    mapping, _ = propose(profile_table(TR), TR, series_id="adhoc:konut")
    text = verify_mapping(TR, mapping).render()
    assert text.startswith("DOĞRULAMA: geçti") and "6/6 satır eşlendi" in text
