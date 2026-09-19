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
    assert total == 3 and len(pngs) == 2 and pngs[0][0] == 1 and pngs[0][1][:8] == b"\x89PNG\r\n\x1a\n"
    chosen, _ = pdf_pages_to_png(pdf, scale=1.0, pages=[3, 1, 9])
    assert [n for n, _ in chosen] == [3, 1]          # sınır dışı 9 atlandı, sıra korundu


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


def test_sayfa_secimi_ve_zaman_butcesi() -> None:
    from kkb_agent.vision.ocr import parse_pages
    assert parse_pages(None, 24) == [1, 2, 3, 4, 5]
    assert parse_pages("3", 24) == [3] and parse_pages("2-4", 24) == [2, 3, 4] and parse_pages("1,5,7", 24) == [1, 5, 7]
    assert parse_pages("20-40", 24) == [20, 21, 22, 23, 24] and parse_pages("x", 24) == []
    assert parse_pages("1-9", 24, max_pages=3) == [1, 2, 3]          # bütçe yine keser

    class Slow(OcrSession):
        def post(self, url, json=None, headers=None, timeout=None):
            import time as _t
            _t.sleep(0.05)
            return super().post(url, json=json, headers=headers, timeout=timeout)
    client = OcrClient(base_url="https://mia.example/v1", api_key="k", model="ocr", session=Slow())
    doc = ocr_document(_blank_pdf(4), "application/pdf", client=client, url="https://x/r.pdf", pages="1-4", max_seconds=0.01)
    assert len(doc.pages) == 1 and doc.truncated and "zaman bütçesi" in doc.truncated_reason and "pages=" in doc.note()
    doc2 = ocr_document(_blank_pdf(4), "application/pdf", client=client, url="https://x/r.pdf", pages="3")
    assert [p.page_no for p in doc2.pages] == [3] and not doc2.truncated and "seçilen 1" in doc2.note()
    doc3 = ocr_document(_blank_pdf(7), "application/pdf", client=client, url="https://x/r.pdf")
    assert len(doc3.pages) == 5 and doc3.truncated and "ilk 5 sayfa" in doc3.truncated_reason


def test_tablo_duzeyinde_ayrac_kurali_belirsiz_kolonu_cozer() -> None:
    from kkb_agent.web.html import convert_numbers
    raw = pd.DataFrame({"Yıl": ["2024", "2025", "2026"], "Toplam": ["1.234,50", "2.000,00", "3.100,25"],
                        "Ocak": ["1.484", "89", "129"], "Şubat": ["514.813", "3.119", "11.345"]})
    conv, notes = convert_numbers(raw)
    assert conv["Ocak"].tolist() == [1484.0, 89.0, 129.0] and conv["Şubat"].tolist()[0] == 514813.0
    assert any("ayraç kuralıyla" in n for n in notes)
    # tabloda ayraçlı çözümlü kolon yoksa ve kolon yalnız noktalı değerlerden oluşuyorsa belirsiz kalır
    raw2 = pd.DataFrame({"Yıl": ["2024", "2025", "2026"], "Ocak": ["1.484", "2.119", "3.500"]})
    conv2, notes2 = convert_numbers(raw2)
    assert not pd.api.types.is_numeric_dtype(conv2["Ocak"]) and any("metin bırakıldı" in n for n in notes2)


def test_satir_toplami_tutarliligi_ocr_kalitesini_isaretler() -> None:
    from kkb_agent.web.html import row_sum_consistency
    good = pd.DataFrame({"Yıl": [2024.0, 2025.0, 2026.0], "Toplam": [6.0, 15.0, 24.0], "Ocak": [1.0, 4.0, 7.0], "Şubat": [2.0, 5.0, 8.0], "Mart": [3.0, 6.0, 9.0]})
    assert row_sum_consistency(good) == 1.0
    bad = good.copy(); bad["Ocak"] = [0.0, 0.0, 40.0]
    assert row_sum_consistency(bad) < 0.5
    assert row_sum_consistency(pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [1.0, 2.0, 3.0]})) is None   # toplam kolonu yok
    raw = ("<|det|>table [0,0,1,1]<|/det|><table><tr><td>Yıl</td><td>Toplam</td><td>Ocak</td><td>Şubat</td><td>Mart</td></tr>"
           "<tr><td>2024</td><td>6</td><td>0</td><td>0</td><td>40</td></tr><tr><td>2025</td><td>15</td><td>0</td><td>0</td><td>40</td></tr>"
           "<tr><td>2026</td><td>24</td><td>7</td><td>8</td><td>9</td></tr></table>")
    client = OcrClient(base_url="https://mia.example/v1", api_key="k", model="ocr", session=OcrSession(raw))
    page = extract_page(_blank_pdf(1), "application/pdf", "https://x/t.pdf", ocr=client)
    assert page.ocr["quality"] == "düşük" and any("DİKKAT" in n for n in page.notes)


