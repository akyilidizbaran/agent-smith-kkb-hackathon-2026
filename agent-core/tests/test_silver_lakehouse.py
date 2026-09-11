"""Veri ekibinin Silver şemasına bağlanan adaptör.

Bu testler `lakehouse-core` paketini import ETMEZ; yalnızca onların DDL'iyle
kurulmuş iki tabloya karşı koşar. Gerçek veritabanı geldiğinde aynı testler
ona karşı da koşabilir — şema varsayımlarımızın kaydı budur.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.adapters.silver_lakehouse import SilverLakehouse  # noqa: E402
from kkb_agent.contracts.catalog import CumulativeKind, Frequency, SemanticType  # noqa: E402
from kkb_agent.contracts.lakehouse import LakehouseClient, LakehouseError  # noqa: E402

DDL = """
CREATE SCHEMA meta; CREATE SCHEMA silver;
CREATE TABLE meta.series (
    series_id VARCHAR PRIMARY KEY, source_id VARCHAR, native_code VARCHAR,
    dataset_id VARCHAR, name_tr VARCHAR, description VARCHAR,
    aliases VARCHAR[], tags VARCHAR[], frequency VARCHAR, week_anchor VARCHAR,
    unit VARCHAR, measure_type VARCHAR, default_agg VARCHAR, cumulative_reset VARCHAR,
    semantic_confidence VARCHAR, semantic_source VARCHAR,
    first_obs DATE, last_obs DATE, metadata_url VARCHAR, status VARCHAR);
CREATE TABLE silver.fact_observation (
    series_id VARCHAR, entity_id VARCHAR, observation_date DATE,
    period_start DATE, period_end DATE, value DOUBLE,
    frequency VARCHAR, unit VARCHAR, measure_type VARCHAR, quality_flag VARCHAR,
    source_id VARCHAR, dataset_id VARCHAR, artifact_sha256 VARCHAR,
    fetched_at TIMESTAMPTZ, schema_version VARCHAR, vintage_id VARCHAR, run_id VARCHAR);
