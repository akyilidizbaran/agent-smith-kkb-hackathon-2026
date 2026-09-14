"""D01/D07 (ADR-0065): kayıpsız ve açık kurallı anahtar eşleme; yardımcı kolon kullanıcı verisini ezmez.

Bağımsız kontrolün R01/R07 yeniden üretimleri birebir burada: büyük ardışık tamsayılar, '001' ↔ '1', boş anahtarlar,
aynı gün iki saat, bildirilmiş metin/tamsayı eşlemesi, yinelenen sağ anahtar; `__k=preserve-me`, `_merge`, hazır
`value_k2`, aynı adlı kolonlar ve açık `columns` seçimi."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.lakehouse import QueryProvenance  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.workspace_join import JoinParams, WorkspaceJoinTool, key_kind  # noqa: E402


def _ws(left: pd.DataFrame, right: pd.DataFrame) -> tuple[AnalysisWorkspace, WorkspaceJoinTool]:
    ws = AnalysisWorkspace()
    ws.set_table(left, description="sol", provenance=QueryProvenance(sql="sol.csv", dataset_ids=[], sources=["web — sol"]))
    ws.set_table(right, description="sağ", provenance=QueryProvenance(sql="sag.csv", dataset_ids=[], sources=["web — sağ"]))
    return ws, WorkspaceJoinTool(ws)


def _run(tool, **kw):
    p = JoinParams(left="k1", right="k2", purpose="test", **kw)
    assert tool.validate_refs(p) is None
    return tool.run(p)


def test_ardisik_buyuk_tamsayilar_asla_eslesmez() -> None:
    ws, tool = _ws(pd.DataFrame({"id": [9007199254740992, 7], "a": [1, 2]}),
                   pd.DataFrame({"id": [9007199254740993, 7], "v": [99, 5]}))
    r = _run(tool, left_key="id")
    assert r.ok and pd.isna(ws.table.loc[ws.table["id"] == 9007199254740992, "v"].iloc[0]), "R01: 99 yanlış satıra yazılmaz"
    assert ws.table.loc[ws.table["id"] == 7, "v"].iloc[0] == 5
    assert "yalnız solda 1" in r.content and "yalnız sağda 1" in r.content
    assert key_kind(pd.Series([9007199254740992])) == "tamsayı"
    only_big = _ws(pd.DataFrame({"id": [9007199254740992]}), pd.DataFrame({"id": [9007199254740993], "v": [99]}))[1]
    miss = _run(only_big, left_key="id")
    assert not miss.ok and miss.error.error_code == "JOIN_MISMATCH"


def test_float_okunmus_buyuk_kimlik_dogruluk_iddia_etmez() -> None:
    _, tool = _ws(pd.DataFrame({"id": [9.007199254740992e15, 1.0]}), pd.DataFrame({"id": [9007199254740993.0, 1.0], "v": [1, 2]}))
    r = _run(tool, left_key="id")
    assert not r.ok and "2^53" in r.error.message and r.error.layer == "data"


def test_001_ile_1_acik_kural_olmadan_farkli_kalir_sayi_kuraliyla_eslesir() -> None:
    ws, tool = _ws(pd.DataFrame({"kod": ["001", "002"], "a": [1, 2]}), pd.DataFrame({"kod": ["1", "2"], "v": [10, 20]}))
    r = _run(tool, left_key="kod")
    assert not r.ok and r.error.candidates == ["sayi"] and "birebir eşitlikle 0" in r.error.message
    assert ws.active_source_id == "k2"
    ok = _run(tool, left_key="kod", key_policy="sayi")
    assert ok.ok and ws.table["v"].tolist() == [10, 20] and ws.table["kod"].tolist() == ["001", "002"], "ham değer korunur"
    assert "Anahtar kuralı: sayi" in ok.content and "baştaki sıfırlar yok sayıldı" in ok.content
    assert "kural: sayi" in ws.column_provenance("v").sql


def test_bos_anahtarlar_ayni_varlik_sayilmaz() -> None:
    ws, tool = _ws(pd.DataFrame({"id": [None, "a"], "x": [1, 2]}), pd.DataFrame({"id": [None, "a"], "v": [7, 8]}))
    r = _run(tool, left_key="id")
    assert r.ok and pd.isna(ws.table["v"].iloc[0]) and ws.table["v"].iloc[1] == 8
    assert "anahtarı boş" in r.content and "boş anahtarlar hiçbir satırla eşleştirilmedi" in r.content


def test_ayni_gun_iki_saat_zaman_damgasinda_ayri_kalir_gun_kurali_acik() -> None:
    left = pd.DataFrame({"t": pd.to_datetime(["2025-01-01 09:00", "2025-01-01 17:00"]), "a": [1, 2]})
    ws, tool = _ws(left, pd.DataFrame({"t": pd.to_datetime(["2025-01-01 09:00"]), "v": [5]}))
    r = _run(tool, left_key="t")
    assert r.ok and ws.table["v"].iloc[0] == 5 and pd.isna(ws.table["v"].iloc[1])
    ws2, tool2 = _ws(left, pd.DataFrame({"t": pd.to_datetime(["2025-01-01"]), "v": [5]}))
    asked = _run(tool2, left_key="t")
    assert not asked.ok and asked.error.candidates == ["tarih_gun"]
    day = _run(tool2, left_key="t", key_policy="tarih_gun")
    assert day.ok and ws2.table["v"].tolist() == [5, 5] and ws2.table["t"].dt.hour.tolist() == [9, 17], "saat bilgisi kaynakta kalır"


def test_bildirilmis_metin_tamsayi_eslemesi_dogru_ve_gorunur() -> None:
    ws, tool = _ws(pd.DataFrame({"id": [1, 2]}), pd.DataFrame({"id": ["1", "02"], "v": [10, 20]}))
    asked = _run(tool, left_key="id")
    assert not asked.ok and set(asked.error.candidates) == {"metin", "sayi"} and "tamsayı" in asked.error.message
    metin = _run(tool, left_key="id", key_policy="metin")
    assert metin.ok and ws.table["v"].iloc[0] == 10 and pd.isna(ws.table["v"].iloc[1]) and "Anahtar kuralı: metin" in metin.content
    sayi = _run(tool, left_key="id", key_policy="sayi")
    assert sayi.ok and ws.table["v"].tolist() == [10, 20]


def test_yinelenen_sag_anahtar_kural_yuzunden_olusunca_da_reddedilir() -> None:
    _, tool = _ws(pd.DataFrame({"il": ["Van"], "x": [1]}), pd.DataFrame({"il": ["Van", "van "], "v": [1, 2]}))
    r = _run(tool, left_key="il", key_policy="metin_normal")
    assert not r.ok and r.error.error_code == "JOIN_MISMATCH" and "metin_normal' kuralı yüzünden" in r.error.message


def test_d07_kullanici_kolonlari_ve_yardimci_adlar_korunur() -> None:
    left = pd.DataFrame({"id": ["a", "b"], "__k": ["preserve-me", "x"], "_merge": ["sol", "sol"], "value_k2": [0, 0], "value": [1, 2]})
    right = pd.DataFrame({"id": ["a"], "value": [99], "_merge": ["sağ"], "__k": ["r"]})
    before_left, before_right = left.copy(), right.copy()
    ws, tool = _ws(left, right)
    r = _run(tool, left_key="id")
    t = ws.table
    assert r.ok and t.loc[0, "__k"] == "preserve-me" and t.loc[0, "_merge"] == "sol", "R07: kullanıcı kolonu ve değeri korunur"
    assert list(t.columns) == ["id", "__k", "_merge", "value_k2", "value", "value_k2_2", "_merge_k2", "__k_k2"]
    assert t.columns.is_unique and t.loc[0, "value_k2_2"] == 99 and t.loc[0, "value_k2"] == 0
    assert "value → value_k2_2" in r.content and "kural: tam" in ws.column_provenance("value_k2_2").sql
    pd.testing.assert_frame_equal(ws.source("k1").frame, before_left)
    pd.testing.assert_frame_equal(ws.source("k2").frame, before_right)
    ws2, tool2 = _ws(left, right)
    only = _run(tool2, left_key="id", columns=["value"])
    assert only.ok and list(ws2.table.columns) == ["id", "__k", "_merge", "value_k2", "value", "value_k2_2"]


def test_outer_birlestirmede_yalniz_sagdaki_satir_ham_anahtarla_eklenir() -> None:
    ws, tool = _ws(pd.DataFrame({"id": [1], "a": [1]}), pd.DataFrame({"id": [1, 3], "v": [5, 6]}))
    r = _run(tool, left_key="id", how="outer")
    assert r.ok and ws.table["id"].tolist() == [1, 3] and ws.table["v"].tolist() == [5, 6] and pd.isna(ws.table["a"].iloc[1])
    ws2, tool2 = _ws(pd.DataFrame({"id": [1, 2], "a": [1, 2]}), pd.DataFrame({"id": [1], "v": [5]}))
    inner = _run(tool2, left_key="id", how="inner")
    assert inner.ok and ws2.table["id"].tolist() == [1] and "sonuca girmedi" in inner.content
