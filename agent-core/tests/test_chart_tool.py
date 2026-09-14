"""`chart` aracı: kural araçta, model yalnız ne çizileceğini söyler; denetçi geçmeden dosya yok."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.catalog import (  # noqa: E402
    ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency, SemanticType,
)
from kkb_agent.contracts.lakehouse import LakehouseError, QueryProvenance  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.chart import UNIT_UNKNOWN, ChartTool  # noqa: E402


class FakeLakehouse:
    def get_dataset(self, dataset_id: str) -> DatasetSpec:
        if dataset_id != "bddk_monthly:konut":
            raise LakehouseError("yok")
        return DatasetSpec(
            dataset_id=dataset_id, name="Konut Kredisi", description="d", source="bddk_monthly",
            frequency=Frequency.MONTHLY, time_column="observation_date", grain=["observation_date"],
            columns=[
                ColumnSpec(name="observation_date", role=ColumnRole.TIME, dtype="DATE", description="d"),
                ColumnSpec(name="value", role=ColumnRole.MEASURE, dtype="DOUBLE", description="v",
                           semantic_type=SemanticType.STOCK, unit="milyon TL", unit_multiplier=1e6),
            ],
            coverage=Coverage(start=date(2021, 1, 31), end=date(2026, 6, 30)),
        )


def _table(n: int = 12) -> pd.DataFrame:
    return pd.DataFrame({
        "observation_date": [date(2025, i + 1, 28) for i in range(n)],
        "bakiye": [500_000.0 + i * 10_000 for i in range(n)],
        "quality_flag": ["source_warning" if i == 2 else "ok" for i in range(n)],
    })


@pytest.fixture
def env(tmp_path: Path):
    ws = AnalysisWorkspace()
    prov = QueryProvenance(sql="SELECT ...", dataset_ids=["bddk_monthly:konut"],
                           sources=["bddk_monthly — Konut Kredisi"])
    ws.set_table(_table(), description="2025 aylık konut kredisi", provenance=prov)
    tool = ChartTool(FakeLakehouse(), ws, chart_dir=tmp_path / "charts", geo_dir=tmp_path / "geo")
    return tool, ws, tmp_path


def test_cizgi_grafik_kural_aracta_denetci_gecti_png_yazildi(env) -> None:
    tool, ws, tmp = env
    r = tool.validate_and_run({"chart_type": "line", "y_columns": ["bakiye"], "title": "Konut kredisi bakiyesi"})

    assert r.ok, r.content
    art = r.artifacts["chart"]
    assert art["lint_ok"] and Path(art["png_path"]).is_file() and Path(art["spec_path"]).is_file()
    spec = json.loads(Path(art["spec_path"]).read_text(encoding="utf-8"))
    # SQL'de yeniden adlandırılmış tek ölçüm: birim ve stok bilgisi katalogdan geldi
    assert spec["title"]["text"] == "Konut kredisi bakiyesi · milyon TL · 2025-01-28 → 2025-12-28"
    assert spec["layer"][0]["encoding"]["y"]["scale"] == {"zero": True}
    assert spec["title"]["subtitle"].startswith("Kaynak: bddk_monthly")
    assert "denetim: 6/6 kural geçti" in r.content.splitlines()[1]
    assert "png:" in r.content and "YAPACAĞIN" in r.content


def test_aktif_tablo_yoksa_workspace_katmaninda_durur(tmp_path: Path) -> None:
    tool = ChartTool(FakeLakehouse(), AnalysisWorkspace(), chart_dir=tmp_path)
    r = tool.validate_and_run({"chart_type": "line", "y_columns": ["x"], "title": "t"})
    assert not r.ok and r.error.error_code == "NO_ACTIVE_TABLE"


def test_olmayan_kolon_adaylarla_doner(env) -> None:
    tool, _, _ = env
    r = tool.validate_and_run({"chart_type": "line", "y_columns": ["deger"], "title": "t"})
    assert not r.ok and r.error.error_code == "COLUMN_NOT_FOUND" and "bakiye" in r.error.candidates


def test_cift_eksen_tek_kolonla_semada_durur(env) -> None:
    tool, _, _ = env
    r = tool.validate_and_run({"chart_type": "line", "y_columns": ["bakiye"], "title": "t", "dual_axis": True})
    assert not r.ok and r.error.error_code == "INVALID_ARGS"


def test_turetilmis_kolonun_birimi_bilinmiyorsa_acikca_yazilir(env) -> None:
    tool, ws, _ = env
    ws.add_column("degisim", ws.table["bakiye"].diff(), description="aylık fark",
                  provenance=QueryProvenance(sql="diff", dataset_ids=[], sources=[]))
    r = tool.validate_and_run({"chart_type": "bar", "y_columns": ["degisim"], "title": "Aylık değişim"})
    assert r.ok, r.content
    spec = json.loads(Path(r.artifacts["chart"]["spec_path"]).read_text(encoding="utf-8"))
    assert UNIT_UNKNOWN in spec["title"]["text"] and spec["layer"][0]["mark"]["type"] == "bar"


def test_harita_sinir_dosyasi_yoksa_politikada_durur(env) -> None:
    tool, ws, _ = env
    ws.set_table(pd.DataFrame({"il": ["Ankara"], "bakiye": [1.0]}), description="il")
    r = tool.validate_and_run({"chart_type": "map", "y_columns": ["bakiye"], "province_column": "il", "title": "İl haritası"})
    assert not r.ok and r.error.error_code == "TOOL_FAILED" and r.error.layer == "policy"
    assert "tr_provinces.geojson" in r.content and "çubuk" in r.content


def test_harita_sentetik_sinirlarla_cizilir(env) -> None:
    tool, ws, tmp = env
    geo = tmp / "geo"; geo.mkdir()
    def sq(x, y, name):
        return {"type": "Feature", "properties": {"name": name},
                "geometry": {"type": "Polygon", "coordinates": [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]]}}
    (geo / "tr_provinces.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [sq(32, 39, "Ankara"), sq(28, 41, "İstanbul")]}), encoding="utf-8")
    ws.set_table(pd.DataFrame({"il": ["ANKARA", "İstanbul"], "bakiye": [3.0, 9.0]}), description="2025-09 il bazında",
                 provenance=QueryProvenance(sql="s", dataset_ids=["bddk_monthly:konut"], sources=["bddk_finturk"]))
    ws.title = "2025-09 il bazında konut kredisi"

    r = tool.validate_and_run({"chart_type": "map", "y_columns": ["bakiye"], "province_column": "il", "title": "İl bazında konut kredisi"})

    assert r.ok, r.content
    art = r.artifacts["chart"]
    assert art["kind"] == "map" and Path(art["png_path"]).is_file()
    assert "2 il eşleşti" in r.content


def test_denetci_gecmezse_dosya_yazilmaz(env, monkeypatch) -> None:
    tool, _, tmp = env
    import kkb_agent.tools.chart as mod
    real = mod.build_spec
    def broken(frame, intent):
        spec = real(frame, intent)
        spec["layer"][0]["encoding"]["y"]["scale"] = {"zero": False}   # inşacı hatası taklidi
        return spec
    monkeypatch.setattr(mod, "build_spec", broken)
    r = tool.validate_and_run({"chart_type": "line", "y_columns": ["bakiye"], "title": "t"})
    assert not r.ok and r.error.error_code == "TOOL_FAILED" and not r.error.is_retryable
    assert "level_zero" in r.content
    assert not list((tmp / "charts").glob("*.png"))


def test_gold_join_kolonlari_onekten_birim_ve_etiket_alir(env) -> None:
    """Gold join çerçevesinde kolon '<seri>@<varlık>::value'; önek seri kimliğidir, birim oradan gelir."""
    tool, ws, _ = env
    prov = QueryProvenance(sql="gold-run join_on_period(...)", dataset_ids=["bddk_monthly:konut", "evds:TP.KTF12"], sources=["gold — join"])
    ws.set_table(pd.DataFrame({
        "period_start": [date(2025, 1, 1), date(2025, 2, 1)],
        "period_end": [date(2025, 1, 31), date(2025, 2, 28)],
        "bddk_monthly:konut@bddk:10001::value": [100.0, 110.0],
        "evds:TP.KTF12::value": [40.0, 39.5],
    }), description="join", provenance=prov)
    r = tool.validate_and_run({"chart_type": "line", "y_columns": ["bddk_monthly:konut@bddk:10001::value", "evds:TP.KTF12::value"],
                               "title": "Bakiye ve faiz", "dual_axis": True})
    assert r.ok, r.content
    spec = json.loads(Path(r.artifacts["chart"]["spec_path"]).read_text(encoding="utf-8"))
    assert spec["layer"][0]["encoding"]["x"]["field"] == "period_end"          # period_start değil
    assert "Konut Kredisi (milyon TL)" in spec["layer"][0]["encoding"]["y"]["title"]  # katalog adı + birim
    assert UNIT_UNKNOWN in spec["layer"][1]["encoding"]["y"]["title"]              # KTF12 sahte katalogda yok
    assert spec["layer"][0]["encoding"]["x"]["timeUnit"] == "yearmonth"


def test_farkli_birimli_iki_seri_ilk_donem_100e_cevrilir_cift_eksen_acilmaz(env) -> None:
    """M16 kabul bulgusu: 'karşılaştırmalı grafik' L9'a takılıyordu; harness endeksler, model iş yapmaz."""
    tool, ws, _ = env
    prov = QueryProvenance(sql="gold-run join_on_period(...)", dataset_ids=["bddk_monthly:konut", "evds:TP.KTF12"], sources=["gold — join"])
    ws.set_table(pd.DataFrame({
        "period_end": [date(2025, 2, 28), date(2025, 1, 31)],
        "bddk_monthly:konut@bddk:10001::value": [110.0, 100.0],
        "evds:TP.KTF12::value": [39.5, 40.0],
    }), description="join", provenance=prov)
    r = tool.validate_and_run({"chart_type": "line", "y_columns": ["bddk_monthly:konut@bddk:10001::value", "evds:TP.KTF12::value"],
                               "title": "Bakiye ve faiz"})
    assert r.ok, r.content
    art = r.artifacts["chart"]
    assert art["lint_ok"] and art["rebased_to_100"]
    assert "ilk döneminde 100" in r.content and "98.75" in r.content and "110.0" in r.content
    spec = json.loads(Path(art["spec_path"]).read_text(encoding="utf-8"))
    assert "layer" not in spec or all("y" not in (l.get("resolve") or {}) for l in spec.get("layer", []))
    assert "100" in json.dumps(spec, ensure_ascii=False)


def test_ilk_degeri_sifir_olan_seride_endeksleme_yapilmaz(env) -> None:
    tool, ws, _ = env
    prov = QueryProvenance(sql="gold-run", dataset_ids=["bddk_monthly:konut"], sources=["gold"])
    ws.set_table(pd.DataFrame({
        "period_end": [date(2025, 1, 31), date(2025, 2, 28)],
        "bddk_monthly:konut@bddk:10001::value": [100.0, 110.0],
        "evds:TP.KTF12::value": [0.0, 39.5],
    }), description="join", provenance=prov)
    r = tool.validate_and_run({"chart_type": "line", "y_columns": ["bddk_monthly:konut@bddk:10001::value", "evds:TP.KTF12::value"], "title": "t"})
    assert not r.ok and "dual_axis=true" in (r.error.hint or "")
