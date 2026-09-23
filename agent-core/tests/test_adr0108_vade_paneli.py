"""ADR-0108: vade kovaları, kırılım paneli ve takip turunda tablonun korunması.

Gerçek `SilverLakehouse` adaptörü küçük bir DuckDB üzerinde: bir toplam, altı vade kovası, ikinci bir toplam, haftalık bir
oran ve aylık bir fiyat endeksi. Sayılar elle kurulmuştur; her beklenti kovaların toplamından ya da tanımdan çıkar.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.adapters.silver_lakehouse import SilverLakehouse  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.breakdown import LakehouseBreakdownPanelTool, resolve_group  # noqa: E402
from kkb_agent.tools.lakehouse import LakehouseQueryTool  # noqa: E402
from kkb_agent.tools.workspace_join import WorkspaceJoinTool  # noqa: E402
from tests.test_silver_lakehouse import DDL, _series  # noqa: E402

TOTAL = "bddk_monthly:520_Toplam"
OTHER = "bddk_monthly:524_Toplam"
RATE = "evds:TP.TEST.FAIZ"
CPI = "evds:TP.TEST.TUFE"
BUCKETS = {  # sonek → (etiket, aralık)
    "Vadesiz": ("Vadesiz", "[0,0]"), "BirAyaKadar": ("1 Aya Kadar", "(0,1]"), "BirAyUcAy": ("1-3 Ay Arası", "(1,3]"),
    "UcAyAltiAy": ("3-6 Ay Arası", "(3,6]"), "AltiAyBirYil": ("6-12 Ay Arası", "(6,12]"), "BirYil": ("1 Yıl Üzeri", "(12,inf)"),
}
MONTHS = [date(2020, 12, 31), date(2021, 1, 31), date(2021, 2, 28)]
# Ay başına kovalar: vadesiz, 1 aya kadar, 1-3, 3-6, 6-12, 1 yıl üzeri. Toplam = kovaların toplamı.
BUCKET_VALUES = {
    date(2020, 12, 31): [10, 20, 30, 5, 3, 2],
    date(2021, 1, 31): [12, 21, 33, 6, 3, 2],
    date(2021, 2, 28): [15, 25, 30, 8, 4, 3],
}


def _obs(con, sid, d, v, *, unit="TRY_mn", mt="stock", freq="monthly"):
    con.execute(
        "INSERT INTO silver.fact_observation VALUES (?,NULL,?,NULL,?,?,?,?,?,'ok',"
        "'src','ds','sha',now(),'v1','vin','run')",
        [sid, d, d, v, freq, unit, mt],
    )


@pytest.fixture
def lake(tmp_path: Path) -> SilverLakehouse:
    import duckdb
    db = tmp_path / "lh.duckdb"
    con = duckdb.connect(str(db))
    con.execute(DDL)
    con.execute("""CREATE TABLE meta.series_relation (series_id VARCHAR, concept_id VARCHAR, parent_series_id VARCHAR,
                   relation_type VARCHAR, dimension_path VARCHAR[], additivity VARCHAR, relation_confidence VARCHAR,
                   relation_source VARCHAR)""")
    table = "(Mevduat Vade İtibarıyla, Sektör)"
    _series(con, TOTAL, native_code="520?Toplam", name_tr=f"TP Mevduat {table}", aliases=["tp mevduat"])
    _series(con, OTHER, native_code="524?Toplam", name_tr=f"DTH {table}", aliases=["dth"])
    _series(con, RATE, source_id="evds", native_code="TP.TEST.FAIZ", name_tr="Test Faizi", unit="pct",
            measure_type="rate", default_agg="avg", frequency="weekly", week_anchor="friday", aliases=["faiz"])
    _series(con, CPI, source_id="evds", native_code="TP.TEST.TUFE", name_tr="Test TÜFE", unit="index",
            measure_type="index", default_agg="last", aliases=["tüfe"])
    con.execute("INSERT INTO meta.series_relation VALUES (?, 'c520', NULL, 'parent_total', [], 'additive', 'derived', 's')",
                [TOTAL])
    con.execute("INSERT INTO meta.series_relation VALUES (?, 'c524', NULL, 'standalone', [], 'unknown', 'derived', 's')",
                [OTHER])
    for index, (suffix, (label, interval)) in enumerate(BUCKETS.items()):
        sid = f"bddk_monthly:520_{suffix}"
        _series(con, sid, native_code=f"520?{suffix}", name_tr=f"TP Mevduat - {label} {table}", aliases=[f"tp {label}"])
        con.execute("INSERT INTO meta.series_relation VALUES (?, 'c520', ?, 'child_breakdown', ?, 'unknown', 'derived', 's')",
                    [sid, TOTAL, [f"vade={label}", f"vade_ay={interval}"]])
        for month, values in BUCKET_VALUES.items():
            _obs(con, sid, month, values[index])
    for month, values in BUCKET_VALUES.items():
        _obs(con, TOTAL, month, sum(values))
        _obs(con, OTHER, month, 1000 + month.month)
        _obs(con, CPI, month, {12: 100.0, 1: 110.0, 2: 121.0}[month.month], unit="index", mt="index")
    for day, value in ((date(2021, 1, 8), 10.0), (date(2021, 1, 15), 20.0), (date(2021, 2, 5), 30.0)):
        _obs(con, RATE, day, value, unit="pct", mt="rate", freq="weekly")
    con.close()
    return SilverLakehouse(db)


def _panel(lake, ws=None, question=""):
    registry = SimpleNamespace(active_question=question)
    return LakehouseBreakdownPanelTool(lake, ws or AnalysisWorkspace(), registry=registry)


def test_resolve_group_includes_vadesiz_and_widens_to_the_narrowest_covering_buckets() -> None:
    buckets = {f"b{i}": ("x", lo, hi) for i, (lo, hi) in enumerate(
        [(-1, 0), (0, 1), (1, 3), (3, 6), (6, 12), (12, float("inf"))])}
    up_to_3, note = resolve_group(buckets, None, 3)
    assert up_to_3 == ["b0", "b1", "b2"] and note is None            # Vadesiz dahil
    over_3, _ = resolve_group(buckets, 3, None)
    assert over_3 == ["b3", "b4", "b5"]
    five_years, note = resolve_group(buckets, 60, None)
    assert five_years == ["b5"] and "60 ay → 12 ay" in note           # 5 yıl → 1 Yıl Üzeri, söylenir
    two_months, note = resolve_group(buckets, None, 2)
    assert two_months == ["b0", "b1", "b2"] and "2 ay → 3 ay" in note


def test_panel_groups_buckets_and_turns_every_column_into_monthly_change_with_base_month(lake) -> None:
    r = _panel(lake).validate_and_run({
        "series": [{"series_id": TOTAL, "column_name": "tp"}, {"series_id": OTHER, "column_name": "yp"}],
        "groups": [{"total_series_id": TOTAL, "column_name": "tp_3aya_kadar", "max_months": 3},
                   {"total_series_id": TOTAL, "column_name": "tp_3aydan_fazla", "min_months": 3}],
        "period_from": "2021-01", "period_to": "2021-02", "value": "monthly_change", "purpose": "t"})
    assert r.ok, r.content
    t = r.data
    assert list(t.columns) == ["donem", "tp", "yp", "tp_3aya_kadar", "tp_3aydan_fazla"] and len(t) == 2
    # Ocak hareketi Aralık tabanıyla: ≤3 = (12+21+33) − (10+20+30) = 6; >3 = (6+3+2) − (5+3+2) = 1; toplam 77 − 70 = 7;
    # YP 1001 − 1012 = −11 (değer 1000 + ay numarası).
    assert t.iloc[0][["tp", "tp_3aya_kadar", "tp_3aydan_fazla", "yp"]].tolist() == [7, 6, 1, -11]
    assert t.iloc[1][["tp", "tp_3aya_kadar", "tp_3aydan_fazla"]].tolist() == [8, 4, 4]
    assert "Vadesiz + 1 Aya Kadar + 1-3 Ay Arası" in r.content and "TABAN AYI: 2020-12" in r.content
    assert "±3 dışında kalan ay: 0" in r.content and "STOK DEĞİL" in r.content


def test_panel_refuses_level_when_the_user_asked_for_monthly_movement(lake) -> None:
    r = _panel(lake, question="Her satır o aydaki değişimi versin, stok olmasın.").validate_and_run({
        "series": [{"series_id": TOTAL, "column_name": "tp"}], "period_from": "2021-01", "period_to": "2021-02",
        "value": "level", "purpose": "t"})
    assert not r.ok and r.error.error_code == "INVALID_ARGS" and "monthly_change" in r.content


def test_panel_reduces_weekly_rate_to_monthly_mean_and_joins_session_table_with_real_and_index(lake) -> None:
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"period_month": ["2021-01", "2021-02"], "İşlem Hacmi (TL)": [110.0, 242.0],
                               "Günlük Ortalama İşlem Hacmi (TL)": [22.0, 48.4]}), description="yüklenen dosya")
    r = _panel(lake, ws).validate_and_run({
        "series": [{"series_id": TOTAL, "column_name": "tp"}, {"series_id": RATE, "column_name": "faiz"},
                   {"series_id": CPI, "column_name": "tufe"}],
        "period_from": "2021-01", "period_to": "2021-02", "join_session": True, "deflator_series_id": CPI,
        "base_period": "2021-02", "index_base": "2021-01", "purpose": "t"})
    assert r.ok, r.content
    t = r.data.set_index(r.data["donem"].dt.strftime("%Y-%m"))
    assert t.loc["2021-01", "faiz"] == 15.0 and t.loc["2021-02", "faiz"] == 30.0          # haftalık → aylık ortalama
    assert "Günlük Ortalama İşlem Hacmi (TL)" not in t.columns                              # ortalama eklenmez
    assert t.loc["2021-01", "İşlem Hacmi (TL)_reel"] == pytest.approx(110.0 * 121.0 / 110.0)  # reel, 2021-02 fiyatlarıyla
    assert t.loc["2021-02", "İşlem Hacmi (TL)_reel"] == pytest.approx(242.0)
    assert t.loc["2021-01", "tp_endeks"] == 100 and t.loc["2021-02", "tp_endeks"] == pytest.approx(85 / 77 * 100)
    assert "faiz_endeks" not in t.columns and "tufe_endeks" not in t.columns               # oran ve endeks endekslenmez


def test_manual_sql_sum_of_maturity_buckets_is_refused_and_redirected(lake) -> None:
    registry = SimpleNamespace(get=lambda name: object() if name == "lakehouse_breakdown_panel" else None,
                               active_question="")
    r = LakehouseQueryTool(lake, AnalysisWorkspace(), registry).validate_and_run({
        "sql": "SELECT observation_date, sum(value) FROM silver.fact_observation WHERE series_id IN "
               "('bddk_monthly:520_BirAyaKadar','bddk_monthly:520_BirAyUcAy') AND observation_date BETWEEN "
               "'2021-01-01' AND '2021-02-28' GROUP BY 1", "purpose": "t"})
    assert not r.ok and "vade kovasını elle birleştiriyor" in r.content and "lakehouse_breakdown_panel" in r.content


def test_join_month_policy_matches_different_month_spellings() -> None:
    from kkb_agent.tools.workspace_join import JoinParams
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"donem": pd.to_datetime(["2022-05-31", "2022-06-30"]), "a": [1.0, 2.0]}), description="a")
    ws.set_table(pd.DataFrame({"donem": ["202205", "2022-06"], "b": [10.0, 20.0]}), description="b")
    r = WorkspaceJoinTool(ws).run(JoinParams(left="k1", right="k2", left_key="donem", key_policy="ay", purpose="x"))
    assert r.ok, r.content
    assert ws.table["b"].tolist() == [10.0, 20.0]


def test_table_from_previous_turn_is_protected_but_tables_built_this_turn_are_not() -> None:
    from kkb_agent.core.agent import AnalyticsAgent
    from kkb_agent.core.registry import ToolRegistry

    agent = AnalyticsAgent(llm=SimpleNamespace(model="x", supports_native_tools=lambda: True), registry=ToolRegistry(),
                           workspace=AnalysisWorkspace(), max_steps=4)
    agent.workspace.set_table(pd.DataFrame({"donem": ["2021-01"], "tp": [1.0]}), description="önceki tur")
    agent._turn_start_generation = agent.workspace.generation
    call = SimpleNamespace(name="gold_join", arguments={})
    question = "TÜFE'yi getir, mevcut veri setiyle hizala ve reel hale getir."
    assert agent._table_rebuild_blocked(call, question) is not None
    assert agent._table_rebuild_blocked(SimpleNamespace(name="lakehouse_query", arguments={"as_active_table": False}),
                                        question) is None
    agent.workspace.set_table(pd.DataFrame({"donem": ["2021-01"], "x": [1.0]}), description="bu turda okundu")
    assert agent._table_rebuild_blocked(call, question) is None


def test_multi_source_join_question_gets_wider_limits_and_session_tables_note() -> None:
    from kkb_agent.core.agent import AnalyticsAgent
    from kkb_agent.core.registry import ToolRegistry

    agent = AnalyticsAgent(llm=SimpleNamespace(model="x", supports_native_tools=lambda: True), registry=ToolRegistry(),
                           workspace=AnalysisWorkspace(), max_steps=4)
    question = "BDDK kredilerini EVDS kuru ve TÜİK enflasyonuyla ay ay birleştir."
    assert agent._multi_source_scale(question) == 8
    assert agent._multi_source_scale("BDDK konut kredisini getir.") == 0
    assert agent._session_sources_note(question) is None                      # tek tablo yokken not yok
    agent.workspace.set_table(pd.DataFrame({"donem": ["2021-01"], "tp": [1.0]}), description="mevduat")
    agent.workspace.set_table(pd.DataFrame({"period_month": ["2021-01"], "hacim": [2.0]}), description="dosya")
    note = agent._session_sources_note(question)
    assert note is not None and "k1" in note and "k2" in note and "key_policy='ay'" in note


def test_group_total_is_added_when_the_model_forgets_it(lake) -> None:
    """23 Eyl senaryo koşusu: model grupları istedi, toplamı series'e koymadı; tablo toplamsız kaldı."""
    r = _panel(lake).validate_and_run({
        "series": [{"series_id": OTHER, "column_name": "yp"}],
        "groups": [{"total_series_id": TOTAL, "column_name": "tp_3aya_kadar", "max_months": 3},
                   {"total_series_id": TOTAL, "column_name": "tp_3aydan_fazla", "min_months": 3}],
        "period_from": "2021-01", "period_to": "2021-02", "value": "monthly_change", "purpose": "t"})
    assert r.ok, r.content
    assert list(r.data.columns) == ["donem", "yp", "tp_toplam", "tp_3aya_kadar", "tp_3aydan_fazla"]
    assert r.data["tp_toplam"].tolist() == [7, 8]


