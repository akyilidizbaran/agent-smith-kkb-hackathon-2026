"""V3 döngüsü, sahte LLM ile: paralel çağrı, güvenli başarısızlık, grounding, yükseltme."""

from __future__ import annotations

from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.llm.base import LLMResponse
from kkb_agent_v3.core.agent import AgentConfig, V3Agent
from kkb_agent_v3.core.validator import ToolRegistry
from kkb_agent_v3.tools.lakehouse import LakehouseDescribeTool, LakehouseQueryTool
from kkb_agent_v3.tools.workspace import workspace_tools

from .conftest import FakeLLM, StubLakehouse, call, final, tool_turn

SQL_2025 = "SELECT donem, toplam FROM test_krediler WHERE EXTRACT(year FROM donem) = 2025"


def _agent(lh: StubLakehouse, responses: list[LLMResponse], **cfg) -> tuple[V3Agent, FakeLLM]:
    ws = AnalysisWorkspace()
    reg = ToolRegistry()
    reg.register_all([LakehouseDescribeTool(lh), LakehouseQueryTool(lh, ws, reg), *workspace_tools(lh, ws)])
    llm = FakeLLM(responses)
    return V3Agent(llm, reg, workspace=ws, config=AgentConfig(**cfg)), llm


def test_ayni_turda_iki_cagri_paralel_ve_sirali_doner(lakehouse: StubLakehouse) -> None:
    agent, llm = _agent(lakehouse, [
        tool_turn(call("lakehouse_describe", 1, dataset_id="test_krediler"),
                  call("lakehouse_query", 2, sql=SQL_2025, purpose="aylık")),
        final("2025'te toplam 100 ve 110 milyon TL."),
    ])
    ans = agent.ask("2025 aylık")
    tool_steps = [s for s in ans.steps if s.tool_name]
    assert [s.tool_name for s in tool_steps] == ["lakehouse_describe", "lakehouse_query"]
    assert all(s.ok for s in tool_steps) and ans.extra["llm_turns"] == 2
    # tool mesajları modelin verdiği sırayla ve doğru id ile döner
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["c1", "c2"]
    assert ans.extra["grounding"] == "OK"
    # Üretim tavanı her turda gönderilir (11 Eylül: tavansız cevap turu 103 s sürdü)
    assert all(c["max_tokens"] == 700 for c in llm.calls)


def test_retry_edilemez_hata_aracsiz_cevap_turu(lakehouse: StubLakehouse) -> None:
    agent, llm = _agent(lakehouse, [
        tool_turn(call("lakehouse_query", 1, sql="SELECT * FROM test_krediler WHERE EXTRACT(year FROM donem)=2015", purpose="x")),
        final("2015 verisi yok; elde 2021-2026 var."),
    ], nudge_if_no_data=False)
    ans = agent.ask("2015 bakiye")
    assert ans.extra["error_codes"] == ["OUT_OF_COVERAGE"]
    assert llm.calls[1]["tools"] is None          # güvenli başarısızlık: araçsız tur
    assert "2021" in ans.text and not ans.workspace.has_table


def test_grounding_enforce_bir_kez_yeniden_uretir(lakehouse: StubLakehouse) -> None:
    agent, llm = _agent(lakehouse, [
        tool_turn(call("lakehouse_query", 1, sql=SQL_2025, purpose="aylık")),
        final("Bakiye 45 milyon TL arttı."),        # 45 araç çıktısında yok (≤31 kontrol dışı)
        final("Bakiye 100'den 110 milyon TL'ye çıktı."),
    ])
    ans = agent.ask("2025 değişim")
    assert ans.extra["llm_turns"] == 3
    assert ans.text.startswith("Bakiye 100")
    assert any("araç çıktısında yok" in m.content for m in llm.calls[2]["messages"] if m.role == "user")
    assert ans.extra["grounding"] == "OK"


def test_grounding_shadow_sadece_olcer(lakehouse: StubLakehouse) -> None:
    agent, _ = _agent(lakehouse, [
        tool_turn(call("lakehouse_query", 1, sql=SQL_2025, purpose="aylık")),
        final("Bakiye 45 milyon TL arttı."),
    ], grounding="shadow")
    ans = agent.ask("2025 değişim")
    assert ans.extra["llm_turns"] == 2 and ans.extra["grounding"].startswith("MISS:45")


def test_grounding_ingiliz_ondalik_turkce_binlik_karismaz() -> None:
    """pandas '1.357539' ondalıktır, model '678.970' binliktir; ikisi de doğru havuza girmeli."""
    from kkb_agent_v3.core.grounding import grounding_check, numbers_in

    assert numbers_in("1.357539 31.965387 678970.0 12.5") == [1.357539, 31.965387, 678970.0, 12.5]
    assert numbers_in("678.970 milyon, 1.234.567,25 ve %1,36") == [678970.0, 1234567.25, 1.36]
    pool = ["donem toplam degisim\n2025-01-31 678970.0 1.357539\n2025-02-28 700000.0 31.965387"]
    assert grounding_check("2025", "Bakiye 678.970 milyon TL; aylık %1,36, yıllık %32 arttı.", pool) == "OK"
    assert grounding_check("2025", "Aylık %2,5 arttı.", pool).startswith("MISS:2,5")


