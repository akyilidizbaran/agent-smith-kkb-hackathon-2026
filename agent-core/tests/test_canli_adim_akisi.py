"""Canlı adım akışı (ADR-0079): /api/ask/stream satır satır adım olayları, sonda /api/ask ile aynı cevap yükü; sahte ajan, ağ yok."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.agent import AgentAnswer, AgentStep  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.tool import Tool, ToolResult  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.live_steps import args_detail, live_hooks, tool_label  # noqa: E402
from kkb_agent.llm.base import LLMResponse, ToolCall  # noqa: E402
from kkb_agent.web_app import create_app  # noqa: E402

HTML = Path(__file__).resolve().parents[1] / "src" / "kkb_agent" / "static" / "index.html"


class _Params(BaseModel):
    dataset_id: str
    purpose: str = ""


class _Query(Tool):
    name = "lakehouse_query"
    description = "sorgu"
    Params = _Params

    def run(self, params: BaseModel) -> ToolResult:
        return ToolResult(content="Sorgu başarılı: 2 satır")


class _LLM:
    model = "sahte"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)

    def chat(self, messages, **kwargs) -> LLMResponse:
        return self.responses.pop(0)


class _Builder:
    def build(self, *args, **kwargs):
        return None


class StepAgent:
    """Gerçek döngünün çağrı sırasını taklit eder: plan → araç → hatalı araç → taslak → geri gönderme → yeniden yazım → kanıt."""

    def __init__(self) -> None:
        self.registry = ToolRegistry()
        self.registry.register(_Query())
        self.workspace = AnalysisWorkspace()
        self.llm = _LLM([
            LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="lakehouse_query",
                                                         arguments={"dataset_id": "bddk_monthly:1534_Toplam", "purpose": "aylık bakiye"})]),
            LLMResponse(content="Aralık bakiyesi 999 milyon TL."),        # doğrulanmamış taslak: ekrana düşmemeli
            LLMResponse(content="Aralık bakiyesi 678.970 milyon TL."),
        ])
        self.evidence_builder = _Builder()
        self.tool_gate = False
        self.last_gate = SimpleNamespace(allowed=frozenset({"lakehouse_query"}), opened=(), closed=())

    def ask(self, question: str) -> AgentAnswer:
        plan = self.llm.chat([], tools=[])
        for call in plan.tool_calls:
            self.registry.execute(call.name, call.arguments)
        self.registry.execute("yok_boyle", {})
        self.llm.chat([])
        final = self.llm.chat([])
        self.evidence_builder.build(question)
        return AgentAnswer(text=final.content, usage={},
                           steps=[AgentStep(index=1, role="execute", tool_name="lakehouse_query", ok=True, duration_ms=5.0,
                                            tool_args={"dataset_id": "bddk_monthly:1534_Toplam", "purpose": "aylık bakiye"})])


def _stream(client: TestClient, question: str) -> list[dict]:
    with client.stream("POST", "/api/ask/stream", json={"question": question}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


def _hooks_restored(agent: StepAgent) -> bool:
    return "execute" not in vars(agent.registry) and "chat" not in vars(agent.llm) and "build" not in vars(agent.evidence_builder)


def test_akis_once_adimlari_sonra_ayni_cevap_yukunu_verir() -> None:
    made: list[StepAgent] = []
    client = TestClient(create_app(lambda: made.append(StepAgent()) or made[-1]))
    events = _stream(client, "2025 Aralık konut kredisi bakiyesi?")
    steps = [e for e in events if e["type"] == "step"]
    assert [e["label"] for e in steps if e["state"] == "run"] == [
        "Soru inceleniyor", "Veri havuzunda sorgu çalıştırılıyor", "yok_boyle çalışıyor", "Sonuçlar değerlendiriliyor",
        "Cevap denetleniyor", "Cevap yeniden yazılıyor", "Cevap denetleniyor", "Kanıt zinciri kuruluyor"]
    final = {}
    for e in steps:
        final[e["id"]] = {**final.get(e["id"], {}), **e}
    by_label = lambda label: [s for s in final.values() if s["label"] == label]  # noqa: E731
    assert by_label("Soru inceleniyor")[0]["state"] == "ok" and by_label("Soru inceleniyor")[0]["kind"] == "model"
    query = by_label("Veri havuzunda sorgu çalıştırılıyor")[0]
    assert query["state"] == "ok" and query["detail"] == "aylık bakiye" and query["kind"] == "tool" and query["ms"] >= 0
    assert by_label("yok_boyle çalışıyor")[0]["state"] == "fail" and by_label("yok_boyle çalışıyor")[0]["detail"] == "UNKNOWN_TOOL"
    checks = [s for s in final.values() if s["kind"] == "check"]
    assert [c["state"] for c in checks] == ["back", "ok"] and checks[0]["label"] == "Taslak geri gönderildi"
    assert by_label("Kanıt zinciri kuruluyor")[0]["state"] == "ok"
    assert not any("999" in json.dumps(e, ensure_ascii=False) or "678.970" in json.dumps(e, ensure_ascii=False) for e in steps), \
        "modelin metni ve cevap sayıları adım olaylarında yok"
    assert events[-1]["type"] == "answer"
    payload = events[-1]["payload"]
    assert payload["index"] == 0 and payload["text"] == "Aralık bakiyesi 678.970 milyon TL."
    assert payload["steps"][0]["label"] == "Veri havuzunda sorgu çalıştırılıyor" and payload["steps"][0]["detail"] == "aylık bakiye"
    assert client.get("/api/answers").json()[0]["text"] == payload["text"]
    assert _hooks_restored(made[-1]), "soru bitince sarmalayıcılar kalkar"


def test_ajan_hatasi_akista_hata_olayi_olur_ve_oturum_kilitlenmez() -> None:
    class Boom(StepAgent):
        def ask(self, question: str) -> AgentAnswer:
            self.registry.execute("lakehouse_query", {"dataset_id": "x"})
            raise RuntimeError("model düştü")

    made: list[StepAgent] = []
    client = TestClient(create_app(lambda: made.append(Boom()) or made[-1]))
    events = _stream(client, "bakiye?")
    assert events[-1] == {"type": "error", "detail": "RuntimeError: model düştü"}
    assert [e["state"] for e in events if e["type"] == "step"] == ["run", "ok"]
    assert _hooks_restored(made[-1])
    assert client.post("/api/ask", json={"question": "tekrar"}).status_code == 500, "kilit bırakıldı, düz uç da çalışıyor"


def test_metin_ici_arac_cagrisinda_denetim_satiri_duser_ve_eksik_nesne_sorun_olmaz() -> None:
    events: list[dict] = []
    agent = StepAgent()
    agent.llm = _LLM([LLMResponse(content='{"tool": "lakehouse_query"}')])     # yerel tool-calling yok
    with live_hooks(agent, events.append):
        agent.llm.chat([])
        agent.registry.execute("lakehouse_query", {"dataset_id": "x"})
    check = [e for e in events if e.get("kind") == "check"]
    assert check and [e["state"] for e in events if e["id"] == check[0]["id"]] == ["run", "drop"]
    bare = SimpleNamespace(registry=None, llm=SimpleNamespace(model="m"), evidence_builder=None)
    with live_hooks(bare, events.append):
        pass
    with live_hooks(agent, lambda e: (_ for _ in ()).throw(ConnectionError("istemci koptu"))):
        assert agent.registry.execute("lakehouse_query", {"dataset_id": "x"}).ok, "olay gönderilemese de araç çalışır"


def test_arguman_ozeti_yol_ve_uzunluk() -> None:
    assert args_detail("web_url", {"url": "https://www.tcmb.gov.tr/kurlar/201501/02012015.xml"}) == "tcmb.gov.tr/…/02012015.xml"
    assert args_detail("web_url", {"url": "/srv/data/incoming/uploads/ab12cd34/cb6d79f3_hastane.csv"}) == "hastane.csv", "sunucu dizini ekrana çıkmaz"
    assert args_detail("lakehouse_search", {"query": "konut kredisi"}) == "“konut kredisi”"
    long = args_detail("workspace_query", {"sql": "SELECT " + ", ".join(f"kolon_{i}" for i in range(40)) + " FROM t"})
    assert len(long) <= 110 and long.endswith("…")
    assert args_detail("chart", None) == "" and tool_label("yeni_arac") == "yeni_arac çalışıyor" and tool_label(None) == ""


def test_arayuz_akis_ucunu_ve_yazim_animasyonunu_kullanir() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "/api/ask/stream" in html and "function typewrite(" in html and "function liveLog(" in html
    assert "Düşünüyor…" in html and "pq.remove()" in html and "Cevaptaki sayılar" not in html
    assert 'class="hop ' in html and 'class="stage ' not in html, "kanıt akışı halkaları yolculuk sahnesinin .stage stiliyle çakışmaz"
