"""M03-T04 (ADR-0060): kaynak adları çekirdek kodda değil yapılandırmada; boş yapılandırmada motor çalışır."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent import source_hints  # noqa: E402
from kkb_agent.core import access_policy, facets  # noqa: E402

CORE = Path(__file__).resolve().parents[1] / "src" / "kkb_agent" / "core"


def test_cekirdek_kodda_kaynak_adi_ve_hostu_yok() -> None:
    for name in ("facets.py", "access_policy.py", "small_talk.py", "tool_gate.py", "agent.py", "grounding.py", "evidence.py"):
        code = "\n".join(l for l in (CORE / name).read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))
        for token in ("bddk_finturk", "bddk_monthly", "evds3.tcmb", "evds2.tcmb", '"BDDK"', '"TCMB"'):
            assert token not in code, f"{name}: {token}"


def test_varsayilan_ipuclari_calisir(monkeypatch) -> None:
    monkeypatch.delenv("SOURCE_HINTS_FILE", raising=False)
    source_hints.clear_cache()
    assert "evds" in facets.extract_facets("EVDS'deki faiz").sources
    assert access_policy.credential_env_name("https://evds3.tcmb.gov.tr/x") == "EVDS_API_KEY"
    assert access_policy.detect_source_constraint("BDDK'dan getir").pinned


def test_bos_yapilandirmada_motor_calisir_ipucu_olmaz(tmp_path, monkeypatch) -> None:
    empty = tmp_path / "hints.json"
    empty.write_text(json.dumps({"source_words": {}, "credential_env_by_host": {}, "institutions": []}), encoding="utf-8")
    monkeypatch.setenv("SOURCE_HINTS_FILE", str(empty))
    source_hints.clear_cache()
    try:
        f = facets.extract_facets("Ankara'da aylık EVDS verisi")
        assert f.sources == () and f.provinces == ("Ankara",) and f.frequency == "monthly"
        assert access_policy.credential_env_name("https://evds3.tcmb.gov.tr/x") == "KKB_CREDENTIAL_EVDS3_TCMB_GOV_TR", "genel ad kuralına düşer"
        assert not access_policy.detect_source_constraint("BDDK'dan getir").pinned
        assert access_policy.detect_source_constraint("https://x.org/veri.csv adresinden getir").pinned, "URL sabitleme alandan bağımsız"
    finally:
        monkeypatch.delenv("SOURCE_HINTS_FILE", raising=False)
        source_hints.clear_cache()
