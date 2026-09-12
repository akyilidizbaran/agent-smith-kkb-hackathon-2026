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


def test_arama_kimligin_tablo_adi_olmadigini_soyluyor(lake: SilverLakehouse) -> None:
    """Silver'da `dataset_id` bir tablo adı değil; arama çıktısı bunu söylemek zorunda.

    Ölçüm (Büşra'nın 11 Eylül karşılaştırması, Silver şeması): motorumuzdaki 33 araç
    hatasının 21'i tek kök nedenden geliyordu — model `FROM bddk_monthly:konut_toplam`
    yazıyordu. Kalıp `lakehouse_describe` çıktısında zaten vardı, ama model önce arama
    yapıyor ve arama çıktısı kimliği "tablo" diye sunup fiziksel erişimden hiç söz
    etmiyordu. Kalıbı adaptör üretiyor (ADR-0024 `series_sql`), araç metin kurmuyor:
    verilen şey kopyalanıp çalıştırılabilir SQL, tarif değil.
    """
    from kkb_agent.tools.lakehouse import LakehouseSearchTool

    out = LakehouseSearchTool(lake).run(
        LakehouseSearchTool.Params(query="konut kredisi")
    ).content

    assert "bir tablo adı DEĞİL" in out
    assert "FROM silver.fact_observation WHERE series_id = 'bddk_monthly:konut'" in out


def test_kimlik_zaten_tablo_adiysa_ipucu_verilmez(tmp_path: Path) -> None:
    """Seed adaptöründe `dataset_id` gerçekten tablo adı; orada aynı satır gürültü olur.

    Bu, ipucunun tahminle değil ölçümle verildiğinin kanıtı: araç kimliğin tablo olup
    olmadığını varsaymıyor, adaptörün ürettiği SQL'de `FROM <dataset_id>` geçip
    geçmediğine bakıyor.
    """
    from kkb_agent.adapters.duckdb_lakehouse import DuckDBLakehouse
    from kkb_agent.tools.lakehouse import LakehouseSearchTool

    seed = Path("data/lakehouse.duckdb")
    if not seed.is_file():
        pytest.skip("seed veritabanı yok (scripts/dev_seed.py)")
    lake = DuckDBLakehouse(seed)

    out = LakehouseSearchTool(lake).run(
        LakehouseSearchTool.Params(query="konut kredisi")
    ).content

    assert "bir tablo adı DEĞİL" not in out


def test_ayni_adaptor_es_zamanli_sorgulari_kaldirir(lake: SilverLakehouse) -> None:
    """Bir turda paralel çalışan okuma araçları tek bağlantıyı paylaşır.

    Ölçüldü: tek bir `DuckDBPyConnection`'ı dört iş parçacığından kullanınca 800
    sorgunun 2'si `TypeError: object of type 'NoneType' has no len()` ile düştü —
    sonuç kümesi çağıranın altından çekiliyor. Oran küçük ama hata biçimi kötü:
    SQL hatası gibi değil, harness'ın içinden gelen anlamsız bir tip hatası gibi
    görünüyor. Her sorgu artık kendi imlecinde çalışıyor.
    """
    import concurrent.futures as cf

    sql = (
        "SELECT count(*) AS n FROM silver.fact_observation "
        "WHERE series_id = 'bddk_monthly:konut'"
    )
    expected = lake.execute_sql(sql).data.iloc[0, 0]

    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        results = [f.result() for f in [pool.submit(lake.execute_sql, sql) for _ in range(200)]]

    assert all(r.data.iloc[0, 0] == expected for r in results)


ADHOC_DDL = """
CREATE SCHEMA adhoc;
CREATE TABLE adhoc.fact_observation AS SELECT * FROM silver.fact_observation WHERE 1=0;
"""


@pytest.fixture
def lake_with_draft(tmp_path: Path) -> SilverLakehouse:
    """Küratörlü bir seri + adhoc ilişkisinde yaşayan bir TASLAK seri."""
    db = tmp_path / "lh.duckdb"
    con = duckdb.connect(str(db))
    con.execute(DDL); con.execute(ADHOC_DDL)
    _series(con, "bddk_monthly:konut", aliases=["konut kredisi"], name_tr="Konut Kredisi")
    _series(con, "adhoc:juri_dosyasi", source_id="adhoc", dataset_id="adhoc_juri_dosyasi",
            semantic_confidence="derived", semantic_source="profiler", status="draft",
            aliases=["jüri dosyası"], name_tr="Jüri dosyası (taslak)")
    for i, v in enumerate([100.0, 110.0, 121.0], start=1):
        _obs(con, "bddk_monthly:konut", date(2025, i, 28), v)
    for i, v in enumerate([5.0, 6.0], start=1):
        con.execute(
            "INSERT INTO adhoc.fact_observation VALUES (?,NULL,?,NULL,?,?,'monthly','TRY_mn','stock','ok',"
            "'adhoc','adhoc_juri_dosyasi','sha',now(),'v1','vin','run')",
            ["adhoc:juri_dosyasi", date(2025, i, 28), date(2025, i, 28), v],
        )
    con.close()
    return SilverLakehouse(db)


