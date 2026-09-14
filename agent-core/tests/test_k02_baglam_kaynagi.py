"""K02-T04 (A06, ADR-0075): dış bağlam — web araması sonucu kanıtta ve raporda veri kaynaklarından ayrı, 'veri değil' diye."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.evidence import EvidencePanel  # noqa: E402
from kkb_agent.core.evidence import EvidenceBuilder  # noqa: E402
from kkb_agent.tools.web import WebSearchTool  # noqa: E402
from kkb_agent.web.search import TavilySearch  # noqa: E402
from kkb_agent.web_app import evidence_to_dict, report_html  # noqa: E402

PPK, HABER = "https://tcmb.example/ppk", "https://haber.example/konut"


class Session:
    def post(self, url, json=None, headers=None, timeout=None):
        return SimpleNamespace(status_code=200, json=lambda: {"results": [
            {"title": "PPK kararı", "url": PPK, "content": "Kurul faizi artırdı."},
            {"title": "Konut talebi", "url": HABER, "content": "Talep zayıfladı."}]})


def _search_artifact() -> dict:
    return {"kind": "web_search", "query": "PPK 2023", "hits": [PPK, HABER],
            "results": [{"url": PPK, "title": "PPK kararı"}, {"url": HABER, "title": "Konut talebi"}]}


def test_arama_artefakti_adres_ve_baslik_tasir() -> None:
    reg = SimpleNamespace(active_question="internette ara", sanctioned_locators=set())
    r = WebSearchTool(TavilySearch(environ={"TAVILY_API_KEY": "k"}, session=Session()), registry=reg).validate_and_run({"query": "PPK 2023"})
    art = r.artifacts["web_search"]
    assert r.ok and art["hits"] == [PPK, HABER]
    assert art["results"] == [{"url": PPK, "title": "PPK kararı"}, {"url": HABER, "title": "Konut talebi"}]


def test_arama_sonucu_baglam_kaynagi_acilip_tabloya_giren_sayfa_veri_kaynagi_kalir() -> None:
    panel = EvidencePanel(question="q")
    web = {"kind": "web", "used": HABER, "visited": [{"url": HABER, "sha256": "ab" * 32, "fetched_at": "2026-09-14", "status": 200, "title": "Konut talebi"}]}
    EvidenceBuilder._web(panel, [_search_artifact(), web])
    assert [c["url"] for c in panel.context_sources] == [PPK], "tabloya giren sayfa bağlam değil veri kaynağıdır"
    assert panel.context_sources[0]["note"] == "web araması — bağlam, veri değil" and panel.context_sources[0]["query"] == "PPK 2023"
    assert [w["url"] for w in panel.web_sources] == [HABER]
    text = panel.render()
    assert "BAĞLAM KAYNAĞI (web araması; veri değil" in text and f"{PPK} — PPK kararı (arama: PPK 2023)" in text


def test_json_ve_rapor_baglam_kaynagini_veri_kaynaklarindan_ayri_listeler() -> None:
    panel = EvidencePanel(question="q")
    EvidenceBuilder._web(panel, [_search_artifact()])
    ev = evidence_to_dict(panel)
    assert [c["url"] for c in ev["context_sources"]] == [PPK, HABER] and ev["web_sources"] == []
    html = report_html({"question": "q", "text": "Bağlam için PPK kararına bakıldı.", "evidence": ev, "index": 3}, None, version="abc1234")
    assert f"bağlam (web araması, veri değil): {PPK} · PPK kararı · arama &#x27;PPK 2023&#x27;" in html
