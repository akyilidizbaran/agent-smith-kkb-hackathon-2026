# `feature/lakehouse-ingestion-observability`

> **Amaç:** Bağımsız denetim raporundaki **D2** bulgusunu kapatmak — parser'ların ürettiği
> veri kalitesi uyarıları `IngestionPipeline` döndükten sonra kayboluyordu, ve `meta.run`
> tablosu oluşturuluyor ama hiçbir üretim kodu tarafından kullanılmıyordu.
>
> **Taban:** `feature/lakehouse-integration` @ `2f9234d`
> **Kapsam dışı:** Silver, Gold, yayın (publication) katmanı, agent yüzeyi.

## Sorun

Parser'lar gerçekten değerli uyarılar üretiyor:

- "gözlem sayısı istek başına limite ulaştı; yanıt sessizce kırpılmış olabilir"
- "`totalCount` ile dönen gözlem sayısı uyuşmuyor"
- "5 dönem döndü ama 66 dönem istendi"
- "`defaultValue` '0' — ölçülmüş bir sıfır sayılmamalı"
- "`series_id` alt çizgi → nokta dönüşümüyle türetildi; etiket kararlı bir anahtar değil"

Bu uyarılar `ParsedBatch.warnings` içinde taşınıyor, `IngestionResult`'a kadar geliyor ve
orada bitiyordu. Hiçbir yere yazılmıyordu. Sonuç: sistem sessizce kırpılmış veya eksik
veriyi "başarılı" olarak kaydedebiliyordu.

## Ne yapıldı

`IngestionPipeline`'a **varsayılan olarak açık** çalışma takibi eklendi. Her `run()`
çağrısında:

1. Benzersiz bir `run_id` üretilir (`new_run_id()`, UUID4) ve `validate_run_id()` ile
   doğrulanır.
2. `meta.run` içine `running` durumuyla bir satır açılır.
3. Connector → artifact kaydı → parser → Bronze yazımı **sırası hiç değişmeden** çalışır.
4. Her `ParsedBatch`'in uyarıları `meta.ingest_warning` tablosuna **kayıpsız** yazılır.
5. Uyarı yoksa run `success`, en az bir uyarı varsa `warning` olarak kapanır.
6. Herhangi bir aşamada hata olursa run `failed` olarak kapanır ve **asıl exception
   değiştirilmeden yeniden yükseltilir**.
7. Üretilen her `IngestionResult` ait olduğu run'ın `run_id` değerini taşır.

## Tasarım kararları

### Neden varsayılan olarak açık?

Gözlemlenebilirliği kapatan **hiçbir örtük veya varsayılan yol yoktur**. Parser uyarıları
gerçek veri kalitesi sorunlarını anlatır; bunları sessizce atan bir pipeline zaten bu
katmanın var olma sebebi olan kusurdur. Kapatılabilir bir bayrak bırakmak, üretimde kimsenin
açmayacağı bir özellik üretirdi — nitekim bugün pipeline'ı kuran bir giriş noktası da yok
(denetim raporu, bulgu D6).

`run_repository` alanı **yalnızca bağımlılık enjeksiyonu** içindir. Verilmediğinde pipeline,
`ArtifactRepository`'nin zaten bootstrap edilmiş güvenilir DuckDB bağlantısı üzerinden bir
tane oluşturur. Bu yüzden tarihsel dört parametreli kullanım hiçbir ek işlem gerektirmeden
tam gözlemlenebilirlik alır:

```python
IngestionPipeline(
    connector=...,
    parser=...,
    artifact_repository=...,
    parquet_storage=...,
)
```

`None` değeri "kapat" değil, "bir tane oluştur" anlamına gelir. Karşılaştırma amaçlı bir
baseline gereken tek testte, açıkça isimlendirilmiş bir test double
(`NoOpRunRepositoryForComparisonOnly`) test dosyasının içinde tanımlanmıştır; üretim kodunda
karşılığı yoktur.

**Not:** Varsayılan açık olduğu için pipeline'a verilen `ArtifactRepository`'nin bağlantısı
bootstrap edilmiş olmalıdır. Mevcut tüm çağrı noktaları `bootstrap_database()` kullanıyor.

### Neden ayrı bir repository?

`ArtifactRepository` *veri hakkında* metadata tutar ve kayıt sonrası değişmezdir. Bir run
ise *süreç hakkında* metadata'dır ve tam olarak bir kez değiştirilir (aç, sonra kapat).
İkisini ayrı tutmak her ikisini de küçük tutar. Aynı DuckDB bağlantısını paylaşmaları
beklenen ve desteklenen kullanımdır — ikisi de trusted bağlantıda `meta` şemasına yazar.

