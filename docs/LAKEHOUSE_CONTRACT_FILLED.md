# Lakehouse Contract — veri katmanı ↔ agent katmanı sözleşmesi

> **Durum:** Data ekibi tarafından nihai Lakehouse kararına göre doldurulmuş / hizalanmış sürüm  
> **Tarih:** 8 Eylül 2026  
> **Amaç:** Veri ve agent ekiplerinin birbirini beklemeden paralel çalışabilmesi ve entegrasyonda sözleşme uyuşmazlığı yaşamaması.

---

## 0. Ortak mimari kararı

Data tarafında P0 için seçilen temel yapı:

```text
BDDK / EVDS / URL / File
        ↓
Connector
        ↓
Immutable RAW + SHA-256
        ↓
Parser + Quality Gate
        ↓
Bronze (Parquet)
        ↓
SQL models
        ↓
Silver (Parquet, canonical long format)
        ↓
SQL models
        ↓
Gold (DuckDB native view/table)
        ↓
Meta Catalog + Lakehouse Tools
        ↓
Agent
```

**P0 teknoloji kararları:**
- Python 3.12
- Parquet
- DuckDB
- pandas yalnız ingestion / parsing sınırında
- SQL-first dönüşümler
- pytest; ilerleyen aşamada parse sınırında Pandera + Silver/Gold SQL assertion'ları
- DuckDB FTS/BM25 P0 semantic discovery; embedding/reranker P1

**P0 dışında:** DuckLake, dbt, LanceDB, Spark, Airflow, Iceberg, Delta.

Agent fiziksel Parquet yollarını veya RAW dosya yapısını bilmez. Agent yalnızca aşağıda tanımlanan Lakehouse Tool sözleşmesini ve semantic catalog bilgisini kullanır.

---

## 1. Canonical Lakehouse Tool sözleşmesi

Nihai mimaride iki ekip arasındaki **tek imza kaynağı** `contracts/lakehouse_tools.json` olacaktır.

P0 arayüzü:

```python
class LakehouseClient(Protocol):
    def search_series(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        k: int = 20,
    ) -> ToolResult: ...

    def describe(self, object_id: str) -> ToolResult: ...

    def get_series(
        self,
        ids: list[str],
        start: date,
        end: date,
        frequency: str | None = None,
        agg: str | None = None,
        transform: str | None = None,
        base_period: date | None = None,
    ) -> ToolResult: ...

    def execute_sql(
        self,
        sql: str,
        *,
        limit: int = 1000,
    ) -> ToolResult: ...

    def ingest_adhoc(
        self,
        uri: str,
        hint: str | None = None,
    ) -> ToolResult: ...
```

### Agent tarafındaki mevcut arayüzle uyumluluk

Agent repo'sunda şu yardımcı metotlar kullanılmaya devam edebilir:

```python
list_datasets()
get_dataset(dataset_id)
search_datasets(query, limit)
preview(dataset_id, n)
health()
```

Ancak bunlar **canonical inter-team contract değildir**; adapter/convenience metotlarıdır. Eşleşme:

| Agent helper | Canonical data karşılığı |
|---|---|
| `search_datasets()` | `search_series()` + `describe()` |
| `get_dataset()` | `describe()` |
| `preview()` | `get_series()` veya güvenli `execute_sql()` |
| `list_datasets()` | catalog/meta sorgusu |
| `health()` | adapter health check; data contract dışı yardımcı metot |

Böylece agent tarafı geliştirmeye devam edebilir; gerçek Lakehouse hazır olduğunda yalnız adapter değiştirilir.

---

## 2. `execute_sql` güvenlik sözleşmesi

LLM tarafından üretilen SQL **güvenilmez input** kabul edilir.

