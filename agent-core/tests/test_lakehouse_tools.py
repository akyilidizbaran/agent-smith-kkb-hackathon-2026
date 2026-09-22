"""Lakehouse araçlarının LLM'siz doğrulaması.

Buradaki testlerin varlık sebebi somut: kapsam kontrolünü ekledim ama `re`
import'unu unutmuştum. Araç sessizce hata döndürdü, model bunu "SQL hatası"
sanıp kullanıcıya hata ayıklama tavsiyesi yazdı. Kusuru ancak uçtan uca
koşarken, dakikalar sonra fark ettim. Bu sınıf hataları saniyeler içinde
yakalamak için araçların kendisi doğrudan test edilir.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.catalog import (  # noqa: E402
    ColumnRole,
    ColumnSpec,
    Coverage,
    DatasetSpec,
    Frequency,
)
from kkb_agent.contracts.lakehouse import QueryProvenance, QueryResult  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.lakehouse import LakehouseQueryTool  # noqa: E402

SPEC = DatasetSpec(
    dataset_id="test_tablo",
    name="Test",
    description="test",
    source="TEST",
    frequency=Frequency.MONTHLY,
    time_column="donem",
    grain=["donem"],
    columns=[
        ColumnSpec(name="donem", role=ColumnRole.TIME, dtype="DATE", description="dönem"),
        ColumnSpec(
            name="deger", role=ColumnRole.MEASURE, dtype="DOUBLE",
            description="değer", unit="milyon TL",
        ),
    ],
    coverage=Coverage(start=date(2021, 1, 1), end=date(2026, 6, 1)),
)


class StubLakehouse:
    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def list_datasets(self):
        return [SPEC]

    def get_dataset(self, dataset_id: str):
        return SPEC

    def execute_sql(self, sql: str, *, max_rows: int = 10_000):
        return QueryResult(
            data=self._df,
            provenance=QueryProvenance(sql=sql, dataset_ids=["test_tablo"], row_count=len(self._df)),
        )


@pytest.fixture
def empty_tool() -> LakehouseQueryTool:
    return LakehouseQueryTool(StubLakehouse(pd.DataFrame()), AnalysisWorkspace())


def test_kapsam_disi_donem_kesin_dille_bildirilir(empty_tool: LakehouseQueryTool) -> None:
    """Kapsam dışı sorgu 'tekrar dene' değil, 'bu veri yok' demeli.

    Ayrım kritik: 'filtreleri kontrol et' mesajı modeli denemeye devam ettirip
    adım limitini yakıyordu.
    """
    res = empty_tool.validate_and_run(
        {"sql": "SELECT * FROM test_tablo WHERE EXTRACT(year FROM donem) = 2015",
         "purpose": "kapsam dışı"}
    )
    assert res.ok
    assert "bulunmuyor" in res.content.lower()
    assert "2021-01-01" in res.content, "kullanıcıya mevcut aralık bildirilmeli"
    assert "başka sorgu deneme" in res.content.lower() or "sorgu deneme" in res.content.lower()


def test_kapsam_ici_bos_sonuc_filtreye_yonlendirir(empty_tool: LakehouseQueryTool) -> None:
    """Dönem kapsam içindeyse boş sonucun sebebi filtredir; model denemeye devam etmeli."""
    res = empty_tool.validate_and_run(
        {"sql": "SELECT * FROM test_tablo WHERE kalem = 'olmayan' AND donem >= '2025-01-01'",
         "purpose": "yanlış filtre"}
    )
    assert res.ok
    assert "bulunmuyor" not in res.content.lower()
    assert "distinct_values" in res.content


def test_kismi_kapsam_disi_engellemez(empty_tool: LakehouseQueryTool) -> None:
    """2020-2025 aralığı sorulduysa veri kısmen var; 'veri yok' denmemeli."""
    res = empty_tool.validate_and_run(
        {"sql": "SELECT * FROM test_tablo WHERE donem BETWEEN '2020-01-01' AND '2025-12-31'",
         "purpose": "kısmi kapsam"}
    )
    assert "bulunmuyor" not in res.content.lower()


def test_atlanan_donem_filtresi_bildirilir() -> None:
    """Soruda yıl geçip sorguda geçmiyorsa model uyarılmalı.

    Ölçülmüş hata modu: "2025 yılında ... aylık göster" sorusuna model dönem
    filtresiz sorgu üretti, tüm kapsam döndü ve üç golden vakası birden düştü.
    """

    class SahteRegistry:
        active_question = "2025 yılında konut kredisini aylık göster"

    df = pd.DataFrame({"donem": pd.to_datetime(["2021-01-01"] * 3), "deger": [1.0, 2.0, 3.0]})
    tool = LakehouseQueryTool(StubLakehouse(df), AnalysisWorkspace(), SahteRegistry())
    res = tool.validate_and_run(
        {"sql": "SELECT donem, deger FROM test_tablo", "purpose": "filtresiz"}
    )
    assert not res.ok, "uyarı yetmiyordu; sorgu reddedilmeli"
    assert "2025" in res.content and "dönem filtresi yok" in res.content


def test_donem_filtresi_varsa_uyarmaz() -> None:
    class SahteRegistry:
        active_question = "2025 yılında konut kredisini aylık göster"

    df = pd.DataFrame({"donem": pd.to_datetime(["2025-01-01"]), "deger": [1.0]})
    tool = LakehouseQueryTool(StubLakehouse(df), AnalysisWorkspace(), SahteRegistry())
    res = tool.validate_and_run(
        {"sql": "SELECT donem, deger FROM test_tablo WHERE donem >= '2025-01-01'",
         "purpose": "filtreli"}
    )
    assert res.ok and "dönem filtresi yok" not in res.content


def test_ic_ice_anchor_yillari_dis_pencere_filtresine_eklenmez() -> None:
    class SahteRegistry:
        active_question = ("2021-01 ile 2025-12 arasındaki 60 aylık dönemde "
                           "2022-2023 alt aralığını içeren verileri getir")

    df = pd.DataFrame({
        "donem": pd.date_range("2021-01-31", periods=60, freq="ME"),
        "deger": range(60),
    })
    tool = LakehouseQueryTool(StubLakehouse(df), AnalysisWorkspace(), SahteRegistry())
    res = tool.validate_and_run({
        "sql": "SELECT donem, deger FROM test_tablo WHERE EXTRACT(year FROM donem) BETWEEN 2021 AND 2025",
        "purpose": "60 aylık dış pencere",
    })
    assert res.ok and (res.error is None or res.error.error_code != "MISSING_PERIOD_FILTER")


def test_sonucta_birimler_bildirilir() -> None:
    """Model birim çevirisi yapmasın diye birim etiketi sonuca eklenir."""
    df = pd.DataFrame({"donem": pd.to_datetime(["2025-01-01"]), "deger": [42.0]})
    tool = LakehouseQueryTool(StubLakehouse(df), AnalysisWorkspace())
    res = tool.validate_and_run({"sql": "SELECT donem, deger FROM test_tablo", "purpose": "x"})
    assert res.ok
    assert "deger = milyon TL" in res.content


def test_basarili_sorgu_analiz_tablosunu_kurar() -> None:
    df = pd.DataFrame({"donem": pd.to_datetime(["2025-01-01"]), "deger": [42.0]})
    ws = AnalysisWorkspace()
    tool = LakehouseQueryTool(StubLakehouse(df), ws)
    tool.validate_and_run(
        {"sql": "SELECT donem, deger FROM test_tablo", "purpose": "ana sonuç",
         "as_active_table": True}
    )
    assert ws.has_table and len(ws.table) == 1


def test_aylik_pencere_yillik_anchor_satirlarina_indirgenemez() -> None:
    """60 aylık istek, yalnızca 2022 ve 2023 Aralık satırlarını kabul etmez."""

    class SahteRegistry:
        active_question = (
            "Türkiye ulusal örnek 60 aylık penceresinde kredi ve kart serilerini getir "
            "[Otomatik dönem sınırı: 2021-04 ile 2026-03 arasındaki 60 aylık pencereyi kullan]"
        )

    df = pd.DataFrame({
        "period_end": pd.to_datetime(["2022-12-31", "2023-12-31"]),
        "ihtiyac": [674.803, 983.284],
        "kart": [452.478, 1185.215],
    })
    ws = AnalysisWorkspace()
    tool = LakehouseQueryTool(StubLakehouse(df), ws, SahteRegistry())
    result = tool.validate_and_run({
        "sql": ("SELECT period_end, ihtiyac, kart FROM test_tablo "
                "WHERE period_end BETWEEN '2021-04-01' AND '2026-03-31'"),
        "purpose": "60 aylık BDDK aylık sonuç",
    })

    assert not result.ok
    assert result.error is not None
    assert result.error.error_code == "PERIOD_GRAIN_MISMATCH"
    assert result.error.is_retryable
    assert not ws.has_table


def test_aylik_pencere_tam_ay_sayisini_kabul_eder() -> None:
    class SahteRegistry:
        active_question = (
            "Örnek 60 aylık ulusal penceredeki verileri getir "
            "[Otomatik dönem sınırı: 2021-04 ile 2026-03 arasındaki 60 aylık pencereyi kullan]"
        )

    dates = pd.date_range("2021-04-30", periods=60, freq="ME")
    df = pd.DataFrame({"period_end": dates, "deger": range(60)})
    tool = LakehouseQueryTool(StubLakehouse(df), AnalysisWorkspace(), SahteRegistry())
    result = tool.validate_and_run({
        "sql": ("SELECT period_end, deger FROM test_tablo "
                "WHERE period_end BETWEEN '2021-04-01' AND '2026-03-31'"),
        "purpose": "60 aylık sonuç",
    })

    assert result.ok
    assert result.error is None


def test_secili_seri_pencereyi_kapsamiyorsa_sql_calismadan_reddedilir() -> None:
    """Kısa türetilmiş kart serisi, tam kapsama sahip doğrulanmış parent'ın yerine geçemez."""
    from types import SimpleNamespace

    def spec(dataset_id: str, name: str, start: date, *, confidence: str | None) -> DatasetSpec:
        return DatasetSpec(
            dataset_id=dataset_id,
            name=name,
            description="BDDK aylık ulusal toplam seri",
            source="bddk_monthly",
            frequency=Frequency.MONTHLY,
            time_column="period_end",
            grain=["period_end"],
            columns=[
                ColumnSpec(name="period_end", role=ColumnRole.TIME, dtype="DATE", description="dönem"),
                ColumnSpec(name="value", role=ColumnRole.MEASURE, dtype="DOUBLE", description="bakiye", unit="milyon TL"),
            ],
            coverage=Coverage(start=start, end=date(2026, 6, 30)),
            semantic_confidence=confidence,
        )

    need = spec("bddk_monthly:need", "Tüketici Kredileri - İhtiyaç, Toplam (Sektör)", date(2016, 1, 31), confidence="verified")
    bad_card = spec("bddk_monthly:bad_card", "Kredi Kartları (Krediler, Sektör)", date(2022, 1, 31), confidence="derived")
    good_card = spec("bddk_monthly:good_card", "Bireysel Kredi Kartları, Toplam (Sektör)", date(2016, 1, 31), confidence="verified")

    class Lake:
        def list_datasets(self):
            return [need, bad_card, good_card]

        def get_dataset(self, dataset_id: str):
            return next(item for item in self.list_datasets() if item.dataset_id == dataset_id)

        def execute_sql(self, sql: str, *, max_rows: int = 10_000):  # pragma: no cover - guard must stop before this
            raise AssertionError("kapsam hatasında SQL çalıştırılmamalı")

    registry = SimpleNamespace(
        active_question=(
            "2022-2023 yıllarını kapsayan 60 aylık dönemde Türkiye'deki ihtiyaç kredisi "
            "ve bireysel kredi kartı verilerini BDDK verilerinden getir. "
            "[Otomatik dönem sınırı: 2021-01 ile 2025-12 arasındaki 60 aylık pencereyi kullan]"
        )
    )
    workspace = AnalysisWorkspace()
    tool = LakehouseQueryTool(Lake(), workspace, registry)
    result = tool.validate_and_run({
        "sql": 'SELECT "period_end", "value" FROM "bddk_monthly:need" JOIN "bddk_monthly:bad_card" USING ("period_end")',
        "purpose": "60 aylık BDDK sonuç",
    })

    assert not result.ok
    assert result.error is not None
    assert result.error.error_code == "SERIES_COVERAGE_MISMATCH"
    assert result.error.is_retryable
    assert "bddk_monthly:good_card" in result.error.candidates
    assert not workspace.has_table


