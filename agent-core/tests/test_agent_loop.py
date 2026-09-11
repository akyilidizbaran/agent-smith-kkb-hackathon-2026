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
