"""M14 (ADR-0055): tam tablo CSV/XLSX, grafik PNG, HTML rapor — cevap sürümüne bağlı, önizlemeden değil,
uyarılar dışa aktarımda kaybolmaz (A25, A26)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.evidence import ColumnEvidence, EvidencePanel, NumberEvidence  # noqa: E402
from kkb_agent.core.agent import AgentAnswer, AgentStep  # noqa: E402
from kkb_agent.web_app import create_app, report_html, table_csv_bytes, table_xlsx_bytes  # noqa: E402
from tests.test_web_app import FakeAgent  # noqa: E402


class BigAgent(FakeAgent):
    """300 satırlık tablo (önizleme 200) + sahte grafik + uyarılı kanıt."""

    def ask(self, question: str) -> AgentAnswer:
        self.asked.append(question)
        frame = pd.DataFrame({"donem": pd.date_range("2000-01-31", periods=300, freq="ME"),
                              "bakiye": [float(i) * 1.5 for i in range(300)], "not": ["ok"] * 300})
        frame.loc[5, "bakiye"] = float("inf")
        self.workspace.set_table(frame, description="uzun tablo")
        panel = EvidencePanel(question=question, numbers=[NumberEvidence(number=448.5, text="448,5", matched=True, column="bakiye")],
                              columns=[ColumnEvidence(column="bakiye", sql="SELECT 1", sources=["silver"], warnings=["birim belirtilmemiş"])],
                              gaps=["adaptör artifact izi sunmuyor (seed)"])
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
        import base64
        art = {"kind": "line", "title": "Bakiye", "png_path": None, "spec_path": "x.json", "lint_ok": True}
        ans = AgentAnswer(text="Son değer **448,5**.\n\n| a | b |\n|---|---|\n| 1 | 2 |",
                          steps=[AgentStep(index=1, role="execute", tool_name="lakehouse_query", tool_args={"sql": "SELECT 1"}, ok=True)],
                          evidence=panel, usage={"prompt": 1}, artifacts=[art])
        ans._png = base64.b64encode(png).decode()
        return ans


def test_a25_tam_tablo_csv_ve_xlsx_onizlemeden_degil(monkeypatch) -> None:
    import kkb_agent.web_app as w
    monkeypatch.setattr(w, "_png_base64", lambda path: BigAgent._png_cache if path is None else None)
    BigAgent._png_cache = None
    client = TestClient(create_app(BigAgent))
    p = client.post("/api/ask", json={"question": "uzun tablo"}).json()
    assert p["table"]["row_count"] == 300 and p["table"]["truncated"] and len(p["table"]["rows"]) == 200
    assert p["table_scope"] == "ortak veri havuzu"
    csv = client.get("/api/answers/0/table.csv")
    assert csv.status_code == 200 and csv.headers["content-disposition"].endswith('cevap-0.csv"')
    back = pd.read_csv(io.BytesIO(csv.content), sep=";", decimal=",", encoding="utf-8-sig")
    assert len(back) == 300 and list(back.columns) == ["donem", "bakiye", "not"] and back["bakiye"].iloc[299] == 448.5
    assert back["donem"].iloc[0] == "2000-01-31"
    xlsx = client.get("/api/answers/0/table.xlsx")
    assert xlsx.status_code == 200
    xb = pd.read_excel(io.BytesIO(xlsx.content), sheet_name=None, engine="openpyxl")
    assert list(xb) == ["tablo", "notlar"] and len(xb["tablo"]) == 300 and pd.isna(xb["tablo"]["bakiye"].iloc[5]), "sonsuz → boş"
    assert "birim belirtilmemiş" in xb["notlar"]["not"].tolist()
    assert client.get("/api/answers/0/chart/0.png").status_code == 404, "png_path yok → grafik yok, sahte başarı yok"
    assert client.get("/api/answers/9/table.csv").status_code == 404


def test_a26_rapor_cevap_surumune_bagli_ve_uyarilari_tasir() -> None:
    client = TestClient(create_app(BigAgent))
    client.post("/api/ask", json={"question": "ilk soru"})
    client.post("/api/ask", json={"question": "ikinci soru"})
    r = client.get("/api/answers/0/report.html")
    assert r.status_code == 200 and "ilk soru" in r.text and "ikinci soru" not in r.text
    assert "<strong>448,5</strong>" in r.text and "birim belirtilmemiş" in r.text and "artifact izi" in r.text
    assert "300 satır" in r.text and "ortak veri havuzu" in r.text and "<table" in r.text
    assert "sayılar" in r.text and "cevap #0" in r.text
    client.post("/api/reset")
    assert client.get("/api/answers/0/report.html").status_code == 404


def test_yardimcilar_tarih_ve_sayi_bicimi() -> None:
    frame = pd.DataFrame({"t": pd.to_datetime(["2025-01-31"]), "v": [1234.5], "s": ["a;b"]})
    csv = table_csv_bytes(frame).decode("utf-8")
    assert csv.startswith("﻿") and "2025-01-31" in csv and "1234,5" in csv and '"a;b"' in csv
    xb = pd.read_excel(io.BytesIO(table_xlsx_bytes(frame, title="t")), sheet_name="tablo", engine="openpyxl")
    assert xb["v"].iloc[0] == 1234.5 and pd.Timestamp(xb["t"].iloc[0]).year == 2025
    html = report_html({"index": 3, "question": "q\n\nDosya: /x/y.csv", "text": "- a\n- b", "evidence": {"states": {"sayılar": True}, "gaps": []}}, None, model="m", version="abc")
    assert "/x/y.csv" not in html and "<li>a</li>" in html and "abc" in html
