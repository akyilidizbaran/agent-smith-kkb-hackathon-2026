"""Deterministic contract tests for selective multi-turn context reuse."""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.lakehouse import QueryProvenance
from kkb_agent.core.agent import AnalyticsAgent, _web_outage_summary
from kkb_agent.core.evidence import EvidenceBuilder
from kkb_agent.core.follow_up import FollowUpContext, _extract, is_active_table_composition, resolve_follow_up
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


class _WorkspaceQueryTool(_QueryTool):
    """A lakehouse-like query that installs a verified 60-month workspace."""

    def __init__(self, workspace: AnalysisWorkspace) -> None:
        super().__init__()
        self.workspace = workspace

    def run(self, params: _QueryParams) -> ToolResult:
        self.calls += 1
        dates = pd.date_range("2021-04-30", "2026-03-31", freq="ME")
        frame = pd.DataFrame(
            {
                "period_end": dates,
                "need": range(len(dates)),
                "card": [value * 10 for value in range(len(dates))],
            }
        )
        provenance = QueryProvenance(
            sql="SELECT period_end, need, card FROM verified_fixture",
            dataset_ids=["bddk_monthly:1536_Toplam", "bddk_monthly:1539_Toplam"],
            sources=["bddk_monthly"],
            row_count=len(frame),
        )
        self.workspace.set_table(frame, description="verified 60 month fixture", provenance=provenance)
        return ToolResult(
            content=f"Sorgu başarılı: {len(frame)} aylık satır",
            data=frame,
            provenance=provenance,
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


class _QueryThenNarrationTimeoutLLM(_ScriptedLLM):
    """Completes the data call, then simulates a provider timeout while narrating."""

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None) -> LLMResponse:
        if self.calls == 0:
            self.messages.append(list(messages))
            self.calls += 1
            return LLMResponse(content="", tool_calls=[_call(2025, "q1")])
        raise RuntimeError("LLM 2 denemede yanıt vermedi: Request timed out.")


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


def test_explicit_month_window_is_not_implicitly_a_comparison() -> None:
    previous = FollowUpContext(
        domain="finance", source="BDDK", metric="kredi",
        series="bddk_monthly:1536_Toplam", date_range="2021-04–2026-03", frequency="monthly",
    )
    result = resolve_follow_up(
        "Verileri 202301–202412 döneminde aylık bazda hizala.", previous
    )

    assert result.is_follow_up
    assert result.context.date_range == "2023-01–2024-12"
    assert result.context.comparison_target == ()


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


def test_aktif_tabloya_yeni_kaynak_ekleme_composition_olarak_siniflanir() -> None:
    previous = FollowUpContext(
        domain="finance", source="BDDK Aylık Bülten", metric="ihtiyaç kredisi",
        series="bddk_monthly:1536_Toplam", date_range="2022-01–2023-12", frequency="monthly",
    )
    catalog = [SimpleNamespace(
        dataset_id="evds:TP.TUFE", name="Tüketici Fiyat Endeksi", source="TCMB EVDS",
        tags=["TÜFE", "enflasyon"], columns=[],
    )]
    question = "Mevcut tabloya TCMB EVDS TÜFE serisini ekle ve dönem bazında birleştir."
    resolution = resolve_follow_up(question, previous, catalog=catalog)

    assert is_active_table_composition(question, resolution)
    assert not is_active_table_composition("2024 TÜFE verilerini getir", resolution)
    assert not is_active_table_composition("Mevcut tabloyu göster", resolution)


def test_composition_context_provenance_kimliklerini_prompta_tasir() -> None:
    workspace = AnalysisWorkspace()
    workspace.set_table(
        pd.DataFrame({"donem": [date(2024, 1, 31)], "bakiye": [10.0]}),
        description="Doğrulanmış BDDK tablosu",
        provenance=QueryProvenance(sql="SELECT ...", dataset_ids=["bddk_monthly:1536_Toplam"], sources=["BDDK"]),
    )
    agent = AnalyticsAgent(_ScriptedLLM([]), ToolRegistry(), workspace=workspace)
    question = "Mevcut tabloya TCMB EVDS TÜFE serisini ekle ve birleştir."
    catalog = [SimpleNamespace(
        dataset_id="evds:TP.TUFE", name="Tüketici Fiyat Endeksi", source="TCMB EVDS",
        tags=["TÜFE", "enflasyon"], columns=[],
    )]
    agent._follow_up_resolution = resolve_follow_up(question, FollowUpContext(
        domain="finance", source="BDDK", metric="ihtiyaç kredisi", series="bddk_monthly:1536_Toplam",
    ), catalog=catalog)
    agent._active_table_reuse_allowed = False
    agent._active_table_composition_allowed = True
    agent._attach_active_series_identities()

    messages = agent._build_messages(question)

    assert "AKTİF TABLO BİRLEŞTİRME ÇAPASI" in messages[0].content
    assert "bddk_monthly:1536_Toplam" in messages[0].content
    assert "tek başına yeni isteğin cevabı değildir" in messages[0].content


