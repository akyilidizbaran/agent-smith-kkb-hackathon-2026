"""Deterministic contract tests for selective multi-turn context reuse."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.agent import AnalyticsAgent
from kkb_agent.core.follow_up import FollowUpContext, _extract, resolve_follow_up
from kkb_agent.core.registry import ToolRegistry
from kkb_agent.core.tool import Tool, ToolResult
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.llm.base import LLMResponse, ToolCall
from kkb_agent.web_app import Session, answer_to_dict


class _QueryParams(BaseModel):
    year: int = 2025


class _QueryTool(Tool):
    name = "lakehouse_query"
    description = "test sorgusu"
    Params = _QueryParams

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.calls = 0
        self.fail_after = fail_after

    def run(self, params: _QueryParams) -> ToolResult:
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            return ToolResult.fail("TOOL_FAILED", "test aracı başarısız oldu", retryable=False)
        import pandas as pd

        return ToolResult(
            content=f"Sorgu başarılı: yil={params.year} deger=100",
            data=pd.DataFrame({"yil": [params.year], "deger": [100.0]}),
        )


class _ScriptedLLM:
    model = "scripted"

    def __init__(self, turns: list[LLMResponse]) -> None:
        self.turns = turns
        self.calls = 0
        self.messages: list[list] = []

    def supports_native_tools(self) -> bool:
        return True

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None) -> LLMResponse:
        self.messages.append(list(messages))
        turn = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        return turn


def _call(year: int, call_id: str) -> ToolCall:
    return ToolCall(id=call_id, name="lakehouse_query", arguments={"year": year})


def _catalog() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            dataset_id="bddk:konut",
            name="Konut kredileri",
            source="BDDK",
            source_detail=None,
            tags=[],
            columns=[SimpleNamespace(name="il", role="dimension", example_values=["Ankara", "İstanbul"], aliases=[])],
        ),
        SimpleNamespace(
            dataset_id="evds:usd_alis",
            name="USD alış kuru",
            source="EVDS",
            source_detail=None,
            tags=[],
            columns=[],
        ),
        SimpleNamespace(
            dataset_id="evds:usd_satis",
            name="USD satış kuru",
            source="EVDS",
            source_detail=None,
            tags=[],
            columns=[],
        ),
    ]


def test_same_metric_new_year_inherits_only_metric_and_overrides_year() -> None:
    first = resolve_follow_up("2025 yılında konut kredileri", catalog=_catalog())
    second = resolve_follow_up("2024te?", first.context, catalog=_catalog())

    assert second.is_follow_up
    assert second.context.series == "bddk:konut"
    assert second.context.date_range == "2024"
    assert "metric" in second.inherited
    assert "date_range" in second.overridden
    assert second.context.comparison_target == ("2025", "2024")


def test_geography_is_overridden_for_new_question() -> None:
    first = resolve_follow_up("Ankara için konut kredileri", catalog=_catalog())
    second = resolve_follow_up("İstanbul için göster", first.context, catalog=_catalog())

    assert second.context.geography == ("İstanbul",)
    assert second.context.entity == "İstanbul"
    assert "geography" in second.overridden


def test_comparison_follow_up_extends_geography_without_stale_single_filter() -> None:
    first = resolve_follow_up("Ankara için konut kredileri", catalog=_catalog())
    second = resolve_follow_up("İstanbul'la karşılaştır", first.context, catalog=_catalog())

    assert second.context.geography == ("Ankara", "İstanbul")
    assert second.context.comparison_target == ("İstanbul",)
    assert "geography" in second.extended


def test_frequency_change_is_an_override_not_a_resampling_implementation() -> None:
    first = resolve_follow_up("Konut kredilerini aylık göster", catalog=_catalog())
    second = resolve_follow_up("Çeyreklik yap", first.context, catalog=_catalog())

    assert second.context.frequency == "quarterly"
    assert "frequency" in second.overridden
    assert "Gold" in second.prompt()


def test_referential_monthly_word_is_not_a_series_selection() -> None:
    catalog = [
        SimpleNamespace(
            dataset_id="gold.net_kar_aylik",
            name="Bankacılık sektörü aylık net kârı",
            source="BDDK",
            source_detail=None,
            tags=["aylik"],
            columns=[],
        )
    ]
    previous = FollowUpContext(
        domain="finance",
        source="BDDK",
        metric="kredi",
        series="bddk_monthly:1536_Toplam",
        entity=None,
        date_range="2022-2023",
        frequency="monthly",
        aggregation=None,
    )

    result = resolve_follow_up(
        "Bu verilerin bir önceki aya göre aylık değişimlerini göster.", previous, catalog
    )

    assert result.explicit.series is None
    assert result.context.series == previous.series
    assert "series" not in result.overridden


def test_buying_series_is_replaced_by_selling_series() -> None:
    first = resolve_follow_up("USD alış kurunu getir", catalog=_catalog())
    second = resolve_follow_up("Peki satış?", first.context, catalog=_catalog())

    assert first.context.series == "evds:usd_alis"
    assert second.context.series == "evds:usd_satis"
    assert "series" in second.overridden


def test_comparison_follow_up_keeps_both_year_targets() -> None:
    first = resolve_follow_up("2025 konut kredileri", catalog=_catalog())
    second = resolve_follow_up("2024'te?", first.context, catalog=_catalog())
    third = resolve_follow_up("İkisini karşılaştır", second.context, catalog=_catalog())

    assert third.context.comparison_target == ("2025", "2024")
    assert "comparison_target" in third.inherited


def test_unresolvable_reference_requires_clarification() -> None:
    result = resolve_follow_up("Onu diğerine göre karşılaştır.")

    assert result.clarification_required
    assert "reference" in result.ambiguous or "comparison_target" in result.ambiguous


def test_domain_switch_clears_finance_specific_context() -> None:
    first = resolve_follow_up("2025 Ankara konut kredilerini aylık göster", catalog=_catalog())
    second = resolve_follow_up("Şimdi aynı analizi sağlık verisinde yap", first.context, catalog=_catalog())

    assert second.context.domain == "health"
    assert second.context.metric is None
    assert second.context.series is None
    assert second.context.geography == ()
    assert "series" in second.cleared
    assert second.context.date_range == "2025"


def test_standalone_new_scope_does_not_inherit_old_context() -> None:
    first = resolve_follow_up("2025 Ankara konut kredileri", catalog=_catalog())
    second = resolve_follow_up("2026 USD satış kuru", first.context, catalog=_catalog())

    assert not second.is_follow_up
    assert second.context.series == "evds:usd_satis"
    assert second.context.geography == ()
    assert "geography" in second.cleared


def test_frequency_without_a_series_fails_closed() -> None:
    result = resolve_follow_up("Haftalık yap")

    assert result.clarification_required
    assert "series" in result.ambiguous


def test_time_aliases_do_not_bind_follow_up_to_first_catalog_series() -> None:
    catalog = [
        SimpleNamespace(
            dataset_id="bddk_finturk:ADANA_BireyselKrediKartlari",
            name="Bireysel kredi kartları, ADANA",
            source="bddk_finturk",
            tags=["aylık"],
            columns=[
                SimpleNamespace(name="observation_date", role="time", example_values=[],
                                 aliases=["dönem", "tarih", "ay"]),
                SimpleNamespace(name="value", role="measure", example_values=[], aliases=["bireysel kredi kartları"]),
            ],
        ),
    ]
    question = (
        "Aktif tabloyu aylık değişim analizine hazırlayıp tüm serileri "
        "202001–202112 döneminde ortak ay eksenine hizala."
    )
    explicit = _extract(question, catalog)
    assert explicit.series is None
    assert explicit.aggregation is None

    previous = FollowUpContext(
        domain="finance", metric="kredi", series="bddk_monthly:1536_Toplam",
        date_range="2022-2023", frequency="monthly",
    )
    resolved = resolve_follow_up(question, previous, catalog=catalog)
    assert resolved.is_follow_up
    assert resolved.context.series == previous.series
    assert resolved.context.date_range == "2020-01–2021-12"
    assert "date_range" in resolved.overridden
    assert "series" not in resolved.overridden


def _agent(llm: _ScriptedLLM, *, fail_after: int | None = None) -> tuple[AnalyticsAgent, _QueryTool]:
    tool = _QueryTool(fail_after=fail_after)
    registry = ToolRegistry()
    registry.register(tool)
    return AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace()), tool


def test_tool_failure_does_not_commit_failed_follow_up_or_fabricate_fresh_state() -> None:
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call(2025, "a1")]),
        LLMResponse(content="2025 verisi 100."),
        LLMResponse(content="", tool_calls=[_call(2024, "b1")]),
        LLMResponse(content="Bu veri alınamadı."),
    ])
    agent, tool = _agent(llm, fail_after=1)

    agent.ask("2025 konut kredisi")
    answer = agent.ask("2024'te?")

    assert tool.calls == 2
    assert agent.follow_up_context.date_range == "2025"
    assert agent.follow_up_resolution is not None
    assert not agent.follow_up_resolution.committed
    assert any(a.get("kind") == "follow_up_resolution" for a in answer.artifacts)
    assert answer.error_codes().get("TOOL_FAILED")


def test_separate_sessions_do_not_share_follow_up_context() -> None:
    def factory() -> AnalyticsAgent:
        llm = _ScriptedLLM([
            LLMResponse(content="", tool_calls=[_call(2025, "a1")]),
            LLMResponse(content="Veri 100."),
        ])
        return _agent(llm)[0]

    session_a = Session(factory)
    session_b = Session(factory)
    session_a.ask("2025 konut kredisi")
    session_b.ask("2024 USD satış kuru")

    assert session_a.agent.follow_up_context.metric == "konut kredisi"
    assert session_b.agent.follow_up_context.metric == "usd"
    assert session_b.agent.follow_up_context.metric != session_a.agent.follow_up_context.metric


def test_api_payload_exposes_follow_up_resolution_without_exposing_raw_history() -> None:
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call(2025, "a1")]),
        LLMResponse(content="2025 verisi 100."),
        LLMResponse(content="", tool_calls=[_call(2024, "b1")]),
        LLMResponse(content="2024 verisi 100."),
    ])
    agent, _ = _agent(llm)
    agent.ask("2025 konut kredisi")
    answer = agent.ask("2024'te?")
    payload = answer_to_dict(answer, agent)

    assert payload["follow_up"]["overridden"] == ["date_range"]
    assert "2025 konut kredisi" not in payload["follow_up"]
