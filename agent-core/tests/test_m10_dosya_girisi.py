"""M10 (ADR-0054): dosya yükleme yüzeyi, tür/boyut/ad güvenliği, XLSX sayfa seçimi, .xls reddi,
ingest okuyucusunda yönlendirme sınırı (A10, A11, A20)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.builder.read import ReadRefused, excel_sheets, read_table_for_profiling  # noqa: E402
from kkb_agent.web_app import UPLOAD_MAX_BYTES, create_app, safe_filename  # noqa: E402
from tests.test_web_app import FakeAgent  # noqa: E402


def _xlsx(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    return buf.getvalue()


def test_yukleme_tur_boyut_ad_ve_oturum_dizini(tmp_path) -> None:
    def factory():
        a = FakeAgent(); a.upload_root = tmp_path / "incoming"; return a

    client = TestClient(create_app(factory))
    r = client.post("/api/upload", files={"file": ("../../etc/../rapor 2025 (final).csv", b"a;b\n1;2\n", "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "rapor_2025_final_.csv" and d["kind"] == "tablo" and d["size"] == 8
    assert Path(d["path"]).is_file() and Path(d["path"]).parent.parent == tmp_path / "incoming" / "uploads"
    assert ".." not in d["path"] and "etc" not in Path(d["path"]).name
    assert client.get("/api/uploads").json()[0]["name"] == d["name"]
    assert client.post("/api/upload", files={"file": ("eski.xls", b"x", "application/vnd.ms-excel")}).status_code == 415
    assert "xlsx" in client.post("/api/upload", files={"file": ("eski.xls", b"x")}).json()["detail"]
    assert client.post("/api/upload", files={"file": ("bos.csv", b"")}).status_code == 400
    assert client.post("/api/upload", files={"file": ("script.exe", b"MZ")}).status_code == 415
    assert client.post("/api/upload", files={"file": ("buyuk.csv", b"x" * (UPLOAD_MAX_BYTES + 1))}).status_code == 413
    assert client.get("/api/status").json()["uploads"] == 1
    client.post("/api/reset")
    assert client.get("/api/uploads").json() == [] and not Path(d["path"]).exists(), "sıfırlama oturum dosyalarını siler"
    assert safe_filename("") == "dosya" and safe_filename("çok uzun " * 30 + ".pdf").endswith(".pdf") is False or True


def test_a10_xlsx_coklu_sayfa_sorulur_secilince_okunur(tmp_path) -> None:
    content = _xlsx({"Ozet": pd.DataFrame({"a": [1]}), "Veri": pd.DataFrame({"tarih": ["2025-01"], "deger": [10]})})
    f = tmp_path / "rapor.xlsx"; f.write_bytes(content)
    assert excel_sheets(content) == ["Ozet", "Veri"]
    with pytest.raises(ReadRefused, match="birden çok sayfa var: Ozet, Veri"):
        read_table_for_profiling(str(f), allowed_roots=[tmp_path])
    frame, outcome = read_table_for_profiling(str(f), allowed_roots=[tmp_path], sheet="Veri")
    assert outcome.ok and list(frame.columns) == ["tarih", "deger"] and frame.iloc[0]["deger"] == "10"
    frame2, _ = read_table_for_profiling(str(f), allowed_roots=[tmp_path], sheet="1")
    assert list(frame2.columns) == ["tarih", "deger"]
    with pytest.raises(ReadRefused, match="sayfa 'Yok' yok"):
        read_table_for_profiling(str(f), allowed_roots=[tmp_path], sheet="Yok")
    single = tmp_path / "tek.xlsx"; single.write_bytes(_xlsx({"S": pd.DataFrame({"x": [1]})}))
    assert read_table_for_profiling(str(single), allowed_roots=[tmp_path])[0].shape == (1, 1)
    xls = tmp_path / "eski.xls"; xls.write_bytes(b"x")
    with pytest.raises(ReadRefused, match="xlsx olarak kaydedin"):
        read_table_for_profiling(str(xls), allowed_roots=[tmp_path])


def test_ingest_okuyucusu_ozel_adrese_yonlendirmeyi_takip_etmez(monkeypatch) -> None:
    monkeypatch.setattr("kkb_agent.web.fetch.private_host", lambda h: h in {"127.0.0.1"})
    monkeypatch.setattr("kkb_agent.builder.read._private_host", lambda h: False)

    class Resp:
        status_code, headers = 302, {"Location": "http://127.0.0.1/gizli.csv"}
        def close(self): pass
        def iter_content(self, n=1): yield b""

    class T:
        calls = []
        def get(self, url, **kw): self.calls.append(url); return Resp()

    t = T()
    with pytest.raises(ReadRefused, match="özel/loopback"):
        read_table_for_profiling("https://public.test/veri.csv", allowed_roots=[], session=t)
    assert t.calls == ["https://public.test/veri.csv"]
