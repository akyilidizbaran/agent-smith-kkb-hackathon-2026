"""Answer-level result projection: full workspace stays available, output stays focused."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pandas as pd
from pytest import approx

from kkb_agent.contracts.lakehouse import QueryProvenance
from kkb_agent.core.agent import AgentAnswer, AgentStep
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.web_app import frame_to_dict, project_result_table, table_csv_bytes, table_xlsx_bytes


def _derived_answer(*, transport: bool = False, percent: bool = False):
    if transport:
        base = pd.DataFrame({
            "date": pd.to_datetime(["2022-01-31", "2022-02-28"]),
            "city": ["Ankara", "Ankara"],
            "passengers": [100.0, 110.0],
            "avg_delay": [8.0, 9.0],
            "helper_score": [7.0, 7.0],
        })
        definitions = [("passengers_change", "passengers - LAG(passengers) OVER (PARTITION BY city ORDER BY date)")]
    elif percent:
        base = pd.DataFrame({
            "date": pd.to_datetime(["2022-01-31", "2022-02-28"]),
            "metric_a": [100.0, 105.0],
            "helper_score": [7.0, 7.0],
        })
        definitions = [("metric_a_pct_change", "metric_a / LAG(metric_a) OVER (ORDER BY date) * 100")]
    else:
        base = pd.DataFrame({
            "date": pd.to_datetime(["2022-01-31", "2022-02-28"]),
            "metric_a": [463.792, 467.902],
            "metric_b": [214.776, 221.561],
            "helper_score": [7.0, 7.0],
        })
        definitions = [
            ("metric_a_change", "metric_a - LAG(metric_a) OVER (ORDER BY date)"),
            ("metric_b_change", "metric_b - LAG(metric_b) OVER (ORDER BY date)"),
        ]

    workspace = AnalysisWorkspace()
    workspace.set_table(base, description="fixture")
    steps = []
    for name, expression in definitions:
        values = {
            "metric_a_change": [None, 4.110],
            "metric_b_change": [None, 6.785],
            "metric_a_pct_change": [None, 5.0],
            "passengers_change": [None, 10.0],
        }[name]
        workspace.add_column(
            name,
            pd.Series(values, index=workspace.table.index),
            description=name,
            provenance=QueryProvenance(sql=f"türetilmiş: {expression}", dataset_ids=[]),
        )
        steps.append(AgentStep(
            index=len(steps) + 1,
            role="execute",
            tool_name="workspace_compute_column",
            tool_args={"column_name": name, "expression": expression},
            result_data=workspace.table.copy(),
        ))
    return AgentAnswer(text="ok", steps=steps, workspace=workspace), SimpleNamespace(workspace=workspace), base


def test_change_projection_keeps_identity_nulls_and_workspace_columns() -> None:
    answer, agent, before = _derived_answer()
    projected = project_result_table(answer, agent, question="aylık değişimleri göster", table_before=before)

    assert projected is not None
    assert list(projected.columns) == ["date", "metric_a_change", "metric_b_change"]
    assert pd.isna(projected.iloc[0]["metric_a_change"])
    assert projected.iloc[1]["metric_a_change"] == approx(4.110)
    assert projected.iloc[1]["metric_b_change"] == approx(6.785)
    assert list(agent.workspace.table.columns) == ["date", "metric_a", "metric_b", "helper_score", "metric_a_change", "metric_b_change"]
    assert agent.workspace.column_provenance("metric_a_change") is not None


def test_percent_and_explicit_base_plus_change_projection() -> None:
    answer, agent, before = _derived_answer(percent=True)
    projected = project_result_table(answer, agent, question="aylık yüzde değişimleri göster", table_before=before)
    assert projected is not None and list(projected.columns) == ["date", "metric_a_pct_change"]

    answer, agent, before = _derived_answer()
    projected = project_result_table(answer, agent, question="bakiyeleri ve aylık değişimleri birlikte göster", table_before=before)
    assert projected is not None
    assert list(projected.columns) == ["date", "metric_a", "metric_b", "metric_a_change", "metric_b_change"]

    answer, agent, before = _derived_answer()
    projected = project_result_table(
        answer,
        agent,
        question="Orijinal bakiyeleri de aylık değişimlerle birlikte göster.",
        table_before=before,
    )
    assert projected is not None
    assert list(projected.columns) == ["date", "metric_a", "metric_b", "metric_a_change", "metric_b_change"]


def test_generic_transport_projection_and_explicit_all_columns() -> None:
    answer, agent, before = _derived_answer(transport=True)
    projected = project_result_table(answer, agent, question="show monthly passenger changes", table_before=before)
    assert projected is not None and list(projected.columns) == ["date", "city", "passengers_change"]
    assert projected.iloc[1]["passengers_change"] == approx(10.0)

    all_columns = project_result_table(answer, agent, question="tüm sütunları göster", table_before=before)
    assert all_columns is not None
    assert list(all_columns.columns) == list(agent.workspace.table.columns)


def test_export_columns_match_projected_answer() -> None:
    answer, agent, before = _derived_answer()
    projected = project_result_table(answer, agent, question="aylık değişimleri göster", table_before=before)
    assert projected is not None

    payload = frame_to_dict(projected)
    csv_frame = pd.read_csv(io.BytesIO(table_csv_bytes(projected)), sep=";", decimal=",", encoding="utf-8-sig")
    xlsx_frame = pd.read_excel(io.BytesIO(table_xlsx_bytes(projected, title="projection")), sheet_name="tablo", engine="openpyxl")
    assert [c["label"] for c in payload["columns"]] == list(projected.columns) == list(csv_frame.columns) == list(xlsx_frame.columns)
    assert csv_frame.iloc[1]["metric_a_change"] == approx(4.110)
    assert xlsx_frame.iloc[1]["metric_b_change"] == approx(6.785)


def test_direct_query_projection_can_show_base_values_without_deleting_derived_columns() -> None:
    answer, agent, before = _derived_answer()
    base_view = agent.workspace.table[["date", "metric_a", "metric_b"]].copy()
    answer.steps.append(AgentStep(index=3, role="execute", tool_name="workspace_query", result_data=base_view))
    projected = project_result_table(answer, agent, question="orijinal değerleri göster", table_before=before)

    assert projected is not None and list(projected.columns) == ["date", "metric_a", "metric_b"]
    assert "metric_a_change" in agent.workspace.table.columns


def test_read_only_peek_does_not_replace_full_active_table() -> None:
    """Narration's four-row verification query must not shrink a 60-row export."""
    answer, agent, before = _derived_answer()
    answer.steps.append(AgentStep(
        index=3,
        role="execute",
        tool_name="workspace_query",
        tool_args={"as_active_table": False},
        result_data=agent.workspace.table.iloc[[0, 1]].copy(),
        ok=True,
    ))

    projected = project_result_table(answer, agent, question="60 aylık veriyi getir", table_before=before)

    assert projected is not None
    assert len(projected) == len(agent.workspace.table)
    assert list(projected.columns) == list(agent.workspace.table.columns)