def test_compact_ay_araligi_disina_tasan_sonuc_reddedilir() -> None:
    class SahteRegistry:
        active_question = "Tüm serileri 202301–202412 döneminde aylık bazda aynı eksende hizala"

    dates = pd.date_range("2023-01-31", periods=24, freq="ME")
    # One extra month makes the result violate the explicit compact range.
    dates = dates.append(pd.DatetimeIndex([pd.Timestamp("2025-01-31")]))
    df = pd.DataFrame({"period_end": dates, "deger": range(len(dates))})
    tool = LakehouseQueryTool(StubLakehouse(df), AnalysisWorkspace(), SahteRegistry())
    result = tool.validate_and_run({
        "sql": ("SELECT period_end, deger FROM test_tablo "
                "WHERE period_end BETWEEN '2023-01-01' AND '2024-12-31'"),
        "purpose": "2023-01–2024-12 aylık sonuç",
    })

    assert not result.ok
    assert result.error is not None and result.error.error_code == "PERIOD_GRAIN_MISMATCH"
    assert "pencere dışı" in result.content


def test_aylik_pencere_60_sayiya_ulasip_ay_atlarsa_reddedilir() -> None:
    class SahteRegistry:
        active_question = (
            "2021-01 ile 2025-12 arasındaki 60 aylık dönemde verileri getir "
            "[Otomatik dönem sınırı: 2021-01 ile 2025-12 arasındaki 60 aylık pencereyi kullan]"
        )

    # 60 satır var, ancak bir ay eksik ve başka bir ay iki kez tekrarlanıyor.
    dates = list(pd.date_range("2021-01-31", periods=59, freq="ME"))
    dates.append(pd.Timestamp("2021-01-31"))
    df = pd.DataFrame({"period_end": dates, "deger": range(60)})
    tool = LakehouseQueryTool(StubLakehouse(df), AnalysisWorkspace(), SahteRegistry())
    result = tool.validate_and_run({
        "sql": ("SELECT period_end, deger FROM test_tablo "
                "WHERE period_end BETWEEN '2021-01-01' AND '2025-12-31'"),
        "purpose": "eksik aylı sonuç",
    })

    assert not result.ok
    assert result.error is not None and result.error.error_code == "PERIOD_GRAIN_MISMATCH"
    assert "eksik" in result.content


