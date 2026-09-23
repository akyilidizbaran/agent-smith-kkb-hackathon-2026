"""Web erişimi: bütçe, robots, erişim sözleşmesi, tablo çıkarımı, kanıt zinciri — ağ yok, oturum sahte."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.evidence import EvidencePanel  # noqa: E402
from kkb_agent.core.agent import AnalyticsAgent  # noqa: E402
from kkb_agent.core.evidence import EvidenceBuilder  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.llm.base import LLMResponse, ToolCall  # noqa: E402
from kkb_agent.tools.web import WebSearchTool, WebUrlTool  # noqa: E402
from kkb_agent.web import CrawlBudget, CrawlResult, ContentTooLarge, RobotsCache, TavilySearch, crawl, extract_page, fetch_url  # noqa: E402
from kkb_agent.web.crawl import link_score  # noqa: E402
from kkb_agent.web.fetch import FetchRefused  # noqa: E402

HTML = """<html><head><title>TÜFE Yıllık</title></head><body><script>var x=1;</script>
<h1>TÜFE yıllık enflasyon</h1><p>Bu sayfa 2025 yılı verisini içerir.</p>
<table><tr><th>Yıl</th><th>Yıllık TÜFE (%)</th></tr>
<tr><td>2024</td><td>44,38</td></tr><tr><td>2025</td><td>31,07</td></tr></table>
<a href="/veri/tufe.csv">CSV indir</a> <a href="/hakkinda">Hakkında</a>
<a href="https://baska.example.org/x">Dış bağlantı</a> <a href="/enflasyon-raporu-2025">Enflasyon raporu 2025</a>
</body></html>"""
CSV = "Yil;TUFE\n2024;44,38\n2025;31,07\n"


class Resp:
    def __init__(self, status=200, body=b"", url=None, ctype="text/html"):
        self.status_code, self._body, self.url = status, body, url
        self.headers = {"Content-Type": ctype}
        self.content = body

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]

    def close(self):
        pass


class Session:
    """URL → yanıt haritası; robots.txt de buradan gelir. Çağrılar sayılır (bütçe ölçümü)."""

    def __init__(self, routes: dict, robots: str | None = None):
        self.routes, self.robots, self.calls = routes, robots, []

    def get(self, url, **kw):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return Resp(200, self.robots.encode()) if self.robots else Resp(404, b"")
        r = self.routes.get(url)
        if r is None:
            return Resp(404, b"yok")
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def _no_private(monkeypatch):
    monkeypatch.setattr("kkb_agent.web.fetch.private_host", lambda host: False)


# ------------------------------------------------------------------ fetch


def test_fetch_ok_sha_ve_zaman_tasir() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    r = fetch_url("https://site.example/tufe", session=s, robots=RobotsCache())
    assert r.ok and r.http_status == 200 and len(r.sha256) == 64 and r.media_type == "text/html"
    assert r.fetched_at.tzinfo is not None


def test_robots_disallow_erisim_sozlesmesiyle_doner() -> None:
    s = Session({"https://site.example/gizli": Resp(200, b"x")}, robots="User-agent: *\nDisallow: /gizli\n")
    r = fetch_url("https://site.example/gizli", session=s, robots=RobotsCache())
    assert not r.ok and r.outcome.status == "blocked" and r.outcome.reason == "robots_disallow"
    assert "https://site.example/gizli" not in s.calls   # sayfa hiç istenmedi


def test_bot_engeli_ve_404_ve_ulasilamayan() -> None:
    s = Session({
        "https://site.example/bot": Resp(403, b"<h1>Security Controls Triggered</h1>"),
        "https://site.example/yok": Resp(404, b""),
        "https://site.example/down": ConnectionError("dns"),
    })
    assert fetch_url("https://site.example/bot", session=s).outcome.reason == "bot_challenge"
    assert fetch_url("https://site.example/yok", session=s).outcome.status == "not_found"
    assert fetch_url("https://site.example/down", session=s).outcome.reason == "unreachable"


def test_yerel_dosya_yalniz_izinli_kokten(tmp_path: Path) -> None:
    (tmp_path / "in").mkdir(); (tmp_path / "in" / "a.html").write_text(HTML, encoding="utf-8")
    (tmp_path / "out.html").write_text(HTML, encoding="utf-8")
    r = fetch_url(str(tmp_path / "in" / "a.html"), allowed_local_roots=[tmp_path / "in"])
    assert r.ok and r.from_local_file and r.media_type == "text/html"
    with pytest.raises(FetchRefused):
        fetch_url(str(tmp_path / "out.html"), allowed_local_roots=[tmp_path / "in"])
    with pytest.raises(FetchRefused):
        fetch_url("ftp://x/y")


def test_boyut_siniri_asilirsa_reddedilir() -> None:
    s = Session({"https://site.example/big": Resp(200, b"x" * 1000)})
    with pytest.raises(ContentTooLarge):
        fetch_url("https://site.example/big", session=s, max_bytes=100)


def test_boyut_siniri_crawlerda_erisim_engeli_degil_ayri_siniftir() -> None:
    s = Session({"https://site.example/big": Resp(200, b"x" * 1000)})
    result = crawl("https://site.example/big", budget=CrawlBudget(max_bytes_per_page=100), session=s)

    assert result.pages == [] and result.blocked == []
    assert result.limit_exceeded == [("https://site.example/big", "kaynak 100 bayt sınırını aşıyor")]
    assert "1 boyut sınırı" in result.summary()


# ------------------------------------------------------------------ html


def test_sayfadan_tablo_metin_ve_baglanti_cikarilir() -> None:
    page = extract_page(HTML.encode(), "text/html", "https://site.example/tufe")
    assert page.title == "TÜFE Yıllık" and "var x" not in page.text and "2025 yılı verisini" in page.text
    assert len(page.tables) == 1 and page.tables[0].iloc[1, 1] == 31.07   # Türkçe ondalık
    assert page.data_links == [("CSV indir", "https://site.example/veri/tufe.csv")]
    assert [h for _, h in page.links] == ["https://site.example/hakkinda", "https://site.example/enflasyon-raporu-2025"]


def test_csv_dogrudan_tablo() -> None:
    page = extract_page(CSV.encode(), "text/csv", "https://site.example/veri/tufe.csv")
    assert page.kind == "data" and page.tables[0].shape == (2, 2)


def test_pdf_data_linki_ayni_domain_kesfinde_oncelik_alir() -> None:
    html = b'<html><body><a href="/rapor.pdf">Veri raporu</a><a href="/about">Hakkinda</a></body></html>'
    page = extract_page(html, "text/html", "https://site.example/index")

    assert page.data_links == [("Veri raporu", "https://site.example/rapor.pdf")]
    assert link_score("Veri raporu", "https://site.example/rapor.pdf", set()) > link_score(
        "Hakkinda", "https://site.example/about", set()
    )


# ------------------------------------------------------------------ crawl


def test_tarama_butcesi_ve_oncelik() -> None:
    routes = {
        "https://site.example/tufe": Resp(200, HTML.encode()),
        "https://site.example/veri/tufe.csv": Resp(200, CSV.encode(), ctype="text/csv"),
        "https://site.example/enflasyon-raporu-2025": Resp(200, b"<html><body><p>rapor 2025</p></body></html>"),
        "https://site.example/hakkinda": Resp(200, b"<html><body>hakkinda</body></html>"),
    }
    s = Session(routes)
    r = crawl("https://site.example/tufe", budget=CrawlBudget(max_pages=2, max_depth=1),
              keywords={"enflasyon", "2025"}, session=s, robots=RobotsCache())
    assert [p.url for p in r.pages] == ["https://site.example/tufe", "https://site.example/veri/tufe.csv"]  # veri linki önce
    skipped = dict(r.skipped)
    assert "https://baska.example.org/x" not in r.visited_urls and "https://baska.example.org/x" not in skipped  # dış alan adı çıkarımda elenir
    assert skipped["https://site.example/hakkinda"] == "ilgisiz"
    assert "https://site.example/enflasyon-raporu-2025" in skipped and skipped["https://site.example/enflasyon-raporu-2025"].startswith("bütçe")
    assert "2 sayfa okundu" in r.summary()


def test_derinlik_sifirda_baglanti_izlenmez() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode())})
    r = crawl("https://site.example/tufe", budget=CrawlBudget(max_pages=3, max_depth=0), session=s, robots=RobotsCache())
    assert len(r.pages) == 1 and r.skipped == []


# ------------------------------------------------------------------ araçlar


def _tool(session, question: str, tmp_path: Path | None = None) -> tuple[WebUrlTool, AnalysisWorkspace]:
    ws = AnalysisWorkspace()
    reg = SimpleNamespace(active_question=question, turn=1)
    tool = WebUrlTool(ws, allowed_local_root=tmp_path, registry=reg, session=session, robots=RobotsCache())
    return tool, ws


def test_web_url_listeler_sonra_tabloyu_yukler_provenance_url_sha_zaman() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    tool, ws = _tool(s, "Şu sayfadan 2025 yıllık TÜFE'yi söyle: https://site.example/tufe")

    r1 = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE"})
    assert r1.ok and "TABLO #0" in r1.content and "Soruda geçen yıl(lar) sayfada mevcut: 2025" in r1.content
    assert "ERİŞİM[ok]" in r1.content and ws.table is None
    assert r1.artifacts["web"]["used"] is None and r1.artifacts["web"]["visited"][0]["sha256"]
    assert r1.artifacts["web"]["table_loaded"] is False
    assert r1.artifacts["web"]["visited"][0].get("table_used") is None
    list_panel = EvidencePanel(question="TÜFE sayfasını araştır")
    EvidenceBuilder._web(list_panel, [{"kind": "web", **r1.artifacts["web"]}])
    assert len(list_panel.web_reads) == 1 and not list_panel.web_sources

    r2 = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE", "table_index": 0})
    assert r2.ok and r2.content.startswith("TABLO YÜKLENDİ: #0")
    assert s.calls.count("https://site.example/tufe") == 1, "aynı turda seçilen tablo yeniden çekilmemeli"
    assert r2.artifacts["web"]["cache_reused"] is True
    assert ws.table is not None and ws.table.iloc[1, 1] == 31.07
    assert r2.artifacts["web"]["table_loaded"] is True
    assert r2.artifacts["web"]["table_index"] == 0
    assert r2.artifacts["web"]["table_rows"] == 2 and r2.artifacts["web"]["table_columns"] == 2
    prov = ws.column_provenance("Yıllık TÜFE (%)")
    assert prov.sql.startswith("web_url https://site.example/tufe tablo#0") and prov.source_urls == ["https://site.example/tufe"]
    assert "sha256" in prov.warnings[0] and r2.artifacts["web"]["used"] == "https://site.example/tufe"


def test_web_url_kesfi_onceki_turdan_yeniden_kullanilmaz() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    tool, _ = _tool(s, "Şu sayfadan 2025 yıllık TÜFE'yi söyle: https://site.example/tufe")

    first = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE"})
    tool._registry.turn = 2
    second = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE", "table_index": 0})

    assert first.ok and second.ok
    assert s.calls.count("https://site.example/tufe") == 2


def test_web_url_bos_sayfa_basari_saymaz_acik_hata_doner() -> None:
    # A1: HTTP 200 ama tablo yok + kullanılabilir metin yok → ok=True DÖNMEMELİ. Aksi halde ajan
    # "sayfa okundu" (web_page_succeeded) sanıp stale-tablo korumasını yanlış aşar (demo: TEFAS/CSV).
    empty = b"<html><head><title>Bos</title></head><body></body></html>"
    s = Session({"https://site.example/bos": Resp(200, empty, url="https://site.example/bos")})
    tool, ws = _tool(s, "Şu sayfadan verileri getir: https://site.example/bos")

    r = tool.validate_and_run({"url": "https://site.example/bos", "purpose": "veri"})
    assert not r.ok, "boş sayfa başarı sayılmamalı"
    assert r.error is not None and r.error.error_code in {"EMPTY_RESULT", "DOCUMENT_EXTRACTION_FAILED"}
    assert r.artifacts.get("web") is not None
    assert ws.table is None


def test_web_url_enrich_intent_joins_instead_of_overwriting(tmp_path: Path) -> None:
    # Phase 6: "mevcut veri setine ekle/zenginleştir/hizala" niyetinde YENİ kaynak aktif tabloyu
    # ÜZERİNE YAZMAMALI; Tarih üzerinden join edilmeli (deterministik). Kazara set_table = BAŞARISIZLIK.
    import pandas as pd
    csv = tmp_path / "tefas.csv"
    csv.write_text("Dönem;TEFAS Hacim (TL);Net Takas (TL)\n2025-12;18107;3434\n2023-06;118064;25997\n", encoding="utf-8")
    q = f"Mevcut analizi TEFAS verileriyle zenginleştir; aynı aylık tarih ekseninde hizala: {csv}"
    tool, ws = _tool(Session({}), q, tmp_path=tmp_path)
    prior = pd.DataFrame({"Tarih": ["2025-12-01", "2023-06-01", "2021-01-01"], "TP Mevduat": [687299, 397773, -9650]})
    ws.set_table(prior, description="BDDK-EVDS mevduat")

    r = tool.validate_and_run({"url": str(csv), "purpose": "TEFAS işlem hacmi ile zenginleştirme", "table_index": 0})
    assert r.ok, r.content
    cols = [str(c) for c in ws.table.columns]
    assert "TP Mevduat" in cols, f"mevcut BDDK-EVDS kolonu korunmalı (üzerine yazılmamalı) — kolonlar: {cols}"
    assert "TEFAS Hacim (TL)" in cols and "Net Takas (TL)" in cols, f"TEFAS kolonları eklenmeli — {cols}"
    assert len(ws.table) == len(prior), "mevcut tablonun satırları korunmalı (left join)"
    row = ws.table[ws.table["Tarih"] == "2025-12-01"].iloc[0]
    assert float(row["TEFAS Hacim (TL)"]) == 18107, "eşleşen ayın TEFAS değeri taşınmalı"
    match = ws.table[ws.table["Tarih"] == "2021-01-01"].iloc[0]
    assert pd.isna(match["TEFAS Hacim (TL)"]) or match["TEFAS Hacim (TL)"] in ("", None), "TEFAS'ta olmayan ay boş kalmalı"


def test_web_url_enrich_join_failure_does_not_overwrite_active_table(tmp_path: Path) -> None:
    # P5: enrich intent varken join YAPILAMAZSA (ortak ay yok) mevcut tablo ÜZERİNE YAZILMAMALI; açık hata.
    import pandas as pd
    csv = tmp_path / "baska.csv"
    csv.write_text("Dönem;Hacim\n2019-01;5\n2018-03;7\n", encoding="utf-8")  # taban tabloyla ortak ay yok
    q = f"Mevcut analizi zenginleştir; aynı aylık tarih ekseninde hizala: {csv}"
    tool, ws = _tool(Session({}), q, tmp_path=tmp_path)
    prior = pd.DataFrame({"Tarih": ["2025-12-01", "2023-06-01"], "TP Mevduat": [687299, 397773]})
    ws.set_table(prior, description="BDDK-EVDS")

    r = tool.validate_and_run({"url": str(csv), "purpose": "zenginleştirme", "table_index": 0})
    assert not r.ok and r.error is not None and r.error.error_code == "JOIN_MISMATCH"
    cols = [str(c) for c in ws.table.columns]
    assert cols == ["Tarih", "TP Mevduat"], "join başarısız → mevcut tablo değişmemeli (üzerine yazma yok)"
    assert len(ws.table) == 2


def test_web_url_cache_locator_normalizes_scheme_host_default_port_and_fragment() -> None:
    normalized = WebUrlTool._normalized_locator("HTTPS://SITE.EXAMPLE:443/data?year=2025#table")
    assert normalized == "https://site.example/data?year=2025"
    assert WebUrlTool._normalized_locator("http://site.example:80/data") == "http://site.example/data"
    assert WebUrlTool._normalized_locator("https://site.example:8443/data") == "https://site.example:8443/data"


def test_web_url_turn_cache_refuses_content_over_byte_budget(monkeypatch) -> None:
    body = "<html><body><p>" + ("uzun içerik " * 100) + "</p></body></html>"
    s = Session({"https://site.example/large": Resp(200, body.encode(), url="https://site.example/large")})
    tool, _ = _tool(s, "Şu sayfayı incele: https://site.example/large")
    monkeypatch.setattr("kkb_agent.tools.web._WEB_TURN_CACHE_MAX_BYTES", 32)

    first = tool.validate_and_run({"url": "https://site.example/large", "purpose": "kaynağı incele"})
    second = tool.validate_and_run({"url": "https://site.example/large", "purpose": "aynı kaynağı analiz et"})

    assert first.ok and second.ok
    assert second.artifacts["web"]["cache_reused"] is False
    assert s.calls.count("https://site.example/large") == 2


def test_web_url_acik_refresh_ayni_turda_yeniden_ceker() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    tool, _ = _tool(s, "Şu sayfadan 2025 yıllık TÜFE'yi söyle: https://site.example/tufe")

    first = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE"})
    refreshed = tool.validate_and_run({
        "url": "https://site.example/tufe", "purpose": "2025 TÜFE", "table_index": 0, "refresh": True,
    })

    assert first.ok and refreshed.ok
    assert refreshed.artifacts["web"]["cache_reused"] is False
    assert s.calls.count("https://site.example/tufe") == 2


def test_basarisiz_web_url_kesfi_cachelenmez_ama_basari_ayni_turda_kullanilir() -> None:
    s = Session({"https://site.example/tufe": ConnectionError("geçici ağ hatası")})
    tool, _ = _tool(s, "Şu sayfadan 2025 yıllık TÜFE'yi söyle: https://site.example/tufe")

    failed = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE"})
    s.routes["https://site.example/tufe"] = Resp(200, HTML.encode(), url="https://site.example/tufe")
    listed = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE"})
    loaded = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE", "table_index": 0})

    assert not failed.ok and listed.ok and loaded.ok
    assert loaded.artifacts["web"]["cache_reused"] is True
    assert s.calls.count("https://site.example/tufe") == 2


def test_web_url_dogrudan_sayfa_amac_degisse_de_ayni_tur_cache_kullanir() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    tool, _ = _tool(s, "Şu sayfadan 2025 yıllık TÜFE'yi söyle: https://site.example/tufe")

    first = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE"})
    second = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "tablodaki verileri analiz et", "table_index": 0})

    assert first.ok and second.ok
    assert second.artifacts["web"]["cache_reused"] is True
    assert s.calls.count("https://site.example/tufe") == 1


def test_web_url_ayni_metni_tekrar_model_baglamina_eklemez() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    tool, _ = _tool(s, "Şu sayfadan 2025 yıllık TÜFE'yi söyle: https://site.example/tufe")

    first = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE"})
    second = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "aynı duyurunun bağlamı"})

    assert first.ok and "METİN (" in first.content
    assert second.ok and "KAYNAK TEKRARI" in second.content
    assert second.artifacts["web"]["duplicate_excerpt_suppressed"] is True
    assert second.artifacts["web"]["cache_reused"] is True
    assert s.calls.count("https://site.example/tufe") == 1


def test_web_url_cached_document_allows_new_text_window_without_refetch() -> None:
    body = ("<html><body><p>" + ("Bu metin farklı belge bölümlerini test eder. " * 400) + "</p></body></html>")
    s = Session({"https://site.example/long": Resp(200, body.encode(), url="https://site.example/long")})
    tool, _ = _tool(s, "Şu sayfayı oku: https://site.example/long")

    first = tool.validate_and_run({"url": "https://site.example/long", "purpose": "belgeyi incele"})
    second = tool.validate_and_run({"url": "https://site.example/long", "purpose": "belgenin devamı", "text_from": 8000})

    assert first.ok and "METİN (karakter 0–8000" in first.content
    assert second.ok and "METİN (karakter 8000–" in second.content
    assert second.artifacts["web"]["cache_reused"] is True
    assert s.calls.count("https://site.example/long") == 1


def test_web_url_amac_farki_derin_taramada_yeni_link_secimini_etkiler() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    tool, _ = _tool(s, "Site içinde ilgili belgeyi bul: https://site.example/tufe")

    first = tool.validate_and_run({
        "url": "https://site.example/tufe", "purpose": "TÜFE verisi", "max_depth": 1, "max_pages": 3,
    })
    second = tool.validate_and_run({
        "url": "https://site.example/tufe", "purpose": "enflasyon raporu", "max_depth": 1, "max_pages": 3,
    })

    assert first.ok and second.ok
    assert second.artifacts["web"]["cache_reused"] is False
    assert s.calls.count("https://site.example/tufe") == 2


def test_web_url_boyut_asimi_erisim_engeli_ve_veri_yoklugundan_ayrilir(monkeypatch) -> None:
    url = "https://site.example/big.csv"
    tool, _ = _tool(Session({}), f"Şu URL'deki dosyayı analiz et: {url}")
    monkeypatch.setattr(
        "kkb_agent.tools.web.crawl",
        lambda *_args, **_kwargs: CrawlResult(
            start_url=url, limit_exceeded=[(url, "8 MiB indirme sınırı")], budget=CrawlBudget(),
        ),
    )

    result = tool.validate_and_run({"url": url, "purpose": "CSV verisini analiz et"})

    assert not result.ok and result.error.error_code == "CONTENT_TOO_LARGE"
    assert result.error.layer == "data" and result.error.is_retryable is False
    assert "erişim hatası veya veri yokluğu değildir" in result.error.message
    assert result.artifacts["web"]["limit_exceeded"] == [{"url": url, "reason": "8 MiB indirme sınırı"}]
    panel = EvidencePanel(question="büyük kaynağı oku")
    EvidenceBuilder._web(panel, [{"kind": "web", **result.artifacts["web"]}])
    assert panel.web_unused == [{"url": url, "note": "boyut sınırı: 8 MiB indirme sınırı"}]


def test_sayfada_istenen_yil_yoksa_acikca_soyler() -> None:
    body = (HTML.replace("<tr><td>2025</td><td>31,07</td></tr>", "")
            .replace("2025 yılı verisini", "2024 yılı verisini")
            .replace('<a href="/enflasyon-raporu-2025">Enflasyon raporu 2025</a>', ""))
    s = Session({"https://site.example/tufe": Resp(200, body.encode())})
    tool, _ = _tool(s, "Şu sayfadan 2025 yıllık TÜFE'yi söyle: https://site.example/tufe")
    r = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE"})
    assert r.ok and "DİKKAT: soruda geçen 2025 yılı bu sayfa(lar)da GEÇMİYOR" in r.content


def test_sabit_kaynaga_erisilemezse_sorulur_gecilmez() -> None:
    s = Session({"https://site.example/tufe": ConnectionError("dns")})
    tool, _ = _tool(s, "Şu adresten 2025 TÜFE: https://site.example/tufe")
    r = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE"})
    assert not r.ok and r.error.error_code == "ACCESS_BLOCKED" and not r.error.is_retryable
    assert "KAYNAK SABİT" in r.content and "unreachable" in r.content
    assert r.artifacts["web"]["blocked"][0]["reason"] == "unreachable"
    panel = EvidencePanel(question="sabit kaynağı oku")
    EvidenceBuilder._web(panel, [{"kind": "web", **r.artifacts["web"]}])
    assert panel.web_unused == [{"url": "https://site.example/tufe", "note": "erişilemedi: blocked / unreachable"}]


def test_bot_engeli_hesapla_asilmaz_secenek_yok() -> None:
    s = Session({"https://site.example/x": Resp(403, b"<h1>Security Controls Triggered</h1>")})
    tool, _ = _tool(s, "https://site.example/x adresinden veri")
    r = tool.validate_and_run({"url": "https://site.example/x", "purpose": "veri"})
    assert not r.ok and "bot_challenge" in r.content and "credential" not in r.content.split("SEÇENEKLER")[-1].lower()


def test_yerel_fikstur_izinli_kokten_okunur(tmp_path: Path) -> None:
    (tmp_path / "tufe.html").write_text(HTML, encoding="utf-8")
    tool, ws = _tool(None, "Şu sayfadan 2025 TÜFE: " + str(tmp_path / "tufe.html"), tmp_path)
    r = tool.validate_and_run({"url": str(tmp_path / "tufe.html"), "purpose": "2025 TÜFE", "table_index": 0})
    assert r.ok and len(ws.table) == 2


def test_olmayan_tablo_indeksi_adaylarla_doner() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode())})
    tool, _ = _tool(s, "https://site.example/tufe sayfasındaki tablo")
    r = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "x", "table_index": 5})
    assert not r.ok and r.error.error_code == "COLUMN_NOT_FOUND" and r.error.candidates == ["#0"]


def test_web_search_anahtar_yoksa_needs_credential() -> None:
    tool = WebSearchTool(TavilySearch(environ={}), registry=SimpleNamespace(active_question="enflasyon"))
    r = tool.validate_and_run({"query": "2025 enflasyon"})
    assert not r.ok and r.error.error_code == "NEEDS_CREDENTIAL"


def test_web_search_sonuc_veri_degildir_anahtar_baslikta_butce_sayilir() -> None:
    seen: list[dict] = []

    class S:
        def post(self, url, json=None, headers=None, timeout=None):
            seen.append({"json": json, "headers": headers})
            return SimpleNamespace(
                status_code=200, json=lambda: {"results": [{"title": "TÜİK TÜFE", "url": "https://tuik.example/tufe", "content": "yıllık %31"}]})
    search = TavilySearch(environ={"TAVILY_API_KEY": "k"}, session=S(), budget=2)
    tool = WebSearchTool(search)
    r = tool.validate_and_run({"query": "2025 enflasyon", "topic": "news", "time_range": "year"})
    assert r.ok and "https://tuik.example/tufe" in r.content and "veri kanıtı değildir" in r.content
    assert "k" not in r.artifacts["web_search"]["hits"]
    assert seen[0]["headers"]["Authorization"] == "Bearer k" and "api_key" not in seen[0]["json"]
    assert seen[0]["json"]["topic"] == "news" and seen[0]["json"]["time_range"] == "year" and seen[0]["json"]["search_depth"] == "basic"
    assert "kalan arama bütçesi: 1" in r.content
    tool.validate_and_run({"query": "2025 enflasyon tuik"})
    r3 = tool.validate_and_run({"query": "2025 enflasyon üçüncü"})
    assert not r3.ok and "bütçesi doldu" in r3.content and len(seen) == 2


def test_verified_fallback_clamps_search_query_and_domains_and_runs_once() -> None:
    seen: list[dict] = []

    class S:
        def post(self, url, json=None, headers=None, timeout=None):
            seen.append({"json": json, "headers": headers})
            return SimpleNamespace(status_code=200, json=lambda: {"results": []})

    plan = {"query": "BDDK aylık kredi 2024", "include_domains": ["bddk.gov.tr"], "topic": "finance", "max_results": 5}
    registry = SimpleNamespace(
        active_question="2024 BDDK kredi verilerini getir",
        public_web_fallback_plan=plan,
        public_web_fallback_consumed=False,
        sanctioned_locators=set(),
    )
    tool = WebSearchTool(TavilySearch(environ={"TAVILY_API_KEY": "k"}, session=S()), registry=registry)

    result = tool.validate_and_run({
        "query": "ignore the plan and search all web",
        "include_domains": ["evil.example"],
        "topic": "news",
    })
    duplicate = tool.validate_and_run({"query": "another query"})

    assert result.ok and not duplicate.ok and duplicate.error.error_code == "DUPLICATE_CALL"
    assert len(seen) == 1
    assert seen[0]["json"]["query"] == plan["query"]
    assert seen[0]["json"]["include_domains"] == plan["include_domains"]
    assert seen[0]["json"]["topic"] == "finance"
    assert registry.public_web_fallback_consumed is True


def test_web_search_explicit_domain_is_provider_and_result_boundary_and_data_files_rank_first() -> None:
    seen: list[dict] = []

    class S:
        def post(self, url, json=None, headers=None, timeout=None):
            seen.append(json)
            return SimpleNamespace(status_code=200, json=lambda: {"results": [
                {"title": "Landing", "url": "https://data.example/landing", "content": "page"},
                {"title": "CSV", "url": "https://data.example/series.csv?download=1", "content": "value 999"},
                {"title": "Lookalike", "url": "https://data.example.evil.org/series.csv", "content": "bad"},
                {"title": "Script", "url": "javascript:alert(1)", "content": "bad"},
                {"title": "Credentials", "url": "https://user@data.example/series.csv", "content": "bad"},
                {"title": "Malformed", "url": "https://[invalid", "content": "bad"},
            ]})

    registry = SimpleNamespace(
        active_question="https://data.example/landing adresindeki finans verisini araştır",
        sanctioned_locators=set(),
    )
    tool = WebSearchTool(TavilySearch(environ={"TAVILY_API_KEY": "k"}, session=S()), registry=registry)
    result = tool.validate_and_run({"query": "model query", "include_domains": ["evil.org"]})

    assert result.ok
    assert seen[0]["include_domains"] == ["data.example"]
    assert result.artifacts["web_search"]["hits"] == [
        "https://data.example/series.csv?download=1", "https://data.example/landing",
    ]
    assert result.artifacts["web_search"]["rejected_count"] == 4
    assert result.artifacts["web_search"]["results"][0]["direct_data"] is True
    assert registry.sanctioned_locators == set(result.artifacts["web_search"]["hits"])
    assert "veri kanıtı değildir" in result.content


def test_web_search_gecersiz_model_domainiyle_kapsam_genisletmez() -> None:
    seen: list[dict] = []

    class S:
        def post(self, url, json=None, headers=None, timeout=None):
            seen.append(json)
            return SimpleNamespace(status_code=200, json=lambda: {"results": []})

    registry = SimpleNamespace(active_question="internetten kamu verisi ara", sanctioned_locators=set())
    tool = WebSearchTool(TavilySearch(environ={"TAVILY_API_KEY": "k"}, session=S()), registry=registry)
    result = tool.validate_and_run({"query": "finans", "include_domains": ["example.org/private/path"]})

    assert not result.ok and result.error.error_code == "INVALID_ARGS"
    assert seen == []


# ------------------------------------------------------------------ kanıt zinciri


def test_web_tablosunun_kanit_zinciri_sayfanin_baytlarinda_biter() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    tool, ws = _tool(s, "Şu sayfadan 2025 TÜFE: https://site.example/tufe")
    r = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE", "table_index": 0})

    class Silverish:  # EvidenceCapable ama web tablosu için gözlem aranmaz
        def evidence_for_observations(self, *a, **k): return []
        def evidence_for_artifacts(self, *a, **k): return {}

    panel: EvidencePanel = EvidenceBuilder(Silverish()).build(
        "soru", "2025 yıllık TÜFE %31,07.", ws, [], artifacts=[
            {"kind": "web_search", "query": "TÜFE", "results": [
                {"url": "https://site.example/tufe", "title": "TÜFE"},
                {"url": "https://other.example/tufe", "title": "Başka aday"},
            ]},
            {"kind": "web", **r.artifacts["web"]},
        ])
    assert panel.web_sources and panel.web_sources[0]["url"] == "https://site.example/tufe"
    assert panel.web_sources[0]["table_used"] is True
    assert panel.web_sources[0]["table_index"] == 0
    assert panel.web_sources[0]["table_rows"] == 2
    assert panel.web_reads == []
    assert [item["url"] for item in panel.context_sources] == ["https://other.example/tufe"]
    assert panel.complete, panel.gaps
    assert "web sayfası (sha256+zaman)" in panel.summary() and "WEB KAYNAĞI" in panel.render()
    ws.remember_web(r.artifacts["web"])
    follow_up = EvidenceBuilder(Silverish()).build("takip", "", ws, [])
    assert follow_up.web_sources[0]["sha256"] == panel.web_sources[0]["sha256"]
    assert follow_up.web_sources[0]["table_used"] is True
    assert follow_up.web_sources[0]["table_index"] == 0


def test_web_arama_adayi_okunan_url_ve_secilen_tablo_ayri_izlenir() -> None:
    panel = EvidencePanel(question="web verisini araştır")
    EvidenceBuilder._web(panel, [
        {"kind": "web_search", "query": "finans", "results": [
            {"url": "https://site.example/read", "title": "Okunan"},
            {"url": "https://site.example/candidate", "title": "Yalnız aday"},
        ]},
        {"kind": "web", "used": None, "table_loaded": False, "cache_reused": False,
         "visited": [{"url": "https://site.example/read", "status": 200, "sha256": "a" * 64,
                      "fetched_at": "2026-09-19T10:00:00+00:00", "title": "Okunan",
                      "extraction": {"method": "pdf_text_layer", "pages": [1, 2], "total_pages": 8}}],
         "blocked": [], "limit_exceeded": [{"url": "https://site.example/large.pdf", "reason": "100 bayt sınırı"}],
         "skipped": []},
    ])

    assert panel.web_sources == []
    assert len(panel.web_reads) == 1
    assert panel.web_reads[0]["url"] == "https://site.example/read"
    assert panel.web_reads[0]["table_used"] is False
    assert panel.web_reads[0]["extraction"]["method"] == "pdf_text_layer"
    assert [item["url"] for item in panel.context_sources] == ["https://site.example/candidate"]
    assert panel.web_unused == [{"url": "https://site.example/large.pdf", "note": "boyut sınırı: 100 bayt sınırı"}]
    assert "WEB OKUNDU, TABLOYA SEÇİLMEDİ" in panel.render()
    assert panel.to_dict()["web_reads"] == panel.web_reads


def test_anlatim_zaman_asiminda_web_tablosu_ve_kaynak_kaniti_korunur() -> None:
    class TimeoutAfterFetch:
        model = "test-timeout"

        def __init__(self) -> None:
            self.calls = 0

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="", tool_calls=[ToolCall(
                    id="web-1", name="web_url", arguments={
                        "url": "https://site.example/tufe", "purpose": "TÜFE tablosu", "table_index": 0,
                    },
                )])
            raise RuntimeError("LLM 2 denemede yanıt vermedi: Request timed out.")

    class Silverish:
        def evidence_for_observations(self, *a, **k): return []
        def evidence_for_artifacts(self, *a, **k): return {}

    question = "https://site.example/tufe sayfasındaki TÜFE tablosunu yükle ve sonucu kısaca açıkla."
    session = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    workspace = AnalysisWorkspace()
    registry = ToolRegistry()
    web_tool = WebUrlTool(workspace, registry=registry, session=session, robots=RobotsCache())
    web_tool._fitness = lambda *a, **k: (None, [])
    registry.register(web_tool)
    agent = AnalyticsAgent(
        llm=TimeoutAfterFetch(), registry=registry, workspace=workspace,
        evidence=EvidenceBuilder(Silverish()), tool_gate=False, max_steps=3,
        time_budget_s=5, tool_timeout_s=5, narration_timeout_s=1,
    )

    answer = agent.ask(question)

    assert answer.availability_status == "FOUND"
    assert workspace.table is not None and len(workspace.table) == 2
    web_artifact = next(a for a in answer.artifacts if a.get("kind") == "web")
    assert web_artifact["table_loaded"] is True and web_artifact["used"] == "https://site.example/tufe"
    assert answer.evidence is not None
    evidence = answer.evidence.to_dict()
    assert evidence["web_sources"][0]["table_used"] is True
    assert evidence["web_sources"][0]["sha256"] == web_artifact["visited"][0]["sha256"]
    assert "Anlatım servisi yanıt vermediği için" in answer.text


def test_nokta_ondalikli_sayfa_yuz_kat_hataya_dusmez() -> None:
    """Ölçüldü: pandas thousands='.' varsayımı TCMB'nin '31.51'ini 3151 yaptı."""
    html = ("<table><tr><th>Ay-Yıl</th><th>TÜFE (Yıllık % Değişim)</th></tr>"
            "<tr><td>08-2026</td><td>31.51</td></tr><tr><td>07-2026</td><td>33.52</td></tr></table>")
    page = extract_page(html.encode(), "text/html", "https://tcmb.example/x")
    assert page.tables[0]["TÜFE (Yıllık % Değişim)"].tolist() == [31.51, 33.52]
    assert page.notes == []


