"""Deterministic verified-workspace transformation contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
from pytest import approx

from kkb_agent.contracts.lakehouse import QueryProvenance
from kkb_agent.core.agent import AnalyticsAgent
from kkb_agent.core.follow_up import FollowUpContext, resolve_follow_up
from kkb_agent.core.registry import ToolRegistry
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.core.workspace_fastpath import (
    execute_verified_workspace_transform,
    plan_verified_workspace_transform,
)


def _spec(
    *, source: str = "transport", frequency: str = "monthly", name: str = "Passengers"
) -> SimpleNamespace:
    return SimpleNamespace(
        dataset_id=f"{source}:passengers", source=source, frequency=frequency, name=name
    )


def _workspace(*, city: bool = False, quarterly: bool = False) -> AnalysisWorkspace:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2022-01-31", "2022-02-28", "2022-03-31"]),
            "metric_a": [463.792, 467.902, 477.686],
            "metric_b": [214.776, 221.561, 233.911],
        }
    )
    if city:
        frame.insert(1, "city", ["İstanbul", "İstanbul", "İstanbul"])
    workspace = AnalysisWorkspace()
    workspace.set_table(
        frame,
        description="verified fixture",
        provenance=QueryProvenance(
            sql="SELECT date, metric_a, metric_b FROM verified_fixture",
            dataset_ids=["transport:passengers"],
            sources=["fixture"],
        ),
    )
    return workspace


def _resolution(question: str, *, source: str = "transport", frequency: str = "monthly"):
    return resolve_follow_up(
        question,
        FollowUpContext(
            domain="transport", source=source, metric="passengers", frequency=frequency
        ),
    )


def test_verified_absolute_change_is_one_deterministic_operation() -> None:
    workspace = _workspace()
    resolution = _resolution("Bu verilerin bir önceki aya göre aylık değişimlerini göster.")
    plan = plan_verified_workspace_transform(
        resolution.question, resolution, workspace, active_specs=[_spec()]
    )

    assert plan is not None
    result = execute_verified_workspace_transform(workspace, plan)

    assert result is not None
    assert list(result.frame.columns) == [
        "date",
        "metric_a",
        "metric_b",
        "metric_a_change",
        "metric_b_change",
    ]
    assert pd.isna(result.frame.iloc[0]["metric_a_change"])
    assert result.frame.iloc[1]["metric_a_change"] == approx(4.110)
    assert result.frame.iloc[1]["metric_b_change"] == approx(6.785)
    assert result.frame.iloc[2]["metric_a_change"] == approx(9.784)
    assert result.frame.iloc[2]["metric_b_change"] == approx(12.350)
    assert len(workspace.history) == 2
    assert list(workspace.table.columns) == list(result.frame.columns)


def test_verified_percentage_change_handles_zero_base_deterministically() -> None:
    workspace = AnalysisWorkspace()
    workspace.set_table(
        pd.DataFrame(
            {"date": pd.to_datetime(["2022-01-31", "2022-02-28"]), "passengers": [100.0, 105.0]}
        ),
        description="verified fixture",
        provenance=QueryProvenance(sql="SELECT", dataset_ids=["transport:passengers"]),
    )
    resolution = _resolution("Bunların aylık yüzde değişimini göster.")
    plan = plan_verified_workspace_transform(
        resolution.question, resolution, workspace, active_specs=[_spec()]
    )
    assert plan is not None and plan.operation == "percent_change"
    result = execute_verified_workspace_transform(workspace, plan)
    assert result is not None
    assert pd.isna(result.frame.iloc[0]["passengers_pct_change"])
    assert result.frame.iloc[1]["passengers_pct_change"] == approx(5.0)


def test_explicit_geography_source_and_frequency_conflicts_fall_back() -> None:
    workspace = _workspace(city=True)
    assert (
        plan_verified_workspace_transform(
            "Ankara için aylık değişimleri göster",
            _resolution("Ankara için aylık değişimleri göster"),
            workspace,
            active_specs=[_spec(name="İstanbul Passengers")],
        )
        is None
    )

    source_resolution = _resolution(
        "BDDK aylık bültendeki değişimleri göster", source="bddk_finturk"
    )
    assert (
        plan_verified_workspace_transform(
            source_resolution.question,
            source_resolution,
            workspace,
            active_specs=[_spec(source="bddk_finturk")],
        )
        is None
    )

    frequency_resolution = _resolution("Bunların aylık değişimini göster", frequency="quarterly")
    assert (
        plan_verified_workspace_transform(
            frequency_resolution.question,
            frequency_resolution,
            workspace,
            active_specs=[_spec(frequency="quarterly")],
        )
        is None
    )


def test_no_workspace_is_not_eligible() -> None:
    resolution = _resolution("Bunların aylık değişimini göster")
    assert (
        plan_verified_workspace_transform(
            resolution.question, resolution, AnalysisWorkspace(), active_specs=[_spec()]
        )
        is None
    )


def test_generic_transport_follow_up_skips_llm() -> None:
    class NeverCalledLLM:
        model = "test"

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, *args, **kwargs):
            raise AssertionError("verified workspace fast path should not call the LLM")

    workspace = AnalysisWorkspace()
    workspace.set_table(
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2022-01-31", "2022-02-28"]),
                "passengers": [100.0, 110.0],
                "delay": [8.0, 9.0],
            }
        ),
        description="transport fixture",
        provenance=QueryProvenance(sql="SELECT", dataset_ids=["transport:passengers"]),
    )
    agent = AnalyticsAgent(NeverCalledLLM(), ToolRegistry(), workspace=workspace)
    agent._follow_up_context = FollowUpContext(
        domain="transport", metric="passengers", frequency="monthly"
    )

    answer = agent.ask("show monthly passenger changes")

    assert answer.usage == {"prompt": 0, "completion": 0, "calls": 0}
    assert len(answer.steps) == 1
    assert answer.steps[0].tool_name == "workspace_compute_column"
    assert answer.steps[0].ok
    assert "passengers_change" in workspace.columns()
