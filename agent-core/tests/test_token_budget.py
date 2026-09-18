from __future__ import annotations

import pandas as pd
import pytest

from kkb_agent.core.agent import AnalyticsAgent
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


def test_agent_chat_faz_butcesini_ve_uzun_tablo_esigini_uygular() -> None:
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

    assert [call["max_tokens"] for call in llm.calls] == [1000, 3400]
    assert [item["phase"] for item in agent._usage["token_budget_calls"]] == ["planning", "narration"]
