"""Arayüz (D9): ajanı sarar, cevabı olduğu gibi JSON'a çevirir; sahte ajanla, ağ yok."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.evidence import EvidencePanel, NumberEvidence  # noqa: E402
from kkb_agent.core.agent import AgentAnswer, AgentStep  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.web_app import create_app, frame_to_dict  # noqa: E402


class FakeAgent:
    def __init__(self) -> None:
        self.registry = ToolRegistry()
        self.workspace = AnalysisWorkspace()
        self.llm = SimpleNamespace(model="sahte")
        self.tool_gate = True
        self.last_gate = SimpleNamespace(allowed=frozenset({"lakehouse_query"}), opened=(), closed=("grafik",))
        self.asked: list[str] = []

    def ask(self, question: str) -> AgentAnswer:
        self.asked.append(question)
        self.workspace.set_table(pd.DataFrame({"donem": ["2025-11", "2025-12"], "bakiye": [658770.0, 678970.0]}), description="t")
        panel = EvidencePanel(question=question, numbers=[NumberEvidence(number=678970.0, text="678.970", matched=True, column="bakiye")])
        return AgentAnswer(text="2025 Aralık bakiyesi **678.970** milyon TL.\n\n| Dönem | Bakiye |\n|---|---|\n| 2025-12 | 678.970 |",
                           steps=[AgentStep(index=1, role="execute", tool_name="lakehouse_query", tool_args={"sql": "SELECT 1"}, ok=True,
                                            result_summary="Sorgu başarılı", duration_ms=12.0)],
                           evidence=panel, usage={"prompt": 26240, "completion": 300, "calls": 2})


def test_status_ask_reset_dongusu() -> None:
    made: list[FakeAgent] = []

    def factory() -> FakeAgent:
        made.append(FakeAgent()); return made[-1]

    client = TestClient(create_app(factory))
    assert "Agent Smith" in client.get("/").text
    s = client.get("/api/status").json()
    assert s["model"] == "sahte" and s["tool_gate"] is True and s["history"] == []
    r = client.post("/api/ask", json={"question": "2025 Aralık konut kredisi bakiyesi?"}).json()
    assert r["text"].startswith("2025 Aralık") and r["table"]["columns"] == [{"key": "c0", "label": "donem"}, {"key": "c1", "label": "bakiye"}] and r["table"]["rows"][1]["c1"] == 678970.0
    assert r["steps"][0]["tool"] == "lakehouse_query" and r["steps"][0]["ok"] is True and r["steps"][0]["duration_ms"] == 12
    assert r["evidence"]["complete"] is True and r["evidence"]["numbers"][0]["text"] == "678.970"
    assert r["usage"]["prompt"] == 26240 and r["gate"]["closed"] == ["grafik"] and r["elapsed_s"] >= 0
    assert client.get("/api/status").json()["history"][0]["question"].startswith("2025 Aralık")
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/reset").json() == {"ok": True} and len(made) == 2
    assert client.get("/api/status").json()["history"] == []


def test_tablo_serilestirme_nan_sonsuz_ve_kirpma() -> None:
    import json
    frame = pd.DataFrame({"a": [1.0, float("nan"), float("inf")] + [3.0] * 300, "b": ["x", "y", "w"] + ["z"] * 300})
    d = frame_to_dict(frame)
    assert d["row_count"] == 303 and d["truncated"] and len(d["rows"]) == 200 and d["rows"][1]["c0"] is None and d["rows"][2]["c0"] is None
    json.dumps(d, allow_nan=False)   # katı JSON: NaN/Infinity kalmadı (A29)
    assert frame_to_dict(None) is None and frame_to_dict(pd.DataFrame()) is None


def test_tabloya_dokunmayan_cevap_eski_tabloyu_gostermez() -> None:
    class Greeter(FakeAgent):
        def ask(self, question: str) -> AgentAnswer:  # ilk soru tablo kurar, ikincisi selam
            if question == "selam":
                return AgentAnswer(text="Selam. Sorunu yazabilirsin.", steps=[AgentStep(index=1, role="narrate", thought="selamlaşma")], usage={})
            return super().ask(question)

    client = TestClient(create_app(Greeter))
    first = client.post("/api/ask", json={"question": "2025 konut"}).json()
    assert first["table"] is not None
    second = client.post("/api/ask", json={"question": "selam"}).json()
    assert second["table"] is None and second["table_title"] == "" and second["text"] == "Selam. Sorunu yazabilirsin."


def test_statik_dosyalar_yerelden_servis_edilir_uc_boyut_kutuphanesi_yok() -> None:
    client = TestClient(create_app(FakeAgent))
    assert client.get("/static/index.html").status_code == 200
    assert client.get("/static/vendor/three.module.min.js").status_code == 404   # ADR-0083: 3B gösterim kaldırıldı
    page = client.get("/").text
    assert "Yolculuğu izle" in page and "three" not in page.lower()


def test_cevaplar_ucu_sayfa_yenilemede_sohbeti_geri_getirir() -> None:
    client = TestClient(create_app(FakeAgent))
    assert client.get("/api/answers").json() == []
    client.post("/api/ask", json={"question": "2025 konut"})
    lst = client.get("/api/answers").json()
    assert len(lst) == 1 and lst[0]["index"] == 0 and lst[0]["question"] == "2025 konut" and lst[0]["table"]["columns"] == [{"key": "c0", "label": "donem"}, {"key": "c1", "label": "bakiye"}]
    assert client.get("/api/answers/0").json()["index"] == 0
    assert client.get("/api/answers/5").status_code == 404
    client.post("/api/reset")
    assert client.get("/api/answers").json() == []
