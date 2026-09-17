"""E-1 + E-4: ortak sayısal karşılaştırma kuralı — hassasiyet tabanlı tolerans ve oran/puan bağlamı.

E-1: araç sonucuna dayanan doğrudan sayısal iddialarda göreli %0,5 tolerans YOK; eşleşme cevapta gösterilen
hassasiyetin yarım birimidir (tam sayı 0,5; bir ondalık 0,05; iki ondalık 0,005; üç ondalık 0,0005). Değer
büyüdükçe tolerans büyümez; işaret korunur; Türkçe sayı biçimleri korunur.

E-4: ≤31 küçük sayı muafiyeti oran/değişim iddiası bağlamında (%, yüzde, puan, baz puan) kaldırılır; tarih ve
liste numarası muafiyeti korunur.

Bu testler değişiklikten ÖNCE yazıldı; grounding_check'te göreli tolerans ve bağlamsız ≤31 muafiyeti nedeniyle
E-1/E-4 satırları başlangıçta kırmızıdır.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.agent import unverified_numbers  # noqa: E402
from kkb_agent.core.evidence import EvidenceBuilder  # noqa: E402
from kkb_agent.core.grounding import grounding_check, in_rate_context, token_tolerance  # noqa: E402


# --------------------------------------------------------------------------- token_tolerance
@pytest.mark.parametrize("raw, expected", [
    ("20200", 0.5), ("678.970", 0.5), ("-100", 0.5),   # tam sayı / binlik-noktalı → 0,5
    ("18,4", 0.05),                                     # bir ondalık (virgül)
    ("18,39", 0.005),                                   # iki ondalık (virgül)
    ("0,001", 0.0005),                                  # üç ondalık (virgül)
    ("2.31", 0.005),                                    # iki ondalık (NOKTA — binlik değil; ikinci-göz Açık 1)
    ("0.263", 0.0005),                                  # üç ondalık (nokta, korelasyon katsayısı)
    ("+0.003", 0.0005),                                 # üç ondalık, işaretli
])
def test_token_tolerans_gosterilen_hassasiyet(raw, expected):
    assert token_tolerance(raw) == pytest.approx(expected)


def test_tolerans_deger_buyudukce_buyumez():
    # 20.200 için tolerans, 200 için toleransla aynı (büyüklükten bağımsız).
    assert token_tolerance("20.200") == token_tolerance("200") == 0.5


# --------------------------------------------------------------------------- E-1 grounding_check
def test_e1_yakin_ama_farkli_tam_sayi_reddedilir():
    assert grounding_check("fark ne", "Fark 20.150 milyon TL.", ["fark 20.200"]).startswith("MISS")


def test_e1_tam_eslesme_kabul():
    assert grounding_check("fark ne", "Fark 20.200 milyon TL.", ["fark 20.200"]) == "OK"


def test_e1_iki_ondalik_yuvarlama_kabul():
    # Araç 18.388 (tek nokta üç hane → hem 18388 hem 18,388); model iki ondalığa yuvarlayıp %18,39 yazmış.
    assert grounding_check("faiz", "Aylık ortalama faiz %18,39.", ["Gold faiz 18.388"]) == "OK"


def test_e1_677_678_karismaz():
    assert grounding_check("kasım", "Kasım 677.970 milyon TL.", ["Aralık 678.970"]).startswith("MISS")


def test_e1_isaret_korunur_pozitif_negatif_karismaz():
    # Model açıkça +2,31 yazmış; havuzda -2,31 var → işaretli, eşleşmemeli.
    assert grounding_check("katsayı", "Korelasyon +2,31.", ["katsayı -2,31"]).startswith("MISS")


def test_e1_isaretsiz_buyukluk_yon_sozcukle_kabul():
    # "2,31 düştü": işaretsiz büyüklük yazımı; havuzda -2,31 var → mutlak eşleşme kabul (mevcut davranış korunur).
    # Tek kesin senaryo (ikinci-göz: 'or' ile iki cevabı sınamak ilk senaryonun bozulmasını gizleyebilir).
    assert grounding_check("değişim", "Faiz 2,31 puan düştü.", ["değişim -2,31"]) == "OK"


# --------------------------------------------------------------------------- E-4 oran/puan bağlamı
@pytest.mark.parametrize("cevap", ["Kredi %2 arttı.", "Kredi 2% arttı.", "Kredi yüzde 2 arttı.",
                                   "Faiz 2 puan arttı.", "Faiz 2 baz puan arttı."])
def test_e4_oran_baglaminda_kucuk_sayi_havuzda_yoksa_reddedilir(cevap):
    assert grounding_check("değişim", cevap, ["Sorgu: 100, 105"]).startswith("MISS")


@pytest.mark.parametrize("cevap", ["Kredi %2 arttı.", "Faiz 2 puan arttı."])
def test_e4_oran_baglaminda_kucuk_sayi_havuzda_varsa_kabul(cevap):
    assert grounding_check("değişim", cevap, ["Sorgu: 2, 100, 105"]) == "OK"


def test_e4_tarih_donem_ay_muafiyeti_korunur():
    # "2025-12" dönem yazımı sayısal iddia değildir; "12 ay" dönem sayısıdır.
    assert grounding_check("kapsam", "Kapsam 2025-12 dönemine kadar, 12 ay veri var.", ["Sorgu: 100"]) == "OK"


def test_e4_liste_numarasi_ve_gun_muaf():
    assert grounding_check("özet", "3 madde var: ilk 2 dönem eksik.", ["Sorgu: 100, 105"]) == "OK"


def test_e4_yuzde_yalniz_bitisik_sayiya_baglanir_uzaktakine_degil():
    # Cevabın İÇİNDE '%' var ama başka sayıya ait: "12 ayda %2 arttı" → % yalnız 2'ye bağlanır; 12 dönem sayısı muaf
    # kalır (ikinci-göz Açık 2; % ANSWER içinde, tool metninde değil). 2 havuzda → OK.
    assert grounding_check("özet", "12 ayda %2 arttı.", ["Sorgu: 2, 100, 105"]) == "OK"
    # 2 havuzda yoksa yalnız 2 reddedilir; 12 (dönem sayısı) yine de MISS'e girmez.
    assert grounding_check("özet", "12 ayda %2 arttı.", ["Sorgu: 100, 105"]) == "MISS:2"
    # Liste numarası da aynı: "3 kalem: %2 arttı" → 3 muaf, % yalnız 2'ye bağlı.
    assert grounding_check("özet", "3 kalem: %2 arttı.", ["Sorgu: 2, 100"]) == "OK"


def test_e4_politika_kelimesi_engellenmez_sayi_kontrol_edilir():
    # "politika faizi %2" — politika siyasi içerik değil; %2 havuzda varsa kabul.
    assert grounding_check("faiz", "Politika faizi %2.", ["Sorgu: 2"]) == "OK"
    assert grounding_check("faiz", "Politika faizi %2.", ["Sorgu: 100"]).startswith("MISS")


# --------------------------------------------------------------------------- in_rate_context birimi
@pytest.mark.parametrize("metin, hedef, beklenen", [
    ("%2 arttı", "2", True), ("2% arttı", "2", True), ("yüzde 2 arttı", "2", True),
    ("2 puan arttı", "2", True), ("2 baz puan arttı", "2", True),
    ("12 ay veri", "12", False), ("3 kalem", "3", False),
])
def test_in_rate_context(metin, hedef, beklenen):
    i = metin.index(hedef)
    assert in_rate_context(metin, i, i + len(hedef)) is beklenen


# --------------------------------------------------------------------------- E-4 unverified_numbers (araçsız/final-exit yolu)
def test_e4_unverified_numbers_oran_baglami():
    # 3 satır → satır sayısı 3; "2" ne değerlerde ne satır sayısında var (satır sayısı havuza katılır).
    tablo = pd.DataFrame({"value": [100.0, 105.0, 110.0]})
    assert unverified_numbers("Kredi %2 arttı.", tablo), "2 tabloda yok, oran bağlamı → bayrak"
    tablo2 = pd.DataFrame({"value": [2.0, 100.0, 105.0]})
    assert not unverified_numbers("Kredi %2 arttı.", tablo2)   # 2 tabloda var → temiz


def test_e4_unverified_numbers_tarih_ay_muaf():
    tablo = pd.DataFrame({"value": [100.0]})
    assert not unverified_numbers("12 ay veri, 3 kalem.", tablo)


# --------------------------------------------------------------------------- ikinci-göz Açık 1: noktalı ondalık toleransı
@pytest.mark.parametrize("cevap, deger", [
    ("Faiz %2.31.", 2.7),          # 2.31 ondalık; 0,5 toleransla 2,7'ye eşleşmemeli
    ("Korelasyon 0.263.", 0.7),    # 0.263 korelasyon katsayısı (üç ondalık)
    ("Korelasyon +0.003.", -0.003),  # işaretli + noktalı; hem hassasiyet hem işaret ayrışmalı
])
def test_e1_noktali_ondalik_yanlis_degeri_dogrulamaz(cevap, deger):
    assert grounding_check("soru", cevap, [str(deger)]).startswith("MISS")


@pytest.mark.parametrize("cevap, deger", [("Faiz %2.31.", 2.7), ("Korelasyon 0.263.", 0.7), ("Korelasyon +0.003.", -0.003)])
def test_e1_noktali_ondalik_panelde_de_eslesmez(cevap, deger):
    # Panel aynı ortak kurala bağlı; kopya formül 0,5 verip yanlış eşleştirmemeli (ikinci-göz uyarısı).
    from kkb_agent.core.evidence import EvidenceBuilder
    ev = EvidenceBuilder(None)._match_numbers(cevap, pd.DataFrame({"value": [deger]}), None)
    assert ev and not ev[0].matched


# --------------------------------------------------------------------------- ikinci-göz Açık 3: sorudaki dönem sayısı oranı muaf kılmaz
def test_e4_sorudaki_donem_sayisi_desteklenmeyen_orani_muaf_kilmaz():
    # Soru "12 aylık…" → 12 dönem sayısı; ama cevaptaki "%12" araçta yok, oran iddiası → MISS.
    assert grounding_check("12 aylık değişimi göster", "Kredi %12 arttı.", ["değer 100, 105"]).startswith("MISS")
    # Aynı 12, oran bağlamı olmadan dönem olarak yazılırsa muaf kalır.
    assert grounding_check("12 aylık değişimi göster", "Son 12 ayda veri var.", ["değer 100, 105"]) == "OK"


# --------------------------------------------------------------------------- ikinci-göz Açık 4: '%' olmayan 'oran' bağlamı
def test_e4_yuzde_isareti_olmayan_oran_ifadesi_kontrol_edilir():
    assert grounding_check("değişim", "Artış oranı 2 oldu.", ["değer 100, 105"]).startswith("MISS")
    assert grounding_check("değişim", "Artış oranı 2 oldu.", ["oran 2, değer 100"]) == "OK"


# --------------------------------------------------------------------------- ikinci-göz Açık 2: bitişiklik, boşluklu '%' bağlanmaz
def test_in_rate_context_boslukla_ayrik_yuzde_onceki_sayiya_baglanmaz():
    # "100 %2": '%' 2'ye aittir, 100'e boşlukla ayrık → 100 oran bağlamında değil.
    metin = "100 %2 arttı"
    assert in_rate_context(metin, 0, 3) is False           # "100"
    assert in_rate_context(metin, metin.index("2"), metin.index("2") + 1) is True   # "2"


# --------------------------------------------------------------------------- üçüncü-göz Açık 1: doğal oran yazımları muafiyeti aşar
@pytest.mark.parametrize("cevap", [
    "Faiz 2 % oldu.",              # boşluklu son-ek '%' (ardında sayı yok)
    "Faiz 2 puanlık arttı.",       # Türkçe ek: puanlık
    "Faiz 2 baz puanlık arttı.",   # baz puan + ek
    "Artış oranı: 2 oldu.",        # etiket–sayı arası iki nokta
    "Faiz 2 puandan yükseldi.",    # Türkçe ek: puandan
])
def test_e4_dogal_oran_yazimlari_kucuk_sayi_muafiyetini_asar(cevap):
    assert grounding_check("faiz", cevap, ["değer 100, 105"]).startswith("MISS")
    assert unverified_numbers(cevap, pd.DataFrame({"value": [100.0, 105.0, 110.0]}))


def test_e4_dogal_oran_yazimlari_negatifler_korunur():
    # Boşluklu '%' ardından sayı gelirse önceki sayıya bağlanmaz; eski negatif regresyonlar korunur.
    metin = "100 %2 arttı"
    assert in_rate_context(metin, 0, 3) is False                       # "100" → boşluklu %, ardından 2
    assert in_rate_context("2 %3", 0, 1) is False                      # "2" → % ardından 3 var, bağlanmaz
    assert grounding_check("özet", "12 ayda %2 arttı.", ["Sorgu: 2, 100"]) == "OK"   # 12 dönem, muaf
    assert grounding_check("özet", "3 kalem: %2 arttı.", ["Sorgu: 2, 100"]) == "OK"  # 3 liste no, muaf
    # "puan" ekli birime karşı: gerçek sözcük değilse bağlanmaz.
    assert in_rate_context("2 punto", 0, 1) is False


# --------------------------------------------------------------------------- üçüncü-göz Açık 2: yarım-birim sınırı üç yolda tutarlı
_BUILDER = EvidenceBuilder(None)


@pytest.mark.parametrize("cevap, deger", [
    ("Faiz %1,01.", 1.005),    # 1,005 → %1,01 doğru yuvarlama; float farkı 0,005'i kıl payı aşıyor
    ("Faiz %37,29.", 37.285),  # 37,285 → %37,29
    ("Faiz %2,30.", 2.305),    # 2,305 → %2,30
])
def test_e1_yarim_birim_siniri_uc_yolda_kabul(cevap, deger):
    frame = pd.DataFrame({"value": [deger]})
    assert grounding_check("faiz", cevap, [str(deger)]) == "OK"
    assert not unverified_numbers(cevap, frame)
    ev = _BUILDER._match_numbers(cevap, frame, None)
    assert ev and ev[0].matched


@pytest.mark.parametrize("cevap, deger", [
    ("Faiz %37,29.", 37.2951),  # gerçek fark 0,0051 > yarım birim → sınırın DIŞINDA, reddedilmeli
    ("Faiz %37,29.", 37.30),    # fark 0,01
    ("Faiz %2,30.", 2.32),      # fark 0,02
])
def test_e1_yarim_birim_sinirinin_disi_uc_yolda_ret(cevap, deger):
    frame = pd.DataFrame({"value": [deger]})
    assert grounding_check("faiz", cevap, [str(deger)]).startswith("MISS")
    assert unverified_numbers(cevap, frame)
    ev = _BUILDER._match_numbers(cevap, frame, None)
    assert ev and not ev[0].matched