### `rows_in` ve `rows_out` ne anlama geliyor?

| Alan | Anlam | Gerekçe |
|---|---|---|
| `rows_in` | **Daima `NULL`** | Connector satır değil **bayt** döndürür. Bronze ingestion sınırında dürüst bir "giriş satır sayısı" yoktur. Uydurmak, bilinmiyor bırakmaktan kötüdür. |
| `rows_out` | Bu run'ın Bronze'a **gerçekten yazdığı** toplam satır | Ölçülebilir ve doğrulanabilir bir sayıdır. Kısmi başarısızlıkta o ana kadar yazılan satırları korur (hiç yazılmadıysa `0`), böylece temizlik gerekip gerekmediği görülebilir. |

### Uyarılar kayıpsız, hatalar redakte

Bu ayrım bilinçlidir:

- **Uyarılar birinci-taraf metindir.** Bu deponun kendi parser'ları üretir; içlerinde
  credential, locator veya response gövdesi yoktur (branch açılmadan önce tüm
  `warnings.append` çağrıları tek tek denetlendi). Bu yüzden **verbatim** saklanırlar —
  ne kısaltma, ne yeniden biçimlendirme, ne de uydurma hata kodu. `ParsedBatch.warnings:
  list[str]` sözleşmesi değişmedi.
- **Hata metni üçüncü-taraf metindir.** Bir başarısızlık `requests`, `pyarrow` veya
  `duckdb` kaynaklı bir exception yüzeye çıkarabilir ve bunların mesajları istek URL'i,
  header dökümü veya response gövdesi parçası taşıyabilir. `describe_exception()` bu metni
  `redact_error_text()` üzerinden geçirir ve uzunluğunu sınırlar.

`meta.run.error` alanının **güvenilir ve makine tarafından okunabilir** kısmı baştaki
segmenttir: exception sınıf adı ve — `LakehouseError` ise — yapısal `error_code`.
Devamındaki serbest metin en iyi çaba redaksiyonundan geçmiş ve sınırlanmıştır.

Redaksiyon iki aşamalıdır:

1. URL'ler query string'ini, fragment'ini ve `user:pass@` kısmını kaybeder. Şema, host ve
   path korunur çünkü hatayı teşhis edilebilir kılan onlardır.
2. Adı credential'a benzeyen `ad=değer` / `ad: değer` çiftleri değerini kaybeder
   (`Bearer <token>` biçimi dahil). Liste bilinçli olarak geniştir; `key` de listededir
   çünkü EVDS connector'ı API anahtarını tam olarak `key` adlı bir header'da gönderir.

### Zaman

Tüm zaman damgaları timezone-aware UTC'dir; naive değer reddedilir. Saat
`IngestionPipeline.clock` alanından enjekte edilebilir (connector'lardaki mevcut desenle
aynı), böylece testler zamanı tam olarak belirler. `RunRepository` kendi saatini tutmaz —
her zaman damgası argüman olarak gelir.

## Şema

### `meta.run` (mevcut tablo, additive genişletme)

`001–004` migration dosyalarına dokunulmadı. `010_ingestion_observability.sql` iki
**nullable** kolon ekler:

```sql
ALTER TABLE meta.run ADD COLUMN IF NOT EXISTS source_id VARCHAR;
ALTER TABLE meta.run ADD COLUMN IF NOT EXISTS dataset_id VARCHAR;
```

Bunlar olmadan bir run satırı hiçbir şeye atfedilemiyordu. `ADD COLUMN IF NOT EXISTS`
tekrarlanan bootstrap'larda no-op'tur (test edildi).

> **Sena'ya not:** `meta.run` ortak bir tablodur. Değişiklik yalnızca eklemedir ve tablo
> bugüne kadar hiçbir üretim kodu tarafından kullanılmıyordu, ama şeklinin değiştiğini
> bilmenizde fayda var.

### `meta.run.status` sözlüğü

| Durum | Anlamı |
|---|---|
| `running` | Run başladı, henüz kapanmadı. Tek terminal-olmayan durum. |
| `success` | Run tamamlandı, hiç parser uyarısı üretmedi. |
| `warning` | Run tamamlandı, en az bir parser uyarısı üretti. |
| `failed` | Run hata aldı; `ended_at` ve `error` dolduruldu, asıl exception yeniden yükseltildi. |

`RunRepository.finish()` terminal olmayan bir durumu reddeder.

### Yaşam döngüsü gerçekten zorlanıyor

"Run tam olarak bir kez açılır ve bir kez kapanır" iddiası bir docstring değil, testle
kanıtlanmış bir kuraldır. `RunRepository` şunları reddeder:

