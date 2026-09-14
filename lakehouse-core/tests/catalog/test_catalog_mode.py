"""D04 (ADR-0067): empty-catalog mode survives every later bootstrap; the default catalog is an explicit choice."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb

from src.lakehouse.application import run_bootstrap, run_gold_build, run_promote_draft, run_silver_build
from src.lakehouse.db.bootstrap import bootstrap_database, read_catalog_mode

ROOT = Path(__file__).resolve().parents[2]


def _series_count(db: Path) -> int:
    with duckdb.connect(str(db), read_only=True) as con:
        return int(con.execute("SELECT count(*) FROM meta.series").fetchone()[0])


def test_schema_only_mode_is_stored_and_honoured_by_every_later_command(tmp_path: Path) -> None:
    db = tmp_path / "data" / "lakehouse.duckdb"
    db.parent.mkdir(parents=True)
    summary = run_bootstrap(db, catalog_mode="none")
    assert summary.catalog_mode == "none" and summary.catalog_series_count == 0
    with duckdb.connect(str(db), read_only=True) as con:   # ajanın açabilmesi için boş Silver ilişkisi var (K01 bulgusu)
        assert con.execute("SELECT count(*) FROM silver.fact_observation").fetchone()[0] == 0
    # every command that bootstraps first must keep the catalog empty
    run_silver_build(database=db, data_root=tmp_path / "data")
    assert _series_count(db) == 0
    run_gold_build(database=db)
    assert _series_count(db) == 0
    try:
        run_promote_draft(database=db, series_id="adhoc:yok")
    except Exception:  # noqa: BLE001 — no such draft; the point is the bootstrap side effect
        pass
    assert _series_count(db) == 0
    again = run_bootstrap(db)                               # no flag: stored mode wins after "restart"
    assert again.catalog_mode == "none" and again.catalog_series_count == 0
    connection = bootstrap_database(db)                     # plain library call, e.g. an ingest composition
    try:
        assert read_catalog_mode(connection) == "none"
        assert connection.execute("SELECT count(*) FROM meta.series").fetchone()[0] == 0
    finally:
        connection.close()


def test_default_catalog_is_an_explicit_choice_and_legacy_databases_stay_default(tmp_path: Path) -> None:
    empty = tmp_path / "empty.duckdb"
    run_bootstrap(empty, catalog_mode="none")
    restored = run_bootstrap(empty, catalog_mode="default")
    assert restored.catalog_mode == "default" and restored.catalog_series_count > 0
    legacy = tmp_path / "legacy.duckdb"
    first = run_bootstrap(legacy)
    assert first.catalog_mode == "default" and first.catalog_series_count > 0


def test_cli_bootstrap_catalog_flag(tmp_path: Path) -> None:
    db = tmp_path / "cli.duckdb"
    command = [sys.executable, "-m", "lakehouse", "bootstrap", "--database", str(db), "--data-root", str(tmp_path)]
    empty = subprocess.run([*command, "--catalog", "none"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert empty.returncode == 0, empty.stderr
    assert "catalog_mode: none" in empty.stdout and "catalog_series_count: 0" in empty.stdout
    kept = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert kept.returncode == 0 and "catalog_mode: none" in kept.stdout and "catalog_series_count: 0" in kept.stdout
    bad = subprocess.run([*command, "--catalog", "finans"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert bad.returncode != 0 and "invalid choice" in bad.stderr and "Traceback" not in bad.stderr
