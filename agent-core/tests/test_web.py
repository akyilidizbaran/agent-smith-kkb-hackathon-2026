"""Web erişimi: bütçe, robots, erişim sözleşmesi, tablo çıkarımı, kanıt zinciri — ağ yok, oturum sahte."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.evidence import EvidencePanel  # noqa: E402
from kkb_agent.core.evidence import EvidenceBuilder  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.web import WebSearchTool, WebUrlTool  # noqa: E402
from kkb_agent.web import CrawlBudget, RobotsCache, TavilySearch, crawl, extract_page, fetch_url  # noqa: E402
from kkb_agent.web.fetch import FetchRefused, FetchTooLarge  # noqa: E402

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
    with pytest.raises(FetchTooLarge) as exc:   # FetchRefused alt tipi: boyut aşımı ayrı sınıflanır
        fetch_url("https://site.example/big", session=s, max_bytes=100)
    assert exc.value.limit == 100


def test_crawl_buyuk_belge_oversize_olarak_isaretlenir() -> None:
    # Boyut sınırından büyük başlangıç belgesi: erişim engeli/yokluk değil, ayrı 'oversize' kaydı.
    s = Session({"https://site.example/rapor.pdf": Resp(200, b"%PDF-" + b"x" * 5000, ctype="application/pdf")})
    result = crawl("https://site.example/rapor.pdf", budget=CrawlBudget(max_bytes_per_page=100),
                   session=s, robots=RobotsCache())
    assert result.first is None and not result.pages and not result.blocked
    assert result.oversize == [("https://site.example/rapor.pdf", 100)]


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
    reg = SimpleNamespace(active_question=question)
    tool = WebUrlTool(ws, allowed_local_root=tmp_path, registry=reg, session=session, robots=RobotsCache())
    return tool, ws


def test_web_url_listeler_sonra_tabloyu_yukler_provenance_url_sha_zaman() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    tool, ws = _tool(s, "Şu sayfadan 2025 yıllık TÜFE'yi söyle: https://site.example/tufe")

    r1 = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE"})
    assert r1.ok and "TABLO #0" in r1.content and "Soruda geçen yıl(lar) sayfada mevcut: 2025" in r1.content
    assert "ERİŞİM[ok]" in r1.content and ws.table is None
    assert r1.artifacts["web"]["used"] is None and r1.artifacts["web"]["visited"][0]["sha256"]

    r2 = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE", "table_index": 0})
    assert r2.ok and r2.content.startswith("TABLO YÜKLENDİ: #0")
    assert ws.table is not None and ws.table.iloc[1, 1] == 31.07
    prov = ws.column_provenance("Yıllık TÜFE (%)")
    assert prov.sql.startswith("web_url https://site.example/tufe tablo#0") and prov.source_urls == ["https://site.example/tufe"]
    assert "sha256" in prov.warnings[0] and r2.artifacts["web"]["used"] == "https://site.example/tufe"


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
    assert r.ok and "https://tuik.example/tufe" in r.content and "sayı okuma" in r.content
    assert "k" not in r.artifacts["web_search"]["hits"]
    assert seen[0]["headers"]["Authorization"] == "Bearer k" and "api_key" not in seen[0]["json"]
    assert seen[0]["json"]["topic"] == "news" and seen[0]["json"]["time_range"] == "year" and seen[0]["json"]["search_depth"] == "basic"
    assert "kalan arama bütçesi: 1" in r.content
    tool.validate_and_run({"query": "2025 enflasyon tuik"})
    r3 = tool.validate_and_run({"query": "2025 enflasyon üçüncü"})
    assert not r3.ok and "bütçesi doldu" in r3.content and len(seen) == 2


# ------------------------------------------------------------------ kanıt zinciri


def test_web_tablosunun_kanit_zinciri_sayfanin_baytlarinda_biter() -> None:
    s = Session({"https://site.example/tufe": Resp(200, HTML.encode(), url="https://site.example/tufe")})
    tool, ws = _tool(s, "Şu sayfadan 2025 TÜFE: https://site.example/tufe")
    r = tool.validate_and_run({"url": "https://site.example/tufe", "purpose": "2025 TÜFE", "table_index": 0})

    class Silverish:  # EvidenceCapable ama web tablosu için gözlem aranmaz
        def evidence_for_observations(self, *a, **k): return []
        def evidence_for_artifacts(self, *a, **k): return {}

    panel: EvidencePanel = EvidenceBuilder(Silverish()).build(
        "soru", "2025 yıllık TÜFE %31,07.", ws, [], artifacts=[{"kind": "web", **r.artifacts["web"]}])
    assert panel.web_sources and panel.web_sources[0]["url"] == "https://site.example/tufe"
    assert panel.complete, panel.gaps
    assert "web sayfası (sha256+zaman)" in panel.summary() and "WEB KAYNAĞI" in panel.render()


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
