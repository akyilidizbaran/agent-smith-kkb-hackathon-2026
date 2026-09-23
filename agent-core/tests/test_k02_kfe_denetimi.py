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


def test_reel_deger_birden_cok_sutunu_tek_cagrida_cevirir_ve_endeksi_bir_kez_ekler() -> None:
    """ADR-0108 (canlı koşu, 23 Eyl): tutarların reel değerini isteyen takipte model yalnız iki sütunu çevirdi; araç
    value_columns ile bütün tutarları tek çağrıda alır, endeks sütunu bir kez eklenir, önceki sütunlar değişmez."""
    ws = _ws()
    ws.add_column("diger", pd.Series([50.0, 55.0, 60.5], index=ws.table.index), description="ikinci tutar")
    before = ws.table[["bakiye", "diger"]].copy()
    tool = WorkspaceRealValueTool(Lake(), ws, registry=SimpleNamespace(current_message="Tutarları reel yap."))
    r = tool.validate_and_run({"value_columns": ["bakiye", "diger"], "index_dataset_id": TUFE, "base_period": "2025-03",
                               "purpose": "test"})
    assert r.ok, r.content
    t = ws.table
    assert {"bakiye_reel", "diger_reel"} <= set(t.columns)
    assert [c for c in t.columns if "endeks" in c] == ["endeks_tufe"]
    assert t["bakiye_reel"].tolist() == [121.0, 121.0, 121.0]            # 100×242/200, 110×242/220, 121×242/242
    assert t[["bakiye", "diger"]].equals(before)


def test_harness_reel_istenip_arac_cagrilmazsa_dogrulanmis_endeksle_kendisi_uygular() -> None:
    """Canlı koşu (23 Eyl): reel dönüşüm istendi, tablo koruma kuralı yeniden kurmayı engelledi, model aracı hiç
    çağırmadı. Harness doğrulanmış endeksle (KFE derived olduğu için TÜFE) önceki turun tablosuna bir kez uygular."""
    from kkb_agent.core.agent import _REQUESTED_CAPABILITIES, AnalyticsAgent
    from kkb_agent.core.registry import ToolRegistry

    ws = _ws()
    registry = ToolRegistry()
    registry.register(WorkspaceRealValueTool(Lake(), ws, registry=SimpleNamespace(current_message="")))
    agent = AnalyticsAgent(llm=SimpleNamespace(model="x", supports_native_tools=lambda: True), registry=registry,
                           workspace=ws, max_steps=4)
    agent._turn_start_generation = ws.generation
    requested = [cap for cap in _REQUESTED_CAPABILITIES if cap[0] == "reel"]
    step, note = agent._auto_real_value("Tutarları 2025-03 fiyatlarıyla reel hale getir.", requested, [], 1)
    assert step.ok and step.tool_args["index_dataset_id"] == TUFE and step.tool_args["value_columns"] == ["bakiye"]
    assert step.tool_args["base_period"] == "2025-03" and "bakiye_reel" in ws.table.columns and "ARAÇ ÇAĞIRMA" in note
    assert agent._auto_real_value("Tutarları reel hale getir.", requested, [step], 2) is None   # bir kez


def test_tablo_yeniden_kurma_engellenince_harness_reel_donusumu_sonraki_adimda_uygular() -> None:
    """Canlı koşu (23 Eyl): reel takibinde model tabloyu yeniden çekmeye çalıştı, engellendi, sonra kaynak reddiyle tur
    kapandı. Harness engelden sonraki ilk adımda reel dönüşümü uygular; model yalnız anlatır."""
    from pydantic import BaseModel as _BM

    from kkb_agent.core.agent import AnalyticsAgent
    from kkb_agent.core.registry import ToolRegistry
    from kkb_agent.core.tool import Tool, ToolResult
    from kkb_agent.llm.base import LLMResponse, ToolCall

    class _QP(_BM):
        sql: str = ""

    class _Query(Tool):
        name = "lakehouse_query"
        description = "sahte sorgu"
        Params = _QP
        calls = 0

        def run(self, params):
            _Query.calls += 1
            return ToolResult(content="çalışmamalıydı")

    class _LLM:
        model = "x"

        def __init__(self):
            self.turns = [LLMResponse(content="", tool_calls=[ToolCall(id="q", name="lakehouse_query", arguments={"sql": "x"})]),
                          LLMResponse(content="Mevduat 2025-03 fiyatlarıyla reel hâle getirildi.")]
            self.n = 0

        def supports_native_tools(self):
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            self.n += 1
            return self.turns[min(self.n - 1, len(self.turns) - 1)]

    ws = _ws()
    registry = ToolRegistry()
    registry.register(_Query())
    registry.register(WorkspaceRealValueTool(Lake(), ws, registry=SimpleNamespace(current_message="")))
    agent = AnalyticsAgent(llm=_LLM(), registry=registry, workspace=ws, max_steps=5, tool_gate=False)
    agent._catalog_specs = lambda: []

    answer = agent.ask("Kredi tablosuna TÜFE ekle ve bakiyeleri 2025-03 fiyatlarıyla göster, reel olsun.")

    assert _Query.calls == 0, "önceki turun tablosunu yeniden kuran sorgu çalışmadı"
    auto = [s for s in answer.steps if s.tool_name == "workspace_real_value"]
    assert auto and auto[0].ok and "harness" in auto[0].thought and "bakiye_reel" in ws.table.columns