def test_belirsiz_sayi_bicimi_metin_kalir_ve_soylenir() -> None:
    html = "<table><tr><th>Yıl</th><th>Tutar</th></tr><tr><td>2024</td><td>3.151</td></tr><tr><td>2025</td><td>4.208</td></tr></table>"
    page = extract_page(html.encode(), "text/html", "https://x.example/x")
    t = page.tables[0]
    assert t["Yıl"].tolist() == [2024.0, 2025.0]           # ayraçsız: her çift aynı sayıyı verir
    assert t["Tutar"].tolist() == ["3.151", "4.208"]       # binlik mi ondalık mı belli değil → metin
    assert page.notes and "belirsiz" in page.notes[0] and "Tutar" in page.notes[0]


def test_yuzde_isareti_ve_turkce_ondalik() -> None:
    html = "<table><tr><th>Yıl</th><th>Oran</th></tr><tr><td>2025</td><td>%31,07</td></tr><tr><td>2024</td><td>44,38 %</td></tr></table>"
    page = extract_page(html.encode(), "text/html", "https://x.example/x")
    assert page.tables[0]["Oran"].tolist() == [31.07, 44.38]


def test_niyet_kapisi_kullanicinin_vermedigi_adres_acilmaz_arama_sonucu_acilir() -> None:
    """ADR-0037: sayfaya gömülü adres açılmaz (sızdırma kanalı); kullanıcının istediği aramanın sonucu açılır."""
    s = Session({"https://evil.example/x": Resp(200, HTML.encode()), "https://tuik.example/tufe": Resp(200, HTML.encode())})
    tool, _ = _tool(s, "2025 enflasyonunu bul")
    r = tool.validate_and_run({"url": "https://evil.example/x", "purpose": "x"})
    assert not r.ok and r.error.error_code == "INTENT_REQUIRED" and not r.error.is_retryable
    assert s.calls == []   # istek hiç atılmadı

    tool._registry.sanctioned_locators = {"https://tuik.example/tufe"}
    r2 = tool.validate_and_run({"url": "https://tuik.example/tufe", "purpose": "x"})
    assert r2.ok


