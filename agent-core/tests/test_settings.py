from kkb_agent.config import load_settings
from kkb_agent.core.agent import AnalyticsAgent
from kkb_agent.core.registry import ToolRegistry


def test_narration_timeout_defaults_to_100_seconds(monkeypatch) -> None:
    monkeypatch.delenv("LLM_NARRATION_TIMEOUT_S", raising=False)
    monkeypatch.delenv("LLM_TIMEOUT", raising=False)

    settings = load_settings()
    assert settings.llm_narration_timeout_s == 100
    assert settings.llm_timeout == 100


def test_narration_timeout_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("LLM_NARRATION_TIMEOUT_S", "42.5")
    monkeypatch.setenv("LLM_TIMEOUT", "70")

    settings = load_settings()
    assert settings.llm_narration_timeout_s == 42.5
    assert settings.llm_timeout == 70


def test_agent_direct_default_allows_100_second_narration() -> None:
    agent = AnalyticsAgent(llm=object(), registry=ToolRegistry())

    assert agent.narration_timeout_s == 100
