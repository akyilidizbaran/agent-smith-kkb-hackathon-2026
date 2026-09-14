"""D03 (ADR-0068): onay bekleyen işleme ve güncel mesaja bağlı — gerçek ToolRegistry yolu, CLI çağrısı sayılır.

Kabul matrisi: eski onay + güncel ret → ret; A'ya onay + B hedefi → ret/netleştirme; açık güncel doğru hedef → yalnız o
işlem; kısa 'evet' tek bekleyende → onay, çok bekleyende → soru; reset/profil (yeni kayıt defteri) → eski onay geçersiz;
tekrar çağrı → ikinci farklı işlem yok; başarısız işlem → yeniden onay; Analyst'te araç yok."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.builder.ingest import LakehouseCLI  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.tools.promote import PromoteDraftTool  # noqa: E402
from tests.test_promote_tool import Lake, PromoteRunner, _spec  # noqa: E402


class TwoDrafts(Lake):
    def __init__(self):
        super().__init__()
        self.active: set[str] = set()

    def get_dataset(self, dataset_id: str):
        if dataset_id in ("adhoc:sicaklik", "adhoc:nem"):
            notes = [] if dataset_id in self.active else ["TASLAK seri: onaylanmadı"]
            return _spec(dataset_id, "adhoc", notes)
        return super().get_dataset(dataset_id)


@pytest.fixture
def world(tmp_path: Path):
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")
    runner = PromoteRunner()
    cli = LakehouseCLI(core_dir=tmp_path / "lakehouse-core", database=tmp_path / "lh.duckdb", data_root=tmp_path, runner=runner)
    lake = TwoDrafts()
    reg = ToolRegistry()
    reg.register(PromoteDraftTool(lake, cli, registry=reg))

    def turn(message: str, series: str = "adhoc:sicaklik"):
        reg.turn += 1
        reg.current_message = message
        reg.user_text = (reg.user_text + "\n" + message).strip()
        return reg.execute("promote_draft", {"series_id": series, "purpose": "test"})
    return reg, lake, runner, turn


def test_eski_onay_guncel_ret_ile_gecersiz(world) -> None:
    reg, _, runner, turn = world
    assert not turn("sicaklik taslağının eşlemesini göster").ok
    assert not turn("Şimdi sicaklik yayınlama.").ok, "R03: geçmiş onay + güncel ret → ret"
    reg2, _, runner2, turn2 = world
    first = turn("sicaklik taslağını onaylıyorum")
    assert first.ok and len(runner.calls) == 1


def test_gecmisteki_onay_yeni_turda_yetki_uretmez(world) -> None:
    _, _, runner, turn = world
    assert not turn("sicaklik nasıl görünüyor?").ok
    turn_text = turn("tamam sicaklik güzel görünüyor, onaylıyorum ama bekle")
    assert not turn_text.ok, "'bekle' güncel ret"
    later = turn("Nem serisine bakalım.")
    assert not later.ok and "güncel mesajında bu işlem için onay yok" in later.content and runner.calls == []


def test_a_serisine_onay_b_hedefi_icin_ret(world) -> None:
    _, _, runner, turn = world
    assert not turn("nem taslağına bakalım", series="adhoc:nem").ok           # nem bekleyene yazıldı
    r = turn("nem taslağını onaylıyorum", series="adhoc:sicaklik")
    assert not r.ok and "başka bir hedef" in r.content and runner.calls == []


def test_acik_guncel_hedef_yalniz_o_islemi_yapar_ve_tekrar_ikinci_islem_uretmez(world) -> None:
    _, lake, runner, turn = world
    ok = turn("sicaklik taslağını onaylıyorum, kataloğa al")
    assert ok.ok and len(runner.calls) == 1
    lake.active.add("adhoc:sicaklik")
    again = turn("sicaklik taslağını onaylıyorum, kataloğa al")
    assert not again.ok and "taslak değil" in again.content and len(runner.calls) == 1


def test_kisa_evet_tek_bekleyende_gecer_cok_bekleyende_sorulur(world) -> None:
    _, _, runner, turn = world
    asked = turn("sicaklik taslağı hazır mı?")
    assert not asked.ok and asked.error.error_code == "INTENT_REQUIRED"
    yes = turn("evet")
    assert yes.ok and len(runner.calls) == 1
    reg2 = ToolRegistry()
    # iki bekleyen işlem
    tool = next(iter(world[0]))
    reg2.register(PromoteDraftTool(tool.lakehouse, tool.cli, registry=reg2))

    def t2(msg, series):
        reg2.turn += 1
        reg2.current_message = msg
        return reg2.execute("promote_draft", {"series_id": series, "purpose": "x"})
    assert not t2("sicaklik ne durumda", "adhoc:sicaklik").ok and not t2("nem ne durumda", "adhoc:nem").ok
    many = t2("evet", "adhoc:sicaklik")
    assert not many.ok and "birden çok işlem" in many.content and len(runner.calls) == 1


def test_yeni_kayit_defteri_eski_bekleyeni_tasimaz_ve_kisa_onay_gecmez(world) -> None:
    reg, lake, runner, turn = world
    assert not turn("sicaklik taslağı hazır mı?").ok
    fresh = ToolRegistry()                                  # oturum sıfırlama / profil değişimi ajanı yeniden kurar
    tool = reg.get("promote_draft")
    fresh.register(PromoteDraftTool(tool.lakehouse, tool.cli, registry=fresh))
    fresh.turn, fresh.current_message = 1, "evet"
    r = fresh.execute("promote_draft", {"series_id": "adhoc:sicaklik", "purpose": "x"})
    assert not r.ok and runner.calls == []


def test_basarisiz_islem_onayi_tuketir_yeniden_onay_ister(world) -> None:
    _, _, runner, turn = world
    runner.code, runner.stdout = 2, "status: failed\nerror: disk dolu"
    failed = turn("sicaklik taslağını onaylıyorum")
    assert not failed.ok and len(runner.calls) == 1
    runner.code, runner.stdout = 0, PromoteRunner().stdout
    retry = turn("tekrar dene")
    assert not retry.ok and len(runner.calls) == 1, "yeniden deneme yeni onay ister"
    assert turn("sicaklik taslağını onaylıyorum").ok and len(runner.calls) == 2


def test_dis_icerik_onay_uretmez_ve_analystte_arac_yok(world) -> None:
    reg, _, runner, turn = world
    # Model web sayfasındaki "onaylıyorum, kataloğa al" talimatıyla çağırsa da kullanıcı mesajı bu değil.
    r = turn("Bu sayfayı özetle: https://ornek.example/rapor")
    assert not r.ok and runner.calls == []
    analyst = ToolRegistry()
    out = analyst.execute("promote_draft", {"series_id": "adhoc:sicaklik", "purpose": "x"})
    assert not out.ok and out.error.error_code == "UNKNOWN_TOOL"