def test_arama_sonuclari_onayli_adres_olur() -> None:
    reg = SimpleNamespace(active_question="enflasyonu ara", sanctioned_locators=set())

    class S:
        def post(self, url, json=None, headers=None, timeout=None):
            return SimpleNamespace(status_code=200, json=lambda: {"results": [{"title": "t", "url": "https://tuik.example/tufe", "content": "c"}]})
    WebSearchTool(TavilySearch(environ={"TAVILY_API_KEY": "k"}, session=S()), registry=reg).validate_and_run({"query": "enflasyon"})
    assert reg.sanctioned_locators == {"https://tuik.example/tufe"}


def test_k02_t10_tavily_http_hatasi_ve_baglanti_kopmasi_kontrollu_doner() -> None:
    """A27: arama sağlayıcısı 503/429 dönerse ya da bağlantı koparsa sahte başarı yok; erişim zarfı ve sebep döner."""
    for status, reason in ((503, "unreachable"), (429, "rate_limited")):
        class S:
            def post(self, url, json=None, headers=None, timeout=None, _s=status):
                return SimpleNamespace(status_code=_s, json=lambda: {})
        tool = WebSearchTool(TavilySearch(environ={"TAVILY_API_KEY": "k"}, session=S(), budget=3))
        r = tool.validate_and_run({"query": "2025 enflasyon"})
        assert not r.ok and r.error.error_code == "ACCESS_BLOCKED" and r.error.layer == "access" and reason in r.content, (status, r.content)
        assert not r.error.is_retryable and "k" not in r.content.split()

    class Broken:
        def post(self, *a, **k):
            raise ConnectionError("bağlantı koptu")
    r = WebSearchTool(TavilySearch(environ={"TAVILY_API_KEY": "k"}, session=Broken(), budget=3)).validate_and_run({"query": "enflasyon"})
    assert not r.ok and r.error.error_code == "ACCESS_BLOCKED" and "unreachable" in r.content


