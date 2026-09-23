"""`gold_align / gold_decompose / gold_join` — kural katalogdan, red görünür, CLI sahte.

Ölçülen garantiler: başarılı çağrı hesaplanmış tabloyu workspace'e koyar (value sayısal,
tarih kolonu tarih); red `GOLD_REFUSED` ile döner, tekrar denenmez ve Türkçe sebep taşır;
olmayan seri CLI hiç çağrılmadan referansta durur; dönem filtresi deterministik, dönem
dışıysa tablo kurulmaz; join kolonları önekli gelir.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.adapters.gold_cli import GoldCLI, document_to_frame  # noqa: E402
from kkb_agent.adapters.silver_lakehouse import SilverLakehouse  # noqa: E402
from kkb_agent.contracts.lakehouse import GoldCapable, GoldRefused  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.gold import (  # noqa: E402
    GoldAlignTool, GoldDecomposeTool, GoldJoinTool, parse_period, workspace_view,
)
from tests.test_silver_lakehouse import DDL, _obs, _series  # noqa: E402

ALIGNED_COLUMNS = [
    "series_id", "entity_id", "period_start", "period_end", "value", "quality_flag",
    "measure_type", "unit", "aggregation", "source_frequency", "target_frequency",
    "observations", "missing_observations", "warned_observations",
    "source_observation_dates", "artifact_sha256_list", "vintage_id_list", "run_id_list",
]


def _aligned_row(period_start: str, period_end: str, value, flag="ok"):
    return ["bddk_monthly:konut", None, period_start, period_end, value, flag, "stock", "TRY_mn",
            "last", "monthly", "quarterly", 3, 0, 0, [period_end], ["ab" * 32], ["v1"], ["r1"]]


ALIGN_DOC = {
    "gold_document_version": "1.0", "function": "align_frequency",
    "arguments": {"series_ids": ["bddk_monthly:konut"], "target_frequency": "quarterly"},
    "columns": ALIGNED_COLUMNS,
    "rows": [
        _aligned_row("2024-10-01", "2024-12-31", 90.0),
        _aligned_row("2025-01-01", "2025-03-31", 100.0),
        _aligned_row("2025-04-01", "2025-06-30", 110.0),
        _aligned_row("2025-07-01", "2025-09-30", None, "missing_value"),
        _aligned_row("2025-10-01", "2025-12-31", 121.0),
    ],
}


class FakeGoldRunner:
    """`gold-run` yerine geçer: `--out` dosyasına belgeyi yazar ya da red basar."""

    def __init__(self, document=None, *, refusal: tuple[str, str] | None = None, fail: str | None = None):
        self.document, self.refusal, self.fail = document, refusal, fail
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], cwd: Path) -> tuple[int, str, str]:
        self.calls.append(cmd)
        if self.refusal:
            reason, message = self.refusal
            return 3, f"status: refused\nreason: {reason}\nseries_id: bddk_monthly:konut\nmessage: {message}\n", ""
        if self.fail:
            return 2, "status: failed", f"error: {self.fail}"
        out = Path(cmd[cmd.index("--out") + 1])
        out.write_text(json.dumps(self.document), encoding="utf-8")
        return 0, f"status: success\nrows: {len(self.document['rows'])}\n", ""


@pytest.fixture
def env(tmp_path: Path):
    import duckdb
    db = tmp_path / "lh.duckdb"
    con = duckdb.connect(str(db)); con.execute(DDL)
    _series(con, "bddk_monthly:konut", aliases=["konut kredisi"], name_tr="Konut Kredisi")
    _series(con, "evds:TP.KTF12", unit="pct", measure_type="rate", default_agg="avg",
            frequency="weekly", week_anchor="friday", aliases=["konut kredisi faizi"], name_tr="Konut Faizi")
    _series(con, "evds:TP.CEKILMEDI", aliases=["taşıt kredisi"], name_tr="Taşıt (henüz çekilmedi)")
    for i, v in enumerate([100.0, 110.0, 121.0], start=1):
        _obs(con, "bddk_monthly:konut", date(2025, i, 28), v)
        _obs(con, "evds:TP.KTF12", date(2025, i, 28), 40.0 + i, unit="pct", mt="rate")
    con.close()
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")
    runner = FakeGoldRunner(ALIGN_DOC)
    gold = GoldCLI(core_dir=tmp_path / "lakehouse-core", database=db, runner=runner, scratch_dir=tmp_path / "scratch")
    lake = SilverLakehouse(db, gold=gold)
    ws = AnalysisWorkspace()
    return lake, ws, runner


def test_adaptor_gold_sozlesmesini_karsilar(env) -> None:
    lake, _, _ = env
    assert isinstance(lake, GoldCapable)
    assert lake.health()["gold_run_available"] is True


def test_align_kurali_katalogdan_tabloyu_workspace_e_koyar(env) -> None:
    lake, ws, runner = env
    tool = GoldAlignTool(lake, ws)

    r = tool.validate_and_run({"series_id": "bddk_monthly:konut", "target_frequency": "quarterly",
                               "purpose": "2025 çeyreklik konut kredisi", "period_from": "2025", "period_to": "2025"})

    assert r.ok, r.content
    cmd = runner.calls[0]
    assert cmd[:3] == ["uv", "run", "python"] and "gold-run" in cmd
    flags = dict(zip(cmd, cmd[1:]))
    assert flags["--function"] == "align_frequency" and flags["--series"] == "bddk_monthly:konut"
    assert flags["--target"] == "quarterly" and "--allow-unverified-semantics" not in cmd
    table = ws.table
    assert table is not None and len(table) == 4  # 2024 Q4 filtrelendi
    assert str(table["value"].dtype) == "float64" and table["value"].isna().sum() == 1
    assert all(hasattr(v, "year") for v in table["period_end"])
    assert "vintage_id_list" not in table.columns and "artifact_sha256_list" in table.columns
    assert "entity_id" not in table.columns  # tümü NULL → düşer
    assert "5 dönem hesaplandı" in r.content and "4 satır" in r.content
    assert "stock → last" in r.content and "TRY_mn" in r.content
    assert "missing_value×1" in " ".join(r.provenance.warnings)
    assert r.provenance.sql.startswith("gold-run align_frequency(")
    assert "gold — align_frequency" in r.provenance.sources


def test_red_gold_refused_tekrar_denenmez_ve_turkce_sebep_tasir(env) -> None:
    lake, ws, runner = env
    runner.refusal = ("NOT_DECOMPOSABLE", "measure_type 'stock' does not accumulate")
    tool = GoldDecomposeTool(lake, ws)

    r = tool.validate_and_run({"series_id": "bddk_monthly:konut", "purpose": "akıma çöz"})

    assert not r.ok and r.error.error_code == "GOLD_REFUSED" and r.error.layer == "policy"
    assert not r.error.is_retryable
    assert "NOT_DECOMPOSABLE" in r.content and "birikimli değil" in r.content
    assert "gold_align" in r.content  # alternatif öneri
    # ADR-0104: ret uygulanabilir bir alternatif gösteriyorsa tur bitmez; aynı çağrı yine tekrar denenmez.
    assert r.error.terminal is False and "TEKRAR DENEMEYLE ÇÖZÜLMEZ" not in r.content and "Tur devam ediyor" in r.content
    assert ws.table is None


def test_onay_gerektiren_gold_reddi_turu_kapatir(env) -> None:
    lake, ws, runner = env
    runner.refusal = ("UNVERIFIED_SEMANTICS", "semantics not verified")
    r = GoldDecomposeTool(lake, ws).validate_and_run({"series_id": "bddk_monthly:konut", "purpose": "akıma çöz"})
    assert not r.ok and r.error.terminal is not False and "TEKRAR DENEMEYLE ÇÖZÜLMEZ" in r.content


def test_adaptor_reddi_typed_exception_olarak_yukseltir(env) -> None:
    lake, _, runner = env
    runner.refusal = ("UNVERIFIED_SEMANTICS", "semantic_confidence is 'derived'")
    with pytest.raises(GoldRefused) as exc:
        lake.gold_align("bddk_monthly:konut", "monthly")
    assert exc.value.reason == "UNVERIFIED_SEMANTICS" and exc.value.series_id == "bddk_monthly:konut"


def test_olmayan_seri_cli_cagrilmadan_referansta_durur(env) -> None:
    lake, ws, runner = env
    r = GoldAlignTool(lake, ws).validate_and_run(
        {"series_id": "bddk_monthly:yok", "target_frequency": "monthly", "purpose": "x"})
    assert not r.ok and r.error.error_code == "DATASET_NOT_FOUND"
    assert runner.calls == []


def test_yuklenmemis_seri_ayri_sebeple_durur(env) -> None:
    lake, ws, runner = env
    r = GoldAlignTool(lake, ws).validate_and_run(
        {"series_id": "evds:TP.CEKILMEDI", "target_frequency": "monthly", "purpose": "x"})
    assert not r.ok and "henüz hiç gözlem yüklenmemiş" in r.content and runner.calls == []


def test_gold_tablosu_kimligi_seri_degil(env) -> None:
    lake, ws, runner = env
    r = GoldAlignTool(lake, ws).validate_and_run(
        {"series_id": "gold.konut_kredisi_ceyreklik", "target_frequency": "monthly", "purpose": "x"})
    assert not r.ok and r.error.error_code == "DATASET_NOT_FOUND"
    assert "lakehouse_query" in r.content and runner.calls == []


def test_donem_disi_filtrede_tablo_kurulmaz_kapsam_soylenir(env) -> None:
    lake, ws, _ = env
    r = GoldAlignTool(lake, ws).validate_and_run(
        {"series_id": "bddk_monthly:konut", "target_frequency": "quarterly", "purpose": "x",
         "period_from": "2019", "period_to": "2019"})
    assert r.ok and r.content.startswith("SONUÇ") and "2024-12-31 → 2025-12-31" in r.content
    assert ws.table is None


def test_bozuk_donem_bicimi_semada_durur(env) -> None:
    lake, ws, runner = env
    r = GoldAlignTool(lake, ws).validate_and_run(
        {"series_id": "bddk_monthly:konut", "target_frequency": "quarterly", "purpose": "x", "period_from": "dün"})
    assert not r.ok and r.error.error_code == "INVALID_ARGS" and runner.calls == []


def test_join_prefixli_kolonlar_ve_eksik_donem_uyarisi(env) -> None:
    lake, ws, runner = env
    a, b = "bddk_monthly:konut", "evds:TP.KTF12"
    cols = ["period_start", "period_end"]
    for k in (a, b):
        cols += [f"{k}::series_id", f"{k}::value", f"{k}::quality_flag", f"{k}::measure_type", f"{k}::unit",
                 f"{k}::aggregation", f"{k}::observations", f"{k}::missing_observations",
                 f"{k}::warned_observations", f"{k}::source_observation_dates",
                 f"{k}::artifact_sha256_list", f"{k}::vintage_id_list", f"{k}::run_id_list"]
    cols += ["contributing_series", "absent_series", "is_complete_period"]

    def row(ps, pe, va, vb, complete):
        r = [ps, pe]
        for k, v, mt, unit, agg in ((a, va, "stock", "TRY_mn", "last"), (b, vb, "rate", "pct", "avg")):
            r += [k, v, "ok" if v is not None else None, mt, unit, agg, 1 if v is not None else 0, 0, 0,
                  [pe] if v is not None else [], ["ab" * 32] if v is not None else [], [], []]
        r += [[a, b] if complete else [a], [] if complete else [b], complete]
        return r

    runner.document = {"gold_document_version": "1.0", "function": "join_on_period", "arguments": {},
                       "columns": cols, "rows": [row("2025-01-01", "2025-01-31", 100.0, 41.0, True),
                                                 row("2025-02-01", "2025-02-28", 110.0, None, False)]}

    r = GoldJoinTool(lake, ws).validate_and_run(
        {"series_ids": [a, b], "target_frequency": "monthly", "purpose": "faiz ve bakiye yan yana"})

    assert r.ok, r.content
    cmd = runner.calls[0]
    assert cmd.count("--series") == 2 and "join_on_period" in cmd
    t = ws.table
    assert len(t) == 2 and f"{a}::value" in t.columns and f"{b}::value" in t.columns
    assert f"{b}::series_id" not in t.columns and "is_complete_period" in t.columns
    assert str(t[f"{b}::value"].dtype) == "float64"
    assert "1 dönemde en az bir seri yayımlamamış" in " ".join(r.provenance.warnings)
    assert f"{a}: stock → last" in r.content and f"{b}: rate → avg" in r.content


def test_gold_ambiguous_anchor_donemini_ust_pencereye_tasiyor(env) -> None:
    """60 aylık istek anchor yılları Gold filtresiyle 24 aya daraltılamaz."""
    lake, ws, runner = env
    monthly_columns = [
        "series_id", "entity_id", "period_start", "period_end", "value", "quality_flag",
        "measure_type", "unit", "aggregation", "source_frequency", "target_frequency",
        "observations", "missing_observations", "warned_observations",
        "source_observation_dates", "artifact_sha256_list", "vintage_id_list", "run_id_list",
    ]
    rows = []
    for i, period in enumerate(pd.date_range("2021-04-30", periods=60, freq="ME")):
        start = period.replace(day=1).date().isoformat()
        rows.append([
            "bddk_monthly:konut", None, start, period.date().isoformat(), float(i), "ok",
            "stock", "TRY_mn", "last", "monthly", "monthly", 1, 0, 0,
            [period.date().isoformat()], ["ab" * 32], ["v1"], ["r1"],
        ])
    runner.document = {
        "gold_document_version": "1.0", "function": "align_frequency",
        "arguments": {}, "columns": monthly_columns, "rows": rows,
    }

    class ResolvedRegistry:
        active_question = (
            "Anchor yıllarını içeren 60 aylık sentetik rapor penceresindeki verileri getir. "
            "[Otomatik dönem sınırı: 2021-04 ile 2026-03 arasındaki 60 aylık pencereyi kullan]"
        )

    tool = GoldAlignTool(lake, ws, registry=ResolvedRegistry())
    result = tool.validate_and_run({
        "series_id": "bddk_monthly:konut", "target_frequency": "monthly",
        "purpose": "60 aylık sonuç", "period_from": "2022-01", "period_to": "2023-12",
    })

    assert result.ok, result.content
    assert ws.table is not None and len(ws.table) == 60
    assert ws.table["period_end"].min() == date(2021, 4, 30)
    assert ws.table["period_end"].max() == date(2026, 3, 31)


def test_decompose_basarili_flagleri_ozetler(env) -> None:
    lake, ws, runner = env
    cols = ["series_id", "entity_id", "period_start", "period_end", "value", "decomposition_flag",
            "quality_flag", "cumulative_value", "previous_cumulative_value", "previous_observation_date",
            "raw_change", "measure_type", "unit", "source_frequency", "source_observation_dates",
            "artifact_sha256_list", "vintage_id_list", "run_id_list", "contributor_count"]
    rows = [["s", None, "2025-01-01", "2025-01-31", 10.0, "ok", "ok", 10.0, None, None, None, "flow_ytd", "TRY_mn", "monthly", ["2025-01-31"], ["x"], [], [], 1],
            ["s", None, "2025-02-01", "2025-02-28", 5.0, "ok", "ok", 15.0, 10.0, "2025-01-31", 5.0, "flow_ytd", "TRY_mn", "monthly", ["2025-01-31", "2025-02-28"], ["x"], [], [], 2],
            ["s", None, "2025-04-01", "2025-04-30", None, "spans_multiple_periods", "ok", 30.0, 15.0, "2025-02-28", 15.0, "flow_ytd", "TRY_mn", "monthly", ["2025-02-28", "2025-04-30"], ["x"], [], [], 2]]
    runner.document = {"gold_document_version": "1.0", "function": "decompose_cumulative", "arguments": {},
                       "columns": cols, "rows": rows}

    r = GoldDecomposeTool(lake, ws).validate_and_run({"series_id": "bddk_monthly:konut", "purpose": "akım"})

    assert r.ok, r.content
    assert "spans_multiple_periods×1" in r.content and "ok×2" in r.content
    assert ws.table["value"].isna().sum() == 1 and "cumulative_value" in ws.table.columns
    assert "spans_multiple_periods×1" in " ".join(r.provenance.warnings)


def test_cli_hatasi_tool_failed_olarak_doner(env) -> None:
    lake, ws, runner = env
    runner.fail = "database is locked"
    r = GoldAlignTool(lake, ws).validate_and_run(
        {"series_id": "bddk_monthly:konut", "target_frequency": "monthly", "purpose": "x"})
    assert not r.ok and r.error.error_code == "TOOL_FAILED" and "database is locked" in r.content


def test_gold_cli_gecici_dosyayi_temizler(env, tmp_path: Path) -> None:
    lake, ws, runner = env
    GoldAlignTool(lake, ws).validate_and_run(
        {"series_id": "bddk_monthly:konut", "target_frequency": "quarterly", "purpose": "x"})
    assert list((tmp_path / "scratch").glob("gold_run_*.json")) == []


def test_document_to_frame_tipleri_taban_addan_kazanir() -> None:
    frame = document_to_frame(ALIGN_DOC)
    assert str(frame["value"].dtype) == "float64"
    assert frame["period_end"].iloc[0] == date(2024, 12, 31)
    assert frame["source_observation_dates"].iloc[0] == [date(2024, 12, 31)]
    assert str(frame["observations"].dtype) == "Int64"


def test_parse_period_ve_workspace_view() -> None:
    assert parse_period("2025", end=False) == date(2025, 1, 1)
    assert parse_period("2025", end=True) == date(2025, 12, 31)
    assert parse_period("2025-02", end=True) == date(2025, 2, 28)
    assert parse_period("2025-02-03", end=True) == date(2025, 2, 3)
    assert parse_period("", end=True) is None
    with pytest.raises(ValueError):
        parse_period("Q1", end=False)
    view = workspace_view(document_to_frame(ALIGN_DOC))
    assert "run_id_list" not in view.columns and "source_observation_dates" in view.columns


def test_workspace_view_json_tarihlerini_gercek_tarih_tipine_dondurur() -> None:
    frame = pd.DataFrame({
        "period_start": ["2024-01-01", "2024-02-01"],
        "period_end": ["2024-01-31", "2024-02-29"],
        "value": [10.0, 12.0],
    })
    view = workspace_view(frame)
    assert view["period_end"].iloc[0] == date(2024, 1, 31)
    assert all(isinstance(value, date) for value in view["period_end"])


def test_seri_kimligi_tablo_adi_olarak_kullanilmaz(env) -> None:
    """23 Eyl demo, ADIM 4: `evds:TP.KTF12` / `TP.KTF12` FROM'a yazılınca DuckDB 'Catalog "TP" does not exist' dedi.
    lakehouse_distinct_values kimliği kendisi FROM'a yazıyordu (araç hatası); lakehouse_query'de model yazınca hata
    genel SQL_FAILED + yanıltıcı ipucuyla dönüyordu. Artık kırılım aracı doğru ilişkiyi kullanır, sorgu aracı çalıştırmadan
    doğru kalıbı söyler; gold tablosu ve doğru yazılmış seri sorgusu etkilenmez."""
    from kkb_agent.tools.lakehouse import LakehouseDistinctValuesTool, LakehouseQueryTool

    lake, ws, _ = env
    assert lake.relation_sql("evds:TP.KTF12").startswith("(SELECT * FROM silver.fact_observation WHERE series_id = ")

    distinct = LakehouseDistinctValuesTool(lake).validate_and_run({"dataset_id": "evds:TP.KTF12", "column": "quality_flag"})
    assert distinct.ok, distinct.content

    query = LakehouseQueryTool(lake, ws)
    for sql in ("SELECT observation_date, value FROM evds:TP.KTF12",
                "SELECT observation_date, value FROM TP.KTF12",
                'SELECT observation_date, value FROM "evds:TP.KTF12"'):
        r = query.validate_and_run({"sql": sql, "purpose": "faiz"})
        assert not r.ok and r.error.error_code == "INVALID_ARGS" and r.error.is_retryable, sql
        assert "series_id = 'evds:TP.KTF12'" in r.content and r.error.candidates == ["evds:TP.KTF12"]

    ok = query.validate_and_run({"sql": "SELECT observation_date, value FROM silver.fact_observation "
                                        "WHERE series_id = 'evds:TP.KTF12' AND observation_date BETWEEN '2025-01-01' "
                                        "AND '2025-03-31' ORDER BY observation_date", "purpose": "faiz"})
    assert ok.ok, ok.content
