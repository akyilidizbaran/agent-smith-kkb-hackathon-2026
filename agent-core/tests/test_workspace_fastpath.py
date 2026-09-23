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
    inspect_existing_verified_transform,
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


def test_preparatory_workspace_query_cannot_finalize_without_change_columns() -> None:
    """A date cast/sort step is completed by the harness before narration."""
    from types import SimpleNamespace

    workspace = _workspace()
    agent = AnalyticsAgent(object(), ToolRegistry(), workspace=workspace)
    question = "Bu verilerin bir önceki aya göre aylık değişimlerini göster."
    agent._follow_up_resolution = _resolution(question)
    agent._active_table_reuse_allowed = True
    agent._catalog_specs = lambda: [_spec()]
    steps = [SimpleNamespace(ok=True, tool_name="workspace_query")]

    assert agent._complete_pending_verified_transform(question, steps)
    assert any(step.tool_name == "workspace_compute_column" for step in steps)
    assert "metric_a_change" in workspace.table.columns
    assert "metric_b_change" in workspace.table.columns


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

    metric_resolution = _resolution("Konut kredilerini de ek")
    assert (
        plan_verified_workspace_transform(
            metric_resolution.question,
            metric_resolution,
            workspace,
            active_specs=[_spec()],
        )
        is None
    )


def test_compact_explicit_period_conflict_falls_back_from_full_workspace() -> None:
    """A compact YYYYMM range is a new scope, so a stale table is unsafe."""
    workspace = _workspace()
    resolution = resolve_follow_up(
        "Show the monthly change for the 202303–202402 period.",
        FollowUpContext(
            domain="transport", source="transport", metric="passengers",
            series="transport:passengers", date_range="2021-04–2026-03", frequency="monthly",
        ),
    )
    assert resolution.explicit.date_range == "2023-03–2024-02"
    assert "date_range" in resolution.overridden
    assert (
        plan_verified_workspace_transform(
            resolution.question,
            resolution,
            workspace,
            active_specs=[_spec()],
        )
        is None
    )


def test_explicit_month_range_filters_after_full_window_lag() -> None:
    dates = pd.date_range("2021-04-30", "2026-03-31", freq="ME")
    frame = pd.DataFrame(
        {
            "period_end": dates,
            "ay": dates.strftime("%Y-%m"),
            "need": [float(i) for i in range(len(dates))],
            "card": [float(i * 10) for i in range(len(dates))],
            "bddk_monthly:1536::series_id": ["bddk_monthly:1536"] * len(dates),
            "bddk_monthly:1536::unit": ["TRY_mn"] * len(dates),
            "bddk_monthly:1536::quality_flag": ["ok"] * len(dates),
            "gold_metric_id": ["fixture"] * len(dates),
        }
    )
    workspace = AnalysisWorkspace()
    workspace.set_table(
        frame,
        description="verified 60 month fixture",
        provenance=QueryProvenance(
            sql="SELECT period_end, need, card FROM verified_fixture",
            dataset_ids=["bddk_monthly:1536", "bddk_monthly:1539"],
            sources=["bddk_monthly"],
        ),
    )
    resolution = resolve_follow_up(
        "Show monthly changes within 202301–202412 and keep the monthly axis aligned.",
        FollowUpContext(
            domain="finance", source="bddk_monthly", metric="kredi",
            series="bddk_monthly:1536", date_range="2021-04–2026-03", frequency="monthly",
        ),
    )
    plan = plan_verified_workspace_transform(
        resolution.question,
        resolution,
        workspace,
        active_specs=[_spec(source="bddk_monthly", name="İhtiyaç"), _spec(source="bddk_monthly", name="Kart")],
    )

    assert plan is not None
    assert plan.group_columns == (), "a month label mirroring the date axis is not a panel dimension"
    assert plan.period_start == pd.Timestamp("2023-01-01")
    assert plan.period_end == pd.Timestamp("2024-12-31")
    result = execute_verified_workspace_transform(workspace, plan)

    assert result is not None
    assert len(result.frame) == 24
    assert result.frame.iloc[0]["period_end"] == pd.Timestamp("2023-01-31")
    # December 2022 remains available as the LAG base for January 2023.
    assert result.frame.iloc[0]["need_change"] == approx(1.0)
    assert result.frame.iloc[0]["card_change"] == approx(10.0)
    assert result.frame.iloc[-1]["period_end"] == pd.Timestamp("2024-12-31")
    # The active table keeps all 60 months and gains the derived columns.
    assert len(workspace.table) == 60
    assert "need_change" in workspace.table.columns and "card_change" in workspace.table.columns


