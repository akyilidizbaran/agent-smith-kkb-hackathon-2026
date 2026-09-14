"""K02-T09 (A24): Silver değiştikten sonra bayat Gold tablosundan sayı verilmez — sorgu reddedilir, eski değer dönmez."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.lakehouse import LakehouseQueryTool  # noqa: E402
from tests.test_silver_lakehouse import _gold_fixture  # noqa: E402


def _tool(lake):
    ws = AnalysisWorkspace()
    return LakehouseQueryTool(lake, ws, SimpleNamespace(active_question="çeyreklik konut kredisi", user_text=""), gold_available=True), ws


def test_bayat_gold_tablosu_reddedilir_eski_deger_donmez(tmp_path: Path) -> None:
    lake = _gold_fixture(tmp_path, stale=True)
    assert lake.stale_gold_tables() == ["gold.konut_ceyreklik"]
    tool, ws = _tool(lake)
    r = tool.validate_and_run({"sql": "SELECT period_end, value FROM gold.konut_ceyreklik", "purpose": "çeyreklik"})
    assert not r.ok and r.error.error_code == "GOLD_STALE" and not r.error.is_retryable
    assert not ws.has_table and "121" not in r.content and "gold_align" in r.content


def test_guncel_gold_tablosu_sorgulanir(tmp_path: Path) -> None:
    lake = _gold_fixture(tmp_path, stale=False)
    assert lake.stale_gold_tables() == []
    tool, ws = _tool(lake)
    r = tool.validate_and_run({"sql": "SELECT period_end, value FROM gold.konut_ceyreklik", "purpose": "çeyreklik"})
    assert r.ok, r.content
    assert ws.has_table and float(ws.table["value"].iloc[0]) == 121.0
