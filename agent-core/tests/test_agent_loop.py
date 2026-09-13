"""Harness'ın modelden bağımsız garantileri — sahte LLM ile.

Bu dosyadaki hiçbir test MIA'ya çıkmaz. Ölçtüğü şey modelin ne kadar akıllı olduğu
değil, harness'ın modelin bilinen kötü davranışlarına ne yaptığı: aynı çağrıyı
tekrarlamak, veri çekmeden cevap yazmak, çözülmeyecek bir hatada ısrar etmek.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.agent import AnalyticsAgent  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.tool import Tool, ToolResult  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.llm.base import ChatMessage, LLMResponse, ToolCall  # noqa: E402


class _Params(BaseModel):
    year: int = 2025


class _CountingTool(Tool):
    """Çağrıldığını sayan, her seferinde aynı sonucu veren bir veri aracı."""

    name = "lakehouse_query"
    description = "test aracı"
    Params = _Params

    def __init__(self) -> None:
        self.calls = 0

    def run(self, params: _Params) -> ToolResult:
        self.calls += 1
        return ToolResult(
            content=f"Sorgu başarılı: 1 satır. yil={params.year} deger=100",
            data=pd.DataFrame({"yil": [params.year], "deger": [100.0]}),
        )


class _ScriptedLLM:
    """Kendisine verilen turları sırayla oynar; bittiğinde sonuncuyu tekrarlar."""

    model = "scripted"

    def __init__(self, turns: list[LLMResponse]) -> None:
        self._turns = turns
        self.seen_tool_offers: list[bool] = []

    def supports_native_tools(self) -> bool:
        return True

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None) -> LLMResponse:
        self.seen_tool_offers.append(tools is not None)
        turn = self._turns[min(len(self.seen_tool_offers) - 1, len(self._turns) - 1)]
        return turn


def _call(i: int) -> ToolCall:
    return ToolCall(id=f"c{i}", name="lakehouse_query", arguments={"year": 2025})


def _agent(llm) -> tuple[AnalyticsAgent, _CountingTool]:
    tool = _CountingTool()
    registry = ToolRegistry()
    registry.register(tool)
    agent = AnalyticsAgent(
        llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=10
    )
    return agent, tool


def test_ayni_cagri_tekrarlanirsa_arac_bir_kez_calisir() -> None:
    """Kilit aracı korur: model ne kadar isterse istesin yan etki bir kez olur."""

    llm = _ScriptedLLM([LLMResponse(content="", tool_calls=[_call(i)]) for i in range(6)])
    agent, tool = _agent(llm)

    answer = agent.ask("2025'te ne oldu?")

    assert tool.calls == 1, "aynı argümanla ikinci kez çalışmamalıydı"
    assert answer.error_codes().get("DUPLICATE_CALL")


def test_ikinci_tekrarda_araclar_geri_alinir_ve_cevap_yazdirilir() -> None:
    """Kilit tek başına döngüyü kırmıyor; ölçülmüş hata modu buydu.

    11 Eylül motor karşılaştırmasında L4-01, DUPLICATE_CALL'ı yedi kez arka arkaya
    alıp adım limitini yaktı: araç korunmuştu ama model aynı çağrıyı istemeye devam
    ediyordu, çünkü hata "tekrar denenebilir" sınıfındaydı. İkinci tekrardan sonra
    harness araçları geri alıyor — model artık ancak cevap yazabilir.
    """

    llm = _ScriptedLLM([LLMResponse(content="", tool_calls=[_call(i)]) for i in range(9)])
    agent, tool = _agent(llm)

    answer = agent.ask("2025'te ne oldu?")

    assert tool.calls == 1
    assert not answer.hit_step_limit, "adım limitine kadar dönmemeliydi"
    # Son tur araçsız yapılmalı: modele araç teklif edilmediği en az bir tur var.
    assert llm.seen_tool_offers[-1] is False
    # Üç tur yeter: ilk çağrı, ilk tekrar, ikinci tekrar + araçsız kapanış.
    assert len(llm.seen_tool_offers) <= 5, llm.seen_tool_offers


def test_veri_cekmeden_cevap_bir_kez_geri_gonderilir() -> None:
    """Katalog bilgisi cevap değildir; harness bir kez geri gönderir, sonra bırakır."""

    llm = _ScriptedLLM([LLMResponse(content="Konut kredisi arttı.")])
    agent, _ = _agent(llm)

    answer = agent.ask("2025'te ne oldu?")

    assert any(s.thought and "veri" in s.thought.lower() for s in answer.steps)
    assert answer.text


class _NoToolTool(Tool):
    """Sayı döndüren bir veri aracı; grounding havuzunu doldurmak için."""

    name = "lakehouse_query"
    description = "test aracı"
    Params = _Params

    def run(self, params: _Params) -> ToolResult:
        return ToolResult(
            content="Sorgu başarılı: 2 satır.\ndonem=2025-01 deger=100.0\ndonem=2025-12 deger=110.0",
            data=pd.DataFrame({"donem": ["2025-01", "2025-12"], "deger": [100.0, 110.0]}),
        )


def _grounding_agent(turns: list[LLMResponse]) -> tuple[AnalyticsAgent, _ScriptedLLM]:
    registry = ToolRegistry()
    registry.register(_NoToolTool())
    llm = _ScriptedLLM(turns)
    return (
        AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=10),
        llm,
    )


def test_anlatidaki_uydurma_sayi_bir_kez_geri_gonderilir() -> None:
    """SQL'de hesap yaptırmak, modelin anlatıda kendi aritmetiğini yapmasını engellemiyor.

    Araç çıktısında 100 ve 110 var; "10,5 arttı" hiçbirinde yok. Harness cevabı bir kez
    geri gönderir; ikinci cevap temizse o gider.
    """
    agent, llm = _grounding_agent([
        LLMResponse(content="", tool_calls=[_call(1)]),
        LLMResponse(content="Bakiye 10,5 milyon TL arttı."),
        LLMResponse(content="Bakiye 100'den 110'a çıktı."),
    ])

    answer = agent.ask("2025'te ne oldu?")

    assert answer.text.startswith("Bakiye 100")
    assert answer.grounding == "OK"
    assert any(s.thought and s.thought.startswith("grounding: MISS") for s in answer.steps)


def test_ikinci_denemede_de_dogrulanamayan_sayi_isaretlenir() -> None:
    """Cevap engellenmiyor — doğrulanamayan değer açıkça işaretleniyor.

    Tabloyu kullanıcı zaten görüyor; cevabı tümden bastırmak bilgi kaybı olur.
    """
    agent, _ = _grounding_agent([
        LLMResponse(content="", tool_calls=[_call(1)]),
        LLMResponse(content="Bakiye 10,5 milyon TL arttı."),
        LLMResponse(content="Yine de 10,5 milyon TL arttı."),
    ])

    answer = agent.ask("2025'te ne oldu?")

    assert "doğrulanamadı" in answer.text
    assert answer.grounding.startswith("MISS")


def test_nedensellik_iddiasi_da_geri_gonderilir() -> None:
    """Veriden çıkarılamayan neden-sonuç, uydurma sayı kadar risklidir."""
    agent, _ = _grounding_agent([
        LLMResponse(content="", tool_calls=[_call(1)]),
        LLMResponse(content="Bakiye 100'den 110'a çıktı; faiz indirimi buna yol açtı."),
        LLMResponse(content="Bakiye 100'den 110'a çıktı."),
    ])

    answer = agent.ask("2025'te ne oldu?")

    assert "yol açtı" not in answer.text
    assert answer.grounding == "OK"


def test_veri_cekilmemisse_grounding_olculmez() -> None:
    """Havuz boşken her sayı 'eksik' görünür; ölçüm anlamsız olur."""
    agent, _ = _grounding_agent([LLMResponse(content="Kapsam 2021-2026 arası.")])

    answer = agent.ask("Hangi yıllar var?")

    assert answer.grounding == ""


def test_extra_yazilabilir_olmali() -> None:
    """Karşılaştırma koşucusu iki turlu vakalarda bu alana geri yazıyor.

    `answer.extra = {...}` — property olarak tanımlanınca bu atama AttributeError
    veriyor ve vaka "çalıştırma hatası" olarak düşüyor. Ölçüldü: G6 ve G7 0/3, hem de
    motorun davranışıyla hiç ilgisi olmayan bir sebeple. Ölçüm aracının okuduğu
    yüzey, ölçülen şeyi bozmamalı.
    """
    from kkb_agent.core.agent import AgentAnswer, AgentStep

    answer = AgentAnswer(
        text="x",
        steps=[AgentStep(index=1, tool_name="lakehouse_query", error_code="SQL_FAILED")],
        grounding="OK",
    )

    assert answer.extra == {"grounding": "OK", "error_codes": ["SQL_FAILED"]}

    answer.extra = {"grounding": "OK | MISS:5", "error_codes": ["SQL_FAILED", "SQL_FAILED"]}
    assert answer.extra["grounding"] == "OK | MISS:5"


def test_kanit_paneli_cevaba_ilistirilir_ve_hata_cevabi_dusurmez() -> None:
    """ADR-0033: panel cevaptan SONRA kurulur; inşacı patlarsa cevap yine döner."""
    from kkb_agent.core.evidence import EvidenceBuilder

    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call(1)]),
        LLMResponse(content="2025 yılında değer 100 idi.", tool_calls=[]),
    ])
    tool = _CountingTool()
    registry = ToolRegistry()
    registry.register(tool)
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=10,
                           evidence=EvidenceBuilder(object()))
    # _CountingTool workspace'e yazmıyor; tabloyu elle koyup paneli ölçelim
    answer = agent.ask("2025'te değer?")
    assert answer.evidence is not None and "analiz tablosu yok" in answer.evidence.gaps

    class Broken:
        def build(self, *a, **k):
            raise RuntimeError("patladı")

    agent2 = AnalyticsAgent(llm=_ScriptedLLM([LLMResponse(content="Cevap.", tool_calls=[])]),
                            registry=registry, workspace=AnalysisWorkspace(), max_steps=3, evidence=Broken())
    assert agent2.ask("soru").text


class _ChartParams(BaseModel):
    chart_type: str = "line"


class _FakeChart(Tool):
    name = "chart"
    role = "narrate"
    description = "sahte grafik"
    Params = _ChartParams

    def __init__(self) -> None:
        self.calls = 0

    def run(self, params: _ChartParams) -> ToolResult:
        self.calls += 1
        return ToolResult(content="GRAFİK: çizildi", artifacts={"chart": {"png_path": "/tmp/x.png", "kind": "chart"}})


def test_grafik_istendi_chart_cagrilmadan_cevap_bir_kez_geri_gonderilir() -> None:
    """Ölçüldü (Deney 2, tur 3): model tabloyu doğrulamak için sorgular atıp grafiksiz cevap yazdı."""
    tool, chart = _CountingTool(), _FakeChart()
    registry = ToolRegistry(); registry.register(tool); registry.register(chart)
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call(1)]),
        LLMResponse(content="Değer 100.", tool_calls=[]),                       # grafiksiz cevap → geri
        LLMResponse(content="", tool_calls=[ToolCall(id="g", name="chart", arguments={"chart_type": "line"})]),
        LLMResponse(content="Grafik çizildi, değer 100.", tool_calls=[]),
    ])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=10)
    answer = agent.ask("2025 değerinin grafiğini çiz")
    assert chart.calls == 1 and any("grafik istendi" in (s.thought or "") for s in answer.steps)
    assert answer.artifacts and answer.artifacts[0]["png_path"] == "/tmp/x.png"
    assert "Grafik çizildi" in answer.text


def test_grafik_istenmediyse_chart_zorlanmaz() -> None:
    tool, chart = _CountingTool(), _FakeChart()
    registry = ToolRegistry(); registry.register(tool); registry.register(chart)
    llm = _ScriptedLLM([LLMResponse(content="", tool_calls=[_call(1)]), LLMResponse(content="Değer 100.", tool_calls=[])])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=10)
    answer = agent.ask("2025 değeri kaç?")
    assert chart.calls == 0 and answer.text == "Değer 100." and len(answer.steps) == 2


def test_grafik_cizildikten_sonra_veri_cekilmedi_uyarisi_verilmez() -> None:
    """Ölçüldü (Deney 1, tur 5): chart sonrası cevap 'veri çekilmedi' diye geri gönderiliyordu."""
    tool, chart = _CountingTool(), _FakeChart()
    registry = ToolRegistry(); registry.register(tool); registry.register(chart)
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall(id="g", name="chart", arguments={"chart_type": "line"})]),
        LLMResponse(content="Grafik hazır.", tool_calls=[]),
    ])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=10)
    answer = agent.ask("bunun grafiğini çiz")
    assert answer.text == "Grafik hazır." and not any("geri gönderildi" in (s.thought or "") for s in answer.steps)
    assert tool.calls == 0 and len(answer.steps) == 2


class _AnomParams(BaseModel):
    column: str = "deger"


class _FakeAnomaly(Tool):
    name = "anomaly_detect"
    description = "sahte analitik"
    Params = _AnomParams

    def __init__(self) -> None:
        self.calls = 0

    def run(self, params: _AnomParams) -> ToolResult:
        self.calls += 1
        return ToolResult(content="AYKIRILIK: 1 aykırı dönem, 2025-03, skor 2.1")


def test_aykirilik_soruldu_analitik_arac_cagrilmadan_cevap_bir_kez_geri_gonderilir() -> None:
    tool, anom = _CountingTool(), _FakeAnomaly()
    registry = ToolRegistry(); registry.register(tool); registry.register(anom)
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call(1)]),
        LLMResponse(content="Değer 100, aykırı ay yok.", tool_calls=[]),      # araçsız iddia → geri
        LLMResponse(content="", tool_calls=[ToolCall(id="a", name="anomaly_detect", arguments={"column": "deger"})]),
        LLMResponse(content="Bir aykırı dönem var: 2025-03, skor 2.1.", tool_calls=[]),
    ])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=10)
    answer = agent.ask("2025'te değerde aykırı ay var mı?")
    assert anom.calls == 1 and any("analitik istendi" in (s.thought or "") for s in answer.steps)
    assert answer.text.startswith("Bir aykırı dönem var")


def test_selamlasma_llm_e_gitmez() -> None:
    llm = _ScriptedLLM([LLMResponse(content="olmamalı")])
    agent, tool = _agent(llm)
    answer = agent.ask("selam")
    assert answer.text == "Selam. Sorunu yazabilirsin."
    assert len(llm.seen_tool_offers) == 0 and tool.calls == 0
    assert answer.steps[0].role == "narrate" and "LLM çağrılmadı" in answer.steps[0].thought
    assert answer.usage["calls"] == 0 and answer.evidence is None


def test_oneri_kuyrugu_cevaptan_kirpilir_tarihce_de_guncellenir() -> None:
    llm = _ScriptedLLM([LLMResponse(content="Cevap: veri yok.\n\nBaşka bir analiz istersen buradayım. Örneğin:\n- x")])
    agent, _ = _agent(llm)
    answer = agent.ask("2025 konut kredisi bakiyesi")
    assert answer.text == "Cevap: veri yok."
    assert any("kırpıldı" in (s.thought or "") for s in answer.steps if s.role == "narrate")
    assert agent._history[-1].content == "Cevap: veri yok."


def test_arac_turlari_sifir_anlati_turu_ayarli_sicaklik() -> None:
    class _TempLLM(_ScriptedLLM):
        def __init__(self, turns):
            super().__init__(turns); self.temps: list[float] = []

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            self.temps.append(temperature); return super().chat(messages, tools=tools, temperature=temperature, max_tokens=max_tokens)

    llm = _TempLLM([LLMResponse(content="", tool_calls=[_call(1)]), LLMResponse(content="Cevap: 2025 toplam 1.")])
    tool = _CountingTool(); registry = ToolRegistry(); registry.register(tool)
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=10, narrate_temperature=0.5)
    agent.ask("2025 toplam")
    assert llm.temps[0] == 0.0, "araç seçimi turu deterministik kalmalı"
    assert llm.temps[-1] == 0.5, "veri geldikten sonraki anlatı turu ayarlı sıcaklıkla"
    llm2 = _TempLLM([LLMResponse(content="", tool_calls=[_call(1)]), LLMResponse(content="Cevap: 2025 toplam 1.")])
    registry2 = ToolRegistry(); registry2.register(_CountingTool())
    AnalyticsAgent(llm=llm2, registry=registry2, workspace=AnalysisWorkspace(), max_steps=10).ask("2025 toplam")
    assert llm2.temps == [0.0, 0.0], "varsayılan: her tur 0 (testler ve golden deterministik)"


def test_ayni_soru_tekrarinda_kopyalama_yasagi_notu_gider() -> None:
    class _SeeingLLM(_ScriptedLLM):
        def __init__(self, turns):
            super().__init__(turns); self.user_msgs: list[str] = []

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            self.user_msgs += [m.content for m in messages if m.role == "user"]
            return super().chat(messages, tools=tools, temperature=temperature, max_tokens=max_tokens)

    llm = _SeeingLLM([LLMResponse(content="Cevap: 2025 toplam 1.")])
    agent, _ = _agent(llm)

    def asked(q: str) -> bool:  # bu sorunun modele giden hâli tekrar notu taşıyor mu? (nudge mesajları ayrı)
        llm.user_msgs.clear(); agent.ask(q)
        return any(m.startswith(q) and "daha önce soruldu" in m for m in llm.user_msgs)

    assert not asked("2025 toplam?")
    assert asked("2025 Toplam"), "noktalama/büyük-küçük farkı tekrarı gizlememeli"
    assert not asked("2024 toplam")
    assert agent._history[2].content == "2025 Toplam", "tarihçeye not değil, ham soru yazılır"


def test_architect_katalogu_degistirince_profil_yeniden_turetilir() -> None:
    from kkb_agent.domain import DomainProfile

    class _Promote(_CountingTool):
        name = "promote_draft"
        description = "terfi"

    profiles = [DomainProfile(domain="bddk kaynaklı veriler"), DomainProfile(domain="hastane kaynaklı veriler")]
    made: list[int] = []

    def factory() -> DomainProfile:
        made.append(1); return profiles[min(len(made), 2) - 1]

    promote = LLMResponse(content="", tool_calls=[ToolCall(id="p1", name="promote_draft", arguments={"year": 2025})])
    llm = _ScriptedLLM([promote, LLMResponse(content="Taslak terfi etti."), promote, LLMResponse(content="İkinci taslak da terfi etti.")])
    registry = ToolRegistry(); registry.register(_Promote())
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=6, profile_factory=factory)
    assert "yapılandırılmış veri" in agent._system_prompt          # başlangıç: jenerik profil
    agent.ask("bu taslağı kataloğa al")
    assert agent.profile.domain == "bddk kaynaklı veriler" and "bddk kaynaklı veriler" in agent._system_prompt
    assert registry.profile is agent.profile, "araç açıklamaları da yeni profili görür"
    agent.ask("bir daha terfi et")
    assert agent.profile.domain == "hastane kaynaklı veriler", "her katalog değişiminde yeniden türetilir"


def test_arac_cagrilmadan_islem_iddiasi_geri_gonderilir() -> None:
    class _SeeingLLM(_ScriptedLLM):
        def __init__(self, turns):
            super().__init__(turns); self.users: list[list[str]] = []

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            self.users.append([m.content for m in messages if m.role == "user"])
            return super().chat(messages, tools=tools, temperature=temperature, max_tokens=max_tokens)

    llm = _SeeingLLM([LLMResponse(content="Dosya yüklendi ve birleştirildi; 24 il eşleşti."), LLMResponse(content="Dosyayı okuyamadım.")])
    agent, tool = _agent(llm)
    agent.workspace.set_table(pd.DataFrame({"a": [1, 2]}), description="önceki tur")
    ans = agent.ask("Hastane dosyasını yükle ve birleştir.\n\nDosya: /tmp/x.csv")
    assert any("HİÇBİR ARAÇ ÇALIŞMADI" in u for u in llm.users[-1]), "iddia modele geri gönderildi"
    assert any(s.role == "validate" and "işlem iddiası" in (s.thought or "") for s in ans.steps)
    assert ans.text == "Dosyayı okuyamadım."


def test_cok_kisa_donemsiz_soruda_netlestirme_notu() -> None:
    from types import SimpleNamespace
    from kkb_agent.core.agent import vague_candidates

    specs = [SimpleNamespace(name=n) for n in ("Krediler (Toplam)", "Tüketici Kredileri, Toplam", "Konut Kredisi, ANKARA (Sektör)", "Konut Kredisi, İZMİR", "Kredi Kartları")]
    search = lambda q, k: specs
    assert vague_candidates("Kredi bakiyesini göster", search) == ["Krediler", "Tüketici Kredileri", "Konut Kredisi", "Kredi Kartları"]
    assert vague_candidates("2025 kredi bakiyesi", search) == [], "dönem varsa kapı yok"
    assert vague_candidates("Konut kredisi bakiyesi aylık", search) == []
    assert vague_candidates("Konut kredisi bakiyesi göster", search) == [], "3 içerik sözcüğü: yeterince belirli"
    assert vague_candidates("Kredi göster", lambda q, k: specs[:2]) == [], "iki aday: soru sormaya değmez"


def test_a27_model_kesintisi_kontrollu_cevap_sayi_yok_istek_hatasi_yutulmaz() -> None:
    """A27: bağlantı/5xx kesintisi açıklamalı cevap olur (sahte başarı, uydurma sayı yok); 400 isteği hatası yukarı çıkar."""
    import httpx
    from openai import APIConnectionError, BadRequestError, InternalServerError

    req = httpx.Request("POST", "http://mia.local/v1/chat/completions")

    class _Down:
        model = "down"

        def __init__(self, exc):
            self.exc = exc

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            raise self.exc

    for exc in (APIConnectionError(request=req),
                InternalServerError("bakımda", response=httpx.Response(503, request=req), body=None)):
        agent, tool = _agent(_Down(exc))
        ans = agent.ask("2025 konut kredisi ne kadar?")
        assert "ulaşılamıyor" in ans.text and "Sayı üretmedim" in ans.text
        assert ans.steps[-1].error_code == "LLM_UNAVAILABLE" and tool.calls == 0
        assert not any(ch.isdigit() for ch in ans.text.split("(")[0]), "kesinti cevabında sayı yok"

    agent, _ = _agent(_Down(BadRequestError("şema", response=httpx.Response(400, request=req), body=None)))
    with pytest.raises(BadRequestError):
        agent.ask("x")


def test_l10_kisa_belirsiz_soruda_llm_cagrilmadan_netlestirme_ve_yanitta_kapi_susar() -> None:
    from types import SimpleNamespace

    class _Search(Tool):
        name = "lakehouse_search"
        description = "arama"
        Params = _Params

        def __init__(self) -> None:
            names = ("Krediler (Toplam)", "Tüketici Kredileri, Toplam", "Konut Kredisi, ANKARA", "Kredi Kartları")
            self.lakehouse = SimpleNamespace(search_datasets=lambda q, limit=5: [SimpleNamespace(name=n) for n in names])

        def run(self, params):
            return ToolResult(content="-")

    llm = _ScriptedLLM([LLMResponse(content="Konut kredisi tablosu hazır.")])
    agent, _ = _agent(llm)
    agent.registry.register(_Search())
    ans = agent.ask("Kredi bakiyesini göster.")
    assert llm.seen_tool_offers == [], "LLM çağrılmadı"
    assert ans.text.rstrip().endswith("?") and "- Tüketici Kredileri" in ans.text and ans.steps[0].candidates
    agent.ask("Konut kredisi")            # bizim soruya kısa yanıt: kapı susar, model çalışır
    assert llm.seen_tool_offers, "bekleyen soruya yanıt modele gitti"


def test_grafik_istegi_tablo_varken_aracsiz_retle_bitmez() -> None:
    """M16 üçüncü koşu: 'karşılaştırmalı grafik' turunda model chart'ı hiç çağırmadan 'çizilemez' yazdı; bu turda veri
    üretilmediği için grafik zorunluluğu susuyordu. Tablo varken de bir kez geri gönderilir."""

    class _Chart(Tool):
        name = "chart"
        description = "grafik"
        Params = _Params

        def __init__(self) -> None:
            self.calls = 0

        def run(self, params):
            self.calls += 1
            return ToolResult(content="GRAFİK: çizildi")

    llm = _ScriptedLLM([
        LLMResponse(content="Seriler farklı birimde olduğu için grafik çizilemez."),
        LLMResponse(content="", tool_calls=[ToolCall(id="g1", name="chart", arguments={"year": 2025})]),
        LLMResponse(content="Grafik hazır."),
    ])
    agent, _ = _agent(llm)
    chart = _Chart()
    agent.registry.register(chart)
    agent.workspace.set_table(pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]}), description="önceki tur")
    ans = agent.ask("Bunu bana karşılaştırmalı grafik olarak göster.")
    assert chart.calls == 1 and ans.text == "Grafik hazır."