def test_period_parser_skips_list_cells_of_gold_evidence_columns() -> None:
    import numpy as np
    from kkb_agent.builder.temporal import infer_temporal, parse_period
    assert parse_period(np.array(["2022-05-31", "2022-06-30"])) is None and parse_period(["2021-01"]) is None
    frame = pd.DataFrame({"period_end": pd.to_datetime(["2022-05-31", "2022-06-30"]),
                          "x::source_observation_dates": [np.array(["2021-01-08"]), np.array(["2021-02-05"])]})
    assert infer_temporal(frame).period_column == "period_end"


def test_real_value_request_is_a_requested_capability() -> None:
    from kkb_agent.core.agent import _REQUESTED_CAPABILITIES
    real = next(cap for cap in _REQUESTED_CAPABILITIES if cap[0] == "reel")
    assert real[1].search("kredi bakiyesini 2024-06 fiyatlarıyla göster")
    assert "workspace_real_value" in real[2] and not real[1].search("konut kredisi stokunu getir")


def test_join_does_not_carry_gold_evidence_columns_by_default() -> None:
    from kkb_agent.tools.workspace_join import JoinParams
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"donem": ["2021-01"], "a": [1.0]}), description="a")
    ws.set_table(pd.DataFrame({"donem": ["2021-01"], "x::value": [2.0], "x::quality_flag": ["ok"],
                               "x::source_observation_dates": [["2021-01-08"]], "is_complete_period": [True]}),
                 description="gold")
    r = WorkspaceJoinTool(ws).run(JoinParams(left="k1", right="k2", left_key="donem", purpose="x"))
    assert r.ok, r.content
    assert list(ws.table.columns) == ["donem", "a", "x::value"]