def _ay_araci(question: str) -> LakehouseQueryTool:
    """Kapsamı 2021-01 → 2026-06 olan tek serilik bir lakehouse üstünde sorgu aracı."""

    class _Registry:
        active_question = question

    stub = StubLakehouse(pd.DataFrame({"donem": [date(2026, 1, 31)], "deger": [1.0]}))
    return LakehouseQueryTool(stub, AnalysisWorkspace(), registry=_Registry())


def test_sorudaki_ay_kapsam_disiysa_sorgu_hic_calismaz() -> None:
    """Yıl kapsamda, ay değil: eski kontrol bu boşluğu görmüyordu.

    Veri 2026-06'da bitiyor. "2026 Ağustos kaç?" sorusunda 2026 kapsam içinde
    göründüğü için hiçbir şey tetiklenmiyor, model o yılın mevcut aylarını çekip
    tablo kuruyordu. Cevap metni doğru çıksa bile ekranda sayı dolu bir tablo
    kalıyor. Ölçüldü (L9-02): iki şemada da 0/3.
    """
    tool = _ay_araci("2026 Ağustos konut kredisi bakiyesi kaç?")

    # Kapsam kontrolü artık sınır doğrulayıcıda (check_policy); run doğrulanmış
    # parametre varsayar. Test, modelin gördüğü yolu izler: validate_and_run.
    result = tool.validate_and_run(
        {"sql": "SELECT donem, toplam FROM t WHERE EXTRACT(year FROM donem)=2026",
         "purpose": "2026 aylık"}
    )

    assert not result.ok
    assert result.error is not None and result.error.error_code == "OUT_OF_COVERAGE"
    assert not result.error.is_retryable, "tekrar denemek bu dönemi var etmez"
    assert not tool.workspace.has_table, "kapsam dışı soruya tablo kurulmamalı"


