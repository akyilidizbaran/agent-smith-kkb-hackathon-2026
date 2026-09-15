"""clarify (tools/clarify.py, V3 §3.9): yalnız uygunluk 'kısmen' + ölçüm/alt küme belirsizliğinde, tur başına bir kez;
ajan kancası turu soruyla bitirir; sonraki tur bekleyen soru mekanizmasına bağlanır. Sahte LLM, ağ yok."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.agent import AnalyticsAgent  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.tool import Tool, ToolResult  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.llm.base import LLMResponse, ToolCall  # noqa: E402
from kkb_agent.tools.clarify import ClarifyTool  # noqa: E402

ARGS = {"question": "Hangi kolon konut kredisi bakiyesi", "options": ["deger", "tutar_tl"], "why": "İki sayısal kolon var; seçim sonucu değiştirir."}


def _partial(turn: int, dims: dict) -> dict:
    return {"decision": "partial", "dims": dims, "reasons": ["ölçüm adı belirsiz"], "turn": turn}


def test_kapi_kapaliyken_reddeder_tur_bitmez() -> None:
    reg = SimpleNamespace(turn=1)
    r = ClarifyTool(reg).validate_and_run(ARGS)
    assert not r.ok and r.error.error_code == "CLARIFY_NOT_ALLOWED" and r.error.terminal is False and not r.error.is_retryable
    reg.last_fitness = {"decision": "accept", "dims": {"measure": "ok"}, "turn": 1}
    assert not ClarifyTool(reg).validate_and_run(ARGS).ok
    reg.last_fitness = _partial(1, {"measure": "n/a", "entity": "n/a"})   # "gereksinim çıkarılamadı": sayıyı değiştirmez → sorulmaz
    assert not ClarifyTool(reg).validate_and_run(ARGS).ok
    reg.last_fitness = _partial(0, {"measure": "partial"})                # önceki turun kararı bu tura izin vermez
    assert not ClarifyTool(reg).validate_and_run(ARGS).ok


def test_kismen_ve_olcum_belirsizken_sorar_soru_isaretiyle_biter_tur_basina_bir() -> None:
    reg = SimpleNamespace(turn=2, last_fitness=_partial(2, {"measure": "partial", "entity": "n/a"}))
    tool = ClarifyTool(reg)
    r = tool.validate_and_run(ARGS)
    assert r.ok and r.content.rstrip().endswith("?") and "- deger\n- tutar_tl" in r.content
    assert r.artifacts["clarify"]["question"] == "Hangi kolon konut kredisi bakiyesi?"
    again = tool.validate_and_run(ARGS)
    assert not again.ok and "zaten bir netleştirme soruldu" in again.content
    reg.turn = 3
    reg.last_fitness = _partial(3, {"entity": "partial"})
    assert tool.validate_and_run(ARGS).ok, "yeni turda yeniden sorulabilir"


# ------------------------------------------------------------------ ajan kancası
class _P(BaseModel):
    table_index: int | None = None


class _Loader(Tool):
    name = "web_url"
    description = "sahte"
    Params = _P

    def __init__(self, ws: AnalysisWorkspace, dims: dict) -> None:
        self.ws, self.dims = ws, dims

    def run(self, params: _P) -> ToolResult:
        df = pd.DataFrame({"donem": ["2024-01", "2024-12"], "deger": [100.0, 130.0]})
        self.ws.set_table(df, description="konut 2024")
        return ToolResult(content="TABLO YÜKLENDİ\ndonem deger\n2024-01 100\n2024-12 130\nuygunluk: kısmen — ölçüm adı belirsiz", data=df,
                          artifacts={"fitness": {"decision": "partial", "dims": self.dims, "reasons": ["ölçüm adı belirsiz"],
                                                 "coverage": "konut — 2024–2024, monthly, 2 satır", "quality": [], "confirmed": False}})


class _LLM:
    model = "scripted"

    def __init__(self, turns):
        self.turns, self.n, self.messages = turns, 0, []

    def supports_native_tools(self):
        return True

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
        self.messages.append(list(messages))
        t = self.turns[min(self.n, len(self.turns) - 1)]
        self.n += 1
        return t


def _agent(dims: dict, turns) -> tuple[AnalyticsAgent, _LLM]:
    ws = AnalysisWorkspace()
    reg = ToolRegistry()
    reg.register(_Loader(ws, dims))
    reg.register(ClarifyTool(reg))
    llm = _LLM(turns)
    return AnalyticsAgent(llm=llm, registry=reg, workspace=ws, max_steps=6, tool_gate=False), llm


def test_clarify_turu_bitirir_kapsam_satiri_basta_soru_sonda_model_yeniden_cagrilmaz() -> None:
    agent, llm = _agent({"measure": "partial"}, [
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="web_url", arguments={"table_index": 0})]),
        LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="clarify", arguments=ARGS)]),
        LLMResponse(content="BU CEVAP YAZILMAMALI 999.999"),
    ])
    a = agent.ask("Şu dosyadan 2024 konut kredisi bakiyesini göster: konut.csv")
    assert a.text.startswith("(Veri: konut — 2024–2024, monthly, 2 satır | UYARI: uygunluk kısmen")
    assert a.text.rstrip().endswith("Hangi kolon konut kredisi bakiyesi?") and "999.999" not in a.text
    assert llm.n == 2, "netleştirmeden sonra model çağrılmadı"
    assert any(x.get("kind") == "clarify" for x in a.artifacts) and a.steps[-1].tool_name == "clarify" and a.steps[-1].ok
    # Sonraki tur: kısa kullanıcı cevabı bekleyen soruya bağlanır (pending_question → CLARIFY_NOTE).
    llm.turns = [LLMResponse(content="deger kolonuyla: 100 → 130.")]
    agent.ask("deger")
    assert "Hangi kolon konut kredisi bakiyesi?" in llm.messages[-1][-1].content


def test_kapi_izin_vermezse_model_hata_alir_ve_cevabini_yazar() -> None:
    agent, llm = _agent({"measure": "n/a"}, [
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="web_url", arguments={"table_index": 0})]),
        LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="clarify", arguments=ARGS)]),
        LLMResponse(content="Uyarı: ölçüm adı belirsiz. 2024'te 100'den 130'a."),
    ])
    a = agent.ask("Şu dosyadan 2024 konut kredisi bakiyesini göster: konut.csv")
    codes = [s.error_code for s in a.steps if s.error_code]
    assert codes == ["CLARIFY_NOT_ALLOWED"] and "100'den 130'a" in a.text
    assert not a.hit_step_limit and llm.n == 3