def test_karisik_kolon_kurali_ve_yapisiz_ocr_isareti() -> None:
    from kkb_agent.web.html import convert_numbers
    raw = pd.DataFrame({"Yıl": ["2024", "2025", "2026"], "Elmas": ["1.484", "89", "129"], "Safir": ["12", "3.119", "45"]})
    conv, notes = convert_numbers(raw)
    assert conv["Elmas"].tolist() == [1484.0, 89.0, 129.0] and conv["Safir"].tolist()[1] == 3119.0
    assert all("binlik sayıldı" in n for n in notes if "Elmas" in n)
    only_dotted = pd.DataFrame({"Yıl": ["2024", "2025"], "Oran": ["1.484", "2.119"]})   # hepsi noktalı: karar yok
    conv2, notes2 = convert_numbers(only_dotted)
    assert not pd.api.types.is_numeric_dtype(conv2["Oran"])
    raw_ocr = ("<|det|>table [0,0,1,1]<|/det|><table><tr><td>Val</td><td>Toplinn</td><td>Oct</td></tr>"
               "<tr><td>2O25</td><td>l7582</td><td>-</td></tr><tr><td>2O24</td><td>x</td><td>4O</td></tr></table>")
    client = OcrClient(base_url="https://mia.example/v1", api_key="k", model="ocr", session=OcrSession(raw_ocr))
    page = extract_page(_blank_pdf(1), "application/pdf", "https://x/scan.pdf", ocr=client)
    assert page.ocr["quality"] == "belirsiz" and any("tablo yapısını çözemedi" in n for n in page.notes)


def test_ocr_nokta_ondalik_duzeltmesi_ve_uc_satirli_baslik() -> None:
    from lxml import html as lh
    from kkb_agent.web.html import _string_tables, convert_numbers, normalize_ocr_decimals, promote_header_rows
    raw = pd.DataFrame({"Yıl": ["2024", "2025"], "Hacim": ["133.119.720.04", "0.00"], "Adet": ["1.484", "89"]})
    fixed, n = normalize_ocr_decimals(raw)
    assert n == 2 and fixed["Hacim"].tolist() == ["133.119.720,04", "0,00"] and fixed["Adet"].tolist() == ["1.484", "89"]
    conv, _ = convert_numbers(fixed)
    assert conv["Hacim"].tolist() == [133119720.04, 0.0] and conv["Adet"].tolist() == [1484.0, 89.0]
    html = ("<table><tr><td rowspan='3'>Yıl</td><td colspan='2'>Hacim</td></tr><tr><td>TL</td><td>USD</td></tr>"
            "<tr><td>a</td><td>b</td></tr><tr><td>2024</td><td>1.000.50</td><td>2.00</td></tr></table>")
    named = promote_header_rows(_string_tables(lh.fromstring(html))[0], max_rows=3)
    assert list(named.columns) == ["Yıl", "Hacim | TL | a", "Hacim | USD | b"] and len(named) == 1


