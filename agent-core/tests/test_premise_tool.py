"""check_premise (tools/premise.py, V3 §3.9): öncül yönü veriden, deterministik; araç kapısı ve ajan geri göndermesi sahte LLM ile."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency, SemanticType  # noqa: E402
from kkb_agent.contracts.lakehouse import LakehouseError, QueryProvenance, QueryResult  # noqa: E402
from kkb_agent.core import tool_gate  # noqa: E402
from kkb_agent.core.agent import AnalyticsAgent  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.tool import Tool, ToolResult  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.llm.base import LLMResponse, ToolCall  # noqa: E402
from kkb_agent.tools.premise import CheckPremiseTool, normalize_direction  # noqa: E402

KONUT, TASIT = "Tüketici Kredileri - Konut", "Tüketici Kredileri - Taşıt"


class FakeLakehouse:
    """Seed'in yerleşimi: tek tablo, kalem kırılımı, dönem sonu tarihleri."""

    def __init__(self) -> None:
        months = pd.date_range("2024-01-31", "2025-12-31", freq="ME")
        rows = []
        for i, d in enumerate(months):
            rows.append((d, KONUT, 480_000 + i * 8_500))                    # sürekli artan
            rows.append((d, TASIT, 100_000 - i * 1_200 if d.year == 2024 else 90_000 + i * 300))   # 2024'te düşen
        self.frame = pd.DataFrame(rows, columns=["donem", "kalem", "toplam"])
        self.spec = DatasetSpec(
            dataset_id="bddk_aylik_krediler", name="BDDK aylık krediler", description="", source="BDDK",
            frequency=Frequency.MONTHLY, time_column="donem", grain=["donem", "kalem"],
            coverage=Coverage(start=date(2024, 1, 31), end=date(2025, 12, 31)),
            columns=[ColumnSpec(name="donem", role=ColumnRole.TIME, dtype="DATE", description=""),
                     ColumnSpec(name="kalem", role=ColumnRole.DIMENSION, dtype="VARCHAR", description=""),
                     ColumnSpec(name="toplam", role=ColumnRole.MEASURE, dtype="DOUBLE", description="", semantic_type=SemanticType.STOCK)],
        )
        self.sql_seen: list[str] = []

    def list_datasets(self):
        return [self.spec]

    def get_dataset(self, dataset_id):
        if dataset_id != self.spec.dataset_id:
            raise LakehouseError(f"'{dataset_id}' bulunamadı.")
        return self.spec

    def series_sql(self, dataset_id, *, key_column, value_column, filter_column=None, filter_value=None):
        self.get_dataset(dataset_id)
        return f"SELECT {key_column}, {value_column} FROM {dataset_id}" + (f" WHERE {filter_column} = '{filter_value}'" if filter_column else "")

    def execute_sql(self, sql, *, max_rows=10_000):
        self.sql_seen.append(sql)
        df = self.frame
        if "WHERE" in sql:
            val = sql.split("= '", 1)[1].rstrip("'")
            df = df[df["kalem"] == val]
        return QueryResult(data=df[["donem", "toplam"]].reset_index(drop=True),
                           provenance=QueryProvenance(sql=sql, dataset_ids=["bddk_aylik_krediler"], sources=["BDDK — test"]))


def _tool() -> tuple[CheckPremiseTool, FakeLakehouse]:
    lake = FakeLakehouse()
    return CheckPremiseTool(lake), lake


def test_yon_normalize() -> None:
    assert normalize_direction("düştüğü için") == "düştü" and normalize_direction("azaldı") == "düştü" and normalize_direction("geriledi") == "düştü"
    assert normalize_direction("arttı") == "arttı" and normalize_direction("yükseldi") == "arttı"
    assert normalize_direction("bilinmez") is None


def test_yanlis_oncul_celisiyor_karti_ilk_son_ve_yapacagin_tasir() -> None:
    tool, lake = _tool()
    r = tool.validate_and_run({"dataset_id": "bddk_aylik_krediler", "value_column": "toplam", "filter_column": "kalem",
                               "filter_value": KONUT, "year": 2025, "claimed_direction": "düştü",
                               "subject": "2025'te konut kredisi bakiyesi düştü"})
    assert r.ok and r.content.startswith("ÖNCÜL [ÇELİŞİYOR]")
    assert "iddia: düştü; veri: arttı" in r.content
    assert "İlk gözlem 2025-01: 582.000 → son gözlem 2025-12: 675.500" in r.content, r.content
    assert "YAPACAĞIN: cevabın İLK cümlesi bu düzeltme olsun" in r.content
    assert r.artifacts["premise"]["verdict"] == "ÇELİŞİYOR" and r.artifacts["premise"]["n"] == 12
    assert r.data is None, "aktif tabloya dokunmaz"
    assert "WHERE kalem = 'Tüketici Kredileri - Konut'" in lake.sql_seen[-1]


def test_dogru_oncul_destekliyor_ve_nedensellik_uyarisi() -> None:
    tool, _ = _tool()
    r = tool.validate_and_run({"dataset_id": "bddk_aylik_krediler", "value_column": "toplam", "filter_column": "kalem",
                               "filter_value": TASIT, "year": 2024, "claimed_direction": "geriledi", "subject": "2024'te taşıt geriledi"})
    assert r.ok and r.content.startswith("ÖNCÜL [DESTEKLİYOR]") and "nedensellik değildir" in r.content
    assert r.artifacts["premise"]["actual"] == "düştü"


