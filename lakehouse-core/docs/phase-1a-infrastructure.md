# Phase 1A — Infrastructure Foundation

**Tarih:** 8 Eylül 2026
**Branch:** `feature/infrastructure`
**Durum:** Tamamlandı ve bağımsız güvenlik audit'inden geçirildi.

Bu doküman, Phase 0/0.5 ortak contract'ları (common base) üzerine kurulan
Infrastructure track'inin ne yaptığını, hangi sınırları koruduğunu ve neyi
bilinçli olarak sonraki fazlara bıraktığını özetler. Kod okumayan bir ekip
üyesinin ana resmi anlayabilmesi, kod okuyan birinin ise teknik detayı
kaybetmemesi hedeflenmiştir.

---

## 1. Amaç ve kapsam

Infrastructure track'inin görevi, gerçek veri kaynaklarından bağımsız olarak
çalışan, tekrar üretilebilir ve güvenli bir **lakehouse temeli** kurmaktır. Bu
temel tek bir dikey dilimi uçtan uca ayakta tutar:

```
ParsedBatch → Bronze Parquet → DuckDB → Metadata / provenance → Safe SQL
```

Bu fazın **tam pipeline olmadığı** özellikle vurgulanmalıdır:

- Gerçek **BDDK / EVDS** source access (connector/parser) ayrı bir track'tedir
  (Source Access) ve bu faza dahil değildir.
