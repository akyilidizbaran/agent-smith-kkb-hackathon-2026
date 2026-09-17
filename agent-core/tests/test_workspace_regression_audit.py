"""Regression guards for semantic workspace/session reuse."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd

from kkb_agent.contracts.catalog import Frequency
from kkb_agent.contracts.lakehouse import QueryProvenance, QueryResult
from kkb_agent.core.agent import AnalyticsAgent
from kkb_agent.core.registry import ToolRegistry
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.tools.lakehouse import LakehouseQueryTool
from kkb_agent.web_app import Session, project_result_table


class _LLM:
    def supports_native_tools(self) -> bool:
        return True


def _spec(dataset_id: str, name: str, source: str, frequency: Frequency):
    return SimpleNamespace(dataset_id=dataset_id, name=name, source=source, frequency=frequency)


def _agent_with_adana_table() -> AnalyticsAgent:
    specs = [
        _spec("bddk_finturk:ADANA_konut", "Konut kredisi, ADANA", "bddk_finturk", Frequency.QUARTERLY),
        _spec("bddk_monthly:konut", "Konut kredisi, ulusal", "bddk_monthly", Frequency.MONTHLY),
    ]
    agent = AnalyticsAgent(_LLM(), ToolRegistry(), workspace=AnalysisWorkspace())
    agent._catalog_specs = lambda: specs
    agent.workspace.set_table(
        pd.DataFrame({"donem": ["2024-Q1"], "bakiye": [100.0]}),
        description="Adana FinTürk",
        provenance=QueryProvenance(sql="source", dataset_ids=["bddk_finturk:ADANA_konut"]),
    )
    return agent


def test_incompatible_national_request_does_not_receive_adana_workspace() -> None:
    agent = _agent_with_adana_table()
    question = "Ulusal aylık konut kredisi bakiyesini getir."

    agent._prepare_follow_up(question)
    assert not agent._active_table_is_compatible(question)
    agent._active_table_reuse_allowed = False
    messages = agent._build_messages(question)
    system = messages[0].content

    assert "AKTİF TABLO KULLANIMI YASAK" in system
    assert "Adana FinTürk" not in system
    assert all(message.role != "assistant" for message in messages[1:])


def test_session_a_adana_table_cannot_leak_into_session_b() -> None:
    session_a = Session(lambda: SimpleNamespace(workspace=AnalysisWorkspace()))
    session_b = Session(lambda: SimpleNamespace(workspace=AnalysisWorkspace()))

    session_a.agent.workspace.set_table(
        pd.DataFrame({"donem": ["2024-Q1"], "bakiye": [100.0]}),
        description="Adana FinTürk",
    )

    assert session_a.agent.workspace.has_table
    assert not session_b.agent.workspace.has_table


def test_new_conversation_clears_the_previous_active_workspace() -> None:
    session = Session(lambda: SimpleNamespace(workspace=AnalysisWorkspace()))
    session.agent.workspace.set_table(pd.DataFrame({"bakiye": [100.0]}), description="Adana FinTürk")
    session.answers.append({"question": "Adana", "steps": []})

    old_id = session.id
    new_id = session.new_conversation()

    assert new_id != old_id
    assert not session.agent.workspace.has_table


def test_display_projection_does_not_replace_workspace_or_other_session_state() -> None:
    workspace_a = AnalysisWorkspace()
    full = pd.DataFrame({"donem": ["2022-01"], "bakiye": [100.0], "yardimci": [1.0]})
    workspace_a.set_table(full, description="ulusal aylık")
    agent_a = SimpleNamespace(workspace=workspace_a)
    answer = SimpleNamespace(
        workspace=workspace_a,
        steps=[SimpleNamespace(tool_name="workspace_query", result_data=full[["donem", "bakiye"]].copy(), ok=True)],
    )
    workspace_b = AnalysisWorkspace()
    agent_b = SimpleNamespace(workspace=workspace_b)

    projected = project_result_table(answer, agent_a, question="bakiyeyi göster", table_before=full)

    assert projected is not None
    assert list(workspace_a.table.columns) == ["donem", "bakiye", "yardimci"]
    assert not agent_b.workspace.has_table


def test_compatible_follow_up_may_reuse_workspace() -> None:
    agent = _agent_with_adana_table()
    question = "Aynı tabloyu göster."

    agent._prepare_follow_up(question)
    assert agent._active_table_is_compatible(question)


def test_transformation_projection_returns_relevant_view_without_deleting_base_data() -> None:
    workspace = AnalysisWorkspace()
    base = pd.DataFrame({"date": ["2022-01", "2022-02"], "bakiye": [100.0, 110.0], "helper": [1, 1]})
    workspace.set_table(base, description="ulusal aylık")
    change = pd.Series([None, 10.0], index=base.index)
    workspace.add_column(
        "bakiye_change",
        change,
        description="aylık değişim",
        provenance=QueryProvenance(sql="türetilmiş: bakiye - LAG(bakiye) OVER (ORDER BY date)", dataset_ids=[]),
    )
    agent = SimpleNamespace(workspace=workspace)
    answer = SimpleNamespace(
        workspace=workspace,
        steps=[SimpleNamespace(
            tool_name="workspace_compute_column",
            tool_args={"column_name": "bakiye_change", "expression": "bakiye - LAG(bakiye) OVER (ORDER BY date)"},
            result_data=workspace.table.copy(),
            ok=True,
        )],
    )

    projected = project_result_table(answer, agent, question="aylık değişimleri göster", table_before=base)

    assert projected is not None and list(projected.columns) == ["date", "bakiye_change"]
    assert list(workspace.table.columns) == ["date", "bakiye", "helper", "bakiye_change"]


class _Lakehouse:
    def __init__(self) -> None:
        self.specs = [
            _spec("bddk_finturk:ADANA_konut", "Konut kredisi, ADANA", "bddk_finturk", Frequency.QUARTERLY),
            _spec("bddk_monthly:konut", "Konut kredisi, ulusal", "bddk_monthly", Frequency.MONTHLY),
        ]
        self.executed = False

    def list_datasets(self):
        return self.specs

    def execute_sql(self, sql: str, *, max_rows: int = 10_000) -> QueryResult:
        self.executed = True
        return QueryResult(
            data=pd.DataFrame({"donem": [date(2024, 1, 31)], "bakiye": [1.0]}),
            provenance=QueryProvenance(sql=sql, dataset_ids=["bddk_finturk:ADANA_konut"]),
        )


def test_national_monthly_cannot_fallback_to_provincial_quarterly() -> None:
    lakehouse = _Lakehouse()
    registry = SimpleNamespace(active_question="Ulusal aylık konut kredisi bakiyesi")
    tool = LakehouseQueryTool(lakehouse, AnalysisWorkspace(), registry=registry)

    result = tool.validate_and_run({
        "sql": "SELECT * FROM silver.fact_observation WHERE series_id = 'bddk_finturk:ADANA_konut'",
        "purpose": "ulusal aylık bakiye",
    })

    assert not result.ok
    assert result.error is not None and result.error.error_code in {"FREQUENCY_MISMATCH", "GEOGRAPHY_MISMATCH"}
    assert not lakehouse.executed

    # With the frequency made compatible, the independent geography guard is
    # still required to reject the provincial fallback before execution.
    lakehouse.specs[0].frequency = Frequency.MONTHLY
    result = tool.validate_and_run({
        "sql": "SELECT * FROM silver.fact_observation WHERE series_id = 'bddk_finturk:ADANA_konut'",
        "purpose": "ulusal aylık bakiye",
    })

    assert not result.ok
    assert result.error is not None and result.error.error_code == "GEOGRAPHY_MISMATCH"
    assert not lakehouse.executed