"""


def _series(con, sid, **kw):
    d = dict(source_id="bddk_monthly", native_code="x", dataset_id="ds", name_tr=sid,
             description="d", aliases=["konut kredisi"], tags=["kredi"], frequency="monthly",
             week_anchor=None, unit="TRY_mn", measure_type="stock", default_agg="last",
             cumulative_reset=None, semantic_confidence="verified", semantic_source="source_docs",
             first_obs=date(2025, 1, 31), last_obs=date(2025, 3, 31),
             metadata_url="https://x", status="active")
    d.update(kw)
    con.execute(
        "INSERT INTO meta.series VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [sid, *[d[k] for k in ("source_id", "native_code", "dataset_id", "name_tr",
                               "description", "aliases", "tags", "frequency", "week_anchor",
                               "unit", "measure_type", "default_agg", "cumulative_reset",
                               "semantic_confidence", "semantic_source", "first_obs",
                               "last_obs", "metadata_url", "status")]],
    )


def _obs(con, sid, d, v, flag="ok", unit="TRY_mn", mt="stock"):
    con.execute(
        "INSERT INTO silver.fact_observation VALUES (?,NULL,?,NULL,?,?,'monthly',?,?,?,"
        "'bddk_monthly','ds','sha',now(),'v1','vin','run')",
        [sid, d, d, v, unit, mt, flag],
    )


@pytest.fixture
def lake(tmp_path: Path) -> SilverLakehouse:
    db = tmp_path / "lh.duckdb"
    con = duckdb.connect(str(db))
    con.execute(DDL)
    _series(con, "bddk_monthly:konut", aliases=["konut kredisi", "mortgage"], name_tr="Konut Kredisi")
    _series(con, "evds:TP.KTF12", unit="pct", measure_type="rate", default_agg="avg",
            frequency="weekly", week_anchor="friday", aliases=["konut kredisi faizi"],
            name_tr="Konut Faizi")
    _series(con, "evds:TP.KFE.TR", unit="index", measure_type="index",
            semantic_confidence="derived", aliases=["konut fiyat endeksi"], name_tr="KFE")
    # Katalogda tanımlı, tek gözlemi yok: veri ekibinin gerçek veritabanında 1620 serinin
    # 1605'i bu durumda. Adaptörün bunu ayrı bir durum olarak ele alması test ediliyor.
    _series(con, "evds:TP.HENUZ.CEKILMEDI", aliases=["taşıt kredisi"],
            name_tr="Taşıt Kredisi (henüz çekilmedi)")
    for i, v in enumerate([100.0, 110.0, 121.0], start=1):
        _obs(con, "bddk_monthly:konut", date(2025, i, 28), v)
    for i, v in enumerate([42.1, 41.8, 41.5], start=1):
        _obs(con, "evds:TP.KTF12", date(2025, i, 28), v, unit="pct", mt="rate")
    _obs(con, "evds:TP.KFE.TR", date(2025, 1, 31), 1842.3, unit="index", mt="index")
    _obs(con, "evds:TP.KFE.TR", date(2025, 2, 28), None, flag="missing_value",
         unit="index", mt="index")
    con.close()
    return SilverLakehouse(db)


def test_protokolu_karsilar(lake: SilverLakehouse) -> None:
    assert isinstance(lake, LakehouseClient)


def test_yalnizca_gozlemi_olan_seri_katalogda(lake: SilverLakehouse) -> None:
    """Katalogda dört seri var, üçünde gözlem var; modele gidecek olan o üçü.

    Veri ekibinin gerçek veritabanında bu oran 1620'ye 15: `meta.series` "hangi serinin
    anlamı kayıtlı" sorusunu yanıtlıyor, "hangi serinin verisi var" sorusunu değil.
    Sorgulanamayan seriyi kataloğa koymak, modele üzerinden cevap üretemeyeceği bir tablo
    göstermek demektir.
    """
    ids = {s.dataset_id for s in lake.list_datasets()}
    assert ids == {"bddk_monthly:konut", "evds:TP.KTF12", "evds:TP.KFE.TR"}
    assert "evds:TP.HENUZ.CEKILMEDI" not in ids


def test_yuklenmemis_seri_yok_sayilmaz_ayri_sebeple_reddedilir(
    lake: SilverLakehouse,
) -> None:
    """'Böyle bir seri yok' ile 'verisi yok' aynı cevap değildir.

    Jüri katalogda olup henüz çekilmemiş bir seriyi sorduğunda doğru cevap "bilmiyorum"
    değil, "bu seri tanımlı fakat verisi yüklenmemiş"tir. İkisini tek hataya indirgersek
    o ayrımı söyleyemeyiz.
    """
    with pytest.raises(LakehouseError, match="henüz hiç gözlem yüklenmemiş"):
        lake.get_dataset("evds:TP.HENUZ.CEKILMEDI")

    with pytest.raises(LakehouseError, match="bulunamadı"):
        lake.get_dataset("evds:BOYLE.BIR.SERI.YOK")


def test_eslesme_yoksa_arama_alakasiz_tablo_dondurmez(lake: SilverLakehouse) -> None:
    """Boş sonuç, yanlış sonuçtan iyidir.

    Skorlama hiçbir şey bulmadığında eskiden kataloğun ilk N serisi dönüyordu. Dört
    tablolu bir seed'de zararsızdı; 1620 serilik katalogda modele alakasız bir tablo
    verip ondan cevap üretmeye davet ediyor.
    """
    assert lake.search_datasets("kuantum kromodinamiği") == []


def test_measure_type_ve_birim_cevrilir(lake: SilverLakehouse) -> None:
    """Onların tek enum'u bizim SemanticType + CumulativeKind ikilisine çevrilmeli."""
    v = lake.get_dataset("bddk_monthly:konut").column("value")
    assert v.semantic_type is SemanticType.STOCK
    assert v.cumulative is CumulativeKind.NONE
    assert v.unit == "milyon TL" and v.unit_multiplier == 1_000_000.0

    faiz = lake.get_dataset("evds:TP.KTF12")
    assert faiz.column("value").semantic_type is SemanticType.RATE
    assert faiz.column("value").unit == "yüzde"
    assert faiz.frequency is Frequency.WEEKLY


