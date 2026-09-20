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
        self.tool_names: list[set[str]] = []

    def supports_native_tools(self) -> bool:
        return True

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None) -> LLMResponse:
        self.messages.append(list(messages))
        self.tool_offers.append(tools is not None)
        self.tool_names.append({item["function"]["name"] for item in (tools or [])})
        response = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        return response


class _FailingScriptedLLM(_ScriptedLLM):
    def __init__(self, turns: list[LLMResponse], *, fail_on_call: int, error: Exception) -> None:
        super().__init__(turns)
        self.fail_on_call = fail_on_call
        self.error = error

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None) -> LLMResponse:
        if self.calls == self.fail_on_call:
            self.messages.append(list(messages))
            self.tool_offers.append(tools is not None)
            self.tool_names.append({item["function"]["name"] for item in (tools or [])})
            self.calls += 1
            raise self.error
        return super().chat(messages, tools=tools, temperature=temperature, max_tokens=max_tokens)


def _call(name: str, route: str, call_id: str) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={"route": route})


class _QueueTool(Tool):
    description = "deterministic recovery test tool"
    Params = _Params

    def __init__(self, name: str, results: list[ToolResult], workspace: AnalysisWorkspace | None = None) -> None:
        self.name = name
        self.results = list(results)
        self.calls: list[str] = []
        self.workspace = workspace

    def run(self, params: _Params) -> ToolResult:
        self.calls.append(params.route)
        result = self.results.pop(0) if self.results else ToolResult(content="no result")
        if self.workspace is not None and result.ok and isinstance(result.data, pd.DataFrame):
            self.workspace.set_table(result.data, description="verified test table")
        return result


def _data(text: str = "Sorgu başarılı: 2023 değer=100") -> ToolResult:
    return ToolResult(content=text, data=pd.DataFrame({"dönem": ["2023"], "değer": [100.0]}))


def _agent(
    llm: _ScriptedLLM,
    *tools: Tool,
    max_steps: int = 10,
    workspace: AnalysisWorkspace | None = None,
) -> AnalyticsAgent:
    registry = ToolRegistry()
    registry.register_all(list(tools))
    return AnalyticsAgent(
        llm=llm,
        registry=registry,
        workspace=workspace or AnalysisWorkspace(),
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


def test_content_too_large_stops_same_fetch_retries_and_uses_single_recovery_turn() -> None:
    web = _QueueTool(
        "web_url",
        [ToolResult.fail(
            "CONTENT_TOO_LARGE",
            "Kaynağa ulaşıldı ancak indirme boyutu sınırı aşıldı.",
            hint="Daha daraltılmış dışa aktarım kullan.",
            layer="data",
            retryable=False,
        )],
    )
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("web_url", "large-file", "w1")]),
        LLMResponse(content="Kaynağa ulaştım ancak indirme sınırı nedeniyle içeriği doğrulayamadım."),
    ])

    answer = _agent(llm, web).ask("Bu adresteki dosyayı analiz et")

    assert web.calls == ["large-file"]
    assert answer.error_codes() == {"CONTENT_TOO_LARGE": 1}
    assert "doğrulayamadım" in answer.text


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


def test_terminal_duplicate_loop_skips_unrecoverable_narration_call() -> None:
    search = _QueueTool("lakehouse_search", [ToolResult(content="Aday seri: demo")])
    same_search = _call("lakehouse_search", "toplam kredi", "s1")
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[same_search]),
        LLMResponse(content="", tool_calls=[same_search]),
        LLMResponse(content="", tool_calls=[same_search]),
        # A fourth response would be the redundant terminal narration call.
        LLMResponse(content="Yanıt üretildi."),
    ])

    answer = _agent(llm, search).ask("Katalogda toplam kredi serilerini bul")

    assert llm.calls == 3
    assert search.calls == ["toplam kredi"]
    assert answer.availability_status == "RETRIEVAL_FAILED"
    assert answer.usage["deterministic_recovery_shortcuts"] == 1
    assert "bulunmadığını göstermez" in answer.text
    assert "sayı sunmadım" in answer.text
    assert answer.error_codes()["DUPLICATE_CALL"] >= 1


