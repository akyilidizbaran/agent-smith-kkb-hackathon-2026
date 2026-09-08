# Phase 1A — Infrastructure Foundation

Phase 1A, source ingestion ile analitik modelleme arasındaki infrastructure
sınırını oluşturur. Source Access tarafının ürettiği `ParsedBatch` çıktıları bu
katmanda immutable Bronze representation'lara dönüştürülür, provenance'ı
korunarak kaydedilir ve DuckDB üzerinden kontrollü biçimde sorgulanabilir hale
gelir. Faz sonunda elimizde gerçek veriye henüz bağlı olmayan, ancak bağlanmaya
hazır, tekrar üretilebilir ve güvenlik sınırları çizilmiş bir lakehouse temeli
var.

## 1. Scope and Architecture

Katman, Phase 0/0.5'te tanımlanan ortak contract'ların (common base) üzerine
oturur ve tek bir dikey dilimi uçtan uca ayakta tutar:

```
ParsedBatch
    ↓
Bronze Parquet
    ↓
DuckDB
    ↓
Metadata / Provenance
    ↓
Safe Query Execution
```

Gerçek kaynak erişimi (BDDK / EVDS connector ve parser'ları) Source Access
track'inde yürür; Silver/Gold modelleri ve semantic dönüşümler sonraki fazlara
aittir. Bu doküman yalnızca yukarıdaki infrastructure hattını kapsar.

## 2. Storage and Database Layer

Depolama iki parçadan oluşur. Bronze verisi diskte Parquet olarak durur; DuckDB
ise bu veriyi ve metadata'yı sorgulayan motordur. Parquet fiziksel analitik
depolama formatı, DuckDB ise sorgu ve metadata motorudur.

DuckDB embedded bir analitik engine olarak kullanılır. Database dosyası
varsayılan olarak `data/lakehouse.duckdb`'dir ve çağıran taraf isterse farklı
bir path verebilir. Şema ve tablo kurulumu `sql/bootstrap/` altındaki SQL
dosyalarından yapılır; tüm ifadeler `IF NOT EXISTS` ile yazıldığından bootstrap
idempotenttir ve tekrar çalıştırıldığında mevcut veriyi bozmaz. Kurulan şemalar
`meta`, `bronze`, `silver` ve `gold`'dur; `silver` ve `gold` bu fazda yalnızca
ileride kullanılmak üzere açılmış boş namespace'lerdir.

Bronze tarafında her `ParsedBatch`, kaynağa özgü hiçbir dönüşüm uygulanmadan
PyArrow ile Parquet'e yazılır. Dosya yolu, temsilin kimliğinden deterministik
olarak türetilir:

```
data/bronze/
  source_id=<source>/
  dataset_id=<dataset>/
  schema_version_sha256=<schema-key>/
  artifact_sha256=<sha>.parquet
```

`schema_version` path'e doğrudan yazılmaz; SHA-256'ya indirgenerek dizin adına
konur, dolayısıyla schema versiyonları birbirinden izole edilir ve serbest metin
bir path segment'i üretemez. `source_id`, `dataset_id` ve `artifact_sha256`
zaten `ParsedBatch` seviyesinde slug/hex olarak doğrulandığı için yol
enjeksiyonu mümkün değildir.

Yazma önce geçici bir dosyaya yapılır, ardından `os.replace` ile hedefe taşınır;
böylece yarım kalmış bir dosya asla yerine geçmez. Aynı kimlik ve aynı içerik
tekrar yazılmak istendiğinde mevcut dosya yeniden üretilmez, var olan yol geri
döner. Aynı kimliğe sahip fakat farklı bir içerik gelirse `ParquetConflictError`
yükseltilir; `overwrite=True` verilse dahi mevcut Bronze temsili sessizce
değiştirilmez. Bu davranış Bronze'un değişmezliğini (immutability) garanti eder.

## 3. Metadata and Provenance

`meta` şeması dört tablo içerir: `source`, `artifact`, `run` ve
`dataset_version`. Bu fazın ağırlık merkezi `meta.artifact`'tir; `run` ve
`dataset_version` şimdilik yalnızca şema düzeyinde hazırdır ve onları besleyen
lifecycle mantığı sonraki fazlara bırakılmıştır (özellikle
`dataset_version.is_current`).

Bir artifact `artifact_sha256` üzerinden kaydedilir ve bu değer kimliktir. Aynı
içerik ikinci kez geldiğinde yeni satır açılmaz; kayıttaki değişmez alanlar
(`source_id`, `dataset_id`, `locator`, `media_type`, `byte_size`, `http_status`,
`raw_path`) yeni gelenle karşılaştırılır ve bir uyuşmazlık varsa işlem hata ile
durur. Bu, aynı SHA'nın farklı bir kaynak/konum iddiasıyla yeniden
yazılamayacağı anlamına gelir.

Zaman damgalarında iki kavram ayrı tutulur: `fetched_at` artifact'ın indirildiği
an, `first_seen_at`/`last_seen_at` ise kaydın ilk ve son görülme anıdır. İlk
kayıtta `first_seen_at` yazılır ve bir daha değişmez; sonraki her görülmede
sadece `last_seen_at` güncellenir. Tüm operasyonel zamanlar timezone-aware
UTC'ye normalize edilir.

Provenance yalnızca veritabanında tutulmaz. Bronze Parquet dosyalarının schema
metadata'sına `source_id`, `dataset_id`, `artifact_sha256` ve `schema_version`
gömülür, dolayısıyla bir dosyanın kökeni veritabanından bağımsız olarak dosyanın
kendisinden de geri okunabilir.

## 4. Query Security

Güven modeli iki bağlantı profiline dayanır. İç altyapı işlemleri (bootstrap,
metadata, kontrollü Bronze kaydı) yazılabilen bir trusted bağlantı üzerinden
yürür. Agent tarafından üretilen SQL ise yalnızca sertleştirilmiş bir untrusted
bağlantıda çalışır: read-only açılır, external access kapalıdır, extension
autoload/autoinstall devre dışıdır, community ve unsigned extension'lara izin
verilmez ve bağlantı açıldıktan sonra konfigürasyon kilitlenir. Kilit en son
uygulandığı için, oturum içinde hiçbir `SET` bu ayarları geri gevşetemez.
Uygulanan ayarların tümü DuckDB'nin runtime setting kataloğuna karşı doğrulanır.

Bağlantı katmanının üstünde SQL Guard yer alır. Guard yalnızca tek bir okuma
sorgusuna izin verir; girdi `SELECT` veya `WITH ... SELECT` ile başlamalı ve tek
statement olmalıdır. Yorumlar ve fazladan boşluklar ayıklanır, birden çok
statement reddedilir. Mutation ve konfigürasyon ifadeleri (`INSERT`, `UPDATE`,
`DELETE`, `DROP`, `ATTACH`, `COPY`, `INSTALL`, `PRAGMA` ve benzerleri) ile dış
kaynak okuyan tablo fonksiyonları (`read_csv`, `read_parquet`, `glob`,
`query_table`, `query` ve benzerleri) engellenir; `FROM`/`JOIN` ardına doğrudan
dosya yolu yazılması da kabul edilmez.

Sorguları çalıştıran `QueryExecutor`, kendisine verilen bağlantının gerçekten
sertleştirilmiş untrusted profile uyduğunu (`access_mode` read-only, external
access kapalı, konfigürasyon kilitli) doğrular; trusted/yazılabilir bir bağlantı
verilirse hata yükseltir. Çalıştırma satır sınırlıdır: `max_rows` kadar satır
tutulur, bir fazlası çekilerek truncation tespit edilir ve sonuç `columns`,
`rows`, `row_count`, `truncated`, `executed_sql` alanlarıyla yapılandırılmış
biçimde döner.

## 5. Independent Security Review

İlk implementasyon, onu yazmayan ikinci bir agent tarafından bağımsız bir code
review'den geçirildi. İncelemede, DuckDB'nin `query('<sql>')` table
fonksiyonunun guard'ın deny list'inde bulunmadığı tespit edildi; `query_table`
engelliyken `query` engellenmiyordu ve bu, dış fonksiyon denetiminin string
içine gizlenmiş bir sorguyla atlatılmasına açık kapı bırakıyordu. Bulgu push
blocker kabul edilip `query` deny list'e eklenerek kapatıldı.

İnceleme sonrasında birkaç savunma katmanı daha eklendi: untrusted bağlantıda
`allow_community_extensions` ve `allow_unsigned_extensions` kapatıldı,
`lock_configuration` en son adım olarak uygulandı ve `QueryExecutor`'ın
trusted bağlantıyı reddetmesi kod seviyesinde zorunlu kılındı.

## 6. Validation

Doğrulama, gerçek internete çıkmayan bir offline vertical slice ile yapılır.
Sahte RAW baytları önce içerik-adresli olarak saklanır ve bir `FetchedAsset`
üretir; bundan bir `ParsedBatch` oluşur, Bronze Parquet'e yazılır, artifact
metadata'sı DuckDB'ye kaydedilir ve son olarak veri untrusted bağlantı üzerinden
güvenli bir `SELECT` ile geri okunur:

```
Fake RAW → FetchedAsset → ParsedBatch → Bronze Parquet
  → artifact metadata → DuckDB → safe SELECT
```

Bu zincir; Parquet round-trip ve tip korunumunu, provenance'ın geri
okunabilirliğini, aynı içeriğin tek fiziksel kayda inmesini (deduplication),
sorgu satır sınırını ve yazma/DDL ile dış dosya erişimi gibi güvensiz SQL'in
reddini birlikte doğrular.

| Check | Result |
|---|---|
| `uv sync --frozen` | PASS |
| `uv lock --check` | PASS |
| `make test` | 81 passed |
| `make build` | PASS |
| `make demo-check` | 2 passed |

## 7. Current State and Next Step

Phase 1A sonunda infrastructure hattı çalışır durumda: DuckDB bootstrap ve
metadata temeli, immutable Bronze Parquet depolama, artifact ve provenance
takibi, trusted/untrusted sorgu sınırı, sertleştirilmiş SQL çalıştırma ve bunları
uçtan uca doğrulayan offline testler yerinde.

- DuckDB bootstrap and metadata foundation
- immutable Bronze Parquet storage
- artifact / provenance tracking
- trusted / untrusted query boundary
- hardened SQL execution
- offline integration tests

Sıradaki adım Phase 1B — Real Source Integration. Source Access tarafındaki hat
(BDDK / EVDS → Connector → RAW → Parser → ParsedBatch) ile bu fazdaki hat
(ParsedBatch → Bronze Parquet → metadata → DuckDB → safe query) birleştiğinde,
projenin ilk gerçek source-backed lakehouse vertical slice'ı ortaya çıkacaktır.

Bunun ötesinde Silver canonical model, frequency ve measure semantics, Gold
view'ları, catalog/search ve agent'a açık Lakehouse Tool katmanı sonraki fazlara
bırakılmıştır.

## Repository Reference

```
Branch: feature/infrastructure
Implementation commit: 0cd88a7500c4fd10a2000d236c544a6d4de953ae
```