def test_taslak_seri_ingestten_sonra_gorunur_ve_sorgulanir(lake_with_draft: SilverLakehouse) -> None:
    """Ölçülen açık: ingest başarılıydı ama Analist 'yeni: []' görüyordu — gözlemler adhoc'ta.

    Taslak seri katalogda görünür, notu taslak olduğunu söyler, fiziksel sorgusu ve
    preview'u adhoc ilişkisine gider; küratörlü seri Silver'da kalır.
    """
    lake = lake_with_draft
    ids = {s.dataset_id for s in lake.list_datasets()}
    assert ids == {"bddk_monthly:konut", "adhoc:juri_dosyasi"}

    draft = lake.get_dataset("adhoc:juri_dosyasi")
    assert any("TASLAK" in n for n in draft.notes)
    assert "adhoc.fact_observation" in draft.source_detail

    sql = lake.series_sql("adhoc:juri_dosyasi", key_column="observation_date", value_column="value")
    assert "FROM adhoc.fact_observation" in sql
    assert "FROM silver.fact_observation" in lake.series_sql(
        "bddk_monthly:konut", key_column="observation_date", value_column="value"
    )
    assert len(lake.preview("adhoc:juri_dosyasi").data) == 2
    assert lake.execute_sql(sql).data["value"].tolist() == [5.0, 6.0]

    h = lake.health()
    assert h["draft_series"] == 1 and h["adhoc_observations"] == 2


def test_adhoc_iliskisi_olmayan_veritabani_yine_yuklenir(lake: SilverLakehouse) -> None:
    """Seed/test veritabanlarında adhoc şeması yok; adaptör buna takılmamalı."""
    assert lake.health()["adhoc_observations"] == 0
    assert lake.health()["draft_series"] == 0


# ---------- Gold tabloları (ADR-0031) ----------

GOLD_DDL = """
CREATE SCHEMA gold;
CREATE TABLE meta.gold_build (
    build_id VARCHAR NOT NULL, metric_id VARCHAR NOT NULL, function VARCHAR NOT NULL,
    series_ids VARCHAR[] NOT NULL, target_frequency VARCHAR, name_tr VARCHAR NOT NULL,
    description VARCHAR NOT NULL, aliases VARCHAR[], tags VARCHAR[],
    allow_unverified_semantics BOOLEAN NOT NULL, status VARCHAR NOT NULL, row_count BIGINT,
    refusal_reason VARCHAR, refusal_message VARCHAR, catalog_content_sha256 VARCHAR NOT NULL,
    silver_fingerprint VARCHAR NOT NULL, silver_row_count BIGINT NOT NULL,
    is_current BOOLEAN NOT NULL, built_at TIMESTAMPTZ NOT NULL);
CREATE TABLE gold.konut_ceyreklik (
    series_id VARCHAR, entity_id VARCHAR, period_start DATE, period_end DATE, value DOUBLE,
    quality_flag VARCHAR, measure_type VARCHAR, unit VARCHAR, aggregation VARCHAR,
    source_frequency VARCHAR, target_frequency VARCHAR, observations INTEGER,
    missing_observations INTEGER, warned_observations INTEGER,
    source_observation_dates DATE[], artifact_sha256_list VARCHAR[], vintage_id_list VARCHAR[],
    run_id_list VARCHAR[], gold_metric_id VARCHAR, gold_function VARCHAR, gold_build_id VARCHAR,
    gold_built_at TIMESTAMPTZ, gold_catalog_content_sha256 VARCHAR, silver_fingerprint VARCHAR);
"""