def _agent(llm: _ScriptedLLM, *, fail_after: int | None = None) -> tuple[AnalyticsAgent, _QueryTool]:
    tool = _QueryTool(fail_after=fail_after)
    registry = ToolRegistry()
    registry.register(tool)
    return AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace()), tool


def test_narration_timeout_commits_verified_context_for_monthly_follow_up() -> None:
    """A provider outage after query execution must not orphan the active table."""
    workspace = AnalysisWorkspace()
    tool = _WorkspaceQueryTool(workspace)
    registry = ToolRegistry()
    registry.register(tool)
    specs = [
        SimpleNamespace(
            dataset_id="bddk_monthly:1536_Toplam",
            name="İhtiyaç kredisi",
            source="bddk_monthly",
            frequency=SimpleNamespace(value="monthly"),
            coverage=SimpleNamespace(start=date(2021, 4, 1), end=date(2026, 3, 31)),
        ),
        SimpleNamespace(
            dataset_id="bddk_monthly:1539_Toplam",
            name="Bireysel kredi kartları",
            source="bddk_monthly",
            frequency=SimpleNamespace(value="monthly"),
            coverage=SimpleNamespace(start=date(2021, 4, 1), end=date(2026, 3, 31)),
        ),
    ]
    agent = AnalyticsAgent(
        llm=_QueryThenNarrationTimeoutLLM([]),
        registry=registry,
        workspace=workspace,
        max_steps=4,
    )
    agent._catalog_specs = lambda: specs

    first = agent.ask(
        "Aylık BDDK ihtiyaç kredisi ve bireysel kredi kartı bakiyelerini tabloya getir ve sonucu kısaca açıkla."
    )

    assert tool.calls == 1
    assert first.steps[0].tool_name == "lakehouse_query"
    assert first.steps[-1].error_code == "LLM_UNAVAILABLE"
    assert first.availability_status == "FOUND"
    assert "Doğrulanmış tablo" in first.text
    assert "Model servisine şu an ulaşılamıyor" not in first.text
    assert "Yerel otomatik veri özeti (LLM yorumu değildir)" in first.text
    assert "60 satır, 3 sütun" in first.text
    assert "need" in first.text and "min 0" in first.text and "max 59" in first.text
    assert "card" in first.text and "min 0" in first.text and "max 590" in first.text
    assert first.usage["failed_llm_calls"] == 1
    assert first.usage["failed_llm_call_ms"] >= first.steps[-1].duration_ms
    assert first.usage["llm_call_ms"] >= first.usage["failed_llm_call_ms"]
    assert first.steps[-1].llm_duration_ms == first.steps[-1].duration_ms
    payload = answer_to_dict(
        first,
        agent,
        question="Aylık BDDK ihtiyaç kredisi ve bireysel kredi kartı bakiyelerini tabloya getir ve sonucu kısaca açıkla.",
    )
    assert payload["table"]["row_count"] == 60, "ilk doğrulanmış aktif tablo tam pencereyi korumalı"
    assert agent.follow_up_context.series == "bddk_monthly:1536_Toplam"
    assert agent.follow_up_resolution is not None and agent.follow_up_resolution.committed

    second = agent.ask("Aylık değişimleri 202301–202412 dönemine hizala.")

    assert second.usage["calls"] == 0, "takip deterministik fast path ile tamamlanmalı"
    assert tool.calls == 1, "takip yeni katalog/sorgu çağrısı yapmamalı"
    assert second.steps[0].tool_name == "workspace_compute_column"
    view = second.steps[0].result_data
    assert len(view) == 24
    assert view.iloc[0]["need_change"] == 1
    assert view.iloc[0]["card_change"] == 10
    assert len(workspace.table) == 60, "pencere görünümü aktif tablonun yerine geçmez"
    second_payload = answer_to_dict(
        second,
        agent,
        question="Aylık değişimleri 202301–202412 dönemine hizala.",
    )
    assert second_payload["table"]["row_count"] == 24
    assert second_payload["table"]["rows"][0]["c0"] == "2023-01-31"
    assert second_payload["table"]["rows"][-1]["c0"] == "2024-12-31"


