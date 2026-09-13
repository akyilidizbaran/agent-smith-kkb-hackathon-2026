"""M01 (ADR-0049): yollar repo köküne göre, demo modu sessiz düşmez, ön kontrol salt-okunur ve dürüst."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent import config  # noqa: E402
from kkb_agent.contracts.lakehouse import LakehouseError  # noqa: E402


def _settings(monkeypatch, **env):
    for k in ("DATA_ROOT", "LAKEHOUSE_PATH", "LAKEHOUSE_MODE", "LAKEHOUSE_CORE_DIR", "INGEST_ALLOWED_ROOT", "CHART_DIR"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    return config.load_settings()


def test_yollar_repo_kokune_gore_ve_data_root_altinda(monkeypatch, tmp_path) -> None:
    s = _settings(monkeypatch)
    assert s.data_root == config.REPO_ROOT / "data" and s.lakehouse_path == config.REPO_ROOT / "data" / "lakehouse.duckdb"
    assert s.ingest_allowed_root == config.REPO_ROOT / "data" / "incoming" and s.lakehouse_core_dir == config.REPO_ROOT / "lakehouse-core"
    assert s.lakehouse_mode == "demo"
    s2 = _settings(monkeypatch, LAKEHOUSE_PATH="data/lakehouse.duckdb")          # göreli → repo kökü, agent-core değil
    assert s2.lakehouse_path == config.REPO_ROOT / "data" / "lakehouse.duckdb"
    s3 = _settings(monkeypatch, DATA_ROOT=tmp_path, LAKEHOUSE_MODE="SEED")
    assert s3.lakehouse_path == tmp_path / "lakehouse.duckdb" and s3.chart_dir == tmp_path / "charts" and s3.lakehouse_mode == "seed"


def test_demo_modu_db_yoksa_ve_sema_seed_ise_acik_nedenle_durur(tmp_path) -> None:
    from kkb_agent.cli import open_lakehouse

    with pytest.raises(LakehouseError) as e:
        open_lakehouse(tmp_path / "yok.duckdb", mode="demo")
    assert "LAKEHOUSE_MODE=demo" in str(e.value) and "make demo-data" in str(e.value)
    seed = tmp_path / "seed.duckdb"
    duckdb.connect(str(seed)).execute("CREATE TABLE bddk_konut(donem DATE, deger DOUBLE)").close()
    with pytest.raises(LakehouseError) as e2:
        open_lakehouse(seed, mode="demo")
    assert "Silver şeması taşımıyor" in str(e2.value)
    with pytest.raises(LakehouseError):
        open_lakehouse(seed, mode="yanlış")


def test_on_kontrol_salt_okunur_ve_eksigi_soyler(monkeypatch, tmp_path) -> None:
    from kkb_agent.preflight import render, run_preflight

    s = _settings(monkeypatch, DATA_ROOT=tmp_path, LAKEHOUSE_CORE_DIR=tmp_path / "yok")
    checks = run_preflight(s)
    by = {c.name: c for c in checks}
    assert not by["veritabanı"].ok and "make demo-data" in by["veritabanı"].detail and by["veritabanı"].required
    assert not by["lakehouse-core"].ok and not by["izinli dosya kökü"].ok
    assert "HAZIR DEĞİL" in render(checks) and not (tmp_path / "lakehouse.duckdb").exists(), "ön kontrol dosya yaratmaz"
    assert all(v not in render(checks) for v in ("tvly-", "sk-")), "anahtar değeri asla yazılmaz"
    # Silver şemalı boş DB: şema geçer, veri düşer
    db = tmp_path / "lakehouse.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE SCHEMA meta; CREATE SCHEMA silver; CREATE TABLE meta.series(series_id VARCHAR); "
              "CREATE TABLE silver.fact_observation(series_id VARCHAR, observation_date DATE, value DOUBLE)")
    c.close()
    by2 = {c.name: c for c in run_preflight(s)}
    assert by2["şema"].ok and not by2["veri"].ok and by2["veritabanı"].ok
