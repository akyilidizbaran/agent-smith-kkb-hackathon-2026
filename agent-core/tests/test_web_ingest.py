"""Page/attachment/table ingestion: genuine PDF parsing, deterministic HTTP fixtures."""
import io
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from kkb_agent.builder.ingest import LakehouseCLI
from kkb_agent.builder.profile import profile_table, propose
from kkb_agent.builder.web_source import read_web_source
from kkb_agent.tools.ingest import IngestFromUrlTool
from tests.test_ingest_tool import FakeRunner, SpyLakehouse

URL = "https://reports.example/list?month=7#report-42"
PDF_URL = "https://reports.example/download/42"


def table_pdf():
    """Small real PDF with a ruled table and a text layer; no OCR/server dependency."""
    stream = ["0.5 w"]
    for x in (30, 200, 300, 400):
        stream.append(f"{x} 600 m {x} 690 l S")
    for y in (600, 630, 660, 690):
        stream.append(f"30 {y} m 400 {y} l S")
    rows = [("Temmuz 2026", "Banka A", "Toplam"),
            ("Nakdi Krediler (Milyar TL)", "1.234", "2.345"),
            ("Tasfiye (Milyar TL)", "10", "20")]
    for y, row in zip((675, 645, 615), rows):
        for x, cell in zip((35, 205, 305), row):
            cell = cell.replace("(", r"\(").replace(")", r"\)")
            stream.append(f"BT /F1 9 Tf {x} {y} Td ({cell}) Tj ET")
    body = "\n".join(stream).encode("ascii")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream"]
    out = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 6\n0000000000 65535 f \n"
    out += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
    return out + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()


class Response:
    def __init__(self, url, content, media, status=200, extra=None):
        self.url, self.content, self.status_code = url, content, status
        self.headers = {"content-type": media, **(extra or {})}
        self.closed = False

    def iter_content(self, n):
        yield self.content

    def close(self):
        self.closed = True


class Session:
    def __init__(self, routes):
        self.routes, self.calls, self.responses = routes, [], []

    def get(self, url, **kwargs):
        self.calls.append(url)
        response = Response(url, *self.routes[url])
        self.responses.append(response)
        return response


@pytest.fixture
def source_env(tmp_path, monkeypatch):
    # Only DNS resolution is replaced, private IP and redirect checks remain real.
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    html = (b'<html><div id="other"><a href="/wrong.pdf">Wrong period</a></div>'
            b'<div id="report-42"><a href="/download/41" type="application/pdf" download>Summary</a>'
            b'<a href="/download/42" type="application/pdf" download>Monthly report</a></div></html>')
    session = Session({URL: (html, "text/html"), PDF_URL: (table_pdf(), "application/pdf")})
    core = tmp_path / "core/src/lakehouse"
    core.mkdir(parents=True)
    (core / "cli.py").write_text("# fixture")
    runner = FakeRunner()
    registry = SimpleNamespace(user_text=f"{URL} kaydet", active_question=f"{URL} kaydet", turn=1)
    tool = IngestFromUrlTool(SpyLakehouse(),
        LakehouseCLI(core_dir=tmp_path / "core", database=tmp_path / "test.db", data_root=tmp_path, runner=runner),
        allowed_root=tmp_path / "incoming", registry=registry, session=session)
    return tool, runner, session, tmp_path


def test_fragment_limits_attachment_selection_and_does_not_write(source_env):
    tool, runner, session, root = source_env
    result = tool.validate_and_run({"locator": URL, "name": "Report"})
    assert result.ok and result.content.startswith("EKLENMEDİ")
    assert "resource_index" in result.content and "Monthly report" in result.content
    assert "Wrong period" not in result.content
    assert session.calls == [URL] and not runner.calls
    assert not (root / "incoming").exists()
    assert all(r.closed for r in session.responses)


def test_extensionless_pdf_is_parsed_and_measure_selection_is_required(source_env):
    tool, runner, session, _ = source_env
    result = tool.validate_and_run({"locator": URL, "name": "Report", "resource_index": 1})
    assert result.ok and "value_row" in result.content
    assert "Nakdi Krediler (Milyar TL)" in result.content
    assert session.calls == [URL, PDF_URL] and not runner.calls


def test_pdf_matrix_reaches_cli_with_period_entities_units_and_source_chain(source_env):
    tool, runner, _session, root = source_env
    result = tool.validate_and_run({"locator": URL, "name": "Report", "resource_index": 1,
                                   "value_row": "Nakdi Krediler (Milyar TL)", "series_key": "risk_monthly"})
    assert result.ok and result.content.startswith("EKLENDİ"), result.content
    command = runner.calls[0][0]
    flags = dict(pairwise(command))
    assert flags["--frequency"] == "monthly"
    assert flags["--unit"] == "TRY_bn"
    assert flags["--entity-column"] == "kurum"
    assert flags["--decimal-separator"] == "," and flags["--thousands-separator"] == "."
    frame = pd.read_csv(flags["ingest-file"], dtype=str)
    assert frame["tarih"].tolist() == ["2026-07-31"] * 2
    assert frame["kurum"].tolist() == ["Banka A", "Toplam"]
    assert frame.iloc[:, 2].tolist() == ["1.234", "2.345"]
    assert URL in flags["--description"] and PDF_URL in flags["--description"]
    assert "sha256" in flags["--description"] and "pdfplumber" in flags["--description"]
    assert len(list((root / "incoming").glob("source_*.pdf"))) == 1
    assert len(list((root / "incoming").glob("source_*.html"))) == 1