def test_web_narration_timeout_keeps_sources_and_does_not_attach_stale_table() -> None:
    class _WebParams(BaseModel):
        url: str
        purpose: str

    class _WebReadTool(Tool):
        name = "web_url"
        description = "web sayfası oku"
        Params = _WebParams

        def run(self, params: _WebParams) -> ToolResult:
            return ToolResult(
                content="Sayfa açıldı; içerik tablosu yok.",
                artifacts={"web": {
                    "start_url": params.url,
                    "used": None,
                    "table_loaded": False,
                    "visited": [{
                        "url": params.url,
                        "status": 200,
                        "sha256": "a" * 64,
                        "fetched_at": "2026-09-20T10:00:00+00:00",
                        "title": "Duyurular",
                    }],
                    "blocked": [],
                    "skipped": [],
                    "limit_exceeded": [],
                }},
            )

    class _ReadThenTimeoutLLM:
        model = "web-timeout"

        def __init__(self) -> None:
            self.calls = 0

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="", tool_calls=[ToolCall(
                    id="read-1",
                    name="web_url",
                    arguments={"url": "https://example.test/news", "purpose": "duyuruları incele"},
                )])
            raise RuntimeError("LLM 1 denemede yanıt vermedi: Request timed out.")

    workspace = AnalysisWorkspace()
    workspace.set_table(pd.DataFrame({"eski_soru_degeri": [987654321]}), description="önceki tur")
    registry = ToolRegistry()
    registry.register(_WebReadTool())
    agent = AnalyticsAgent(
        _ReadThenTimeoutLLM(), registry, workspace=workspace,
        evidence=EvidenceBuilder(None), max_steps=4,
    )
    session = Session(lambda: agent)

    payload = session.ask("TERA Holding duyurularını şu sayfadan incele: https://example.test/news")

    assert "dış kaynak sayfaları okundu" in payload["text"]
    assert "doğrulanmış bir içerik özeti veya sayı sunmuyorum" in payload["text"]
    assert "987654321" not in payload["text"]
    assert payload["availability_status"] == "UNKNOWN"
    assert payload["table"] is None, "önceki tur tablosu yeni web yanıtına sızmamalı"
    assert payload["evidence"]["table_rows"] == 0
    assert payload["evidence"]["web_reads"][0]["url"] == "https://example.test/news"
    assert "sentezlenmedi" in payload["evidence"]["gaps"][-1]


def test_web_outage_summary_distinguishes_search_candidates_from_read_sources() -> None:
    search_only = [{
        "kind": "web_search",
        "hits": ["https://example.test/report"],
        "results": [{"url": "https://example.test/report", "title": "Rapor"}],
    }]
    text = _web_outage_summary(search_only)
    assert text is not None and "Arama parçacıkları" in text
    assert "sayfa açıldı" not in text
    assert _web_outage_summary([]) is None


def test_search_only_timeout_preserves_candidates_as_context_not_data() -> None:
    class _SearchParams(BaseModel):
        query: str

    class _SearchTool(Tool):
        name = "web_search"
        description = "web araması"
        Params = _SearchParams

        def run(self, params: _SearchParams) -> ToolResult:
            return ToolResult(
                content="Bir arama adayı bulundu.",
                artifacts={"web_search": {
                    "query": params.query,
                    "hits": ["https://example.test/report"],
                    "results": [{"url": "https://example.test/report", "title": "Ekonomik görünüm"}],
                }},
            )

    class _SearchThenTimeoutLLM:
        model = "search-timeout"

        def __init__(self) -> None:
            self.calls = 0

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="", tool_calls=[ToolCall(
                    id="search-1", name="web_search", arguments={"query": "ekonomik görünüm"},
                )])
            raise RuntimeError("LLM 1 denemede yanıt vermedi: Request timed out.")

    workspace = AnalysisWorkspace()
    registry = ToolRegistry()
    registry.register(_SearchTool())
    agent = AnalyticsAgent(
        _SearchThenTimeoutLLM(), registry, workspace=workspace,
        evidence=EvidenceBuilder(None), max_steps=4,
    )

    payload = Session(lambda: agent).ask("İnternetten ekonomik görünümü araştır ve özetle.")

    assert "Arama parçacıkları veri kanıtı sayılmadığından" in payload["text"]
    assert payload["table"] is None
    assert payload["evidence"]["context_sources"][0]["url"] == "https://example.test/report"
    assert payload["evidence"]["web_reads"] == []


