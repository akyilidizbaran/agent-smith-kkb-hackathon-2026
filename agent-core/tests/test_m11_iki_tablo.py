"""M11 (ADR-0059): oturumda kimlikli tablolar, denetimli birleştirme (A09), bekleyen netleştirme sorusu."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.lakehouse import QueryProvenance  # noqa: E402
from kkb_agent.core.agent import pending_question  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.workspace_join import JoinParams, WorkspaceJoinTool  # noqa: E402
from kkb_agent.tools.workspace_query import WorkspaceQueryParams, WorkspaceQueryTool  # noqa: E402


def _prov(name):
    return QueryProvenance(sql=f"web_url /x/{name}.csv tablo#0", dataset_ids=[], sources=[f"web — {name}"])


def _two():
    ws = AnalysisWorkspace()
    k1 = ws.set_table(pd.DataFrame({"il": ["Adana", "Ankara", "Van", "Van"], "nufus": [2.2, 5.8, 1.1, 1.1]}), description="nüfus", provenance=_prov("nufus"))
    k2 = ws.set_table(pd.DataFrame({"il": ["ankara", "Adana ", "İzmir"], "hastane": [120, 40, 90]}), description="hastane", provenance=_prov("hastane"))
    return ws, k1, k2


def test_ikinci_yukleme_birinciyi_kaybettirmez_ve_llm_ozeti_listeler() -> None:
    ws, k1, k2 = _two()
    assert (k1, k2) == ("k1", "k2") and [s.id for s in ws.sources()] == ["k1", "k2"]
    assert list(ws.source("k1").frame.columns) == ["il", "nufus"] and ws.active_source_id == "k2"
    text = ws.describe_for_llm()
    assert "k1: nüfus — 4 satır" in text and "k2: hastane" in text


def test_a09_birlestirme_eslesmeyen_ve_coktan_bire_karta_yazilir() -> None:
    ws, k1, k2 = _two()
    tool = WorkspaceJoinTool(ws)
    p = JoinParams(left="k1", right="k2", left_key="il", purpose="nüfus ve hastane")
    assert tool.validate_refs(p) is None
    r = tool.run(p)
    t = ws.table
    assert r.ok and len(t) == 4 and list(t.columns) == ["il", "nufus", "hastane"], "left: sol satırlar korunur, anahtar tekrarlanmaz"
    assert t.loc[t["il"] == "Ankara", "hastane"].iloc[0] == 120 and t.loc[t["il"] == "Adana", "hastane"].iloc[0] == 40, "boşluk/büyük-küçük farkı eşleşir"
    assert "yalnız solda 2" in r.content and "yalnız sağda 1" in r.content and "çoktan-bire" in r.content
    assert ws.column_provenance("hastane").sources == ["web — hastane"] and ws.column_provenance("nufus").sources == ["web — nufus"]
    assert [s.id for s in ws.sources()] == ["k1", "k2", "k3"], "sonuç da kimlikli kaynak"


def test_anahtar_belirsizse_sorar_sagda_yinelenen_anahtar_reddedilir() -> None:
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"il": ["A"], "yil": [2025], "x": [1]}), description="a")
    ws.set_table(pd.DataFrame({"il": ["A"], "yil": [2025], "y": [2]}), description="b")
    err = WorkspaceJoinTool(ws).validate_refs(JoinParams(left="k1", right="k2", purpose="?"))
    assert err is not None and "belirsiz" in err.message and set(err.candidates) == {"il", "yil"}
    ws2, k1, k2 = _two()
    out = WorkspaceJoinTool(ws2).run(JoinParams(left="k2", right="k1", left_key="il", purpose="ters"))
    assert not out.ok and out.error.error_code == "JOIN_MISMATCH" and "yinelenen" in out.error.message and "Van" in out.error.message


def test_ad_cakismasi_sonek_hic_eslesmeme_ve_tarih_anahtari() -> None:
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"tarih": pd.to_datetime(["2025-01-31", "2025-02-28"]), "deger": [1.0, 2.0]}), description="a")
    ws.set_table(pd.DataFrame({"tarih": ["2025-01-31", "2025-02-28"], "deger": [10.0, 20.0]}), description="b")
    r = WorkspaceJoinTool(ws).run(JoinParams(left="k1", right="k2", left_key="tarih", purpose="x"))
    assert r.ok and ws.table["deger_k2"].tolist() == [10.0, 20.0] and "deger → deger_k2" in r.content
    ws.set_table(pd.DataFrame({"kod": ["x"], "v": [1]}), description="c")
    ws.set_table(pd.DataFrame({"kod": ["y"], "w": [1]}), description="d")
    none = WorkspaceJoinTool(ws).run(JoinParams(left="k4", right="k5", left_key="kod", purpose="x"))
    missing_col = WorkspaceJoinTool(ws).run(JoinParams(left="k3", right="k5", left_key="kod", purpose="x"))
    assert not missing_col.ok and missing_col.error.error_code == "COLUMN_NOT_FOUND"
    assert not none.ok and "hiç eşleşmedi" in none.error.message


def test_workspace_query_oturum_tablolarini_okur() -> None:
    ws, k1, k2 = _two()
    tool = WorkspaceQueryTool(ws)
    ok = WorkspaceQueryParams(sql="SELECT count(*) AS n FROM k1", purpose="say")
    assert tool.validate_refs(ok) is None and tool.run(ok).ok
    assert tool.validate_refs(WorkspaceQueryParams(sql="SELECT * FROM k9", purpose="x")).error_code == "INVALID_ARGS"


def test_bekleyen_netlestirme_sorusuna_kisa_yanit() -> None:
    hist = [SimpleNamespace(role="user", content="Kredi bakiyesini göster"),
            SimpleNamespace(role="assistant", content="Birden çok seri var. Hangisini istersiniz: konut mu, taşıt mı?")]
    assert pending_question(hist, "konut, 2025") == "Hangisini istersiniz: konut mu, taşıt mı?"
    assert pending_question(hist, "2025 yılında konut kredisi bakiyesi aylık olarak nasıl değişti acaba") is None
    assert pending_question([SimpleNamespace(role="assistant", content="Tamam.")], "konut") is None