P0 şartları:
- Yalnız salt-okunur `SELECT` sorguları.
- `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `ATTACH`, `COPY`, `INSTALL`, `LOAD` reddedilir.
- Birden fazla SQL statement reddedilir.
- Dış dosya/ağ erişimi agent bağlantısında kapalıdır.
- `read_csv`, `read_parquet`, `read_text`, `read_blob`, `glob` gibi doğrudan dış erişim yolları agent'a açık değildir.
- Sonuç satır limiti uygulanır.
- Uygulama seviyesinde timeout uygulanacaktır.
- Agent yalnız `gold.*` ve izin verilen `meta.*` yüzeylerini sorgular; `raw/bronze/silver` doğrudan agent yüzeyi değildir.

---

## 3. Ortak dönüş zarfı (`ToolResult`)

Tüm Lakehouse fonksiyonları mümkün olduğunca aynı zarfı döndürür:

```json
{
  "ok": true,
  "rows": [],
  "columns": [],
  "row_count": 0,
  "truncated": false,
  "search_mode": null,
  "source_tier": null,
  "provenance": [],
  "caveats": [],
  "error": null
}
```

### `QueryProvenance`

Her sonuçta mümkün olduğu ölçüde aşağıdaki bilgiler taşınır:

```json
{
  "source_id": "bddk_monthly",
  "publisher": "BDDK",
  "source_url": "...",
  "fetched_at": "2026-09-08T12:00:00Z",
  "artifact_sha256": "...",
  "vintage_id": "bddk_monthly@2026-09-08",
  "rows_from_this_source": 66
}
```

Amaç, agent'ın kullandığı bir değerden kaynak URL'sine, çekim zamanına ve ham artifact hash'ine geri gidilebilmesidir.

---

## 4. Semantic Catalog sözleşmesi

Catalog Lakehouse içinde `meta.*` tablolarında tutulacaktır. Agent'ın doğru veri/seri seçebilmesi için minimum seri metadata'sı:

```yaml
series_id: evds:<RESMI_SERI_KODU>
source_id: evds
native_code: <RESMI_SERI_KODU>
name_tr: "..."
name_en: "..."
description: "..."
aliases:
  - "..."
tags:
  - "..."