def test_direct_table_request_finishes_after_verified_data_without_narration() -> None:
    """Retrieval-only asks must not spend another model turn narrating a complete table."""
    workspace = AnalysisWorkspace()
    tool = _WorkspaceQueryTool(workspace)
    registry = ToolRegistry()
    registry.register(tool)
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call(2024, "retrieve")]),
    ])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=workspace, max_steps=4)

    question = "2024 yılına ait aylık konut kredisi bakiyelerini tablo olarak göster."
    answer = agent.ask(question)

    assert llm.calls == 1, "başarılı tablo sonrasında anlatı/örnekleme için ikinci LLM turu olmamalı"
    assert tool.calls == 1
    assert answer.steps[0].llm_duration_ms > 0
    assert answer.steps[0].tool_duration_ms >= 0
    assert answer.usage["llm_call_ms"] >= answer.steps[0].llm_duration_ms
    assert answer.availability_status == "FOUND"
    assert len(answer.workspace.table) == 60
    assert answer.steps[-1].role == "narrate"
    assert "model anlatım turu atlandı" in answer.steps[-1].thought
    assert "veri tablosu hazırlandı" in answer.text
    assert answer_to_dict(answer, agent, question=question)["table"]["row_count"] == 60


def test_narration_phase_uses_shorter_deadline_than_question_budget() -> None:
    class _DeadlineLLM:
        model = "deadline-test"

        def __init__(self) -> None:
            self.deadlines = []

        def supports_native_tools(self) -> bool:
            return True

        def set_deadline(self, deadline) -> None:
            self.deadlines.append(deadline)

        def set_thinking(self, _disabled) -> None:
            pass

        def chat(self, _messages, *, tools=None, temperature=0.0, max_tokens=None):
            return LLMResponse(content="Kısa, doğrulanmış açıklama.")

    llm = _DeadlineLLM()
    agent = AnalyticsAgent(
        llm=llm,
        registry=ToolRegistry(),
        time_budget_s=600,
        narration_timeout_s=12,
    )
    started = time.perf_counter()
    agent._ask_deadline = started + 600

    agent._chat([], phase="narration")

    assert len(llm.deadlines) == 2
    assert started + 10 <= llm.deadlines[0] <= started + 12.1
    assert llm.deadlines[1] is None, "LLM istemcisindeki çağrı deadline'ı temizlenmeli"


def test_tool_phase_has_total_deadline_below_question_budget() -> None:
    class _DeadlineLLM:
        model = "deadline-test"

        def __init__(self) -> None:
            self.deadlines = []

        def supports_native_tools(self) -> bool:
            return True

        def set_deadline(self, deadline) -> None:
            self.deadlines.append(deadline)

        def chat(self, _messages, *, tools=None, temperature=0.0, max_tokens=None):
            return LLMResponse(content="Kısa araç planı.")

    llm = _DeadlineLLM()
    agent = AnalyticsAgent(
        llm=llm, registry=ToolRegistry(), time_budget_s=600, tool_timeout_s=18,
    )
    started = time.perf_counter()
    agent._ask_deadline = started + 600

    agent._chat([], phase="tool")

    assert len(llm.deadlines) == 2
    assert started + 16 <= llm.deadlines[0] <= started + 18.1
    assert llm.deadlines[1] is None


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


def _two_series_monthly_workspace() -> tuple[AnalysisWorkspace, FollowUpContext, list[SimpleNamespace]]:
    dates = pd.date_range("2021-04-30", periods=60, freq="ME")
    workspace = AnalysisWorkspace()
    workspace.set_table(
        pd.DataFrame({"date": dates, "metric_a": range(60), "metric_b": [i * 3 for i in range(60)]}),
        description="generic verified fixture",
        provenance=QueryProvenance(sql="SELECT * FROM fixture", dataset_ids=[], sources=["fixture"]),
        column_provenance={
            "metric_a": QueryProvenance(sql="SELECT metric_a FROM fixture_a", dataset_ids=["fixture:a"]),
            "metric_b": QueryProvenance(sql="SELECT metric_b FROM fixture_b", dataset_ids=["fixture:b"]),
        },
    )
    context = FollowUpContext(
        domain="generic", source="fixture", metric="activity", series="fixture:a",
        date_range="2021-04–2026-03", frequency="monthly",
    )
    specs = [
        SimpleNamespace(dataset_id="fixture:a", source="fixture", frequency=SimpleNamespace(value="monthly"), name="Metric A"),
        SimpleNamespace(dataset_id="fixture:b", source="fixture", frequency=SimpleNamespace(value="monthly"), name="Metric B"),
    ]
    return workspace, context, specs


