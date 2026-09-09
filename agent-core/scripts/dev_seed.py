"""Geliştirme amaçlı seed lakehouse.

DİKKAT: Bu üretim ingestion'ı DEĞİLDİR. Üretim veri boru hattı veri ekibinin
sorumluluğunda ve Bronze/Silver/Gold katmanlarıyla kurulacak. Bu script sadece
agent katmanını GERÇEK veriyle geliştirebilmek için küçük bir Gold tablo üretir.

Aynı zamanda veri ekibine iki şeyi somut olarak gösterir:
  1. BDDK'nın JSON endpoint'i (Excel indirmeye gerek yok),
  2. Semantic Catalog'un nasıl doldurulacağı.
"""

from __future__ import annotations

import calendar
import json
import sys
from datetime import date
from pathlib import Path

import duckdb
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.catalog import (  # noqa: E402
    ColumnRole,
    ColumnSpec,
    Coverage,
    CumulativeKind,
    DatasetSpec,
    Frequency,
    SemanticType,
)

BDDK_URL = "https://www.bddk.org.tr/BultenAylik/tr/Home/BasitRaporGetir"
OUT_DB = Path(__file__).resolve().parents[1] / "data" / "lakehouse.duckdb"
CATALOG_PATH = OUT_DB.parent / "catalog.json"

# BDDK aylık bülten tablo haritası (canlı keşifle doğrulandı).
# Birimlerin FARKLI olduğuna dikkat: tablo 5 bin TL, diğerleri milyon TL.
TABLES = {
    3: ("Krediler", 1_000_000.0),
    4: ("Tüketici Kredileri", 1_000_000.0),
}


