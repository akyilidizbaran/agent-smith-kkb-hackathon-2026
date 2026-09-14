"""K02-T03 (A05, ADR-0075): baz yılı doğrulanmamış endeks (KFE) — birim, baz ve dönem denetimi; kaynak kolonlar korunur."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.adapters.silver_lakehouse import SilverLakehouse  # noqa: E402
from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency, SemanticType  # noqa: E402
from kkb_agent.contracts.lakehouse import LakehouseError, QueryProvenance  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.real_value import RealValueParams, WorkspaceRealValueTool  # noqa: E402
from kkb_agent.tools.workspace import AddColumnParams, WorkspaceAddColumnTool  # noqa: E402

KFE, TUFE = "evds:TP.KFE.TR", "evds:TUFE"
IDX = pd.DataFrame({"observation_date": [date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)], "value": [200.0, 220.0, 242.0]})


def _spec(sid: str, confidence: str) -> DatasetSpec:
    return DatasetSpec(
        dataset_id=sid, name=sid, description="endeks", source="evds", frequency=Frequency.MONTHLY,
        time_column="observation_date", grain=["observation_date"],
        columns=[ColumnSpec(name="observation_date", role=ColumnRole.TIME, dtype="DATE", description="dönem"),
                 ColumnSpec(name="value", role=ColumnRole.MEASURE, dtype="DOUBLE", description="değer",
                            semantic_type=SemanticType.INDEX, unit="endeks")],
        coverage=Coverage(start=date(2025, 1, 31), end=date(2025, 3, 31), row_count=3), semantic_confidence=confidence,
    )


class Lake:
    specs = {KFE: _spec(KFE, "derived"), TUFE: _spec(TUFE, "verified")}

    def get_dataset(self, sid):
        if sid not in self.specs:
            raise LakehouseError(f"'{sid}' yok")
        return self.specs[sid]

    def list_datasets(self):
        return list(self.specs.values())

    def series_sql(self, sid, **kw):
        return f"SELECT observation_date, value FROM silver.fact_observation WHERE series_id = '{sid}'"

    def execute_sql(self, sql):
        sid = sql.split("'")[1]
        return SimpleNamespace(data=IDX.copy(), provenance=QueryProvenance(sql=sql, dataset_ids=[sid], sources=[sid]))


def _ws() -> AnalysisWorkspace:
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"observation_date": pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"]), "bakiye": [100.0, 110.0, 121.0]}),
                 description="nominal", provenance=QueryProvenance(sql="SELECT …", dataset_ids=["bddk_monthly:1534_Toplam"], sources=["BDDK"]))
    return ws


def _rv(index: str) -> RealValueParams:
    return RealValueParams(value_column="bakiye", index_dataset_id=index, base_period="2025-03", column_name="reel", purpose="test")


def test_adaptor_katalog_anlam_guvenini_spec_e_tasir() -> None:
    row = (KFE, "evds", "TP.KFE.TR", None, "Konut Fiyat Endeksi", "açıklama", [], [], "monthly", None, "index", "index", "avg",
           None, "derived", date(2016, 1, 31), date(2026, 6, 30), None, "active")
    spec = SilverLakehouse._to_spec(object.__new__(SilverLakehouse), row, 126)
    assert spec.semantic_confidence == "derived" and spec.column("value").semantic_type == SemanticType.INDEX


def test_dogrulanmamis_endeks_reel_donusumde_rizasiz_reddedilir_dogrulanmis_onerilir() -> None:
    ws = _ws()
    tool = WorkspaceRealValueTool(Lake(), ws, registry=SimpleNamespace(current_message="Konut kredisini KFE ile reel yap."))
    assert tool.validate_refs(_rv(KFE)) is None, "endeks tipi doğru; ret anlam güveninden"
    err = tool.check_policy(_rv(KFE))
    assert err is not None and err.error_code == "UNVERIFIED_SEMANTICS" and "baz yılı" in err.message
    assert err.candidates == [TUFE] and not err.is_retryable
    assert tool.check_policy(_rv(TUFE)) is None
    assert "reel" not in ws.table.columns


def test_riza_yalniz_guncel_mesajdan_ve_uyari_karta_ve_kanita_iner() -> None:
    old = SimpleNamespace(current_message="KFE ile reel yap.", user_text="önceki: doğrulanmamış olsa da kullan")
    assert WorkspaceRealValueTool(Lake(), _ws(), registry=old).check_policy(_rv(KFE)) is not None, "önceki turdaki rıza sayılmaz"
    ws = _ws()
    tool = WorkspaceRealValueTool(Lake(), ws, registry=SimpleNamespace(current_message="KFE doğrulanmamış olsa da kullan, reel yap."))
    assert tool.check_policy(_rv(KFE)) is None
    r = tool.run(_rv(KFE))
    assert r.ok and "UYARI" in r.content and "semantic_confidence=derived" in r.content
    assert any("doğrulanmamış" in w for w in ws.column_provenance("reel").warnings)
    assert ws.table["bakiye"].tolist() == [100.0, 110.0, 121.0] and ws.table["reel"].tolist() == [121.0, 121.0, 121.0]


def test_kfe_sutun_eklerken_birim_baz_donem_karti_kaynak_kolonlar_korunur() -> None:
    ws = _ws()
    tool = WorkspaceAddColumnTool(Lake(), ws)
    p = AddColumnParams(dataset_id=KFE, key_column="observation_date", value_column="value", column_name="kfe",
                        join_on="observation_date", purpose="konut fiyat endeksi")
    assert tool.validate_refs(p) is None
    r = tool.run(p)
    assert r.ok
    for part in ("Birim: endeks", "ölçüm tipi: index", "kaynak frekansı: monthly", "Dönem eşleşmesi: 3/3 satır", "baz yılı DOĞRULANMAMIŞ", "UYARI"):
        assert part in r.content, part
    assert ws.table["bakiye"].tolist() == [100.0, 110.0, 121.0] and ws.table["kfe"].tolist() == [200.0, 220.0, 242.0]
    assert list(ws.table.columns) == ["observation_date", "bakiye", "kfe"]
    assert any("semantic_confidence=derived" in w for w in ws.column_provenance("kfe").warnings)

    ws2 = _ws()
    r2 = WorkspaceAddColumnTool(Lake(), ws2).run(AddColumnParams(dataset_id=TUFE, key_column="observation_date", value_column="value",
                                                                 column_name="tufe", join_on="observation_date", purpose="tüfe"))
    assert r2.ok and "katalogda doğrulanmış seri" in r2.content and "UYARI" not in r2.content
    assert not ws2.column_provenance("tufe").warnings
