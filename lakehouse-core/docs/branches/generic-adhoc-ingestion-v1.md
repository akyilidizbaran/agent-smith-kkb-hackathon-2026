# `feature/generic-adhoc-ingestion-v1`

> **Amaç:** P1 Generic + Ad-hoc Ingestion paketini tek çalışan vertical slice olarak teslim
> etmek — `GenericTabularConnector`, `GenericTabularParser`, programatik `register_series` ve
> izole `adhoc.fact_observation`.
>
> **Taban:** `feature/gold-functions-v1` @ `994654f`
> **Kapsam dışı:** CLI, EVDS pencereleme, katalog genişletme, FinTürk, PDF/OCR/VLM, agent
> kodu, dashboard, embedding/retrieval, otomatik semantic inference, draft → active promotion,
> Gold değişikliği, Silver snapshot davranışı.

Sözleşmelerin tamamı [`docs/generic-ingestion-contract.md`](../generic-ingestion-contract.md)
ve [`docs/adhoc-publication-contract.md`](../adhoc-publication-contract.md) içinde. Bu belge
**neden öyle yapıldığını** ve nelerin bilinçli olarak dışarıda bırakıldığını anlatır.

## Ön uygulama değerlendirmesi

Mevcut mimari bu işi büyük ölçüde zaten taşıyor:

- `RawStorage` değişmezliği, SHA-256'yı, atomik yazımı ve dedup'ı hallediyor — olduğu gibi
  kullanıldı.
- `IngestionPipeline` connector → artifact → parser → Bronze zincirini `run_id` ve warning
  kalıcılığıyla birlikte kuruyor. İnceleme düzeltmesinde ad-hoc sonuçlar için zorunlu run_id
  doğrulaması eklendi; legacy kaynakların eski constructor sözleşmesi korundu. Ek turda her
  indirilen artifact, parse'tan önce `meta.run_artifact` ile run'a kalıcı olarak bağlandı;
  ad-hoc yayın bu bağı ve bağdaki `fetched_at` değerini zorunlu kılıyor.
- `catalog/series.py` içindeki `_parse_entry` on sekiz kuralın tek kaynağı. `register_series`
  bunu kopyalamak yerine `build_series_record` adıyla dışa açıp yeniden kullanıyor.

Baran'ın önerisinde eksik veya riskli bulduğumuz noktalar:

1. **`adhoc.fact_observation` "aynı şema, ayrı şema adı" olarak öneriliyordu ama neden ayrı
   olması gerektiği yazılmamıştı.** Asıl gerekçe Silver'ın tam-snapshot değiştirmesi: ad-hoc
   bir seriyi Silver'a eklemek her curated seriyi yeniden üretmeyi gerektirirdi ve bir mapping
   hatası curated veriyi de düşürürdü. Bunu sözleşmeye yazdık.
2. **`register_series(record, *, confidence="derived", ...)` imzası, parametrelerin gerçekten
   seçilebilir olduğu izlenimi veriyor.** Seçilebilir olmamalılar. İmzada duruyorlar ama
   `derived`/`profiler`/`draft` dışındaki her değer reddediliyor, ve `record` içine gömülmüş
   bir `verified` de doğrulamadan önce eziliyor.
3. **Önerin format tespitine değinmiyordu.** Content-Type tek başına güvenilmez; workbook
   olarak servis edilen bir `.csv` sessizce mojibake üretirdi. Signature > explicit >
   (extension ∧ content-type) sıralaması ve çelişkide reddetme eklendi.
4. **SSRF sınırı önerinin kapsamında yoktu.** URL alan bir connector, üzerinde çalıştığı
   makineyi ve yanındaki cloud metadata servisini okumanın bir yolu hâline gelebilir. Tam bir
   adres/redirect/streaming sınırı eklendi — ve kapatılamayan kısmı (DNS rebinding) dürüstçe
   belgelendi.

## Kritik kararlar

### `source_id` neden yalnız `adhoc`

Tek bir ayrılmış namespace, provenance sorusunu yapısal hâle getiriyor: `adhoc:` ile başlayan
bir seri oturum içinde birinin verdiği dosyadan geldi ve ulaşabileceği tek fact tablosu
`adhoc.fact_observation`. Burada serbest `source_id` kabul etmek, kullanıcı verisinin
incelenmiş bir kaynağın kimliğini ödünç almasına izin verirdi — namespace'in var olma sebebi
tam da bu karışıklığı önlemek.

### HTML için neden yeni bağımlılık yok