def _add_fixture_changes(workspace: AnalysisWorkspace, context: FollowUpContext, specs) -> None:
    from kkb_agent.core.workspace_fastpath import (
        execute_verified_workspace_transform,
        plan_verified_workspace_transform,
    )

    question = "Bu aktif tablodaki aylık değişimleri hesapla."
    resolution = resolve_follow_up(question, context)
    plan = plan_verified_workspace_transform(question, resolution, workspace, active_specs=specs)
    assert plan is not None
    assert execute_verified_workspace_transform(workspace, plan) is not None


class _FixtureChartParams(BaseModel):
    chart_type: str
    x_column: str
    y_columns: list[str]
    title: str


class _FixtureChartTool(Tool):
    name = "chart"
    description = "fixture chart"
    Params = _FixtureChartParams

    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls = 0

    def run(self, params: _FixtureChartParams) -> ToolResult:
        self.calls += 1
        self.path.write_text("{}", encoding="utf-8")
        return ToolResult(content="Chart hazır.", artifacts={
            "chart": {"kind": "chart", "title": params.title, "spec_path": str(self.path)}
        })


def test_verified_transform_and_chart_follow_up_is_deterministic_and_keeps_all_series(tmp_path) -> None:
    workspace, context, specs = _two_series_monthly_workspace()
    before = workspace.table
    chart = _FixtureChartTool(tmp_path / "chart.json")
    registry = ToolRegistry()
    registry.register(chart)

    class _NeverCalledLLM:
        model = "never-called"

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, *_args, **_kwargs):
            raise AssertionError("verified table + graph must not need another model turn")

    agent = AnalyticsAgent(_NeverCalledLLM(), registry, workspace=workspace)
    agent._catalog_specs = lambda: specs
    agent._follow_up_context = context
    question = "Bu serilerin aylık değişimlerini çizgi grafikte göster."

    answer = agent.ask(question)

    assert chart.calls == 1
    assert answer.usage["calls"] == 0
    assert any(step.tool_name == "workspace_compute_column" and step.ok for step in answer.steps)
    assert any(step.tool_name == "chart" and step.ok for step in answer.steps)
    assert agent.follow_up_resolution is not None
    assert agent.follow_up_resolution.active_series_ids == ("fixture:a", "fixture:b")
    payload = answer_to_dict(answer, agent, table_before=before, question=question)
    assert payload["table"]["row_count"] == 60
    assert [column["label"] for column in payload["table"]["columns"]] == [
        "date", "metric_a_change", "metric_b_change"
    ]
    assert len(payload["charts"]) == 1


def test_chart_and_verified_table_survive_narration_timeout(tmp_path) -> None:
    workspace, context, specs = _two_series_monthly_workspace()
    _add_fixture_changes(workspace, context, specs)
    chart = _FixtureChartTool(tmp_path / "chart.json")
    registry = ToolRegistry()
    registry.register(chart)

    class _ChartThenTimeoutLLM:
        model = "chart-timeout"

        def __init__(self) -> None:
            self.calls = 0

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="", tool_calls=[ToolCall(
                    id="chart-1",
                    name="chart",
                    arguments={
                        "chart_type": "line", "x_column": "date",
                        "y_columns": ["metric_a_change", "metric_b_change"],
                        "title": "Monthly changes",
                    },
                )])
            raise RuntimeError("LLM 1 denemede yanıt vermedi: Request timed out.")

    llm = _ChartThenTimeoutLLM()
    agent = AnalyticsAgent(llm, registry, workspace=workspace, max_steps=4)
    agent._catalog_specs = lambda: specs
    agent._follow_up_context = context
    agent.upload_root = tmp_path
    question = "Bu aylık değişimlerin grafiğini çiz ve bulguları yorumla."

    session = Session(lambda: agent)
    payload = session.ask(question)

    assert llm.calls == 2
    assert chart.calls == 1
    assert payload["availability_status"] == "FOUND"
    assert payload["usage"]["failed_llm_phase"] == "narration"
    assert any(step["tool"] == "chart" and step["ok"] for step in payload["steps"])
    assert any(chart["kind"] == "chart" for chart in payload["charts"])
    assert payload["table"]["row_count"] == 60
    assert [column["label"] for column in payload["table"]["columns"]] == [
        "date", "metric_a_change", "metric_b_change"
    ]
    assert "Model servisine şu an ulaşılamıyor" not in payload["text"]
    exported = session.tables[0]
    assert list(exported.columns) == ["date", "metric_a_change", "metric_b_change"]
    assert len(exported) == 60
    from io import BytesIO

    from kkb_agent.web_app import table_csv_bytes, table_xlsx_bytes

    csv_frame = pd.read_csv(BytesIO(table_csv_bytes(exported)), sep=";", decimal=",", encoding="utf-8-sig")
    xlsx_frame = pd.read_excel(BytesIO(table_xlsx_bytes(exported)), engine="openpyxl")
    assert list(csv_frame.columns) == list(xlsx_frame.columns) == list(exported.columns)
    assert len(csv_frame) == len(xlsx_frame) == 60