@pytest.mark.parametrize(
    "question",
    [
        "2026 Mart konut kredisi bakiyesi kaç?",   # kapsam içinde
        "2025 yılında aylık göster",               # ay yok, yalnız yıl
        "Konut kredisi bakiyesi nedir?",           # dönem yok
    ],
)
def test_kapsamdaki_ay_ve_donemsiz_sorular_engellenmez(question: str) -> None:
    """Kontrol yalnız hiçbir serinin veremeyeceği dönemde tetiklenmeli."""
    tool = _ay_araci(question)

    result = tool.validate_and_run(
        {"sql": "SELECT donem, toplam FROM t WHERE EXTRACT(year FROM donem)=2026", "purpose": "x"}
    )

    assert result.ok or (result.error and result.error.error_code != "OUT_OF_COVERAGE")



def test_arama_bos_donunce_yuklenmemis_seri_soylenir_ve_dongu_kirilir() -> None:
    """Ölçüldü: gerçek DB'de olmayan seri için model on kez aradı. Yüklenmemiş seri varsa
    ilk boş aramada, yoksa ikinci boş aramada tekrar denenmez hata döner."""
    from kkb_agent.tools.lakehouse import LakehouseSearchTool

    class Lake:
        def __init__(self, pending):
            self.pending = pending
        def search_datasets(self, query, limit=5):
            return []
        def search_uningested(self, query, limit=5):
            return self.pending

    tool = LakehouseSearchTool(Lake([("evds:TP.X", "Taşıt Kredisi")]))
    r = tool.validate_and_run({"query": "taşıt kredisi"})
    assert not r.ok and r.error.error_code == "DATASET_NOT_FOUND" and not r.error.is_retryable
    assert "HENÜZ YÜKLENMEMİŞ" in r.content and "evds:TP.X" in r.content and r.error.candidates == ["evds:TP.X"]

    tool2 = LakehouseSearchTool(Lake([]))
    first = tool2.validate_and_run({"query": "enflasyon"})
    assert first.ok and "EN FAZLA bir kez daha" in first.content
    second = tool2.validate_and_run({"query": "tüfe"})
    assert not second.ok and second.error.error_code == "DATASET_NOT_FOUND" and not second.error.is_retryable


