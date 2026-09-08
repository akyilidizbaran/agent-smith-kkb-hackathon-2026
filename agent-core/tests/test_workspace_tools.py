"""Workspace araçlarının LLM'den bağımsız doğrulaması.

Golden set uçtan uca davranışı ölçer ama stokastiktir. Araçların kendisi
deterministik olmalı; buradaki testler saniyeler içinde koşar ve bir aracın
bozulduğunu golden set'i beklemeden söyler.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.workspace import (  # noqa: E402
    WorkspaceAddColumnTool,
    WorkspaceComputeColumnTool,
)


class FakeLakehouse:
    """execute_sql çağrısını sabit bir sonuca bağlar."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def execute_sql(self, sql: str, *, max_rows: int = 10_000):
        from kkb_agent.contracts.lakehouse import QueryProvenance, QueryResult

        return QueryResult(
            data=self._df,
            provenance=QueryProvenance(sql=sql, dataset_ids=[], row_count=len(self._df)),
        )


@pytest.fixture
def workspace() -> AnalysisWorkspace:
    ws = AnalysisWorkspace()
    ws.set_table(
        pd.DataFrame(
            {
                "donem": pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"]),
                "konut": [100.0, 110.0, 121.0],
            }
        ),
        description="test tablosu",
    )
    return ws


def test_add_column_tabloyu_bozmaz(workspace: AnalysisWorkspace) -> None:
    lake = FakeLakehouse(
        pd.DataFrame(
            {
                "donem": pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"]),
                "deger": [10.0, 20.0, 30.0],
            }
        )
    )
    tool = WorkspaceAddColumnTool(lake, workspace)
    res = tool.validate_and_run(
        {"sql": "SELECT donem, deger FROM x", "column_name": "tasit",
         "join_on": "donem", "purpose": "taşıt kredisi"}
    )
    assert res.ok, res.content
    table = workspace.table
    assert len(table) == 3, "satır sayısı değişmemeli"
    assert list(table["konut"]) == [100.0, 110.0, 121.0], "mevcut sütun bozulmamalı"
    assert list(table["tasit"]) == [10.0, 20.0, 30.0]


def test_add_column_anahtar_ortusmezse_hata_verir(workspace: AnalysisWorkspace) -> None:
    lake = FakeLakehouse(
        pd.DataFrame({"donem": pd.to_datetime(["2019-01-01"]), "deger": [5.0]})
    )
    tool = WorkspaceAddColumnTool(lake, workspace)
    res = tool.validate_and_run(
        {"sql": "SELECT donem, deger FROM x", "column_name": "eski",
         "join_on": "donem", "purpose": "kapsam dışı"}
    )
    assert not res.ok
    assert "eşleş" in res.content.lower()
    assert "eski" not in workspace.columns(), "başarısız ekleme tabloyu kirletmemeli"


def test_add_column_iki_kolon_sarti(workspace: AnalysisWorkspace) -> None:
    lake = FakeLakehouse(pd.DataFrame({"a": [1], "b": [2], "c": [3]}))
    tool = WorkspaceAddColumnTool(lake, workspace)
    res = tool.validate_and_run(
        {"sql": "SELECT a,b,c FROM x", "column_name": "x", "join_on": "donem", "purpose": "y"}
    )
    assert not res.ok and "2" in res.content


def test_compute_column_hesabi_motorda_yapar(workspace: AnalysisWorkspace) -> None:
    tool = WorkspaceComputeColumnTool(workspace)
    res = tool.validate_and_run(
        {
            "expression": "100.0 * (konut - LAG(konut) OVER (ORDER BY donem)) "
            "/ LAG(konut) OVER (ORDER BY donem)",
            "column_name": "degisim_yuzde",
            "purpose": "aylık yüzde değişim",
        }
    )
    assert res.ok, res.content
    table = workspace.table
    assert len(table) == 3, "satır sayısı değişmemeli"
    assert pd.isna(table["degisim_yuzde"].iloc[0])
    assert table["degisim_yuzde"].iloc[1] == pytest.approx(10.0)
    assert table["degisim_yuzde"].iloc[2] == pytest.approx(10.0)


def test_compute_column_veri_degistiren_ifadeyi_reddeder(workspace: AnalysisWorkspace) -> None:
    tool = WorkspaceComputeColumnTool(workspace)
    res = tool.validate_and_run(
        {"expression": "(SELECT 1); DROP TABLE analiz", "column_name": "kotu", "purpose": "test"}
    )
    assert not res.ok
    assert "kotu" not in workspace.columns()


def test_revert_son_islemi_geri_alir(workspace: AnalysisWorkspace) -> None:
    tool = WorkspaceComputeColumnTool(workspace)
    tool.validate_and_run(
        {"expression": "konut * 2", "column_name": "iki_kat", "purpose": "test"}
    )
    assert "iki_kat" in workspace.columns()
    assert workspace.revert() is True
    assert "iki_kat" not in workspace.columns()