def _provincial_catalog() -> list[SimpleNamespace]:
    """Alphabetically first FinTürk series plus a national total, as in the demo catalog."""
    return [
        SimpleNamespace(
            dataset_id="bddk_finturk:ADANA_DigerMevduat",
            name="Diğer Mevduat, ADANA (Bireysel Bankacılık, Sektör)",
            source="bddk_finturk",
            source_detail=None,
            tags=["mevduat", "aylık", "il"],
            columns=[
                SimpleNamespace(name="observation_date", role="time", example_values=[], aliases=["dönem"]),
                SimpleNamespace(name="value", role="measure", example_values=[], aliases=["diğer mevduat"]),
            ],
        ),
        SimpleNamespace(
            dataset_id="bddk_finturk:IZMIR_DigerMevduat",
            name="Diğer Mevduat, İZMİR (Bireysel Bankacılık, Sektör)",
            source="bddk_finturk",
            source_detail=None,
            tags=["mevduat", "aylık", "il"],
            columns=[
                SimpleNamespace(name="value", role="measure", example_values=[], aliases=["diğer mevduat"]),
            ],
        ),
        SimpleNamespace(
            dataset_id="bddk_monthly:1200_Toplam",
            name="Toplam Mevduat",
            source="bddk_monthly",
            source_detail=None,
            tags=["mevduat", "aylık"],
            columns=[
                SimpleNamespace(name="value", role="measure", example_values=[], aliases=["toplam mevduat"]),
            ],
        ),
    ]


def test_generic_metric_word_does_not_bind_first_provincial_series() -> None:
    """PR #18 jenerik (21 Eyl): 'mevduat' alfabetik ilk seri olan ADANA'ya bağlanıyor, 20 ulusal soru il'e kayıyordu."""
    question = "2022 ile 2024 arasında mevduat ve kredi serilerini çeyrek sonu değerleriyle karşılaştır."
    explicit = _extract(question, _provincial_catalog())

    assert explicit.series is None
    assert explicit.metric == "kredi"
    assert explicit.geography == ()
    resolution = resolve_follow_up(question, catalog=_provincial_catalog())
    assert "series=" not in resolution.prompt()
    assert "ADANA" not in resolution.prompt()


def test_named_province_binds_only_that_province_series() -> None:
    catalog = _provincial_catalog()

    izmir = _extract("İzmir diğer mevduat bakiyesini 2024 için getir", catalog)
    assert izmir.series == "bddk_finturk:IZMIR_DigerMevduat"

    adana = _extract("Adana diğer mevduat bakiyesini 2024 için getir", catalog)
    assert adana.series == "bddk_finturk:ADANA_DigerMevduat"

    national = _extract("Toplam mevduat bakiyesini 2024 için getir", catalog)
    assert national.series == "bddk_monthly:1200_Toplam"


def test_multi_word_catalog_name_still_binds_on_new_question() -> None:
    """Tek genel sözcük kuralı çok sözcüklü katalog adlarını (ör. 'USD satış kuru') etkilemez."""
    first = resolve_follow_up("2026 USD satış kuru", catalog=_catalog())
    assert first.context.series == "evds:usd_satis"


