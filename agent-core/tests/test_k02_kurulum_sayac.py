"""K02-T01 (A01) ve K01-T07 bulguları: uzak model anahtarı boşsa ön kontrol HAZIR demez; onaylanmış adhoc seri katalog sayacında."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent import config  # noqa: E402
from kkb_agent.preflight import run_preflight  # noqa: E402
from kkb_agent.web_app import Session  # noqa: E402


def _settings(monkeypatch, tmp_path, **env):
    for k in ("LAKEHOUSE_PATH", "LAKEHOUSE_MODE", "LAKEHOUSE_CORE_DIR", "INGEST_ALLOWED_ROOT", "CHART_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return config.load_settings()


def test_uzak_modelde_bos_anahtar_on_kontrolde_hata_yerelde_degil(monkeypatch, tmp_path) -> None:
    remote = _settings(monkeypatch, tmp_path, LLM_BASE_URL="https://mia.example/v1", LLM_API_KEY="", LLM_MODEL="m")
    assert remote.llm_key_missing
    model = {c.name: c for c in run_preflight(remote)}["model"]
    assert not model.ok and "LLM_API_KEY boş" in model.detail
    assert not _settings(monkeypatch, tmp_path, LLM_BASE_URL="https://mia.example/v1", LLM_API_KEY="anahtar", LLM_MODEL="m").llm_key_missing
    local = _settings(monkeypatch, tmp_path, LLM_BASE_URL="http://localhost:11434/v1", LLM_API_KEY="", LLM_MODEL="qwen")
    assert not local.llm_key_missing and {c.name: c for c in run_preflight(local)}["model"].ok


def _spec(sid: str, source: str, notes: list[str]) -> SimpleNamespace:
    return SimpleNamespace(dataset_id=sid, source=source, notes=notes)


def test_onaylanan_adhoc_seri_katalog_ve_yuklu_sayacinda_taslak_degil() -> None:
    lake = SimpleNamespace(
        list_datasets=lambda: [_spec("adhoc:web_ziyaret", "adhoc", ["Frekans indirgemede kural: avg."]),
                               _spec("adhoc:taslak", "adhoc", ["TASLAK seri: kullanıcının getirdiği veriden…"]),
                               _spec("gold.x", "gold", []), _spec("evds:a", "evds", [])],
        _uningested={"evds:b": "B"}, readiness=lambda: {},
    )

    class Registry:
        def get(self, name):
            return SimpleNamespace(lakehouse=lake) if name == "lakehouse_query" else None

        def names(self):
            return ["lakehouse_query"]

    agent = SimpleNamespace(registry=Registry(), llm=SimpleNamespace(model="m"))
    st = Session(lambda profile="analyst": agent).status()
    assert st["catalog_series"] == 3 and st["loaded_series"] == 2 and st["gold_tables"] == 1
