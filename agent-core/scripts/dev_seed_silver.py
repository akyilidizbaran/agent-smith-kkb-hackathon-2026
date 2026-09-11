"""Geliştirme seed'i — veri ekibinin Silver şemasında.

DİKKAT: Bu üretim ingestion'ı değildir. Veri ekibinin `lakehouse-core` boru hattı
gerçek veriyi üretecek; bu script yalnızca agent tarafının onların ŞEMASINA karşı
geliştirilip test edilebilmesi için aynı yapıyı kendi BDDK seed'imizden kurar.

Neden gerekli: `feature/generic-adhoc-ingestion-v1` dalında henüz gerçek veri yok
(bütün testler fixture ile). Onların verisini beklemek yerine şemayı kuruyoruz;
gerçek veritabanı geldiğinde değişen tek şey LAKEHOUSE_PATH olacak.

Kurulan yapı (onların DDL'i ve fact_observation.yml sözleşmesiyle birebir):
    meta.series               insan yazımı semantik katalog
    silver.fact_observation   kanonik, tipli, kaynak-bağımsız gözlemler
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.config import load_settings  # noqa: E402

SOURCE_DB = Path(__file__).resolve().parents[1] / "data" / "lakehouse.duckdb"
OUT_DB = Path(__file__).resolve().parents[1] / "data" / "lakehouse_silver.duckdb"

# meta.series — veri ekibinin 004_series_catalog.sql'inden birebir alındı.
META_SERIES_DDL = """
CREATE SCHEMA IF NOT EXISTS meta;
CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE IF NOT EXISTS meta.series (
    series_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    native_code VARCHAR NOT NULL,
    dataset_id VARCHAR,
    name_tr VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    aliases VARCHAR[],
    tags VARCHAR[],
    frequency VARCHAR NOT NULL,
    week_anchor VARCHAR,
    unit VARCHAR,
    measure_type VARCHAR NOT NULL,
    default_agg VARCHAR,
    cumulative_reset VARCHAR,
    semantic_confidence VARCHAR NOT NULL,
    semantic_source VARCHAR NOT NULL,
    first_obs DATE,
    last_obs DATE,
    metadata_url VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'active',
    catalog_content_sha256 VARCHAR NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    CONSTRAINT series_measure_type_vocabulary CHECK (measure_type IN (
        'stock', 'flow_periodic', 'flow_ytd', 'flow_cumulative',
        'rate', 'ratio', 'index', 'count', 'unknown')),
    CONSTRAINT series_semantic_confidence_vocabulary CHECK (semantic_confidence IN (
        'verified', 'derived', 'unknown')),
    CONSTRAINT series_status_vocabulary CHECK (status IN ('active', 'deprecated', 'draft'))
);

