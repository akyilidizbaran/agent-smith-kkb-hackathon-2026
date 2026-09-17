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