def test_kucuk_tam_sayilar_ve_yillar_kontrol_disi(lakehouse: StubLakehouse) -> None:
    agent, _ = _agent(lakehouse, [
        tool_turn(call("lakehouse_query", 1, sql=SQL_2025, purpose="aylık")),
        final("2025'in ilk 2 ayında bakiye 100'den 110'a çıktı."),
    ])
    ans = agent.ask("2025 değişim")
    assert ans.extra["llm_turns"] == 2 and ans.extra["grounding"] == "OK"


def test_nedensellik_dili_yeniden_uretim(lakehouse: StubLakehouse) -> None:
    agent, _ = _agent(lakehouse, [
        tool_turn(call("lakehouse_query", 1, sql=SQL_2025, purpose="aylık")),
        final("Faiz düşüşü bakiyenin 110 olmasına yol açtı."),
        final("Faiz düşüşü ve bakiyenin 110'a çıkışı birlikte hareket etti."),
    ])
    ans = agent.ask("2025")
    assert "birlikte hareket" in ans.text and ans.extra["llm_turns"] == 3


def test_iki_ardisik_hata_reasoning_yukseltir(lakehouse: StubLakehouse) -> None:
    agent, llm = _agent(lakehouse, [
        tool_turn(call("lakehouse_describe", 1, dataset_id="yok1")),
        tool_turn(call("lakehouse_describe", 2, dataset_id="yok2")),
        tool_turn(call("lakehouse_query", 3, sql=SQL_2025, purpose="aylık")),
        final("100 ve 110."),
    ])
    ans = agent.ask("2025")
    assert llm.calls[0]["extra"] is None and llm.calls[1]["extra"] is None
    assert llm.calls[2]["extra"] == {"reasoning_effort": "low"}
    assert ans.extra["error_codes"] == ["SERIES_NOT_FOUND", "SERIES_NOT_FOUND"]


def test_arac_basina_onarim_limiti(lakehouse: StubLakehouse) -> None:
    bad = lambda i: tool_turn(call("lakehouse_describe", i, dataset_id=f"yok{i}"))  # noqa: E731
    agent, llm = _agent(lakehouse, [bad(1), bad(2), bad(3), final("Bulamadım.")], nudge_if_no_data=False, escalate=False)
    ans = agent.ask("x")
    assert len(ans.extra["error_codes"]) == 3
    assert llm.calls[3]["tools"] is None and not ans.hit_step_limit


def test_veri_cekmeden_cevap_geri_gonderilir(lakehouse: StubLakehouse) -> None:
    agent, llm = _agent(lakehouse, [
        final("Katalogda konut var."),
        tool_turn(call("lakehouse_query", 1, sql=SQL_2025, purpose="aylık")),
        final("100, 110."),
    ])
    ans = agent.ask("2025")
    assert ans.extra["llm_turns"] == 3 and ans.workspace.has_table


def test_ayni_cagri_tekrari_calistirilmaz_ve_kilitlenir(lakehouse: StubLakehouse) -> None:
    same = lambda i: tool_turn(call("lakehouse_query", i, sql=SQL_2025, purpose="aylık"))  # noqa: E731
    agent, llm = _agent(lakehouse, [same(1), same(2), same(3), final("100 ve 110.")], grounding="off")
    ans = agent.ask("2025")
    assert len(lakehouse.calls) == 1                          # sorgu yalnız bir kez çalıştı
    assert ans.extra["error_codes"] == ["DUPLICATE_CALL", "DUPLICATE_CALL"]
    assert llm.calls[3]["tools"] is None                      # ikinci tekrarda araçsız cevap turu
    assert ans.text == "100 ve 110." and not ans.hit_step_limit


def test_xml_tool_call_fallback(lakehouse: StubLakehouse) -> None:
    xml = '<tool_call>{"name": "lakehouse_query", "arguments": {"sql": "%s", "purpose": "p"}}</tool_call>' % SQL_2025
    agent, _ = _agent(lakehouse, [LLMResponse(content=xml), final("100, 110.")])
    ans = agent.ask("2025")
    assert ans.workspace.has_table and ans.steps[0].tool_name == "lakehouse_query"


def test_tur_limiti_kismi_cevap(lakehouse: StubLakehouse) -> None:
    turns = [tool_turn(call("lakehouse_query", i, sql=SQL_2025, purpose="p")) for i in range(2)]
    agent, _ = _agent(lakehouse, turns + [final("Kısmi.")], max_turns=2, grounding="off")
    ans = agent.ask("2025")
    assert ans.hit_step_limit and ans.text == "Kısmi." and ans.extra["llm_turns"] == 3
