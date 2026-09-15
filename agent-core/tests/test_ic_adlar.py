"""Kullanıcıya dönük metinde iç kimlik ve veri mimarisi adı yok (ADR-0082).

15 Eyl arayüz denemesi: "Elinde nasıl veriler var" deterministik veri seti cevabına düşmedi; model 5 aramadan sonra
"4. Hazır Gold tabloları" başlığı ve doğrulanmamış "687+ seri" yazdı. Grafik altyazısı ve rapor kaynakları iç etiketle yazılıyordu.
Kanıt zinciri (sağ panel) katman adlarını taşımaya devam eder.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kkb_agent.core.agent import SYSTEM_PROMPT  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.small_talk import capability_reply  # noqa: E402
from kkb_agent.core.tool import Tool, ToolResult  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.core.agent import AnalyticsAgent  # noqa: E402
from kkb_agent.labels import humanize_internal, readable_source, spec_origin  # noqa: E402
from kkb_agent.llm.base import LLMResponse, ToolCall  # noqa: E402
from test_agent_loop import _agent, _ScriptedLLM  # noqa: E402
from test_geri_bildirim_2026_09_14 import _spec  # noqa: E402

HTML = Path(__file__).resolve().parents[1] / "src" / "kkb_agent" / "static" / "index.html"


def test_nasil_ne_tur_veri_sorulari_deterministik() -> None:
    d0, d1 = date(2016, 1, 31), date(2026, 6, 30)
    specs = [_spec("a", "bddk_monthly", d0, d1), _spec("gold.x", "gold", d0, d1)]
    for q in ("Elinde nasıl veriler var", "Elimizde ne tür veriler var?", "Ne çeşit verilerle çalışıyorsun?", "elimizde hangi veriler var"):
        reply = capability_reply(q, tools=set(), datasets=lambda: specs)
        assert reply is not None and reply.startswith("Veri havuzunda") and "gold" not in reply.lower(), q
    for q in ("Hangi seriler konut kredisini gösteriyor?", "Konut kredisi nasıl değişti?", "2025'te hangi veriler arttı?"):
        assert capability_reply(q, tools=set(), datasets=lambda: specs) is None, q


def test_kaynak_etiketi_ve_tablonun_kaynagi_okunur() -> None:
    assert readable_source("bddk_monthly — Tüketici Kredileri - Konut, Toplam (Sektör)") == "BDDK Aylık Bülten — Tüketici Kredileri - Konut, Toplam (Sektör)"
    assert readable_source("gold — join_on_period") == "hesaplanmış tablo — dönem eşlemeli birleştirme"
    assert readable_source("gold — Konut kredisi faiz oranı, aylık ortalama") == "hesaplanmış tablo — Konut kredisi faiz oranı, aylık ortalama"
    assert readable_source("adhoc — acil_basvuru — acil_basvuru_aylik.csv (taslak)") == "kullanıcının eklediği seri — acil basvuru"
    assert readable_source("web — TCMB kur sayfası") == "web — TCMB kur sayfası" and readable_source("türetilmiş sütun — a/b") == "türetilmiş sütun — a/b"
    gold = _spec("gold.faiz_dolar_aylik", "gold", date(2016, 1, 31), date(2026, 6, 30)).model_copy(
        update={"source_detail": "gold.faiz_dolar_aylik — join_on_period(evds:TP.KTF12, bddk_monthly:1534_Toplam) kurulum abcd1234"})
    assert spec_origin(gold) == "hesaplanmış tablo (TCMB EVDS ve BDDK Aylık Bülten verisinden)"
    assert spec_origin(_spec("a", "bddk_finturk", date(2016, 3, 31), date(2026, 6, 30))) == "BDDK FinTürk (il bazında)"


def test_gercek_cevaptaki_gold_basligi_ve_kimlikler_cevrilir() -> None:
    faiz = _spec("gold.konut_faizi_aylik", "gold", date(2016, 1, 31), date(2026, 6, 30)).model_copy(
        update={"name": "Konut kredisi faiz oranı, aylık ortalama"})
    text, changed = humanize_internal("**4. Hazır Gold tabloları (aylık/çeyreklik karşılaştırma)**\n- Tüketici kredisi kırılımı (aylık)", [faiz])
    assert text.startswith("**4. Hesaplanmış tablolar (aylık/çeyreklik karşılaştırma)**") and changed
    assert humanize_internal("Bu değer Gold tablosunda duruyor.")[0] == "Bu değer hesaplanmış tabloda duruyor."
    assert humanize_internal("Değerler `gold.konut_faizi_aylik` tablosundan.", [faiz])[0] == "Değerler Konut kredisi faiz oranı, aylık ortalama tablosundan."
    assert humanize_internal("evds:TP.KTF12 serisi haftalıktır.")[0] == "TCMB EVDS serisi haftalıktır.", "'serisi serisi' olmaz"
    assert humanize_internal("Kaynak bddk_monthly:1534_Toplam.")[0] == "Kaynak BDDK Aylık Bülten serisi."
    assert humanize_internal("Silver katmanından okunur; Silver gözlemleri 43.830.")[0] == "Kaynak verisinden okunur; gözlemleri 43.830.", \
        "metin başında büyük harf korunur"
    assert humanize_internal("Değerler Silver katmanından okunur.")[0] == "Değerler kaynak verisinden okunur."
    plain = "2025 Aralık bakiyesi 678.970 milyon TL; kaynak BDDK Aylık Bülten. Altın fiyatı verisi yok."
    assert humanize_internal(plain) == (plain, [])


def test_ajanin_son_cevabinda_ic_ad_kalmaz() -> None:
    llm = _ScriptedLLM([LLMResponse(content="Hazır Gold tabloları var; faiz gold.konut_faizi_aylik tablosunda.")])
    agent, _ = _agent(llm)
    ans = agent.ask("Sen kimsin?")
    assert "Gold" not in ans.text and "gold." not in ans.text and ans.text.startswith("Hesaplanmış tablolar var")
    assert any("iç adlar kullanıcı diline çevrildi" in (s.thought or "") for s in ans.steps)
    assert "gold." not in agent._history[-1].content, "sohbet geçmişine de sade metin girer"


class _SearchParams(BaseModel):
    query: str


class _CatalogSearch(Tool):
    name = "katalog_ara"
    description = "katalog"
    Params = _SearchParams
    role = "retrieve"

    def run(self, params: BaseModel) -> ToolResult:
        return ToolResult(content="Bulunan tablolar:\n- a: Seri A [kapsam: 2016-01-31→2026-06-30]\n- b: Seri B")


def test_tablosuz_katalog_turunda_dogrulanmamis_sayi_yayimlanmaz() -> None:
    registry = ToolRegistry()
    registry.register(_CatalogSearch())
    llm = _ScriptedLLM([LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="katalog_ara", arguments={"query": "veri"})]),
                        LLMResponse(content="Veri havuzunda iki seri görünüyor. Toplamda 687 seri mevcut.")])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=6)
    ans = agent.ask("Katalogda ne görüyorsun, kısaca özetle")
    assert "687" not in ans.text, ans.text
    assert any("çıkarıldı" in (s.thought or "") for s in ans.steps)


def test_tablosuz_turda_onceki_cevaptaki_dogru_sayi_silinmez_not_tablo_demez() -> None:
    """S8 canlı senaryosu (15 Eyl, 3/3): önceki deterministik cevaptaki '81 il' model tarafından tekrarlanınca, havuz yalnız bu turun
    araç çıktısı olduğu için doğru madde siliniyor ve not tablo yokken 'doğrulanmış değerler tabloda' diyordu."""
    from kkb_agent.llm.base import ChatMessage

    registry = ToolRegistry()
    registry.register(_CatalogSearch())
    llm = _ScriptedLLM([LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="katalog_ara", arguments={"query": "konut"})]),
                        # Kalan metin ≥40 harf olmalı: daha kısası D02'de "anlamlı metin kalmadı" sayılıp genel uyarıyla değişir.
                        LLMResponse(content="İl bazında 81 il için konut kredisi ve takipteki konut kredisi serileri çeyreklik olarak var. "
                                            "Toplamda 687 seri mevcut.")])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=6)
    agent._history += [ChatMessage(role="user", content="elimizde hangi veriler var"),
                       ChatMessage(role="assistant", content="- BDDK FinTürk (il bazında): 648 seri; 81 il × 8 konu: konut kredisi")]
    ans = agent.ask("Bunlardan konut kredisiyle ilgili hangileri var?")
    assert "81 il için konut kredisi ve takipteki konut kredisi" in ans.text, "önceki doğrulanmış cevaptaki sayı kaynak sayılır"
    assert "687" not in ans.text and ans.text.rstrip().endswith("cevaptan çıkarıldı.)") and "tabloda" not in ans.text


def test_aracsiz_tablosuz_turda_hesaplanmis_sayi_da_dogrulanir() -> None:
    """S8 canlı (15 Eyl): model araç çağırmadan 'konut kredisiyle ilgili toplam 166 seri' yazdı; denetim yalnız araç çalışan turdaydı."""
    from kkb_agent.llm.base import ChatMessage

    reply = ("BDDK FinTürk'te 81 il için konut kredisi ve takipteki konut kredisi serileri çeyreklik olarak bulunuyor. "
             "Toplamda konut kredisiyle ilgili 166 seri var.")
    llm = _ScriptedLLM([LLMResponse(content=reply)])
    agent, _ = _agent(llm)
    agent._history += [ChatMessage(role="user", content="elimizde hangi veriler var"),
                       ChatMessage(role="assistant", content="- BDDK FinTürk (il bazında): 648 seri; 81 il × 8 konu: konut kredisi")]
    ans = agent.ask("Bunlardan konut kredisiyle ilgili hangileri var?")
    assert "81 il için konut kredisi" in ans.text and "166" not in ans.text, ans.text
    fresh, _ = _agent(_ScriptedLLM([LLMResponse(content=reply)]))
    assert "166" in fresh.ask("Konut kredisiyle ilgili neler var?").text, "havuz boşsa (geçmiş, kart, araç yok) denetim atlanır"


def test_istem_kurali_ve_arayuz_etiketleri() -> None:
    assert "veri mimarisi katman adları (Gold, Silver, Bronze, RAW, lakehouse) YAZMA" in SYSTEM_PROMPT
    html = HTML.read_text(encoding="utf-8")
    assert '<div class="k">hesaplanmış tablo</div>' in html and '<div class="k">gözlem</div>' in html
    # Sol panel ve durum penceresi kullanıcı diliyle; "Silver gözlemi" yalnız kanıt yolculuğu halkalarında kalır (kullanıcı onayı).
    for old in ('<div class="k">Gold tablosu</div>', '<div class="k">Silver gözlemi</div>', "Silver gözlemi · ", "Gold tablosu`",
                "Gold'a hazır"):
        assert old not in html, old
    assert '"Silver · gözlem"' in html and '"Bronze · ham dosya"' in html, "kanıt zinciri katman adlarını taşımaya devam eder"