def _gold_fixture(tmp_path: Path, *, stale: bool = False) -> SilverLakehouse:
    from kkb_agent.adapters.silver_lakehouse import SILVER_FINGERPRINT_SQL

    db = tmp_path / "lh.duckdb"
    con = duckdb.connect(str(db))
    con.execute(DDL); con.execute(GOLD_DDL)
    _series(con, "bddk_monthly:konut", aliases=["konut kredisi"], name_tr="Konut Kredisi")
    for i, v in enumerate([100.0, 110.0, 121.0], start=1):
        _obs(con, "bddk_monthly:konut", date(2025, i, 28), v)
    fp = con.execute(SILVER_FINGERPRINT_SQL).fetchone()[0]
    con.execute(
        "INSERT INTO gold.konut_ceyreklik VALUES ('bddk_monthly:konut', NULL, '2025-01-01', '2025-03-31', 121.0, 'ok',"
        " 'stock', 'TRY_mn', 'last', 'monthly', 'quarterly', 3, 0, 0, ['2025-01-28','2025-02-28','2025-03-28'],"
        " ['sha'], ['vin'], ['run'], 'konut_ceyreklik', 'align_frequency', 'b1', now(), 'c1', ?)", [fp],
    )
    con.execute(
        "INSERT INTO meta.gold_build VALUES ('b1', 'konut_ceyreklik', 'align_frequency', ['bddk_monthly:konut'],"
        " 'quarterly', 'Konut kredisi çeyreklik', 'Çeyrek sonu bakiyesi', ['çeyreklik konut kredisi'],"
        " ['gold'], false, 'built', 1, NULL, NULL, 'c1', ?, 3, true, now())", [fp],
    )
    # Defterde 'refused' olan metrik ve defterde olup diskte olmayan tablo listelenmez.
    con.execute(
        "INSERT INTO meta.gold_build VALUES ('b1', 'konut_akim', 'decompose_cumulative', ['bddk_monthly:konut'],"
        " NULL, 'x', 'y', [], [], false, 'refused', NULL, 'NOT_DECOMPOSABLE', 'stock', 'c2', ?, 3, true, now())", [fp],
    )
    con.execute(
        "INSERT INTO meta.gold_build VALUES ('b1', 'yarim_kalan', 'align_frequency', ['bddk_monthly:konut'],"
        " 'monthly', 'x', 'y', [], [], false, 'built', 1, NULL, NULL, 'c3', ?, 3, true, now())", [fp],
    )
    if stale:
        con.execute("UPDATE silver.fact_observation SET value = value + 1 WHERE observation_date = '2025-03-28'")
    con.close()
    return SilverLakehouse(db)


def test_kurulmus_gold_tablosu_defterden_dataset_olarak_gorunur(tmp_path: Path) -> None:
    lake = _gold_fixture(tmp_path)
    ids = {s.dataset_id for s in lake.list_datasets()}
    assert ids == {"bddk_monthly:konut", "gold.konut_ceyreklik"}  # refused ve yarım kalan yok

    spec = lake.get_dataset("gold.konut_ceyreklik")
    assert spec.source == "gold" and spec.time_column == "period_end"
    assert spec.frequency is Frequency.QUARTERLY
    value = next(c for c in spec.columns if c.name == "value")
    assert value.unit == "milyon TL" and value.unit_multiplier == 1_000_000.0
    assert value.semantic_type is SemanticType.STOCK and "çeyreklik konut kredisi" in value.aliases
    assert any(n.startswith("GOLD TABLOSU (align_frequency)") and "stok → dönemin son gözlemi" in n for n in spec.notes)
    assert not any("BAYAT" in n for n in spec.notes)
    assert spec.coverage.start == date(2025, 1, 1) and spec.coverage.end == date(2025, 3, 31)

    # Arama alias'tan bulur; kimlik gerçek tablo adı → SQL FROM'a yazılır, ipucu gerekmez.
    assert [s.dataset_id for s in lake.search_datasets("çeyreklik konut kredisi")][0] == "gold.konut_ceyreklik"
    sql = lake.series_sql("gold.konut_ceyreklik", key_column="period_end", value_column="value")
    assert sql == 'SELECT "period_end", "value" FROM gold.konut_ceyreklik ORDER BY "period_end"'
    assert lake.execute_sql(sql).data["value"].tolist() == [121.0]
    preview = lake.preview("gold.konut_ceyreklik")
    assert "artifact_sha256_list" not in preview.data.columns and "value" in preview.data.columns
    h = lake.health()
    assert h["gold_tables"] == 1 and h["stale_gold_tables"] == 0 and h["queryable_series"] == 1
    assert h["gold_run_available"] is False


def test_silver_degisince_gold_tablosu_bayat_diye_isaretlenir(tmp_path: Path) -> None:
    lake = _gold_fixture(tmp_path, stale=True)
    spec = lake.get_dataset("gold.konut_ceyreklik")
    assert any("BAYAT" in n for n in spec.notes)
    assert spec.coverage.known_gaps == ["BAYAT: Silver sonradan değişti"]
    assert lake.health()["stale_gold_tables"] == 1
    # Uyarı sorgu sonucuna da taşınır: model tabloyu bayat bilerek anlatır.
    r = lake.execute_sql("SELECT value FROM gold.konut_ceyreklik")
    assert any("BAYAT" in w for w in r.provenance.warnings)


def test_gold_defteri_olmayan_veritabani_yine_yuklenir(lake: SilverLakehouse) -> None:
    assert lake.health()["gold_tables"] == 0
    assert not any(s.dataset_id.startswith("gold.") for s in lake.list_datasets())


def test_gold_cagrisi_cli_yokken_anlasilir_sebeple_durur(lake: SilverLakehouse) -> None:
    with pytest.raises(LakehouseError, match="gold-run"):
        lake.gold_align("bddk_monthly:konut", "quarterly")
