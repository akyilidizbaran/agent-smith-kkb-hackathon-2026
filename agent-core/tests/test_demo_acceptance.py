"""Demo kabul betiği: komut planı deterministik, senaryo kimlikleri golden'da var (D4)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scripts.demo_acceptance import DEMO_SERIES, SCENARIO_CASES, build_commands  # noqa: E402
from tests.golden.cases import CASES  # noqa: E402


def test_komut_plani_sirali_ve_yollari_tasir(tmp_path: Path) -> None:
    plan = build_commands(tmp_path, Path("/core"), launcher="uv run python")
    names = [n for n, _ in plan]
    assert names[0] == "bootstrap" and names[-1] == "gold" and "silver" in names
    ingest = dict(plan)["ingest (canlı: BDDK + EVDS)"]
    assert "--only" in ingest and ",".join(DEMO_SERIES) in ingest
    for _, cmd in plan:
        assert cmd[:3] == ["uv", "run", "python"] and str(tmp_path / "data" / "lakehouse.duckdb") in cmd


def test_senaryo_kimlikleri_golden_da_var() -> None:
    ids = {c.id for c in CASES}
    assert set(SCENARIO_CASES) <= ids
    assert len(SCENARIO_CASES) == 11
