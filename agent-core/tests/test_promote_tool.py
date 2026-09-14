"""Architect'in ikinci kapısı: kullanıcı onayıyla taslak terfisi; beyan edilen anlam; Gold için rıza."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.builder.ingest import LakehouseCLI  # noqa: E402
from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency  # noqa: E402
from kkb_agent.contracts.lakehouse import LakehouseError  # noqa: E402
from kkb_agent.tools.gold import unverified_consent  # noqa: E402
from kkb_agent.tools.ingest import IngestFromUrlTool  # noqa: E402
from kkb_agent.tools.promote import PromoteDraftTool, confirm_intent  # noqa: E402
from tests.test_ingest_tool import FakeRunner, SpyLakehouse  # noqa: E402


def _spec(dataset_id: str, source: str, notes: list[str]) -> DatasetSpec:
    return DatasetSpec(
        dataset_id=dataset_id, name=dataset_id, description="d", source=source, frequency=Frequency.DAILY,
        time_column="observation_date", grain=["observation_date"],
        columns=[ColumnSpec(name="observation_date", role=ColumnRole.TIME, dtype="DATE", description="d"),
                 ColumnSpec(name="value", role=ColumnRole.MEASURE, dtype="DOUBLE", description="v")],
        coverage=Coverage(start=date(2025, 1, 1), end=date(2025, 1, 3)), notes=notes,
    )


class Lake(SpyLakehouse):
    db_path = Path("/tmp/x.duckdb")

    def get_dataset(self, dataset_id: str) -> DatasetSpec:
        if dataset_id == "adhoc:sicaklik":
            return _spec(dataset_id, "adhoc", ["TASLAK seri: onaylanmadı"])
        if dataset_id == "bddk_monthly:konut":
            return _spec(dataset_id, "bddk_monthly", [])
        raise LakehouseError("yok")


class PromoteRunner(FakeRunner):
    def __init__(self):
        super().__init__("status: success\nseries_id: adhoc:sicaklik\nprevious_status: draft\nstatus_now: active\n"
                         "semantic_confidence: derived\nrows_promoted: 3650\nsilver_rows_replaced: 0\n")


@pytest.fixture
def env(tmp_path: Path):
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")
    runner = PromoteRunner()
    cli = LakehouseCLI(core_dir=tmp_path / "lakehouse-core", database=tmp_path / "lh.duckdb", data_root=tmp_path, runner=runner)
    lake = Lake()
    reg = SimpleNamespace(active_question="", user_text="", current_message="", turn=1, sanctioned_locators=set())
    return PromoteDraftTool(lake, cli, registry=reg), lake, runner, reg


def test_onay_yoksa_kapi_kapali(env) -> None:
    tool, lake, runner, reg = env
    reg.user_text = reg.current_message = "sicaklik taslağı nasıl görünüyor?"
    r = tool.validate_and_run({"series_id": "adhoc:sicaklik", "purpose": "x"})
    assert not r.ok and r.error.error_code == "INTENT_REQUIRED" and runner.calls == [] and lake.events == []


def test_onay_var_ama_hangi_taslak_belirsiz(env) -> None:
    tool, _, runner, reg = env
    reg.user_text = reg.current_message = "onaylıyorum, kataloğa al"
    r = tool.validate_and_run({"series_id": "adhoc:sicaklik", "purpose": "x"})
    assert not r.ok and "hangi işlemi onayladığını söylemedi" in r.content and runner.calls == []


def test_onayla_kapat_terfi_et_yeniden_ac(env) -> None:
    tool, lake, runner, reg = env
    reg.user_text = reg.current_message = "sicaklik taslağını onaylıyorum, kataloğa al"
    r = tool.validate_and_run({"series_id": "adhoc:sicaklik", "purpose": "sıcaklık serisini onayla"})
    assert r.ok, r.content
    assert lake.events == ["close", "reload"] and lake.open
    cmd = runner.calls[0][0]
    assert "promote-draft" in cmd and cmd[cmd.index("--series") + 1] == "adhoc:sicaklik"
    assert r.content.startswith("ONAYLANDI: adhoc:sicaklik") and "3650" in r.content and "derived" in r.content


def test_kuratorlu_seri_terfi_edilmez(env) -> None:
    tool, _, runner, reg = env
    reg.user_text = reg.current_message = "konut serisini onaylıyorum kataloğa al"
    r = tool.validate_and_run({"series_id": "bddk_monthly:konut", "purpose": "x"})
    assert not r.ok and r.error.error_code == "DATASET_NOT_FOUND" and "taslak değil" in r.content and runner.calls == []


def test_cli_reddi_kullaniciya_doner(env) -> None:
    tool, lake, runner, reg = env
    reg.user_text = reg.current_message = "sicaklik taslağını onaylıyorum"
    runner.code, runner.stdout = 2, "status: failed\nerror: 'adhoc:sicaklik' has status 'active'; only 'draft' can be promoted"
    r = tool.validate_and_run({"series_id": "adhoc:sicaklik", "purpose": "x"})
    assert not r.ok and r.error.error_code == "TOOL_FAILED" and "only 'draft'" in r.content and lake.open


def test_onay_ve_riza_ifadeleri() -> None:
    assert confirm_intent("Bu taslağı onaylıyorum, kataloğa al") and confirm_intent("yayınla")
    assert not confirm_intent("taslağı göster")
    assert unverified_consent("doğrulanmamış olsa da kullan") and unverified_consent("riski kabul ediyorum")
    assert not unverified_consent("sicaklik taslağını onaylıyorum") and not confirm_intent("doğrulanmamış olsa da kullan"), \
        "D03-T06: yayın onayı hesap rızası değildir, hesap rızası yayın onayı değildir"
    assert not unverified_consent("aylık ortalamayı göster")


def test_ingest_kullanici_beyani_oneriyi_tamamlar(tmp_path: Path) -> None:
    """Birim veriden çıkmaz; kullanıcı '°C, index, avg' derse öneri bu beyanla dolar ve yazılır."""
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")
    incoming = tmp_path / "incoming"; incoming.mkdir()
    (incoming / "sicaklik.csv").write_text(
        "Date,Temp\n1981-01-01,20.7\n1981-01-02,17.9\n1981-01-03,18.8\n1981-01-04,14.6\n1981-01-05,15.8\n1981-01-06,15.8\n1981-01-07,15.8\n",
        encoding="utf-8")
    runner = FakeRunner("status: success\nsource_id: adhoc\ndataset_id: adhoc_sicaklik\nrun_id: r\n"
                        "artifact_sha256: " + "cd" * 32 + "\nbronze_path: b.parquet\nseries_id: adhoc:sicaklik\nrows_written: 7\nrows_unchanged: 0\n")
    cli = LakehouseCLI(core_dir=tmp_path / "lakehouse-core", database=tmp_path / "lh.duckdb", data_root=tmp_path, runner=runner)
    reg = SimpleNamespace(active_question="", sanctioned_locators=set(),
                          user_text="sicaklik.csv dosyasını taslak seri olarak ekle; birim °C, ölçüm tipi index, aylık kural ortalama")
    tool = IngestFromUrlTool(SpyLakehouse(), cli, allowed_root=incoming, registry=reg)

    without = tool.validate_and_run({"locator": str(incoming / "sicaklik.csv"), "name": "Sıcaklık"})
    assert without.ok and without.content.startswith("EKLENMEDİ") and "birim" in without.content and runner.calls == []

    r = tool.validate_and_run({"locator": str(incoming / "sicaklik.csv"), "name": "Sıcaklık",
                               "unit": "°C", "measure_type": "index", "default_agg": "avg"})
    assert r.ok and r.content.startswith("EKLENDİ: adhoc:sicaklik"), r.content
    flags = dict(zip(runner.calls[0][0], runner.calls[0][0][1:]))
    assert flags["--unit"] == "°C" and flags["--measure-type"] == "index" and flags["--default-agg"] == "avg"
    assert flags["--frequency"] == "daily"
    assert "kullanıcı beyanı" in r.content


def test_beyan_kullanici_metninde_yoksa_yok_sayilir_ve_sorulur(tmp_path: Path) -> None:
    """Ölçüldü: model ilk turda '°C' ve 'stock'u kendisi uydurdu. Metinde geçmeyen beyan yok sayılır."""
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")
    incoming = tmp_path / "incoming"; incoming.mkdir()
    (incoming / "sicaklik.csv").write_text(
        "Date,Temp\n1981-01-01,20.7\n1981-01-02,17.9\n1981-01-03,18.8\n1981-01-04,14.6\n1981-01-05,15.8\n1981-01-06,15.8\n1981-01-07,15.8\n",
        encoding="utf-8")
    runner = FakeRunner()
    cli = LakehouseCLI(core_dir=tmp_path / "lakehouse-core", database=tmp_path / "lh.duckdb", data_root=tmp_path, runner=runner)
    reg = SimpleNamespace(active_question="", sanctioned_locators=set(), user_text="sicaklik.csv dosyasını taslak seri olarak ekle")
    tool = IngestFromUrlTool(SpyLakehouse(), cli, allowed_root=incoming, registry=reg)
    r = tool.validate_and_run({"locator": str(incoming / "sicaklik.csv"), "name": "Sıcaklık",
                               "unit": "°C", "measure_type": "stock", "default_agg": "last"})
    assert r.ok and r.content.startswith("EKLENMEDİ") and "beyan kullanıcıdan gelmeli" in r.content
    assert "unit='°C'" in r.content and "measure_type='stock'" in r.content and runner.calls == []