def test_rebuilding_follow_up_carries_the_previous_turn_table_by_month() -> None:
    """23 Eyl senaryo koşusu: "mevcut mevduat veri setiyle hizala" takibinde faiz/kur tablosu mevduat tablosunu düşürdü.
    Yeniden kuran araç artık çalışır ve önceki tur tablosu ay üzerinden yeni tabloya taşınır."""
    from kkb_agent.core.agent import AnalyticsAgent
    from kkb_agent.core.registry import ToolRegistry

    agent = AnalyticsAgent(llm=SimpleNamespace(model="x", supports_native_tools=lambda: True), registry=ToolRegistry(),
                           workspace=AnalysisWorkspace(), max_steps=4)
    prior = pd.DataFrame({"donem": pd.to_datetime(["2022-05-31", "2022-06-30"]), "tp": [7.0, 8.0]})
    agent.workspace.set_table(pd.DataFrame({"period_end": pd.to_datetime(["2022-05-31", "2022-06-30"]),
                                            "faiz::value": [17.5, 18.0], "faiz::quality_flag": ["ok", "ok"]}),
                              description="faiz")
    note = agent._carry_prior_table(prior)
    assert note and "1 sütun" in note
    assert agent.workspace.table["tp"].tolist() == [7.0, 8.0] and "faiz::value" in agent.workspace.table.columns
    assert agent._KEEP_TABLE_ASK.search("kuru mevcut kredi veri setine ekle")


def test_only_edge_months_are_reported_as_partial() -> None:
    from kkb_agent.builder.temporal import normalize_frequency
    frame = pd.DataFrame({"period": ["2021/02 (11.01.21-15.01.21)", "2021/05 (01.02.21-05.02.21)",
                                     "2021/13 (29.03.21-02.04.21)", "2021/14 (05.04.21-09.04.21)"],
                          "hacim": [1.0, 2.0, 3.0, 4.0]})
    result = normalize_frequency(frame, requested="monthly", requested_columns=["hacim"])
    warnings = " ".join(result.metadata.warnings)
    assert "2021-01" in warnings and "2021-03" not in warnings        # ilk ay 11'inde başladı; Mart eksik değil


def test_breakpoint_interpretation_requires_web_research() -> None:
    from kkb_agent.core.agent import _REQUESTED_CAPABILITIES
    web = next(cap for cap in _REQUESTED_CAPABILITIES if cap[0] == "web araştırması")
    assert web[1].search("serideki kırılma noktalarını bul ve yorumla") and "web_search" in web[2]
