"""K02 bulgusu (14 Eyl): araç çıktısındaki üç ondalıklı pandas sayısı ("18.388") Türkçe binlik okunuyordu; modelin doğru
yazdığı "%18,39" MISS sayılıp cevap geri gönderiliyordu. Havuzda iki okuma da geçerli; cevap metni tek okumayla ayrışır."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.grounding import grounding_check, numbers_in  # noqa: E402

TOOL = ["observation_date  konut_faizi  konut_kredisi\n2021-01-31  18.388  276785.0\n2021-02-28  17.985  276263.0"]


def test_uc_ondalikli_arac_sayisi_turkce_yuvarlanmis_ve_tam_yazimla_eslesir() -> None:
    for answer in ("Ocak 2021 faizi %18,39.", "Ocak 2021 faizi %18,388.", "Şubat 2021 faizi %17,99.", "Şubat 2021 faizi %17,98."):
        assert grounding_check("soru", answer, TOOL) == "OK", answer


def test_binlik_okuma_korunur_ve_uydurma_sayi_hala_yakalanir() -> None:
    assert grounding_check("soru", "Ocak 2021 bakiyesi 276.785 milyon TL.", TOOL) == "OK"
    assert grounding_check("soru", "Havuzda 18.388 bin konut var.", ["18388 konut"]) == "OK", "Türkçe binlik cevap, düz araç sayısı"
    assert grounding_check("soru", "Faiz %19,40 oldu.", TOOL).startswith("MISS:19,40")
    assert grounding_check("soru", "Bakiye 312.450 milyon TL.", TOOL).startswith("MISS:312.450")


def test_cevap_metni_tek_okuma_havuz_iki_okuma() -> None:
    assert numbers_in("18.388") == [18388.0]
    assert sorted(numbers_in("18.388", both_readings=True)) == [18.388, 18388.0]
    assert numbers_in("1.234.567", both_readings=True) == [1234567.0], "çok gruplu sayı yalnız binliktir"
    assert numbers_in("0.263", both_readings=True) == [0.263]
