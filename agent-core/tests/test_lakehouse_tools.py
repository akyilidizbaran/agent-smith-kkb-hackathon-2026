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


def test_varlik_pivotu_frekans_donusumu_degildir_where_filtresi_kutu_sayilmaz() -> None:
    """Boş katalog provası (22 Eyl): iki ülkeyi aynı tarih taneli satırda yan yana koyan pivot GOLD_REQUIRED yedi."""
    from kkb_agent.tools.lakehouse import LakehouseQueryTool

    class Lake:
        def get_dataset(self, *a, **k):
            raise LookupError

    tool = LakehouseQueryTool(Lake(), AnalysisWorkspace(), None, gold_available=True)
    pivot = ("SELECT observation_date, MAX(CASE WHEN entity_id='Germany' THEN value END) AS almanya, "
             "MAX(CASE WHEN entity_id='Turkiye' THEN value END) AS turkiye FROM silver.fact_observation "
             "WHERE series_id='adhoc:nufus' AND EXTRACT(year FROM observation_date) BETWEEN 2000 AND 2020 GROUP BY observation_date")
    assert not tool._is_period_aggregation(pivot)
    assert tool._is_period_aggregation("SELECT strftime(observation_date, '%Y-%m') AS ay, AVG(value) FROM t GROUP BY 1")
    assert tool._is_period_aggregation("SELECT EXTRACT(year FROM observation_date) AS y, SUM(value) FROM t GROUP BY EXTRACT(year FROM observation_date)")


def test_distinct_degerler_seri_kimligini_tablo_adi_sanmaz() -> None:
    """Boş katalog provası (22 Eyl): 'adhoc:dunya_nufus' FROM'a yazılınca 'Table … does not exist'; adaptörün kapsamı kullanılır."""
    import pandas as pd
    from types import SimpleNamespace
    from kkb_agent.tools.lakehouse import LakehouseDistinctValuesTool

    class Lake:
        def __init__(self):
            self.sql: list[str] = []

        def get_dataset(self, dataset_id):
            return SimpleNamespace(dataset_id=dataset_id, columns=[SimpleNamespace(name="entity_id"), SimpleNamespace(name="value")],
                                   column=lambda name: SimpleNamespace(name=name) if name in ("entity_id", "value") else None)

        def series_scope(self, dataset_id):
            return "silver.fact_observation", "series_id = '" + dataset_id + "'"

        def execute_sql(self, sql):
            self.sql.append(sql)
            data = pd.DataFrame({"n": [2]}) if "COUNT(DISTINCT" in sql else pd.DataFrame({"entity_id": ["Germany", "Turkiye"]})
            return SimpleNamespace(is_empty=False, data=data)

    lake = Lake()
    r = LakehouseDistinctValuesTool(lake).validate_and_run({"dataset_id": "adhoc:nufus", "column": "entity_id", "limit": 5})
    assert r.ok and "Germany" in r.content and "Turkiye" in r.content, r.content
    assert lake.sql[0].startswith("SELECT DISTINCT entity_id FROM silver.fact_observation WHERE series_id = 'adhoc:nufus'"), lake.sql[0]


def test_distinct_degerler_aksana_ve_buyuk_kucuk_harfe_duyarsiz_arar() -> None:
    """Boş katalog provası (22 Eyl): kullanıcı "Türkiye" yazdı, kaynak "Turkiye" tutuyor; ILIKE bulamadı."""
    import pandas as pd
    from types import SimpleNamespace
    from kkb_agent.tools.lakehouse import LakehouseDistinctValuesTool

    class Lake:
        def __init__(self):
            self.sql: list[str] = []

        def get_dataset(self, dataset_id):
            return SimpleNamespace(dataset_id=dataset_id, columns=[SimpleNamespace(name="entity_id")],
                                   column=lambda name: SimpleNamespace(name=name) if name == "entity_id" else None)

        def series_scope(self, dataset_id):
            return "silver.fact_observation", "series_id = '" + dataset_id + "'"

        def execute_sql(self, sql):
            self.sql.append(sql)
            data = pd.DataFrame({"n": [1]}) if "COUNT(DISTINCT" in sql else pd.DataFrame({"entity_id": ["Turkiye"]})
            return SimpleNamespace(is_empty=False, data=data)

    lake = Lake()
    r = LakehouseDistinctValuesTool(lake).validate_and_run({"dataset_id": "adhoc:nufus", "column": "entity_id", "contains": "Türkiye", "limit": 5})
    assert r.ok and "Turkiye" in r.content
    assert "strip_accents(lower(entity_id)) LIKE '%' || strip_accents(lower('Türkiye')) || '%'" in lake.sql[0], lake.sql[0]