def fetch_month(client: httpx.Client, tablo_no: int, yil: int, ay: int) -> list[dict]:
    resp = client.post(
        BDDK_URL,
        data={
            "tabloNo": tablo_no,
            "yil": yil,
            "ay": ay,
            "paraBirimi": "TL",
            "taraf": "10001",  # Sektör toplamı
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        return []

    # Kanonik dönem anahtarı: dönem SONU. Veri ekibinin fact_observation
    # şemasındaki kural bu (date_key = period end) ve uyumsuzluk sessiz bir
    # hatadır: join eşleşmez, sütun boş gelir, hiçbir hata mesajı çıkmaz.
    son_gun = calendar.monthrange(yil, ay)[1]
    out = []
    for row in payload["Json"]["data"].get("rows", []):
        cell = row["cell"]
        # cell = [taraf, sıra, kalem_adı, font, TP, YP, Toplam]
        out.append(
            {
                "donem": date(yil, ay, son_gun),
                "tablo_no": tablo_no,
                "kalem_sira": cell[1],
                "kalem": cell[2],
                # BDDK alt toplam satırlarını 'bold' font ile işaretliyor.
                # Bu sinyali kaydediyoruz: alt toplamlar alt kalemlerle birlikte
                # toplanırsa mükerrer sayım olur — agent'ın en kolay düştüğü tuzak.
                "is_alt_toplam": cell[3] == "bold",
                "tp": cell[4],
                "yp": cell[5],
                "toplam": cell[6],
            }
        )
    return out


def main() -> None:
    rows: list[dict] = []
    # BDDK sertifika zinciri eksik -> verify=False. Üretimde CA bundle ile çözülmeli.
    with httpx.Client(timeout=30.0, verify=False) as client:
        for tablo_no in TABLES:
            for yil in range(2021, 2027):
                for ay in range(1, 13):
                    if (yil, ay) > (2026, 6):
                        break
                    try:
                        got = fetch_month(client, tablo_no, yil, ay)
                        rows.extend(got)
                        print(f"  tablo {tablo_no} {yil}-{ay:02d}: {len(got)} satır", flush=True)
                    except Exception as exc:
                        print(f"  ! tablo {tablo_no} {yil}-{ay:02d} atlandı: {exc}", flush=True)

    if not rows:
        raise SystemExit("Hiç veri çekilemedi.")

    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(OUT_DB))
    con.execute("DROP TABLE IF EXISTS bddk_aylik_krediler")
    con.execute(
        """
        CREATE TABLE bddk_aylik_krediler (
            donem       DATE,
            tablo_no    INTEGER,
            kalem_sira  INTEGER,
            kalem       VARCHAR,
            is_alt_toplam BOOLEAN,
            tp          DOUBLE,
            yp          DOUBLE,
            toplam      DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO bddk_aylik_krediler VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r["donem"], r["tablo_no"], r["kalem_sira"], r["kalem"],
                r["is_alt_toplam"], r["tp"], r["yp"], r["toplam"],
            )
            for r in rows
        ],
    )
    n, lo, hi = con.execute(
        "SELECT COUNT(*), MIN(donem), MAX(donem) FROM bddk_aylik_krediler"
    ).fetchone()
    con.close()

    spec = DatasetSpec(
        dataset_id="bddk_aylik_krediler",
        name="BDDK Aylık Bülten — Krediler ve Tüketici Kredileri",
        description=(
            "Türk bankacılık sektörünün aylık kredi bakiyeleri. Konut, taşıt ve ihtiyaç "
            "kredileri ile sektörel kredi kalemlerini içerir. Her satır bir dönem-kalem "
            "kırılımıdır; tutarlar sektör toplamıdır ve TP (Türk parası), YP (yabancı para) "
            "ile toplam olarak ayrışır."
        ),
        source="BDDK",
        source_url="https://www.bddk.org.tr/BultenAylik",
        source_detail="Aylık Bülten, Tablo 3 (Krediler) ve Tablo 4 (Tüketici Kredileri), Taraf: Sektör",
        frequency=Frequency.MONTHLY,
        time_column="donem",
        grain=["donem", "tablo_no", "kalem"],
        columns=[
            ColumnSpec(
                name="donem", role=ColumnRole.TIME, dtype="DATE",
                description="Verinin ait olduğu ay, dönem SONU günüyle temsil edilir "
                "(Ocak 2025 -> 2025-01-31)",
                aliases=["ay", "dönem", "tarih"],
            ),
            ColumnSpec(
                name="kalem", role=ColumnRole.DIMENSION, dtype="VARCHAR",
                description="Kredi kalemi adı, BDDK'nın yayınladığı biçimde",
                aliases=["kredi türü", "kalem adı"],
                example_values=[
                    "Tüketici Kredileri - Konut",
                    "Tüketici Kredileri - Taşıt",
                    "Tüketici Kredileri - İhtiyaç",
                ],
            ),
            ColumnSpec(
                name="tablo_no", role=ColumnRole.DIMENSION, dtype="INTEGER",
                description="Kaynak bülten tablo numarası (3=Krediler, 4=Tüketici Kredileri)",
            ),
            ColumnSpec(
                name="is_alt_toplam", role=ColumnRole.DIMENSION, dtype="BOOLEAN",
                description="TRUE ise bu satır bir ALT TOPLAMDIR (ör. 'Tüketici Kredileri (2+3+4)'). "
                "Alt kalemlerle birlikte toplanırsa mükerrer sayım olur. Tek bir kalemi "
                "incelerken is_alt_toplam = FALSE filtresi kullanın.",
                aliases=["alt toplam", "toplam satırı"],
            ),
            ColumnSpec(
                name="kalem_sira", role=ColumnRole.METADATA, dtype="INTEGER",
                description="Bültendeki satır sırası; alt toplam ilişkilerini korur",
            ),
            ColumnSpec(
                name="tp", role=ColumnRole.MEASURE, dtype="DOUBLE",
                description="Türk parası cinsinden kredi bakiyesi",
                semantic_type=SemanticType.STOCK, cumulative=CumulativeKind.NONE,
                unit="milyon TL", unit_multiplier=1_000_000.0,
                aliases=["türk parası", "TL kredi"],
            ),
            ColumnSpec(
                name="yp", role=ColumnRole.MEASURE, dtype="DOUBLE",
                description="Yabancı para cinsinden kredi bakiyesi (TL karşılığı)",
                semantic_type=SemanticType.STOCK, cumulative=CumulativeKind.NONE,
                unit="milyon TL", unit_multiplier=1_000_000.0,
                aliases=["yabancı para", "döviz kredi"],
            ),
            ColumnSpec(
                name="toplam", role=ColumnRole.MEASURE, dtype="DOUBLE",
                description="Toplam kredi bakiyesi (TP + YP)",
                semantic_type=SemanticType.STOCK, cumulative=CumulativeKind.NONE,
                unit="milyon TL", unit_multiplier=1_000_000.0,
                aliases=["toplam kredi", "kredi bakiyesi", "kredi tutarı", "kredi hacmi"],
            ),
        ],
        coverage=Coverage(start=lo, end=hi, row_count=n),
        tags=["kredi", "konut kredisi", "tüketici kredisi", "bankacılık"],
        notes=[
            "Kaynak MİLYON TL yayınlar. Gerçek TL değeri için unit_multiplier (1e6) uygulanmalıdır.",
            "Bu bir STOK serisidir: her satır ay sonu bakiyesini gösterir, ay içi kullandırım değildir. "
            "Dönemsel değişim için ardışık aylar arasında fark alınmalıdır.",
            "'Tüketici Kredileri (2+3+4)' gibi kalemler ALT TOPLAMDIR; alt kalemlerle "
            "birlikte toplanırsa mükerrer sayım olur.",
        ],
        last_refreshed=date.today(),
    )
    CATALOG_PATH.write_text(
        json.dumps([spec.model_dump(mode="json")], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✓ {n} satır ({lo} → {hi}) -> {OUT_DB}")
    print(f"✓ katalog -> {CATALOG_PATH}")


if __name__ == "__main__":
    main()