- **Silver / Gold** business semantics (fact tabloları, oran/stok/akış mantığı,
  kümülatif dönüşümler, Gold view'ları) bu fazda **yapılmamıştır**.
- Agent'a açılan Lakehouse Tool katmanı bu fazda yoktur.

Kısacası Phase 1A, "gerçek veriyi bağlamaya hazır, güvenli iskelet"tir.

---

## 2. DuckDB altyapısı

DuckDB, projeye **hazır bir SQL/analitik veritabanı motoru** olarak entegre
edilmiştir; yani DuckDB'yi biz geliştirmedik, onu motor olarak kullanıp
projeye ait database ve bootstrap yapısını kurduk.

| Öğe | Değer |
|---|---|
| Database dosyası | `data/lakehouse.duckdb` (varsayılan) |
| DB path | Configurable — çağıran taraf açık path verebilir |
| Bootstrap | Idempotent (tekrar çalıştırılabilir, yan etkisiz) |
| Bootstrap SQL'leri | `sql/bootstrap/` altında |

Bootstrap iki adımdan oluşur ve `sql/bootstrap/` içindeki dosyalar sıralı
çalıştırılır:

- `001_schemas.sql` → şemaları oluşturur: `meta`, `bronze`, `silver`, `gold`
- `002_meta_tables.sql` → `meta` altındaki metadata tablolarını oluşturur

Şemalar `CREATE SCHEMA IF NOT EXISTS`, tablolar `CREATE TABLE IF NOT EXISTS`
ile tanımlandığı için bootstrap birden çok kez çağrılsa da veri bozulmaz.

---

## 3. Metadata foundation

`meta` şeması altında dört tablo tanımlanmıştır:

| Tablo | Rol |
|---|---|
| `meta.source` | Kaynak kaydı (`source_id` PK, açıklama, `created_at`) |
| `meta.artifact` | İmmutable RAW artifact metadata'sı |
| `meta.run` | İşlem/çalıştırma kaydı (foundation) |
| `meta.dataset_version` | Dataset vintage/versiyon kaydı (foundation) |

### `meta.artifact` davranışı

`ArtifactRepository.register(...)` bir artifact'ı `artifact_sha256` kimliğiyle
kaydeder ve şu garantileri verir:

- **Identity = `artifact_sha256`** (primary key). Aynı içerik için ikinci bir
  satır oluşmaz.
- Aynı SHA tekrar geldiğinde immutable alanlar (`source_id`, `dataset_id`,
  `locator`, `media_type`, `byte_size`, `http_status`, `raw_path`) karşılaştırılır;
  **farklıysa hata** verilir ("already exists with different immutable metadata").
- `first_seen_at` ilk kayıtta yazılır ve **korunur**; tekrar görülmede yalnızca
  `last_seen_at` güncellenir.
- `fetched_at` (artifact'ın indirilme zamanı) ile `seen_at` (kayıt/görülme zamanı)
  ayrı kavramlardır ve karıştırılmaz.
- Tüm timestamp'ler timezone-aware UTC'ye normalize edilir.

### Bilinçli erteleme

`meta.run` ve `meta.dataset_version` bu fazda yalnızca **şema düzeyinde
foundation**tır; onlara yazan lifecycle kodu henüz yoktur. Özellikle
`dataset_version.is_current` lifecycle policy'si **bilinçli olarak** sonraki
faza bırakılmıştır.

---

## 4. Bronze Parquet Storage

Bronze katmanı, `ParsedBatch` içeriğini kaynağa özel hiçbir dönüşüm yapmadan,
**değişmez (immutable)** ve **deterministik** biçimde Parquet olarak saklar.
Depolama motoru **PyArrow**tur.

### Path formatı (koddan doğrulanmıştır)

```
data/bronze/
  source_id=<source>/
  dataset_id=<dataset>/
  schema_version_sha256=<schema_version'ın sha256'sı>/
  artifact_sha256=<sha>.parquet
```

### Garantiler

- **Deterministik identity:** Aynı `source_id` + `dataset_id` +
  `artifact_sha256` + `schema_version` → her zaman aynı path.
- **Atomic write:** Önce geçici dosyaya yazılır, sonra `os.replace` ile
  yerine taşınır (yarım dosya kalmaz).
- **Idempotent retry:** Aynı identity + aynı içerik tekrar yazılırsa aynı
  path döner, dosya yeniden yazılmaz.
- **Immutability:** Aynı identity fakat **farklı içerik** yazılmak istenirse
  `ParquetConflictError` fırlatılır — `overwrite=True` verilse bile mevcut
  Bronze **sessizce ezilmez**.
- **Schema izolasyonu:** `schema_version` değişirse `schema_version_sha256`
  klasörü değişir; farklı bir representation olur, eskisiyle çakışmaz.
- **Path traversal koruması:** `schema_version` doğrudan path'e yazılmaz,
  önce SHA-256'ya hash'lenir; `source_id` / `dataset_id` / `artifact_sha256`
  ise `ParsedBatch` seviyesinde slug/hex olarak valide edilir. Bu yüzden
  `../` gibi bir değer path üretemez.
- **Provenance:** `source_id`, `dataset_id`, `artifact_sha256`,
  `schema_version` Parquet dosyasının **schema metadata'sına** (`lakehouse.*`
  anahtarları) gömülür ve `read_identity(...)` ile kayıpsız geri okunabilir.

### Parquet ↔ DuckDB ayrımı

Kısa ayrım: **Parquet** buradaki *analitik depolama formatı*dır (diskteki
değişmez veri); **DuckDB** ise *sorgu motoru*dur. Trusted tarafta
`register_local_parquet(...)`, doğrulanmış bir Bronze dosyasını PyArrow ile
okuyup DuckDB'ye bir relation olarak tanıtır — bunu yaparken DuckDB'nin
dosya-sistemi SQL fonksiyonlarını (ör. `read_parquet`) açmaya gerek kalmaz.

---

## 5. Trusted / Untrusted DuckDB bağlantıları

İki ayrı güven profili vardır. Ayrım gereklidir çünkü **iç altyapı işlemleri**
ile **agent tarafından üretilen SQL** aynı yetkiye sahip olmamalıdır: agent
SQL'i asla yazma/konfigürasyon/dış erişim yapamamalı, bir hata durumunda tek
savunma katmanına düşülmemelidir.

| | Trusted (`connect_trusted`) | Untrusted (`connect_untrusted`) |
|---|---|---|
| Kullanım | Bootstrap, metadata, kontrollü storage | Agent-generated SQL |
| Erişim | Yazılabilir (internal) | **Read-only** |
| `enable_external_access` | false | false |
| `autoload/autoinstall_known_extensions` | false | false |
| `allow_community_extensions` | (varsayılan) | **false** |
| `allow_unsigned_extensions` | (varsayılan) | **false** |
| `lock_configuration` | uygulanmaz | **true (en son adım)** |

Tüm ayar isimleri runtime'da DuckDB'nin `duckdb_settings()` kataloğuna karşı
doğrulanır; desteklenmeyen bir ayar uydurulup gönderilmez. Untrusted tarafta
`lock_configuration=true` **en son** uygulanır; böylece bağlantı açıldıktan
sonra hiçbir `SET` ile güvenlik ayarları geri gevşetilemez.

---

## 6. SQL Guard ve QueryExecutor

### SQL Guard

Agent SQL'i, DuckDB'ye ulaşmadan önce sözcüksel (lexical) bir allowlist'ten
geçer. Guard yalnızca **tek bir** üst düzey okuma sorgusuna izin verir:

- İzin verilen: `SELECT ...` ve `WITH ... SELECT ...`
- Comment ve fazladan boşluklar temizlenir; birden çok statement (çoklu `;`)
  reddedilir.

Reddedilen yazma/konfigürasyon anahtar kelimeleri (örnekler):

```
INSERT  UPDATE  DELETE  DROP  CREATE  ALTER  ATTACH  DETACH
COPY  INSTALL  LOAD  EXPORT  IMPORT  PRAGMA  CALL  SET  RESET
USE  MERGE  TRUNCATE  GRANT  REVOKE  VACUUM
```

Reddedilen dinamik / dış erişim fonksiyonları:

```
read_csv  read_csv_auto  read_parquet  parquet_scan  read_json
read_json_auto  read_ndjson  read_text  read_blob  glob  httpfs
csv_scan  arrow_scan  delta_scan  iceberg_scan  sqlite_scan
postgres_scan  mysql_scan  query_table  query
```

`FROM`/`JOIN` sonrasına doğrudan dosya yolu (string) yazılması ve
tırnaklı tanımlayıcı içine gizlenen dış fonksiyon adları da reddedilir.

### QueryExecutor

`QueryExecutor` yalnız **hardened untrusted** bağlantı kabul eder; trusted /
writable bir bağlantı verilirse `TrustedConnectionError` fırlatır. Bu kontrol
yalnız gerçek DuckDB ayarlarıyla yapılır (`access_mode == read_only`,
`enable_external_access == false`, `lock_configuration == true`).

Çalıştırma davranışı:

- `max_rows` pozitif tam sayı olmalıdır.
- `max_rows + 1` çekilerek **truncation** doğru tespit edilir.
- Sonuç zarfı: `columns`, `rows`, `row_count`, `truncated`, `executed_sql`.

---

## 7. Bağımsız security audit ve hardening

İlk implementasyon, bağımsız (implementasyonu yazmayan) ikinci bir audit'ten
geçirildi. Audit sırasında bir **push blocker** tespit edildi:

- DuckDB'nin `query('<sql>')` table fonksiyonu SQL Guard'da engellenmiyordu;
  `query_table` engelliyken `query` denylist'te değildi. Bu, guard'ın dış
  fonksiyon denetimini string içine gizlenmiş SQL ile atlatma imkânı veriyordu.

Bu bulgu blocker olarak ele alındı ve `query` denylist'e eklenerek düzeltildi.
Audit sonrası ek olarak defense-in-depth sertleştirmeleri uygulandı:

- `allow_community_extensions=false`
- `allow_unsigned_extensions=false`
- `lock_configuration=true` (en son adım)
- `QueryExecutor` trust boundary'sinin **kod seviyesinde** zorunlu kılınması
  (trusted bağlantı reddi).

---

## 8. Offline vertical slice

Aşağıdaki zincir uçtan uca, **gerçek internete çıkmadan** çalışır:

```
Fake RAW bytes → FetchedAsset → ParsedBatch → Bronze Parquet
  → provenance identity → DuckDB bootstrap → artifact registration
  → safe SELECT (bounded)
```

Testlerde doğrulananlar:

- Parquet round-trip ve **tip korunumu** (ör. tarih, float, string)
- **Provenance** korunumu (Parquet metadata'sından geri okuma)
- Artifact **deduplication** (aynı içerik tek fiziksel kayıt)
- Bounded **safe SELECT** (satır limiti + truncation)
- **Unsafe SQL** reddi (yazma/DDL, `query()`, harici okuma fonksiyonları)
- Runtime **external file access** reddi (`enable_external_access=false`)

---

## 9. Test ve doğrulama

Ortam, kilitli (`--frozen`) bağımlılıklarla birebir yeniden kurulup çalıştırıldı
(Python 3.12, DuckDB 1.5.5, PyArrow 25.0.1, pandas 3.0.5).

| Komut | Sonuç |
|---|---|
| `uv sync --frozen` | PASS |
| `uv lock --check` | PASS (tutarlı) |
| `make test` | **81 passed** |
| `make build` | PASS (base dizinler hazır) |
| `make demo-check` | 2 passed |

Test dağılımı: security 50, contracts 18, db 3, parquet 4, artifacts 1,
connectors 2, shared base 2, integration (vertical slice) 1.

---

## 10. Shared contract uyumluluğu

Phase 1A sırasında paylaşılan contract dosyalarında **breaking change
yapılmamıştır** ve **yeni bağımlılık eklenmemiştir**:

- `src/lakehouse/contracts/*`
- `schemas/*`
- `contracts/*`
- `pyproject.toml`
- `uv.lock`

Değişiklikler yalnızca `db/`, `storage/`, `catalog/`, `security/`, `query/`,
`sql/bootstrap/` ve ilgili testler altında yapılmıştır.

---

## 11. Phase 1A sonunda mevcut durum

Aşağıdakilerin tümü gerçek kod ve testlerle doğrulanmıştır:

- [x] DuckDB foundation (bootstrap, configurable path, idempotent)
- [x] Bronze Parquet storage (immutable, deterministik, provenance)
- [x] Metadata / artifact tracking (`meta.artifact` dedup + seen-at)
- [x] Trusted / untrusted bağlantı ayrımı
- [x] SQL Guard (read-only allowlist)
- [x] QueryExecutor (bounded, trust-boundary enforced)
- [x] Offline vertical slice
- [x] Bağımsız security audit + hardening
- [x] Testler (81 passed)

---

## 12. Bilinçli olarak ertelenenler

Bu fazın kapsamı dışında bırakılanlar (sonraki fazlara aittir):

- Gerçek BDDK / EVDS connector ve parser
- Silver `fact_observation` implementasyonu
- Business semantics (stok / akış / oran / ratio mantığı)
- Kümülatif / YTD dönüşümleri
- Frequency alignment (frekans hizalama)
- Gold view'ları
- Tam catalog / search
- Agent'a açık Lakehouse Tool katmanı
- Dataset version lifecycle policy (`is_current`)
- Lineage / revision / quality'nin tam implementasyonu

---

## 13. Sonraki adım — Phase 1B: Real Source Integration

Phase 1B, Source Access track'i ile bu altyapıyı birleştirir:

```
BDDK / EVDS → Connector → RAW → Parser → ParsedBatch
                                            │
                                            ▼
        ParsedBatch → Bronze Parquet → metadata → DuckDB → safe query
```

Yani Elif'in Source Access tarafındaki `ParsedBatch` çıktısı, bu fazda kurulan
Bronze/metadata/DuckDB/safe-query altyapısına bağlanacaktır. Bu, projenin
**ilk gerçek uçtan uca (end-to-end) Lakehouse entegrasyonu** olacaktır.

---

## 14. Git bilgisi

| | |
|---|---|
| Branch | `feature/infrastructure` |
| Phase 1A implementation commit | `0cd88a7500c4fd10a2000d236c544a6d4de953ae` |