def test_invalid_generated_transform_is_repaired_and_repeat_reuses_verified_output() -> None:
    dates = pd.date_range("2021-04-30", "2026-03-31", freq="ME")
    source = pd.DataFrame(
        {
            "observation_date": dates,
            "ay": dates.strftime("%Y-%m"),
            "metric_a": [float(i) for i in range(len(dates))],
            "metric_b": [float(i * 10) for i in range(len(dates))],
        }
    )
    workspace = AnalysisWorkspace()
    base_provenance = QueryProvenance(
        sql="SELECT observation_date, metric_a, metric_b FROM verified_fixture",
        dataset_ids=["finance:metric_a", "finance:metric_b"],
        sources=["finance"],
    )
    workspace.set_table(source, description="verified 60-period source", provenance=base_provenance)

    # Reproduce the persisted failure mode: a unique text month label was
    # mistakenly used as a partition key, leaving every derived value NULL.
    broken = source.loc[
        pd.to_datetime(source["observation_date"]).between("2023-01-01", "2024-12-31")
    ].copy().reset_index(drop=True)
    broken["metric_a_change"] = float("nan")
    broken["metric_b_change"] = float("nan")
    old_provenance = {
        "metric_a_change": QueryProvenance(
            sql='türetilmiş: "metric_a" - LAG("metric_a") OVER (PARTITION BY "ay" ORDER BY "observation_date")',
            dataset_ids=["finance:metric_a"], sources=["finance"], row_count=len(broken),
        ),
        "metric_b_change": QueryProvenance(
            sql='türetilmiş: "metric_b" - LAG("metric_b") OVER (PARTITION BY "ay" ORDER BY "observation_date")',
            dataset_ids=["finance:metric_b"], sources=["finance"], row_count=len(broken),
        ),
    }
    workspace.replace_table(
        broken,
        description="stale derived view",
        column_provenance=old_provenance,
        columns_added=list(old_provenance),
    )

    class NeverCalledLLM:
        model = "test"

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, *args, **kwargs):
            raise AssertionError("verified local transform and replay must not call the LLM")

    agent = AnalyticsAgent(NeverCalledLLM(), ToolRegistry(), workspace=workspace)
    agent._follow_up_context = FollowUpContext(
        domain="finance", metric="metric", date_range="2021-04–2026-03", frequency="monthly"
    )
    question = "Show monthly changes within 202301–202412"

    assert inspect_existing_verified_transform(
        question,
        _resolution(question, source="finance"),
        workspace,
    ) is None, "a generated LAG column full of invalid NULLs must not be certified"

    repaired = agent.ask(question)
    assert repaired.usage["calls"] == 0
    assert repaired.steps[0].tool_name == "workspace_compute_column"
    assert len(workspace.table) == 60
    assert len(repaired.steps[0].result_data) == 24
    assert repaired.steps[0].result_data.iloc[0]["metric_a_change"] == approx(1.0)
    assert repaired.steps[0].result_data.iloc[0]["metric_b_change"] == approx(10.0)
    assert workspace.table.iloc[1]["metric_a_change"] == approx(1.0)
    assert "2023-01" in workspace.title and "2024-12" in workspace.title

    repeated = agent.ask(question)
    assert repeated.usage["calls"] == 0
    assert repeated.reused_verified_table
    assert repeated.steps[0].role == "validate"
    assert len(workspace.table) == 60
    assert len(repeated.steps[0].result_data) == 24


