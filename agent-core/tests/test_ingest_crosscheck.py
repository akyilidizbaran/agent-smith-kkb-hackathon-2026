"""Çapraz kontrol (builder/crosscheck.py) ve birim tahmini (builder/unit_guess.py) — V3 §3.9-E, 14 Eylül.

Ölçülen garantiler: örtüşen dönemlerde oran ≈ 1 → "örtüşüyor"; ×1000 ölçekle örtüşme → "birim farkı"
ve tahmin bir basamak büyük TL birimi; dağınık → "ÇELİŞİYOR" ve en büyük sapmalar listelenir; birden
çok aday ya da farklı frekans → karşılaştırılmaz, sebebi yazılır; hiçbiri ingest'i engellemez; birim
yoksa boş soru yerine kanıtlı aday sorulur ve yine yazılmaz.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.builder.crosscheck import compare, cross_check  # noqa: E402
from kkb_agent.builder.ingest import LakehouseCLI  # noqa: E402
from kkb_agent.builder.profile import profile_table, propose  # noqa: E402
from kkb_agent.builder.unit_guess import guess_unit  # noqa: E402
from kkb_agent.contracts.catalog import ColumnRole, Frequency  # noqa: E402
from kkb_agent.contracts.lakehouse import QueryProvenance, QueryResult  # noqa: E402
from kkb_agent.tools import ingest as ingest_mod  # noqa: E402
from kkb_agent.tools.ingest import IngestFromUrlTool  # noqa: E402

MONTHS = [date(2025, m, 28) for m in range(1, 7)]
REF = {d: 1000.0 + 50 * i for i, d in enumerate(MONTHS)}          # katalog: milyon TL


def _pts(scale: float = 1.0, noise: dict[int, float] | None = None) -> dict[date, float]:
    out = {}
    for i, d in enumerate(MONTHS):
        v = REF[d] / scale
        if noise and i in noise:
            v *= noise[i]
        out[date(2025, d.month, 27)] = v   # ay içi farklı gün (27 ≠ 28): ay anahtarı yine eşler
    return out


def test_ortusuyor() -> None:
    cc = compare(_pts(), REF, frequency="monthly", dataset_id="x", name="Konut", ref_unit="milyon TL")
    assert cc.verdict == "örtüşüyor" and cc.overlap == 6 and cc.same_unit


def test_birim_farki_x1000_ve_tahmin_milyar() -> None:
    cc = compare(_pts(scale=1000), REF, frequency="monthly", dataset_id="x", name="Konut", ref_unit="milyon TL")
    assert cc.verdict == "birim farkı" and cc.scale == 1000
    g = guess_unit(texts=["deger.csv", "Tarih", "Deger"], crosscheck=cc, values=_pts(scale=1000).values())
    assert g is not None and g.unit == "milyar TL" and g.confidence == "weak"


def test_celisiyor_en_buyuk_sapmalar() -> None:
    cc = compare(_pts(noise={1: 1.5, 3: 0.6, 4: 1.3}), REF, frequency="monthly", dataset_id="x", name="Konut", ref_unit="milyon TL")
    assert cc.verdict == "ÇELİŞİYOR" and cc.agree_share == pytest.approx(0.5)
    assert len(cc.worst) == 3 and "en büyük sapmalar" in cc.lines()[0]


def test_ortusen_donem_yoksa_karsilastirilamaz() -> None:
    far = {date(2019, m, 28): 1.0 for m in range(1, 4)}
    cc = compare(far, REF, frequency="monthly", dataset_id="x", name="Konut", ref_unit=None)
    assert cc.verdict == "karşılaştırılamadı" and cc.overlap == 0


def test_birim_tahmini_metin_once_sonra_aralik() -> None:
    assert guess_unit(texts=["ithalat (kg)"], crosscheck=None, values=[1, 2, 3]).unit == "kg"
    assert guess_unit(texts=["x"], crosscheck=None, values=[12.5, 30.1, 45.0]).unit == "yüzde"
    assert guess_unit(texts=["x"], crosscheck=None, values=[12, 30, 45]).unit == "adet"
    assert guess_unit(texts=["x"], crosscheck=None, values=[1e9, 2e9, 3e9]) is None


# ----------------------------------------------------------------- araç içinde
KONUT_CSV = pd.DataFrame(
    [[d.strftime("%d.%m.%Y"), f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")] for d, v in _pts().items()],
    columns=["Tarih", "Konut Kredisi"], dtype=str,           # başlıkta birim YOK
)


class FakeLakehouse:
    """Katalogda tek bir konut serisi; series_sql/execute_sql onu döndürür."""

    def __init__(self, ref: dict[date, float]) -> None:
        self.ref = ref; self.events: list[str] = []
        self.spec = SimpleNamespace(
            dataset_id="bddk_monthly:konut", name="Konut kredisi bakiyesi", source="BDDK",
            frequency=Frequency.MONTHLY, time_column="observation_date",
            columns=[SimpleNamespace(name="value", role=ColumnRole.MEASURE, unit="milyon TL",
                                     aliases=["konut kredisi", "mortgage"])],
        )

    def list_datasets(self):
        return [self.spec]

    def series_sql(self, dataset_id, *, key_column, value_column, filter_column=None, filter_value=None):
        return f"SELECT {key_column}, {value_column} FROM silver WHERE series_id='{dataset_id}'"

    def execute_sql(self, sql, *, max_rows=10_000):
        df = pd.DataFrame({"observation_date": list(self.ref), "value": list(self.ref.values())})
        return QueryResult(data=df, provenance=QueryProvenance(sql=sql, dataset_ids=["bddk_monthly:konut"]))

    def close(self) -> None:
        self.events.append("close")

    def reload(self) -> None:
        self.events.append("reload")


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, cmd, cwd):
        self.calls.append(cmd)
        return 0, ("status: success\nsource_id: adhoc\ndataset_id: adhoc_x\nrun_id: r1\n"
                   "artifact_sha256: " + "ab" * 32 + "\nbronze_path: b.parquet\nseries_id: adhoc:x\n"
                   "rows_written: 6\nrows_unchanged: 0\n"), ""


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")
    incoming = tmp_path / "incoming"; incoming.mkdir()
    runner = FakeRunner()
    cli = LakehouseCLI(core_dir=tmp_path / "lakehouse-core", database=tmp_path / "lh.duckdb",
                       data_root=tmp_path, runner=runner)
    lake = FakeLakehouse(REF)
    registry = SimpleNamespace(active_question="2025 konut kredisi bakiyesini aylık göster",
                               user_text="konut.csv dosyasını ekle; 2025 konut kredisi bakiyesini aylık göster",
                               sanctioned_locators=set())
    tool = IngestFromUrlTool(lake, cli, allowed_root=incoming, registry=registry)

    def fake_read(locator, *, allowed_roots, session=None, sheet=None):
        from kkb_agent.contracts.access import AccessOutcome
        return KONUT_CSV.copy(), AccessOutcome(status="ok", source=locator, message="okundu")

    monkeypatch.setattr(ingest_mod, "read_table_for_profiling", fake_read)
    return tool, lake, runner, registry


def test_birim_yoksa_kanitli_tahminle_sorar_yazmaz(env) -> None:
    tool, lake, runner, reg = env
    r = tool.validate_and_run({"locator": "konut.csv", "name": "konut"})
    assert r.ok and r.content.startswith("EKLENMEDİ")
    assert runner.calls == [] and lake.events == []
    assert "birim TAHMİNİ: 'milyon TL' [strong]" in r.content     # katalogla oran ≈ 1
    assert "unit='milyon TL'" in r.content


def test_kullanici_birimi_onaylayinca_yazilir_ve_kart_capraz_kontrolu_yazar(env) -> None:
    tool, lake, runner, reg = env
    reg.user_text += " — birim milyon TL"
    r = tool.validate_and_run({"locator": "konut.csv", "name": "konut", "unit": "milyon TL"})
    assert r.ok and r.content.startswith("EKLENDİ"), r.content
    assert len(runner.calls) == 1
    assert "çapraz kontrol (Konut kredisi bakiyesi): örtüşüyor" in r.content
    assert r.artifacts["crosscheck"].verdict == "örtüşüyor"


def test_celiskide_yazmadan_once_kullaniciya_soylenir(env, monkeypatch) -> None:
    tool, lake, runner, reg = env
    lake.ref = {d: v * (1.4 if i % 2 else 0.7) for i, (d, v) in enumerate(REF.items())}
    reg.user_text += " — birim milyon TL"
    r = tool.validate_and_run({"locator": "konut.csv", "name": "konut", "unit": "milyon TL"})
    assert r.content.startswith("EKLENMEDİ") and "ÇELİŞİYOR" in r.content and runner.calls == []


def test_birden_cok_aday_karsilastirilmaz() -> None:
    specs = [SimpleNamespace(dataset_id="a", name="A", frequency=Frequency.MONTHLY, columns=[]),
             SimpleNamespace(dataset_id="b", name="B", frequency=Frequency.MONTHLY, columns=[])]
    frame = KONUT_CSV.copy()
    mapping, semantics = propose(profile_table(frame), frame, series_id="adhoc:x")
    cc = cross_check(None, specs, ["a", "b"], frame, mapping, semantics)
    assert cc is not None and cc.verdict == "karşılaştırılamadı" and "2 aday" in cc.detail