def test_direct_table_delivery_text_carries_rows_period_and_source() -> None:
    """PR #18 jenerik (21 Eyl): 12 vakada iki sabit cümle; kullanıcıya satır/dönem/kaynak bilgisi gitmiyordu."""
    workspace = AnalysisWorkspace()
    tool = _WorkspaceQueryTool(workspace)
    registry = ToolRegistry()
    registry.register(tool)
    llm = _ScriptedLLM([LLMResponse(content="", tool_calls=[_call(2024, "retrieve")])])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=workspace, max_steps=4)
    agent._catalog_specs = lambda: [
        SimpleNamespace(
            dataset_id="bddk_monthly:1536_Toplam", name="İhtiyaç kredisi", source="bddk_monthly",
            source_detail="Tablo 5", source_url=None, frequency=SimpleNamespace(value="monthly"),
            columns=[SimpleNamespace(name="need", role="measure", unit="milyon TL", semantic_type="stock",
                                     aliases=["ihtiyaç kredisi"], example_values=[])],
        ),
        SimpleNamespace(
            dataset_id="bddk_monthly:1539_Toplam", name="Bireysel kredi kartları", source="bddk_monthly",
            source_detail="Tablo 5", source_url=None, frequency=SimpleNamespace(value="monthly"),
            columns=[SimpleNamespace(name="card", role="measure", unit="milyon TL", semantic_type="stock",
                                     aliases=["kredi kartı"], example_values=[])],
        ),
    ]

    answer = agent.ask("2024 yılına ait aylık konut kredisi bakiyelerini tablo olarak göster.")

    assert llm.calls == 1, "anlatım turu yine atlanmalı (token kazancı korunur)"
    assert "veri tablosu hazırlandı" in answer.text
    assert "60 satır" in answer.text
    assert "2021-04-30" in answer.text and "2026-03-31" in answer.text
    assert "period_end, need, card" in answer.text
    assert "İhtiyaç kredisi" in answer.text and "Bireysel kredi kartları" in answer.text
    assert "birim milyon TL" in answer.text
    assert "dönem sonu stok" in answer.text


def test_comparison_request_is_not_finished_by_transform_fast_path() -> None:
    workspace = AnalysisWorkspace()
    tool = _WorkspaceQueryTool(workspace)
    registry = ToolRegistry()
    registry.register(tool)
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call(2024, "retrieve")]),
        LLMResponse(content="İki seri aynı eksende: need 0 → 59, card 0 → 590."),
    ])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=workspace, max_steps=4)

    answer = agent.ask("İki serinin aylık değişimlerini aynı tarih ekseninde karşılaştır.")

    assert llm.calls == 2, "karşılaştırma isteyen soruda anlatım turu atlanmamalı"
    assert answer.steps[-1].role == "narrate"
    assert "dönüşüm doğrulanmış aktif tabloya uygulandı" not in answer.text


def test_bare_tool_name_answer_is_replaced_by_deterministic_summary() -> None:
    """C04 (PR #18 jenerik): anlatım turu yalnız 'workspace_compute_column' döndürdü, harness cevap saydı."""
    workspace = AnalysisWorkspace()
    tool = _WorkspaceQueryTool(workspace)
    registry = ToolRegistry()
    registry.register(tool)
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call(2024, "retrieve")]),
        LLMResponse(content="lakehouse_query"),
    ])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=workspace, max_steps=4)

    answer = agent.ask("2024 verilerinin genel yönünü değerlendir.")

    assert answer.text.strip() != "lakehouse_query"
    assert "Doğrulanmış sonuç tablosu ve indirmeler hazır" in answer.text
    assert "60 satır" in answer.text
    assert answer.usage["empty_final_response_fallbacks"] == 1
    assert any("yalnız araç adı" in (step.thought or "") for step in answer.steps)


def _province_in_id_catalog() -> list[SimpleNamespace]:
    """İl adı yalnız seri kimliğinde (alt çizgili), görünen adda değil."""
    return [
        SimpleNamespace(
            dataset_id="bddk_finturk:VAN_TasitKredisi",
            name="Taşıt Kredisi (Bireysel Bankacılık, Sektör)",
            source="bddk_finturk",
            source_detail=None,
            tags=["kredi", "aylık", "il"],
            columns=[
                SimpleNamespace(name="value", role="measure", example_values=[], aliases=["taşıt kredisi"]),
            ],
        ),
        SimpleNamespace(
            dataset_id="bddk_monthly:1535_Toplam",
            name="Tüketici Kredileri - Taşıt, Toplam (Sektör)",
            source="bddk_monthly",
            source_detail=None,
            tags=["kredi", "aylık"],
            columns=[
                SimpleNamespace(name="value", role="measure", example_values=[], aliases=["taşıt kredisi"]),
            ],
        ),
    ]


