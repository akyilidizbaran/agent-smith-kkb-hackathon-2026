# `feature/gold-functions-v1`

> **Amaç:** Agent ekibinin P0 listesindeki Gold yeteneklerini fonksiyon olarak teslim etmek —
> `align_frequency`, `decompose_cumulative`, `join_on_period`.
>
> **Taban:** `feature/agent-data-p0` @ `7534503`
> **Kapsam dışı:** generic connector/parser, `register_series`, `adhoc` şeması, CLI, EVDS
> pencereleme, katalog genişletme, FinTürk, agent kodu, kalıcı Gold tabloları.

Sözleşmenin tamamı [`docs/gold-contract.md`](../gold-contract.md) içinde. Bu belge **neden
öyle yapıldığını** ve neyin test edildiğini anlatır.

## Neden tablo değil fonksiyon

Agent ekibinin gerekçesi doğru ve ölçülebilir: jüri demo günü katalogda olmayan bir seri
getirebilir. Tablo o seri için bir kolon üretemez; fonksiyon, kataloğun kuralını eline
verilen seriye uygular. Yeni seri = yeni `meta.series` satırı, kod değişikliği yok.

Bu turda **hiçbir şey materyalize edilmiyor**. Fonksiyonlar `silver.fact_observation` ve
`meta.series` okuyup DataFrame döndürüyor. Kalıcı Gold tabloları, fonksiyonlar bir süre
güvenilir kaldıktan sonra gelecek.

## Baran'ın önerdiği imzayı neden birebir almadık

Öneri şuydu:

```python
align_frequency(series_id, target, *, measure_type, default_agg, week_anchor)
```

Üç sorun, aslında hepsi aynı sorun:

1. **`measure_type`, `default_agg` ve `week_anchor` parametre olarak semantik kuralı
   çağırana veriyor.** Buradaki çağıran bir dil modeli. Bir faiz serisi için
   `default_agg="sum"` geçmek, cevap gibi görünen ama olmayan bir sayı üretirdi. Üçü de
   `meta.series`'ten okunuyor — hiçbir Gold fonksiyonunun imzasında bu isimlerden biri yok ve
   bunu gerçek imzalar üzerinden doğrulayan bir test var.
2. **Bağlantı argümanı yok.** Fonksiyonlar Silver ve katalog okumak zorunda; *hangi*
   veritabanını okuduğu bir güvenlik kararı (agent'ın salt-okunur handle'ı mı, trusted mı).
   Açık parametre bu kararı çağrı yerinde görünür tutuyor.
3. **`decompose_cumulative(series_id, *, measure_type)`** aynı sorunu taşıyor, üstüne
   `flow_ytd` için gereken `cumulative_reset` alanını hiç anmıyor.

## Kritik davranış kararları

### Fail-closed, sessiz tahmin yok

Anlamı kanıtlanamayan her dönüşüm `GoldError` ile reddediliyor; hata kapalı bir sözlükten
gelen makine-okunur bir `reason` taşıyor. Böylece agent "reddettim, sebebi bu" ile "bir şey
patladı"yı ayırt edip kullanıcıya sorabiliyor.

### Duplicate / revision

Silver her vintage'ı bilerek saklıyor (duplicate kapısı `artifact_sha256` içeriyor). Bu
append-only bir fact tablosu için doğru, ama Gold'da sessizce çözülmesi yanlış olurdu.
**Repoda henüz revision policy yok**, bu yüzden aynı (`series_id`, `entity_id`,
`observation_date`) için birden fazla okuma varsa Gold reddediyor ve çakışan tarihleri
adlandırıyor. En yenisini, en büyüğünü veya ilkini seçmiyor.

### Null asla sıfır olmuyor

Tamamı eksik bir dönem `None` döndürüyor, `0` değil. "Kaynak yayımlamadı"yı "kaynak sıfır
yayımladı"ya çevirmek bu katmanın yapabileceği en zararlı şey olurdu. Kısmi eksik dönem
`partial_period` bayrağı ve `missing_observations` sayacıyla görünür kalıyor.

### Tatil Perşembe'si

