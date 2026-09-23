"""İlgi kapısı (V3 §3.9, builder/relevance.py) — yanlış dosya, doğru + yanlış dosya, yıl uyuşmazlığı.

Ölçülen garantiler: biçimi düzgün ama konusu ilgisiz dosya YAZILMAZ ve sorulur; soruda yıl
geçiyorsa dosyanın aralığı denetlenir; alias ("enflasyon" ↔ "TÜFE") kapıyı geçirir; soruda
içerik sözcüğü yoksa kapı sessizdir; kullanıcı "yine de ekle" derse geçilir ama modelin
bayrağı tek başına yetmez; aynı oturumda bakılan iki dosyadan daha uygun olanı kart söyler.
Dosya okuma yaması: Windows sürücü harfi `read.py`'de şema sanıldığı için (bilinen taşınabilirlik
hatası) okuma fonksiyonu sahte DataFrame'lerle değiştirildi; kapı bundan bağımsız.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.builder.ingest import LakehouseCLI  # noqa: E402
from kkb_agent.builder.profile import profile_table, propose  # noqa: E402
from kkb_agent.builder.relevance import CatalogEntry, assess, content_terms, years_in  # noqa: E402
from kkb_agent.tools import ingest as ingest_mod  # noqa: E402
from kkb_agent.tools.ingest import IngestFromUrlTool  # noqa: E402


def _frame(header: str, rows: list[str]) -> pd.DataFrame:
    cols = header.split(";")
    return pd.DataFrame([r.split(";") for r in rows], columns=cols, dtype=str)


KONUT_2025 = _frame("Tarih;Konut Kredisi (milyon TL)",
                    ["31.01.2025;1.234,5", "28.02.2025;1.300,0", "31.03.2025;1.402,75",
                     "30.04.2025;1.450,1", "31.05.2025;1.500,0", "30.06.2025;1.560,9"])
OTOBUS = _frame("Tarih;Sefer Sayısı",
                ["31.01.2025;120", "28.02.2025;118", "31.03.2025;125",
                 "30.04.2025;130", "31.05.2025;128", "30.06.2025;131"])
TUFE_2025 = _frame("Tarih;TÜFE Genel Endeks",
                   ["31.01.2025;1.000,0", "28.02.2025;1.030,0", "31.03.2025;1.060,0",
                    "30.04.2025;1.090,0", "31.05.2025;1.120,0", "30.06.2025;1.150,0"])


def _mapping(frame: pd.DataFrame, key: str = "x"):
    mapping, _ = propose(profile_table(frame), frame, series_id=f"adhoc:{key}")
    assert mapping is not None
    return mapping


# ----------------------------------------------------------------- saf fonksiyon
def test_icerik_sozcukleri_durak_sozcukleri_atar_ve_kokler() -> None:
    t = content_terms("Bu dosyayı ekle ve 2025 konut kredilerinin aylık değişimini göster")
    assert "konut" in t and "kredi" in t
    assert not ({"dosya", "ekle", "aylık", "değişim", "göster"} & t)
    assert years_in("2021–2025 arası, 2019 hariç") == {2021, 2025, 2019}


def test_ilgili_dosya_gecer_puan_tam() -> None:
    r = assess("2025 konut kredisi bakiyesini aylık göster", "", "konut.csv", KONUT_2025, _mapping(KONUT_2025))
    assert not r.irrelevant and r.period_ok is True and "konut" in r.term_hits
    assert r.score == r.applicable == 2  # dönem + terim (katalog yok → uygulanmadı)


def test_alakasiz_dosya_puan_sifir() -> None:
    r = assess("2025 konut kredisi bakiyesini aylık göster", "", "otobus_tarifesi.csv", OTOBUS, _mapping(OTOBUS))
    assert r.period_ok is True             # tarih aralığı tutuyor ama
    assert r.term_hits == ()               # konu tutmuyor
    assert not r.irrelevant and r.score == 1  # tek ölçüt tuttuğu için geçer; kart puanı yazar


def test_yil_uyusmazligi_ve_konu_uyusmazligi_birlikte_alakasiz() -> None:
    r = assess("2024 konut kredisi", "", "otobus.csv", OTOBUS, _mapping(OTOBUS))
    assert r.period_ok is False and r.term_hits == () and r.irrelevant


def test_konu_uyusmazligi_yil_yokken_alakasiz() -> None:
    r = assess("konut kredisi bakiyesini göster", "", "otobus.csv", OTOBUS, _mapping(OTOBUS))
    assert r.period_ok is None and r.applicable == 1 and r.irrelevant


def test_katalog_aliasi_enflasyon_tufe_kapiyi_gecirir() -> None:
    cat = [CatalogEntry("evds:tufe", "TÜFE genel endeks", ("enflasyon", "tüketici fiyatları"))]
    r_no = assess("2025 enflasyonu ekle", "", "fiyat.csv", TUFE_2025, _mapping(TUFE_2025))
    assert r_no.term_hits == ()  # "enflasyon" başlıkta yok
    r = assess("2025 enflasyonu ekle", "", "fiyat.csv", TUFE_2025, _mapping(TUFE_2025), catalog=cat)
    assert r.catalog_hits == ("TÜFE genel endeks",) and not r.irrelevant


def test_icerik_sozcugu_yoksa_kapi_sessiz() -> None:
    r = assess("bunu ekle", "bunu ekle", "otobus.csv", OTOBUS, _mapping(OTOBUS))
    assert r.applicable == 0 and not r.irrelevant


# ----------------------------------------------------------------- araç içinde
class SpyLakehouse:
    def __init__(self) -> None:
        self.events: list[str] = []

    def list_datasets(self):
        return []

    def close(self) -> None:
        self.events.append("close")

    def reload(self) -> None:
        self.events.append("reload")


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], cwd: Path) -> tuple[int, str, str]:
        self.calls.append(cmd)
        return 0, ("status: success\nsource_id: adhoc\ndataset_id: adhoc_x\nrun_id: r1\n"
                   "artifact_sha256: " + "ab" * 32 + "\nbronze_path: b.parquet\nseries_id: adhoc:x\n"
                   "rows_written: 6\nrows_unchanged: 0\n"), ""


@pytest.fixture
def tool_env(tmp_path: Path, monkeypatch):
    core = tmp_path / "lakehouse-core" / "src" / "lakehouse"
    core.mkdir(parents=True); (core / "cli.py").write_text("# sahte", encoding="utf-8")
    incoming = tmp_path / "incoming"; incoming.mkdir()
    runner = FakeRunner()
    cli = LakehouseCLI(core_dir=tmp_path / "lakehouse-core", database=tmp_path / "lh.duckdb",
                       data_root=tmp_path, runner=runner)
    lake = SpyLakehouse()
    registry = SimpleNamespace(active_question="", user_text="", sanctioned_locators=set())
    tool = IngestFromUrlTool(lake, cli, allowed_root=incoming, registry=registry)

    frames = {"konut.csv": KONUT_2025, "otobus.csv": OTOBUS}

    def fake_read(locator, *, allowed_roots, session=None, sheet=None):
        from kkb_agent.contracts.access import AccessOutcome
        return frames[Path(locator).name], AccessOutcome(status="ok", source=locator, message="okundu")

    monkeypatch.setattr(ingest_mod, "read_table_for_profiling", fake_read)
    return tool, lake, runner, registry


def test_alakasiz_dosya_yazilmaz_ve_sorulur(tool_env) -> None:
    tool, lake, runner, reg = tool_env
    reg.user_text = "otobus.csv dosyasını ekle; 2024 konut kredisi bakiyesini göster"
    reg.active_question = "2024 konut kredisi bakiyesini göster"

    r = tool.validate_and_run({"locator": "otobus.csv", "name": "x"})

    assert not r.ok and r.error.error_code == "FILE_IRRELEVANT" and not r.error.is_retryable
    assert runner.calls == [] and lake.events == []          # CLI hiç çağrılmadı, okuyucu kapanmadı
    # 15 Eyl: ret kararını uygunluk kapısı verir (core/fitness); kart dosyada NE olduğunu söyler.
    assert "dönem: soru 2024 istiyor" in r.content and "Sefer Sayısı" in r.content
    assert "user_confirmed=true" in r.content


def test_model_bayragi_tek_basina_yetmez_kullanici_onayi_gerekir(tool_env) -> None:
    tool, lake, runner, reg = tool_env
    reg.user_text = "otobus.csv dosyasını ekle; 2024 konut kredisi"
    reg.active_question = "2024 konut kredisi"
    r = tool.validate_and_run({"locator": "otobus.csv", "name": "x", "user_confirmed": True})
    assert not r.ok and r.error.error_code == "FILE_IRRELEVANT" and runner.calls == []

    reg.user_text += " — evet doğru dosya bu, yine de ekle"
    r2 = tool.validate_and_run({"locator": "otobus.csv", "name": "x", "user_confirmed": True})
    assert r2.ok, r2.content
    assert len(runner.calls) == 1 and "kullanıcı onayıyla eklendi" in r2.content


def test_dogru_ve_yanlis_dosya_birlikte_kart_daha_uygun_olani_soyler(tool_env) -> None:
    tool, lake, runner, reg = tool_env
    reg.user_text = "konut.csv ve otobus.csv dosyalarını ekle; 2025 konut kredisi bakiyesini aylık göster"
    reg.active_question = "2025 konut kredisi bakiyesini aylık göster"

    r1 = tool.validate_and_run({"locator": "konut.csv", "name": "konut"})
    assert r1.ok and "ilgi puanı: 2/2" in r1.content

    r2 = tool.validate_and_run({"locator": "otobus.csv", "name": "otobüs"})
    # 15 Eyl (uygunluk kapısı): yıl tutsa da soru konut/kredi/bakiye istiyor, dosyada hiçbiri yok → yazılmaz;
    # hata ipucu aynı oturumda bakılan daha uygun dosyayı adıyla söyler. (13 Eyl ilgi kapısı yıl tuttuğu için yazıyordu.)
    assert not r2.ok and r2.error.error_code == "FILE_IRRELEVANT"
    assert "hiçbiri yok" in r2.content and "konut.csv" in r2.content and "daha uygun" in r2.content.lower()


def test_adressiz_istekte_tahmin_edilen_adres_soruya_donusur(tool_env) -> None:
    """23 Eyl (TEFAS): kullanıcı yalnız sayfa adı yazdı, model adres uydurdu; cevap 'niyet eksikliği' değil 'adres ver' olmalı."""
    tool, lake, runner, reg = tool_env
    reg.user_text = "TEFAS İstatistikleri altındaki Toplam İşlem Hacmi Raporundan aylık işlem hacmini lakehouse'a ekle"
    reg.active_question = reg.user_text
    r = tool.validate_and_run({"locator": "https://tefas.gov.tr/tefas-istatistikleri", "name": "TEFAS işlem hacmi"})
    assert not r.ok and r.error.error_code == "INTENT_REQUIRED" and runner.calls == []
    assert "tahmin" in r.content and "adres" in r.content.lower() and "dosya" in r.content.lower()