`pandas.read_html` lxml, ya da html5lib + BeautifulSoup istiyor. Bir `<table>` okumak için üç
paket kötü bir takas; ama asıl sebep paket sayısı değil: stdlib `html.parser` üzerine yazılan
~200 satırlık çıkarıcı, **ne yapmadığını** kesin olarak söyleyebiliyor. `<script>`/`<style>`
içeriği atılıyor, dosyada hiç URL işleme kodu yok (yani `<img>`, `<link>`, `<iframe>` politika
gereği değil **yapısal olarak** etkisiz), ve `rowspan`/`colspan` genişletmesi bizim kontrolümüzde.

Takas: bozuk bir sayfa tarayıcının render ettiğinden farklı çıkarılabilir. Kabul edilebilir —
burada yayımlanmış veri tabloları okunuyor, keyfi web sayfaları değil.

### Neden yalnız `openpyxl`

XLSX, stdlib okuyucusu olmayan tek desteklenen format. `read_only=True`, `data_only=False`
ve `keep_links=False` ile açılıyor. Workbook'un herhangi bir yerinde formül varsa açık hata
üretiliyor; kullanıcıdan dışarıda hesaplayıp yalnız değerler içeren XLSX/CSV kaydetmesi isteniyor.
Formül çalıştırılmıyor ve eksik cached sonuç sessizce NULL olmuyor.

### Tek doğrulayıcı

`build_series_container` gibi ikinci bir yüzey açmak yerine `_parse_entry` doğrudan
`build_series_record` adıyla dışa açıldı. YAML yolu ile programatik yol aynı fonksiyonu
çağırıyor; on sekiz kuralın iki kopyası yok, dolayısıyla ayrışamazlar.

### Belirsizlik = reddetme

Her formatın kendi belirsizliği var ve hiçbirinde varsayılan seçim yapılmıyor: ikili
delimiter, birden fazla JSON records dizisi, birden fazla görünür sheet, birden fazla HTML
tablosu. Hepsi ilgili parametreyi isteyerek reddediliyor. Gerekçe her yerde aynı: noktalı
virgüllü bir dosyayı virgülle okumak hata değil, tek sütunluk birleşik metin üretir.

## Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `sql/bootstrap/020_adhoc_observations.sql` | **Yeni** — `adhoc` şeması ve fact tablosu, CHECK kısıtlarıyla |
| `src/lakehouse/generic/__init__.py` | **Yeni** |
| `src/lakehouse/generic/formats.py` | **Yeni** — dört sinyalli format çözümü |
| `src/lakehouse/generic/_access.py` | **Yeni** — yerel root allow-list ve URL adres kontrolü |
| `src/lakehouse/generic/connector.py` | **Yeni** — `GenericTabularConnector` |
| `src/lakehouse/generic/_html.py` | **Yeni** — stdlib statik tablo çıkarıcı |
| `src/lakehouse/generic/parser.py` | **Yeni** — `GenericTabularParser` |
| `src/lakehouse/generic/config.py` | **Yeni** — kanonik parser allow-list ve hash |
| `src/lakehouse/contracts/models.py`, `src/lakehouse/storage/parquet.py` | Parser hash'i için additive kimlik alanı |
| `src/lakehouse/ingestion/pipeline.py` | Ad-hoc run_id doğrulaması; artifact kaydından hemen sonra run–artifact bağı |
| `src/lakehouse/ingestion/observability.py` | `RunArtifactLink`, `RunRepository.link_artifact`, `epoch_us` yardımcıları (additive) |
| `sql/bootstrap/011_run_artifact.sql` | **Yeni** — `meta.run_artifact` junction tablosu (additive) |
| `src/lakehouse/catalog/registration.py` | **Yeni** — `register_series` |
| `src/lakehouse/adhoc/__init__.py`, `adhoc/publication.py` | **Yeni** — mapping ve yayın |
| `src/lakehouse/errors.py` | **Ortak sözleşme** — `ACCESS_DENIED` kodu eklendi (additive) |
| `src/lakehouse/catalog/series.py` | `build_series_record` dışa açıldı (additive) |
| `pyproject.toml`, `uv.lock` | **Ortak sözleşme** — `openpyxl` eklendi |
| `tests/generic/*`, `tests/adhoc/*` | **Yeni** — güncel sonuçlar inceleme raporunda |
| `docs/generic-ingestion-contract.md`, `docs/adhoc-publication-contract.md` | **Yeni** |
| `docs/branches/generic-adhoc-ingestion-v1.md` | **Yeni** — bu belge |

Mevcut connector'lar, parser'lar, Silver, Gold, katalog YAML'ları, şemalar, `001–010`
migration'ları, mevcut fixture'lar ve her iki README **değişmedi**.

## Ortak sözleşme değişiklikleri

