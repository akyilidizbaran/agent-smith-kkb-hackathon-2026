# Phase 1B — Real Source Integration

Phase 1B, kaynak erişimi ile ortak lakehouse altyapısını ilk kez aynı akışta
birleştirir. Amaç, gerçek kaynakların connector ve parser sınırlarını koruyarak
RAW, metadata, Bronze ve güvenli sorgu katmanlarına ulaşan küçük bir dikey dilim
oluşturmaktır.

## 1. Entegrasyon Sınırı

Source Access tarafı:

BDDK / EVDS → Connector → RAW → Parser → ParsedBatch

Infrastructure tarafı:

ParsedBatch → Bronze Parquet → metadata → DuckDB → güvenli sorgu

Phase 1B bu iki sınırı birleştirir. Connector yalnızca kaynağa erişir ve ham
yanıtı kaydeder; parser yalnızca kayıtlı RAW artifact'ı okur. Kaynağa özgü
kurallar infrastructure orchestration katmanına taşınmaz.

## 2. Ingestion Orchestration

IngestionPipeline aşağıdaki akışı yönetir:

FetchSpec → Connector → FetchedAsset → artifact kaydı → Parser → ParsedBatch
→ Bronze Parquet

Pipeline, FetchSpec ile FetchedAsset arasındaki source ve dataset kimliklerini
kontrol eder. ParsedBatch'in source, dataset ve artifact_sha256 değerleri de
FetchedAsset ile karşılaştırılır. Boş sonuçlar ve kimlik tutarsızlıkları mevcut
LakehouseError/ErrorPayload sözleşmesiyle raporlanır.

## 3. Kaynak Entegrasyonu

### BDDK Monthly

- Connector: BddkMonthlyConnector
- Parser: BddkMonthlyParser
- Fixture: tests/fixtures/raw/bddk_monthly/bddk_monthly_housing_loans.json
- source_id: bddk_monthly
- dataset_id: bddk_monthly_housing_loans

### EVDS

- Connector: EvdsConnector
- Parser: EvdsParser
- Fixture: tests/fixtures/raw/evds/evds_ktf12_weekly.json
- source_id: evds
- dataset_id: evds_housing_interest

### BDDK Weekly

- Connector: BddkWeeklyConnector
- Parser: BddkWeeklyParser
- Fixture: tests/fixtures/raw/bddk_weekly/bddk_weekly_housing_loans.json
- source_id: bddk_weekly
- dataset_id: bddk_weekly_housing_loans

Haftalik parser kaynak tarihlerini ve degerlerini korur; hafta tarihlerini Cuma'ya
sessizce normalleştirmez. Positional chart id yerine connector metadata'sindaki
stabil native item id kullanilarak `bddk_weekly:5690_3` uretilir.

Offline entegrasyon testlerinde production BDDK/EVDS connector ve parser
sınıfları ile gerçek RawStorage, Bronze Parquet storage, ArtifactRepository,
DuckDB ve QueryExecutor katmanları çalıştırılır. Dış bağımlılıklar, kayıtlı
fixture byte'larını döndüren deterministik HTTP transport, test clock'u ve EVDS
için test credential injection ile izole edilir. Bu testler canlı kaynak çağrısı
değildir.

EVDS documented keyed endpoint için credential destekli canlı smoke test henüz
yapılmamıştır; fixture doğrulaması bu sınırlamayı ortadan kaldırmaz.

## 4. Storage, Provenance ve Query Sınırı

RAW artifact'ın kimliği artifact_sha256 ile belirlenir ve meta.artifact içinde
tekil olarak kaydedilir. Aynı fixture'ın tekrar çalıştırılması yeni artifact
satırı oluşturmaz ve aynı Bronze identity'sini kullanır.

Connector tarafından üretilen locator ve request metadata, credential-shaped
alanlar çıkarıldıktan sonra request-level provenance olarak saklanır:

FetchedAsset.metadata → secret sanitization → deterministic request metadata
locator + metadata → request fingerprint → meta.artifact_request

meta.artifact fiziksel/content provenance'ını, meta.artifact_request ise
artifact'ın request-level provenance'ını tutar. Request provenance locator,
sanitized deterministic metadata, request_fingerprint, first_seen_at ve
last_seen_at alanlarını içerir. Aynı artifact farklı locator veya request
metadata ile yeniden görülebilir; her güvenli request context kendi fingerprint'i
ile saklanır. Bu yapı artifact SHA, RAW path ve Bronze path kimliklerini
değiştirmez.

Bronze Parquet, source_id, dataset_id, artifact_sha256 ve schema_version
kimliklerini Parquet metadata'sında taşır. Böylece representation provenance'ı
dosyadan geri okunabilir.

Mevcut query sınırı şöyledir:

Bronze Parquet → trusted internal registration/materialization
→ DuckDB görünür relation/table → read-only untrusted connection
→ SQL Guard → QueryExecutor → safe SELECT

Untrusted SQL doğrudan rastgele Parquet dosyalarına veya filesystem/network
fonksiyonlarına erişemez. Test bridge'i, trusted bağlantıda kontrollü local
Parquet relation'ını Bronze tablosuna materialize eder; agent-facing bir tool
veya yeni bir persistent registration mimarisi değildir.

## 5. Validation

| Komut | Sonuç |
|---|---|
| uv sync --frozen | başarılı |
| uv lock --check | başarılı |
| make test | 322 passed |
| make build | başarılı |
| make demo-check | 2 passed |

Phase 1B kaynak entegrasyon testleri BDDK aylık konut kredileri, BDDK haftalık
konut kredileri ve EVDS TP.KTF12 haftalık serisini kapsar. Ayrıca pipeline'ın
boş sonuç, kaynak uygulama hatası, duplicate artifact ve provenance davranışları
test edilir.

## 6. Mevcut Sınırlamalar ve Sonraki Adım

EVDS keyed endpoint canlı doğrulaması, operasyonel rate-limit/windowing ve
credential yönetimi sonraki source operasyon adımlarıdır. Silver semantik model
ve fact_observation bir sonraki fazın konusudur.

## Repository Reference

- Bu doküman repository'nin taşıdığı güncel entegre Phase 1B base'ini açıklar.
- Branch: feature/lakehouse-integration
- Historical Phase 1B integration implementation commit:
  bc2f1060822dc8b72485720a26cd83725759c37b
- Later request provenance hardening commit:
  ba3fcf343877ae637ca684d0997f803f23aeb72e
- QueryExecutor schema/table allowlist'i agent-facing production query surface
  oluşturulmadan önce uygulanacaktır.