def test_catalog_search_budget_returns_truthful_status_without_extra_model_call() -> None:
    search = _QueueTool(
        "lakehouse_search",
        [ToolResult(content="Aday seri: toplam kredi aylık")],
    )
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_search", "toplam kredi", "s1")]),
        LLMResponse(content="", tool_calls=[_call("lakehouse_search", "ulusal aylık kredi", "s2")]),
        # A third response would be the redundant terminal narration call.
        LLMResponse(content="Yanıt üretildi."),
    ])
    registry = ToolRegistry()
    registry.register_all([search])
    agent = AnalyticsAgent(
        llm=llm,
        registry=registry,
        workspace=AnalysisWorkspace(),
        tool_gate=False,
        max_catalog_search_calls=1,
    )

    answer = agent.ask("Katalogda ulusal aylık toplam kredi serisini seç")

    assert llm.calls == 2
    assert search.calls == ["toplam kredi"]
    assert answer.availability_status == "RETRIEVAL_FAILED"
    assert answer.usage["deterministic_recovery_shortcuts"] == 1
    assert "arama sınırına ulaşıldığı" in answer.text
    assert "verinin havuzda bulunmadığı anlamına gelmez" in answer.text
    assert answer.error_codes()["CATALOG_SEARCH_BUDGET"] >= 1


def test_blank_final_response_gets_nonempty_deterministic_status() -> None:
    llm = _ScriptedLLM([LLMResponse(content="")])

    answer = _agent(llm).ask("Sen kimsin?")

    assert llm.calls == 1
    assert answer.text.strip()
    assert "metin üretmedi" in answer.text
    assert "verinin bulunmadığını kanıtlamaz" in answer.text
    assert answer.usage["empty_final_response_fallbacks"] == 1


def test_blank_final_response_preserves_verified_table() -> None:
    workspace = AnalysisWorkspace()
    query = _QueueTool("lakehouse_query", [_data()], workspace=workspace)
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "2023", "q1")]),
        LLMResponse(content=""),
    ])

    answer = _agent(llm, query, workspace=workspace).ask("2023 değerlerinin genel yönünü değerlendir")

    assert llm.calls == 2
    assert answer.workspace.table is not None
    assert not answer.workspace.table.empty
    assert "Doğrulanmış sonuç tablosu ve indirmeler hazır" in answer.text
    assert answer.usage["empty_final_response_fallbacks"] == 1


def test_confirmed_public_absence_opens_web_gate_dynamically_once(monkeypatch) -> None:
    query = _QueueTool(
        "lakehouse_query",
        [ToolResult.fail("OUT_OF_COVERAGE", "requested period has no observations", layer="data")],
    )
    search = _QueueTool("web_search", [ToolResult(content="official page candidate")])
    url = _QueueTool("web_url", [ToolResult(content="page read")])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "missing", "q1")]),
        LLMResponse(content="", tool_calls=[_call("web_search", "official", "w1")]),
        LLMResponse(content="Yerel havuzda dönem yok; resmi sayfa adayı bulundu."),
    ])
    registry = ToolRegistry()
    registry.register_all([query, search, url])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), tool_gate=True, max_steps=5)
    plan = {"query": "BDDK aylık kredi 2024", "include_domains": ["bddk.gov.tr"], "topic": "finance"}
    monkeypatch.setattr(
        agent,
        "_verified_public_fallback_plan",
        lambda _question, call, _result: plan if call.name == "lakehouse_query" else None,
    )

    answer = agent.ask("2024 BDDK kredi verilerini getir")

    assert "web_search" not in llm.tool_names[0]
    assert "web_search" in llm.tool_names[1] and "web_url" in llm.tool_names[1]
    assert search.calls == ["official"]
    assert registry.public_web_fallback_plan == plan
    assert answer.usage["verified_public_fallbacks"] == 1
    assert any("yerel veri havuzunda" in (m.content or "").lower() for m in llm.messages[1])


def test_search_snippet_number_never_becomes_answer_when_source_was_not_opened() -> None:
    search = _QueueTool("web_search", [ToolResult(
        content="BAĞLAM ALINTISI (veri kanıtı değildir): 2025 oranı %31.07",
        artifacts={"web_search": {"results": [{"url": "https://stats.example/data", "title": "Oran"}],
                                  "hits": ["https://stats.example/data"], "contains_unverified_snippets": True}},
    )])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("web_search", "official", "s1")]),
        LLMResponse(content="2025 oranı %31.07 olarak gerçekleşti."),
    ])

    answer = _agent(llm, search).ask("2025 oranını internetten bul")

    assert "31.07" not in answer.text
    assert "doğrulanmadı" in answer.text
    assert answer.grounding == "NOT_VERIFIED"
    assert any(item["kind"] == "web_search" for item in answer.artifacts)