def test_explicit_month_range_follow_up_preserves_active_series_without_llm() -> None:
    dates = pd.date_range("2021-04-30", "2026-03-31", freq="ME")
    workspace = AnalysisWorkspace()
    workspace.set_table(
        pd.DataFrame({"date": dates, "metric_a": range(len(dates)), "metric_b": range(len(dates))}),
        description="verified 60 month fixture",
        provenance=QueryProvenance(
            sql="SELECT date, metric_a, metric_b FROM verified_fixture",
            dataset_ids=["transport:passengers"],
            sources=["transport"],
        ),
    )

    class NeverCalledLLM:
        model = "test"

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, *args, **kwargs):
            raise AssertionError("explicit period transformation must reuse the active workspace")

    agent = AnalyticsAgent(NeverCalledLLM(), ToolRegistry(), workspace=workspace)
    agent._catalog_specs = lambda: [_spec()]
    agent._follow_up_context = FollowUpContext(
        domain="transport", source="transport", metric="passengers",
        series="transport:passengers", date_range="2021-04–2026-03", frequency="monthly",
    )

    answer = agent.ask(
        "Compute changes for 202301–202412 and align monthly dates."
    )

    assert answer.usage["calls"] == 0
    assert answer.steps[0].tool_name == "workspace_compute_column"
    assert len(workspace.table) == 60
    assert len(answer.steps[0].result_data) == 24
    assert answer.steps[0].result_data.iloc[0]["metric_a_change"] == approx(1.0)


def test_month_window_follow_up_keeps_full_table_and_answers_with_the_window() -> None:
    """İnceleme (22 Eyl): '2024 Ocak–Mart için değişim' 60 satırlık tabloyu 3 satırla değiştiriyor, eski
    tablo kayboluyordu. Artık sütun eklenir, cevap yalnız pencereyi taşır; tekrar soruda da aynı."""
    dates = pd.date_range("2021-04-30", "2026-03-31", freq="ME")
    workspace = AnalysisWorkspace()
    workspace.set_table(
        pd.DataFrame({"date": dates, "metric_a": range(len(dates)), "metric_b": range(len(dates))}),
        description="verified 60 month fixture",
        provenance=QueryProvenance(
            sql="SELECT date, metric_a, metric_b FROM verified_fixture",
            dataset_ids=["transport:passengers"],
            sources=["transport"],
        ),
    )
    before = workspace.table.copy()

    class NeverCalledLLM:
        model = "test"

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, *args, **kwargs):
            raise AssertionError("explicit period transformation must reuse the active workspace")

    agent = AnalyticsAgent(NeverCalledLLM(), ToolRegistry(), workspace=workspace)
    agent._catalog_specs = lambda: [_spec()]
    agent._follow_up_context = FollowUpContext(
        domain="transport", source="transport", metric="passengers",
        series="transport:passengers", date_range="2021-04–2026-03", frequency="monthly",
    )

    answer = agent.ask("Compute changes for 202401–202403 and align monthly dates.")

    view = answer.steps[0].result_data
    assert len(view) == 3
    assert view.iloc[0]["date"] == pd.Timestamp("2024-01-31")
    assert view.iloc[0]["metric_a_change"] == approx(1.0)
    assert len(workspace.table) == 60
    assert workspace.table[["date", "metric_a", "metric_b"]].equals(before)
    assert answer.artifacts[0]["row_count"] == 3
    assert "3 dönemlik çıktı" in answer.text and "korundu" in answer.text

    repeated = agent.ask("Compute changes for 202401–202403 and align monthly dates.")
    assert repeated.reused_verified_table
    assert len(repeated.steps[0].result_data) == 3
    assert len(workspace.table) == 60


