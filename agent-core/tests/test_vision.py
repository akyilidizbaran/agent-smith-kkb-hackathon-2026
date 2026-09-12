"""Görüntü/PDF girişi (ADR-0041): OCR çıktısı → tablo; belge web_url ve ingest'ten geçer; ağ yok, OCR sahte."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.ingest import IngestFromUrlTool  # noqa: E402
from kkb_agent.tools.web import WebUrlTool  # noqa: E402
from kkb_agent.vision.ocr import OcrClient, clean_ocr_text, is_document, ocr_document, pdf_pages_to_png, prose_from_ocr, tables_from_ocr  # noqa: E402
from kkb_agent.web.html import extract_page  # noqa: E402
from tests.test_ingest_tool import FakeRunner, SpyLakehouse  # noqa: E402
from tests.test_web import Resp, Session  # noqa: E402

OCR_RAW = ("ovi\n<|det|>title [10,10,300,40]<|/det|>Altın İthalatı (kg)\n"
           "<|det|>table [10,60,500,300]<|/det|><table><tr><th>Yıl</th><th>Ocak</th><th>Şubat</th></tr>"
           "<tr><td>2024</td><td>12.345,6</td><td>9.876,5</td></tr><tr><td>2025</td><td>15.000,0</td><td>8.100,25</td></tr></table>\n"
           "<|det|>text [10,320,500,340]<|/det|>Kaynak: Borsa İstanbul")


class OcrSession:
    """OCR ucu: her görsel için aynı belge metnini döndürür; çağrıları ve başlıkları kaydeder."""

    def __init__(self, raw: str = OCR_RAW, status: int = 200) -> None:
        self.calls: list[dict] = []
        self.raw, self.status = raw, status

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return SimpleNamespace(status_code=self.status, json=lambda: {"choices": [{"message": {"content": self.raw}}]})


def _blank_pdf(pages: int = 2) -> bytes:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(200, 100)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_onek_atilir_tablolar_ve_metin_ayrilir() -> None:
    text = clean_ocr_text(OCR_RAW)
    assert text.startswith("<|det|>") and "ovi" not in text
    assert len(tables_from_ocr(text)) == 1 and "<table>" in tables_from_ocr(text)[0]
    prose = prose_from_ocr(text)
    assert "Altın İthalatı" in prose and "Borsa İstanbul" in prose and "<table>" not in prose and "<|det|>" not in prose
    assert is_document("application/pdf", "x") and is_document("", "https://a/b.PDF") and not is_document("text/html", "https://a/b.html")


def test_pdf_sayfalari_png_olur_ve_sayfa_siniri_uygulanir() -> None:
    pdf = _blank_pdf(3)
    pngs, total = pdf_pages_to_png(pdf, max_pages=2, scale=1.0)
    assert total == 3 and len(pngs) == 2 and pngs[0][:8] == b"\x89PNG\r\n\x1a\n"


def test_ocr_belgesi_rehberdeki_istekle_sayfa_sayfa() -> None:
    session = OcrSession()
    client = OcrClient(base_url="https://mia.example/v1/", api_key="k", model="kkbhackathon2026/Unlimited-OCR", session=session)
    doc = ocr_document(_blank_pdf(2), "application/pdf", client=client, url="https://x/ith_au.pdf")
    assert doc.total_pages == 2 and len(doc.pages) == 2 and not doc.truncated and len(doc.tables) == 2
    req = session.calls[0]
    assert req["url"] == "https://mia.example/v1/chat/completions" and req["headers"]["Authorization"] == "Bearer k"
    body = req["json"]
    assert body["model"] == "kkbhackathon2026/Unlimited-OCR" and body["temperature"] == 0.0
    assert body["skip_special_tokens"] is False and body["vllm_xargs"] == {"ngram_size": 35, "window_size": 128}
    parts = body["messages"][0]["content"]
    assert parts[0]["type"] == "image_url" and parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[1]["text"] == "<image>\ndocument parsing"
    assert "doğrulanmadı" in doc.note() and doc.sha256


def test_belge_sayfasi_profilci_dilbilgisiyle_sayiya_cevrilir_ocr_yoksa_okunamaz() -> None:
    client = OcrClient(base_url="https://mia.example/v1", api_key="k", model="ocr", session=OcrSession())
    page = extract_page(_blank_pdf(1), "application/pdf", "https://x/ith_au.pdf", ocr=client)
    assert page.kind == "ocr" and len(page.tables) == 1 and page.ocr["model"] == "ocr" and page.ocr["pages"] == [1]
    t = page.tables[0]
    assert float(t.iloc[1, 1]) == 15000.0 and float(t.iloc[0, 2]) == 9876.5      # 15.000,0 ve 9.876,5: Türkçe biçim
    assert any("OCR ile" in n for n in page.notes)
    none = extract_page(_blank_pdf(1), "application/pdf", "https://x/ith_au.pdf")
    assert none.kind == "document" and not none.tables and "OCR" in none.text


def test_web_url_pdf_tablosunu_yukler_provenance_ocr_notu_tasir() -> None:
    pdf = _blank_pdf(1)
    s = Session({"https://site.example/ith_au.pdf": Resp(200, pdf, ctype="application/pdf", url="https://site.example/ith_au.pdf")})
    client = OcrClient(base_url="https://mia.example/v1", api_key="k", model="ocr", session=OcrSession())
    ws = AnalysisWorkspace()
    reg = SimpleNamespace(active_question="https://site.example/ith_au.pdf belgesinden 2025 Ocak altın ithalatı",
                          user_text="https://site.example/ith_au.pdf belgesinden 2025 Ocak altın ithalatı", sanctioned_locators=set())
    tool = WebUrlTool(ws, registry=reg, session=s, ocr=client)
    listed = tool.validate_and_run({"url": "https://site.example/ith_au.pdf", "purpose": "x"})
    assert listed.ok and "TABLO #0" in listed.content and "OCR ile" in listed.content
    loaded = tool.validate_and_run({"url": "https://site.example/ith_au.pdf", "purpose": "x", "table_index": 0})
    assert loaded.ok and ws.has_table and len(ws.table) == 2
    assert "OCR ile görüntüden okunduğunu" in loaded.content
    prov = ws.column_provenance(ws.columns()[0])
    assert prov.sources[0].startswith("web") and any("OCR" in w for w in prov.warnings)
    assert loaded.artifacts["web"]["visited"][0]["ocr"]["model"] == "ocr"


def test_ingest_pdf_ocr_tablosunu_csv_yazip_cli_ya_verir(tmp_path: Path) -> None:
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")
    incoming = tmp_path / "incoming"; incoming.mkdir()
    (incoming / "ith_au.pdf").write_bytes(_blank_pdf(1))
    from kkb_agent.builder.ingest import LakehouseCLI
    runner = FakeRunner("status: success\nsource_id: adhoc\ndataset_id: adhoc_altin\nrun_id: r\n"
                        "artifact_sha256: " + "ab" * 32 + "\nbronze_path: b.parquet\nseries_id: adhoc:altin\nrows_written: 2\nrows_unchanged: 0\n")
    cli = LakehouseCLI(core_dir=tmp_path / "lakehouse-core", database=tmp_path / "lh.duckdb", data_root=tmp_path, runner=runner)
    raw = ("<|det|>table [0,0,1,1]<|/det|><table><tr><th>Tarih</th><th>Miktar</th></tr>"
           "<tr><td>2025-01-31</td><td>15.000,0</td></tr><tr><td>2025-02-28</td><td>8.100,25</td></tr>"
           "<tr><td>2025-03-31</td><td>9.000,0</td></tr><tr><td>2025-04-30</td><td>9.500,0</td></tr>"
           "<tr><td>2025-05-31</td><td>9.700,0</td></tr><tr><td>2025-06-30</td><td>9.900,0</td></tr>"
           "<tr><td>2025-07-31</td><td>10.100,0</td></tr></table>")
    client = OcrClient(base_url="https://mia.example/v1", api_key="k", model="ocr", session=OcrSession(raw))
    text = f"{incoming / 'ith_au.pdf'} belgesini taslak seri olarak ekle; birim kg, ölçüm tipi dönemlik akım, aylık kural toplam"
    reg = SimpleNamespace(active_question=text, user_text=text, sanctioned_locators=set())
    tool = IngestFromUrlTool(SpyLakehouse(), cli, allowed_root=incoming, registry=reg, ocr=client)
    r = tool.validate_and_run({"locator": str(incoming / "ith_au.pdf"), "name": "Altın ithalatı", "series_key": "altin",
                               "unit": "kg", "measure_type": "flow_periodic", "default_agg": "sum"})
    assert r.ok, r.content
    assert r.content.startswith("EKLENDİ: adhoc:altin") and "OCR: Belge" in r.content and "doğrulanmadı" in r.content
    cmd = runner.calls[0][0]
    csv_arg = cmd[cmd.index("ingest-file") + 1]
    assert csv_arg.endswith("_p1_t0.csv") and Path(csv_arg).exists()
    frame = pd.read_csv(csv_arg)
    assert len(frame) == 7 and float(frame.iloc[0, 1]) == 15000.0
    assert any(p.suffix == ".pdf" and p.name.startswith("ocr_") for p in incoming.iterdir())   # belge kopyası
    desc = cmd[cmd.index("--description") + 1]
    assert "sha256" in desc and "model ocr" in desc


def test_ocr_yoksa_belge_ingest_edilmez(tmp_path: Path) -> None:
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")
    incoming = tmp_path / "incoming"; incoming.mkdir()
    (incoming / "a.pdf").write_bytes(_blank_pdf(1))
    from kkb_agent.builder.ingest import LakehouseCLI
    runner = FakeRunner()
    cli = LakehouseCLI(core_dir=tmp_path / "lakehouse-core", database=tmp_path / "lh.duckdb", data_root=tmp_path, runner=runner)
    text = f"{incoming / 'a.pdf'} belgesini taslak olarak ekle"
    tool = IngestFromUrlTool(SpyLakehouse(), cli, allowed_root=incoming, registry=SimpleNamespace(active_question=text, user_text=text, sanctioned_locators=set()))
    r = tool.validate_and_run({"locator": str(incoming / "a.pdf"), "name": "x"})
    assert not r.ok and r.error.error_code == "TOOL_FAILED" and "OCR" in r.content and runner.calls == []


def test_ocr_tablosunda_td_basliklar_kolon_adi_olur_cok_satirli_birlesir() -> None:
    from kkb_agent.web.html import promote_header_rows
    raw = pd.DataFrame([["AY/MONTH", "TL", "", "USD"], ["", "Hacim", "Miktar", "Hacim"], ["Ocak", "1.000,5", "2", "3"], ["Şubat", "4", "5", "6"]],
                       columns=["sütun_1", "sütun_2", "sütun_3", "sütun_4"])
    out = promote_header_rows(raw)
    assert list(out.columns) == ["AY/MONTH", "TL | Hacim", "TL | Miktar", "USD | Hacim"] and len(out) == 2
    assert out.iloc[0, 0] == "Ocak" and out.iloc[0, 1] == "1.000,5"
    # ilk satır rakam içeriyorsa başlık sayılmaz; anlamlı kolon adı varsa dokunulmaz
    keep = pd.DataFrame([["2024", "1"], ["2025", "2"]], columns=["sütun_1", "sütun_2"])
    assert list(promote_header_rows(keep).columns) == ["sütun_1", "sütun_2"]
    named = pd.DataFrame([["Yıl", "Ocak"], ["2024", "1"]], columns=["a", "b"])
    assert promote_header_rows(named) is named


def test_colspan_rowspan_acilir_ve_yer_tutucu_bos_sayilir() -> None:
    from lxml import html as lh
    from kkb_agent.web.html import _string_tables, convert_numbers, promote_header_rows
    html = ("<table><tr><td rowspan='2'>AY/MONTH</td><td colspan='2'>TL</td><td rowspan='2'>TOPLAM</td></tr>"
            "<tr><td>Hacim</td><td>Miktar</td></tr>"
            "<tr><td>Ocak</td><td>1.000,50</td><td>2,5</td><td>3,0</td></tr>"
            "<tr><td>Şubat</td><td>-</td><td>4,5</td><td>n.a.</td></tr></table>")
    raw = _string_tables(lh.fromstring(html))[0]
    assert list(raw.iloc[0]) == ["AY/MONTH", "TL", "TL", "TOPLAM"] and list(raw.iloc[1]) == ["AY/MONTH", "Hacim", "Miktar", "TOPLAM"]
    named = promote_header_rows(raw)
    assert list(named.columns) == ["AY/MONTH", "TL | Hacim", "TL | Miktar", "TOPLAM"] and len(named) == 2
    conv, notes = convert_numbers(named)
    assert conv["TL | Hacim"].tolist()[0] == 1000.5 and pd.isna(conv["TL | Hacim"].tolist()[1])   # "-" boş
    assert conv["TOPLAM"].tolist()[0] == 3.0 and pd.isna(conv["TOPLAM"].tolist()[1])
