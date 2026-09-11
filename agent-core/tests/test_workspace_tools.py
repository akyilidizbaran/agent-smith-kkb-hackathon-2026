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
    """Sabit bir sonuç ve iki kolonlu bir katalog kaydı sunar."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def get_dataset(self, dataset_id: str):
        from datetime import date

        from kkb_agent.contracts.catalog import (
            ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency,
        )

        return DatasetSpec(
            dataset_id=dataset_id, name="t", description="t", source="TEST",
            frequency=Frequency.MONTHLY, time_column="donem", grain=["donem"],
            columns=[
                ColumnSpec(name="donem", role=ColumnRole.TIME, dtype="DATE", description="d"),
                ColumnSpec(name="deger", role=ColumnRole.MEASURE, dtype="DOUBLE", description="v"),
                ColumnSpec(name="kalem", role=ColumnRole.DIMENSION, dtype="VARCHAR", description="k"),
            ],
            coverage=Coverage(start=date(2021, 1, 1), end=date(2026, 6, 1)),
        )

    def series_sql(self, dataset_id, *, key_column, value_column,
                   filter_column=None, filter_value=None):
        """Adaptör sözleşmesi: kolonları katalogla doğrular, fiziksel SQL'i üretir."""
        from kkb_agent.contracts.lakehouse import LakehouseError

        valid = {c.name for c in self.get_dataset(dataset_id).columns}
        for field, name in (("key_column", key_column), ("value_column", value_column),
                            ("filter_column", filter_column)):
            if name and name not in valid:
                raise LakehouseError(
                    f"{field}='{name}' {dataset_id} tablosunda yok. "
                    f"Mevcut kolonlar: {', '.join(sorted(valid))}"
                )
        where = f" WHERE {filter_column} = '{filter_value}'" if filter_column else ""
        return f"SELECT {key_column}, {value_column} FROM {dataset_id}{where}"

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
        {"dataset_id": "x", "key_column": "donem", "value_column": "deger",
         "column_name": "tasit", "join_on": "donem", "purpose": "ikinci seri"}
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
        {"dataset_id": "x", "key_column": "donem", "value_column": "deger",
         "column_name": "eski", "join_on": "donem", "purpose": "kapsam dışı"}
    )
    assert not res.ok
    assert "eşleş" in res.content.lower()
    assert "eski" not in workspace.columns(), "başarısız ekleme tabloyu kirletmemeli"


def test_olmayan_kolon_katalogla_yakalanir(workspace: AnalysisWorkspace) -> None:
    """Model var olmayan bir kolon adı veremez — katalog doğrulaması engeller."""
    lake = FakeLakehouse(pd.DataFrame({"donem": [], "deger": []}))
    tool = WorkspaceAddColumnTool(lake, workspace)
    res = tool.validate_and_run(
        {"dataset_id": "x", "key_column": "donem", "value_column": "olmayan_kolon",
         "column_name": "yeni", "join_on": "donem", "purpose": "y"}
    )
    assert not res.ok
    assert "olmayan_kolon" in res.content and "Mevcut kolonlar" in res.content


def test_yeni_sutun_adini_kaynak_kolonu_sanma_hatasi(workspace: AnalysisWorkspace) -> None:
    """Model yeni sütunun adını value_column'a yazarsa, hata bunu açıkça söylemeli.

    Ölçülmüş hata modu (G6): serbest SQL alan sürümde model "SELECT donem,
    tasit_kredisi FROM ..." yazdı, ham motor hatasından çıkamadı ve sonunda
    analiz tablosunu yeniden kurdu.
    """
    lake = FakeLakehouse(pd.DataFrame({"donem": [], "deger": []}))
    tool = WorkspaceAddColumnTool(lake, workspace)
    res = tool.validate_and_run(
        {"dataset_id": "x", "key_column": "donem", "value_column": "tasit_kredisi",
         "column_name": "tasit_kredisi", "join_on": "donem", "purpose": "test"}
    )
    assert not res.ok
    assert "YENİ sütunun adı" in res.content
    assert "tasit_kredisi" not in workspace.columns()


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
