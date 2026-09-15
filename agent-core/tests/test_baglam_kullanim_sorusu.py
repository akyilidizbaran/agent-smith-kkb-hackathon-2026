"""Bağlam: ürün kullanım sorusu önceki soruya kaymaz (15 Eyl arayüz denemesi, ADR-0081).

Kullanıcının akışı: "naber" → "elimizde hangi veriler var" (katalogdan) → "architect rolüne nasıl geçebilirim". Üçüncü soru
"veri çekilmedi" diye geri gönderildi; model sayı çekmeye zorlanıp ikinci sorunun cevabını (veri seti tablosu) yeniden yazdı.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kkb_agent.core.small_talk import UPLOAD_HELP_KINDS, UPLOAD_HELP_MB, capability_reply, is_usage_question  # noqa: E402
from kkb_agent.llm.base import LLMResponse  # noqa: E402
from kkb_agent.web_app import UPLOAD_KINDS, UPLOAD_MAX_BYTES  # noqa: E402
from test_agent_loop import _agent, _ScriptedLLM  # noqa: E402


class _RecordingLLM(_ScriptedLLM):
    def __init__(self, turns: list[LLMResponse]) -> None:
        super().__init__(turns)
        self.messages: list[list] = []

    def chat(self, messages, **kwargs) -> LLMResponse:
        self.messages.append(list(messages))
        return super().chat(messages, **kwargs)


def _reply(question: str, tools: set[str] | None = None) -> str | None:
    return capability_reply(question, tools=tools if tools is not None else {"lakehouse_query", "web_url"}, datasets=lambda: [])


def test_kullanim_sorusu_tanimi() -> None:
    for q in ("architect rolüne nasıl geçebilirim", "Analyst profiline nasıl dönerim?", "Dosyayı nasıl yüklerim?",
              "Tabloyu nasıl indiririm?", "Raporu nereden indirebilirim", "Oturumu nasıl sıfırlarım?", "Kanıt zincirini nasıl okurum?"):
        assert is_usage_question(q), q
    for q in ("Konut kredisi bakiyesi nasıl değişti?", "Kredi kullanımı nasıl değişti?", "Bankaların risk profilini göster",
              "Bu dosyayı nasıl analiz edersin?\n\nDosya: /srv/uploads/ab12cd34/cb6d79f3_hastane.csv",
              "2025 raporundaki konut kredisi nasıl?", "Dosyadaki toplam başvuru ne kadar, nasıl hesaplarsın?", "naber"):
        assert not is_usage_question(q), q


def test_rol_sorusu_gercek_profile_gore_cevaplanir() -> None:
    analyst = _reply("architect rolüne nasıl geçebilirim")
    assert analyst.startswith("Şu an Analyst profilindesin") and "Profil rozetine" in analyst and "operatör anahtarını" in analyst
    architect = _reply("Analyst profiline nasıl dönerim?", {"lakehouse_query", "ingest_from_url", "promote_draft"})
    assert architect.startswith("Şu an Architect profilindesin") and "Analyst'i seç" in architect
    assert _reply("Profili nasıl değiştiririm?").startswith("Şu an Analyst"), "analiz sözcüğü koruması ('değiş') kullanımı yutmaz"


def test_yukleme_ve_indirme_cevabi_arayuzle_tutarli() -> None:
    upload = _reply("Dosyayı nasıl yüklerim?")
    assert set(UPLOAD_HELP_KINDS) == {k.lstrip(".").upper() for k in UPLOAD_KINDS}, "arayüzün kabul ettiği türlerle aynı"
    assert UPLOAD_HELP_MB * 1024 * 1024 == UPLOAD_MAX_BYTES and f"{UPLOAD_HELP_MB} MB" in upload
    assert "kataloğa yazılmaz" in upload and "taslak seri" in _reply("Dosyayı nasıl yüklerim?", {"ingest_from_url"})
    export = _reply("Tabloyu nasıl indiririm?")
    assert "CSV" in export and "XLSX" in export and "HTML rapor" in export, "'tablo' analiz sözcüğü korumasına takılmaz"
    assert _reply("Kanıt zincirini nasıl okurum?") is None, "deterministik konusu olmayan kullanım sorusu modele gider"


def test_oturum_sifirlama_arayuzdeki_dugmelerle_cevaplanir() -> None:
    """Canlı S5 (15 Eyl): model üç tekrarda da "'oturumu sıfırla' yazmanız yeterli" dedi."""
    html = (Path(__file__).resolve().parents[1] / "src" / "kkb_agent" / "static" / "index.html").read_text(encoding="utf-8")
    assert "Oturumu sıfırla</button>" in html and "Tam veri sıfırlama…</button>" in html, "arayüz etiketleri cevaptakilerle aynı"
    analyst = _reply("Oturumu nasıl sıfırlarım?")
    assert "'Oturumu sıfırla' düğmesi" in analyst and "yalnız Architect" in analyst and "yazmanız" not in analyst
    assert "'Tam veri sıfırlama…' düğmesi" in _reply("Oturumu nasıl sıfırlarım?", {"ingest_from_url", "promote_draft"})


def test_kullanicinin_akisi_rol_sorusu_onceki_soruya_kaymaz() -> None:
    llm = _RecordingLLM([LLMResponse(content="Veri havuzunda şu kaynaklar ve seriler var: …")])
    agent, _ = _agent(llm)
    agent.ask("naber")
    agent.ask("elimizde hangi veriler var")
    ans = agent.ask("architect rolüne nasıl geçebilirim")
    assert ans.text.startswith("Şu an Analyst profilindesin") and "kaynaklar ve seriler" not in ans.text
    assert llm.messages == [], "üç soru da modele gitmedi"


def test_modele_giden_kullanim_sorusu_geri_gonderilmez() -> None:
    draft = "Her halka bir öncekine bağlanır: cevap → tablo → sorgu → gözlem → ham dosya → kaynak."
    llm = _RecordingLLM([LLMResponse(content=draft), LLMResponse(content="Veri havuzunda şu kaynaklar var.")])
    agent, _ = _agent(llm)
    agent.ask("elimizde hangi veriler var")
    ans = agent.ask("Kanıt zincirini nasıl okurum?")
    assert ans.text == draft and len(llm.messages) == 1
    assert not any("veri çekilmeden" in (s.thought or "") for s in ans.steps)


def test_belirsiz_soruda_geri_gonderme_notu_son_soruyu_yazar() -> None:
    llm = _RecordingLLM([LLMResponse(content="Bu bilgi bende yok."), LLMResponse(content="Bu konuda elimde bilgi yok.")])
    agent, _ = _agent(llm)
    agent.ask("elimizde hangi veriler var")
    ans = agent.ask("Bu sistemi kim geliştirdi?")
    assert any("veri çekilmeden" in (s.thought or "") for s in ans.steps), "kullanım/kimlik değilse geri gönderme sürer"
    note = llm.messages[1][-1].content
    assert "«Bu sistemi kim geliştirdi?»" in note and "Önceki sorulara dönme" in note and "veri istemiyorsa" in note


def _with_table(llm) -> object:
    agent, _ = _agent(llm)
    agent.workspace.set_table(pd.DataFrame({"donem": ["2025-11-30", "2025-12-31"], "bakiye": [658770.0, 678970.0]}),
                              description="konut kredisi bakiyesi")
    return agent


def test_tablo_varken_kullanim_sorusunda_anlatim_fiili_islem_iddiasi_sayilmaz() -> None:
    """Canlı S3 (15 Eyl): 'Kanıt zincirini nasıl okurum?' geri gönderilince model önceki Aralık bakiyesi sorusunu cevapladı."""
    draft = "Önce sorgu çalıştırılır ve tablo hesaplandı olarak işaretlenir; sonra her halka bir öncekine bağlanır: tablo → sorgu → kaynak."
    llm = _RecordingLLM([LLMResponse(content=draft), LLMResponse(content="Aralık bakiyesi 678.970 milyon TL.")])
    agent = _with_table(llm)
    ans = agent.ask("Kanıt zincirini nasıl okurum?")
    assert ans.text == draft and len(llm.messages) == 1, "anlatım fiili (çalıştırılır, hesaplandı) geri gönderme sebebi değil"


def test_yakin_uydurma_tutar_ve_satir_sayisina_denk_ondalik_okuma_dogrulanmis_sayilmaz() -> None:
    """Canlı S3 (15 Eyl): tabloda yalnız Aralık 678.970 varken araçsız cevap "Kasım 677.970, fark +1.000" yazdı ve yayımlandı:
    677.970 göreli %0,5 toleransla 678.970'e, "1.000" ondalık okumayla (1,0) satır sayısı 1'e eşleşiyordu."""
    from kkb_agent.core.agent import unverified_numbers

    december = pd.DataFrame({"observation_date": ["2025-12-31"], "value": [678970.0]})
    bad = unverified_numbers("Kasım 2025 sonu: 677.970 milyon TL; Aralık 2025 sonu: 678.970 milyon TL; fark +1.000 milyon TL.", december)
    assert "677.970" in bad and any(x.lstrip("+") == "1.000" for x in bad) and "678.970" not in bad
    assert unverified_numbers("Aralık 2025 sonu bakiye 678.970 milyon TL (1 satır).", december) == []
    assert unverified_numbers("Bakiye 678.970 milyon TL.", pd.DataFrame({"value": [678969.6]})) == [], "gösterim yuvarlaması (0,5) geçer"
    rates = pd.DataFrame({"faiz": [18.388, 37.2875]})
    assert unverified_numbers("Faiz 18.388 ve %37,29.", rates) == [], "üç ondalıklı nokta yazımı ve virgüllü yuvarlama geçer"
    assert unverified_numbers("Faiz 18.100.", rates) == ["18.100"], "ondalık okuma gevşek değil"


def test_tablo_varken_uydurma_fark_yayimlanmaz() -> None:
    fabricated = "Kasım 2025 sonu: 677.970 milyon TL. Aralık 2025 sonu: 678.970 milyon TL. Fark: +1.000 milyon TL."
    llm = _RecordingLLM([LLMResponse(content=fabricated), LLMResponse(content=fabricated)])
    agent, _ = _agent(llm)
    agent.workspace.set_table(pd.DataFrame({"observation_date": ["2025-12-31"], "value": [678970.0]}), description="Aralık bakiyesi")
    ans = agent.ask("Bir önceki aya göre farkı ne?")
    assert "677.970" in llm.messages[1][-1].content, "geri gönderme notu uydurma sayıyı adıyla söyler"
    assert "677.970" not in ans.text and "1.000" not in ans.text, "ikinci denemede de uydurma tutar yayımlanmaz (D02 son çıkış)"


def test_tablo_varken_uydurma_sayi_geri_gonderilir_not_son_soruyu_yazar() -> None:
    llm = _RecordingLLM([LLMResponse(content="Örneğin 999.999 değerindeki bir sayı tabloya bağlanır."),
                         LLMResponse(content="Her sayı tablodaki hücreye, sorguya ve kaynağa bağlanır.")])
    agent = _with_table(llm)
    ans = agent.ask("Kanıt zincirini nasıl okurum?")
    assert len(llm.messages) == 2 and ans.text == "Her sayı tablodaki hücreye, sorguya ve kaynağa bağlanır."
    note = llm.messages[1][-1].content
    assert note.startswith("Kullanıcının SON sorusu: «Kanıt zincirini nasıl okurum?»") and "Önceki sorulara dönme" in note
    assert "999.999" in note, "sayı notu korunur: hangi sayının tabloda olmadığı söylenir"