unit: pct
frequency: weekly
week_anchor: FRI
measure_type: rate
semantic_confidence: verified | derived | unknown
semantic_source: manual | evds_flags | bddk_config | profiler
default_agg: avg
cumulative_reset: none
first_obs: 2021-01-01
last_obs: 2026-06-30
category_path: "..."
metadata_url: "..."
revision_policy_url: "..."
status: active
```

### Zorunlu anlam alanları

- `description`: Türkçe ve açıklayıcı.
- `aliases`: kullanıcı dilindeki eşanlamlılar.
- `frequency`: `daily | weekly | monthly | quarterly | ...`
- `unit`: kontrollü birim sözlüğü.
- `measure_type`: aşağıdaki ortak enum.
- `coverage`: `first_obs` / `last_obs` ile temsil edilir.
- `semantic_confidence`: semantiğin ne kadar güvenilir olduğunu agent'a görünür kılar.
- `default_agg`: yalnız doğrulanmış/derived metadata'dan gelir; bilinmeyen seride otomatik dönüşüm tetiklenmez.

---

## 5. Measure type sözlüğü

Ortak enum:

```text
stock
flow_periodic
flow_ytd
flow_cumulative
rate
ratio
index
count
unknown
```

### Varsayılan davranışlar

| Tip | Anlam | Downsample davranışı |
|---|---|---|
| `stock` | belirli andaki bakiye/seviye | dönem sonu (`last`) |
| `flow_periodic` | döneme ait akım | `sum` |
| `flow_ytd` | yılbaşından itibaren kümülatif akım | önce dönemsele çevir, sonra uygun agg |
| `flow_cumulative` | başlangıçtan itibaren kümülatif akım | önce fark al, sonra uygun agg |
| `rate` | faiz/oran | metadata'daki doğrulanmış `default_agg`; demo faiz serisinde aylık `avg` |
| `ratio` | pay/payda oranı | doğrudan `avg/sum` yasak; mümkünse pay/payda üzerinden yeniden hesapla |
| `index` | endeks | metadata metodolojisine göre `last`/doğrulanmış kural |
| `count` | adet/stok benzeri | çoğunlukla `last` |
| `unknown` | semantiği doğrulanmamış | otomatik frekans/kümülatif dönüşüm yapma |

**Önemli:** `rate` ve `index` için tek bir global kural hard-code edilmeyecektir. Kural metadata'dan gelir.

---

## 6. Kümülatiflik sözleşmesi

Nihai modelde kümülatiflik mümkün olduğunca `measure_type` içinde ifade edilir:

- `flow_ytd`: yıl içinde ardışık fark; yılın ilk dönemi aynen kalır.
- `flow_cumulative`: başlangıçtan itibaren ardışık fark.
- Diğer tiplerde otomatik `diff()` uygulanmaz.

Ek metadata gerekirse `cumulative_reset` alanı kullanılabilir:

```text
none
yearly
since_inception
```

**Stok serisine `diff()` uygulayıp "flow" üretmek yasaktır.**

---

## 7. Birim standardı

Canonical birim sözlüğü başlangıçta:

```text
TRY
TRY_th
TRY_mn
pct
index
count
```

Kurallar:
- `%12.5` → `12.5` saklanır; `0.125` saklanmaz.
- Orijinal kaynak değeri ve birimi kaybedilmez.
- Silver'da mümkün olduğunda şu alanlar korunur:
  - `value_original`
  - `unit_original`
  - `value`
  - `unit`
- Birim dönüşümü yapıldıysa derivation/provenance kaydı tutulur.

BDDK Tablo 3/4 ve Tablo 5 gibi farklı ölçekler source spike sırasında fixture/golden değerlerle ayrıca doğrulanacaktır.

---

## 8. Zaman standardı

- `date_key`: gözlemin ait olduğu dönem, `DATE`.
- `period_start`: dönem başlangıcı, nullable `DATE`.
- `period_end`: dönem sonu, nullable `DATE`.
- `fetched_at`: verinin indirildiği zaman; timezone-aware UTC timestamp.
- `published_at`: kaynak yayımlama zamanı biliniyorsa tutulur.
- `date_key` ile `fetched_at` aynı kavram değildir.
- Haftalık canonical takvim çapası: **Cuma**.
- Aylık görünümün dönem anahtarı: ay sonu.
- Düşük frekanstan yüksek frekansa varsayılan **upsample yapılmaz**.

---

## 9. ID sözleşmesi

### `source_id`

```text
evds
bddk_monthly
bddk_weekly
finturk
adhoc
```

Lowercase `snake_case`, stabil.

### `source dataset_id`

Connector/ingestion seviyesinde logical dataset kimliği:

```text
bddk_monthly_housing_loans
evds_housing_interest
```

### `series_id`

Seri için source namespace içeren stabil kimlik:

```text
evds:<RESMI_SERI_KODU>
bddk_monthly:<KALEM_KODU>:<TARAF>:<PARA_BIRIMI>
```

Gerçek kaynak kodları **tahmin edilmeyecek**; source access spike'ında doğrulandıktan sonra contract fixture'larına yazılacaktır.

### `vintage_id`

Örnek:

```text
bddk_monthly@2026-09-08
evds@2026-09-08
```

### `run_id`

UUID.

---

## 10. Connector ↔ Parser sözleşmesi

Bu kısım agent'ın doğrudan kullanacağı yüzey değildir; fakat provenance'ın doğru taşınması için iki ekip açısından bilinmelidir.

### `FetchSpec`

```python
@dataclass(frozen=True)
class FetchSpec:
    source_id: str
    dataset_id: str
    locator: str
    start_date: date | None
    end_date: date | None
    parameters: dict[str, Any]
    headers_ref: str | None
    timeout: float
    requested_at: datetime
```

### `FetchedAsset`

```python
@dataclass(frozen=True)
class FetchedAsset:
    source_id: str
    dataset_id: str
    locator: str
    media_type: str
    byte_size: int
    fetched_at: datetime
    artifact_sha256: str
    raw_path: Path
    http_status: int | None
    metadata: dict[str, Any]
```

### `ParsedBatch`

```python
@dataclass
class ParsedBatch:
    source_id: str
    dataset_id: str
    artifact_sha256: str
    schema_version: str
    dataframe: pd.DataFrame
    warnings: list[str]
