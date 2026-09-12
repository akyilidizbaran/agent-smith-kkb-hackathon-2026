"""Sınır doğrulayıcı: her araç çağrısı aynı boru hattından — şema → SQL guard → referans → politika.

Bu testler sıranın kendisini ölçer. Bir çağrı iki katmanda birden takılabilecekken
hangi hatayı aldığı, sıranın doğru olup olmadığının kanıtıdır.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.catalog import (  # noqa: E402
    ColumnRole,
    ColumnSpec,
    Coverage,
    DatasetSpec,
    Frequency,
)
from kkb_agent.contracts.lakehouse import LakehouseError, QueryProvenance, QueryResult  # noqa: E402
from kkb_agent.core.agent import AnalyticsAgent  # noqa: E402
from kkb_agent.core.errors import ToolError  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.tool import Tool, ToolResult  # noqa: E402
from kkb_agent.core.validator import BoundaryValidator  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.llm.base import LLMResponse, ToolCall  # noqa: E402
from kkb_agent.tools.lakehouse import (  # noqa: E402
    LakehouseDescribeTool,
    LakehouseDistinctValuesTool,
    LakehouseQueryTool,
    LakehouseSearchTool,
)
from kkb_agent.tools.workspace import WorkspaceAddColumnTool, WorkspaceComputeColumnTool  # noqa: E402


SPEC = DatasetSpec(
    dataset_id="test_tablo", name="Test", description="test", source="TEST",
    frequency=Frequency.MONTHLY, time_column="donem", grain=["donem"],
    columns=[
        ColumnSpec(name="donem", role=ColumnRole.TIME, dtype="DATE", description="dönem"),
        ColumnSpec(name="kalem", role=ColumnRole.DIMENSION, dtype="VARCHAR", description="kalem"),
        ColumnSpec(name="deger", role=ColumnRole.MEASURE, dtype="DOUBLE", description="değer", unit="milyon TL"),
    ],
    coverage=Coverage(start=date(2021, 1, 31), end=date(2026, 6, 30)),
)


class StubLakehouse:
    """Kataloğu SPEC olan, her sorguya bir satır dönen sahte lakehouse."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def list_datasets(self):
        return [SPEC]

    def get_dataset(self, dataset_id: str):
        if dataset_id != SPEC.dataset_id:
            raise LakehouseError(f"'{dataset_id}' bulunamadı.")
        return SPEC

    def search_datasets(self, query: str, limit: int = 5):
        return [SPEC]

    def preview(self, dataset_id: str, n: int = 5):
        return self.execute_sql("SELECT 1")

    def execute_sql(self, sql: str, *, max_rows: int = 10_000):
        self.executed.append(sql)
        return QueryResult(
            data=pd.DataFrame({"donem": [date(2025, 1, 31)], "deger": [1.0]}),
            provenance=QueryProvenance(sql=sql, dataset_ids=[SPEC.dataset_id], row_count=1),
        )

    def series_sql(self, dataset_id, *, key_column, value_column, filter_column=None, filter_value=None):
        if value_column not in {c.name for c in SPEC.columns}:
            raise LakehouseError(f"'{value_column}' kolonu yok.")
        return f"SELECT {key_column}, {value_column} FROM {dataset_id}"


class _Registry:
    active_question = "2025 yılında değer nasıl değişti?"


def _query_tool(lake: StubLakehouse | None = None, workspace: AnalysisWorkspace | None = None):
    return LakehouseQueryTool(lake or StubLakehouse(), workspace or AnalysisWorkspace(), registry=_Registry())


# --------------------------------------------------------------------- sıra
def test_sema_once_hicbir_sey_calismadan() -> None:
    lake = StubLakehouse()
    r = _query_tool(lake).validate_and_run({"sql": 123})  # tip yanlış

    assert r.error is not None and r.error.error_code == "INVALID_ARGS"
    assert r.error.layer == "schema"
    assert lake.executed == []


def test_sql_guard_referanstan_once() -> None:
    """DROP + var olmayan tablo: hata UNSAFE_SQL olmalı, DATASET_NOT_FOUND değil.

    Yasak bir ifadenin referansını doğrulamak anlamsız; "tabloyu düzelt" deyip DROP'u
    yeniden denetmek bir tur yakar.
    """
    lake = StubLakehouse()
    r = _query_tool(lake).validate_and_run({"sql": "DROP TABLE olmayan_tablo", "purpose": "x"})

    assert r.error is not None and r.error.error_code == "UNSAFE_SQL"
    assert r.error.layer == "policy" and r.error.is_retryable is False
    assert lake.executed == []


def test_referans_politikadan_once() -> None:
    """Var olmayan tablo + dönem filtresi eksik: hata referans katmanından gelmeli."""
    lake = StubLakehouse()
    tool = LakehouseDistinctValuesTool(lake)
    r = tool.validate_and_run({"dataset_id": "yok_boyle_tablo", "column": "kalem"})

    assert r.error is not None and r.error.error_code == "DATASET_NOT_FOUND"
    assert r.error.layer == "reference"
    assert lake.executed == []


def test_politika_en_son_ve_calistirmadan() -> None:
    """Sorguda dönem yok ama soruda 2025 var: MISSING_PERIOD_FILTER, sorgu hiç çalışmaz."""
    lake = StubLakehouse()
    r = _query_tool(lake).validate_and_run({"sql": "SELECT deger FROM test_tablo", "purpose": "x"})

    assert r.error is not None and r.error.error_code == "MISSING_PERIOD_FILTER"
    assert r.error.layer == "policy"
    assert lake.executed == []