def test_kismi_eslesen_aramalar_ikinci_kezde_durur() -> None:
    """G12 ölçümü: her isabet 'taşıt' sözcüğünü karşılamıyor ve taşıt yüklenmemiş serilerde varsa
    ikinci arama tekrar denenmez hata olur; model konutu taşıt diye kullanmaz."""
    from datetime import date as _d
    from kkb_agent.tools.lakehouse import LakehouseSearchTool

    spec = SPEC.model_copy(update={"dataset_id": "bddk_monthly:konut", "name": "Konut Kredisi"})

    class Lake:
        last_search_terms = {"bddk_monthly:konut": (["kredisi"], ["tasit"])}
        def search_datasets(self, query, limit=5):
            return [spec]
        def search_uningested(self, query, limit=5):
            return [("bddk_monthly:tasit", "Tüketici Kredileri - Taşıt")]
        def series_sql(self, *a, **k):
            return "SELECT donem, deger FROM test_tablo"

    tool = LakehouseSearchTool(Lake())
    first = tool.validate_and_run({"query": "taşıt kredisi"})
    assert first.ok and "EŞLEŞMEYEN: tasit" in first.content and "HENÜZ YÜKLENMEMİŞ" in first.content
    second = tool.validate_and_run({"query": "taşıt kredisi bakiyesi"})
    assert not second.ok and second.error.error_code == "DATASET_NOT_FOUND" and not second.error.is_retryable
    assert second.error.candidates == ["bddk_monthly:tasit"]