CREATE TABLE IF NOT EXISTS silver.fact_observation (
    series_id VARCHAR NOT NULL,
    entity_id VARCHAR,
    observation_date DATE NOT NULL,
    period_start DATE,
    period_end DATE,
    value DOUBLE,
    frequency VARCHAR NOT NULL,
    unit VARCHAR NOT NULL,
    measure_type VARCHAR NOT NULL,
    quality_flag VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    artifact_sha256 VARCHAR NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    schema_version VARCHAR NOT NULL,
    vintage_id VARCHAR,
    run_id VARCHAR
);
"""

# BDDK kalemi -> seri. native_code alanı kaynağın kendi kimliğidir; burada kalem adı.
# Alt toplam kalemleri bilinçli olarak alınmadı (mükerrer sayım riski).
SERIES = [
    {
        "kalem": "Tüketici Kredileri - Konut",
        "series_id": "bddk_monthly:konut_toplam",
        "name_tr": "Tüketici Kredileri - Konut, Toplam (Sektör)",
        "description": (
            "BDDK Aylık Bülten, Tüketici Kredileri tablosu, konut kalemi, Toplam sütunu, "
            "Sektör tarafı. Dönem sonu konut kredisi bakiyesidir (stok): dönemler toplanmaz, "
            "daha düşük frekansa indirilirken dönemin son değeri alınır."
        ),
        "aliases": ["konut kredisi", "konut kredileri", "ev kredisi", "mortgage",
                    "konut finansmanı", "konut kredisi bakiyesi", "konut kredisi stoku"],
        "tags": ["kredi", "konut", "bankacilik", "bddk", "stok"],
    },
    {
        "kalem": "Tüketici Kredileri - Taşıt",
        "series_id": "bddk_monthly:tasit_toplam",
        "name_tr": "Tüketici Kredileri - Taşıt, Toplam (Sektör)",
        "description": "BDDK Aylık Bülten taşıt kredisi bakiyesi (stok), sektör toplamı.",
        "aliases": ["taşıt kredisi", "araç kredisi", "otomobil kredisi", "taşıt kredileri"],
        "tags": ["kredi", "tasit", "bankacilik", "bddk", "stok"],
    },
    {
        "kalem": "Tüketici Kredileri - İhtiyaç",
        "series_id": "bddk_monthly:ihtiyac_toplam",
        "name_tr": "Tüketici Kredileri - İhtiyaç, Toplam (Sektör)",
        "description": "BDDK Aylık Bülten ihtiyaç kredisi bakiyesi (stok), sektör toplamı.",
        "aliases": ["ihtiyaç kredisi", "ihtiyac kredisi", "tüketici kredisi",
                    "bireysel ihtiyaç kredisi"],
        "tags": ["kredi", "ihtiyac", "bankacilik", "bddk", "stok"],
    },
    {
        "kalem": "Takipteki Konut Kredileri",
        "series_id": "bddk_monthly:konut_takipteki",
        "name_tr": "Takipteki Konut Kredileri (Sektör)",
        "description": (
            "BDDK Aylık Bülten, takipteki konut kredileri. DİKKAT: bu canlı kredi bakiyesi "
            "DEĞİL, takibe düşmüş alacaktır; konut kredisi sorulduğunda bu seri kullanılmaz."
        ),
        "aliases": ["takipteki konut kredisi", "batık konut kredisi", "takipteki alacak konut"],
        "tags": ["kredi", "konut", "takipteki", "npl", "bddk", "stok"],
    },
]


def main() -> None:
    if not SOURCE_DB.exists():
        raise SystemExit(f"Önce `python scripts/dev_seed.py` çalıştırın: {SOURCE_DB} yok")

    OUT_DB.unlink(missing_ok=True)
    con = duckdb.connect(str(OUT_DB))
    con.execute(META_SERIES_DDL)
    con.execute(f"ATTACH '{SOURCE_DB}' AS src (READ_ONLY)")

    for s in SERIES:
        con.execute(
            """
            INSERT INTO meta.series (
                series_id, source_id, native_code, dataset_id, name_tr, description,
                aliases, tags, frequency, unit, measure_type, default_agg,
                semantic_confidence, semantic_source, metadata_url, status,
                catalog_content_sha256)
            VALUES (?, 'bddk_monthly', ?, 'bddk_monthly_consumer_loans', ?, ?,
                    ?, ?, 'monthly', 'TRY_mn', 'stock', 'last',
                    'verified', 'source_docs', 'https://www.bddk.org.tr/BultenAylik', 'active',
                    ?)
            """,
            [s["series_id"], s["kalem"], s["name_tr"], s["description"],
             s["aliases"], s["tags"], f"dev-{s['series_id']}"],
        )
        # Bronze -> Silver: kaynağa özel kalem/TP/YP yapısı kanonik gözleme indirgenir.
        con.execute(
            """
            INSERT INTO silver.fact_observation
            SELECT ? AS series_id, NULL AS entity_id,
                   donem AS observation_date,
                   date_trunc('month', donem) AS period_start,
                   donem AS period_end,
                   toplam AS value,
                   'monthly' AS frequency, 'TRY_mn' AS unit, 'stock' AS measure_type,
                   CASE WHEN toplam IS NULL THEN 'missing_value' ELSE 'ok' END AS quality_flag,
                   'bddk_monthly' AS source_id,
                   'bddk_monthly_consumer_loans' AS dataset_id,
                   'dev0000000000000000000000000000000000000000000000000000000000' AS artifact_sha256,
                   now() AS fetched_at, 'bddk_monthly.v1' AS schema_version,
                   'dev' AS vintage_id, 'dev-run' AS run_id
            FROM src.bddk_aylik_krediler
            WHERE kalem = ? AND is_alt_toplam = FALSE
            ORDER BY donem
            """,
            [s["series_id"], s["kalem"]],
        )

    # Kapsam: veri ekibinin coverage.py'ı ile aynı mantık — Silver'dan türetilir.
    con.execute(
        """
        UPDATE meta.series m SET
            first_obs = s.lo, last_obs = s.hi
        FROM (SELECT series_id, MIN(observation_date) lo, MAX(observation_date) hi
              FROM silver.fact_observation GROUP BY series_id) s
        WHERE m.series_id = s.series_id
        """
    )
    rows = con.execute(
        "SELECT m.series_id, m.name_tr, m.first_obs, m.last_obs, count(f.value) "
        "FROM meta.series m LEFT JOIN silver.fact_observation f USING (series_id) "
        "GROUP BY ALL ORDER BY 1"
    ).fetchall()
    con.close()

    print(f"✓ {OUT_DB}")
    for r in rows:
        print(f"  {r[0]:36} {r[2]} → {r[3]}  {r[4]:>3} gözlem")


if __name__ == "__main__":
    main()