def test_final_workspace_show_exports_the_post_transform_snapshot() -> None:
    answer, agent, before = _derived_answer()
    answer.steps.insert(0, AgentStep(
        index=0,
        role="execute",
        tool_name="workspace_query",
        result_data=before.copy(),
        ok=True,
    ))
    answer.steps.append(AgentStep(
        index=99,
        role="retrieve",
        tool_name="workspace_show",
        result_data=agent.workspace.table.copy(),
        ok=True,
    ))

    projected = project_result_table(
        answer,
        agent,
        question="bakiye yapısını aylık değişimleri analiz etmeye uygun hale getir",
        table_before=before,
    )

    assert projected is not None
    assert list(projected.columns) == list(agent.workspace.table.columns)
    assert "metric_a_change" in projected.columns and "metric_b_change" in projected.columns
    assert frame_to_dict(projected)["columns"][-1]["label"] == "metric_b_change"


def test_evidence_columns_stay_out_of_user_projection_after_compute_and_show() -> None:
    base = pd.DataFrame({
        "period_start": pd.to_datetime(["2022-01-01", "2022-02-01"]),
        "period_end": pd.to_datetime(["2022-01-31", "2022-02-28"]),
        "bddk_monthly:1536::value": [100.0, 110.0],
        "bddk_monthly:1536::quality_flag": ["ok", "ok"],
        "contributing_series": [["bddk_monthly:1536"], ["bddk_monthly:1536"]],
        "is_complete_period": [True, True],
    })
    workspace = AnalysisWorkspace()
    workspace.set_table(base, description="gold join fixture")
    workspace.add_column(
        "bddk_monthly:1536::value_change",
        pd.Series([None, 10.0]),
        description="change",
        provenance=QueryProvenance(
            sql='türetilmiş: "bddk_monthly:1536::value" - LAG("bddk_monthly:1536::value")',
            dataset_ids=["bddk_monthly:1536"],
        ),
    )
    answer = AgentAnswer(
        text="ok",
        steps=[
            AgentStep(
                index=1,
                role="execute",
                tool_name="workspace_compute_column",
                tool_args={
                    "column_name": "bddk_monthly:1536::value_change",
                    "expression": '"bddk_monthly:1536::value" - LAG("bddk_monthly:1536::value")',
                },
                result_data=workspace.table.copy(),
            ),
            AgentStep(
                index=2,
                role="retrieve",
                tool_name="workspace_show",
                result_data=workspace.table.copy(),
            ),
        ],
        workspace=workspace,
    )
    agent = SimpleNamespace(workspace=workspace)

    projected = project_result_table(answer, agent, question="aylık değişimleri göster", table_before=base)

    assert projected is not None
    assert list(projected.columns) == [
        "period_end",
        "bddk_monthly:1536::value_change",
    ]


