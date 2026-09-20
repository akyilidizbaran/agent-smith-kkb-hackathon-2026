"""workspace_query: aktif tablo üzerinde SQL, veri havuzuna dokunmadan; provenance zinciri korunur."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.lakehouse import QueryProvenance  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.workspace_query import WorkspaceQueryTool  # noqa: E402


def _ws() -> AnalysisWorkspace:
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"year": [1999.0, 2000.0, 2001.0, 2002.0], "population": [60.0, 62.0, 64.0, 66.0]}),
                 description="nüfus", provenance=QueryProvenance(sql="web_url https://owid.example/p.csv tablo#0",
                                                                dataset_ids=[], sources=["web — OWID"], source_urls=["https://owid.example/p.csv"]))
    return ws


def test_bakis_modu_tabloyu_degistirmez_kirpma_modu_degistirir() -> None:
    ws = _ws()
    peek = WorkspaceQueryTool(ws).validate_and_run({"sql": "SELECT max(population) AS en_yuksek FROM t", "purpose": "özet"})
    assert peek.ok and "AKTİF TABLO DEĞİŞMEDİ" in peek.content and len(ws.table) == 4
    r = WorkspaceQueryTool(ws).validate_and_run({"sql": "SELECT year, population FROM t WHERE year >= 2000 ORDER BY year",
                                                 "purpose": "2000 sonrası", "as_active_table": True})
    assert r.ok and len(ws.table) == 3 and "artık AKTİF TABLO bu" in r.content
    prov = ws.column_provenance("population")
    assert prov.sql.startswith("workspace_query:") and prov.source_urls == ["https://owid.example/p.csv"]
    assert ws.revert() and len(ws.table) == 4   # önceki tablo geçmişte


def test_aktif_tablo_yoksa_ve_t_okunmuyorsa_durur() -> None:
    r = WorkspaceQueryTool(AnalysisWorkspace()).validate_and_run({"sql": "SELECT 1 FROM t", "purpose": "x"})
    assert not r.ok and r.error.error_code == "NO_ACTIVE_TABLE"
    r2 = WorkspaceQueryTool(_ws()).validate_and_run({"sql": "SELECT * FROM silver.fact_observation", "purpose": "x"})
    assert not r2.ok and r2.error.error_code == "INVALID_ARGS"


def test_tehlikeli_sql_reddedilir_ve_sql_hatasi_geri_doner() -> None:
    r = WorkspaceQueryTool(_ws()).validate_and_run({"sql": "DELETE FROM t", "purpose": "x"})
    assert not r.ok and r.error.error_code == "UNSAFE_SQL"
    r2 = WorkspaceQueryTool(_ws()).validate_and_run({"sql": "SELECT yok FROM t", "purpose": "x"})
    assert not r2.ok and r2.error.error_code == "SQL_FAILED"


def test_union_all_sorgusu_guvenli_calisir_ve_parser_hatasi_recoverable_doner() -> None:
    ws = _ws()
    tool = WorkspaceQueryTool(ws)
    valid = (
        "(SELECT year, population FROM t WHERE year <= 2000 ORDER BY year LIMIT 2) "
        "UNION ALL "
        "(SELECT year, population FROM t WHERE year > 2000 ORDER BY year LIMIT 2)"
    )
    result = tool.validate_and_run({"sql": valid, "purpose": "iki aralığı birleştir"})
    assert result.ok, result.content
    assert len(result.data) == 4

    malformed = (
        "SELECT year, population FROM t WHERE year <= 2000 ORDER BY year LIMIT 2 "
        "UNION ALL SELECT year, population FROM t WHERE year > 2000"
    )
    error = tool.validate_and_run({"sql": malformed, "purpose": "iki aralığı birleştir"})
    assert not error.ok and error.error.error_code == "SQL_SYNTAX_ERROR"
    assert error.error.is_retryable
    assert "UNSAFE_SQL" not in error.content
