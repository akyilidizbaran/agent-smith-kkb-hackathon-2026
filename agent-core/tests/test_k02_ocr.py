"""K02-T06 (A12): düşük kaliteli OCR tablosu aktif tablo olmaz; açık kabulle yüklenirse bile uyarı taşır ve sayılar doğrulanmış
sayılmaz."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.web import WebUrlTool  # noqa: E402
from kkb_agent.vision.ocr import OcrClient  # noqa: E402
from tests.test_vision import OcrSession, Resp, Session, _blank_pdf  # noqa: E402

URL = "https://site.example/tarama.pdf"
BAD_OCR = ("<|det|>table [0,0,1,1]<|/det|><table><tr><td>Val</td><td>Toplinn</td><td>Oct</td></tr>"
           "<tr><td>2O25</td><td>l7582</td><td>-</td></tr><tr><td>2O24</td><td>x</td><td>4O</td></tr></table>")


def _tool(user_text: str) -> tuple[WebUrlTool, AnalysisWorkspace]:
    s = Session({URL: Resp(200, _blank_pdf(1), ctype="application/pdf", url=URL)})
    client = OcrClient(base_url="https://mia.example/v1", api_key="k", model="ocr", session=OcrSession(BAD_OCR))
    ws = AnalysisWorkspace()
    reg = SimpleNamespace(active_question=user_text, user_text=user_text, sanctioned_locators=set())
    return WebUrlTool(ws, registry=reg, session=s, ocr=client), ws


def test_dusuk_kaliteli_ocr_tablosu_yuklenmez() -> None:
    tool, ws = _tool(f"{URL} belgesindeki tabloyu oku")
    r = tool.validate_and_run({"url": URL, "purpose": "tablo", "table_index": 0})
    assert not r.ok and r.error.error_code == "LOW_QUALITY_SOURCE" and not r.error.is_retryable
    assert not ws.has_table and "kalite: belirsiz" in r.content and "DİKKAT" in r.content


def test_acik_kabulle_yuklenir_ama_uyari_tasir() -> None:
    tool, ws = _tool(f"{URL} belgesindeki tabloyu doğrulanmamış olsa da kullan")
    r = tool.validate_and_run({"url": URL, "purpose": "tablo", "table_index": 0})
    assert r.ok and ws.has_table
    prov = ws.column_provenance(ws.columns()[0])
    assert any(w.startswith("DİKKAT") for w in prov.warnings), "bütün DİKKAT notları provenance'ta"