def test_pdf_icin_bayt_siniri_daha_genis_html_icin_degil() -> None:
    """Arkadaş bulgusu (22 Eyl): 8 MiB üstü faaliyet raporu PDF'i CONTENT_TOO_LARGE ile açılamıyordu."""
    from kkb_agent.web.fetch import PDF_MAX_BYTES
    body = b"%PDF-1.4 " + b"x" * 500
    s = Session({"https://site.example/rapor.pdf": Resp(200, body, ctype="application/pdf")})
    r = fetch_url("https://site.example/rapor.pdf", session=s, max_bytes=100)
    assert r.outcome.ok and len(r.content) == len(body) and PDF_MAX_BYTES > 8 * 1024 * 1024
    s = Session({"https://site.example/big": Resp(200, b"x" * 1000)})
    with pytest.raises(FetchRefused):
        fetch_url("https://site.example/big", session=s, max_bytes=100)


def test_fallback_is_not_consumed_when_research_state_denies_the_search() -> None:
    """İnceleme (22 Eyl): fallback planı authorize_search reddinden ÖNCE 'consumed' işaretleniyordu."""
    from kkb_agent.core.web_research import WebResearchState

    seen: list[dict] = []

    class S:
        def post(self, url, json=None, headers=None, timeout=None):
            seen.append({"json": json})
            return SimpleNamespace(status_code=200, json=lambda: {"results": []})

    plan = {"query": "BDDK aylık kredi 2024", "include_domains": ["bddk.gov.tr"], "topic": "finance", "max_results": 5}
    registry = SimpleNamespace(
        active_question="2024 BDDK kredi verilerini getir",
        public_web_fallback_plan=plan,
        public_web_fallback_consumed=False,
        sanctioned_locators=set(),
        web_research=WebResearchState(max_searches=0),
    )
    tool = WebSearchTool(TavilySearch(environ={"TAVILY_API_KEY": "k"}, session=S()), registry=registry)

    denied = tool.validate_and_run({"query": "x"})

    assert not denied.ok and denied.error.error_code == "WEB_RESEARCH_BUDGET"
    assert registry.public_web_fallback_consumed is False
    assert seen == []