def test_birim_satiri_basliga_katilir() -> None:
    from kkb_agent.web.html import convert_numbers, normalize_ocr_decimals, promote_header_rows
    raw = pd.DataFrame([["Yıl / Year", "Hacim/ Volume", "Elmas/Diamond", "Zümrüt/Emerald"],
                        ["2025", "TL", "USD", "EURO"],
                        ["2024", "39.813.428.77", "4.981.006.15", "0.00"],
                        ["2025", "49.419.579.35", "7.360.600.08", "150.000.00"]],
                       columns=["sütun_1", "sütun_2", "sütun_3", "sütun_4"])
    named = promote_header_rows(raw, max_rows=3)
    assert list(named.columns) == ["Yıl / Year", "Hacim/ Volume | TL", "Elmas/Diamond | USD", "Zümrüt/Emerald | EURO"]
    assert len(named) == 2
    conv, _ = convert_numbers(normalize_ocr_decimals(named)[0])
    assert conv["Hacim/ Volume | TL"].tolist() == [39813428.77, 49419579.35] and conv["Zümrüt/Emerald | EURO"].tolist()[1] == 150000.0


def test_tablo_etiketi_sayfa_baslagini_tasir() -> None:
    raw = ("ovi\n<|det|>title [0,0,1,1]<|/det|>GÜMÜŞ / SILVER\nSon güncelleme 27.07.2026\n"
           "<|det|>table [0,0,1,1]<|/det|><table><tr><th>Yıl</th><th>Toplam</th><th>Oca</th><th>Şub</th></tr>"
           "<tr><td>2025</td><td>3,0</td><td>1,0</td><td>2,0</td></tr><tr><td>2024</td><td>5,0</td><td>2,0</td><td>3,0</td></tr>"
           "<tr><td>2023</td><td>7,0</td><td>3,0</td><td>4,0</td></tr></table>")
    client = OcrClient(base_url="https://mia.example/v1", api_key="k", model="ocr", session=OcrSession(raw))
    pdf = _blank_pdf(2)
    page = extract_page(pdf, "application/pdf", "https://x/cevher.pdf", ocr=client)
    assert len(page.tables) == 2 and page.table_labels[1].startswith("sayfa 2: GÜMÜŞ / SILVER")
    s = Session({"https://site.example/cevher.pdf": Resp(200, pdf, ctype="application/pdf", url="https://site.example/cevher.pdf")})
    ws = AnalysisWorkspace()
    reg = SimpleNamespace(active_question="https://site.example/cevher.pdf altın", user_text="https://site.example/cevher.pdf altın", sanctioned_locators=set())
    tool = WebUrlTool(ws, registry=reg, session=s, ocr=client)
    listed = tool.validate_and_run({"url": "https://site.example/cevher.pdf", "purpose": "x"})
    assert "TABLO #1 (sayfa 2: GÜMÜŞ / SILVER" in listed.content
    loaded = tool.validate_and_run({"url": "https://site.example/cevher.pdf", "purpose": "x", "table_index": 1})
    assert loaded.ok and "sayfa 2: GÜMÜŞ / SILVER" in loaded.content and "sayfa 2" in ws.column_provenance(ws.columns()[0]).sql


_FIXTURES = Path(__file__).resolve().parent / "golden" / "fixtures"


def test_pdf_metin_katmani_ocrsiz_dogrulanmis_okunur() -> None:
    """Jüri beklentisi (pypdf ile doğrudan okuma): metin katmanlı PDF, OCR OLMADAN dahi birebir/doğrulanmış
    okunur. Eskiden ocr=None → OCR_NOT_CONFIGURED hatası dönerdi; artık gerçek değerler gelir, ocr bayrağı yok."""
    data = (_FIXTURES / "ith_au.pdf").read_bytes()
    pc = extract_page(data, "application/pdf", "https://x/ith_au.pdf", ocr=None)
    assert pc.kind == "document" and pc.ocr is None and pc.extraction_error is None
    assert "9.654" in pc.text and "48.136,74" in pc.text          # 2025 Ocak ithalat + 2026 toplam, birebir
    assert any("metin katman" in n.lower() for n in pc.notes)     # doğrulanmış okuma notu
    # Taranmış/boş PDF metin katmanı taşımaz → OCR yoluna düşer (OCR yoksa dürüst "okunamadı").
    scanned = extract_page(_blank_pdf(1), "application/pdf", "https://x/scan.pdf", ocr=None)
    assert scanned.extraction_error == "OCR_NOT_CONFIGURED"