def test_ytd_kumulatiflik_cevrilir(tmp_path: Path) -> None:
    db = tmp_path / "c.duckdb"
    con = duckdb.connect(str(db)); con.execute(DDL)
    _series(con, "x:ytd", measure_type="flow_ytd", cumulative_reset="yearly")
    _obs(con, "x:ytd", date(2025, 1, 31), 1.0)
    con.close()
    v = SilverLakehouse(db).get_dataset("x:ytd").column("value")
    assert v.semantic_type is SemanticType.FLOW
    assert v.cumulative is CumulativeKind.YTD


def test_dogrulanmamis_seri_uyari_tasir(lake: SilverLakehouse) -> None:
    """derived/unknown seride otomatik dönüşüm yapılmamalı; uyarı modele ulaşmalı."""
    kfe = lake.get_dataset("evds:TP.KFE.TR")
    assert any("DOĞRULANMAMIŞ" in n for n in kfe.notes)
    assert "evds:TP.KFE.TR" in lake.health()["unverified_series"]
    verified = lake.get_dataset("bddk_monthly:konut")
    assert not any("DOĞRULANMAMIŞ" in n for n in verified.notes)


def test_kapsam_katalogdan_gelir(lake: SilverLakehouse) -> None:
    """Halüsinasyon koruması buna bağlı: kapsam dışı dönem reddedilebilmeli."""
    cov = lake.get_dataset("bddk_monthly:konut").coverage
    assert cov.start == date(2025, 1, 31) and cov.end == date(2025, 3, 31)
    assert cov.row_count == 3


def test_arama_aliaslari_agirliklandirir(lake: SilverLakehouse) -> None:
    assert lake.search_datasets("mortgage")[0].dataset_id == "bddk_monthly:konut"
    assert lake.search_datasets("konut fiyat endeksi")[0].dataset_id == "evds:TP.KFE.TR"


def test_sorgu_calisir_ve_provenance_tasir(lake: SilverLakehouse) -> None:
    r = lake.execute_sql(
        "SELECT observation_date, value FROM silver.fact_observation "
        "WHERE series_id = 'bddk_monthly:konut' ORDER BY observation_date"
    )
    assert len(r.data) == 3
    assert r.provenance.dataset_ids == ["bddk_monthly:konut"]
    assert r.provenance.sources and "bddk_monthly" in r.provenance.sources[0]


def test_quality_flag_uyari_olarak_bildirilir(lake: SilverLakehouse) -> None:
    """Kaynak uyarılı satır sessizce geçmemeli — güven katmanı."""
    r = lake.execute_sql(
        "SELECT observation_date, value, quality_flag FROM silver.fact_observation "
        "WHERE series_id = 'evds:TP.KFE.TR'"
    )
    assert any("quality_flag" in w for w in r.provenance.warnings)


def test_guvenlik_sinirlari_korunur(lake: SilverLakehouse) -> None:
    """Adaptör değişti diye guard'lar düşmemeli (ADR-0020)."""
    for sql in ("SELECT 1; SELECT 2",
                "SELECT * FROM read_csv_auto('/etc/passwd')",
                "DROP TABLE silver.fact_observation"):
        with pytest.raises(LakehouseError):
            lake.execute_sql(sql)
    s = lambda n: lake._con.execute("SELECT current_setting(?)", [n]).fetchone()[0]
    assert s("access_mode") == "read_only"
    assert s("enable_external_access") is False and s("lock_configuration") is True


def test_eksik_iliski_erken_yakalanir(tmp_path: Path) -> None:
    db = tmp_path / "bos.duckdb"
    duckdb.connect(str(db)).close()
    with pytest.raises(LakehouseError, match="meta.series"):
        SilverLakehouse(db)
