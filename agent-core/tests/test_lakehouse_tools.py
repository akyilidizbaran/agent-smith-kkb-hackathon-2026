"""Lakehouse araçlarının LLM'siz doğrulaması.

Buradaki testlerin varlık sebebi somut: kapsam kontrolünü ekledim ama `re`
import'unu unutmuştum. Araç sessizce hata döndürdü, model bunu "SQL hatası"
sanıp kullanıcıya hata ayıklama tavsiyesi yazdı. Kusuru ancak uçtan uca
koşarken, dakikalar sonra fark ettim. Bu sınıf hataları saniyeler içinde
yakalamak için araçların kendisi doğrudan test edilir.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.catalog import (  # noqa: E402
    ColumnRole,
    ColumnSpec,
    Coverage,
    DatasetSpec,
    Frequency,
)
from kkb_agent.contracts.lakehouse import QueryProvenance, QueryResult  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.lakehouse import LakehouseQueryTool  # noqa: E402

SPEC = DatasetSpec(
    dataset_id="test_tablo",
    name="Test",
    description="test",
    source="TEST",
    frequency=Frequency.MONTHLY,
    time_column="donem",
    grain=["donem"],
    columns=[
        ColumnSpec(name="donem", role=ColumnRole.TIME, dtype="DATE", description="dönem"),
        ColumnSpec(
            name="deger", role=ColumnRole.MEASURE, dtype="DOUBLE",
            description="değer", unit="milyon TL",
        ),
    ],
    coverage=Coverage(start=date(2021, 1, 1), end=date(2026, 6, 1)),
)


class StubLakehouse:
    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def list_datasets(self):
        return [SPEC]

    def get_dataset(self, dataset_id: str):
        return SPEC

    def execute_sql(self, sql: str, *, max_rows: int = 10_000):
        return QueryResult(
            data=self._df,
            provenance=QueryProvenance(sql=sql, dataset_ids=["test_tablo"], row_count=len(self._df)),
        )


@pytest.fixture
def empty_tool() -> LakehouseQueryTool:
    return LakehouseQueryTool(StubLakehouse(pd.DataFrame()), AnalysisWorkspace())


def test_kapsam_disi_donem_kesin_dille_bildirilir(empty_tool: LakehouseQueryTool) -> None:
    """Kapsam dışı sorgu 'tekrar dene' değil, 'bu veri yok' demeli.

    Ayrım kritik: 'filtreleri kontrol et' mesajı modeli denemeye devam ettirip
    adım limitini yakıyordu.
    """
    res = empty_tool.validate_and_run(
        {"sql": "SELECT * FROM test_tablo WHERE EXTRACT(year FROM donem) = 2015",
         "purpose": "kapsam dışı"}
    )
    assert res.ok
    assert "bulunmuyor" in res.content.lower()
    assert "2021-01-01" in res.content, "kullanıcıya mevcut aralık bildirilmeli"
    assert "başka sorgu deneme" in res.content.lower() or "sorgu deneme" in res.content.lower()


def test_kapsam_ici_bos_sonuc_filtreye_yonlendirir(empty_tool: LakehouseQueryTool) -> None:
    """Dönem kapsam içindeyse boş sonucun sebebi filtredir; model denemeye devam etmeli."""
    res = empty_tool.validate_and_run(
        {"sql": "SELECT * FROM test_tablo WHERE kalem = 'olmayan' AND donem >= '2025-01-01'",
         "purpose": "yanlış filtre"}
    )
    assert res.ok
    assert "bulunmuyor" not in res.content.lower()
    assert "distinct_values" in res.content


def test_kismi_kapsam_disi_engellemez(empty_tool: LakehouseQueryTool) -> None:
    """2020-2025 aralığı sorulduysa veri kısmen var; 'veri yok' denmemeli."""
    res = empty_tool.validate_and_run(
        {"sql": "SELECT * FROM test_tablo WHERE donem BETWEEN '2020-01-01' AND '2025-12-31'",
         "purpose": "kısmi kapsam"}
    )
    assert "bulunmuyor" not in res.content.lower()


def test_sonucta_birimler_bildirilir() -> None:
    """Model birim çevirisi yapmasın diye birim etiketi sonuca eklenir."""
    df = pd.DataFrame({"donem": pd.to_datetime(["2025-01-01"]), "deger": [42.0]})
    tool = LakehouseQueryTool(StubLakehouse(df), AnalysisWorkspace())
    res = tool.validate_and_run({"sql": "SELECT donem, deger FROM test_tablo", "purpose": "x"})
    assert res.ok
    assert "deger = milyon TL" in res.content


def test_basarili_sorgu_analiz_tablosunu_kurar() -> None:
    df = pd.DataFrame({"donem": pd.to_datetime(["2025-01-01"]), "deger": [42.0]})
    ws = AnalysisWorkspace()
    tool = LakehouseQueryTool(StubLakehouse(df), ws)
    tool.validate_and_run(
        {"sql": "SELECT donem, deger FROM test_tablo", "purpose": "ana sonuç",
         "as_active_table": True}
    )
    assert ws.has_table and len(ws.table) == 1