def test_province_is_read_from_underscored_dataset_id() -> None:
    """İnceleme (22 Eyl): `\\b` alt çizgiyi sözcük sayar; il 'VAN_TasitKredisi' kimliğinden okunmuyordu."""
    catalog = _province_in_id_catalog()

    national = _extract("Taşıt kredisi bakiyesini 2024 için getir", catalog)
    assert national.series == "bddk_monthly:1535_Toplam"

    van = _extract("Van taşıt kredisi bakiyesini 2024 için getir", catalog)
    assert van.series == "bddk_finturk:VAN_TasitKredisi"


def test_facet_extraction_failure_keeps_legacy_candidates(monkeypatch) -> None:
    """extract_facets hata verirse il serileri toptan elenmez; filtresiz eski aday listesine dönülür."""
    import kkb_agent.core.follow_up as follow_up_module

    def _boom(_question: str):
        raise RuntimeError("facet fixture failure")

    monkeypatch.setattr(follow_up_module, "extract_facets", _boom)
    explicit = _extract("Van taşıt kredisi bakiyesini 2024 için getir", _province_in_id_catalog())
    assert explicit.series == "bddk_finturk:VAN_TasitKredisi"


def test_single_word_topics_are_metrics_not_series() -> None:
    """'stok', 'kar', 'kur', 'endeks', 'oran', 'takip' yeni konu olarak metric'e yazılır; gövde/ek karışmaz."""
    assert _extract("Şimdi stok serisini getir", []).metric == "stok"
    assert _extract("Kâr marjını 2024 için göster", []).metric == "kar"
    assert _extract("Takipteki alacakları getir", []).metric == "takip"
    assert _extract("Endeksi aylık göster", []).metric == "endeks"
    assert _extract("Kur farkını getir", []).metric == "kur"
    assert _extract("Bunu 2024 ile karşılaştır", []).metric is None
    assert _extract("Kurumsal segmenti getir", []).metric is None
    assert _extract("Aylık değişim oranını hesapla", []).metric is None

    previous = FollowUpContext(domain="finance", metric="mevduat", series="bddk_monthly:1200_Toplam")
    resolution = resolve_follow_up("Stok değişimini hesapla", previous)
    assert resolution.explicit.metric == "stok"
    assert "metric" in resolution.overridden


def test_aggregation_words_tolerate_turkish_suffixes_and_need_word_start() -> None:
    assert _extract("Bu serinin 2024 ortalamasını hesapla", []).aggregation == "average"
    assert _extract("2024 döneminde toplamını ver", []).aggregation == "sum"
    assert _extract("En düşüğünü bul", []).aggregation == "minimum"
    assert _extract("En yüksek değeri göster", []).aggregation == "maximum"
    assert _extract("2025 için tahmin et", []).aggregation is None
    assert _extract("2024 döneminde", []).aggregation is None
    assert _extract("Çeyrekleri toplamadan aylık ver", []).aggregation is None


def test_pre_satisfied_transform_flag_is_cleared_for_the_next_turn() -> None:
    """İnceleme (22 Eyl): `_pre_satisfied_capabilities` yalnız reset()'te sıfırlanıyordu. İlk turda hızlı yol
    'dönüşüm'ü ön-karşılanmış sayınca, yeni konudaki ikinci soru dönüşüm aracı çalışmadan
    'dönüşüm uygulandı' teslimiyle bitebiliyordu."""
    workspace, context, specs = _two_series_monthly_workspace()
    _add_fixture_changes(workspace, context, specs)
    registry = ToolRegistry()
    registry.register(_WorkspaceQueryTool(workspace))
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[_call(2025, "q1")]),
        LLMResponse(content="2025 için hastane başvuru oranı tabloda."),
    ])
    agent = AnalyticsAgent(llm, registry, workspace=workspace, max_steps=4)
    agent._catalog_specs = lambda: specs
    agent._follow_up_context = context

    first = agent.ask("Bu aktif tablodaki aylık değişimleri hesapla.")
    assert first.reused_verified_table and llm.calls == 0
    assert "dönüşüm" in agent._pre_satisfied_capabilities

    # "artışı" closes the plain delivery fast path; "oran" keeps the
    # transformation gate in play, which is where the stale flag was read.
    second = agent.ask("2025 yılı hastane başvuru oranındaki artışı getir.")

    assert agent._pre_satisfied_capabilities == set()
    assert agent._verified_reuse_snapshot is None
    assert llm.calls == 2
    assert second.text == "2025 için hastane başvuru oranı tabloda."
    assert "dönüşüm" not in second.text
    assert not any("model anlatım turu atlandı" in (step.thought or "") for step in second.steps)