def test_gold_varken_donem_toplamasi_sqlde_reddedilir() -> None:
    """ADR-0039: ay/çeyrek kutusuna AVG/SUM alan sorgu Gold'a yönlendirilir; Gold yoksa serbest."""
    from kkb_agent.tools.lakehouse import LakehouseQueryTool

    class Lake:
        def get_dataset(self, *a, **k):
            raise LookupError

    sql = "SELECT strftime(observation_date, '%Y-%m') AS ay, AVG(value) FROM silver.fact_observation WHERE observation_date >= '1985-01-01' GROUP BY 1"
    with_gold = LakehouseQueryTool(Lake(), AnalysisWorkspace(), None, gold_available=True)
    r = with_gold.validate_and_run({"sql": sql, "purpose": "aylık ortalama"})
    assert not r.ok and r.error.error_code == "GOLD_REQUIRED" and r.error.is_retryable and "gold_align" in r.content

    plain = "SELECT observation_date, value FROM silver.fact_observation WHERE observation_date >= '1985-01-01'"
    assert with_gold.check_policy(with_gold.Params(sql=plain, purpose="x")) is None
    without = LakehouseQueryTool(Lake(), AnalysisWorkspace(), None, gold_available=False)
    assert without.check_policy(without.Params(sql=sql, purpose="x")) is None


def test_aylik_soruya_ceyreklik_tablo_okunmaz_incesi_serbest() -> None:
    """Ölçüldü (G16): model 'aylık ... büyüme hızı' sorusuna hazır çeyreklik Gold tablosunu okudu."""
    from datetime import date
    from types import SimpleNamespace
    from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency

    def spec(ds_id: str, freq: Frequency) -> DatasetSpec:
        return DatasetSpec(dataset_id=ds_id, name=ds_id, description="d", source="s", frequency=freq,
                           time_column="observation_date", grain=["observation_date"],
                           columns=[ColumnSpec(name="observation_date", role=ColumnRole.TIME, dtype="DATE", description="d"),
                                    ColumnSpec(name="value", role=ColumnRole.MEASURE, dtype="DOUBLE", description="v")],
                           coverage=Coverage(start=date(2021, 1, 31), end=date(2026, 6, 30)))

    aylik, ceyreklik, haftalik = spec("bddk_monthly:1534_Toplam", Frequency.MONTHLY), spec("gold.konut_kredisi_ceyreklik", Frequency.QUARTERLY), spec("bddk_weekly:5690_3", Frequency.WEEKLY)

    class Lake(StubLakehouse):
        def __init__(self): super().__init__(pd.DataFrame())
        def list_datasets(self): return [aylik, ceyreklik, haftalik]
        def search_datasets(self, q): return [ceyreklik, aylik, haftalik]

    def tool(question: str) -> LakehouseQueryTool:
        return LakehouseQueryTool(Lake(), AnalysisWorkspace(), SimpleNamespace(active_question=question, user_text=question, sanctioned_locators=set()))

    t = tool("Aylık konut kredisi bakiyesinin büyüme hızı 2021'den bu yana ne zaman rejim değiştirdi?")
    err = t.check_policy(t.Params(sql="SELECT period_end, value FROM gold.konut_kredisi_ceyreklik WHERE EXTRACT(year FROM period_end) >= 2021", purpose="x"))
    assert err is not None and err.error_code == "FREQUENCY_MISMATCH" and err.is_retryable
    assert "bddk_monthly:1534_Toplam" in err.candidates and "çeyreklik" in err.message
    # aylık seri okunuyorsa sorun yok
    assert t.check_policy(t.Params(sql="SELECT observation_date, value FROM silver.fact_observation WHERE series_id = 'bddk_monthly:1534_Toplam' AND observation_date >= '2021-01-01'", purpose="x")) is None
    # inceden kabaya serbest: aylık soruya haftalık seri (Gold'un işi), çeyreklik soruya aylık seri
    assert t.check_policy(t.Params(sql="SELECT * FROM silver.fact_observation WHERE series_id = 'bddk_weekly:5690_3' AND observation_date >= '2021-01-01'", purpose="x")) is None
    t2 = tool("Çeyreklik konut kredisi bakiyesi 2021'den bu yana")
    assert t2.check_policy(t2.Params(sql="SELECT * FROM silver.fact_observation WHERE series_id = 'bddk_monthly:1534_Toplam' AND observation_date >= '2021-01-01'", purpose="x")) is None
    # iki frekans sözcüğü: guard susar
    t3 = tool("Haftalık faizi aylık göster, 2021'den bu yana")
    assert t3.check_policy(t3.Params(sql="SELECT * FROM gold.konut_kredisi_ceyreklik WHERE period_end >= '2021-01-01'", purpose="x")) is None
