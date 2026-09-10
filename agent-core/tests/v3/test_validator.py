"""Sınır doğrulayıcı: üç katman, araç gövdesine girmeden yakalar."""

from __future__ import annotations

import pandas as pd

from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent_v3.core.validator import ToolRegistry
from kkb_agent_v3.tools.lakehouse import (
    LakehouseDescribeTool,
    LakehouseDistinctValuesTool,
    LakehouseQueryTool,
)
from kkb_agent_v3.tools.workspace import workspace_tools

from .conftest import StubLakehouse


def _registry(lh: StubLakehouse, question: str = "") -> tuple[ToolRegistry, AnalysisWorkspace]:
    ws = AnalysisWorkspace()
    reg = ToolRegistry()
    reg.register_all([LakehouseDescribeTool(lh), LakehouseDistinctValuesTool(lh),
                      LakehouseQueryTool(lh, ws, reg), *workspace_tools(lh, ws)])
    reg.active_question = question
    return reg, ws


def test_sema_katmani_invalid_args(lakehouse: StubLakehouse) -> None:
    reg, _ = _registry(lakehouse)
    r = reg.execute("lakehouse_query", {"purpose": "x"})  # sql eksik
    assert not r.ok and r.error_code == "INVALID_ARGS" and r.error.layer == "schema"
    assert "sql" in r.content
    assert lakehouse.calls == []  # gövde çalışmadı


def test_bilinmeyen_arac(lakehouse: StubLakehouse) -> None:
    reg, _ = _registry(lakehouse)
    r = reg.execute("lakehouse_qeury", {"sql": "SELECT 1"})
    assert r.error_code == "UNKNOWN_TOOL" and "lakehouse_query" in r.error.candidates


def test_referans_katmani_series_not_found_adaylarla(lakehouse: StubLakehouse) -> None:
    reg, _ = _registry(lakehouse)
    r = reg.execute("lakehouse_describe", {"dataset_id": "test_kredi"})
    assert r.error_code == "SERIES_NOT_FOUND" and r.error.layer == "reference"
    assert r.error.candidates == ["test_krediler"]


def test_referans_katmani_column_not_found(lakehouse: StubLakehouse) -> None:
    reg, _ = _registry(lakehouse)
    r = reg.execute("lakehouse_distinct_values", {"dataset_id": "test_krediler", "column": "kalemm"})
    assert r.error_code == "COLUMN_NOT_FOUND" and "kalem" in r.error.candidates


def test_kapsam_disi_retry_edilmez(lakehouse: StubLakehouse) -> None:
    reg, _ = _registry(lakehouse, question="2015 yılında bakiye ne kadardı?")
    r = reg.execute("lakehouse_query", {
        "sql": "SELECT * FROM test_krediler WHERE EXTRACT(year FROM donem) = 2015", "purpose": "x"})
    assert r.error_code == "OUT_OF_COVERAGE" and r.error.is_retryable is False
    assert "2021-01-31" in r.content and "2026-06-30" in r.content
    assert lakehouse.calls == []


def test_donem_filtresi_eksikse_reddedilir(lakehouse: StubLakehouse) -> None:
    reg, _ = _registry(lakehouse, question="2025 yılında aylık göster")
    r = reg.execute("lakehouse_query", {"sql": "SELECT donem, toplam FROM test_krediler", "purpose": "x"})
    assert r.error_code == "MISSING_PERIOD_FILTER" and "2025" in r.error.hint


def test_double_count_alt_toplam(lakehouse: StubLakehouse) -> None:
    reg, _ = _registry(lakehouse, question="2025")
    r = reg.execute("lakehouse_query", {
        "sql": "SELECT donem, SUM(toplam) AS t FROM test_krediler WHERE EXTRACT(year FROM donem)=2025 GROUP BY donem",
        "purpose": "x"})
    assert r.error_code == "DOUBLE_COUNT" and r.error.is_retryable and "is_alt_toplam" in r.error.hint
    # bayrak filtresi ya da açık kalem seçimi varsa geçer
    for ok_sql in (
        "SELECT donem, SUM(toplam) FROM test_krediler WHERE is_alt_toplam = FALSE AND EXTRACT(year FROM donem)=2025 GROUP BY donem",
        "SELECT donem, SUM(toplam) FROM test_krediler WHERE kalem IN ('Kalem A','Kalem B') AND EXTRACT(year FROM donem)=2025 GROUP BY donem",
        "SELECT donem, toplam FROM test_krediler WHERE kalem = 'Kalem A' AND EXTRACT(year FROM donem)=2025",
    ):
        assert reg.execute("lakehouse_query", {"sql": ok_sql, "purpose": "x"}).ok, ok_sql


def test_politika_katmani_unsafe_sql(lakehouse: StubLakehouse) -> None:
    reg, _ = _registry(lakehouse, question="2025")
    r = reg.execute("lakehouse_query", {"sql": "DROP TABLE test_krediler", "purpose": "x"})
    assert r.error_code == "UNSAFE_SQL" and r.error.layer == "policy" and r.error.is_retryable is False
    r2 = reg.execute("lakehouse_query", {
        "sql": "SELECT * FROM read_csv('/etc/passwd') WHERE 2025=2025", "purpose": "x"})
    assert r2.error_code == "UNSAFE_SQL"


def test_bos_sonuc_empty_dataset(lakehouse: StubLakehouse) -> None:
    lh = StubLakehouse(pd.DataFrame())
    reg, ws = _registry(lh, question="2025")
    r = reg.execute("lakehouse_query", {
        "sql": "SELECT * FROM test_krediler WHERE EXTRACT(year FROM donem) = 2025 AND kalem='yok'", "purpose": "x"})
    assert r.error_code == "EMPTY_DATASET" and r.error.is_retryable
    assert not ws.has_table


def test_basarili_sorgu_tabloyu_kurar(lakehouse: StubLakehouse) -> None:
    reg, ws = _registry(lakehouse, question="2025")
    r = reg.execute("lakehouse_query", {
        "sql": "SELECT donem, toplam FROM test_krediler WHERE EXTRACT(year FROM donem) = 2025", "purpose": "aylık"})
    assert r.ok and ws.has_table and len(ws.table) == 2
    assert "toplam = milyon TL" in r.content


def test_workspace_adaptoru_hatayi_koda_cevirir(lakehouse: StubLakehouse) -> None:
    reg, ws = _registry(lakehouse)
    r = reg.execute("workspace_compute_column", {"expression": "toplam * 2", "column_name": "x", "purpose": "p"})
    assert r.error_code == "WORKSPACE_EMPTY"
    r = reg.execute("lakehouse_query", {"sql": "SELECT donem, toplam FROM test_krediler", "purpose": "aylık"})
    assert r.ok
    r = reg.execute("workspace_compute_column", {"expression": "DROP TABLE x", "column_name": "y", "purpose": "p"})
    assert r.error_code == "POLICY_VIOLATION" and r.error.is_retryable is False
    r = reg.execute("workspace_compute_column", {"expression": "toplam * 2", "column_name": "iki_kat", "purpose": "p"})
    assert r.ok and "iki_kat" in ws.columns()
