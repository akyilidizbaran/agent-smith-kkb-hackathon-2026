from __future__ import annotations

import time
from types import SimpleNamespace

from pydantic import BaseModel

from kkb_agent.core.agent import AnalyticsAgent
from kkb_agent.core.registry import ToolRegistry
from kkb_agent.core.token_budget import TokenBudgetPolicy
from kkb_agent.core.tool import Tool, ToolResult
from kkb_agent.core.web_research import WebResearchState, canonical_page_url
from kkb_agent.llm.base import LLMResponse, ToolCall


def test_follow_up_search_requires_a_read_source_and_an_explicit_gap() -> None:
    state = WebResearchState(max_searches=3)

    assert state.authorize_search("TÜFE 2025") is None
    state.record_tool_result(
        "web_search",
        SimpleNamespace(
            ok=True,
            artifacts={"web_search": {"results": [{"url": "https://stats.example/tufe"}]}},
        ),
    )
    assert (
        state.authorize_search("TÜFE 2025 kaynak", research_gap="farklı sorgu").error_code
        == "WEB_RESEARCH_NEEDS_READ"
    )

    state.record_tool_result(
        "web_url",
        SimpleNamespace(
            ok=False,
            artifacts={"web": {"visited": [{"url": "https://stats.example/tufe", "status": 200}]}},
        ),
    )
    assert state.authorize_search("TÜFE 2025 kaynak").error_code == "WEB_RESEARCH_GAP_REQUIRED"
    assert (
        state.authorize_search(
            "TÜFE 2025 farklı yayın", research_gap="Okunan sayfa dönemsel değeri göstermiyor"
        )
        is None
    )
    assert state.remaining_searches == 1


def test_web_research_blocks_duplicate_queries_and_bounds_page_reads() -> None:
    state = WebResearchState(max_searches=2, max_unique_pages=2)
    assert state.authorize_search("Faiz oranları 2024") is None
    assert (
        state.authorize_search("  FAİZ   ORANLARI 2024! ").error_code
        == "WEB_RESEARCH_DUPLICATE_QUERY"
    )
    assert state.page_budget("https://one.example/a", requested=5) == 2
    state.record_tool_result(
        "web_url",
        SimpleNamespace(
            ok=True,
            artifacts={
                "web": {
                    "visited": [
                        {"url": "https://ONE.example:443/a#top", "status": 200},
                        {"url": "https://one.example/b", "status": 200},
                    ]
                }
            },
        ),
    )
    assert state.remaining_pages == 0
    assert state.page_budget("https://two.example/c", requested=1) == 0
    assert state.page_budget("https://one.example/a", requested=3) == 1
    assert canonical_page_url("https://ONE.example:443/a#top") == "https://one.example/a"


def test_model_evidence_context_is_bounded_and_reports_truncation() -> None:
    state = WebResearchState(max_model_evidence_chars=10)

    assert state.bound_model_evidence("12345") == "12345"
    bounded = state.bound_model_evidence("6789012345")

    assert bounded.startswith("67890")
    assert "kanıt panelinde korunuyor" in bounded
    snapshot = state.snapshot()
    assert snapshot["model_evidence_chars"] == 10
    assert snapshot["context_truncated"] is True


class _SearchParams(BaseModel):
    query: str
    research_gap: str | None = None


class _ReadParams(BaseModel):
    url: str
    purpose: str


class _SearchTool(Tool):
    name = "web_search"
    role = "retrieve"
    description = "İnternette kaynak adayları bulur."
    Params = _SearchParams

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def run(self, params: _SearchParams) -> ToolResult:
        denial = self.registry.web_research.authorize_search(params.query, params.research_gap)
        if denial:
            return ToolResult.fail(
                denial.error_code, denial.message, hint=denial.hint, layer="harness"
            )
        return ToolResult(
            content="Kaynak adayı bulundu; snippet kanıt değildir.",
            artifacts={"web_search": {"results": [{"url": "https://source.example/fact"}]}},
        )