```

Kurallar:
- Connector yalnız erişim + RAW artifact üretir; DataFrame üretmez.
- Parser ağa çıkmaz.
- Parser `FetchedAsset` provenance'ını kaybetmez.
- Parser Silver/Gold business semantiği uygulamaz.

---

## 11. RAW artifact sözleşmesi

Path:

```text
data/raw/{source_id}/{fetch_date}/{artifact_sha256}.{extension}
```

Kurallar:
- SHA-256 orijinal byte'lardan hesaplanır.
- RAW immutable'dır.
- Aynı içerik ikinci kez fiziksel olarak saklanmaz.
- Parse edilmiş veri RAW'a yazılmaz.
- Başarısız HTTP response başarılı artifact sayılmaz.
- Secret'lar metadata/log'a yazılmaz.

Minimum artifact metadata:

```text
artifact_sha256
source_id
dataset_id
locator
media_type
byte_size
http_status
fetched_at
raw_path
first_seen_at
last_seen_at
```

---

## 12. Bronze provenance kolonları

Her Bronze kaydı mümkün olduğunca şu teknik provenance alanlarını taşımalıdır:

```text
_source_id
_dataset_id
_artifact_sha
_fetched_at
_run_id
_vintage_id
```

İsimler iki data geliştiricisi arasında tek tiptir; alternatif isim (`file_hash`, `source_hash` vb.) kullanılmaz.

---

## 13. Silver canonical contract

`silver.fact_observation` minimum hedef şeması:

| Alan | Tip | Nullable | Anlam |
|---|---|---:|---|
| `observation_id` | VARCHAR/UUID | hayır | gözlem kimliği |
| `series_id` | VARCHAR | hayır | stabil seri kimliği |
| `entity_id` | VARCHAR | evet | banka grubu/şehir vb. entity |
| `date_key` | DATE | hayır | gözlemin ait olduğu dönem |
| `period_start` | DATE | evet | dönem başlangıcı |
| `period_end` | DATE | evet | dönem sonu |
| `frequency` | VARCHAR | hayır | daily/weekly/monthly/... |
| `value_original` | DOUBLE | evet | kaynaktan parse edilen değer |
| `unit_original` | VARCHAR | evet | kaynak birimi |
| `value` | DOUBLE | evet | canonical değer |
| `period_value` | DOUBLE | evet | kümülatif seriden türetilmiş dönemsel değer gerekiyorsa |
| `unit` | VARCHAR | hayır | canonical birim |
| `measure_type` | VARCHAR | hayır | ortak enum |
| `quality_flag` | VARCHAR | evet | verified/source_null/revised/... |
| `vintage_id` | VARCHAR | hayır | source vintage |
| `source_id` | VARCHAR | hayır | kaynak |
| `artifact_sha` | VARCHAR | hayır | RAW hash |
| `fetched_at` | TIMESTAMP | hayır | çekim zamanı |
| `run_id` | VARCHAR/UUID | hayır | pipeline run |

Silver **kanonik uzun format**tır.

---

## 14. Gold agent-facing veri modeli

Burada agent dokümanındaki “Gold tamamen uzun olsun” ifadesini şu şekilde netleştiriyoruz:

- **Silver kesin olarak uzun/tidy formatta** (`fact_observation`).
- **Gold soru başına hard-code edilmiş geniş tablolar değildir.**
- Gold, agent için anlamı çözülmüş, frekansı hizalanmış ve gerekli boyutları açık kolonlara çıkarmış **curated view'lar** sunar.
- Yeni her seri için yeni kolon açılmaz; ölçüler `series_id / measure / value` üzerinden satır olarak kalır.

P0 hedef Gold yüzeyleri:

```text
gold.v_bddk_bulletin
gold.v_evds_series
gold.v_series_monthly
gold.v_series_weekly
```

P1/sonraki:

```text
gold.v_finturk_city
gold.v_cpi_spliced
gold.v_series_quarterly
```

Örnek agent-facing Gold satırı:

```text
period_end | source_id | series_id | measure | value | unit | measure_type | quality_flag | artifact_sha | fetched_at
```

Agent bu view'ları `execute_sql()` ile join/pivot edebilir.

---

## 15. Agent-facing `DatasetSpec` / object description

Agent tarafında mevcut `DatasetSpec` korunacaksa aşağıdaki minimum alanlarla doldurulacaktır:

```yaml
dataset_id: gold.v_series_monthly
description: >
  BDDK ve EVDS kaynaklarından gelen, aylık frekansta güvenli biçimde hizalanmış
  zaman serilerini uzun formatta sunan agent-facing Gold görünümü.
