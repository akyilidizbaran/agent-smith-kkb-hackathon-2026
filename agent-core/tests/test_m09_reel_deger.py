"""M09 (ADR-0058): reel dönüşüm deterministik; baz/kapsam/endeks tipi/aylık hizalama denetimli (A04)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.catalog import ColumnRole, SemanticType  # noqa: E402
from kkb_agent.contracts.lakehouse import LakehouseError, QueryProvenance  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.real_value import RealValueParams, WorkspaceRealValueTool  # noqa: E402


class Lake:
    def __init__(self, index: pd.DataFrame, semantic=SemanticType.INDEX):
        self.index, self.semantic = index, semantic

    def get_dataset(self, dataset_id):
        if dataset_id != "evds:TUFE":
            raise LakehouseError(f"'{dataset_id}' yok")
        return SimpleNamespace(time_column="observation_date",
                               columns=[SimpleNamespace(name="value", role=ColumnRole.MEASURE, semantic_type=self.semantic)])

    def series_sql(self, dataset_id, **kw):
        return "SELECT observation_date, value FROM silver.fact_observation WHERE series_id='evds:TUFE'"

    def execute_sql(self, sql):
        return SimpleNamespace(data=self.index, provenance=QueryProvenance(sql=sql, dataset_ids=["evds:TUFE"], sources=["EVDS TÜFE"]))

    def search_datasets(self, q, limit=6):
        return []


def _ws(dates, values):
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"observation_date": pd.to_datetime(dates), "bakiye": values}), description="nominal",
                 provenance=QueryProvenance(sql="SELECT …", dataset_ids=["bddk_monthly:1534_Toplam"], sources=["BDDK"]))
    return ws


IDX = pd.DataFrame({"observation_date": [date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)], "value": [10.0, 11.0, 12.1]})


def _p(**kw):
    base = dict(value_column="bakiye", index_dataset_id="evds:TUFE", base_period="2025-03", column_name="reel_bakiye", purpose="test")
    base.update(kw); return RealValueParams(**base)


def test_a04_reel_deger_formulu_ve_tablo_bozulmaz() -> None:
    ws = _ws(["2025-01-31", "2025-02-28", "2025-03-31"], [100.0, 110.0, 121.0])
    tool = WorkspaceRealValueTool(Lake(IDX), ws)
    assert tool.validate_refs(_p()) is None
    r = tool.run(_p())
    t = ws.table
    assert r.ok and t["reel_bakiye"].tolist() == [121.0, 121.0, 121.0] and t["reel_bakiye_endeks"].tolist() == [10.0, 11.0, 12.1]
    assert t["bakiye"].tolist() == [100.0, 110.0, 121.0] and len(t) == 3, "nominal kolon ve satırlar korunur"
    assert "baz 2025-03 = 12.1" in r.content
    prov = ws.column_provenance("reel_bakiye")
    assert prov.sql.startswith("türetilmiş: reel_değer") and "evds:TUFE" in prov.dataset_ids and "bddk_monthly:1534_Toplam" in prov.dataset_ids
    assert ws.column_provenance("reel_bakiye_endeks").sql.startswith("SELECT"), "endeks kolonu gerçek SQL'e bağlı"


def test_baz_kapsam_disi_ve_endeks_olmayan_seri_reddedilir() -> None:
    ws = _ws(["2025-01-31", "2025-02-28"], [100.0, 110.0])
    out = WorkspaceRealValueTool(Lake(IDX), ws).run(_p(base_period="2019-12"))
    assert not out.ok and out.error.error_code == "OUT_OF_COVERAGE" and "2025-01 → 2025-03" in out.error.message
    err = WorkspaceRealValueTool(Lake(IDX, semantic=SemanticType.STOCK), ws).validate_refs(_p())
    assert err is not None and "fiyat endeksi değil" in err.message
    err2 = WorkspaceRealValueTool(Lake(IDX), ws).validate_refs(_p(index_dataset_id="evds:YOK"))
    assert err2.error_code == "DATASET_NOT_FOUND"


def test_kapsam_disi_satir_bos_kalir_haftalik_tablo_reddedilir() -> None:
    ws = _ws(["2025-02-28", "2025-03-31", "2025-04-30"], [110.0, 121.0, 130.0])
    r = WorkspaceRealValueTool(Lake(IDX), ws).run(_p())
    t = ws.table
    assert r.ok and pd.isna(t["reel_bakiye"].iloc[2]) and "1 satırda endeks yok" in r.content
    weekly = _ws(["2025-03-07", "2025-03-14"], [1.0, 2.0])
    out = WorkspaceRealValueTool(Lake(IDX), weekly).run(_p())
    assert not out.ok and "aynı aya düşen" in out.error.message
    zero = pd.DataFrame({"observation_date": [date(2025, 3, 31)], "value": [0.0]})
    out2 = WorkspaceRealValueTool(Lake(zero), _ws(["2025-03-31"], [1.0])).run(_p())
    assert not out2.ok and "sıfır" in out2.error.message