class _ReadTool(Tool):
    name = "web_url"
    role = "retrieve"
    description = "Verilen kaynak sayfasını okur."
    Params = _ReadParams

    def run(self, params: _ReadParams) -> ToolResult:
        return ToolResult(
            content="Açılan kaynak doğrulanabilir bir açıklama içeriyor.",
            artifacts={"web": {"visited": [{"url": params.url, "status": 200}]}},
        )


class _ResearchLLM:
    model = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.deadlines: list[tuple[float | None, float]] = []
        self.responses = [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="search",
                        name="web_search",
                        arguments={"query": "kurum açıklaması"},
                    )
                ],
            ),
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="read",
                        name="web_url",
                        arguments={
                            "url": "https://source.example/fact",
                            "purpose": "istenen bilgiyi doğrula",
                        },
                    )
                ],
            ),
            LLMResponse(
                content="Okunan kaynak açıklaması doğruluyor.",
                usage={"prompt": 50, "completion": 20},
            ),
        ]

    def supports_native_tools(self) -> bool:
        return True

    def set_deadline(self, deadline: float | None) -> None:
        self.deadlines.append((deadline, time.perf_counter()))

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
        self.calls.append({
            "tools": tools,
            "max_tokens": max_tokens,
            "system": messages[0].content if messages else "",
        })
        return self.responses.pop(0)


def test_agent_keeps_web_tool_decisions_in_tool_phase_until_synthesis() -> None:
    registry = ToolRegistry()
    registry.register(_SearchTool(registry))
    registry.register(_ReadTool())
    llm = _ResearchLLM()
    agent = AnalyticsAgent(
        llm,
        registry,
        token_budget_policy=TokenBudgetPolicy(global_max=4000),
        max_steps=5,
    )

    answer = agent.ask("Bu konuyu webden araştır.")

    phases = [item["phase"] for item in answer.usage["token_budget_calls"]]
    limits = [item["max_tokens"] for item in answer.usage["token_budget_calls"]]
    assert phases == ["planning", "tool", "tool"]
    assert limits == [1000, 1800, 1800]
    assert "İlk turda yalnızca doğru veri yolunu keşfet" in llm.calls[0]["system"]
    assert "İlk turda yalnızca doğru veri yolunu keşfet" in llm.calls[1]["system"]
    assert "YANIT AŞAMASI" in llm.calls[2]["system"]
    assert "İlk turda yalnızca doğru veri yolunu keşfet" not in llm.calls[2]["system"]
    assert answer.usage["web_research"]["stage"] == "complete"
    assert answer.usage["web_research"]["successful_searches"] == 1
    assert answer.usage["web_research"]["unique_pages_read"] == 1
    assert answer.steps[-1].role == "narrate"
    assert llm.deadlines[0][0] is None
    # Tool calls use their own 90 s budget; the default narration timeout is 30 s.
    bounded_deadlines = [
        deadline - started_at for deadline, started_at in llm.deadlines if deadline is not None
    ]
    assert all(remaining > 60 for remaining in bounded_deadlines), bounded_deadlines


def test_rereading_a_known_page_after_a_search_counts_as_a_read() -> None:
    """İnceleme (22 Eyl): daha önce okunmuş sayfa ikinci aramadan sonra yeniden okununca 'yeni okuma'
    sayılmıyor, üçüncü arama NEEDS_READ ile dönüyordu."""
    state = WebResearchState(max_searches=3)
    hits = SimpleNamespace(ok=True, artifacts={"web_search": {"results": [{"url": "https://stats.example/tufe"}]}})
    page = SimpleNamespace(ok=True, artifacts={"web": {"visited": [{"url": "https://stats.example/tufe", "status": 200}]}})

    assert state.authorize_search("TÜFE 2025") is None
    state.record_tool_result("web_search", hits)
    state.record_tool_result("web_url", page)
    assert state.authorize_search("TÜFE 2025 yıllık", research_gap="yıllık değer eksik") is None
    state.record_tool_result("web_search", hits)
    state.record_tool_result("web_url", page)

    assert state.remaining_pages == state.max_unique_pages - 1
    assert state.authorize_search("TÜFE 2025 aylık", research_gap="aylık değer eksik") is None