def test_sql_failure_does_not_open_public_web_fallback(monkeypatch) -> None:
    query = _QueueTool("lakehouse_query", [ToolResult.fail("SQL_FAILED", "syntax error")])
    search = _QueueTool("web_search", [ToolResult(content="must not run")])
    url = _QueueTool("web_url", [ToolResult(content="must not run")])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call("lakehouse_query", "bad", "q1")]),
        LLMResponse(content="Sorgu başarısız oldu."),
    ])
    registry = ToolRegistry()
    registry.register_all([query, search, url])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), tool_gate=True, max_steps=4)
    monkeypatch.setattr(
        agent,
        "_verified_public_fallback_plan",
        lambda *_: pytest.fail("SQL_FAILED fallback plan üretmemeli"),
    )

    answer = agent.ask("2024 kredi verilerini getir")

    assert all("web_search" not in names for names in llm.tool_names)
    assert answer.availability_status == "RETRIEVAL_FAILED"


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


def test_catalog_search_budget_bounds_discovery_without_extra_recovery_call() -> None:
    search = _QueueTool(
        "lakehouse_search",
        [ToolResult(content="Bulunan tablolar: " + ("katalog adayı; " * 250)) for _ in range(3)],
    )
    turns = [
        LLMResponse(content="", tool_calls=[_call("lakehouse_search", f"kredi {i}", f"s{i}")])
        for i in range(4)
    ] + [LLMResponse(content="Bu turda uygun seri doğrulanamadı; katalog adayları incelenebilir.")]
    llm = _ScriptedLLM(turns)
    registry = ToolRegistry()
    registry.register(search)
    agent = AnalyticsAgent(
        llm=llm,
        registry=registry,
        workspace=AnalysisWorkspace(),
        max_steps=10,
        tool_gate=False,
        max_catalog_search_calls=2,
    )

    answer = agent.ask("Kredi serilerini kaynak ve frekansıyla listele")

    recovery = next(item for item in answer.artifacts if item["kind"] == "execution_recovery")
    assert len(search.calls) == 2
    assert answer.error_codes().get("CATALOG_SEARCH_BUDGET") == 1
    assert answer.availability_status == "RETRIEVAL_FAILED"
    assert recovery["catalog_search_calls"] == 2
    assert recovery["catalog_search_budget_exhausted"] is True
    assert llm.calls == 3
    assert answer.usage["deterministic_recovery_shortcuts"] == 1


def test_recovery_timeout_returns_truthful_non_absence_status() -> None:
    query = _QueueTool("lakehouse_query", [ToolResult.fail("UNSAFE_SQL", "blocked by SQL policy")])
    llm = _FailingScriptedLLM(
        [LLMResponse(content="", tool_calls=[_call("lakehouse_query", "unsafe", "q1")])],
        fail_on_call=1,
        error=RuntimeError("LLM recovery request timed out"),
    )
    answer = _agent(llm, query).ask("2024 kredi verisini getir")

    assert answer.availability_status == "RETRIEVAL_FAILED"
    assert "isteği doğrulayamadım" in answer.text
    assert "kaynağın boş olduğunu göstermez" in answer.text
    assert "bulunmuyor" not in answer.text.casefold()
    recovery = next(item for item in answer.artifacts if item["kind"] == "execution_recovery")
    assert recovery["finalization_reason"] == "recovery_llm_unavailable"
    assert answer.error_codes().get("LLM_UNAVAILABLE") == 1


def test_recovery_timeout_preserves_authoritative_absence() -> None:
    absent = _QueueTool(
        "lakehouse_search",
        [ToolResult(content="Bu kapsamda eşleşme yok.", artifacts={"availability_status": "CONFIRMED_ABSENT"})],
    )
    llm = _FailingScriptedLLM(
        [LLMResponse(content="", tool_calls=[_call("lakehouse_search", "unmatched", "s1")])],
        fail_on_call=1,
        error=RuntimeError("LLM recovery request timed out"),
    )
    answer = _agent(llm, absent).ask("Katalogda bu kapsamı ara")

    assert answer.availability_status == "CONFIRMED_ABSENT"
    assert "doğrulanmış bir katalog eşleşmesi olmadığını" in answer.text
    assert "sayı üretmedim" in answer.text.casefold()


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
