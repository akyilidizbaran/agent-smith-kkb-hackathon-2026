"""D06 (ADR-0070): kanıt zinciri gerçek dosya durumuyla eşleşir — RAW yok/Bronze var, RAW var/Bronze yok, ikisi yok,
bozuk RAW özeti, sonradan silinmiş dosya ve eksiksiz zincir. Sayısal doğruluk ve sorgu izi rozetleri bundan etkilenmez."""

from __future__ import annotations

import hashlib
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.contracts.evidence import (  # noqa: E402
    CHAIN_BRONZE_MISSING, CHAIN_DIGEST_MISMATCH, CHAIN_FULL, CHAIN_NO_FILES, CHAIN_RAW_MISSING, EvidencePanel,
    NumberEvidence, ObservationEvidence,
)
from kkb_agent.core.evidence import EvidenceBuilder  # noqa: E402
from kkb_agent.web_app import evidence_to_dict  # noqa: E402
from tests.test_evidence import _workspace, lake  # noqa: E402,F401


def _obs(tmp: Path, *, raw: bool, bronze: bool, digest: bool | None) -> ObservationEvidence:
    raw_path, bronze_path = tmp / "raw.json", tmp / "b.parquet"
    if raw:
        raw_path.write_bytes(b"{}")
    if bronze:
        bronze_path.write_bytes(b"PAR1")
    return ObservationEvidence(series_id="s", entity_id=None, observation_date=date(2025, 1, 31), value=1.0, quality_flag="ok",
                               artifact_sha256=hashlib.sha256(b"{}").hexdigest(), vintage_id=None, run_id=None,
                               fetched_at=datetime(2026, 9, 14), locator="https://kaynak/x", http_status=200,
                               raw_path=str(raw_path), bronze_path=str(bronze_path), raw_digest_ok=digest, checked_at=datetime(2026, 9, 14))


def _panel(*obs: ObservationEvidence) -> EvidencePanel:
    return EvidencePanel(question="q", numbers=[NumberEvidence(number=1.0, text="1", matched=True)], columns=[],
                         observations=list(obs), supports_artifacts=True)


def test_alti_vaka_dogru_durum(tmp_path: Path) -> None:
    cases = {
        "tam": (dict(raw=True, bronze=True, digest=True), CHAIN_FULL),
        "raw_yok_bronze_var": (dict(raw=False, bronze=True, digest=None), CHAIN_RAW_MISSING),
        "raw_var_bronze_yok": (dict(raw=True, bronze=False, digest=True), CHAIN_BRONZE_MISSING),
        "ikisi_yok": (dict(raw=False, bronze=False, digest=None), CHAIN_NO_FILES),
        "bozuk_ozet": (dict(raw=True, bronze=True, digest=False), CHAIN_DIGEST_MISMATCH),
    }
    for name, (kw, expected) in cases.items():
        d = tmp_path / name
        d.mkdir()
        o = _obs(d, **kw)
        assert o.chain_state == expected, name
        assert _panel(o).chain_ok is (expected == CHAIN_FULL), name
        assert _panel(o).claims_ok and _panel(o).provenance_ok, "sayı ve sorgu izi rozetleri etkilenmez"


def test_sonradan_silinen_dosya_ayni_nesnede_yesil_kalmaz(tmp_path: Path) -> None:
    o = _obs(tmp_path, raw=True, bronze=True, digest=True)
    panel = _panel(o)
    assert panel.chain_ok
    Path(o.bronze_path).unlink()
    assert not panel.chain_ok and o.chain_state == CHAIN_BRONZE_MISSING, "R06: Bronze silinince zincir tam değil"
    Path(o.raw_path).unlink()
    assert o.chain_state == CHAIN_NO_FILES and panel.chain_breakdown() == {CHAIN_NO_FILES: 1}
    assert "dosya halkaları: 1 RAW ve Bronze dosyası yok" in panel.summary()


def test_ham_kaynak_eksikligi_boslukta_ui_yukunde_ve_rapor_metninde(lake, tmp_path: Path) -> None:
    ws = _workspace(lake)
    raw = tmp_path / "data" / "raw" / "bddk_monthly" / "a.json"
    raw.unlink()                                               # RAW yok, Bronze var (R06 deneyi)
    panel = EvidenceBuilder(lake).build("soru", "Ocak 100, Şubat 110 milyon TL.", ws, [])
    assert not panel.chain_ok and panel.claims_ok, "doğru sayılar gereksizce yanlış sayılmaz"
    assert any("dosya halkası eksik: ham kaynak (RAW) eksik, işlenmiş veri (Bronze) var" in g for g in panel.gaps)
    payload = evidence_to_dict(panel)
    assert payload["states"]["dosya zinciri"] is False and payload["chain_breakdown"]
    assert any(o.get("chain_state") == CHAIN_RAW_MISSING for o in payload["observations"])
    assert "(YOK)" in panel.render()
