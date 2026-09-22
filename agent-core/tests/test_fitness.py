"""Uygunluk kapısı (core/fitness): soru gereksinimi × veri imzası — LLM yok, ağ yok, DB yok."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency, SemanticType  # noqa: E402
from kkb_agent.core.fitness import DataSignature, Lexicon, assess, signature_of  # noqa: E402


def _monthly(col: str, values, year: int = 2024, n: int = 12) -> pd.DataFrame:
    dates = [d.isoformat() for d in pd.date_range(f"{year}-01-31", periods=n, freq="ME").date]
    return pd.DataFrame({"donem": dates, col: [str(v) for v in values[:n]]})


LEX = Lexicon.load()


def test_dogru_dosya_kabul_ve_imza_dogru() -> None:
    frame = _monthly("konut_kredisi_bakiye", [500000 + i * 1000 for i in range(12)])
    sig = signature_of(frame, "../incoming/hsg_ln_2024.csv")
    assert sig.years == (2024, 2024) and sig.frequency == "monthly" and sig.date_column == "donem"
    f = assess("2024'te konut kredisi bakiyesi aylık nasıl değişti?", sig, LEX)
    assert f.decision == "accept" and f.score == 1.0
    assert set(f.required) == {"konut", "kredi", "bakiye"} and "bakiye" in f.present
    assert f.lines()[0].startswith("uygunluk: kabul")


def test_anlamca_yakin_yanlis_dosya_ret_fiyat_endeksi_bakiye_degil() -> None:
    frame = _monthly("kfe_endeks", [100 + i for i in range(12)])
    f = assess("2024'te konut kredisi bakiyesi nasıl değişti?", signature_of(frame, "konut_fiyat_endeksi.csv"), LEX)
    assert f.decision == "reject" and f.dims["measure"] == "fail"
    assert "aranan ölçüm yok: bakiye" in f.reasons[0] and "fiyat_endeksi" in f.reasons[0]
    msg = f.stop_message()
    assert "uygun görünmüyor" in msg and "kolonlar donem, kfe_endeks" in msg and "2024–2024" in msg


def test_tamamen_ilgisiz_dosya_ret() -> None:
    frame = pd.DataFrame({"hat": ["34", "500T", "E-10"], "kalkis": ["06:00", "06:30", "07:00"], "sefer": ["40", "25", "18"]})
    f = assess("Konut kredisi bakiyesi 2024'te ne oldu?", signature_of(frame, "otobus_tarifesi.csv"), LEX)
    assert f.decision == "reject" and f.present == ()


def test_donem_disi_dosya_ret_kavramlar_dogru_olsa_da() -> None:
    frame = _monthly("konut_kredisi_bakiye", [1000] * 12, year=2019)
    f = assess("2025 konut kredisi bakiyesi", signature_of(frame, "konut_kredisi_2019.csv"), LEX)
    assert f.decision == "reject" and f.dims["period"] == "fail" and "dönem: soru 2025" in f.reasons[0]


def test_yillik_dosyaya_aylik_soru_ret_granularite() -> None:
    frame = pd.DataFrame({"yil": ["2022", "2023", "2024"], "konut_kredisi_bakiye": ["1", "2", "3"]})
    sig = signature_of(frame, "konut_kredisi_yillik.csv")
    assert sig.frequency == "yearly" and sig.years == (2022, 2024)
    f = assess("2024'te konut kredisi bakiyesi aylık nasıl değişti?", sig, LEX)
    assert f.decision == "reject" and f.dims["granularity"] == "fail"


def test_etiket_deger_uyusmazligi_faiz_kolonu_bakiye_tasiyor() -> None:
    # B07 (UEB, iki koşuda sessiz): 'faiz_orani' başlıklı kolon 459.904 gibi değerler taşıyor → faiz güvenilmez → ret.
    frame = _monthly("faiz_orani", [450000 + i * 900 for i in range(12)])
    f = assess("2024 konut kredisi faiz oranı ortalaması ne?", signature_of(frame, "konut_faiz_orani_2024.csv"), LEX)
    assert f.decision == "reject" and f.dims["unit"] == "fail"
    assert any("etiket-değer uyuşmazlığı" in r for r in f.reasons) and "faiz" not in f.present


def test_iliski_sorusu_tek_ozneli_dosya_kismen() -> None:
    frame = _monthly("konut_kredisi_bakiye", [1000] * 12)
    f = assess("Faiz oranları düştüğünde konut kredileri 2024'te nasıl değişti?", signature_of(frame, "hsg_ln_2024.csv"), LEX)
    assert f.decision == "partial" and "ikinci kaynak" in f.reasons[0]


def test_gereksinim_cikarilamazsa_kismen_ret_degil() -> None:
    frame = _monthly("deger", [1] * 12)
    f = assess("bu dosyayı ekle", signature_of(frame, "veri.csv"), LEX)
    assert f.decision == "partial" and "gereksinim çıkarılamadı" in f.reasons[0]


def test_bos_sozlukte_kavram_karari_kismen_donem_yine_ret() -> None:
    empty = Lexicon.empty()
    frame = _monthly("kfe", [1] * 12)
    assert assess("konut kredisi bakiyesi 2024", signature_of(frame, "x.csv"), empty).decision == "partial"
    assert assess("konut kredisi bakiyesi 2025", signature_of(frame, "x.csv"), empty).decision == "reject"


def test_alt_kumeye_kisitli_dosya_kismen_soru_soylemiyorsa() -> None:
    frame = _monthly("konut_kredisi_bakiye", [1000] * 12)
    frame["il"] = "İstanbul"
    sig = signature_of(frame, "istanbul_konut_kredisi_2024.csv")
    assert sig.scoped == ("il=İstanbul",)
    assert assess("2024 konut kredisi bakiyesi", sig, LEX).decision == "partial"
    assert assess("İstanbul 2024 konut kredisi bakiyesi", sig, LEX).decision == "accept"


def test_katalog_aliasi_gevsek_kavram_eksikse_kismen() -> None:
    spec = DatasetSpec(
        dataset_id="ds", name="Hastane yatış", description="", source="saglik", frequency=Frequency.MONTHLY, time_column="donem",
        grain=["donem"], coverage=Coverage(start=date(2024, 1, 1), end=date(2024, 12, 31)),
        columns=[ColumnSpec(name="yatis_sayisi", role=ColumnRole.MEASURE, dtype="BIGINT", description="",
                            semantic_type=SemanticType.COUNT, aliases=["hasta yatışı", "yatan hasta sayısı"])],
    )
    lex = Lexicon.empty().with_catalog([spec])
    assert "yatis_sayisi" in lex.concepts and lex.concepts["yatis_sayisi"].measure and not lex.concepts["yatis_sayisi"].strict
    frame = _monthly("sefer_sayisi", [1] * 12)
    f = assess("2024 hasta yatışı aylık nasıl?", signature_of(frame, "otobus.csv"), lex)
    assert f.decision == "partial" and "yatis_sayisi" in f.reasons[0] and "hiçbiri yok" in f.reasons[0]
    frame2 = _monthly("yatan_hasta_sayisi", [1] * 12)
    assert assess("2024 hasta yatışı aylık nasıl?", signature_of(frame2, "hastane.csv"), lex).decision == "accept"


def test_katalog_aliasi_yapilandirma_kavramini_ikilemez() -> None:
    # UEB D08 duman koşusu (15 Eyl): seed kataloğunun 'kalem' (alias "kredi türü") ve 'toplam' (alias "bakiye") kolonları
    # ikinci bir kavram olarak istenince doğru dosya "eksik kalem" diye kısmen kalıyordu. Katalog yalnız YENİ sözcük ekler.
    spec = DatasetSpec(
        dataset_id="bddk_aylik_krediler", name="BDDK aylık krediler", description="", source="bddk_monthly",
        frequency=Frequency.MONTHLY, time_column="donem", grain=["donem", "kalem"],
        coverage=Coverage(start=date(2021, 1, 1), end=date(2026, 6, 30)),
        columns=[ColumnSpec(name="kalem", role=ColumnRole.DIMENSION, dtype="VARCHAR", description="", aliases=["kalem", "kredi türü"]),
                 ColumnSpec(name="toplam", role=ColumnRole.MEASURE, dtype="DOUBLE", description="", aliases=["kredi bakiyesi", "bakiye"])],
    )
    lex = Lexicon.load().with_catalog([spec])
    assert "toplam" not in lex.concepts and lex.concepts["kalem"].roots == frozenset({"kalem", "türü"})
    frame = pd.DataFrame({"PERIOD_END": ["2024-01-31", "2024-02-29", "2024-03-31"], "HSG_LN_BAL_TRYMN": ["1", "2", "3"]})
    f = assess("Şu dosyadan 2024 Aralık konut kredisi bakiyesini söyle: ../incoming/ueb/hsg_ln_2024.csv", signature_of(frame, "hsg_ln_2024.csv"), lex)
    assert f.decision == "accept", f.reasons


def test_tipli_web_tablosu_da_imzalanir() -> None:
    frame = pd.DataFrame({"Yıl": [2024, 2025], "Yıllık TÜFE (%)": [44.38, 31.07]})
    sig = signature_of(frame, "https://site.example/tufe")
    assert sig.frequency == "yearly" and sig.years == (2024, 2025) and sig.unit_hint
    assert assess("2025 yıllık TÜFE ne kadar?", sig, LEX).decision == "accept"


@pytest.mark.parametrize("question", ["2024 kredi kartı işlem hacmi aylık ne kadar?"])
def test_kredi_karti_sorusu_kredi_kavramini_gerektirmez(question: str) -> None:
    frame = _monthly("islem_tutari", [1] * 12)
    assert assess(question, signature_of(frame, "kredi_karti_islemleri.csv"), LEX).decision == "accept"


def test_yinelenen_ve_sayisal_kolon_etiketi_kapiyi_dusurmez() -> None:
    """Arkadaş bulgusu (22 Eyl): TCMB today.xml tablosunda yinelenen/float etiketler `frame[c]`'yi DataFrame yapıyor,
    yıl taraması 'cannot assemble with duplicate keys' ile patlıyor, kapı sessizce atlanıyordu."""
    frame = pd.DataFrame([[1.5, "x", "2025-09-22"], [2.5, "y", "2025-09-22"]], columns=[1.0, 1.0, "Tarih"])
    sig = signature_of(frame, "today.xml")
    assert sig.rows == 2 and sig.headers == ("1.0", "1.0_1", "Tarih")
    assert sig.years == (2025, 2025)


def test_dolar_alis_satis_sorusu_ingilizce_basliklarla_eslesir() -> None:
    """Sözlük köprüsü (concepts.json): alış↔ForexBuying, satış↔ForexSelling, dolar↔USD; kod değil kelime hazinesi."""
    frame = pd.DataFrame({"CurrencyCode": ["USD", "EUR"], "ForexBuying": ["41.2", "48.1"], "ForexSelling": ["41.3", "48.2"], "Tarih": ["2026-09-22", "2026-09-22"]})
    f = assess("Bugün dolar alış ve satış kuru ne?", signature_of(frame, "today.xml"), LEX)
    assert f.decision in ("accept", "partial"), (f.decision, f.reasons)
    assert not any("aranan ölçüm" in r and "yok" in r for r in f.reasons), f.reasons