def test_direct_gold_projection_hides_lineage_columns_but_all_columns_keeps_them() -> None:
    frame = pd.DataFrame({
        "period_end": pd.to_datetime(["2022-01-31"]),
        "metric": [100.0],
        "metric::quality_flag": ["ok"],
        "contributing_series": [["bddk:metric"]],
        "is_complete_period": [True],
    })
    workspace = AnalysisWorkspace()
    workspace.set_table(frame, description="gold join")
    answer = AgentAnswer(
        text="ok",
        steps=[AgentStep(index=1, role="execute", tool_name="gold_join", result_data=frame.copy())],
        workspace=workspace,
    )
    agent = SimpleNamespace(workspace=workspace)

    clean = project_result_table(answer, agent, question="veriyi göster", table_before=pd.DataFrame())
    full = project_result_table(answer, agent, question="tüm sütunları göster", table_before=pd.DataFrame())

    assert clean is not None and list(clean.columns) == ["period_end", "metric"]
    assert full is not None and list(full.columns) == list(frame.columns)


def test_follow_up_base_request_can_recover_source_columns_from_provenance() -> None:
    _, agent, before = _derived_answer()
    follow_up = AgentAnswer(
        text="ok",
        steps=[AgentStep(index=1, role="retrieve", tool_name="workspace_show", result_data=agent.workspace.table.copy())],
        workspace=agent.workspace,
    )
    projected = project_result_table(follow_up, agent, question="orijinal değerleri de ekle", table_before=before)

    assert projected is not None
    assert list(projected.columns) == ["date", "metric_a", "metric_b", "metric_a_change", "metric_b_change"]


def test_fastpath_multi_column_step_projects_and_exports_derived_only() -> None:
    answer, agent, before = _derived_answer()
    answer.steps = [AgentStep(
        index=1,
        role="execute",
        tool_name="workspace_compute_column",
        tool_args={
            "column_names": ["metric_a_change", "metric_b_change"],
            "expressions": [
                "metric_a - LAG(metric_a) OVER (ORDER BY date)",
                "metric_b - LAG(metric_b) OVER (ORDER BY date)",
            ],
        },
        result_data=agent.workspace.table.copy(),
    )]
    projected = project_result_table(answer, agent, question="aylık değişimleri göster", table_before=before)

    assert projected is not None
    assert list(projected.columns) == ["date", "metric_a_change", "metric_b_change"]
    csv_frame = pd.read_csv(io.BytesIO(table_csv_bytes(projected)), sep=";", decimal=",", encoding="utf-8-sig")
    xlsx_frame = pd.read_excel(io.BytesIO(table_xlsx_bytes(projected, title="fastpath")), sheet_name="tablo", engine="openpyxl")
    assert list(csv_frame.columns) == list(projected.columns) == list(xlsx_frame.columns)


def test_deterministic_fastpath_uses_scoped_result_for_exports() -> None:
    """The active 60-row LAG base must not leak into a 24-row answer artifact."""
    dates = pd.date_range("2021-01-31", periods=60, freq="ME")
    base = pd.DataFrame({"date": dates, "metric": range(60)})
    workspace = AnalysisWorkspace()
    workspace.set_table(base, description="monthly fixture")
    change = pd.Series([None, *[1.0] * 59], index=workspace.table.index)
    workspace.add_column(
        "metric_change",
        change,
        description="monthly change",
        provenance=QueryProvenance(
            sql="türetilmiş: metric - LAG(metric) OVER (ORDER BY date)",
            dataset_ids=[],
        ),
    )
    scoped = workspace.table.iloc[12:36].copy()
    answer = AgentAnswer(
        text="ok",
        steps=[AgentStep(
            index=1,
            role="execute",
            tool_name="workspace_compute_column",
            tool_args={
                "column_name": "metric_change",
                "expression": "metric - LAG(metric) OVER (ORDER BY date)",
                "deterministic": True,
            },
            result_data=scoped,
        )],
        workspace=workspace,
    )
    agent = SimpleNamespace(workspace=workspace)

    projected = project_result_table(answer, agent, question="aylık değişimleri göster")

    assert projected is not None
    assert len(projected) == 24
    assert projected.iloc[0]["date"] == dates[12]
    assert projected.iloc[-1]["date"] == dates[35]
    csv_frame = pd.read_csv(io.BytesIO(table_csv_bytes(projected)), sep=";", decimal=",", encoding="utf-8-sig")
    xlsx_frame = pd.read_excel(io.BytesIO(table_xlsx_bytes(projected, title="scoped")), sheet_name="tablo", engine="openpyxl")
    assert len(csv_frame) == len(xlsx_frame) == 24