| Durum | Sonuç |
|---|---|
| `run_id` geçerli bir UUID değil (`start` ve `finish`) | `ValueError` (`validate_run_id`) |
| Aynı `run_id` ikinci kez açılıyor | `meta.run` primary key reddeder |
| Var olmayan bir run kapatılıyor | `RunLifecycleError` |
| Zaten terminal durumdaki run tekrar kapatılıyor | `RunLifecycleError`, satır değişmez |
| `ended_at < started_at` | `RunLifecycleError` |
| `failed` ama hata detayı boş | `ValueError` |
| `success` / `warning` ama hata detayı dolu | `ValueError` |

Geçiş **atomiktir**: durum koşulu `UPDATE ... WHERE run_id = ? AND status = 'running'
RETURNING run_id` içinde tekrarlanır. Ön kontrol okunabilir hata mesajı üretmek içindir;
gerçek yarış koruması `RETURNING`'in boş dönmesidir — o durumda kapatma reddedilir, sessizce
üzerine yazılmaz.

### Uyarı–run–artifact bütünlüğü

`record_warnings()` tek bir satır yazmadan önce hepsini doğrular, böylece kısmen geçerli bir
batch yarım yazılmaz:

| Kontrol | Reddedilme |
|---|---|
| Her `run_id` geçerli UUID | `ValueError` |
| Tek çağrıda birden fazla run karışmış | `WarningIntegrityError` |
| Run mevcut değil | `WarningIntegrityError` |
| Run artık `running` değil | `WarningIntegrityError` |
| `source_id`/`dataset_id` run kaydıyla uyuşmuyor | `WarningIntegrityError` |
| `artifact_sha256` verilmiş ama `meta.artifact`'ta yok | `WarningIntegrityError` |
| Artifact başka bir source/dataset'e ait | `WarningIntegrityError` |

### Neden `FOREIGN KEY` yok — ölçüldü ve kaldırıldı

`FOREIGN KEY (run_id) REFERENCES meta.run(run_id)` yazıldı, ölçüldü ve **kaldırıldı**.
DuckDB 1.5.5'te bir uyarı satırı run'a referans verdiği anda, run'ı kapatan
`UPDATE ... RETURNING` reddediliyor:

```
Constraint Error: Violates foreign key constraint because key "run_id: ..." is still
referenced by a foreign key in a different table
```

Ölçüm: bellek içi ve dosya tabanlı veritabanında, tek ve çok kolonlu güncellemede — dört
kombinasyonun **hepsinde** `RETURNING` reddedildi, `RETURNING`'siz aynı `UPDATE` **hepsinde**
kabul edildi, ve uyarı satırı yokken ikisi de kabul edildi.

Pratik sonucu ağır ve sessizdi: **uyarı üreten bir run asla kapatılamıyordu**, sonsuza kadar
`running` kalıyordu — üstelik başarısızlık kaydı bilinçli olarak en iyi çaba olduğu için
başarısız run'lar da sessizce açık kalıyordu. Bu, kısıtın önlemeye çalıştığı sorundan
kötüydü.

`RETURNING`'i bırakıp düz `UPDATE`'e dönmek atomik koşullu kapatmayı kör bir güncellemeyle
takas ederdi ve kapatma yolunu, gelecekteki bir DuckDB sürümünün iki yönden birine
çözebileceği bir tutarsızlığa bağlı bırakırdı. Bu yüzden referans kuralı `RunRepository`
seviyesinde yaşıyor — ve orada bir `run_id` foreign key'inin hiç kapsamayacağı artifact
tutarlılığını da kapsıyor.

`CHECK` kısıtları ise sorunsuz çalışıyor ve **korundu**: `warning_seq > 0` ve boş olmayan
`message`, repository'den geçmeyen doğrudan `INSERT`'lerde bile zorlanıyor (test edildi).

### `meta.ingest_warning` (yeni tablo)

| Kolon | Tip | Not |
|---|---|---|
| `run_id` | `VARCHAR NOT NULL` | Birincil anahtarın ilk parçası |
| `warning_seq` | `INTEGER NOT NULL` | Run içinde 1'den başlayan deterministik sıra: (connector'ın döndürdüğü asset sırası, o batch içindeki uyarı sırası) |
| `source_id` | `VARCHAR NOT NULL` | |
| `dataset_id` | `VARCHAR NOT NULL` | |
| `artifact_sha256` | `VARCHAR` | Uyarı tek bir artifact'a atfedilemiyorsa `NULL`. Bugün yazılan her uyarı bir artifact taşır. |
| `message` | `VARCHAR NOT NULL` | **Verbatim** saklanır |
| `created_at` | `TIMESTAMPTZ NOT NULL` | |

