# ADR-0020: Referans adaptörde savunma derinliği; TLS doğrulaması kapatılmaz

**Durum:** Kabul edildi · **Tarih:** 2026-09-10 · **Kaynak:** Ekip kod incelemesi

## Bağlam
Veri ekibinin incelemesi iki açığı çalıştırarak doğruladı: `DuckDBLakehouse.execute_sql`
`read_csv_auto('...')` ile dış dosya okumaya ve `SELECT 1; SELECT 2` gibi çoklu ifadeye
izin veriyordu. Kendi doğrulamamda `glob()` de geçti; `enable_external_access` açıktı;
`workspace_compute_column` kendi bellek içi bağlantısını korumasız açıyordu; adaptörün
hiç birim testi yoktu — açık bu yüzden fark edilmemişti.

Ayrıca `docs/LAKEHOUSE_CONTRACT.md` ve `scripts/dev_seed.py` BDDK'nın eksik ara
sertifikası için `verify=False` kullanıyordu.

## Karar
**Üç katmanlı guard, veri ekibinin ilkesiyle aynı — "SQL guard hiçbir zaman tek bariyer
olmasın":**
1. Bağlantı sertleştirmesi: `read_only` + `enable_external_access=false` +
   `lock_configuration=true`. DuckDB'de bu ayarlar tek yönlüdür; açıldıktan sonra `SET`
   ile geri alınamaz (test: `test_kilitli_yapilandirma_geri_acilamaz`).
2. Parser düzeyi: `duckdb.extract_statements` ile tam bir ifade ve türü SELECT.
3. Sözcüksel yasak liste: DDL/DML + `read_csv*`, `read_parquet`, `read_json*`,
   `read_text`, `read_blob`, `glob`, `httpfs`, `s3_*` vb.

Aynı sertleştirilmiş bağlantı `workspace_compute_column`'da da kullanılır; modelin SQL
çalıştırabildiği iki yol aynı sınırlara sahiptir. Satır sınırı artık motorda (`LIMIT`)
uygulanır, sonucu belleğe alıp kırpmak yerine.

**TLS:** `verify=False` hiçbir yerde kullanılmaz. BDDK sunucusu ara sertifikayı
göndermediği için `certifi` ile doğrulama başarısız olur; çözüm `truststore` ile işletim
sisteminin sertifika deposunu kullanmak (macOS'ta ara sertifika mevcut, HTTP 200 doğrulandı)
ya da `SSL_CERT_FILE` ile ara sertifikayı içeren bir bundle vermek.

## Ölçüm
- 16 tehlikeli ifade parametrik testte reddediliyor; normal SELECT/WITH/CTE geçiyor.
- Guard atlansa bile motor `read_csv_auto`'yu reddediyor (savunma derinliği testi).
- Birim testleri 22 → 47. Golden G1/G7 MIA'da sertleştirme sonrası geçiyor.

## Ders
Referans adaptör "geçici" diye güvenliksiz bırakılmıştı; oysa CLI onu kullanıyor ve demo
ortamında agent'ın ürettiği SQL bu yoldan geçiyor. Geçici kod da ürün koduyla aynı
sınırlara sahip olmalı. Ayrıca bir bileşenin testi yoksa açığı ancak başkası bulur.