def test_direct_html_table_and_extensionless_json(source_env):
    tool, _runner, session, _ = source_env
    table = (b'<html><table><tr><th>Tarih</th><th>Endeks</th></tr>'
             b'<tr><td>2026-07-01</td><td>10</td></tr><tr><td>2026-07-02</td><td>11</td></tr>'
             b'<tr><td>2026-07-03</td><td>12</td></tr></table></html>')
    url = "https://reports.example/table"
    tool._registry.user_text = f"{url} kaydet"
    session.routes[url] = (table, "text/html")
    assert tool.validate_and_run({"locator": url, "name": "Index"}).content.startswith("EKLENDİ")
    json_url = "https://reports.example/data"
    session.routes[json_url] = (b'[{"date":"2026-07-01","index":10}]', "application/json")
    selected = read_web_source(json_url, allowed_root=Path("unused"), session=session)
    assert selected.frame.iloc[0].tolist() == ["2026-07-01", "10"]


def test_missing_fragment_and_foreign_link_do_not_expand_scope(source_env):
    tool, runner, session, root = source_env
    session.routes[URL] = (b'<html><div id="different"><a href="/download/42" download>Report</a></div></html>', "text/html")
    result = tool.validate_and_run({"locator": URL, "name": "x"})
    assert "bölümü sayfada bulunamadı" in result.content and not runner.calls
    session.routes[URL] = (b'<html><div id="report-42"><a href="https://other.example/x.pdf" download>Outside</a></div></html>', "text/html")
    result = tool.validate_and_run({"locator": URL, "name": "x"})
    assert "indirilebilir veri dosyası yok" in result.content
    assert not runner.calls and not (root / "incoming").exists()


def test_private_redirect_and_missing_write_intent_still_block(source_env):
    tool, runner, session, _ = source_env
    session.routes[PDF_URL] = (b"", "text/plain", 302, {"location": "http://127.0.0.1/private.pdf"})
    result = tool.validate_and_run({"locator": URL, "name": "x", "resource_index": 1})
    assert not result.ok and result.error.error_code == "ACCESS_BLOCKED"
    assert "http://127.0.0.1/private.pdf" not in session.calls and not runner.calls
    tool._registry.user_text = f"{URL} ne içeriyor?"
    result = tool.validate_and_run({"locator": URL, "name": "x"})
    assert not result.ok and result.error.error_code == "INTENT_REQUIRED"


def test_single_date_frequency_asks_before_any_write(source_env):
    tool, runner, session, _ = source_env
    url = "https://reports.example/one.json"
    session.routes[url] = (b'[{"date":"2026-07-31","index":100}]', "application/json")
    tool._registry.user_text = f"{url} kaydet"
    result = tool.validate_and_run({"locator": url, "name": "single"})
    assert result.ok and "frekans:" in result.content and not runner.calls


def test_many_entities_one_date_does_not_crash_profiler():
    frame = pd.DataFrame({"date": ["2026-07-31"] * 6, "endeks": [str(i) for i in range(6)]})
    _, semantics = propose(profile_table(frame), frame, series_id="adhoc:one")
    assert semantics.frequency == "irregular"


def test_invalid_pdf_page_and_negative_indices(source_env):
    tool, runner, _, _ = source_env
    result = tool.validate_and_run({"locator": URL, "name": "x", "resource_index": 1, "pages": "99"})
    assert "Sayfa seçimi geçersiz" in result.content and not runner.calls
    result = tool.validate_and_run({"locator": URL, "name": "x", "resource_index": -1})
    assert not result.ok and result.error.error_code == "INVALID_ARGS"


def test_excel_formula_is_not_laundered_through_staged_csv(source_env):
    import openpyxl
    tool, runner, session, root = source_env
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["date", "index"])
    sheet.append(["2026-07-01", "=1+2"])
    buffer = io.BytesIO()
    book.save(buffer)
    url = "https://reports.example/export"
    session.routes[url] = (buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    tool._registry.user_text = f"{url} kaydet"
    result = tool.validate_and_run({"locator": url, "name": "Formula"})
    assert "formül içeriyor" in result.content
    assert not runner.calls and not (root / "incoming").exists()


def test_multiple_html_tables_require_explicit_selection(source_env):
    tool, runner, session, _ = source_env
    url = "https://reports.example/tables"
    table = (b'<table><tr><th>Tarih</th><th>Endeks</th></tr>'
             b'<tr><td>2026-07-01</td><td>10</td></tr>'
             b'<tr><td>2026-07-02</td><td>11</td></tr>'
             b'<tr><td>2026-07-03</td><td>12</td></tr></table>')
    session.routes[url] = (b'<html>' + table + table + b'</html>', 'text/html')
    tool._registry.user_text = f"{url} kaydet"
    result = tool.validate_and_run({"locator": url, "name": "Index"})
    assert "table_index" in result.content and not runner.calls
    result = tool.validate_and_run({"locator": url, "name": "Index", "table_index": 1})
    assert result.content.startswith("EKLENDİ") and len(runner.calls) == 1
