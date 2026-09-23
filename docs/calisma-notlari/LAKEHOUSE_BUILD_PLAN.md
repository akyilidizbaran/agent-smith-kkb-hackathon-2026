# Lakehouse İnşa Planı — sıradaki adım

> **Kime:** Veri ekibi · **Kimden:** Agent katmanı
> **Tarih:** 9 Eylül 2026 · **Teslime:** 11 gün
> Bu doküman `feature/lakehouse-integration` (bc2f106) incelemesi üzerine yazıldı.
> Mevcut mimari kararlarınızı (Parquet + DuckDB, RAW→Bronze→Silver→Gold, SQL-first)
> değiştirmiyor; onların üstüne ne eklenmesi gerektiğini tarif ediyor.

---

## 0. Kurduğunuz şey sağlam

Önce bunu söylemek gerekiyor, çünkü aşağıdaki liste uzun: RAW immutability, SHA-256
artifact takibi, `meta.artifact` / `meta.run` / `meta.dataset_version` üçlüsü, sertleştirilmiş
salt-okunur bağlantı ve SQL Guard — bunlar sağlam bir temel. Özellikle
`_verify_untrusted_connection` yaklaşımı (SQL Guard'ı tek bariyer bırakmamak) agent
tarafındakinden ileri; onu bizim tarafa da alıyoruz.

Aşağıdakiler bu temelin üstüne gelen katmanlar.

---

## 1. Öncelik: katalog önce, Silver sonra

**Yapılacak sıra:** `meta.series` → Silver → Gold

Bu, sezgiye aykırı görünebilir ama kendi şemanız bunu gerektiriyor. `fact_observation.yml`
içinde:

```yaml
- name: measure_type
  nullable: false
```

Silver satırları yazılırken bu alan dolmak zorunda. O bilgi veriden çıkmaz — bir serinin
stok mu akım mı olduğunu sayılara bakarak anlayamazsınız. Kaynağı katalogdur.

Silver'ı önce yazıp katalogu sonra eklemek, Silver'ı yeniden üretmek demektir.

**Katalog bir veri katmanı değildir.** Bronze/Silver/Gold'un yanında duran, onları besleyen
dikey bir katmandır. Sizde zaten iki tür metadata var ve ikisi ters yönde çalışıyor:

| | Operasyonel meta | Semantic catalog |
|---|---|---|
| Nereden gelir | veriden **otomatik türer** | **insan yazar** |
| Örnek | `content_hash`, `row_count`, `fetched_at` | `measure_type`, `unit`, `aliases` |
| Sizde | ✅ var | ❌ yok |

---

## 2. `meta.series` — önerilen DDL

`sql/bootstrap/002_meta_tables.sql` içine eklenebilir:

```sql
CREATE TABLE IF NOT EXISTS meta.series (
    series_id       VARCHAR PRIMARY KEY,   -- 'evds:TP.FG.J0', 'bddk_monthly:t4_konut'
    source_id       VARCHAR NOT NULL,      -- meta.source'a FK
    native_code     VARCHAR,               -- kaynaktaki resmi kod
    dataset_id      VARCHAR NOT NULL,

    name_tr         VARCHAR NOT NULL,
    description     VARCHAR NOT NULL,      -- Türkçe, açıklayıcı; agent seriyi buradan tanır
    aliases         VARCHAR[],             -- ['konut kredisi','mortgage','ev kredisi']
    tags            VARCHAR[],

    frequency       VARCHAR NOT NULL,      -- daily|weekly|monthly|quarterly|yearly
    week_anchor     VARCHAR,               -- haftalık seriler için: 'FRI'
    unit            VARCHAR NOT NULL,      -- TRY | TRY_th | TRY_mn | pct | index | count
    measure_type    VARCHAR NOT NULL,      -- aşağıdaki sözlük
    default_agg     VARCHAR,               -- last | sum | avg — yalnız doğrulanmışsa
    cumulative_reset VARCHAR,              -- none | yearly | since_inception

    semantic_confidence VARCHAR NOT NULL,  -- verified | derived | unknown
    semantic_source     VARCHAR,           -- manual | source_docs | profiler

    first_obs       DATE,
    last_obs        DATE,
    metadata_url    VARCHAR,
    status          VARCHAR NOT NULL DEFAULT 'active',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);
```

### Doldurulması en kritik üç alan

**`aliases`** — Agent'ın seri seçimindeki isabetini en çok bu alan belirliyor. Ölçtük:
agent tarafında bir aday listesi verildiğinde model doğru seçiyor, verilmediğinde kalem
adı uyduruyordu. Kullanıcı "mortgage", "ev kredisi", "konut kredisi" diyebilir — hepsini yazın.

**`measure_type`** — Frekans dönüşümünün girdisi. Yanlışsa aylık→çeyreklik dönüşümü
*sessizce* yanlış sonuç verir. Sizin sözlüğünüz (P0 dokümanındaki) doğru ve bizimkinden iyi,
çünkü kümülatiflik tipin içine gömülü:

```
stock            → dönem sonu (last)
flow_periodic    → sum
flow_ytd         → yıl içinde ardışık fark, sonra agg
flow_cumulative  → başlangıçtan itibaren fark, sonra agg
rate             → metadata'daki default_agg (çoğunlukla avg)
ratio            → pay/payda üzerinden YENİDEN hesapla, ortalama alma
index            → metodolojiye göre
count            → last
unknown          → otomatik dönüşüm YAPMA
```

**`semantic_confidence`** — `unknown` işaretli bir seride agent otomatik frekans/kümülatif
dönüşümü tetiklememeli. Bu alan, emin olmadığınız serileri dürüstçe işaretlemenizi sağlar;
boş bırakmaktan iyidir.

### Doldurma yöntemi

Katalog kod değil **içerik**. Bir YAML/CSV dosyasından yüklemek en pratiği:

```
lakehouse-core/catalog/series/evds.yml
lakehouse-core/catalog/series/bddk_monthly.yml
```

Bootstrap sırasında `meta.series`'e yüklenir. Böylece katalog versiyonlanır, kod
incelemesinde görünür ve elle düzenlenebilir.

> Bu yatırımın getirisi ölçülmüş: yalnız şema verilen bir modelde doğruluk %8,3;
> iş bağlamı dokümanı eklendiğinde %78,3. Frontier modellerde 4 KB'lık bir semantic
> layer dokümanı +17–23 puan kazandırıyor. Yani buradaki kazanç kod değil, **metin**
> yazarak elde ediliyor.

---

## 3. Silver — nasıl saklanmalı

`fact_observation.yml` şemanız doğru: uzun format, `series_id` + `date_key` + `value`.
Eklenmesi gereken kurallar:

### 3.1 Ham değer kaybolmamalı

```
value_original   +  unit_original     ← kaynaktan geldiği gibi
value            +  unit              ← kanonik birime çevrilmiş
```

Birim dönüşümü yapıldıysa provenance'a yazılmalı. Somut sebep: BDDK aylık bülteninde
**Tablo 3/4 "milyon TL", Tablo 5 "bin TL"** yayınlıyor. Aynı bültende iki farklı ölçek var.

### 3.2 Dönem anahtarı tek kural

`date_key` = **dönem sonu**, istisnasız. Aylık seride ayın son günü, haftalık seride Cuma.

Bu kritik çünkü join'ler buna dayanıyor ve uyumsuzluk **sessiz** bir hatadır: satırlar
eşleşmez, sütun boş gelir, hiçbir hata mesajı çıkmaz. Agent tarafındaki seed şu an ayın
ilk gününü kullanıyor; onu sizin kuralınıza uyarlıyoruz.

`period_start` / `period_end` alanları doldurulabildiğinde doldurulmalı — özellikle
haftalık serilerde hangi günleri kapsadığı bilgisi analizde gerekiyor.

### 3.3 Kümülatif ayrıştırma Silver'da YAPILMAZ

Silver kanonik ve **ham**tır. `flow_ytd` bir seri Silver'da kümülatif haliyle durur;
ayrıştırma bir dönüşümdür ve Gold'a aittir.

Sebep: ayrıştırılmış değeri saklarsanız orijinali kaybedersiniz ve ayrıştırma kuralı
sonradan yanlış çıkarsa geri dönemezsiniz. Ayrıca aynı seri farklı analizlerde farklı
biçimlerde gerekebilir.

**Stok serisine `diff()` uygulayıp "flow" üretmek yasaktır.** Kredi bakiyesindeki aylık
değişim, o ay kullandırılan kredi değildir (geri ödemeler, tahsilatlar, kur etkisi vardır).

### 3.4 Fiziksel düzen

```
silver/
  source_id=bddk_monthly/
    dataset_id=t4_tuketici_kredileri/
      year=2025/
        part-0000.parquet
```

Partition anahtarları sorgu filtrelerinizle aynı olmalı: `source_id`, `dataset_id`, `year`.
Ay bazında bölmek küçük veri setlerinde çok sayıda ufak dosya üretir; yıl yeterli.

### 3.5 İdempotency

Aynı vintage yeniden yüklendiğinde satır **çoğalmamalı**. `meta.dataset_version` içindeki
`content_hash` zaten bunun için var: hash değişmemişse yükleme atlanmalı, değişmişse yeni
vintage yazılıp eskisi `is_current = false` yapılmalı.

Silver satırlarında `vintage_id` taşınırsa "bu rakam hangi indirmeden geldi" sorusu ham
dosyaya kadar izlenebilir olur — güven katmanının en güçlü hali budur.

---

## 4. Gold — agent'ın gördüğü yüzey

Agent yalnızca `gold.*` ve izin verilen `meta.*` yüzeylerini sorgular (kendi P0
dokümanınızdaki karar). Yani Gold, agent açısından **API'dir**.

### 4.1 Ne olmalı

- **DuckDB view yeterli**, materyalize tablo şart değil. Veri hacmimiz küçük (5 yıl,
  aylık/haftalık seriler); view basitlik ve tazelik kazandırır. Sorgu yavaşlarsa
  materyalize edilir.
- Her Gold nesnesi `meta.series`'te bir karşılığa sahip olmalı. Katalogda görünmeyen bir
  tabloyu agent bulamaz — dolayısıyla var olmasının anlamı yoktur.
- **Geniş değil uzun tutun.** Her yeni kırılım için kolon açmak yerine satır ekleyin.
  Agent pivot yapabilir; bilmediği kolon adını tahmin edemez.

### 4.2 Burada yapılan dönüşümler

| Dönüşüm | Nerede | Not |
|---|---|---|
| Kümülatif ayrıştırma | Gold | `measure_type`'a göre |
| Frekans dönüşümü (downsample) | Gold | `default_agg`'e göre; `unknown` ise yapma |
| Birim normalleştirme | Silver | ham değer korunarak |
| Alt toplam işaretleme | Silver veya Gold | aşağıya bakın |

### 4.3 Alt toplam tuzağı

BDDK tablolarında `Tüketici Kredileri (2+3+4)` gibi satırlar **alt toplamdır**. Alt
kalemlerle birlikte toplanırsa mükerrer sayım olur — agent tarafında bunu bilfiil yaşadık,
model üç konut kalemini birden toplayıp yanlış sonuç üretti.

İyi haber: kaynak bu bilgiyi zaten veriyor. **BDDK alt toplam satırlarını `bold` font ile
işaretliyor** (JSON'da `cell[3] == "bold"`). Bu sinyali bir bayrağa çevirin
(`is_subtotal BOOLEAN`), yoksa her tüketici bunu yeniden keşfetmek zorunda kalır.

### 4.4 Upsample yapmayın

Düşük frekanstan yüksek frekansa çevirme (aylık → günlük) varsayılan olarak yapılmamalı.
Aylık bir seriyi güne yaymak, olmayan bir hassasiyet uydurmaktır. Kullanıcı açıkça isterse
ve yöntem belirtilirse ayrı konudur.

---

## 5. `LakehouseClient` — agent'ın bağlanacağı arayüz

`src/lakehouse/tools/` şu an boş. Agent'ı bağlamak için gereken tek şey bu.

```python
class LakehouseClient(Protocol):
    def list_datasets(self) -> list[DatasetSpec]: ...
    def get_dataset(self, dataset_id: str) -> DatasetSpec: ...
    def search_datasets(self, query: str, limit: int = 5) -> list[DatasetSpec]: ...
    def execute_sql(self, sql: str, *, max_rows: int = 10_000) -> QueryResult: ...
    def preview(self, dataset_id: str, n: int = 5) -> QueryResult: ...
    def health(self) -> dict[str, Any]: ...
```

Protokolü miras almanız gerekmiyor; aynı imzalara sahip bir sınıf yeterli.

**İyi haber:** altı metottan ikisi bugün karşılanabilir. `execute_sql` için
`QueryExecutor.execute` zaten hazır; `health` için bağlantı + `meta.run` yeterli. Kalan
dördü yalnızca `meta.series`'i okur — katalog gelince her biri birkaç satır.

`search_datasets` için başlangıçta DuckDB FTS/BM25 yeterli (sizin P0 kararınız). Agent
tarafında ölçtük: **saf embedding araması keyword filtresinden kötü çıktı** —
"konut kredisi" sorgusunda `Takipteki Konut Kredileri` (0,902) doğru cevabın
(`Tüketici Kredileri - Konut`, 0,900) önüne geçti. Embedding/reranker'ı erteleyin;
tetikleyicisi katalogun büyümesi olsun.

### Dönüş zarfı

Sonuç, `QueryProvenance` taşımalı: çalıştırılan SQL, kaynak adı ve URL, satır sayısı,
uyarılar. Şartnamedeki *"Güven katmanı: Kaynak gösterimi – İzlenebilirlik – Doğruluk
Kontrolü"* maddesinin karşılığı bu ve puanlanacak.

---

## 6. Yarışma kısıtlarından doğan hatırlatmalar

- **Hazır/lisanslı bulut Lakehouse yasak** (Snowflake, BigQuery vb.) — kod incelenerek
  tespit ediliyor, eleme sebebi. Mevcut yaklaşımınız (Parquet + DuckDB) doğru.
- **`execute_sql` salt-okunur** kalmalı; çoklu statement, dış dosya erişimi
  (`read_csv`, `read_parquet`, `glob`) agent bağlantısında kapalı. Sizde zaten bu şekilde.
- **Platform jenerik olmalı.** "İçini boşaltıp sağlık verisiyle çalıştırın" denirse
  çalışmalı. Pratik testi: kod içinde `konut`, `kredi`, `BDDK` gibi terimler
  **connector/parser dışında** geçmemeli. Agent tarafında bunu bir teste bağladık
  (`tests/test_domain_profile.py`); benzer bir kontrol veri tarafında da işe yarar.
- **API key'leri repoya girmemeli**, private repo olsa bile. `.env` + `.gitignore`.

---

## 7. Bugün için kontrol listesi

Sıra önemli; her madde bir sonrakini besliyor.

- [ ] `meta.series` tablosunu `002_meta_tables.sql`'e ekle
- [ ] `catalog/series/*.yml` dosya düzenini kur, bootstrap'ta yükle
- [ ] EVDS'den seçilecek serileri kararlaştır ve katalogla — en az: **TÜFE, konut kredisi
      faiz oranı, konut fiyat endeksi** (agent tarafındaki enflasyondan arındırma
      senaryosu bunlara bağlı)
- [ ] BDDK aylık bültenden en az Tablo 3 ve 4'ü katalogla
- [ ] `is_subtotal` bayrağını BDDK parser'ında `bold` sinyalinden üret
- [ ] Silver'a bir dataset yaz: `value_original` + `value`, `date_key` = dönem sonu
- [ ] `gold.*` altında bir view aç, `meta.series` ile eşleştir
- [ ] `tools/` altına `LakehouseClient` uygulaması — `execute_sql` ve `health` ile başla

**Uçtan uca doğrulama:** tek bir seri (ör. konut kredisi) RAW'dan Gold'a kadar gidip
`meta.series`'te görünüyorsa, hat çalışıyor demektir. Beş yıllık tam derinlik bunun için
gerekmiyor — bir yıl yeter, kalanı aynı kodla gelir.

---

## 8. Bizim taraftaki uyum işleri

Bunlar agent ekibinde, sizden bir şey beklemiyor:

- `date_key` kuralına uyum (dönem başı → dönem sonu)
- `measure_type` sözlüğüne geçiş (bizim `semantic_type` + `cumulative` ikilisi yerine
  sizin tek enum'unuz)
- Sertleştirilmiş bağlantı doğrulamasını agent tarafındaki DuckDB adaptörüne alma

Sorular ve karşılıklı kontrol için: `docs/LAKEHOUSE_CONTRACT.md` (arayüz sözleşmesi),
`docs/adr/` (agent tarafındaki kararların gerekçeleri).
