"""Şekil düzeltmeleri (21 Eyl): kolon seçimi ve beyan edilen dönem — "istediğimiz veri eklenebilsin".

Ölçülen boşluk: çok kolonlu dosyada profilci "en dolu sayısal kolonu" sessizce alıyordu (TLREF'te kapanış yerine
en düşük değer); tarih kolonu olmayan kesit tabloları (TCMB KFE.pdf: il × ölçüm, dönem başlıkta) hiç kaydedilemiyordu.
CLI sahte, ağ yok.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.builder.ingest import LakehouseCLI  # noqa: E402
from kkb_agent.builder.web_source import SourceSelection, measure_row_to_long  # noqa: E402
from kkb_agent.tools.ingest import IngestFromUrlTool, parse_period  # noqa: E402
from tests.test_ingest_tool import FakeRunner, SpyLakehouse  # noqa: E402

TLREF = (
    "Tarih;Kod;Kapanış Değeri;En Düşük Değer;En Yüksek Değer\n"
    "14.06.2019;BISTTLREF;1000;999;1001\n17.06.2019;BISTTLREF;1000,68;1000,1;1001,2\n"
    "18.06.2019;BISTTLREF;1001,35;1000,9;1002\n19.06.2019;BISTTLREF;1002,1;1001,5;1002,8\n"
    "20.06.2019;BISTTLREF;1002,9;1002,2;1003,4\n21.06.2019;BISTTLREF;1003,7;1003,0;1004,1\n"
)
HASTANE = "il;hastane_sayisi;yatak_sayisi\nAdana;41;7120\nAnkara;96;22310\nİzmir;73;15405\nVan;18;3020\n"


def _tool(tmp_path: Path, user_text: str, files: dict[str, str]):
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")
    incoming = tmp_path / "incoming"; incoming.mkdir()
    for name, body in files.items():
        (incoming / name).write_text(body, encoding="utf-8")
    runner = FakeRunner()
    cli = LakehouseCLI(core_dir=tmp_path / "lakehouse-core", database=tmp_path / "lh.duckdb", data_root=tmp_path, runner=runner)
    registry = SimpleNamespace(active_question=user_text, user_text=user_text, sanctioned_locators=set())
    return IngestFromUrlTool(SpyLakehouse(), cli, allowed_root=incoming, registry=registry), runner, incoming


def _flag(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def test_cok_kolonlu_dosyada_deger_kolonu_secilmeden_yazilmaz_sorulur(tmp_path: Path) -> None:
    tool, runner, incoming = _tool(tmp_path, "tlref.csv dosyasını taslak olarak kaydet; birim puan, ölçüm tipi seviye", {"tlref.csv": TLREF})
    r = tool.validate_and_run({"locator": str(incoming / "tlref.csv"), "name": "TLREF", "unit": "puan", "measure_type": "index"})
    assert r.ok and r.content.startswith("EKLENMEDİ") and "değer kolonu: 3 sayısal kolon" in r.content, r.content
    assert "Kapanış Değeri" in r.content and not runner.calls, "sessiz tahminle CLI çağrılmadı"


def test_kullanicinin_andigi_deger_kolonu_cliya_gider(tmp_path: Path) -> None:
    tool, runner, incoming = _tool(tmp_path, "tlref.csv dosyasındaki kapanış değerini taslak olarak kaydet; birim puan, ölçüm tipi seviye", {"tlref.csv": TLREF})
    r = tool.validate_and_run({"locator": str(incoming / "tlref.csv"), "name": "TLREF", "unit": "puan", "measure_type": "index",
                               "value_column": "Kapanış Değeri"})
    assert r.content.startswith("EKLENDİ"), r.content
    cmd = runner.calls[-1][0]
    assert _flag(cmd, "--value-column") == "Kapanış Değeri" and _flag(cmd, "--date-column") == "Tarih"
    assert _flag(cmd, "--decimal-separator") == ","


def test_kullanicinin_anmadigi_kolon_secimi_beyan_sayilmaz_ve_sorulur(tmp_path: Path) -> None:
    tool, runner, incoming = _tool(tmp_path, "tlref.csv dosyasını taslak olarak kaydet; birim puan, ölçüm tipi seviye", {"tlref.csv": TLREF})
    r = tool.validate_and_run({"locator": str(incoming / "tlref.csv"), "name": "TLREF", "unit": "puan", "measure_type": "index",
                               "value_column": "En Düşük Değer"})       # model seçti, kullanıcı anmadı
    assert r.content.startswith("EKLENMEDİ") and "value_column='En Düşük Değer'" in r.content and not runner.calls


def test_olmayan_kolon_secimi_acikca_reddedilir(tmp_path: Path) -> None:
    tool, runner, incoming = _tool(tmp_path, "tlref.csv dosyasındaki hacim kolonunu kaydet; birim puan, ölçüm tipi seviye", {"tlref.csv": TLREF})
    r = tool.validate_and_run({"locator": str(incoming / "tlref.csv"), "name": "x", "unit": "puan", "measure_type": "index", "value_column": "Hacim"})
    assert not r.ok and "dosyada yok" in r.content and "Kapanış Değeri" in r.content and not runner.calls


def test_tarihsiz_kesit_tablosu_beyan_edilen_donemle_kaydedilir(tmp_path: Path) -> None:
    tool, runner, incoming = _tool(
        tmp_path, "hastane_il.csv dosyasındaki hastane sayısını il bazında, dönem Ağustos 2026, taslak olarak kaydet; birim adet, ölçüm tipi sayım",
        {"hastane_il.csv": HASTANE})
    r = tool.validate_and_run({"locator": str(incoming / "hastane_il.csv"), "name": "Hastane", "unit": "adet", "measure_type": "count",
                               "period": "Ağustos 2026", "value_column": "hastane_sayisi", "entity_column": "il"})
    assert r.content.startswith("EKLENDİ"), r.content
    cmd = runner.calls[-1][0]
    staged = Path(_flag(cmd, "--file-or-url") or cmd[cmd.index("ingest-file") + 1])
    assert staged.name.startswith("derived_hastane_il_") and staged.parent == incoming
    frame = pd.read_csv(staged)
    assert list(frame.columns)[0] == "observation_date" and set(frame["observation_date"]) == {"2026-08-31"} and len(frame) == 4
    assert _flag(cmd, "--date-column") == "observation_date" and _flag(cmd, "--value-column") == "hastane_sayisi"
    assert _flag(cmd, "--entity-column") == "il" and _flag(cmd, "--frequency") == "monthly"
    assert "dönem sonu 2026-08-31" in r.content and "derived_hastane_il_" in r.content


def test_donem_kullanici_metninde_gecmiyorsa_beyan_sayilmaz(tmp_path: Path) -> None:
    tool, runner, incoming = _tool(tmp_path, "hastane_il.csv dosyasını taslak olarak kaydet; birim adet, ölçüm tipi sayım", {"hastane_il.csv": HASTANE})
    r = tool.validate_and_run({"locator": str(incoming / "hastane_il.csv"), "name": "Hastane", "unit": "adet", "measure_type": "count",
                               "period": "Ağustos 2026", "value_column": "hastane_sayisi"})
    assert not runner.calls and ("period=" in r.content or "tarih kolonu" in r.content.lower()), r.content


def test_donem_yazimlari() -> None:
    assert parse_period("2026-06-30") == ("2026-06-30", None)
    assert parse_period("2026-08") == ("2026-08-31", "monthly")
    assert parse_period("Ağustos 2026") == ("2026-08-31", "monthly") and parse_period("2026 Şubat") == ("2026-02-28", "monthly")
    assert parse_period("2026Q2") == ("2026-06-30", "quarterly") and parse_period("2026 Ç4") == ("2026-12-31", "quarterly")
    assert parse_period("2025") == ("2025-12-31", "yearly")
    assert parse_period("06/08/2026") is None and parse_period("gelecek ay") is None and parse_period("2026-13") is None


def test_satir_olcum_matrisi_beyan_edilen_donemle_uzun_tabloya_cevrilir() -> None:
    frame = pd.DataFrame({"": ["Konut Fiyat Endeksi", "Yıllık Değişim", "Aylık Değişim"],
                          "TÜRKİYE": ["236,8", "%23,0", "%0,9"], "İSTANBUL": ["226,6", "%26,3", "%1,9"],
                          "ANKARA": ["265,0", "%24,8", "%1,5"], "İZMİR": ["229,6", "%23,3", "%2,7"]})
    with pytest.raises(SourceSelection, match="period ile"):
        measure_row_to_long(frame, "Konut Fiyat Endeksi", None)
    long, note, freq = measure_row_to_long(frame, "Konut Fiyat Endeksi", ("2026-08-31", "monthly"))
    assert list(long.columns) == ["tarih", "kurum", "Konut Fiyat Endeksi"] and len(long) == 4
    assert set(long["tarih"]) == {"2026-08-31"} and long["kurum"].tolist() == ["TÜRKİYE", "İSTANBUL", "ANKARA", "İZMİR"]
    assert long["Konut Fiyat Endeksi"].tolist() == ["236,8", "226,6", "265,0", "229,6"] and freq == "monthly"
    assert "kullanıcı beyanı" in note
    with pytest.raises(SourceSelection, match="value_row ile seç"):
        measure_row_to_long(frame, "Yok", ("2026-08-31", "monthly"))
    assert measure_row_to_long(frame, None, None) is None, "value_row yoksa dönüşüm istenmiyor"


def test_varlik_kolonu_adi_kullanicinin_sozunden() -> None:
    from kkb_agent.tools.ingest import _entity_label
    assert _entity_label("KFE satırını il bazında kaydet") == "il"
    assert _entity_label("kurumlara göre nakdi kredi") == "kurum"
    assert _entity_label("ülke bazında enflasyon") == "ulke"
    assert _entity_label("taslak olarak kaydet") == "kurum"
    frame = pd.DataFrame({"": ["KFE"], "TÜRKİYE": ["236,8"], "ANKARA": ["265,0"]})
    long, _, _ = measure_row_to_long(frame, "KFE", ("2026-08-31", "monthly"), entity_label="il")
    assert list(long.columns) == ["tarih", "il", "KFE"]


def test_kaynak_birimi_acikca_yaziyorsa_sorulmadan_alinir(tmp_path: Path) -> None:
    csv = "Tarih;Konut Kredisi (milyon TL)\n31.01.2025;1.234,5\n28.02.2025;1.300,0\n31.03.2025;1.402,75\n30.04.2025;1.450,1\n31.05.2025;1.500,0\n30.06.2025;1.560,9\n"
    tool, runner, incoming = _tool(tmp_path, "konut.csv dosyasını taslak olarak kaydet; ölçüm tipi stok", {"konut.csv": csv})
    r = tool.validate_and_run({"locator": str(incoming / "konut.csv"), "name": "Konut", "measure_type": "stock"})
    assert r.content.startswith("EKLENDİ"), r.content
    assert _flag(runner.calls[-1][0], "--unit") in ("milyon TL", "TRY_mn") and "birim kaynaktan alındı" in r.content
    # Kaynak sessizse yine sorulur; tahmin yazılmaz.
    sessiz = "Tarih;deger\n31.01.2025;1.234,5\n28.02.2025;1.300,0\n31.03.2025;1.402,75\n30.04.2025;1.450,1\n31.05.2025;1.500,0\n30.06.2025;1.560,9\n"
    tool2, runner2, incoming2 = _tool(tmp_path / "b", "sessiz.csv dosyasını taslak olarak kaydet; ölçüm tipi stok", {"sessiz.csv": sessiz})
    r2 = tool2.validate_and_run({"locator": str(incoming2 / "sessiz.csv"), "name": "Sessiz", "measure_type": "stock"})
    assert r2.content.startswith("EKLENMEDİ") and "birim" in r2.content and not runner2.calls
