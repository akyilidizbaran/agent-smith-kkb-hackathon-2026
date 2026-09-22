from __future__ import annotations

import pandas as pd
import pytest

from kkb_agent.core.agent import (
    COMPACT_PLANNING_PROMPT,
    NARRATION_PROMPT,
    SYSTEM_PROMPT,
    AnalyticsAgent,
)
from kkb_agent.core.registry import ToolRegistry
from kkb_agent.core.token_budget import TokenBudgetPolicy
from kkb_agent.llm.base import LLMResponse


def test_phase_butcesi_katalog_turunu_kucultur_uzun_tabloyu_korur() -> None:
    policy = TokenBudgetPolicy(global_max=4000)

    assert policy.for_phase("planning") == 1000
    assert policy.for_phase("tool") == 1800
    assert policy.for_phase("narration", rows=24, columns=3) == 2800
    assert policy.for_phase("narration", rows=60, columns=3) == 3400
    assert policy.for_phase("narration", rows=24, columns=7) == 3400
    assert policy.for_phase("narration", rows=60, columns=7, extended_narration=False) == 2800
    assert policy.for_phase("narration", rows=1, columns=2, extended_narration=True) == 3400
    assert policy.for_phase("recovery") == 1400


def test_global_tavan_faz_butcelerini_keser() -> None:
    policy = TokenBudgetPolicy(global_max=1500)

    assert policy.for_phase("planning") == 1000
    assert policy.for_phase("tool") == 1500
    assert policy.for_phase("narration", rows=60, columns=7) == 1500


def test_gecersiz_faz_ve_butce_reddedilir() -> None:
    with pytest.raises(ValueError):
        TokenBudgetPolicy(planning=0)
    with pytest.raises(ValueError):
        TokenBudgetPolicy(global_max=0)
    with pytest.raises(ValueError):
        TokenBudgetPolicy().for_phase("unknown")


def test_agent_chat_buyuk_artifact_yuzunden_anlatim_butcesini_arttirmez() -> None:
    class FakeLLM:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            self.calls.append({"max_tokens": max_tokens, "temperature": temperature})
            return LLMResponse(content="hazır")

    llm = FakeLLM()
    agent = AnalyticsAgent(
        llm,
        ToolRegistry(),
        token_budget_policy=TokenBudgetPolicy(global_max=4000),
    )
    agent._usage = {"token_budget_calls": []}
    agent._chat([], phase="planning")
    agent.workspace.set_table(pd.DataFrame({"ay": range(60), "deger": range(60)}), description="test")
    agent._chat([], phase="narration")

    assert [call["max_tokens"] for call in llm.calls] == [1000, 2800]
    assert [item["phase"] for item in agent._usage["token_budget_calls"]] == ["planning", "narration"]
    assert agent._usage["llm_calls"][-1]["extended_narration"] is False


def test_agent_chat_analiz_isteginde_genis_anlatim_butcesi_secer() -> None:
    class FakeLLM:
        model = "fake"

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            self.max_tokens = max_tokens
            return LLMResponse(content="hazır")

    llm = FakeLLM()
    agent = AnalyticsAgent(llm, ToolRegistry(), token_budget_policy=TokenBudgetPolicy(global_max=4000))
    agent._usage = {"token_budget_calls": [], "llm_calls": [], "llm_phase_ms": {}}
    agent.registry.active_question = "Explain the relationship between the two series."
    agent._chat([], phase="narration")

    assert llm.max_tokens == 3400
    assert agent._usage["llm_calls"][-1]["extended_narration"] is True


def test_narration_prompt_kisadir_ve_calisma_zarfi_baglamini_korur() -> None:
    class FakeLLM:
        model = "fake"

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            return LLMResponse(content="hazır")

    agent = AnalyticsAgent(FakeLLM(), ToolRegistry())
    runtime_context = "\n\nAKTİF TABLO: dönem=2025-01, deger=100"
    full_operational = agent._system_prompt + runtime_context
    full_narration = agent._narration_system_content(full_operational, compact_planning=False)
    compact_operational = agent.profile.render(COMPACT_PLANNING_PROMPT) + runtime_context
    compact_narration = agent._narration_system_content(compact_operational, compact_planning=True)

    assert len(NARRATION_PROMPT) < len(SYSTEM_PROMPT) * 0.5
    assert full_narration.startswith(agent.profile.render(NARRATION_PROMPT))
    assert compact_narration.startswith(agent.profile.render(NARRATION_PROMPT))
    assert full_narration.endswith(runtime_context)
    assert compact_narration.endswith(runtime_context)


def test_genel_system_prompt_sikistirilirken_kritik_kurallar_korunur() -> None:
    assert len(SYSTEM_PROMPT) < 3500
    for invariant in (
        "lakehouse_search",
        "lakehouse_describe",
        "lakehouse_distinct_values",
        "workspace_compute_column",
        "kaynağını (kurum/tablo)",
        "Nedenselliği kanıt olmadan ileri sürme.",
        "veri mimarisi katman adları (Gold, Silver, Bronze, RAW, lakehouse) YAZMA",
    ):
        assert invariant in SYSTEM_PROMPT


def test_agent_streaming_yalniz_toolsuz_narration_cagrisinda_kullanilir() -> None:
    class FakeLLM:
        model = "fake"

        def __init__(self) -> None:
            self.stream_calls = 0
            self.normal_calls = 0

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            self.normal_calls += 1
            return LLMResponse(content="normal")

        def chat_stream(self, messages, *, temperature=0.0, max_tokens=None):
            self.stream_calls += 1
            return LLMResponse(content="akış", usage={"first_token_ms": 12.5, "streaming": True})

    llm = FakeLLM()
    agent = AnalyticsAgent(llm, ToolRegistry(), stream_narration=True)
    agent._usage = {"token_budget_calls": [], "llm_calls": [], "llm_phase_ms": {}}
    response = agent._chat([], tools=None, phase="narration")

    assert response.content == "akış"
    assert llm.stream_calls == 1 and llm.normal_calls == 0
    assert agent._usage["llm_calls"][-1]["streaming"] is True
    assert agent._usage["llm_calls"][-1]["first_token_ms"] == 12.5


def test_narration_prompt_ozel_system_promptu_silmez() -> None:
    class FakeLLM:
        model = "fake"

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            return LLMResponse(content="hazır")

    agent = AnalyticsAgent(FakeLLM(), ToolRegistry(), system_prompt="Özel işletme talimatı")
    system = "Özel işletme talimatı\n\nçalışma durumu"
    narrated = agent._narration_system_content(system, compact_planning=False)

    assert narrated.startswith(system)
    assert "YANIT AŞAMASI" in narrated
