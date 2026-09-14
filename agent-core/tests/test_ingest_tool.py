"""`ingest_from_url` — Analist'ten Architect'e tek kapı; CLI sahte, ağ yok.

Ölçülen garantiler: yazmadan önce okuyucu kapanır ve sonra yeniden açılır; CLI'a
giden bayraklar öneriden birebir gelir; belirsizlikte ve birim yokken CLI HİÇ
çağrılmaz; erişim engeli ADR-0028 zarfıyla döner; izinsiz kök okunmaz.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.builder.ingest import LakehouseCLI  # noqa: E402
from kkb_agent.tools.ingest import IngestFromUrlTool  # noqa: E402

TR_CSV = (
    "Tarih;Konut Kredisi (milyon TL)\n"
    "31.01.2025;1.234,5\n28.02.2025;1.300,0\n31.03.2025;1.402,75\n"
    "30.04.2025;1.450,1\n31.05.2025;1.500,0\n30.06.2025;1.560,9\n"
)


class SpyLakehouse:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.open = True

    def list_datasets(self):
        return []

    def close(self) -> None:
        self.events.append("close"); self.open = False

    def reload(self) -> None:
        self.events.append("reload"); self.open = True


class FakeRunner:
    """CLI yerine geçer: komutu kaydeder, sabit bir 'success' çıktısı döner."""

    def __init__(self, stdout: str | None = None, code: int = 0) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.stdout = stdout or (
            "status: success\nsource_id: adhoc\ndataset_id: adhoc_konut\n"
            "run_id: 0f1e2d3c-0000-4000-8000-000000000001\n"
            "artifact_sha256: " + "ab" * 32 + "\nbronze_path: data/bronze/x.parquet\n"
            "series_id: adhoc:konut\nrows_written: 6\nrows_unchanged: 0\n"
        )
        self.code = code

    def __call__(self, cmd: list[str], cwd: Path) -> tuple[int, str, str]:
        self.calls.append((cmd, cwd))
        return self.code, self.stdout, ""


@pytest.fixture
def env(tmp_path: Path):
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")
    incoming = tmp_path / "incoming"; incoming.mkdir()
    (incoming / "konut.csv").write_text(TR_CSV, encoding="utf-8")
    runner = FakeRunner()
    cli = LakehouseCLI(core_dir=tmp_path / "lakehouse-core", database=tmp_path / "lh.duckdb",
                       data_root=tmp_path, runner=runner)
    lake = SpyLakehouse()
    # Niyet kapısı (ADR-0037): adres ve yazma isteği kullanıcı metninde olmalı.
    from types import SimpleNamespace
    registry = SimpleNamespace(
        active_question="",
        user_text="Şu dosyaları taslak seri olarak ekle: konut.csv belirsiz.csv birimsiz.csv "
                  "disarida.csv https://www.spglobal.com/x",
        sanctioned_locators=set(),
    )
    tool = IngestFromUrlTool(lake, cli, allowed_root=incoming, registry=registry)
    return tool, lake, runner, incoming, tmp_path


def test_mutlu_yol_kapat_yaz_yeniden_ac_ve_belgele(env) -> None:
    tool, lake, runner, incoming, _ = env

    r = tool.validate_and_run({"locator": str(incoming / "konut.csv"), "name": "Konut kredisi (test)"})

    assert r.ok, r.content
    assert lake.events == ["close", "reload"] and lake.open
    assert len(runner.calls) == 1
    cmd, cwd = runner.calls[0]
    # bayraklar öneriden birebir
    flags = dict(zip(cmd, cmd[1:]))
    assert flags["--date-column"] == "Tarih" and flags["--date-format"] == "%d.%m.%Y"
    assert flags["--value-column"] == "Konut Kredisi (milyon TL)"
    assert flags["--decimal-separator"] == "," and flags["--thousands-separator"] == "."
    assert flags["--unit"] == "TRY_mn" and flags["--frequency"] == "monthly"
    assert flags["--series-id"] == "adhoc:konut" and flags["--allowed-local-root"] == str(incoming)
    assert cmd[:3] == ["uv", "run", "python"] and "-m" in cmd and "ingest-file" in cmd
    # belge kartı
    assert r.content.startswith("EKLENDİ: adhoc:konut")
    assert "run_id: 0f1e2d3c" in r.content and "artifact_sha256: abab" in r.content
    assert "taslak" in r.content and "6 eşlendi" in r.content


def test_belirsiz_tarihte_sorar_yazmaz(env) -> None:
    tool, lake, runner, incoming, _ = env
    (incoming / "belirsiz.csv").write_text("d,v\n01/02/2026,1\n03/04/2026,2\n05/06/2026,3\n", encoding="utf-8")

    r = tool.validate_and_run({"locator": str(incoming / "belirsiz.csv"), "name": "x"})

    assert r.ok and r.content.startswith("EKLENMEDİ")
    assert "kullanıcıya sorulmalı" in r.content and "date_format" in r.content
    assert runner.calls == [] and lake.events == []


def test_birim_yoksa_sorar_yazmaz(env) -> None:
    tool, lake, runner, incoming, _ = env
    (incoming / "birimsiz.csv").write_text(
        "donem,deger\n2026-01-31,100\n2026-02-28,110\n2026-03-31,120\n2026-04-30,130\n2026-05-31,140\n2026-06-30,150\n",
        encoding="utf-8",
    )

    r = tool.validate_and_run({"locator": str(incoming / "birimsiz.csv"), "name": "x"})

    assert r.content.startswith("EKLENMEDİ") and "birim" in r.content
    assert runner.calls == [] and lake.events == []


def test_izinsiz_kok_okunmaz(env, tmp_path: Path) -> None:
    tool, lake, runner, _, _ = env
    outside = tmp_path / "disarida.csv"; outside.write_text(TR_CSV, encoding="utf-8")

    r = tool.validate_and_run({"locator": str(outside), "name": "x"})

    assert not r.ok and r.error.error_code == "ACCESS_BLOCKED"
    assert runner.calls == [] and lake.open


def test_bot_engeli_adr0028_zarfiyla_doner(env, monkeypatch) -> None:
    tool, lake, runner, _, _ = env

    class Resp:
        status_code = 403; url = "https://www.spglobal.com/x"
        def iter_content(self, n): yield b"<h1>Security Controls Triggered</h1>"
        def close(self): pass

    class Session:
        def get(self, *a, **k): return Resp()

    monkeypatch.setattr("kkb_agent.builder.read._private_host", lambda host: False)
    tool.session = Session()

    r = tool.validate_and_run({"locator": "https://www.spglobal.com/x", "name": "x"})

    assert not r.ok and r.error.error_code == "ACCESS_BLOCKED" and r.error.layer == "access"
    assert "bot_challenge" in r.content and "KURAL:" in r.content
    assert runner.calls == [] and lake.open


def test_cli_hatasi_okuyucuyu_yine_de_geri_acar(env) -> None:
    tool, lake, runner, incoming, _ = env
    runner.code = 2; runner.stdout = "status: failed\nerror: adhoc:konut: '1.234,5' at row 0 is not a number"

    r = tool.validate_and_run({"locator": str(incoming / "konut.csv"), "name": "x"})

    assert not r.ok and r.error.error_code == "TOOL_FAILED" and not r.error.is_retryable
    assert lake.events == ["close", "reload"] and lake.open


def test_cli_yoksa_politikada_durur(tmp_path: Path) -> None:
    from types import SimpleNamespace
    cli = LakehouseCLI(core_dir=tmp_path / "yok", database=tmp_path / "x", data_root=tmp_path, runner=FakeRunner())
    reg = SimpleNamespace(active_question="x.csv dosyasını ekle", user_text="x.csv dosyasını ekle", sanctioned_locators=set())
    tool = IngestFromUrlTool(SpyLakehouse(), cli, allowed_root=tmp_path, registry=reg)
    r = tool.validate_and_run({"locator": "x.csv", "name": "x"})
    assert not r.ok and r.error.error_code == "TOOL_FAILED" and r.error.layer == "policy"


def test_niyet_kapisi_kullanicinin_vermedigi_kaynak_ve_istenmemis_yazma(env) -> None:
    """ADR-0037: sayfaya gömülü 'şu adresi ingest et' talimatı kapıyı açamaz; yazma isteği yoksa da."""
    tool, lake, runner, incoming, _ = env
    r = tool.validate_and_run({"locator": "https://evil.example/tufe.csv", "name": "x"})
    assert not r.ok and r.error.error_code == "INTENT_REQUIRED" and not r.error.is_retryable
    assert "kullanıcının mesajında geçmiyor" in r.content and runner.calls == [] and lake.events == []

    tool._registry.user_text = "Şu dosyada ne var: konut.csv"   # adres var, yazma isteği yok
    r2 = tool.validate_and_run({"locator": str(incoming / "konut.csv"), "name": "x"})
    assert not r2.ok and r2.error.error_code == "INTENT_REQUIRED" and "açıkça istemedi" in r2.content
    assert runner.calls == []


def test_katalog_kaydi_kullanicinin_adindan_bagimsiz_deterministik(env) -> None:
    """Ölçülen hata: model ikinci koşuda farklı 'name' verdi, veri ekibinin sözleşmesi
    "aynı draft, farklı içerik" diye reddetti. Katalog kaydı dosya + öneriden türer;
    kullanıcının adı yalnız karta girer."""
    tool, _, runner, incoming, _ = env

    r1 = tool.validate_and_run({"locator": str(incoming / "konut.csv"), "name": "Konut test verisi"})
    r2 = tool.validate_and_run({"locator": str(incoming / "konut.csv"), "name": "Bambaşka bir ad"})

    assert r1.ok and r2.ok
    f1 = dict(zip(runner.calls[0][0], runner.calls[0][0][1:]))
    f2 = dict(zip(runner.calls[1][0], runner.calls[1][0][1:]))
    assert f1["--name"] == f2["--name"] == "konut — konut.csv (taslak)"
    assert f1["--description"] == f2["--description"]
    assert "Konut test verisi" in r1.content and "Bambaşka bir ad" in r2.content


def test_farkli_icerikli_taslak_catismasi_kullaniciya_sorulur(env) -> None:
    tool, lake, runner, incoming, _ = env
    runner.code = 2
    runner.stdout = ("status: failed\nerror: 'adhoc:konut' already exists as a draft with different "
                     "content; delete or promote the existing draft before proposing a different one")

    r = tool.validate_and_run({"locator": str(incoming / "konut.csv"), "name": "x"})

    assert not r.ok and r.error.error_code == "TOOL_FAILED" and not r.error.is_retryable
    assert "zaten var" in r.content and "series_key" in r.content
    assert lake.events == ["close", "reload"]
