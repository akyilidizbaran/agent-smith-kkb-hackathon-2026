"""Selamlaşma ve öneri kuyruğu — harness kuralı, LLM'e iş yok (ADR-0045)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.small_talk import is_small_talk, small_talk_reply, trim_unsolicited_offers  # noqa: E402


def test_selamlasma_dar_sozluk() -> None:
    for q in ("selam", "Selam!", "merhaba", "sa", "günaydın", "nasılsın?", "teşekkürler", "tamam", "ok", "iyi akşamlar", "selam kral"):
        assert is_small_talk(q), q
    for q in ("selam, 2025 konut kredisi bakiyesi?", "tamam devam et", "merhaba, tabloyu göster", "selam grafik çiz",
              "", "nasıl hesapladın?", "2025", "konut", "selam bu veri nereden geliyor"):
        assert not is_small_talk(q), q


def test_selam_cevabi_tek_cumle_oneri_yok() -> None:
    r = small_talk_reply("selam", has_table=False)
    assert r == "Selam. Sorunu yazabilirsin."
    r2 = small_talk_reply("selam", has_table=True)
    assert "Aktif tablo duruyor" in r2 and "\n" not in r2 and "Örneğin" not in r2
    assert small_talk_reply("teşekkürler", has_table=True) == "Rica ederim."
    assert small_talk_reply("tamam", has_table=True) == "Tamam."


def test_oneri_kuyrugu_kirpilir() -> None:
    text = ("2025 sonunda bakiye 678.970 milyon TL. Kaynak: BDDK Aylık Bülten.\n\n"
            "Başka bir soru ya da analiz istersen buradayım. Örneğin:\n\n"
            "- Taşıt kredisi\n- Faiz oranları\n\nNe yapmak istersin?")
    out, trimmed = trim_unsolicited_offers(text)
    assert trimmed and out == "2025 sonunda bakiye 678.970 milyon TL. Kaynak: BDDK Aylık Bülten."


def test_istersen_ile_baslayan_son_paragraf_duser_ortadaki_kalir() -> None:
    text = "Ocak 523.455, Aralık 678.970 milyon TL.\n\nÖrneğin Haziran'da artış yavaşladı (+7.812).\n\nİstersen çeyreklik kırılımı da çıkarabilirim."
    out, trimmed = trim_unsolicited_offers(text)
    assert trimmed and out.endswith("(+7.812).") and "İstersen" not in out


def test_tumuyle_oneri_olan_cevap_bos_birakilmaz_emoji_gider() -> None:
    text = "Selam! 👋\n\nBaşka bir soru istersen buradayım. Örneğin:\n- Taşıt kredisi"
    out, trimmed = trim_unsolicited_offers(text)
    assert "👋" not in out and "Taşıt" in out  # yalnız açılış selamı kalırdı → kırpılmaz, emoji gider
    plain = "Bakiye 678.970 milyon TL (BDDK)."
    assert trim_unsolicited_offers(plain) == (plain, False)