Başlangıç eklemelerine, incelemede gerekli kimlik alanları ve ad-hoc run zorunluluğu eklendi:

1. **`src/lakehouse/errors.py` → `ACCESS_DENIED`.** Politika reddi (izinli root dışı yol,
   private URL, boyut aşımı) ile `SOURCE_UNAVAILABLE`'ın "erişilemedi"si farklı şeyler; agent
   "izinli değilim" ile "kaynak kapalı"yı ayırt edebilmeli, çünkü yalnız biri retry veya
   kullanıcıya kaynak sorunu olarak bildirmeye değer.
2. **`pyproject.toml` + `uv.lock` → `openpyxl` (3.1.5, `et-xmlfile` ile birlikte).** XLSX'in
   stdlib alternatifi yok. lxml, html5lib ve beautifulsoup4 bilinçli olarak **eklenmedi**.

3. **`contracts/models.py` + `storage/parquet.py`.** Opsiyonel parser konfigürasyon hash'i
   Bronze metadata ve yol kimliğine eklendi. Alan yokken eski kaynak/Silver davranışı korunuyor.
4. **`ingestion/pipeline.py`.** Ad-hoc `IngestionResult` artık geçerli run_id gerektiriyor.
5. **`sql/bootstrap/011_run_artifact.sql` + `ingestion/observability.py`.** Her run, kaydettiği
   her artifact'i `meta.run_artifact` ile kalıcı olarak bağlıyor. Tablo additive; mevcut
   tablolara sütun eklenmiyor. Curated kaynaklar `parser_config_sha256=NULL` ile bağlanıyor ve
   sonuçları değişmiyor. Baseline `tests/ingestion/test_pipeline_observability.py` içindeki
   karşılaştırma amaçlı no-op `RunRepository` test double'ına tek satırlık no-op `link_artifact`
   eklendi; başka baseline test değişmedi.

## Test verisi disiplini

Bu turda **hiçbir gerçek fixture kullanılmadı ve hiçbiri değiştirilmedi**. Bütün içerik
`SYNTHETIC`: testin kendisi geçici dizine yazıyor, hiçbiri gerçek bir yayımlanmış rakamı
temsil etmiyor. Ağ testlerinin tamamı sahte `FakeSession` ve sahte DNS resolver ile çalışıyor;
tek bir socket açılmıyor ve iki test bunu iddia etmek yerine kanıtlıyor.

## Doğrulama

Son doğrulamanın komutları, gerçek sonuçları ve 13 bulgunun test eşlemesi
[Generic/Ad-hoc inceleme raporunda](generic-adhoc-review-fixes.md) tutuluyor.

## Bilinen sınırlar

- **DNS rebinding engellenmiyor.** Adres kontrolü bu kodda, bağlantıyı HTTP istemcisi kendi
  çözümüyle kuruyor. Kapatmak için bağlantının doğrulanmış adrese sabitlenmesi gerekir; bu
  sürüm bunu yapmıyor. Redirect adımları yeniden doğrulanıyor, yani yaygın
  "public URL → metadata servisi" senaryosu kapalı; kalan risk düşman veya ele geçirilmiş bir
  resolver.
- **JavaScript ile üretilen sayfalar desteklenmiyor** ve denenmiyor. Connector sunucunun
  döndürdüğü baytları saklıyor; tablo tarayıcıda kuruluyorsa o baytlarda tablo yok ve parse
  dürüstçe başarısız oluyor.
- **PDF ve görsel yok.** OCR/VLM agent ekibinde; buraya CSV olarak geliyor.
- **`draft → active/verified` promotion yolu yok** ve bilinçli olarak eklenmedi. Bir
  profiler önerisi ancak bir insan yükselttikten sonra Gold tarafından kullanılabilir.
- **`adhoc.fact_observation` benzersizliği uygulama seviyesinde.** DuckDB PK kolonlarını
  `NOT NULL` yapıyor ve `entity_id` meşru şekilde nullable. Silver'daki emsalle aynı.
- **`period_start`/`period_end` her zaman NULL.** Ad-hoc mapping bir dönem etiketi taşımıyor;
  gerekirse ayrı bir turda eklenmeli.
- **Performans ölçülmedi.** Yayın satır satır `SELECT` + `INSERT` yapıyor; birkaç bin satırda
  sorun değil, çok daha büyük dosyalarda toplu yazım gerekebilir.
- **Encoding tespiti sezgisel.** `latin-1` her baytı kabul ettiği için son sırada ve
  ulaşıldığında uyarı üretiliyor; yine de yanlış karakter üretme ihtimali sıfır değil, bu
  yüzden gerektiğinde artık desteklenen allow-list içinden explicit `encoding` verilmelidir.
