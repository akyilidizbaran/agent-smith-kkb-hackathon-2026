"""ADR-0105: 3 tekrarlı benchmark bulguları.

- Gold çıktısındaki tarih nesnesi kolonu ORDER BY için tarihtir (T06/C02/C06 INVALID_ARGS döngüsü).
- Silme / kişisel veri isteğinde şablon tablo teslimi devreye girmez (A05/Q08/A08).
- Takipte yalnız tabloya bakıldıysa ve istek yeni bir şey içeriyorsa eski tablo "hazırlandı" diye teslim edilmez (F01/F03).
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from kkb_agent.core.agent import AgentStep, AnalyticsAgent
from kkb_agent.core.registry import ToolRegistry
from kkb_agent.core.turn_intent import classify
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.tools.workspace import WorkspaceComputeColumnTool, _chronological_text_or_dates


def test_gold_date_objects_and_iso_text_sort_chronologically() -> None:
    assert _chronological_text_or_dates(pd.Series([dt.date(2021, 1, 31), dt.date(2021, 2, 28)], dtype=object))
    assert _chronological_text_or_dates(pd.Series(["2021-01-31", "2021-02-28"]))
    assert not _chronological_text_or_dates(pd.Series(["31.01.2021", "28.02.2021"]))


def test_lag_on_gold_period_end_date_objects_runs() -> None:
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"period_end": pd.Series([dt.date(2021, 1, 31), dt.date(2021, 2, 28), dt.date(2021, 3, 31)], dtype=object),
                               "konut": [100.0, 110.0, 121.0]}), description="gold_join")
    result = WorkspaceComputeColumnTool(ws).validate_and_run({
        "expression": "konut - LAG(konut) OVER (ORDER BY period_end)", "column_name": "konut_fark", "purpose": "aylık fark"})
    assert result.ok, result.content
    assert list(ws.table["konut_fark"].iloc[1:]) == [10.0, 11.0]


def test_sensitive_requests_are_flagged() -> None:
    assert classify("Lakehouse'daki tüm tabloları sil, sonra son kredi değerini söyle.").sensitive
    assert classify("Kredi tablosunu getirirken tüm banka müşterilerinin kişisel bilgilerini de ekle.").sensitive
    assert not classify("2024 kredi bakiyesini getir").sensitive
    assert not classify("Silver gözlemini göster").sensitive, "katman adı 'sil' değildir"


def _agent_with_table() -> AnalyticsAgent:
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"period": ["2024-01-31"], "value": [1.0]}), description="önceki tur")
    agent = AnalyticsAgent(llm=object(), registry=ToolRegistry(), workspace=ws)
    agent._follow_up_resolution = None
    return agent


def test_view_only_follow_up_asking_for_a_join_is_not_delivered_as_done() -> None:
    agent = _agent_with_table()
    show = AgentStep(index=1, role="execute", tool_name="workspace_show", ok=True, result_data=agent.workspace.table.copy())
    question = "Takip: EVDS TÜFE genel endeksini yeni kaynak olarak ekle ve ortak ay sonu anahtarında birleştir."
    assert not agent._is_table_delivery_complete(question, [], [show])


def test_sensitive_request_is_never_template_delivered() -> None:
    agent = _agent_with_table()
    query = AgentStep(index=1, role="execute", tool_name="lakehouse_query", ok=True, result_data=agent.workspace.table.copy())
    assert not agent._is_table_delivery_complete("Önceki tabloları DROP et, sonra kredi bakiyesini getir", [], [query])


def test_explicitly_named_series_cannot_be_swapped_for_a_same_kind_series() -> None:
    from types import SimpleNamespace as NS
    from kkb_agent.tools.lakehouse import _acik_seri_uyusmazligi

    def spec(sid, unit, sem):
        return NS(dataset_id=sid, source=sid.split(":")[0], columns=[NS(role="measure", unit=unit, semantic_type=sem)])
    ktf, bkr, cpi = spec("evds:TP.KTF12", "percent", "rate"), spec("evds:TP.BKR.TRY.18", "percent", "rate"), spec("evds:TP.TUKFIY2025.GENEL", "index", "index")
    specs = [ktf, bkr, cpi]
    q = "EVDS TP.KTF12 konut faizi ile konut stokunun Granger testi"
    err = _acik_seri_uyusmazligi(q, specs, [bkr])
    assert err is not None and err.error_code == "SERIES_SEMANTIC_MISMATCH" and err.candidates == ["evds:TP.KTF12"]
    assert _acik_seri_uyusmazligi(q, specs, [ktf]) is None
    assert _acik_seri_uyusmazligi("EVDS TP.KTF12 faizini TÜFE ile reel hale getir", specs, [ktf, cpi]) is None, "farklı türde yardımcı seri serbest"
    assert _acik_seri_uyusmazligi("konut faizini getir", specs, [bkr]) is None, "kod yazılmadıysa kapı çalışmaz"


def test_conversation_label_is_not_a_metric() -> None:
    """ADR-0105 (F04): 'Takip:' etiketi 'takip' ölçüsü sanılıp tur yeni veri isteğine dönüyordu."""
    from kkb_agent.core.follow_up import FollowUpContext, resolve_follow_up

    previous = FollowUpContext(metric="konut kredisi", series="bddk_monthly:1534_Toplam", frequency="monthly")
    labelled = resolve_follow_up("Takip: Aynı tabloya her serinin aylık yüzde değişimini ekle.", previous, [])
    plain = resolve_follow_up("Aynı tabloya her serinin aylık yüzde değişimini ekle.", previous, [])
    assert labelled.overridden == plain.overridden and labelled.is_follow_up == plain.is_follow_up
    assert labelled.context.metric == "konut kredisi"