def test_hepsi_gecince_run_calisir() -> None:
    lake = StubLakehouse()
    r = _query_tool(lake).validate_and_run(
        {"sql": "SELECT donem, deger FROM test_tablo WHERE EXTRACT(year FROM donem)=2025", "purpose": "x"}
    )

    assert r.ok and lake.executed


# ------------------------------------------------------------ referans adayları
def test_bulunamayan_kimlikte_adaylar_tum_katalog_degil() -> None:
    """1620 serilik katalogda tüm kimlikleri listelemek hatayı hataya çevirir (ADR-0026)."""
    lake = StubLakehouse()
    r = LakehouseDescribeTool(lake).validate_and_run({"dataset_id": "yok"})

    assert r.error is not None and r.error.error_code == "DATASET_NOT_FOUND"
    assert len(r.error.candidates) <= 8


def test_kolon_yoksa_referans_katmani() -> None:
    r = LakehouseDistinctValuesTool(StubLakehouse()).validate_and_run(
        {"dataset_id": "test_tablo", "column": "yok"}
    )
    assert r.error is not None and r.error.error_code == "COLUMN_NOT_FOUND"
    assert "kalem" in r.error.candidates


# ---------------------------------------------------------- workspace araçları
def test_tablo_yokken_add_column_referansta_takilir() -> None:
    r = WorkspaceAddColumnTool(StubLakehouse(), AnalysisWorkspace()).validate_and_run(
        {"dataset_id": "test_tablo", "key_column": "donem", "value_column": "deger",
         "column_name": "yeni", "join_on": "donem", "purpose": "x"}
    )
    assert r.error is not None and r.error.error_code == "NO_ACTIVE_TABLE"


def test_compute_guvensiz_ifade_politikada_takilir() -> None:
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"a": [1.0, 2.0]}), description="t")
    r = WorkspaceComputeColumnTool(ws).validate_and_run(
        {"expression": "read_csv('/etc/passwd')", "column_name": "b", "purpose": "x"}
    )
    assert r.error is not None and r.error.error_code == "UNSAFE_SQL"
    assert r.error.is_retryable is False


def test_compute_var_olan_kolon_referansta_takilir() -> None:
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"a": [1.0, 2.0]}), description="t")
    r = WorkspaceComputeColumnTool(ws).validate_and_run(
        {"expression": "a * 2", "column_name": "a", "purpose": "x"}
    )
    assert r.error is not None and r.error.error_code == "COLUMN_EXISTS"


# ------------------------------------------------------------- yeni araç sözleşmesi
def test_yeni_arac_iki_hook_yazar_baska_bir_sey_ogrenmez() -> None:
    """Sırayı araç bilmez; yalnız 'neyi doğrulayacağını' söyler."""

    class P(BaseModel):
        n: int

    class T(Tool):
        name = "t"
        description = "test"
        Params = P

        def __init__(self) -> None:
            self.calls: list[str] = []

        def validate_refs(self, params: P) -> ToolError | None:
            self.calls.append("refs")
            return ToolError(error_code="VALUE_NOT_FOUND", message="yok", layer="reference") if params.n == 1 else None

        def check_policy(self, params: P) -> ToolError | None:
            self.calls.append("policy")
            return ToolError(error_code="MISSING_PERIOD_FILTER", message="dönem", layer="policy") if params.n == 2 else None

        def run(self, params: P) -> ToolResult:
            self.calls.append("run")
            return ToolResult(content="ok")

    v = BoundaryValidator()
    t = T(); assert v.validate_and_run(t, {"n": 1}).error.error_code == "VALUE_NOT_FOUND"
    assert t.calls == ["refs"]
    t = T(); assert v.validate_and_run(t, {"n": 2}).error.error_code == "MISSING_PERIOD_FILTER"
    assert t.calls == ["refs", "policy"]
    t = T(); assert v.validate_and_run(t, {"n": 3}).ok
    assert t.calls == ["refs", "policy", "run"]


# ------------------------------------------------------------------- roller
class _ScriptedLLM:
    model = "scripted"

    def __init__(self, turns: list[LLMResponse]) -> None:
        self._turns = turns
        self.n = 0

    def supports_native_tools(self) -> bool:
        return True

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None) -> LLMResponse:
        turn = self._turns[min(self.n, len(self._turns) - 1)]
        self.n += 1
        return turn


def test_izde_roller_gorunur() -> None:
    """Planner/Retriever/Validator/Narrator rol olarak tutuluyor, agent olarak değil."""
    lake = StubLakehouse()
    ws = AnalysisWorkspace()
    reg = ToolRegistry()
    reg.register_all([LakehouseSearchTool(lake), LakehouseDescribeTool(lake),
                      LakehouseQueryTool(lake, ws, registry=reg)])
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall(id="1", name="lakehouse_search", arguments={"query": "değer"})]),
        LLMResponse(content="", tool_calls=[ToolCall(id="2", name="lakehouse_query",
                    arguments={"sql": "SELECT deger FROM test_tablo", "purpose": "x"})]),   # dönem yok → validate
        LLMResponse(content="", tool_calls=[ToolCall(id="3", name="lakehouse_query",
                    arguments={"sql": "SELECT donem, deger FROM test_tablo WHERE EXTRACT(year FROM donem)=2025", "purpose": "x"})]),
        LLMResponse(content="2025'te değer 1,0."),
    ])
    agent = AnalyticsAgent(llm=llm, registry=reg, workspace=ws, max_steps=8)

    answer = agent.ask("2025 yılında değer nasıl değişti?")

    roles = [s.role for s in answer.steps]
    assert roles == ["retrieve", "validate", "execute", "narrate"]
    assert "[retrieve]" in answer.trace_text() and "[narrate]" in answer.trace_text()