def test_all_verified_series_follow_up_reuses_the_workspace() -> None:
    workspace = _workspace()
    resolution = _resolution("Tüm serilerin değişimini göster")
    plan = plan_verified_workspace_transform(
        resolution.question, resolution, workspace, active_specs=[_spec()]
    )

    assert plan is not None
    assert plan.value_columns == ("metric_a", "metric_b")


def test_verified_transform_skips_numeric_provenance_columns() -> None:
    workspace = AnalysisWorkspace()
    workspace.set_table(
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2022-01-31", "2022-02-28", "2022-03-31"]),
                "metric": [100.0, 110.0, 121.0],
                "metric::observations": [1, 1, 1],
                "metric::missing_observations": [0, 0, 0],
            }
        ),
        description="verified fixture with lineage metadata",
        provenance=QueryProvenance(sql="SELECT", dataset_ids=["transport:metric"]),
    )
    resolution = _resolution("Bu serinin aylık değişimini göster.")

    plan = plan_verified_workspace_transform(
        resolution.question, resolution, workspace, active_specs=[_spec()]
    )

    assert plan is not None
    assert plan.value_columns == ("metric",)


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

    assert answer.usage["prompt"] == 0
    assert answer.usage["completion"] == 0
    assert answer.usage["calls"] == 0
    assert len(answer.steps) == 1
    assert answer.steps[0].tool_name == "workspace_compute_column"
    assert answer.steps[0].ok
    assert "passengers_change" in workspace.columns()


def test_referential_monthly_follow_up_keeps_verified_series_and_skips_retrieval() -> None:
    class NeverCalledLLM:
        model = "test"

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, *args, **kwargs):
            raise AssertionError("referential follow-up must not invoke the planner")

    workspace = _workspace()
    agent = AnalyticsAgent(NeverCalledLLM(), ToolRegistry(), workspace=workspace)
    agent._follow_up_context = FollowUpContext(
        domain="finance",
        source="BDDK Aylık Bülten",
        metric="kredi",
        series="bddk_monthly:1536_Toplam",
        date_range="2022-2023",
        frequency="monthly",
    )
    agent._catalog_specs = lambda: [
        _spec(source="BDDK Aylık Bülten", name="Verified credit balances")
    ]

    answer = agent.ask("Bu verilerin bir önceki aya göre aylık değişimlerini göster.")

    assert answer.usage["prompt"] == 0
    assert answer.usage["completion"] == 0
    assert answer.usage["calls"] == 0
    assert answer.steps[0].tool_name == "workspace_compute_column"
    assert "gold.net_kar_aylik" not in workspace.columns()
    assert workspace.table is not None
    assert workspace.table.iloc[1]["metric_a_change"] == approx(4.110)
    assert workspace.table.iloc[1]["metric_b_change"] == approx(6.785)
    assert workspace.table.iloc[2]["metric_a_change"] == approx(9.784)
    assert workspace.table.iloc[2]["metric_b_change"] == approx(12.350)


def test_referential_percentage_follow_up_uses_all_verified_metrics() -> None:
    workspace = _workspace()
    previous = FollowUpContext(
        domain="finance",
        metric="kredi",
        series="bddk_monthly:1536_Toplam",
        date_range="2022-2023",
        frequency="monthly",
    )
    resolution = resolve_follow_up("Bunların aylık yüzde değişimlerini göster.", previous)
    plan = plan_verified_workspace_transform(
        resolution.question, resolution, workspace, active_specs=[_spec()]
    )

    assert resolution.context.series == previous.series
    assert plan is not None and plan.operation == "percent_change"
    result = execute_verified_workspace_transform(workspace, plan)
    assert result is not None
    assert pd.isna(result.frame.iloc[0]["metric_a_pct_change"])
    assert result.frame.iloc[1]["metric_a_pct_change"] == approx(0.8861731121)
    assert result.frame.iloc[1]["metric_b_pct_change"] == approx(3.1591053004)
