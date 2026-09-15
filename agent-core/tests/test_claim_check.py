"""İddia–hücre (G5) ve aralık beyanı (G6) — core/claim_check.py (V3 §3.9): sayı doğru dönemle mi? Ajan kancası sahte LLM ile."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.agent import AnalyticsAgent  # noqa: E402
from kkb_agent.core.claim_check import claim_cell, range_claim  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.tool import Tool, ToolResult  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.llm.base import LLMResponse, ToolCall  # noqa: E402

MONTHS = pd.date_range("2025-01-31", "2025-12-31", freq="ME")
TABLE = pd.DataFrame({"donem": MONTHS, "toplam": [512259.0 + i * 15000 for i in range(12)]})   # Ekim = 647.259, Aralık = 677.259
EKIM, ARALIK = "647.259", "677.259"


def test_tablo_satirinda_yanlis_hucre_yakalanir_dogru_hucre_gecer() -> None:
    bad = f"| Aralık 2025 | {EKIM} |"
    assert claim_cell(bad, [TABLE]) == [f"'{EKIM}' satırda 2025-12 ile yan yana; tabloda bu değer 2025-10 döneminde"]
    assert claim_cell(f"| Aralık 2025 | {ARALIK} |", [TABLE]) == []
    assert claim_cell(f"| 2025-10-31 | {EKIM} |", [TABLE]) == []


def test_duz_yazida_tek_donem_tek_sayi_kurali_ve_turkce_sira() -> None:
    assert claim_cell(f"2025 Aralık ayında bakiye {EKIM} milyon TL oldu.", [TABLE]) != []
    assert claim_cell(f"Aralık 2025'te bakiye {ARALIK} milyon TL.", [TABLE]) == []
    # İki dönem + iki sayı bir cümlede (A15/D05 yanlış pozitif kaynağı): karar verilmez.
    assert claim_cell(f"Ocak 2025'te 512.259, Aralık 2025'te {EKIM}.", [TABLE]) == []
    # Tabloda hiç olmayan sayı grounding'in işi: karışılmaz.
    assert claim_cell("Aralık 2025: 999.999", [TABLE]) == []
    # Yıl ve küçük sayılar sayılmaz; tarih kolonu olmayan tablo indekslenmez.
    assert claim_cell("Aralık 2025: 12", [TABLE]) == [] and claim_cell(f"Aralık 2025: {EKIM}", [pd.DataFrame({"a": [1.0]})]) == []


def test_aralik_beyani_yalniz_kapsam_satirinda_ve_uyusmazsa() -> None:
    assert range_claim("Veri kapsamı 2025-01 → 2025-10.", [TABLE]) == ["aralık beyanı '2025-01 → 2025-10' ≠ tablo 2025-01→2025-12"]
    assert range_claim("Veri kapsamı 2025-01 → 2025-12.", [TABLE]) == []
    assert range_claim("Tablo Ocak–Ekim 2025 dönemini kapsıyor.", [TABLE]) != []
    assert range_claim("Ocak–Ekim 2025 arasında yükseldi.", [TABLE]) == [], "kapsam sözcüğü yoksa aranmaz"
    assert range_claim("Veri: Ocak 2025 – Aralık 2025.", [TABLE]) == []


# ------------------------------------------------------------------ ajan kancası
class _P(BaseModel):
    year: int = 2025


class _Q(Tool):
    name = "lakehouse_query"
    description = "sahte"
    Params = _P

    def __init__(self, ws: AnalysisWorkspace) -> None:
        self.ws = ws

    def run(self, params: _P) -> ToolResult:
        self.ws.set_table(TABLE, description="konut 2025")
        # Kart tam tabloyu taşır (core/preview: ≤24 satır tamamı); yanlış hücre grounding'i geçer, iddia–hücre yakalar.
        return ToolResult(content="12 satır.\n" + TABLE.to_string(index=False), data=TABLE)


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


def _agent(turns):
    ws = AnalysisWorkspace()
    reg = ToolRegistry()
    reg.register(_Q(ws))
    llm = _LLM(turns)
    return AnalyticsAgent(llm=llm, registry=reg, workspace=ws, max_steps=8, tool_gate=False), llm


def test_yanlis_hucre_bir_kez_geri_gonderilir_duzelince_gecer() -> None:
    agent, llm = _agent([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="lakehouse_query", arguments={})]),
        LLMResponse(content=f"| Aralık 2025 | {EKIM} |"),
        LLMResponse(content=f"| Aralık 2025 | {ARALIK} |"),
    ])
    a = agent.ask("2025 Aralık konut kredisi bakiyesi?")
    assert a.text.strip() == f"| Aralık 2025 | {ARALIK} |" and "(Not:" not in a.text
    assert "dönem–sayı eşleşmesi tabloyla çelişiyor" in llm.messages[2][-1].content
    assert any("CELL:" in (s.thought or "") for s in a.steps)


def test_israr_edilirse_deterministik_not_eklenir() -> None:
    agent, _ = _agent([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="lakehouse_query", arguments={})]),
        LLMResponse(content=f"| Aralık 2025 | {EKIM} |"),
    ])
    a = agent.ask("2025 Aralık konut kredisi bakiyesi?")
    assert "(Not: cevaptaki dönem etiketi tabloyla uyuşmuyor" in a.text and EKIM in a.text
    assert a.grounding.startswith("OK | CELL:")
