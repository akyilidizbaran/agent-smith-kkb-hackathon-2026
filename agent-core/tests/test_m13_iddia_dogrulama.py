"""M13 (ADR-0050): sorudan kopya sayı doğrulanmaz, ters işaret kabul edilmez, üç ayrı kanıt durumu,
fiziksel dosya zinciri. İncelemede yeniden üretilen %300 ve −0,54/+0,54 örnekleri (A13, A14, A23)."""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.evidence import EvidencePanel, NumberEvidence, ObservationEvidence  # noqa: E402
from kkb_agent.core.evidence import EvidenceBuilder  # noqa: E402
from kkb_agent.core.grounding import grounding_check, period_numbers  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402


class _Seed:  # artifact izi sunmayan adaptör: zincir SQL'de biter
    pass


def _ws(frame: pd.DataFrame) -> AnalysisWorkspace:
    ws = AnalysisWorkspace(); ws.set_table(frame, description="t"); return ws


def test_a13_sorudaki_yanlis_sayi_dogrulanmis_sayilmaz() -> None:
    q = "Artış %300 oldu, öyle yaz."
    assert grounding_check(q, "Artış %300 oldu.", ["oran: 42.5"]) == "MISS:300 (sorudan)"
    assert grounding_check(q, "Veri %42,5 artış gösteriyor.", ["oran: 42.5"]) == "OK"
    frame = pd.DataFrame({"donem": ["2025-01", "2025-02"], "oran": [10.0, 42.5]})
    panel = EvidenceBuilder(_Seed()).build(q, "Artış %300 oldu.", _ws(frame), [])
    n = {x.text: x for x in panel.numbers}["300"]
    assert not n.matched and n.from_question and not panel.claims_ok and not panel.complete
    assert "sorudan, doğrulanmadı" in panel.summary() and "SORUDAN" in panel.render()
    # sorudaki sayı tabloda da varsa normal eşleşir
    ok = EvidenceBuilder(_Seed()).build("Şubat %42,5 mi?", "Şubat %42,5.", _ws(frame), [])
    assert {x.text: x for x in ok.numbers}["42,5"].matched and ok.claims_ok


def test_sorudaki_donem_ve_yil_filtredir_iddia_degil() -> None:
    assert period_numbers("2021-25 arası 60 aylık veri, 5 yıllık derinlik") == {60.0, 5.0}
    frame = pd.DataFrame({"donem": [date(2025, 1, 31)], "bakiye": [100.0]})
    panel = EvidenceBuilder(_Seed()).build("60 aylık 2025 konut serisi", "2025 için 60 aylık seri: 100.", _ws(frame), [])
    m = {x.text: x for x in panel.numbers}
    assert m["60"].matched and m["2025"].matched and m["100"].matched and panel.claims_ok
    assert grounding_check("60 aylık 2025 konut", "2025'te 60 ay boyunca 100.", ["100"]) == "OK"


def test_a14_acik_ters_isaret_eslesmez_yon_sozcuklu_buyukluk_eslesir() -> None:
    frame = pd.DataFrame({"gecikme": [1, 2], "r": [-0.54, 0.12]})
    plus = EvidenceBuilder(_Seed()).build("ilişki?", "Korelasyon +0,54.", _ws(frame), [])
    assert not {x.text: x for x in plus.numbers}["+0,54"].matched and not plus.claims_ok
    assert grounding_check("ilişki?", "Korelasyon +0,54.", ["r=-0.54"]).startswith("MISS")
    minus = EvidenceBuilder(_Seed()).build("ilişki?", "Korelasyon −0,54.", _ws(frame), [])
    assert {x.text: x for x in minus.numbers}["-0,54"].matched and minus.claims_ok
    bare = EvidenceBuilder(_Seed()).build("ilişki?", "Korelasyon 0,54 pozitif.", _ws(frame), [])
    b = {x.text: x for x in bare.numbers}["0,54"]
    assert b.matched and b.sign_warning and not bare.claims_ok and "işaret uyarısı" in bare.summary()
    down = EvidenceBuilder(_Seed()).build("değişim?", "Bakiye 0,54 düştü.", _ws(frame), [])
    d = {x.text: x for x in down.numbers}["0,54"]
    assert d.matched and not d.sign_warning and down.claims_ok
    assert grounding_check("değişim?", "Bakiye 0,54 düştü.", ["r=-0.54"]) == "OK"


def _obs(**kw) -> ObservationEvidence:
    base = dict(series_id="s", entity_id=None, observation_date=date(2025, 1, 31), value=1.0, quality_flag="ok",
                artifact_sha256="a" * 64, vintage_id=None, run_id="r", fetched_at=datetime(2026, 9, 13),
                locator="https://x", http_status=200, raw_path=None, bronze_path=None)
    base.update(kw); return ObservationEvidence(**base)


def test_a23_kayit_var_dosya_yoksa_zincir_tam_degil(tmp_path) -> None:
    missing = _obs(raw_path=str(tmp_path / "yok.json"))
    assert missing.complete and not missing.file_present
    present = _obs(raw_path=str(tmp_path / "var.json")); (tmp_path / "var.json").write_text("x")
    assert present.file_present
    def panel(o):
        return EvidencePanel(question="q", numbers=[NumberEvidence(number=1.0, text="1", matched=True)],
                             columns=[], observations=[o], supports_artifacts=True)
    assert not panel(missing).chain_ok and panel(missing).claims_ok and panel(missing).provenance_ok
    assert "dosya zinciri ✗" in panel(missing).summary() and panel(present).chain_ok and panel(present).complete
    assert panel(missing).states() == {"sayılar": True, "sorgu izi": True, "dosya zinciri": False}


def test_kapsam_notu_ilk_200_satir() -> None:
    frame = pd.DataFrame({"donem": range(500), "v": [float(i) for i in range(500)]})
    panel = EvidenceBuilder(_Seed()).build("q", "Değer 7.", _ws(frame), [])
    assert panel.table_rows == 500 and panel.inspected_rows == 200 and "ilk 200/500 satır incelendi" in panel.summary()


def test_m13_t05_tolerans_yuvarlamayi_gecirir_maddi_farki_gecirmez() -> None:
    """Tolerans %0,5: gösterim yuvarlaması geçer, maddi fark geçmez (M13-T05 sınır örnekleri)."""
    pool = ["bakiye: 678970.0", "oran: 3.066321", "r=-0.5437"]
    assert grounding_check("q", "Bakiye 678.970 milyon TL.", pool) == "OK"
    assert grounding_check("q", "Aylık artış %3,07.", pool) == "OK", "iki ondalık yuvarlama geçer"
    assert grounding_check("q", "Korelasyon −0,54.", pool) == "OK", "iki ondalık yuvarlama geçer"
    assert grounding_check("q", "Bakiye 685.000 milyon TL.", pool).startswith("MISS"), "%0,89 fark maddi"
    assert grounding_check("q", "Aylık artış %3,2.", pool).startswith("MISS"), "3,066 → 3,2 yuvarlama değil"
    assert grounding_check("q", "Korelasyon −0,60.", pool).startswith("MISS"), "0,54 → 0,60 maddi"