frequency: monthly
time_column: period_end
grain:
  - period_end
  - series_id
  - entity_id
coverage:
  start: 2021-01-01
  end: 2026-06-30
notes:
  - Düşük frekanstan yüksek frekansa otomatik upsample yapılmaz.
  - Semantiği unknown olan serilerde otomatik aggregation uygulanmaz.
  - Provenance kolonları sonuçla birlikte korunur.
columns:
  - name: period_end
    type: date
    description: Canonical aylık dönem sonu.
  - name: series_id
    type: string
    description: Stabil seri kimliği.
  - name: value
    type: float
    description: Canonical değer.
  - name: unit
    type: string
    description: Canonical birim.
  - name: measure_type
    type: string
    description: stock/flow_periodic/flow_ytd/flow_cumulative/rate/ratio/index/count/unknown.
  - name: quality_flag
    type: string
    nullable: true
    description: Veri kalite/derivation durumu.
  - name: source_id
    type: string
    description: Kaynak kimliği.
  - name: artifact_sha
    type: string
    description: RAW artifact SHA-256.
```

**Not:** Agent tarafındaki `ColumnSpec.semantic_type`, `cumulative`, `unit_multiplier` gibi alanlar gerekiyorsa metadata adapter tarafından `meta.series` üzerinden türetilir. Canonical veri ekibi modeli `measure_type`, `unit`, `default_agg`, `cumulative_reset` alanlarını kullanır.

---

## 16. İlk vertical slice — iki ekip için ortak entegrasyon hedefi

İlk gerçek uçtan uca kullanım:

> **2021–2026 arasında konut kredisi bakiyesi ile konut kredisi faiz oranını aylık olarak karşılaştır.**

Data tarafı şu çıktıları sağlayacaktır:

1. BDDK konut kredisi RAW + hash.
2. BDDK Bronze.
3. EVDS konut kredisi faiz RAW + hash.
4. EVDS Bronze.
5. İki serinin `silver.fact_observation` karşılığı.
6. Konut kredisi `measure_type=stock`.
7. Faiz `measure_type=rate`.
8. Faiz serisi için doğrulanmış haftalık→aylık aggregation (ilk demo serisinde `avg`).
9. `gold.v_series_monthly` üzerinden ikisinin aynı aylık grain'de sorgulanması.
10. Sonuçla birlikte provenance + caveat.

Agent ekibinin bu vertical slice için bütün 5 yıllık katalogu beklemesi gerekmez; iki doğrulanmış seri ve birkaç yüz satırlık örnek yeterlidir.

---

## 17. İlk handoff sırası

### Handoff 0 — contract/stub

Data ekibi paylaşacak:
- `contracts/lakehouse_tools.json`
- `DatasetSpec` / object description örneği
- `ToolResult` / provenance / error şeması
- stub LakehouseClient
- contract testleri

### Handoff 1 — ilk gerçek veri

Data ekibi paylaşacak:
- `gold.v_series_monthly`
- BDDK housing loans serisi
- EVDS housing-interest serisi
- ilgili `meta.series` kayıtları
- provenance örneği

### Handoff 2 — gerçek Lakehouse Tool

P0 fonksiyonları canlı:
- `search_series`
- `describe`
- `get_series`
- `execute_sql`
- `ingest_adhoc`

---

## 18. Hata sözleşmesi

Minimum hata kodları:

```text
SOURCE_UNAVAILABLE
FETCH_TIMEOUT
HTTP_ERROR
UNSUPPORTED_FORMAT
PARSE_FAILED
SCHEMA_MISMATCH
EMPTY_DATASET
OBSERVATION_COUNT_MISMATCH
QUALITY_FAILED
SERIES_NOT_FOUND
SERIES_NOT_MATERIALIZED
SEMANTIC_VIOLATION
UNSAFE_SQL
QUERY_TIMEOUT
```

Minimum error payload:

```json
{
  "error_code": "SEMANTIC_VIOLATION",
  "message": "Ratio serisine doğrudan avg uygulanamaz.",
  "source_id": "bddk_monthly",
  "dataset_id": null,
  "retryable": false,
  "hint": "Pay ve paydayı ayrı seriler olarak getirip oranı yeniden hesaplayın."
}
```

Agent'ın hatayı düzeltebilmesi için mümkün olduğunda `hint` döndürülür.

---

## 19. İlk arama modu

P0:

```text
Exact match
+ aliases
+ metadata filters
+ DuckDB FTS / BM25 (Türkçe)
```

Dönüşte:

```text
search_mode = "lexical"
```

P1'de Kloudeks embedding + reranker eklenirse:

```text
search_mode = "hybrid"
```

Kloudeks/embedding erişilemezse lexical yol çalışmaya devam eder.

---

## 20. BDDK erişimi — agent dokümanından gelen bilgi ve data ekibi kararı

Agent tarafındaki dokümanda aşağıdaki BDDK JSON endpoint'lerinin **2026-09-08 tarihinde canlı doğrulandığı** belirtilmiştir:

```text
POST /BultenAylik/tr/Home/BasitRaporGetir
POST /BultenFinturk/tr/Home/VeriGetir
POST /BultenHaftalik/tr/Home/KiyaslamaJsonGetir
```

Bu bilgiler **source access spike'ında data ekibi tarafından fixture/golden değer ile yeniden doğrulanacaktır**. Üretim contract'ına doğrulamadan gerçek tablo/kalem kodu yazılmayacaktır.

Ayrıca:
- JSON yolu ana taşıma olarak değerlendirilebilir.
- Excel yolu fallback olarak korunacaktır.
- SSL doğrulamasını global olarak `verify=False` yapma kararı şu anda contract değildir; mümkünse uygun CA/sertifika yaklaşımı tercih edilir. Gerekirse source spike sonucuna göre yalnız BDDK connector seviyesinde kontrollü fallback uygulanır ve uyarı/log bırakılır.
- Alt toplam satırları `notes` / metadata ile işaretlenecek; toplam + alt kalem birlikte toplanmayacaktır.

---

## 21. Şimdilik açık kalan konular

Aşağıdakiler henüz hard-code edilmeyecek:

1. Gerçek EVDS konut kredisi faiz seri kodu — source spike ile doğrulanacak.
2. Gerçek BDDK konut kredisi kalem kodu/taraf/para birimi kombinasyonu — source spike ile doğrulanacak.
3. Tüm EVDS serilerinin materyalize kapsamı — ilk vertical slice'tan sonra genişletilecek.
4. Embedding/reranker — P1.
5. FinTürk — P1; çeyreklik grain korunacak.
6. Ad-hoc PDF/OCR extraction detayları — `ingest_adhoc` contract P0, gelişmiş OCR sonraki adım.

---

## 22. Definition of Done — data ↔ agent entegrasyonu

Bir inter-team teslimat ancak şu koşullarda tamamlanmış sayılır:

- Contract dosyası güncel.
- Breaking signature değişikliği iki ekip tarafından onaylanmış.
- Contract testleri yeşil.
- Agent stub ile gerçek implementasyon aynı imzaya sahip.
- SQL salt-okunur güvenlik testleri geçiyor.
- Agent'a dönen sonuç provenance içeriyor.
- Semantiği bilinmeyen seri için sistem veri uydurmuyor.
- Kaynak/seri ID'leri tahmin edilmemiş, doğrulanmış.
- Secret/API key/cookie log veya repoya girmiyor.

---

## 23. Kısa özet — agent ekibinin güvenebileceği garantiler

Data ekibi agent tarafına şu garantileri verir:

1. Agent fiziksel storage yapısını bilmek zorunda değildir.
2. Agent'a verilen Gold yüzeyi SQL ile sorgulanabilir olacaktır.
3. Her kritik seri `unit`, `frequency`, `measure_type`, coverage ve provenance ile tanımlanacaktır.
4. Kümülatif/frekans dönüşümleri LLM'e bırakılmayacak; veri katmanında deterministic uygulanacaktır.
5. Güvenli olmayan SQL çalıştırılmayacaktır.
6. Semantiği belirsiz veride sistem otomatik dönüşüm yapmayacak; caveat/hata döndürecektir.
7. İlk entegrasyon hedefi BDDK konut kredisi + EVDS konut kredisi faizi aylık karşılaştırmasıdır.