BDDK haftalık fixture'ı 19.03.2026 Perşembe gözlemini içeriyor ve katalog `week_anchor:
friday` diyor. Gözlem, gerçek tarihinin ait olduğu aya konuyor — önce Cuma'ya taşınmıyor.
Test bunu hem Mart kutusunda bulunduğunu hem de 20.03'ün üretilmediğini doğrulayarak
sabitliyor.

### `index` ve `count` neden farklı ele alındı

Baran'ın belgesinde ikisi için de genel kural yok. Ama katalog `index` için niyeti zaten
ifade ediyor (`default_agg`), bu yüzden `index` **katalog söylüyorsa** destekleniyor,
söylemiyorsa reddediliyor — kural modelden değil katalogdan geliyor. `count` için böyle bir
ifade yok: bir sayım anlık popülasyon da olabilir dönem içi olay sayısı da, ve ikisi farklı
toplanır. Doğrulanmış kural olmadığı için reddediliyor.

### `allow_unverified_semantics`

Varsayılanı `False`. Yalnızca `semantic_confidence` kapısını gevşetiyor; measure type,
aggregation rule, frekans veya çapa **veremiyor** — bunları geçirecek bir parametre yok.
Yani bayrağı açan bir agent bile sayıların nasıl birleştirileceğini seçemiyor, sadece
kataloğun "tam kanıtlı değil" dediği bir seriyi kullanma sorumluluğunu üstleniyor.

Bugün bu iki gerçek seriyi etkiliyor: `evds:TP.KFE.TR` ve `evds:TP.FG.J0` ikisi de `derived`
(baz yılı doğrulanmamış). İkisi de otomatik dönüşmüyor.

## Hardening turu (bağımsız inceleme sonrası)

İnceleme yedi bulgu çıkardı; hepsi **önce yeniden üretildi**, sonra düzeltildi.

| # | Bulgu | Uygulanan davranış |
|---|---|---|
| 1 | `last`/`first` örtülü forward-fill yapıyordu (son gözlem NULL iken önceki değeri döndürüyordu) | Boundary kuralları **tüm** gözlemler üzerinden konuma göre seçim yapıyor; seçilen gözlem NULL ise sonuç NULL ve yeni `boundary_missing` kalite durumu. `sum/avg/min/max` için kısmi-null politikası aynen korundu |
| 2 | Kümülatif farkın provenance'ı yalnız mevcut gözlemi taşıyordu | `previous_artifact_sha256` / `previous_vintage_id` / `previous_run_id` + `*_list` + `contributor_count` eklendi; `quality_flag` **iki girdiden birlikte** türetiliyor — önceki gözlemde uyarı varsa fark `ok` görünmüyor |
| 3 | Haftalık cumulative'de 3 haftalık boşluk `ok`/30 dönüyordu | Adjacency yalnız `monthly`/`quarterly` için güvenilir; diğer frekanslar `UNSUPPORTED_SOURCE_FREQUENCY` ile reddediliyor. Tatil haftalarının 6/8 günlük kayması gerekçe olarak belgelendi. Aynı ayda iki gözlem artık `PERIOD_GRAIN_CONFLICT` |
| 4 | Katalog `status` okunuyor ama uygulanmıyordu | `require_active_status` eklendi; `draft`/`deprecated` → `INACTIVE_SERIES`. **`allow_unverified_semantics` bu kapıyı açmıyor** |
| 5 | Gözlemsiz seri boş DataFrame dönüyordu | `align_frequency` ve `decompose_cumulative` `NO_OBSERVATIONS` üretiyor; `join_on_period` sessizce atlamıyor, propagate ediyor |
| 6 | Join lineage'ında `source_observation_dates` yoktu | Alan eklendi; absent dönemde **boş liste** (null değil), `<key>::series_id` yine dolu |
| 7 | Doküman çalışmayan bir composition yolu vaat ediyordu | İddia kaldırıldı; `align_frequency` frame kabul etmediği ve unattributable satırların sessiz eksik toplam üreteceği açıkça belgelendi |

Ek giriş doğrulamaları: `allow_unverified_semantics` gerçek `bool` olmak zorunda (`"false"`
gibi truthy string `INVALID_ARGUMENT` üretiyor); `series_ids` elemanları tek tek non-empty
string olarak doğrulanıyor; tüm hatalar kapalı Gold refusal sözlüğünden geliyor.

### Composition kararı

**Seçenek 2 uygulandı: yanlış iddia kaldırıldı, sınır belgelendi.** Gerçek bir composition
yolu açmak, "içinde attributable olmayan bir ay bulunan çeyrek ne anlama gelir" sorusuna
sözleşme düzeyinde cevap vermeyi gerektiriyor (çeyreği reddet mi, kısmi olarak say mı) ve bu
karar alınmadı. Yarım desteklemektense kapsam dışı bırakmak daha güvenli.

## Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `src/lakehouse/gold/__init__.py` | **Yeni** — paket yüzeyi ve üç garanti |
| `src/lakehouse/gold/errors.py` | **Yeni** — `GoldError`, kapalı `reason` sözlüğü |
| `src/lakehouse/gold/periods.py` | **Yeni** — aylık/çeyreklik dönem kutulama, upsampling reddi |
| `src/lakehouse/gold/_semantics.py` | **Yeni** — `meta.series` okuma ve semantik kapılar |
| `src/lakehouse/gold/_observations.py` | **Yeni** — Silver okuma, vintage kapısı, lineage |
| `src/lakehouse/gold/align.py` | **Yeni** — `align_frequency` |
| `src/lakehouse/gold/cumulative.py` | **Yeni** — `decompose_cumulative` |
| `src/lakehouse/gold/join.py` | **Yeni** — `join_on_period` |
| `tests/gold/_support.py` | **Yeni** — gerçek fixture yolları + SYNTHETIC katalog satırları |
| `tests/gold/conftest.py`, `tests/gold/__init__.py` | **Yeni** |
| `tests/gold/test_align_frequency.py` | **Yeni** — 24 test |
| `tests/gold/test_decompose_cumulative.py` | **Yeni** — 12 test |
| `tests/gold/test_join_on_period.py` | **Yeni** — 8 test |
| `tests/gold/test_gold_security.py` | **Yeni** — 14 test |
| `tests/gold/test_gold_hardening.py` | **Yeni** — 43 regression testi (yedi bulgu) |
| `docs/gold-contract.md` | **Yeni** — API ve semantik sözleşme |
| `docs/branches/gold-functions-v1.md` | **Yeni** — bu belge |

Mevcut hiçbir üretim dosyası, fixture, katalog satırı, şema veya test değiştirilmedi.

## Test verisi disiplini

İki tür girdi kesin olarak ayrı tutuldu:

* **Gerçek fixture'lar.** `tests/fixtures/raw/` baytları gerçek connector → parser →
  ingestion pipeline → Silver adapter → materyalizasyon zincirinden geçiriliyor. İki zorunlu
  örnek (KTF12 haftalık→aylık ortalama, BDDK haftalık stok→ay sonu) bu yolla kanıtlanıyor.
* **SYNTHETIC katalog satırları ve gözlemler.** Git'teki katalogda `ratio`, `flow_periodic`,
  `flow_ytd`, `flow_cumulative`, `count` veya `unknown` serisi yok; bu dallar gerçek veriyle
  sınanamıyor. Hepsi `synthetic:` ad alanında ve **yalnızca test veritabanına** yazılıyor.
  `catalog/series/*.yml` dosyalarına dokunulmadı ve bu değerlerin hiçbiri gerçek bir
  ekonomik büyüklüğü temsil etmiyor.

## Doğrulama

```text
uv run pytest -q                          677 passed
uv run pytest --ignore=tests/gold         576 passed   (dokunulmamış baseline)
uv run pytest tests/gold                  101 passed
uv run pytest tests/acceptance             37 passed
make build                                exit 0
make demo-check                           2 passed, exit 0
```

## Bilinen sınırlar

- **Kalıcı Gold tablosu yok.** Bilinçli; fonksiyonlar güvenilirliğini kanıtlayana kadar
  materyalizasyon eklenmiyor.
- **Yalnızca `monthly` ve `quarterly` hedef frekans.** `semiannual`, `yearly`, `daily` test
  edilmediği için desteklenmiyor.
- **Cumulative decomposition yalnız `monthly`/`quarterly`.** Haftalık/günlük için güvenilir
  adjacency kuralı yok; tatil kaymalarını boşluktan ayırt edecek bir takvim bilgisi gerekiyor.
- **Decompose → align composition yolu yok** — gerekçesi yukarıda.
- **Revision policy yok** — çakışan vintage'da fail-closed. Politika geldiğinde
  `AMBIGUOUS_VINTAGE` yolu gevşetilmeli.
- **Enflasyondan arındırma yok.** Doğrulanmış baz yılı gerekiyor; TÜFE hâlâ `derived`.
- **`ratio` desteklenmiyor** — Silver pay/paydayı taşımıyor. Destek istenirse önce Silver'ın
  bu iki bileşeni taşıması gerekir.
- **`count` desteklenmiyor** — doğrulanmış kural yok.
- Performans ölçülmedi; `align_frequency` seri başına birkaç `SELECT` yapıyor ve mevcut
  hacimde sorun değil, ama katalog onlarca seriye çıktığında `join_on_period` için toplu
  okuma gerekebilir.
