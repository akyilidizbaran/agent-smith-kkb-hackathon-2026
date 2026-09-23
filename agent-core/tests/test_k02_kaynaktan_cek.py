"""K02-T12 (A30): Architect yüklü aralık dışını kayıtlı kaynağından çeker (run kayıtlı toplu betik + Silver); kaynak erişilemezse
sebep dürüstçe döner, Silver yenilenmez; Analyst'te araç yok."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.builder.ingest import LakehouseCLI  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.tools.ingest_source import IngestSourceTool  # noqa: E402
from tests.test_promote_tool import Lake  # noqa: E402


class ReportRunner:
    def __init__(self, status="ok", code=0, error=None):
        self.calls: list[list[str]] = []
        self.status, self.code, self.error = status, code, error

    def __call__(self, cmd, cwd):
        self.calls.append(list(cmd))
        if "scripts/run_catalog_ingestion.py" in cmd:
            report = Path(cmd[cmd.index("--report") + 1])
            report.write_text(json.dumps({"outcomes": [{"series_id": cmd[cmd.index("--only") + 1], "status": self.status,
                                                        "run_id": "r-1", "new": 3, "rows_out": 3, "error": self.error}]}))
            return self.code, "", ""
        return 0, "status: success", ""


@pytest.fixture
def make(tmp_path: Path):
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")

    def build(runner, message):
        cli = LakehouseCLI(core_dir=tmp_path / "lakehouse-core", database=tmp_path / "lh.duckdb", data_root=tmp_path, runner=runner)
        lake = Lake()
        reg = SimpleNamespace(current_message=message, active_question=message, get=lambda n: None)
        return IngestSourceTool(lake, cli, registry=reg), lake
    return build


def test_kaynaktan_ceker_silveri_yeniler_ve_yeniden_yukler(make) -> None:
    runner = ReportRunner()
    tool, lake = make(runner, "2015 aralık konut kredisini kaynaktan çek")
    r = tool.validate_and_run({"series_id": "bddk_monthly:konut", "start": "2015-12-01", "end": "2015-12-31", "purpose": "2015"})
    assert r.ok, r.content
    fetch, silver, gold = runner.calls
    assert fetch[fetch.index("--only") + 1] == "bddk_monthly:konut" and fetch[fetch.index("--start") + 1] == "2015-12-01"
    assert "silver" in silver and lake.events == ["close", "reload"] and "KAYNAKTAN ÇEKİLDİ" in r.content
    assert "gold" in gold and "Silver ve Gold yeniden kuruldu" in r.content, "Silver değişince Gold da yenilenir (GOLD_STALE ölçümü)"


def test_kaynak_erisilemezse_sebep_doner_silver_yenilenmez(make) -> None:
    runner = ReportRunner(status="failed", code=1, error="SOURCE_UNAVAILABLE: GET https://www.bddk.org.tr failed (timeout)")
    tool, lake = make(runner, "2015 verisini kaynaktan getir")
    r = tool.validate_and_run({"series_id": "bddk_monthly:konut", "start": "2015-12-01", "end": "2015-12-31", "purpose": "2015"})
    assert not r.ok and r.error.layer == "access" and "SOURCE_UNAVAILABLE" in r.content
    assert len(runner.calls) == 1 and lake.events == ["close", "reload"], "Silver çalışmadı, okuyucu geri açıldı"


def test_politika_niyet_katalog_ve_tarih(make) -> None:
    runner = ReportRunner()
    tool, _ = make(runner, "2015 konut kredisi ne kadardı?")
    assert tool.validate_and_run({"series_id": "bddk_monthly:konut", "start": "2015-12-01", "end": "2015-12-31", "purpose": "x"}).error.error_code == "INTENT_REQUIRED"
    tool2, _ = make(runner, "kaynaktan çek")
    assert tool2.validate_and_run({"series_id": "yok:seri", "start": "2015-12-01", "end": "2015-12-31", "purpose": "x"}).error.error_code == "DATASET_NOT_FOUND"
    assert tool2.validate_and_run({"series_id": "adhoc:sicaklik", "start": "2015-12-01", "end": "2015-12-31", "purpose": "x"}).error.error_code == "INVALID_ARGS"
    assert tool2.validate_and_run({"series_id": "bddk_monthly:konut", "start": "2016-12-01", "end": "2015-12-31", "purpose": "x"}).error.error_code == "INVALID_ARGS"
    assert runner.calls == []


def test_analyst_kayit_defterinde_arac_yok() -> None:
    assert ToolRegistry().execute("ingest_source", {}).error.error_code == "UNKNOWN_TOOL"
