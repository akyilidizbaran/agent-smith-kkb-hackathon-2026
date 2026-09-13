"""Analitik araçlar: aktif tablo üzerinde, sütun ekler, kartı yazar, kanıt için not eder (ADR-0040)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.lakehouse import QueryProvenance  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.analytics import AnomalyDetectTool, ChangePointsTool, LeadLagTool  # noqa: E402


def _ws(n: int = 48, jump_at: int | None = 24) -> AnalysisWorkspace:
    rng = np.random.default_rng(7)
    growth = 1 + (2.0 + rng.normal(0, 0.3, n)) / 100
    v = 100 * np.cumprod(growth)
    if jump_at is not None:
        v[jump_at:] *= 1.15
    dates = pd.date_range("2022-01-31", periods=n, freq="ME").date
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"donem": dates, "bakiye": v, "il": ["X"] * n}), description="test",
                 provenance=QueryProvenance(sql="SELECT ...", dataset_ids=["s:1"], sources=["test"]))
    return ws


def test_anomali_sutun_ekler_ve_sicrama_ayini_kartta_yazar() -> None:
    ws = _ws()
    r = AnomalyDetectTool(ws).validate_and_run({"column": "bakiye", "purpose": "aykırı ay"})
    assert r.ok, r.content
    assert "bakiye_anomali" in ws.table.columns and "bakiye_skor" in ws.table.columns and "bakiye_degisim_yuzde" in ws.table.columns
    assert len(ws.table) == 48 and (ws.table["bakiye_anomali"] == "aykırı").sum() >= 1
    assert ws.table.loc[24, "bakiye_anomali"] == "aykırı" and "2024-01-31" in r.content
    assert "NEDEN" not in r.content and "sebep uydurma" in r.content
    assert ws.peeks() and ws.peeks()[0][0].startswith("anomaly_detect")
    assert ws.column_provenance("bakiye_anomali").sql.startswith("türetilmiş: anomali(")


def test_olmayan_ya_da_sayisal_olmayan_sutun_hata() -> None:
    ws = _ws()
    r = AnomalyDetectTool(ws).validate_and_run({"column": "yok", "purpose": "x"})
    assert not r.ok and r.error.error_code == "COLUMN_NOT_FOUND" and "bakiye" in r.error.candidates
    r = AnomalyDetectTool(ws).validate_and_run({"column": "il", "purpose": "x"})
    assert not r.ok and r.error.error_code == "INVALID_ARGS"
    r = AnomalyDetectTool(AnalysisWorkspace()).validate_and_run({"column": "bakiye", "purpose": "x"})
    assert not r.ok and r.error.error_code == "NO_ACTIVE_TABLE"


def test_kirilma_rejim_sutunu_ve_kart() -> None:
    rng = np.random.default_rng(8)
    g = np.array([0.5] * 30 + [3.0] * 30) / 100 + rng.normal(0, 0.001, 60)
    v = 100 * np.cumprod(1 + g)
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"donem": pd.date_range("2021-01-31", periods=60, freq="ME").date, "bakiye": v}),
                 description="t", provenance=QueryProvenance(sql="q", dataset_ids=[], sources=["t"]))
    r = ChangePointsTool(ws).validate_and_run({"column": "bakiye", "purpose": "kırılma"})
    assert r.ok, r.content
    assert "bakiye_rejim" in ws.table.columns and ws.table["bakiye_rejim"].nunique() >= 2
    assert "kırılma 1:" in r.content and "2023-0" in r.content and "önceki rejim" in r.content


def test_oncul_ardil_karti_nedensellik_degil_der() -> None:
    rng = np.random.default_rng(9)
    a = rng.normal(0, 1, 120)
    b = np.array([0.0] * 120)
    for t in range(2, 120):
        b[t] = 0.9 * a[t - 2] + 0.2 * rng.normal()
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"hafta": pd.date_range("2024-01-05", periods=120, freq="W-FRI").date, "faiz": a, "bakiye": b}),
                 description="t", provenance=QueryProvenance(sql="q", dataset_ids=[], sources=["t"]))
    r = LeadLagTool(ws).validate_and_run({"column_a": "faiz", "column_b": "bakiye", "max_lag": 4, "basis": "level", "purpose": "öncülük"})
    assert r.ok, r.content
    assert "gecikme +2" in r.content and "faiz, bakiye'den 2 dönem ÖNCE" in r.content
    assert "NEDENSELLİK DEĞİLDİR" in r.content and "Granger" in r.content
    assert len(ws.table.columns) == 3          # tablo değişmedi
    names = [p[0] for p in ws.peeks()]
    assert any(n.startswith("granger") for n in names) and any(n.startswith("lead_lag") for n in names)
    same = LeadLagTool(ws).validate_and_run({"column_a": "faiz", "column_b": "faiz", "purpose": "x"})
    assert not same.ok and same.error.error_code == "INVALID_ARGS"


def test_sayi_ayristirma_tanimlayici_ve_sifirli_ondalik() -> None:
    from kkb_agent.core.grounding import numbers_in
    assert numbers_in("bddk_weekly:5690_3 serisinde r=0.263, 124 hafta, k=1,5, 65.425.957 kişi") == [0.263, 124.0, 1.5, 65425957.0]
    assert numbers_in("TP.KTF12 2025'te %33,39") == [2025.0, 33.39]


def test_unicode_eksi_ve_olumsuz_nedensellik() -> None:
    from kkb_agent.core.grounding import causal_language, grounding_check, numbers_in
    assert numbers_in("r = \u22120,54 ve 2024\u20132026") == [-0.54, 2024.0, 2026.0]
    assert grounding_check("soru", "En güçlü ilişki r = \u22120,54.", ["gecikme +1, r=-0.54"]) == "OK"
    assert causal_language("Faiz artışı bakiyenin düşmesine neden oldu.") == ["neden oldu"]
    assert causal_language("Bu, faizin bakiyeye neden olduğu anlamına gelmez; öncülük bulgusudur.") == []
    assert causal_language("Faizin bakiyeye yol açtığı söylenemez.") == []


def test_tarih_yazimi_sayi_sayilmaz() -> None:
    from kkb_agent.core.evidence import _number_texts
    from kkb_agent.core.grounding import numbers_in
    assert numbers_in("Son güncelleme 27.07.2026; 2025 toplamı 28.088,44 kg; 2026-06-30 itibarıyla 31,07") == [2025.0, 28088.44, 31.07]
    assert [t for t, _ in _number_texts("Güncelleme tarihi 27.07.2026, değer 3.058,69")] == ["3.058,69"]
