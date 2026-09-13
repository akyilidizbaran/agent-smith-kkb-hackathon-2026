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