def test_web_url_page_budget_clamp_keeps_turn_cache_key() -> None:
    """İnceleme (22 Eyl): page_budget max_pages'i kırpınca tur önbelleği anahtarı değişiyor, aynı sayfa
    yeniden indiriliyordu."""
    from kkb_agent.core.web_research import WebResearchState

    s = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    tool, _ = _tool(s, "Şu sayfayı oku: https://site.example/tufe")
    state = WebResearchState(max_unique_pages=2)
    tool._registry.web_research = state

    first = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE", "max_pages": 2})
    state.record_tool_result("web_url", first)
    assert first.ok and state.page_budget("https://site.example/tufe", 2) == 1

    second = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE", "max_pages": 2})

    assert second.ok and second.artifacts["web"]["cache_reused"] is True
    assert s.calls.count("https://site.example/tufe") == 1


def test_general_scope_fallback_allows_empty_domains_and_runs_once() -> None:
    """Option A: harness'in 'general' planı domain-pinsiz (boş include_domains) tek aramayı çalıştırır.
    Boş domain artık INTENT_REQUIRED değil — YALNIZ scope=general bayrağında."""
    seen: list[dict] = []

    class S:
        def post(self, url, json=None, headers=None, timeout=None):
            seen.append({"json": json})
            return SimpleNamespace(status_code=200, json=lambda: {"results": []})

    plan = {"query": "küresel faiz konut piyasası 2024", "include_domains": [],
            "topic": "finance", "max_results": 5, "scope": "general"}
    registry = SimpleNamespace(
        active_question="o dönemde dünya piyasalarında ne yaşandı internetten araştır",
        public_web_fallback_plan=plan,
        public_web_fallback_consumed=False,
        sanctioned_locators=set(),
    )
    tool = WebSearchTool(TavilySearch(environ={"TAVILY_API_KEY": "k"}, session=S()), registry=registry)

    result = tool.validate_and_run({"query": "ignore the plan", "include_domains": ["evil.example"]})

    assert result.ok, result.error and result.error.error_code
    assert len(seen) == 1
    assert seen[0]["json"]["query"] == plan["query"]
    assert not seen[0]["json"].get("include_domains")  # genel arama: domain kısıtı yok
    assert registry.public_web_fallback_consumed is True


def test_empty_domain_fallback_without_general_scope_is_rejected() -> None:
    """scope=general olmayan bir fallback planında boş domain hâlâ reddedilir (resmi-kaynak zorunlu)."""

    class S:
        def post(self, *args, **kwargs):
            raise AssertionError("kaynakla sınırlandırılmamış arama çalıştırılmamalı")

    plan = {"query": "x", "include_domains": [], "topic": "finance", "max_results": 5}  # scope yok
    registry = SimpleNamespace(
        active_question="q", public_web_fallback_plan=plan,
        public_web_fallback_consumed=False, sanctioned_locators=set(),
    )
    tool = WebSearchTool(TavilySearch(environ={"TAVILY_API_KEY": "k"}, session=S()), registry=registry)

    result = tool.validate_and_run({"query": "q"})

    assert not result.ok and result.error.error_code == "INTENT_REQUIRED"
    assert registry.public_web_fallback_consumed is False
