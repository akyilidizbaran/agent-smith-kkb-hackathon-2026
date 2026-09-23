"""HTTP 200 + an HTML denial is not a successfully downloaded, corrupt PDF."""
from types import SimpleNamespace

import pytest

from kkb_agent.builder.ingest import LakehouseCLI
from kkb_agent.core.access_policy import classify_access
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.tools.ingest import IngestFromUrlTool
from kkb_agent.tools.web import WebUrlTool
from kkb_agent.vision.ocr import is_document
from kkb_agent.web.html import extract_page
from tests.test_ingest_tool import FakeRunner, SpyLakehouse
from tests.test_web import Resp, Session

URL = "https://reports.example/report.pdf"
REJECTED = (b"<html><head><title>Request Rejected</title></head><body>"
            b"The requested URL was rejected. Please consult with your administrator."
            b"<br>Your support ID is: 12345</body></html>")


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])


def no_ocr(*args, **kwargs):
    pytest.fail("An HTML denial/landing page must not be passed to OCR")


def test_http_200_rejection_is_blocked_with_evidence():
    result = classify_access(URL, http_status=200, body_excerpt=REJECTED.decode(), environ={})
    assert not result.ok and result.reason == "bot_challenge"
    assert result.evidence.http_status == 200
    assert "the requested url was rejected" in result.evidence.markers
    assert "dosyanın bozuk olduğunu göstermez" in result.message


def test_read_tool_reports_access_failure_without_ocr(monkeypatch, tmp_path):
    monkeypatch.setattr("kkb_agent.vision.ocr.ocr_document", no_ocr)
    tool = WebUrlTool(AnalysisWorkspace(), registry=SimpleNamespace(user_text=URL, active_question=URL),
                      session=Session({URL: Resp(200, REJECTED)}), ocr=object(), allowed_local_root=tmp_path)
    result = tool.validate_and_run({"url": URL, "pages": "4", "purpose": "Read page 4"})
    assert not result.ok and result.error.error_code == "ACCESS_BLOCKED"
    assert result.error.terminal is True
    assert "Request Rejected" in result.content
    assert not result.artifacts["web"]["visited"]
    assert result.artifacts["web"]["blocked"][0]["reason"] == "bot_challenge"


def test_ingestion_is_blocked_before_staging_or_cli(monkeypatch, tmp_path):
    monkeypatch.setattr("kkb_agent.builder.web_source.ocr_document", no_ocr)
    core = tmp_path / "core"
    (core / "src/lakehouse").mkdir(parents=True)
    (core / "src/lakehouse/cli.py").write_text("# fixture")
    runner = FakeRunner()
    tool = IngestFromUrlTool(SpyLakehouse(), LakehouseCLI(core, tmp_path / "db", tmp_path, runner=runner),
        allowed_root=tmp_path / "incoming", registry=SimpleNamespace(user_text=f"{URL} kaydet", active_question=URL),
        session=Session({URL: Resp(200, REJECTED)}), ocr=object())
    result = tool.validate_and_run({"locator": URL, "name": "Report", "pages": "4"})
    assert not result.ok and result.error.error_code == "ACCESS_BLOCKED"
    assert not runner.calls and not (tmp_path / "incoming").exists()


@pytest.mark.parametrize("media", ["text/html", "application/xhtml+xml", "application/pdf", ""])
def test_html_body_is_not_treated_as_pdf_even_with_wrong_mime(monkeypatch, media):
    monkeypatch.setattr("kkb_agent.vision.ocr.ocr_document", no_ocr)
    page = extract_page(b"<html><head><title>Document moved</title></head><body>New location</body></html>",
                        media, URL, ocr=object())
    assert page.kind == "html" and page.title == "Document moved"
    assert "OCR" not in page.text


def test_document_type_keeps_pdf_and_image_support():
    assert not is_document("text/html", URL)
    assert is_document("application/octet-stream", URL)
    assert is_document("application/pdf", "https://reports.example/download/42")
    assert is_document("image/png", "https://reports.example/image")


def test_real_pdf_signature_beats_incorrect_html_header(monkeypatch):
    sentinel = object()
    monkeypatch.setattr("kkb_agent.vision.ocr.ocr_document", lambda *a, **k: sentinel)
    monkeypatch.setattr("kkb_agent.web.html.extract_ocr_page", lambda url, doc: doc)
    assert extract_page(b"%PDF-1.7\n", "text/html", URL, ocr=object()) is sentinel
