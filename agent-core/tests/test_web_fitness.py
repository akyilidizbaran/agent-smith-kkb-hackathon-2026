"""web_url önünde uygunluk kapısı (V3 §3.9, 15 Eyl): yanlış tablo aktif tablo OLMAZ; kullanıcı onayıyla aşılır;
uygun tablo kapsam/uygunluk satırıyla yüklenir. Ağ yok, oturum sahte; ajan kancaları sahte LLM ile."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kkb_agent.core.agent import AnalyticsAgent  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.tool import Tool, ToolResult  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.llm.base import LLMResponse, ToolCall  # noqa: E402
from kkb_agent.tools.web import WebUrlTool  # noqa: E402
from kkb_agent.web import RobotsCache  # noqa: E402

from test_web import HTML, Resp, Session  # noqa: E402

URL = "https://site.example/tufe"


def _tool(question: str, user_text: str | None = None) -> tuple[WebUrlTool, AnalysisWorkspace]:
    ws = AnalysisWorkspace()
    reg = SimpleNamespace(active_question=question, user_text=user_text or question, sanctioned_locators=set())
    s = Session({URL: Resp(200, HTML.encode(), url=URL)})
    return WebUrlTool(ws, registry=reg, session=s, robots=RobotsCache()), ws


def test_uygun_tablo_yuklenir_kart_uygunluk_ve_kapsam_tasir() -> None:
    tool, ws = _tool(f"Şu sayfadan 2025 yıllık TÜFE'yi söyle: {URL}")
    r = tool.validate_and_run({"url": URL, "purpose": "2025 TÜFE", "table_index": 0})
    assert r.ok and ws.table is not None
    assert "uygunluk: kabul" in r.content
    fit = r.artifacts["fitness"]
    assert fit["decision"] == "accept" and "tufe" in fit["present"] and fit["coverage"].startswith("tufe — 2024–2025, yearly, 2 satır")


def test_yanlis_tablo_yuklenmez_kart_tabloda_ne_oldugunu_soyler() -> None:
    # Soru konut kredisi bakiyesi; sayfadaki tablo TÜFE (anlamca yakın-yanlış: UEB B02 sınıfı).
    tool, ws = _tool(f"Şu sayfadan 2025 konut kredisi bakiyesini söyle: {URL}")
    r = tool.validate_and_run({"url": URL, "purpose": "konut kredisi bakiyesi", "table_index": 0})
    assert not r.ok and r.error.error_code == "FILE_IRRELEVANT" and not r.error.is_retryable
    assert ws.table is None, "reddedilen tablo aktif tablo olmamalı"
    assert "soru bakiye, konut, kredi istiyor; veride bunların hiçbiri yok (veride: tufe)" in r.content
    assert "Yıllık TÜFE (%)" in r.content, "kart tabloda ne olduğunu söyler"
    assert "user_confirmed=true" in r.content


def test_kullanici_onayiyla_yuklenir_model_bayragi_tek_basina_yetmez() -> None:
    q = f"Şu sayfadan 2025 konut kredisi bakiyesini söyle: {URL}"
    tool, ws = _tool(q)
    r = tool.validate_and_run({"url": URL, "purpose": "bakiye", "table_index": 0, "user_confirmed": True})
    assert not r.ok and ws.table is None, "kullanıcı metninde onay yokken bayrak yetmez"
    tool2, ws2 = _tool(q, user_text=q + "\nyine de yükle, doğru tablo bu")
    r2 = tool2.validate_and_run({"url": URL, "purpose": "bakiye", "table_index": 0, "user_confirmed": True})
    assert r2.ok and ws2.table is not None and r2.artifacts["fitness"]["confirmed"] is True


def test_kapi_hesaplanamazsa_tablo_eski_davranisla_yuklenir(monkeypatch) -> None:
    tool, ws = _tool(f"{URL} sayfasındaki tabloyu yükle")
    monkeypatch.setattr(WebUrlTool, "_fitness", lambda self, q, t, l: (None, []))
    r = tool.validate_and_run({"url": URL, "purpose": "tablo", "table_index": 0})
    assert r.ok and ws.table is not None and "fitness" not in r.artifacts


# ------------------------------------------------------------------ ajan kancaları (sahte LLM)
class _P(BaseModel):
    table_index: int | None = None


class _LoaderTool(Tool):
    """web_url'in kapıdan geçmiş hâlini taklit eder: tablo + uygunluk artefaktı."""

    name = "web_url"
    description = "sahte"
    Params = _P

    def __init__(self, ws: AnalysisWorkspace, quality: list[str]) -> None:
        self.ws, self.quality = ws, quality

    def run(self, params: _P) -> ToolResult:
        df = pd.DataFrame({"donem": ["2025-01", "2025-08"], "bakiye": [100.0, 116.0]})
        self.ws.set_table(df, description="konut 2025")
        return ToolResult(content="TABLO YÜKLENDİ\ndonem bakiye\n2025-01 100\n2025-08 116", data=df,
                          artifacts={"fitness": {"decision": "partial", "reasons": ["ölçüm adı belirsiz"], "quality": self.quality,
                                                 "coverage": "konut_2025 — 2025–2025, monthly, 8 satır", "confirmed": False}})


class _LLM:
    model = "scripted"

    def __init__(self, turns):
        self.turns, self.n, self.messages = turns, 0, []

    def supports_native_tools(self):
        return True

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
        self.messages.append(list(messages))   # kopya: harness aynı listeye geri gönderme notu ekliyor
        t = self.turns[min(self.n, len(self.turns) - 1)]
        self.n += 1
        return t


def test_kapsam_beyani_cevabin_ilk_satirina_deterministik_girer() -> None:
    ws = AnalysisWorkspace()
    reg = ToolRegistry()
    reg.register(_LoaderTool(ws, ["kısmi yıl: 2025 için 8 ay var"]))
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="web_url", arguments={"table_index": 0})]),
                LLMResponse(content="2025'te bakiye 100'den 116'ya çıktı.")])
    agent = AnalyticsAgent(llm=llm, registry=reg, workspace=ws, max_steps=6, tool_gate=False)
    a = agent.ask("2025 konut kredisi bakiyesi yıllık büyüme?")
    first = a.text.splitlines()[0]
    assert first.startswith("(Veri: konut_2025 — 2025–2025, monthly, 8 satır")
    assert "UYARI: uygunluk kısmen — ölçüm adı belirsiz | kısmi yıl: 2025 için 8 ay var" in first
    assert "100'den 116'ya" in a.text and any(x.get("kind") == "fitness" for x in a.artifacts)


def test_on_kosul_satiri_soruya_eklenir_ve_izde_kalir() -> None:
    ws = AnalysisWorkspace()
    reg = ToolRegistry()
    reg.register(_LoaderTool(ws, []))
    llm = _LLM([LLMResponse(content="Tahmin üretmedim; 2025 verisi şöyle.")])
    agent = AnalyticsAgent(llm=llm, registry=reg, workspace=ws, max_steps=4, tool_gate=False)
    agent.ask("2026 konut kredisi bakiyesi tahminin ne?")
    user_msg = llm.messages[0][-1].content
    assert "ÖN-KOŞUL" in user_msg and "tahmin/öngörü istendi" in user_msg
    assert agent.last_preflight is not None and agent.last_preflight.flags