def test_base_and_derived_projection_needs_both_and_a_connective() -> None:
    from kkb_agent.web_app import _BASE_AND_DERIVED_REQUEST as both
    for question in ("Orijinal bakiyeleri de aylık değişimlerle birlikte göster", "Hem bakiye hem değişim göster",
                     "Değişimleri ve orijinal değerleri göster", "Orijinal değerlerle birlikte yüzde değişimi göster",
                     "Show both values and changes"):
        assert both.search(question), question
    for question in ("Değişim değerlerini göster", "Aylık değişimleri göster", "Yüzde değişimi hesapla", "Bakiyeleri göster"):
        assert not both.search(question), f"{question}: yalnız biri istendi, orijinal kolonlar eklenmez"


def test_base_data_request_keeps_source_columns_and_both_operations() -> None:
    """ADR-0105: F04 'tabloda period, üç bakiye, fark ve yüzde olsun', F02 'aynı tabloya aylık farkı ekle'.
    Kaynak veri istenince bakiyeler görünür; mutlak fark + yüzde birlikte istenince yüzde kelimesi mutlak farkı düşürmez.
    'Yalnız değişim' her zaman kazanır."""
    answer, agent, before = _derived_answer()
    both = project_result_table(answer, agent, table_before=before,
                                question="Kullanıcı tablosunda period, bakiyeler, aylık mutlak farkı ve aylık yüzde değişimi olsun.")
    assert both is not None and list(both.columns) == ["date", "metric_a", "metric_b", "metric_a_change", "metric_b_change"]
    added = project_result_table(answer, agent, question="Aynı tabloya aylık farkı ekle.", table_before=before)
    assert added is not None and "metric_a" in added.columns and "helper_score" not in added.columns
    only = project_result_table(answer, agent, question="Bakiyeleri gösterme, yalnız aylık değişimleri göster.", table_before=before)
    assert only is not None and list(only.columns) == ["date", "metric_a_change", "metric_b_change"]


def test_compute_request_keeps_source_and_untransformed_turn_shows_full_table() -> None:
    """Son 3× (23 Eyl): F07 'Aylık farkı hesapla' tabloya kolon ekler, stok görünür kalır. F08 dışa aktarma turu ve
    T05 'nominal ve reel aynı tabloda' türetme istemez; hesaplanan kolonlar görünümü daraltmaz, tablo olduğu gibi çıkar."""
    answer, agent, before = _derived_answer()
    computed = project_result_table(answer, agent, question="Takip: Aylık farkı hesapla.", table_before=before)
    assert computed is not None and list(computed.columns) == ["date", "metric_a", "metric_b", "metric_a_change", "metric_b_change"]
    export = project_result_table(answer, agent, table_before=before,
                                  question="Takip: Kullanıcı projection'ını CSV ve XLSX olarak dışa aktar.")
    assert export is not None and list(export.columns) == list(agent.workspace.table.columns)
    shown = project_result_table(answer, agent, question="aylık değişimleri göster", table_before=before)
    assert shown is not None and list(shown.columns) == ["date", "metric_a_change", "metric_b_change"]


def test_only_restricting_months_does_not_hide_source_values() -> None:
    """Son 3× (23 Eyl, Q05): 'Yalnız komşu takvim ayları için ... değişim hesapla' ay kısıtıdır; değer kolonu görünür kalır."""
    answer, agent, before = _derived_answer()
    projected = project_result_table(answer, agent, table_before=before,
                                     question="Yalnız komşu takvim ayları için mutlak ve yüzde değişim hesapla.")
    assert projected is not None and "metric_a" in projected.columns and "metric_a_change" in projected.columns
