"""Generic source discovery and controlled fallback; all providers/LLMs are local fakes."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from kkb_agent.contracts.evidence import EvidencePanel, NumberEvidence
from kkb_agent.core.agent import AnalyticsAgent
from kkb_agent.core.registry import ToolRegistry
from kkb_agent.core.tool import Tool, ToolResult
from kkb_agent.core.tool_gate import decide
from kkb_agent.core.web_routing import public_db_fallback, source_domains
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.llm.base import LLMResponse, ToolCall
from kkb_agent.tools.web import WebSearchTool, WebUrlTool
from kkb_agent.web.search import TavilySearch
from kkb_agent.web_app import evidence_to_dict


class Resp:
    def __init__(self, status, body, ctype="text/html"):
        self.status_code, self.content = status, body
        self.headers = {"Content-Type": ctype}

    def iter_content(self, n):
        yield self.content

    def close(self):
        pass


class Session:
    def __init__(self, routes):
        self.routes = routes

    def get(self, url, **kwargs):
        return self.routes.get(url, Resp(404, b"missing"))


class SearchSession:
    def __init__(self, urls=None):
        self.payloads = []
        self.urls = urls if urls is not None else ["https://stats.example/releases/data.csv"]

    def post(self, url, *, json, headers, timeout):
        self.payloads.append(json)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "results": [
                    {"url": u, "title": "Release", "content": "snippet says 999"} for u in self.urls
                ]
            },
        )


class ScriptedLLM:
    model = "local-script"

    def __init__(self, responses, native=True):
        self.responses = responses
        self.native = native
        self.offers = []
        self.messages = []

    def supports_native_tools(self):
        return self.native

    def chat(self, messages, *, tools=None, **kwargs):
        self.offers.append({t["function"]["name"] for t in tools or []})
        self.messages.append([m.content for m in messages])
        return self.responses[min(len(self.offers) - 1, len(self.responses) - 1)]


def call(name, **args):
    return LLMResponse(content="", tool_calls=[ToolCall(name=name, id=name, arguments=args)])


def build(responses, db=None, search_urls=None):
    reg = ToolRegistry()
    ws = AnalysisWorkspace()
    search_session = SearchSession(search_urls)
    reg.register(
        WebSearchTool(TavilySearch(environ={"TAVILY_API_KEY": "test"}, session=search_session), reg)
    )
    fetch_session = Session(
        {
            "https://stats.example/": Resp(
                200, b'<h1>Portal</h1><a href="/releases/data.csv">Data</a>'
            ),
            "https://stats.example/releases/data.csv": Resp(
                200, b"Year,Count\n2025,42\n", ctype="text/csv"
            ),
        }
    )
    reg.register(WebUrlTool(ws, registry=reg, session=fetch_session))
    if db:
        reg.register(db)
    llm = ScriptedLLM(responses)
    return AnalyticsAgent(llm, reg, workspace=ws, max_steps=9), llm, search_session


def cached_page(agent, *, age=0, readable=True):
    url = "https://stats.example/reports?id=7"
    agent.workspace.remember_web({"visited": [{"url": url, "sha256": "abc123", "readable": readable,
        "status": 200, "fetched_at": (datetime.now(UTC) - timedelta(seconds=age)).isoformat()}],
        "read_text": {"url": url, "text": "Annual report 2025. Count 48.6116."}})
    return url


def test_recent_read_excerpt_reused_with_proof_and_without_rewrite():
    agent, llm, _ = build([])
    url = cached_page(agent)
    llm.responses = [LLMResponse(content=f"Annual report 2025. Source: {url}")]
    answer = agent.ask("Webden stats.example faaliyet raporu yılını bul.")
    assert len(llm.offers) == 1
    web = next(a for a in answer.artifacts if a.get("kind") == "web")
    assert web["reused"] and web["visited"][0]["sha256"] == "abc123"
    assert web["read_text"]["text"] == agent.workspace.web_pages[url]["text_excerpt"]


@pytest.mark.parametrize("age,readable", [(301, True), (0, False)])
def test_stale_or_unreadable_excerpt_cannot_support_answer(age, readable):
    agent, _, _ = build([])
    url = cached_page(agent, age=age, readable=readable)
    assert not agent._cached_web_evidence("Webden stats.example raporunu bul", url)


def test_refresh_and_new_query_identity_require_new_fetch():
    agent, _, _ = build([])
    url = cached_page(agent)
    assert not agent._cached_web_evidence("stats.example raporunu yeniden kontrol et", url)
    assert not agent._cached_web_evidence("https://stats.example/reports?id=8 oku", url)
    del agent.workspace.web_pages[url]["text_excerpt"]
    assert not agent._cached_web_evidence("stats.example raporunu bul", url)


def test_web_prose_removes_unsupported_year_and_preserves_rounding():
    agent, _, _ = build([])
    url = cached_page(agent)
    artifacts = agent._cached_web_evidence("stats.example raporunu bul", url)
    clean = agent._source_note(f"Latest report 2025. Report 2026 is unpublished. Count 48.61. Source: {url}", [], artifacts)
    assert "2025" in clean and "48.61" in clean
    assert "2026" not in clean
    assert any(a.get("kind") == "web_prose_validation" for a in artifacts)


def test_ocr_reading_keeps_source_chain_and_separate_uncertainty():
    panel = EvidencePanel(question="read document", numbers=[NumberEvidence(2024, "2024", matched=True)],
        web_sources=[{"url": "https://stats.example/document", "sha256": "abc", "fetched_at": "now"}],
        ocr_unverified=True, gaps=["metin OCR ile görüntüden okundu; doğrulanmadı"])
    assert panel.chain_ok and not panel.claims_ok and not panel.complete
    assert evidence_to_dict(panel)["ocr_unverified"] is True


def test_explicit_web_skips_database_preload_but_db_request_keeps_it():
    agent, _, _ = build([])
    called = []
    agent.preloader = lambda q: called.append(q)
    agent._build_messages("https://stats.example/rates.xml döviz alış ve satış değerlerini getir")
    assert not called
    agent._build_messages("Veri havuzundaki konut kredisi bakiyesini getir")
    assert len(called) == 1


def test_model_that_never_reads_web_stops_without_rewrite_loop():
    agent, llm, _ = build([LLMResponse(content="Annual report 2025.")])
    answer = agent.ask("Webden stats.example faaliyet raporunu bul")
    assert len(llm.offers) == 2
    assert "2025" not in answer.text
    assert "kaynak içeriği okunmadığından" in answer.text


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    from kkb_agent.core import web_routing
    from kkb_agent.source_hints import load_source_hints
    hints = dict(load_source_hints())
    hints["public_source_domains"] = {**hints["public_source_domains"], "public_counts": ["stats.example"]}
    monkeypatch.setattr(web_routing, "load_source_hints", lambda: hints)
    monkeypatch.setattr("kkb_agent.web.fetch.private_host", lambda host: False)


@pytest.mark.parametrize(
    "question",
    [
        "stats.example içinden yıllık raporu getir",
        "https://stats.example/ içinden yıllık raporu getir",
    ],
)
def test_domain_discovery_filters_and_fetches_actual_data(question):
    agent, llm, session = build(
        [
            call("web_search", query="annual counts"),
            LLMResponse(content="Count is 999."),  # harness must demand URL fetch
            call("web_url", url="https://stats.example/releases/data.csv", purpose="annual counts"),
            call(
                "web_url",
                url="https://stats.example/releases/data.csv",
                purpose="annual counts",
                table_index=0,
            ),
            LLMResponse(content="2025: 42."),
        ],
        search_urls=[
            "https://stats.example/releases/data.csv",
            "https://stats.example.evil.example/data",
            "https://other.example/data",
        ],
    )
    answer = agent.ask(question)
    assert session.payloads[0]["include_domains"] == ["stats.example"]
    assert agent.registry.sanctioned_locators == {"https://stats.example/releases/data.csv"}
    assert answer.workspace.table["Count"].iloc[0] == 42
    assert "999" not in answer.text
    assert answer.grounding == "OK"
    assert "https://stats.example/releases/data.csv" in answer.text
    assert "web_search" in llm.offers[0]


def test_bare_domain_root_and_same_domain_links_authorized():
    agent, _, _ = build([])
    agent.registry.active_question = "stats.example içinden raporu getir"
    result = agent.registry.execute(
        "web_url", {"url": "https://stats.example/", "purpose": "annual data"}
    )
    assert result.ok and "AYNI DOMAIN KAYNAK ADAYLARI" in result.content
    assert agent.registry.execute(
        "web_url", {"url": "https://stats.example/releases/data.csv", "purpose": "counts"}
    ).ok
    assert not agent.registry.execute(
        "web_url", {"url": "https://other.example/", "purpose": "counts"}
    ).ok


def test_direct_file_url_uses_fetch_without_search():
    agent, _, session = build(
        [
            call(
                "web_url",
                url="https://stats.example/releases/data.csv",
                purpose="counts",
                table_index=0,
            ),
            LLMResponse(content="2025: 42."),
        ]
    )
    answer = agent.ask("https://stats.example/releases/data.csv verisini oku")
    assert not session.payloads
    assert answer.workspace.has_table


class Params(BaseModel):
    query: str = ""


class DB(Tool):
    name = "lakehouse_query"
    description = "local database"
    Params = Params

    def __init__(self, result):
        from kkb_agent.contracts.lakehouse import QueryProvenance
        self.lakehouse = self
        if result.provenance is None:
            result.provenance = QueryProvenance(sql="", dataset_ids=["public-counts"])
        self.result = result

    def get_dataset(self, dataset_id):
        if dataset_id != "public-counts":
            raise KeyError(dataset_id)
        return SimpleNamespace(source="public_counts", name="Annual counts")

    def run(self, params):
        return self.result


@pytest.mark.parametrize(
    "result",
    [
        ToolResult(
            content="outside coverage", artifacts={"availability_status": "CONFIRMED_ABSENT"}
        ),
        ToolResult.fail("OUT_OF_COVERAGE", "outside coverage"),
    ],
)
def test_verified_public_db_absence_dynamically_opens_web(result):
    agent, llm, session = build(
        [
            call("lakehouse_query"),
            call("web_search", query="TBB annual statistics", include_domains=["stats.example"]),
            call(
                "web_url",
                url="https://stats.example/releases/data.csv",
                purpose="counts",
                table_index=0,
            ),
            LLMResponse(content="2025: 42."),
        ],
        db=DB(result),
    )
    answer = agent.ask("TBB yıllık istatistiklerini getir")
    assert "web_search" not in llm.offers[0]
    assert "web_search" in llm.offers[1]
    assert len(session.payloads) == 1
    assert answer.availability_status == "FOUND"
    assert answer.workspace.has_table


@pytest.mark.parametrize(
    "question,result",
    [
        ("TBB yıllık istatistikleri", ToolResult.fail("SQL_FAILED", "bad sql")),
        ("TBB yıllık istatistikleri", ToolResult.fail("GOLD_STALE", "stale")),
        (
            "TBB yıllık istatistikleri",
            ToolResult(content="bad filter", artifacts={"availability_status": "RETRIEVAL_FAILED"}),
        ),
        (
            "Müşteri hesap hareketleri",
            ToolResult(content="empty", artifacts={"availability_status": "CONFIRMED_ABSENT"}),
        ),
        (
            "TBB kurum içi müşteri hesapları",
            ToolResult(content="empty", artifacts={"availability_status": "CONFIRMED_ABSENT"}),
        ),
        (
            "TBB yıllık istatistikleri; web kullanma",
            ToolResult(content="empty", artifacts={"availability_status": "CONFIRMED_ABSENT"}),
        ),
    ],
)
def test_errors_private_requests_and_web_prohibition_never_open_fallback(question, result):
    agent, llm, session = build(
        [call("lakehouse_query"), LLMResponse(content="İstek doğrulanamadı.")], db=DB(result)
    )
    agent.ask(question)
    assert not session.payloads
    # Explicit "web kullanma" can match the existing gate regex, but never starts fallback.
    if "web" not in question:
        assert all("web_search" not in offers for offers in llm.offers)


def test_search_only_answer_cannot_publish_snippet():
    agent, _, _ = build(
        [call("web_search", query="annual counts"), LLMResponse(content="Count is 999.")]
    )
    answer = agent.ask("Webden yıllık sayıyı bul")
    assert "999" not in answer.text and "okun" in answer.text
    assert not answer.workspace.has_table


def test_failed_fetch_after_search_cannot_publish_snippet():
    agent, _, _ = build(
        [
            call("web_search", query="annual counts"),
            call("web_url", url="https://stats.example/missing", purpose="counts"),
            LLMResponse(content="Count is 999."),
        ],
        search_urls=["https://stats.example/missing"],
    )
    answer = agent.ask("Webden yıllık sayıyı bul")
    assert "999" not in answer.text


def test_institution_scope_and_domain_suffix_boundary():
    assert source_domains("TBB'den yıllık istatistik getir") == ["tbb.org.tr"]
    agent, _, session = build(
        [], search_urls=["https://www.tbb.org.tr/data", "https://tbb.org.tr.evil.example/data"]
    )
    agent.registry.active_question = "TBB'den yıllık istatistik getir"
    result = agent.registry.execute("web_search", {"query": "statistics"})
    assert result.ok
    assert session.payloads[0]["include_domains"] == ["tbb.org.tr"]
    assert result.artifacts["web_search"]["hits"] == ["https://www.tbb.org.tr/data"]
    assert not agent.registry.execute(
        "web_search", {"query": "statistics", "include_domains": ["other.example"]}
    ).ok
    assert not agent.registry.execute(
        "web_url", {"url": "https://www.tcmb.gov.tr/data", "purpose": "statistics"}
    ).ok


def test_no_search_key_still_supports_direct_url():
    agent, llm, _ = build(
        [
            call(
                "web_url",
                url="https://stats.example/releases/data.csv",
                purpose="counts",
                table_index=0,
            ),
            LLMResponse(content="2025: 42."),
        ]
    )
    agent.registry._tools.pop("web_search")
    answer = agent.ask("https://stats.example/releases/data.csv oku")
    assert answer.workspace.has_table and "web_search" not in llm.offers[0]


def test_new_domain_is_visible_in_gate():
    assert decide(
        "fresh-authority.example içinden raporu getir", {"web_search", "web_url"}
    ).allowed == {"web_search", "web_url"}
    assert not public_db_fallback("TBB istatistikleri")
    assert public_db_fallback("istatistik", ["public_counts"])
    assert not public_db_fallback("Özel satış raporu")


def test_portal_read_before_search_does_not_ground_discovered_document():
    agent, _, _ = build(
        [
            call("web_url", url="https://stats.example/", purpose="counts"),
            call("web_search", query="annual counts"),
            LLMResponse(content="Count is 999."),
        ]
    )
    answer = agent.ask("stats.example içinden yıllık veriyi getir")
    assert "999" not in answer.text and not answer.workspace.has_table


def test_public_provenance_can_enable_fallback_without_institution_in_question():
    from kkb_agent.contracts.lakehouse import QueryProvenance

    result = ToolResult(
        content="outside coverage",
        artifacts={"availability_status": "CONFIRMED_ABSENT"},
        provenance=QueryProvenance(sql="", dataset_ids=["public-counts"], sources=["public_counts"], row_count=0),
    )
    agent, llm, _ = build(
        [call("lakehouse_query"), LLMResponse(content="İstek doğrulanamadı.")], db=DB(result)
    )
    answer = agent.ask("Yıllık yayımlanmış istatistikleri getir")
    assert "web_search" in llm.offers[1]
    assert answer.availability_status == "CONFIRMED_ABSENT"
    assert not public_db_fallback("Müşteri hesapları", ["TBB"])


def test_bare_domain_with_slash_is_normalized_and_web_prohibition_enforced():
    agent, _, session = build([])
    agent.registry.active_question = "stats.example içinden raporu getir"
    assert agent.registry.execute("web_url", {"url": "stats.example/", "purpose": "report"}).ok
    agent.registry.active_question = "TBB verisi, web kullanma"
    result = agent.registry.execute("web_search", {"query": "TBB statistics"})
    assert not result.ok and not session.payloads


def test_invalid_domain_filter_rejected_before_network():
    agent, _, session = build([])
    result = agent.registry.execute(
        "web_search", {"query": "statistics", "include_domains": ["not a domain"]}
    )
    assert not result.ok and not session.payloads


def test_search_result_outside_pinned_domain_is_not_sanctioned():
    agent, _, _session = build([], search_urls=["https://other.example/data"])
    agent.registry.active_question = "stats.example içinden raporu getir"
    result = agent.registry.execute("web_search", {"query": "statistics"})
    assert result.ok and result.artifacts["web_search"]["hits"] == []
    assert not agent.registry.sanctioned_locators


def test_named_institution_discovery_opens_web_without_literal_web_keyword():
    gate = decide("TBB sitesinden yıllık raporu getir", {"web_search", "web_url"})
    assert gate.allowed == {"web_search", "web_url"}


def test_bddk_current_official_domain_is_configured_without_changing_explicit_domain():
    assert source_domains("BDDK sitesinden raporu getir") == ["bddk.gov.tr", "bddk.org.tr"]
    assert source_domains("bddk.org.tr içinden raporu getir") == ["bddk.org.tr"]


def test_json_protocol_receives_dynamic_web_catalog_after_db_absence():
    import json

    agent, _, session = build(
        [],
        db=DB(
            ToolResult(
                content="outside coverage", artifacts={"availability_status": "CONFIRMED_ABSENT"}
            )
        ),
    )
    responses = [
        LLMResponse(content=json.dumps({"tool": "lakehouse_query", "args": {}})),
        LLMResponse(content=json.dumps({"tool": "web_search", "args": {"query": "annual counts"}})),
        LLMResponse(
            content=json.dumps(
                {
                    "tool": "web_url",
                    "args": {
                        "url": "https://stats.example/releases/data.csv",
                        "purpose": "counts",
                        "table_index": 0,
                    },
                }
            )
        ),
        LLMResponse(content="2025: 42."),
    ]
    llm = ScriptedLLM(responses, native=False)
    agent.llm = llm
    answer = agent.ask("TBB yıllık istatistikleri")
    assert "- web_search:" in llm.messages[1][0]
    assert "- web_search:" not in llm.messages[0][0]
    assert answer.workspace.has_table and answer.availability_status == "FOUND"
    assert len(session.payloads) == 1


def test_positive_web_search_phrase_is_not_a_prohibition():
    from kkb_agent.core.web_routing import web_forbidden, web_requested

    assert not web_forbidden("Webden arama yap")
    assert web_requested("Webden arama yap")
    assert not web_forbidden("Web araması ile araştır")
    assert web_forbidden("Web kullanma")


def test_query_identity_and_schemaless_subpage_are_preserved():
    from kkb_agent.core.intent import locator_from_user

    assert locator_from_user("https://reports.example/annual?id=4", "reports.example/annual?id=4 oku")
    assert not locator_from_user("https://reports.example/annual?id=5", "reports.example/annual?id=4 oku")
    assert not locator_from_user("https://reports.example/annual?id=5", "", {"https://reports.example/annual?id=4"})
    agent, _, _ = build([])
    agent.registry.active_question = "stats.example/releases/data.csv oku"
    assert agent.registry.execute("web_url", {"url": "stats.example/releases/data.csv", "purpose": "counts"}).ok


def test_public_query_is_built_from_catalog_not_private_question_or_sql():
    from kkb_agent.contracts.lakehouse import QueryProvenance
    from kkb_agent.core.web_routing import public_fallback_plan

    provenance = QueryProvenance(sql="SELECT 'SECRET_ROW'", dataset_ids=["public-counts"])
    db = DB(ToolResult(content="empty", provenance=provenance))
    question = "TCMB ile kıyasla: satışlarımızın 2009 yılı toplamı özel_deger_123"
    plan = public_fallback_plan(question, provenance, db)
    assert plan == {"query": "Annual counts 2009", "include_domains": ["stats.example"]}
    assert not public_fallback_plan(question, QueryProvenance(sql="", dataset_ids=["unknown-private"]), db)
    assert not public_db_fallback(question)


def test_automatic_search_cannot_override_public_catalog_query_or_scope():
    agent, _, session = build([])
    agent.registry.public_web_fallback = {"query": "Annual counts 2009", "include_domains": ["stats.example"]}
    result = agent.registry.execute("web_search", {"query": "SECRET_SQL SECRET_ROW", "include_domains": ["other.example"]})
    assert result.ok
    assert session.payloads[0]["query"] == "Annual counts 2009"
    assert session.payloads[0]["include_domains"] == ["stats.example"]


def test_failed_ocr_is_not_readable_data(monkeypatch):
    from kkb_agent.web.html import extract_page

    class FailedOCR:
        model = "fake-ocr"
        def ocr_png(self, png):
            raise RuntimeError("provider failed")

    page = extract_page(b"not a png", "image/png", "https://stats.example/image.png", ocr=FailedOCR())
    assert page.extraction_error == "OCR_FAILED"
    agent, _, _ = build([])
    agent.registry.active_question = "https://stats.example/releases/data.csv oku"
    import importlib
    crawler = importlib.import_module("kkb_agent.web.crawl")
    monkeypatch.setattr(crawler, "extract_page", lambda *a, **k: page)
    result = agent.registry.execute("web_url", {"url": "https://stats.example/releases/data.csv", "purpose": "read"})
    assert not result.ok and result.error.error_code == "EXTRACTION_FAILED"
    assert not result.artifacts["web"]["visited"][0]["readable"]


def test_text_evidence_has_read_source_without_requiring_table():
    from kkb_agent.core.evidence import EvidenceBuilder

    url = "https://stats.example/annual"
    artifacts = [{"kind": "web", "used_text": url, "read_text": {"url": url, "text": "There are 17 regions."},
                  "visited": [{"url": url, "status": 200, "sha256": "abc", "fetched_at": "2026-01-01", "readable": True}]}]
    panel = EvidenceBuilder(object()).build("question", "There are 17 regions.", AnalysisWorkspace(), [], artifacts=artifacts)
    assert panel.complete and panel.web_sources[0]["url"] == url
    linked = EvidenceBuilder(object()).build("question", "There are 17 regions. https://stats.example/download?id=991", AnalysisWorkspace(), [], artifacts=artifacts)
    assert linked.complete
    panel = EvidenceBuilder(object()).build("question", "There are 999 regions.", AnalysisWorkspace(), [], artifacts=artifacts)
    assert not panel.complete


def test_method_calls_are_not_user_supplied_domains():
    from kkb_agent.core.web_routing import addresses
    assert addresses("Webden Python belgelerini araştır: list.copy() ve copy.deepcopy()") == []
    assert source_domains("Webden Python belgelerini araştır: list.copy()") == []
    assert addresses("docs.python.org/3/library/copy.html oku") == ["docs.python.org/3/library/copy.html"]


def test_public_data_request_does_not_open_web_before_verified_absence():
    gate = decide("BDDK verilerinden 2001 yılı konut kredisi bakiyesini getir", {"web_search", "web_url", "lakehouse_query"})
    assert "web_search" not in gate.allowed
    gate = decide("BDDK sitesinden faaliyet raporunu getir", {"web_search", "web_url"})
    assert "web_search" in gate.allowed


def test_web_prose_keeps_identifier_numbers_but_drops_unsupported_speculation():
    """Aşırı kırpma düzeltmesi (Q1 yalnız-link): kanun no ('5411 sayılı') gibi kimlik/atıf sayısı, kaynakta
    olmasa da meşru cümleyi kırpmaz. Desteklenmeyen spekülatif yıl ('2026 yayımlanmadı') hâlâ çıkarılır."""
    agent, _, _ = build([])                       # known kaynak metni: 2025, 48.6116
    url = cached_page(agent)
    artifacts = agent._cached_web_evidence("stats.example raporunu bul", url)
    ans = (f"BDDK 2025 raporu 5411 sayılı Kanun uyarınca yayımlandı. "
           f"2026 raporu henüz yayımlanmadı. Source: {url}")
    clean = agent._source_note(ans, [], artifacts)
    assert "5411 sayılı" in clean and "2025 raporu" in clean          # kimlik/atıf + destekli yıl korunur
    assert "2026 raporu henüz yayımlanmadı" not in clean               # desteklenmeyen spekülasyon çıkar
