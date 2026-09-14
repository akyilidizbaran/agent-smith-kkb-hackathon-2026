"""K03 hedefli canlı tekrar bulgusu (14 Eyl): birleştirme istenen turda model workspace_join'i çağırmadan anahtar eşleşmesini
tahminle anlattı ("birebir yalnız Adana tutar, İzmir vs Izmir"; ikisi de yanlıştı). Böyle bir cevap bir kez geri gönderilir."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kkb_agent.core.agent import JOIN_NOTE  # noqa: E402
from kkb_agent.llm.base import LLMResponse  # noqa: E402
from test_agent_loop import _agent, _ScriptedLLM  # noqa: E402


class _SeeingLLM(_ScriptedLLM):
    def __init__(self, turns):
        super().__init__(turns)
        self.users: list[list[str]] = []

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
        self.users.append([m.content for m in messages if m.role == "user"])
        return super().chat(messages, tools=tools, temperature=temperature, max_tokens=max_tokens)


GUESS = "Birleştirmede sorun var: il adları farklı yazılmış, birebir eşleşme yalnızca Adana'da tutar. Eşleştireyim mi?"


def _two_tables(agent) -> None:
    agent.workspace.set_table(pd.DataFrame({"il_adi": ["ankara", "ADANA"], "nufus_bin": [5864, 2274]}), description="nüfus")
    agent.workspace.set_table(pd.DataFrame({"il": ["Adana", "Ankara"], "hastane_sayisi": [41, 96]}), description="hastane")


def test_join_cagrilmadan_eslesme_anlatisi_bir_kez_geri_gonderilir() -> None:
    llm = _SeeingLLM([LLMResponse(content=GUESS), LLMResponse(content="Birleştirmeyi araçla denemedim; hangi kolonla birleştireyim?")])
    agent, _ = _agent(llm)
    _two_tables(agent)
    ans = agent.ask("Hastane tablosunu nüfus tablosuyla il üzerinden birleştir.")
    assert any(JOIN_NOTE in u for u in llm.users[-1]), "not modele gitti"
    assert any(s.role == "validate" and "workspace_join çağrılmadan" in (s.thought or "") for s in ans.steps)
    assert ans.text.startswith("Birleştirmeyi araçla denemedim")


def test_tek_tablo_ya_da_birlestirme_istenmeyen_turda_kapi_yok() -> None:
    llm = _SeeingLLM([LLMResponse(content=GUESS)])
    agent, _ = _agent(llm)
    agent.workspace.set_table(pd.DataFrame({"il": ["Adana"], "hastane_sayisi": [41]}), description="hastane")
    agent.ask("Hastane tablosunu nüfus tablosuyla il üzerinden birleştir.")
    assert not any(JOIN_NOTE in u for batch in llm.users for u in batch), "tek tabloda birleştirme kapısı açılmaz"

    llm2 = _SeeingLLM([LLMResponse(content="Adana ve Ankara adları iki tabloda farklı biçimde yazılmış.")])
    agent2, _ = _agent(llm2)
    _two_tables(agent2)
    agent2.ask("İki tablodaki il adlarını karşılaştır.")
    assert not any(JOIN_NOTE in u for batch in llm2.users for u in batch), "birleştirme istenmedi"
