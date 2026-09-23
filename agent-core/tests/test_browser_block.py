"""ADR-0111: gerçek tarayıcıda açılan sayfa bot denetimiyse engel aşılmaz; hızlı ve açık bir erişim sonucu döner.

Canlı arayüz (23 Eyl): dinamik bir rapor sayfası başsız tarayıcıya "Request Rejected" döndürdü; adaptör her çağrıda 30 sn
form öğesi bekleyip sessizce düştü, model aynı adresi üç kez denedi (~100 sn) ve cevap nedeni söylemedi.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.tools.web import WebUrlTool, _manual_export_hint
from kkb_agent.web import browser as B
from kkb_agent.web.fetch import RobotsCache

REJECTED = "<html><head><title>Request Rejected</title></head><body>The requested URL was rejected. " \
           "Please consult with your administrator.</body></html>"
SHELL = "<html><head><title>Rapor</title></head><body><div id='__next'></div></body></html>"


class _Page:
    def __init__(self, html: str) -> None:
        self._html = html
        self.url = "https://rapor.example/istatistik"

    def content(self) -> str:
        return self._html


def test_guard_raises_on_a_rejected_page_and_passes_a_real_page() -> None:
    with pytest.raises(B.BrowserBlocked) as blocked:
        B._guard_block(_Page(REJECTED), "https://rapor.example/istatistik")
    assert blocked.value.outcome.reason == "bot_challenge" and blocked.value.outcome.status == "blocked"
    B._guard_block(_Page("<html><body><table><tr><td>1</td></tr></table></body></html>"), "https://rapor.example/x")


def test_a_blocked_host_is_not_relaunched(monkeypatch) -> None:
    outcome = pytest.importorskip("kkb_agent.core.access_policy").classify_access(
        "https://rapor.example/istatistik", http_status=200, body_excerpt=REJECTED)
    monkeypatch.setitem(B._BLOCKED_HOSTS, "rapor.example", (time.monotonic(), outcome))
    result = B.browser_crawl_result("https://rapor.example/istatistik", "rapor", environ={})
    assert result is not None and not result.pages and result.blocked
    assert result.first is not None and not result.first.ok and result.first.fetch.outcome.reason == "bot_challenge"


def test_web_url_turns_a_browser_block_into_an_access_result_with_the_export_path(monkeypatch) -> None:
    from tests.test_web import Resp, Session

    url = "https://www.tefas.gov.tr/tr/tefas-istatistikleri?tab=volume"
    session = Session({url: Resp(200, SHELL.encode(), url=url)})
    outcome = B.classify_access(url, http_status=200, body_excerpt=REJECTED)
    monkeypatch.setattr(B, "browser_crawl_result", lambda *_a, **_k: B._blocked_result(url, outcome))
    question = f"TEFAS rapor verisini getir {url}"
    tool = WebUrlTool(AnalysisWorkspace(), registry=SimpleNamespace(active_question=question, turn=1),
                      session=session, robots=RobotsCache())
    r = tool.validate_and_run({"url": url, "purpose": "rapor"})
    assert not r.ok and r.error.error_code == "ACCESS_BLOCKED" and r.error.terminal is True
    assert "Request Rejected" in r.content and "DOSYA YÜKLEME YOLU" in r.content and "upload_file" in r.content


def test_export_path_comes_from_configuration_only() -> None:
    assert "Toplam İşlem Hacmi Raporu" in (_manual_export_hint("TEFAS", "https://www.tefas.gov.tr/") or "")
    assert _manual_export_hint("başka bir site", "https://ornek.example/") is None


def test_access_block_answer_is_built_from_the_tool_card() -> None:
    from kkb_agent.core.agent import AnalyticsAgent
    from kkb_agent.core.errors import ToolError

    card = ("ERİŞİM[blocked]: engel\nSEBEP: bot_challenge\n"
            "SEÇENEKLER: upload_file: Dosyayı siz yükleyin | alternative_source: Başka bir kaynak arayayım\n"
            "KULLANICIYA: Belirttiğiniz kaynağa erişemedim: otomatik istemci engellendi.\n"
            "DOSYA YÜKLEME YOLU — Rapor (https://rapor.example): Raporu CSV olarak indirip yükleyin.")
    text = AnalyticsAgent._access_blocked_answer(ToolError(error_code="ACCESS_BLOCKED", message=card, layer="access"))
    assert text.startswith("Belirttiğiniz kaynağa erişemedim") and "- Dosyayı siz yükleyin" in text
    assert "Dosyayı şöyle indirebilirsiniz — Rapor" in text and "ERİŞİM[" not in text
    assert AnalyticsAgent._access_blocked_answer(ToolError(error_code="SQL_FAILED", message="x", layer="data")) is None
