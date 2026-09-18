"""Focused regression tests for bounded tool recovery and turn isolation."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.agent import AnalyticsAgent
from kkb_agent.core.errors import ToolError
from kkb_agent.core.execution_recovery import (
    ExecutionState,
    absence_verified,
    classify_error,
)
from kkb_agent.core.registry import ToolRegistry
from kkb_agent.core.tool import Tool, ToolResult
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.llm.base import LLMResponse, ToolCall
from kkb_agent.tools.lakehouse import LakehouseSearchTool
from kkb_agent.web_app import Session, answer_to_dict


class _Params(BaseModel):
    route: str = "default"


class _ScriptedLLM:
    model = "scripted"

    def __init__(self, turns: list[LLMResponse]) -> None:
        self.turns = turns
        self.calls = 0
        self.messages: list[list] = []
        self.tool_offers: list[bool] = []

    def supports_native_tools(self) -> bool:
        return True

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None) -> LLMResponse:
        self.messages.append(list(messages))
        self.tool_offers.append(tools is not None)
        response = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        return response


def _call(name: str, route: str, call_id: str) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={"route": route})


class _QueueTool(Tool):
    description = "deterministic recovery test tool"
    Params = _Params

    def __init__(self, name: str, results: list[ToolResult]) -> None:
        self.name = name
        self.results = list(results)
        self.calls: list[str] = []

    def run(self, params: _Params) -> ToolResult:
        self.calls.append(params.route)
        return self.results.pop(0) if self.results else ToolResult(content="no result")


def _data(text: str = "Sorgu başarılı: 2023 değer=100") -> ToolResult:
    return ToolResult(content=text, data=pd.DataFrame({"dönem": ["2023"], "değer": [100.0]}))


def _agent(llm: _ScriptedLLM, *tools: Tool, max_steps: int = 10) -> AnalyticsAgent:
    registry = ToolRegistry()
    registry.register_all(list(tools))
    return AnalyticsAgent(
        llm=llm,
        registry=registry,
        workspace=AnalysisWorkspace(),
        max_steps=max_steps,
        tool_gate=False,
    )


def _failed_turn(llm: _ScriptedLLM, tool: Tool) -> tuple[AnalyticsAgent, object]:
    agent = _agent(llm, tool)
    answer = agent.ask("2023 tarihsel seri verilerini getir")
    return agent, answer


def test_sql_failed_never_becomes_confirmed_absent() -> None:
    tool = _QueueTool("lakehouse_query", [ToolResult.fail("SQL_FAILED", "query failed")])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "bad", "q1")]),
        LLMResponse(content="Bu veri bulunmuyor."),
        LLMResponse(content="Bu veri bulunmuyor."),
    ])

    _agent_instance, answer = _failed_turn(llm, tool)

    assert answer.availability_status == "RETRIEVAL_FAILED"
    assert answer.availability_status != "CONFIRMED_ABSENT"
    assert "doğrulayamadım" in answer.text
    assert answer.error_codes() == {"SQL_FAILED": 1}


def test_invalid_args_can_replan_to_a_valid_path() -> None:
    tool = _QueueTool("lakehouse_query", [ToolResult.fail("INVALID_ARGS", "bad args"), _data()])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "bad", "q1")]),
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "repaired", "q2")]),
        LLMResponse(content="2023 değer 100."),
    ])

    answer = _agent(llm, tool).ask("2023 verilerini getir")

    assert answer.availability_status == "FOUND"
    assert tool.calls == ["bad", "repaired"]
    assert answer.error_codes()["INVALID_ARGS"] == 1


def test_gold_required_is_recoverable_semantic_guard() -> None:
    query = _QueueTool("lakehouse_query", [ToolResult.fail("GOLD_REQUIRED", "gold required")])
    gold = _QueueTool("gold_align", [_data("Gold sonucu: 2023 değer=100")])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "aggregate", "q1")]),
        LLMResponse(content="", tool_calls=[_call("gold_align", "monthly", "g1")]),
        LLMResponse(content="2023 değer 100."),
    ])

    answer = _agent(llm, query, gold).ask("2023 aylık değeri getir")

    assert answer.availability_status == "FOUND"
    assert "GOLD_REQUIRED" in answer.error_codes()
    assert gold.calls == ["monthly"]


def test_dataset_not_found_gets_bounded_discovery_before_absence() -> None:
    query = _QueueTool("lakehouse_query", [ToolResult.fail("DATASET_NOT_FOUND", "wrong id"), _data()])
    search = _QueueTool("lakehouse_search", [ToolResult(content="Bulunan seri: CPI")])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "wrong", "q1")]),
        LLMResponse(content="", tool_calls=[_call("lakehouse_search", "cpi", "s1")]),
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "correct", "q2")]),
        LLMResponse(content="2023 değer 100."),
    ])

    answer = _agent(llm, query, search).ask("2023 TÜFE verilerini getir")

    assert answer.availability_status == "FOUND"
    assert search.calls == ["cpi"]
    assert answer.error_codes()["DATASET_NOT_FOUND"] == 1


def test_authoritative_empty_search_can_confirm_absence() -> None:
    search = _QueueTool(
        "lakehouse_search",
        [ToolResult.fail("DATASET_NOT_FOUND", "no matching catalog series", layer="reference")],
    )
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_search", "unknown", "s1")]),
        LLMResponse(content="Bu veri bulunmuyor."),
    ])

    answer = _agent(llm, search).ask("2023 tarihsel seri verilerini getir")

    assert answer.availability_status == "CONFIRMED_ABSENT"
    assert "bulunmuyor" in answer.text.lower()
    assert absence_verified("lakehouse_search", ToolError("DATASET_NOT_FOUND", "x", layer="reference"))


def test_transient_failure_retries_once_within_same_turn() -> None:
    tool = _QueueTool(
        "lakehouse_query",
        [ToolResult.fail("TOOL_FAILED", "temporary timeout", retryable=True), _data()],
    )
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "first", "q1")]),
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "second", "q2")]),
        LLMResponse(content="2023 değer 100."),
    ])

    answer = _agent(llm, tool).ask("2023 verilerini getir")

    assert answer.availability_status == "FOUND"
    assert tool.calls == ["first", "second"]
    assert any(a["kind"] == "execution_recovery" for a in answer.artifacts)


def test_identical_failed_call_is_not_repeated_indefinitely() -> None:
    tool = _QueueTool("lakehouse_query", [ToolResult.fail("SQL_FAILED", "bad SQL")])
    same = [_call("lakehouse_query", "same", f"q{i}") for i in range(8)]
    llm = _ScriptedLLM([LLMResponse(content="", tool_calls=[call]) for call in same])

    answer = _agent(llm, tool, max_steps=8).ask("2023 verilerini getir")

    assert tool.calls == ["same"]
    assert answer.error_codes().get("DUPLICATE_CALL", 0) >= 1
    assert llm.calls < 8


def test_recovery_budget_terminates_cleanly() -> None:
    tool = _QueueTool(
        "lakehouse_query",
        [ToolResult.fail("SQL_FAILED", "bad SQL") for _ in range(4)],
    )
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", f"bad{i}", f"q{i}")])
        for i in range(3)
    ] + [LLMResponse(content="Bu turda doğrulanamadı.")])

    answer = _agent(llm, tool, max_steps=8).ask("2023 verilerini getir")
    recovery = next(a for a in answer.artifacts if a["kind"] == "execution_recovery")

    assert len(tool.calls) == ExecutionState.MAX_RECOVERY_ATTEMPTS
    assert recovery["recovery_attempt"] == ExecutionState.MAX_RECOVERY_ATTEMPTS
    assert answer.availability_status == "RETRIEVAL_FAILED"
    assert "doğrulanamadı" in answer.text


def test_same_turn_alternate_path_succeeds_after_first_failure() -> None:
    query = _QueueTool("lakehouse_query", [ToolResult.fail("SQL_FAILED", "schema mismatch")])
    search = _QueueTool("lakehouse_search", [ToolResult(content="Bulunan seri: CPI")])
    gold = _QueueTool("gold_align", [_data()])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "wrong", "q1")]),
        LLMResponse(content="", tool_calls=[_call("lakehouse_search", "cpi", "s1")]),
        LLMResponse(content="", tool_calls=[_call("gold_align", "monthly", "g1")]),
        LLMResponse(content="2023 değer 100."),
    ])

    answer = _agent(llm, query, search, gold).ask("2023 verilerini getir")

    assert answer.availability_status == "FOUND"
    assert [s.error_code for s in answer.steps if s.error_code] == ["SQL_FAILED"]
    assert [s.tool_name for s in answer.steps if s.ok and s.tool_name] == ["lakehouse_search", "gold_align"]


def test_failed_turn_then_greeting_does_not_resume_old_task() -> None:
    tool = _QueueTool("lakehouse_query", [ToolResult.fail("SQL_FAILED", "failure"), _data()])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "old", "q1")]),
        LLMResponse(content="Bu turda doğrulanamadı."),
        LLMResponse(content="Bu turda doğrulanamadı."),
    ])
    agent, first = _failed_turn(llm, tool)
    calls_after_failure = list(tool.calls)

    greeting = agent.ask("selam")

    assert tool.calls == calls_after_failure
    assert llm.calls == 3
    assert "Selam" in greeting.text
    assert first.availability_status == "RETRIEVAL_FAILED"


def test_explicit_retry_restores_semantics_but_uses_fresh_path() -> None:
    query = _QueueTool("lakehouse_query", [ToolResult.fail("SQL_FAILED", "failure")])
    search = _QueueTool("lakehouse_search", [ToolResult(content="Bulunan seri: CPI")])
    fresh = _QueueTool("gold_align", [_data()])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "old", "q1")]),
        LLMResponse(content="Bu turda doğrulanamadı."),
        LLMResponse(content="Bu turda doğrulanamadı."),
        LLMResponse(content="", tool_calls=[_call("lakehouse_search", "fresh", "s1")]),
        LLMResponse(content="", tool_calls=[_call("gold_align", "fresh", "g1")]),
        LLMResponse(content="2023 değer 100."),
    ])
    agent = _agent(llm, query, search, fresh)
    failed = agent.ask("2023 tarihsel seri verilerini getir")
    agent.ask("selam")
    retried = agent.ask("tekrar dene")

    assert failed.availability_status == "RETRIEVAL_FAILED"
    assert query.calls == ["old"]
    assert search.calls == ["fresh"]
    assert retried.availability_status == "FOUND"
    assert any(a.get("resumed_previous_task") for a in retried.artifacts if a.get("kind") == "execution_recovery")


def test_failed_attempt_does_not_commit_false_availability_context() -> None:
    tool = _QueueTool("lakehouse_query", [ToolResult.fail("DATASET_NOT_FOUND", "wrong reference")])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "wrong", "q1")]),
        LLMResponse(content="Bu veri bulunmuyor."),
        LLMResponse(content="Bu veri bulunmuyor."),
    ])
    agent = _agent(llm, tool)
    answer = agent.ask("2023 TÜFE verilerini getir")

    assert answer.availability_status == "RETRIEVAL_FAILED"
    assert agent.follow_up_context.series is None
    assert agent.follow_up_context.metric is None


def test_previous_valid_follow_up_context_survives_failed_recovery() -> None:
    tool = _QueueTool("lakehouse_query", [_data("2025 değer=100"), ToolResult.fail("SQL_FAILED", "failure")])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "2025", "q1")]),
        LLMResponse(content="2025 değer 100."),
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "2024", "q2")]),
        LLMResponse(content="Bu turda doğrulanamadı."),
        LLMResponse(content="Bu turda doğrulanamadı."),
    ])
    agent = _agent(llm, tool)
    agent.ask("2025 konut kredisi")
    failed = agent.ask("2024'te?")

    assert failed.availability_status == "RETRIEVAL_FAILED"
    assert agent.follow_up_context.date_range == "2025"
    assert agent.follow_up_resolution is not None
    assert not agent.follow_up_resolution.committed


def test_sessions_keep_recovery_state_isolated() -> None:
    tools: list[_QueueTool] = []

    def factory() -> AnalyticsAgent:
        tool = _QueueTool("lakehouse_query", [ToolResult.fail("SQL_FAILED", "failure")])
        tools.append(tool)
        llm = _ScriptedLLM([
            LLMResponse(content="", tool_calls=[_call("lakehouse_query", "old", "q1")]),
            LLMResponse(content="Bu turda doğrulanamadı."),
            LLMResponse(content="Bu turda doğrulanamadı."),
        ])
        return _agent(llm, tool)

    a = Session(factory)
    b = Session(factory)
    a.ask("2023 TÜFE verilerini getir")
    b.ask("2024 konut kredisi")

    assert a.agent._last_recovery is not None
    assert b.agent._last_recovery is not None
    assert a.agent._last_recovery.question != b.agent._last_recovery.question


def test_recovery_metadata_is_exposed_without_raw_tool_arguments() -> None:
    tool = _QueueTool("lakehouse_query", [ToolResult.fail("SQL_FAILED", "failure")])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "old", "q1")]),
        LLMResponse(content="Bu turda doğrulanamadı."),
        LLMResponse(content="Bu turda doğrulanamadı."),
    ])
    agent = _agent(llm, tool)
    answer = agent.ask("2023 TÜFE verilerini getir")
    payload = answer_to_dict(answer, agent)

    assert payload["availability_status"] == "RETRIEVAL_FAILED"
    assert payload["execution_recovery"]["tool_error_code"] == "SQL_FAILED"
    assert "old" not in str(payload["execution_recovery"])


@pytest.mark.parametrize(
    ("code", "failure_class"),
    [
        ("SQL_FAILED", "query_execution"),
        ("INVALID_ARGS", "invalid_arguments"),
        ("GOLD_REQUIRED", "semantic_guard"),
        ("PERIOD_GRAIN_MISMATCH", "semantic_guard"),
        ("JOIN_MISMATCH", "join_alignment"),
        ("DATASET_NOT_FOUND", "reference_resolution"),
        ("TOOL_FAILED", "transient_provider"),
    ],
)
def test_observed_error_codes_have_stable_recovery_classes(code: str, failure_class: str) -> None:
    assert classify_error(ToolError(code, "x", retryable=True)) == failure_class


def test_lakehouse_search_streak_is_turn_scoped() -> None:
    class Lake:
        def search_datasets(self, query, limit=5):
            return []

        def search_uningested(self, query, limit=5):
            return []

    tool = LakehouseSearchTool(Lake())
    first = tool.validate_and_run({"query": "one"})
    tool.begin_turn(2)
    second = tool.validate_and_run({"query": "two"})

    assert first.ok and second.ok
    assert tool._empty_streak == 1