def test_kirilimsiz_cagri_ayni_doneme_cok_satir_reddedilir_ve_ipucu_verir() -> None:
    tool, _ = _tool()
    r = tool.validate_and_run({"dataset_id": "bddk_aylik_krediler", "value_column": "toplam", "year": 2025,
                               "claimed_direction": "düştü", "subject": "x"})
    assert not r.ok and r.error.error_code == "INVALID_ARGS" and "filter_column" in r.content and r.error.is_retryable


def test_yetersiz_gozlem_bilinmiyor_ve_referans_hatalari() -> None:
    tool, _ = _tool()
    r = tool.validate_and_run({"dataset_id": "bddk_aylik_krediler", "value_column": "toplam", "filter_column": "kalem",
                               "filter_value": KONUT, "year": 2019, "claimed_direction": "düştü", "subject": "2019"})
    assert r.ok and r.content.startswith("ÖNCÜL [BİLİNMİYOR]") and "0 gözlem" in r.content
    bad = tool.validate_and_run({"dataset_id": "yok", "value_column": "toplam", "claimed_direction": "düştü", "subject": "x"})
    assert not bad.ok and bad.error.error_code == "DATASET_NOT_FOUND"
    col = tool.validate_and_run({"dataset_id": "bddk_aylik_krediler", "value_column": "bakiye", "claimed_direction": "düştü", "subject": "x"})
    assert not col.ok and col.error.error_code == "COLUMN_NOT_FOUND" and col.error.candidates == ["toplam"]
    yon = tool.validate_and_run({"dataset_id": "bddk_aylik_krediler", "value_column": "toplam", "claimed_direction": "belki", "subject": "x"})
    assert not yon.ok and yon.error.error_code == "INVALID_ARGS"


def test_donem_araligi_ile() -> None:
    tool, _ = _tool()
    r = tool.validate_and_run({"dataset_id": "bddk_aylik_krediler", "value_column": "toplam", "filter_column": "kalem",
                               "filter_value": KONUT, "start": "2024-03", "end": "2024-06", "claimed_direction": "arttı", "subject": "x"})
    assert r.ok and "4 gözlem" in r.content and r.artifacts["premise"]["verdict"] == "DESTEKLİYOR"


# ------------------------------------------------------------------ araç kapısı
def test_kapi_oncul_ailesini_yalniz_oncul_sorusunda_acar() -> None:
    reg = {"lakehouse_query", "check_premise", "chart"}
    g = tool_gate.decide("2025'te konut kredisi bakiyesi düştüğü için ihtiyaç kredileri arttı mı?", reg)
    assert "check_premise" in g.allowed and "öncül" in g.opened
    g2 = tool_gate.decide("2024'te taşıt kredileri neden arttı?", reg)
    assert "check_premise" in g2.allowed
    g3 = tool_gate.decide("2025 Aralık konut kredisi bakiyesi ne kadar?", reg)
    assert "check_premise" not in g3.allowed and "öncül" in g3.closed
    assert "clarify" in tool_gate.ALWAYS


# ------------------------------------------------------------------ ajan: araçsız öncül cevabı bir kez geri gönderilir
class _P(BaseModel):
    year: int = 2025


class _DataTool(Tool):
    name = "lakehouse_query"
    description = "sahte"
    Params = _P

    def run(self, params: _P) -> ToolResult:
        df = pd.DataFrame({"donem": ["2025-01-31", "2025-12-31"], "toplam": [512259.0, 678970.0]})
        return ToolResult(content="2 satır.\ndonem toplam\n2025-01-31 512.259\n2025-12-31 678.970", data=df)


class _PremiseStub(Tool):
    name = "check_premise"
    description = "sahte"
    Params = _P
    calls = 0

    def run(self, params: _P) -> ToolResult:
        _PremiseStub.calls += 1
        return ToolResult(content="ÖNCÜL [ÇELİŞİYOR]: iddia: düştü; veri: arttı. 512.259 → 678.970")


class _LLM:
    model = "scripted"

    def __init__(self, turns):
        self.turns, self.n, self.messages = turns, 0, []

    def supports_native_tools(self):
        return True

    def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
        self.messages.append(list(messages))
        t = self.turns[min(self.n, len(self.turns) - 1)]
        self.n += 1
        return t


def test_oncul_sorusunda_arac_cagrilmadan_cevap_bir_kez_geri_gonderilir() -> None:
    reg = ToolRegistry()
    reg.register(_DataTool())
    reg.register(_PremiseStub())
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="lakehouse_query", arguments={})]),
                LLMResponse(content="Konut düştüğü için ihtiyaç arttı."),
                LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="check_premise", arguments={})]),
                LLMResponse(content="Öncül yanlış: konut 2025'te 512.259'dan 678.970'e arttı.")])
    agent = AnalyticsAgent(llm=llm, registry=reg, workspace=AnalysisWorkspace(), max_steps=8, tool_gate=False)
    a = agent.ask("2025'te konut kredisi bakiyesi düştüğü için ihtiyaç kredileri arttı mı?")
    assert any(s.thought and "öncül istendi" in s.thought for s in a.steps), [s.thought for s in a.steps]
    assert _PremiseStub.calls == 1 and "678.970" in a.text
    user_msg = llm.messages[0][-1].content
    assert "check_premise aracıyla doğrula" in user_msg, "ön-koşul satırı aracı adıyla anar"