Birincil anahtar: `(run_id, warning_seq)`.
Kısıtlar: `CHECK (warning_seq > 0)`, `CHECK (length(trim(message)) > 0)`.

## `run_id` sonuçla birlikte dönüyor

`IngestionResult` artık `run_id` taşıyor. Alan **en sonda ve varsayılanlı** (`str | None =
None`), yani dört argümanlı tarihsel kullanım kırılmıyor; pipeline her zaman doldurur ve tek
bir `run()` çağrısındaki bütün sonuçlar **aynı** `run_id` değerini taşır.

Böylece provenance zinciri bir sonuç nesnesinden yürünebilir hale geliyor:

```text
Bronze çıktı (IngestionResult.bronze_path)
    → IngestionResult.run_id
        → meta.run          (ne zaman, hangi source/dataset, hangi durum)
        → meta.artifact     (hangi ham baytlar)
        → meta.ingest_warning (parser ne uyardı)
```

## Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `sql/bootstrap/010_ingestion_observability.sql` | **Yeni** — `meta.ingest_warning` + `meta.run` additive genişletme |
| `src/lakehouse/ingestion/observability.py` | **Yeni** — `RunRepository`, `IngestionWarning`, `redact_error_text`, `describe_exception` |
| `src/lakehouse/ingestion/pipeline.py` | Additive — iki opsiyonel alan ve run kayıt adımları; mevcut sıra ve doğrulamalar değişmedi |
| `src/lakehouse/ingestion/__init__.py` | Additive — yeni isimlerin dışa aktarımı |
| `tests/ingestion/test_run_repository.py` | **Yeni** — repository, şema, idempotentlik ve redaksiyon birim testleri |
| `tests/ingestion/test_pipeline_observability.py` | **Yeni** — uçtan uca run durumu, uyarı kalıcılığı ve geriye uyumluluk testleri |
| `docs/branches/lakehouse-ingestion-observability.md` | **Yeni** — bu belge |

## Doğrulama

```text
uv run pytest -q                          440 passed
uv run pytest --ignore=tests/ingestion    357 passed   (dokunulmamış baseline)
uv run pytest tests/ingestion              83 passed   (bu branch'in testleri)
make build                                exit 0
make demo-check                           2 passed, exit 0
```

Silver, Gold, connector'lar, parser'lar, ortak sözleşmeler, semantic catalog YAML'ları,
query executor, SQL guard, `001–004` migration'ları ve denetim raporu diff'te yoktur.

## Bilinen sınırlar

- **Bayat `running` satırları toplanmıyor.** Süreç öldürülürse veya başarısızlık kaydı
  yapılamazsa geride açık bir run kalır. Bunları tespit eden veya kapatan bir mekanizma yok.
- **`KeyboardInterrupt` / `SystemExit` run'ı `running` bırakır.** Yakalama `Exception` ile
  sınırlıdır. Süreç öldürülürse geride bayat bir `running` satırı kalır; bunları
  toparlayacak bir mekanizma yoktur.
- **Başarısızlık kaydı en iyi çabadır.** Veritabanının kendisi bozulduysa kayıt sessizce
  atlanır — çünkü çağıranın asıl hatayı görmesi, ikincil bir kayıt hatasını görmesinden
  önemlidir. Başarılı bir run'ın kapanışı ise sessizleştirilmez; orada bir hata yüzeye çıkar.
- **Redaksiyon en iyi çabadır.** Bilinmeyen bir kütüphane credential'ı beklenmedik bir
  biçimde gömerse kaçırılabilir. Uzunluk sınırı ikinci savunma hattıdır.
- **Bütünlük kontrolleri tek bağlantı içinde geçerlidir.** Kontrol ile `INSERT` arasında
  ayrı bir bağlantı run'ı kapatırsa uyarı yine de yazılabilir. Tek süreçli mevcut kullanımda
  bu erişilebilir bir durum değil; çok süreçli ingestion geldiğinde yeniden ele alınmalı.
- **`meta.ingest_warning` referans bütünlüğü SQL değil, repository seviyesindedir** —
  gerekçesi ve ölçümü yukarıda. Tabloya doğrudan `INSERT` yapan başka bir yazıcı ortaya
  çıkarsa yetim satır üretebilir.
- **`meta.run` zaman damgaları Python'a `pytz` olmadan okunamaz.** DuckDB bir `TIMESTAMPTZ`
  değerini Python `datetime`'ına çevirirken `pytz` ister ve bu bir proje bağımlılığı
  değildir. Yazma tarafı etkilenmez; okuma yapan kod (ve testler) `epoch_ms()` kullanmalıdır
  — bu, deponun `meta.artifact` ve `meta.series` testlerinde zaten uyguladığı yöntemdir.
