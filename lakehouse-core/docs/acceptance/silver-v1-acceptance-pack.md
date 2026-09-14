# Silver V1 Acceptance Pack

> **KAPANIŞ GÜNCELLEMESİ — 10 Eylül 2026:** Bu rapor ilk denetimin tarihsel kaydıdır.
> Raporda bulunan 7 kırmızı testin temsil ettiği 6 teknik açık daha sonra aynı acceptance
> branch'inde kapatılmıştır. Observability altyapısı birleştirilmiş; warning/run bağlamı,
> BDDK birim ve entity korumaları, deterministic vintage ve Silver Parquet temsil kimliği
> üretim yoluna eklenmiştir. Güncel kabul suite'i **37/37 yeşildir**. Aşağıdaki ilk inceleme
> metnindeki FAIL tabloları sorunun nasıl yakalandığını belgelemek amacıyla korunmuştur;
> nihai karar artık **ACCEPT**'tir. EVDS resmî keyed endpoint smoke testi yalnızca dış sistem
> teyidi olarak ayrı izlenir ve Silver kod kabulünü açık bırakmaz.

> **Bu bir kabul değerlendirmesidir, bir geliştirme çalışması değildir.**
> Silver production kodu, connector'lar, parser'lar, semantic catalog, mevcut şema/SQL model
> dosyaları, mevcut testler ve mevcut fixture'lar **değiştirilmemiştir**. Başarısız kabul
> testleri olduğu gibi raporlanmıştır; hiçbiri production kodu düzeltilerek yeşile
> çevrilmemiştir.

---

## 1. Aday branch ve commit kimliği

| Alan | Beklenen | Doğrulanan | Sonuç |
|---|---|---|---|
| Silver adayı | `origin/feature/silver-v1` | `4cba3bf28198359b4df3ddf6bdd01f0af16232b3` | ✅ eşleşiyor |
| Merge-base | `ae22de71dcdd29e8b83e00200be4f8e038759058` | `git merge-base origin/feature/silver-v1 origin/feature/lakehouse-integration` → `ae22de71dcdd…` | ✅ eşleşiyor |
| Bildirilen test sonucu | `420 passed` | `420 passed` | ✅ eşleşiyor |
| Observability referansı | `origin/feature/lakehouse-ingestion-observability` | `29bbf6fcbb113a109c092d88e6b4023537a2cfb5` | ✅ eşleşiyor |
| Kabul branch'i | `feature/lakehouse-data-trust-acceptance` | Yoktu; `4cba3bf`'ten oluşturuldu | ✅ |

Observability branch'i **merge edilmemiştir**; yalnızca salt okunur olarak (`git show`) incelenmiştir.

Silver adayının merge-base'ten farkı: 19 dosya, +2.902 / −107 satır.

**Not:** `origin/feature/lakehouse-integration` bu inceleme sırasında `2f9234d`'dedir. Silver
adayı `ae22de7`'ten dallandığı için ne bağımsız denetim raporunu ne de observability
çalışmasını içerir. Bu, §12'deki `run_id` değerlendirmesinin bağlamıdır.

---

## 2. Kullanılan kaynaklar

Öncelik sırasıyla:

1. **Organizatör birincil kaynakları** — `references/transcripts/KKB_Hackathon_2026_Kick_Off_Tam_Transkript.md`,
   `references/KKB_Hackathon_2026_Kick_Off_Sunumu.pdf` (çalışma alanında, repo dışı)
2. **Gerçek fixture / RAW cevabı** — `tests/fixtures/raw/{bddk_monthly,bddk_weekly,evds}/`
3. **Connector ve parser davranışı** — `src/lakehouse/connectors/`, `src/lakehouse/parsers/`
4. **Semantic catalog** — `catalog/series/*.yml`
5. **Silver adapter ve foundation** — `src/lakehouse/silver/`, `models/silver/fact_observation.sql`,
   `schemas/fact_observation.yml`
6. **Ekip dokümanları** — `docs/team-contract.md`, `docs/sources/`

Bu kabul paketi hiçbir önceki modelin veya kişinin sonucunu doğrulamaya çalışmamıştır;
tüm bulgular yukarıdaki kaynaklardan bağımsız olarak türetilmiştir.

### Organizatörün doğrudan ilgili beklentileri

| Beklenti | Kaynak |
|---|---|
| Katmanlı Lakehouse; verinin doğruluğunun teyit edilmesi | Transkript `00:07:28`–`00:07:49` |
| Kümülatif verilerin ayrıştırılması | Sunum s.8 (not); Transkript `00:10:25` |
| Frekansların hizalanması | Transkript `00:10:53`–`00:11:02` |
| **Güven katmanı: kaynak gösterimi – izlenebilirlik – doğruluk kontrolü** | Sunum s.7 (alt bant) |
| Jenerik platform; başka bir veri alanına taşınabilmeli | Transkript `00:12:33`, `00:12:55` |

---

## 3. Silver'ın sorumluluk sınırı

`docs/team-contract.md` (Silver adayında güncellenmiş hâli) Silver'ı şöyle tanımlıyor:

> "Silver is the canonical, typed, validated and source-independent observation layer. …
> It is **not** source-specific Bronze structure, Gold aggregation, cross-frequency alignment,
> revision/current-selection logic or agent behaviour. Incremental, append, merge and
> current-vintage behavior are **deferred**. Silver semantics come from `meta.series`;
> **source-specific fields remain in Bronze**."

Bu kabul paketi bu sınıra saygı gösterir. Silver'ın kapsamı dışındaki davranışlar §16'da
ayrı tutulmuş, Silver'a hata olarak yazılmamıştır.

**Ancak** "source-specific fields remain in Bronze" cümlesi bir tasarım kararıdır; kararın
*güvenli* olup olmadığı ayrı bir sorudur ve §14'te kanıtla incelenmiştir.

---

## 4. Source → Bronze → Silver eşleme matrisi

| Kaynak | Bronze kolonları | Silver'a taşınan | Silver'da düşen |
|---|---|---|---|
| **BDDK Monthly** | `source_id`, `dataset_id`, `series_id`, `measure_column`, `measure_label`, **`unit_label`**, **`entity_label`**, `year_raw`, `month_raw`, `value_raw`, `source_order`, `artifact_sha256`, `fetched_at`, `locator` | `series_id`, `value_raw`→`value`, `year/month`→`period_start`/`period_end`/`observation_date`, provenance dörtlüsü | `measure_column`, `measure_label`, **`unit_label`**, **`entity_label`**, `source_order`, `locator` |
| **BDDK Weekly** | `source_id`, `dataset_id`, `series_id`, `chart_id`, **`kalem_id`**, `series_title`, `measure_label`, **`currency_label`**, `column_label`, **`entity_code`**, `date_raw`, `value_raw`, `source_order`, `artifact_sha256`, `fetched_at`, `locator` | `series_id`, `value_raw`→`value`, `date_raw`→`observation_date`, provenance dörtlüsü | `chart_id`, `kalem_id`, `series_title`, `measure_label`, **`currency_label`**, `column_label`, **`entity_code`**, `source_order`, `locator` |
| **EVDS (KTF12 / KFE)** | `source_id`, `dataset_id`, `series_id`, `series_column`, `series_name`, `date_raw`, **`unixtime`**, `value_raw`, `artifact_sha256`, `fetched_at`, `locator` | `series_id`, `value_raw`→`value`, `date_raw`→tarih(lar), provenance dörtlüsü | `series_column`, `series_name`, **`unixtime`**, `locator` |

Semantik alanlar (`frequency`, `unit`, `measure_type`) Bronze'dan değil, `meta.series`'ten
gelir — `models/silver/fact_observation.sql:23-32` `INNER JOIN meta.series`.

`SILVER_STAGING_COLUMNS` dışındaki her kolon `prepare_staging_frame` tarafından reddedilir
(`src/lakehouse/silver/foundation.py:147-149`), yani kaynağa özgü alanların jenerik sınırı
geçmesi **yapısal olarak imkânsızdır**. Bu iyi bir sınır; sonuçları §14'te.

---

## 5. BDDK Monthly kabul sonuçları

**Fixture:** `tests/fixtures/raw/bddk_monthly/bddk_monthly_housing_loans.json`
Gerçek connector + parser + adapter ile çalıştırıldı.

| Kontrol | Sonuç | Kanıt |
|---|---|---|
| `measure_type = stock` | ✅ PASS | `test_a1` |
| `unit = TRY_mn`, `frequency = monthly` | ✅ PASS | `test_a1` |
| Değerler toplanmıyor / fark alınmıyor | ✅ PASS | `test_a2` — 5 Bronze değeri 5 Silver değerine birebir; 2021-01 `276785.0` ve 2026-06 `801438.0` korunuyor |
| Dönem etiketi ay başı + ay sonu | ✅ PASS | `test_a3` — 2026-06 → `period_start=2026-06-01`, `period_end=observation_date=2026-06-30`; artık yıl olmayan Şubat 2021 → `2021-02-28` |
| **Kaynak birimi ↔ katalog birimi çelişkisi** | ❌ **FAIL** | `test_a4` |
| **Entity ayrımı** | ❌ **FAIL** | `test_a5` |

### FAIL — Kaynak birimi çelişkisi sessizce geçiyor

Bronze `unit_label` kolonu BDDK'nın kolon adına gömdüğü birimi taşıyor: fixture'da
`"milyon TL"` (parser: `src/lakehouse/parsers/bddk_monthly.py:123`,
`unit_label_from_column`). Katalog `TRY_mn` diyor — bugün **uyumlu**.

Ancak adapter `unit_label`'ı hiç okumuyor (`src/lakehouse/silver/adapters/bddk_monthly.py:103-120`)
ve foundation birim mutabakatı yapmıyor. `unit_label` `"bin TL"` olsaydı Silver yine
`TRY_mn` etiketiyle yayınlardı — değerler **1000 kat** yanlış olurdu.

Bu teorik bir risk değil: agent ekibinin canlı doğrulanmış notu
(`LAKEHOUSE_CONTRACT.md`, "unit + unit_multiplier") BDDK aylık bülteninde
**Tablo 3/4'ün "milyon TL", Tablo 5'in "bin TL"** yayınladığını kaydediyor. İkinci bir
BDDK tablosu kapsama alındığı anda bu sessiz hata gerçekleşir.

### FAIL — Farklı entity'ler tek kimliğe çöküyor

Bronze `entity_label` fixture'da `"Sektör"` (sektör toplamı). Adapter `entity_id`'yi
koşulsuz `None` yapıyor (`bddk_monthly.py:106`). `series_id` ise yalnızca
`kalemSutun` id'sinden türüyor (`parsers/bddk_monthly.py:120`), `taraf`/`BankaAdi`
içermiyor.

Sonuç: sektör toplamı ile tek bir banka grubu **aynı `series_id`, aynı `observation_date`,
`entity_id = NULL`** üretir. Duplicate kontrolü `artifact_sha256`'yı da anahtara aldığı için
(`foundation.py:271-285`) iki farklı artifact'tan gelen bu satırların **ikisi de kabul edilir**.
`test_a5` bunu gösteriyor: aynı dönem için iki satır, `entity_id.nunique() == 1`.

Bugün yalnızca `Sektör` çekildiği için çakışma yok. İkinci bir `taraf` eklendiği anda
downstream `SUM` sessizce **iki katına** çıkar.

---

## 6. BDDK Weekly kabul sonuçları

**Fixture:** `tests/fixtures/raw/bddk_weekly/bddk_weekly_housing_loans.json`

| Kontrol | Sonuç | Kanıt |
|---|---|---|
| `measure_type = stock`, `unit = TRY_mn`, `frequency = weekly` | ✅ PASS | `test_b1` |
| **Tatil haftası Perşembe'si Cuma'ya taşınmıyor** | ✅ PASS | `test_b2` |
| Tarih ve değerler birebir korunuyor | ✅ PASS | `test_b3` |
| Uydurma dönem etiketi yok | ✅ PASS | `test_b3` — `period_start`/`period_end` NULL |

### Perşembe bulgusu — bu kabul paketinin en net olumlu sonucu

Fixture zaten gerçek tatil-haftası vakasını içeriyor:

| `date_raw` | Tarih | Gün |
|---|---|---|
| `2.01.2026` | 2026-01-02 | Cuma |
| `13.03.2026` | 2026-03-13 | Cuma |
| **`19.03.2026`** | **2026-03-19** | **Perşembe** |
| `27.03.2026` | 2026-03-27 | Cuma |
| `26.06.2026` | 2026-06-26 | Cuma |

Katalog `week_anchor: friday` diyor. Adapter (`bddk_weekly.py:62-72`) tarihi yalnızca
`%d.%m.%Y` ile ayrıştırıyor, **hiçbir hizalama yapmıyor**. `test_b2` Silver'da
`2026-03-19`'un bulunduğunu ve `2026-03-20`'nin **bulunmadığını** doğruluyor.

Bu doğru davranıştır: kaynağın bildirmediği bir gözlem uydurulmuyor.

**Downstream uyarısı:** `week_anchor` Silver satırına kopyalanmıyor
(`schemas/fact_observation.yml:92`). Tüketici `frequency=weekly` ve bir Perşembe tarihi
görür, ancak çapanın ihlal edildiğini anlayamaz. Bkz. §16.

---

## 7. EVDS `TP.KTF12` kabul sonuçları

| Kontrol | Sonuç | Kanıt |
|---|---|---|
| `measure_type = rate`, `unit = pct`, `frequency = weekly` | ✅ PASS | `test_c1` |
| Faiz oranına toplama/fark uygulanmıyor | ✅ PASS | `test_c1` — 5 değer birebir; `18.61` ve `41.45` korunuyor |
| **Tarih, belirsiz olmayan `UNIXTIME` ile uyuşuyor** | ✅ PASS | `test_c2` |
| Tüm gözlemler Cuma'ya düşüyor (katalog çapası) | ✅ PASS | `test_c3` |

### `date_raw` / `YEARWEEK` / `UNIXTIME` — hangisi kullanılmalı?

Bu, kabul paketinin en dikkat isteyen sorusuydu. Kanıtlar:

1. **Parser'ın kendi talimatı** (`src/lakehouse/parsers/evds.py:18-21`):
   > "`Tarih` is **not** a single stable format… `UNIXTIME` is retained as the **unambiguous
   > field a later semantic layer should use** to derive `date_key`."
2. **Adapter bunu yapmıyor:** `evds.py:82` `datetime.strptime(raw, "%m-%d-%Y")` —
   `date_raw` kullanılıyor, `unixtime` staging'e hiç girmiyor.
3. **Connector ters formatta gönderiyor:** `connectors/evds.py:41`
   `EVDS_DATE_FORMAT = "%d-%m-%Y"`. Yani istek `dd-mm-yyyy`, okuma `mm-dd-yyyy`.
4. **Fixture'lar `MM-DD-YYYY`'yi destekliyor:** `01-15-2021`, `01-22-2021` — 15 ve 22 ay olamaz.
5. **`UNIXTIME` çapraz kontrolü tutuyor:** Beş gözlemin beşinde de
   `datetime.fromtimestamp(unixtime, UTC+3).date()` değeri `MM-DD-YYYY` ayrıştırmasıyla
   **aynı**. (`test_c2`)

**Değerlendirme:** Adapter'ın seçimi bu fixture'lar için **doğru sonuç üretiyor**, ancak
belgelenen tavsiyeye **aykırı** ve daha kırılgan bir alana dayanıyor.

`Doğrulandı`: fixture'lar için `date_raw`(MM-DD-YYYY) ≡ `UNIXTIME`(UTC+3).
`TEYİT GEREKLİ`: `docs/sources/evds.md:17` resmî keyed uç noktasının **hiç canlı
çağrılmadığını** kaydediyor; fixture'lar belgelenmemiş `/fe` ucundan alınmış. Resmî uç
`dd-mm-yyyy` döndürürse, **günü 1–12 arası olan her gözlem sessizce ay/gün takas eder**;
günü >12 olanlar `SilverValidationError` ile patlar (kısmi emniyet).

**`test_c2` bu riski kalıcı bir teste dönüştürüyor:** `UNIXTIME` ile `observation_date`
ayrışırsa test kırmızıya döner. Bu, kabul paketinin Silver'a bıraktığı en değerli koruma.

*Not: `UNIXTIME` çözümü sabit UTC+3 ile yapılmıştır. Türkiye 2016'dan beri kalıcı UTC+3
kullandığı için 2021–2026 penceresinde bu kesin doğrudur.*

`YEARWEEK` alanı (`2021-1`, `2026-27`) Bronze'da bile tutulmuyor (parser
`_NON_SERIES_FIELDS` ile atıyor); Silver'da kullanılabilir değil.

---

## 8. EVDS `TP.KFE.TR` kabul sonuçları

| Kontrol | Sonuç | Kanıt |
|---|---|---|
| `measure_type = index`, `unit = index`, `frequency = monthly` | ✅ PASS | `test_d1` |
| Endekse toplama/fark/yeniden bazlama uygulanmıyor | ✅ PASS | `test_d1` — `211.73`, `215.40`, `219.52` birebir |
| Ay sınırları `UNIXTIME` ile uyuşuyor | ✅ PASS | `test_d2` |
| `observation_date = period_end`, `period_start.day == 1` | ✅ PASS | `test_d2` |

`MM-YYYY` biçimi ay/gün belirsizliği taşımadığı için KTF12'deki risk burada yok.
`UNIXTIME` ayın 1'ini gösteriyor ve `period_start` ile birebir eşleşiyor.

Katalogda `semantic_confidence: derived` ve açıklamada **baz yılının doğrulanmadığı**
uyarısı var. Silver bu alanı satıra kopyalamıyor — endeks değerleri doğru taşınıyor ama
tüketici baz yılı belirsizliğini Silver'dan göremiyor. Bkz. §16.

---

## 9. Tarih ve frekans doğrulaması

| Seri | Kaynak biçimi | Silver `observation_date` | `period_start` / `period_end` | Sonuç |
|---|---|---|---|---|
| `bddk_monthly:1534_Toplam` | `Yil`+`Ay` tamsayı | Ay sonu | Ay başı / ay sonu | ✅ |
| `bddk_weekly:5690_3` | `d.MM.yyyy` | Kaynak tarihi birebir | NULL / NULL | ✅ |
| `evds:TP.KTF12` | `MM-DD-YYYY` | Ayrıştırılan gün | NULL / NULL | ✅ (`TEYİT GEREKLİ`, §7) |
| `evds:TP.KFE.TR` | `MM-YYYY` | Ay sonu | Ay başı / ay sonu | ✅ |

Aylık iki seri (BDDK monthly, KFE) **aynı dönem-sonu konvansiyonunu** kullanıyor — bu,
ileride cross-frequency join için tutarlı bir taban.

Haftalık iki seri (BDDK weekly, KTF12) dönem etiketi taşımıyor; ikisi de Cuma çapalı
olarak kataloglanmış ama BDDK tarafında Perşembe istisnası gerçek veri olarak mevcut.

---

## 10. Birim ve measure-type doğrulaması

| Seri | Katalog `unit` | Katalog `measure_type` | Silver'da korunuyor mu | Kaynak birimiyle mutabakat |
|---|---|---|---|---|
| `bddk_monthly:1534_Toplam` | `TRY_mn` | `stock` | ✅ | ❌ **yok** (`unit_label` düşüyor) |
| `bddk_weekly:5690_3` | `TRY_mn` | `stock` | ✅ | ❌ **yok** (`currency_label` düşüyor) |
| `evds:TP.KTF12` | `pct` | `rate` | ✅ | — (kaynak birim alanı yok) |
| `evds:TP.KFE.TR` | `index` | `index` | ✅ | — (kaynak birim alanı yok) |

Katalog semantiği **doğru şekilde** taşınıyor: `INNER JOIN meta.series` sayesinde
`frequency`/`unit`/`measure_type` katalogdan geliyor ve NULL/boş/`unknown` olması hâlinde
materyalizasyon reddediliyor (`foundation.py:247-269`).

Eksik olan **karşı yönlü kontrol**: kaynağın kendi beyan ettiği birim hiç okunmuyor.
Katalog tek doğruluk kaynağı olarak kabul ediliyor ve kaynak sessizce değişirse kimse
fark etmiyor. Bu, §5'teki FAIL'in birim boyutudur.

---

## 11. Null ve numeric quality doğrulaması

| Kontrol | Sonuç | Kanıt |
|---|---|---|
| Kaynak `NULL` → `0` **olmuyor** | ✅ PASS | `test_e1` — `value` NULL kalıyor, `quality_flag='missing_value'` |
| `NaN` reddediliyor | ✅ PASS | `test_e2[nan]` |
| `+Infinity` / `-Infinity` reddediliyor | ✅ PASS | `test_e2[inf]`, `test_e2[-inf]` |
| Sayı olmayan metin reddediliyor | ✅ PASS | `test_e2[not-a-number]`, `test_e2[]` |
| Virgüllü ondalık (`1,5`) reddediliyor | ✅ PASS | `test_e2[1,5]` |
| Metin/tamsayı/NULL tarih reddediliyor | ✅ PASS | `test_e3[2026-01-02]`, `[20260102]`, `[None]` |
| Naive `fetched_at` reddediliyor | ✅ PASS | `test_e4` |

Bu bölüm Silver'ın **en güçlü tarafı**. Doğrulama iki katmanlı: Python tarafında
`prepare_staging_frame` (`foundation.py:191-197`) ve SQL tarafında `TRY_CAST` + `isfinite`
(`foundation.py:227-245`). `1,5` gibi bir değerin sessizce NULL'a düşmesi engelleniyor —
bu, çoğu pipeline'ın kaçırdığı bir tuzak.

---

## 12. Provenance ve run uyumluluğu

| Kontrol | Sonuç | Kanıt |
|---|---|---|
| `source_id`, `dataset_id` korunuyor | ✅ PASS | `test_h1` |
| `artifact_sha256` korunuyor | ✅ PASS | `test_h1` |
| `fetched_at` korunuyor (UTC) | ✅ PASS | `test_h1` |
| Bronze `schema_version` korunuyor | ✅ PASS | `test_h1` — `bddk_monthly_observations.v1` |
| Foundation `run_id` taşıyabiliyor | ✅ PASS | `test_h3` |
| Hatalı `run_id` reddediliyor | ✅ PASS | `test_h4` |
| **Gerçek `run_id` Silver'a ulaşıyor** | ❌ **FAIL** | `test_h2` |

### `run_id` uyumluluk değerlendirmesi (observability branch'i merge edilmeden)

**Hazır olan taraf:**
- `SILVER_STAGING_COLUMNS` içinde `run_id` var (`foundation.py:45`)
- `prepare_staging_frame` `validate_run_id` ile doğruluyor (`foundation.py:208-210`)
- SQL model `run_id`'yi çıkışa taşıyor (`fact_observation.sql:19`, `:54`)
- `test_h3` bir `run_id` verildiğinde uçtan uca taşındığını kanıtlıyor

**Eksik olan taraf:**
- Silver adayında `IngestionResult`'ta `run_id` alanı **yok** (`test_h2`)
- Observability branch'inde **var** (`29bbf6f`, `pipeline.py:34-48`)
- Ancak adapter imzaları `(frame, *, identity)` — `ParquetIdentity` `run_id` taşımıyor ve
  Bronze Parquet'te `run_id` kolonu yok (üç parser'ın hiçbirinde geçmiyor)
- Yani observability merge edilse **bile** `run_id` bugünkü adapter'lardan geçemez

**Sonuç:** Silver `run_id` için **ileriye dönük uyumlu ama bağlanmamış**. Gereken değişiklik
küçük ve additive: adapter'lara bir `run_id` parametresi eklemek veya `(frame, identity)`
yerine `IngestionResult` geçirmek. Silver'ın yeniden tasarımı gerekmiyor.

Aynı şekilde `meta.ingest_warning` (observability branch'i) ile Silver `quality_flag`
arasında bir bağ yok — bkz. §13 ve §17.

---

## 13. Duplicate / revision davranışı

| Kontrol | Sonuç | Kanıt |
|---|---|---|
| Aynı artifact içindeki gerçek duplicate reddediliyor | ✅ PASS | `test_g1` |
| **Farklı artifact'ların aynı dönemi ayırt edilebiliyor** | ❌ **FAIL** | `test_g2` |

Duplicate anahtarı: `(series_id, entity_id, observation_date, artifact_sha256)`
(`foundation.py:271-285`). `artifact_sha256` anahtarın parçası olduğu için:

- **Aynı artifact** içinde tekrar → reddediliyor ✅
- **Farklı artifact'lar** aynı seri+dönem için değer taşırsa → **ikisi de kabul ediliyor**

Bu, append-only bir fact tablosu için doğru bir seçim. Sorun, iki okumanın **ayırt
edilebilir olmaması**: `vintage_id` her iki satırda da `NULL` (adapter'lar koşulsuz `None`
yazıyor). Tüketici hangi okumanın daha yeni olduğunu ancak `artifact_sha256` → `meta.artifact`
→ `fetched_at` zincirini elle kurarak bulabilir; Silver satırında bu bilgi yok.

`materialize_fact_observation_snapshot` tam anlık görüntü değiştirme yaptığı için
(`CREATE OR REPLACE TABLE`) çağıran doğru snapshot'ı kendisi kurmak zorunda. Bu
dokümante edilmiş (`foundation.py:326-331`, `team-contract.md`), ama **bir SUM sorgusu
iki vintage'ı sessizce toplar**.

**Sınıflandırma:** Ekip sözleşmesi "current-vintage behavior deferred" dediği için bu
Silver'ın açık kapsamı dışında. Ancak `vintage_id`'nin **doldurulabilir olmaması** Silver'ın
kendi şemasındaki bir eksik — alan var, hiçbir adapter yazmıyor. Bkz. §19.

---

## 14. Kaybolan source-specific alanlar

`prepare_staging_frame` bilinmeyen kolonları reddediyor — bu **iyi bir sınır**. Soru,
kaybolan alanların kaybının güvenli olup olmadığı.

| Kaybolan alan | Kaynak | Güvenli mi | Gerekçe |
|---|---|---|---|
| `measure_column`, `measure_label`, `series_title`, `column_label` | Her ikisi | ✅ Güvenli | `series_id` zaten kararlı native id'den türüyor; etiketler sunum bilgisi |
| `source_order` | Her ikisi | ✅ Güvenli | Kaynak satır sırası; `observation_date` daha güçlü bir anahtar |
| `locator` | Her ikisi | ✅ Güvenli | `artifact_sha256` üzerinden `meta.artifact.locator`'a ulaşılabilir |
| `chart_id` | Weekly | ✅ Güvenli | Konumsal adres; parser zaten kimlik olarak reddediyor |
| `kalem_id` | Weekly | ✅ Güvenli | `series_id`'nin içine kodlanmış (`5690_3`) |
| `series_column`, `series_name` | EVDS | ✅ Güvenli | `series_id` kanonik |
| **`unixtime`** | EVDS | ⚠️ **Riskli** | Belirsiz olmayan tek tarih alanı; `date_raw` yerine tercih edilmesi gerekirdi (§7) |
| **`unit_label`** | Monthly | ❌ **Güvensiz** | Kaynak birimi ile katalog birimi arasında mutabakat imkânı yok (§5) |
| **`currency_label`** | Weekly | ❌ **Güvensiz** | TRY/USD ayrımı `series_id`'de yok; iki para birimi aynı kimliğe çöker |
| **`entity_label` / `entity_code`** | Monthly / Weekly | ❌ **Güvensiz** | `taraf` / banka grubu ayrımı `series_id`'de yok; farklı popülasyonlar aynı kimliğe çöker (§5) |

**Özet:** 13 kaybolan alandan 9'u güvenli, 1'i riskli, 3'ü güvensiz. Güvensizlerin ortak
paydası aynı: **`series_id` kaynağın kimlik boyutlarının tamamını kodlamıyor** ve
`entity_id` bu boşluğu doldurmak için kullanılmıyor.

Bugün çakışma yok çünkü her kaynaktan tek bir kombinasyon çekiliyor. Bu, bir tasarım
garantisi değil, bir **kapsam tesadüfü**.

---

## 15. Mevcut testlerin yanlış varsayım sabitleyip sabitlemediği

**Evet, iki yerde.**

### 15.1 Uyarı kaybı "doğru davranış" olarak sabitlenmiş

`tests/integration/test_silver_source_mappings.py:126-127`:

```python
assert result.parsed_batch.warnings          # parser gerçekten uyardı
assert staging["source_warning"].isna().all() # ve Silver'da uyarı yok
```

ve aynı testte (`:159`) beklenen satırda `quality_flag` değeri `"ok"`.

Yani mevcut test, **parser'ın uyardığı bir batch'in Silver'da "temiz" görünmesini**
doğrulanmış davranış olarak sabitliyor. Dosyada 4 ayrı yerde `"ok"` beklentisi var.

Bu tam olarak "hatalı bir varsayımı doğru sonuç olarak sabitlemek"tir.

### 15.2 Bronze/Silver kimlik ayrımının olmaması sabitlenmiş

`test_silver_source_mappings.py:170`, `:240`, `:421`, `:488` — dört kez:

```python
assert read_identity(silver_path) == read_identity(result.bronze_path)
```

Silver Parquet'in Bronze ile **birebir aynı kimliği** taşıması beklenen sonuç olarak
yazılmış. §18'deki `test_j1` bunun neden sorunlu olduğunu gösteriyor.

### Yanlış alarm değil

Diğer testler gerçek davranışı doğruluyor. Özellikle `test_silver_v1.py` ve
`tests/silver/test_foundation.py` reddetme yollarını (`NaN`, katalog eksikliği, duplicate)
sağlam biçimde kapsıyor; bu kabul paketi onları bağımsız olarak yeniden üretti ve
**aynı sonuçları aldı**.

---

## 16. Silver sonrası ertelenen kurallar

Bu davranışlar önemli, ancak Silver'ın mevcut sorumluluğunda **değil**. Silver'a hata
yazılmamıştır; bir sonraki sözleşme/gate'e taşınmıştır.

| Kural | Neden Silver'da değil | Nereye ait |
|---|---|---|
| Aylık stoktan çeyreklik `last` | Aggregation Silver kapsamı dışı (`team-contract.md`) | Gold |
| Haftalık faizden aylık `avg` | Aynı | Gold |
| Stock/rate/index için yanlış SQL'in reddedilmesi | Silver veri üretir, sorgu denetlemez | Agent semantic firewall |
| Cross-frequency join | Aggregation/alignment kapsam dışı | Gold |
| Gold aggregation | — | Gold |
| Data Passport | — | Agent/sunum katmanı |
| Current-vintage seçimi | "deferred" olarak yazılı | Gold veya yayın katmanı |
| `week_anchor` ihlalinin görünür olması | Katalog alanı satıra kopyalanmıyor (bilinçli) | Gold / agent katalog erişimi |
| KFE baz yılı belirsizliği | `semantic_confidence` satıra kopyalanmıyor | Agent semantic firewall |

**Ancak** §13'teki vintage sorunu ve §5'teki entity/birim sorunu birer **gate koşulu**
üretir: bunlar çözülmeden Gold'da `SUM`/`JOIN` yapılırsa sessiz yanlış sonuç üretilir.

---

## 17. Acceptance test sonuçları

Tüm testler çevrimdışıdır; hiçbiri socket açmaz. Gerçek connector, gerçek parser, gerçek
adapter, gerçek foundation ve gerçek DuckDB kullanılır; yalnızca HTTP transport fixture
baytlarını tekrar oynatır.

```text
Mevcut baseline (tests/acceptance hariç)   420 passed
Yeni acceptance suite                       37 test → 30 passed, 7 failed
```

### Başarısız kabul maddeleri (7)

| Test | Senaryo | Bulgu |
|---|---|---|
| `test_a4_bddk_monthly_source_unit_conflict_must_not_pass_silently` | 7 | `DID NOT RAISE` — `unit_label='bin TL'` iken Silver `TRY_mn` etiketiyle yayınlıyor |
| `test_a5_bddk_monthly_entities_must_not_collapse_into_one_identity` | 6 | `entity_id.nunique() == 1` — sektör toplamı ve banka grubu ayrılamıyor |
| `test_g2_two_artifacts_for_one_period_stay_distinguishable` | 15 | `vintage_id.nunique() == 1` (ikisi de NULL) |
| `test_h2_run_id_reaches_silver_when_ingestion_records_one` | 18 | `IngestionResult`'ta `run_id` yok; adapter imzası taşıyamıyor |
| `test_i1_a_warned_batch_must_not_be_published_as_ok` | 17 | `{'ok'} == {'ok'}` — 2 parser uyarısına rağmen tüm satırlar temiz |
| `test_i2_warning_text_is_reachable_from_a_silver_row` | 17 | `source_warning` tüm satırlarda NULL |
| `test_j1_silver_parquet_identity_is_distinguishable_from_bronze` | 19 | Silver Parquet, Bronze kimliğini birebir taşıyor |

### Otomatik test edilemeyen maddeler

| Madde | Neden |
|---|---|
| Resmî EVDS keyed uç noktasının tarih biçimi | Canlı çağrı yasak ve API anahtarı yok (`docs/sources/evds.md:17`) |
| BDDK Tablo 5'in gerçekten "bin TL" yayınladığı | Yalnızca agent ekibi belgesinde kayıtlı; bu pakette canlı doğrulanmadı |
| Gerçek tatil takvimiyle Perşembe istisnasının sıklığı | Fixture tek örnek içeriyor; kaynak tarafı bilgi gerekiyor |
| Observability merge sonrası uçtan uca `run_id` | Merge yasak; yalnızca statik uyumluluk incelendi |

### `TEYİT GEREKLİ` işaretli maddeler

1. **EVDS `Tarih` biçimi** — `MM-DD-YYYY` varsayımı yalnızca belgelenmemiş `/fe` ucundan
   alınan fixture'larla doğrulandı. Resmî uç bir kez çağrılmalı. (`test_c2` bu riski
   kalıcı olarak izliyor.)
2. **BDDK aylık birim çeşitliliği** — Tablo 3/4 "milyon TL", Tablo 5 "bin TL" iddiası
   resmî kaynaktan doğrulanmalı; §5'teki FAIL'in aciliyetini bu belirler.
3. **KFE baz yılı** — katalog `semantic_confidence: derived` ve baz yılının doğrulanmadığını
   yazıyor; reel dönüşümde kullanılmadan önce teyit gerekiyor.

---

## 18. PASS / FAIL / BLOCKED matrisi

| # | Senaryo | Sonuç | Kanıt |
|---|---|---|---|
| 1 | BDDK aylık konut kredisi `stock` | ✅ PASS | `test_a1` |
| 2 | BDDK haftalık konut kredisi `stock` | ✅ PASS | `test_b1` |
| 3 | Stok değerleri toplanmıyor/farkı alınmıyor | ✅ PASS | `test_a2`, `test_b3` |
| 4 | Aylık dönem etiketi ay başı/ay sonu | ✅ PASS | `test_a3` |
| 5 | Haftalık kaynak tarihi korunuyor | ✅ PASS | `test_b2`, `test_b3` |
| 6 | Farklı taraf/entity/para birimi yanlış etiketlenmiyor | ❌ **FAIL** | `test_a5` |
| 7 | Kaynak birimi ↔ katalog birimi çelişkisi | ❌ **FAIL** | `test_a4` |
| 8 | KTF12 `rate`, KFE `index` | ✅ PASS | `test_c1`, `test_d1` |
| 9 | Faiz/endekse toplama-fark yok | ✅ PASS | `test_c1`, `test_d1` |
| 10 | Kaynak `NULL` → `0` olmuyor | ✅ PASS | `test_e1` |
| 11 | Geçersiz tarih/sayı/NaN/Inf reddediliyor | ✅ PASS | `test_e2`, `test_e3`, `test_e4` |
| 12 | Katalogda olmayan seri reddediliyor | ✅ PASS | `test_f1`, `test_f3` |
| 13 | `measure_type=unknown` reddediliyor | ✅ PASS | `test_f2` |
| 14 | Aynı artifact içi duplicate reddediliyor | ✅ PASS | `test_g1` |
| 15 | Revision/vintage davranışı açık | ❌ **FAIL** | `test_g2` |
| 16 | Provenance alanları korunuyor | ✅ PASS | `test_h1` |
| 17 | Uyarılı batch koşulsuz `ok` görünmüyor | ❌ **FAIL** | `test_i1`, `test_i2` |
| 18 | Observability sonrası `run_id` korunabilir | ⚠️ **PARTIAL** | `test_h3`/`h4` PASS, `test_h2` FAIL |
| 19 | Silver Parquet kimliği Bronze'dan ayrılıyor | ❌ **FAIL** | `test_j1` |
| 20 | Dört seri anlam kaybı olmadan bir arada | ✅ PASS | `test_k1` |

**Sayım:** 14 PASS · 5 FAIL · 1 PARTIAL · 0 BLOCKED

---

## 19. Merge öncesi bloklayıcı bulgular

Aşağıdaki sınıflandırma, her bulgunun **bugün gerçek mi yoksa gizli mi** olduğuna göre yapıldı.

### B1 — Parser uyarıları Silver'da kayboluyor · **BUGÜN GERÇEK** · Demo öncesi zorunlu

**Kanıt:** Depoya commit edilmiş BDDK aylık fixture'ı, gerçek parser'la çalıştırıldığında
**iki gerçek uyarı** üretiyor:

1. `"column '…' declares a grid display defaultValue of '0'; an absent source value can
   appear as zero in the BDDK UI and must not be treated as a measured zero"`
2. `"5 periods returned but 3 were requested; an OBSERVATION_COUNT_MISMATCH check applies
   upstream"`

Silver bu beş satırın **hepsini `quality_flag='ok'` olarak** yayınlıyor
(`test_i1`). `source_warning` alanı şemada var ama **hiçbir adapter yazmıyor** — üçü de
koşulsuz `None` (`bddk_monthly.py:118`, `bddk_weekly.py:102`, `evds.py:113`).

Ek olarak SQL model `CASE` sırası (`fact_observation.sql:43-47`) `missing_value`'yu
`source_warning`'den önce değerlendiriyor; hem NULL hem uyarılı bir satırda uyarı bilgisi
ayrıca maskeleniyor.

**Neden bloklayıcı:** Organizatör "Güven katmanı: … Doğruluk Kontrolü"nü ayrı bir
değerlendirme bandı olarak yazmış (Sunum s.7). Veri, parser'ın "bu sıfır ölçülmüş bir sıfır
olmayabilir" uyarısına rağmen temiz olarak sunuluyor. Bu bir değer bozulması değil ama
**yanlış bir güven beyanıdır**.

**Düzeltme büyüklüğü:** Küçük. Adapter imzalarına `warnings` geçirmek + `source_warning`
doldurmak. Observability branch'i `meta.ingest_warning`'i zaten kalıcılaştırıyor.

### B2 — Entity ve para birimi kimliğe kodlanmıyor · **GİZLİ** · Kapsam genişletme öncesi zorunlu

Bugün her kaynaktan tek kombinasyon çekildiği için çakışma yok. **İkinci bir `taraf`,
para birimi veya BDDK tablosu eklendiği anda** iki farklı popülasyon aynı `series_id` +
`entity_id=NULL` altında toplanır ve downstream `SUM` sessizce iki katına çıkar (`test_a5`).

**Gate:** Mevcut dört serinin ötesine geçilmeden önce ya `series_id` kimlik boyutlarını
kodlamalı ya da `entity_id` doldurulmalı.

### B3 — Kaynak birimi mutabakatı yok · **GİZLİ** · Kapsam genişletme öncesi zorunlu

Bronze `unit_label` okunmuyor. BDDK aylık bülteninde tablodan tabloya birim değiştiği
kayıtlı olduğu için, ikinci bir tablo eklendiğinde 1000 kat hata riski var (`test_a4`).

**Gate:** B2 ile aynı kapıda.

### B4 — `vintage_id` doldurulamıyor · **GİZLİ** · Gold öncesi gate

Aynı dönemin iki okuması ayırt edilemiyor (`test_g2`). Ekip sözleşmesi vintage seçimini
erteliyor, ancak `vintage_id`'nin **hiç doldurulamaması** Silver şemasının kendi eksiği.
Gold'da veya yayın katmanında `SUM` yapılmadan önce çözülmeli.

### B5 — Silver Parquet Bronze kimliğini taşıyor · **DÜŞÜK** · Bloklamaz

Ayrım yalnızca dizin köküyle sağlanıyor (`data/bronze` vs `data/silver/fact_observation`).
Dosya taşınır/kopyalanırsa hangi katmana ait olduğu anlaşılamaz (`test_j1`). Mevcut testler
bu durumu dört yerde beklenen sonuç olarak sabitlemiş (§15.2). Ucuz düzeltme: Silver
yazımında ayrı bir `schema_version` kullanmak.

### B6 — `run_id` bağlanmamış · **DÜŞÜK** · Bloklamaz

İleriye dönük uyumlu; foundation hazır (`test_h3`). Observability merge edildikten sonra
adapter imzası değişikliği gerekiyor.

---

## 20. Nihai karar

# İlk denetim kararı: `ACCEPT WITH DOCUMENTED LIMITATIONS` *(kapanışta geçersiz kılındı)*

### Gerekçe

Silver V1 **verinin ekonomik ve zamansal anlamını mevcut dört seri için doğru koruyor**.
Bağımsız olarak doğrulanan başarılar önemsiz değil:

- Stok, oran ve endeks ölçü tipleri katalogdan doğru taşınıyor ve **hiçbirine toplama veya
  fark uygulanmıyor** — bu, Silver katmanlarının en sık yaptığı hata ve burada yapılmamış.
- BDDK haftalık **tatil Perşembe'si Cuma'ya taşınmıyor**; katalog Cuma çapası derken bile
  kaynağın bildirdiği tarih korunuyor. Bu, uydurma gözlem üretmemek adına doğru karar.
- Kaynak `NULL` değeri `0` olmuyor; `NaN`, `Infinity`, virgüllü ondalık ve metin tarih
  **reddediliyor**, sessizce NULL'a düşmüyor.
- Katalogda olmayan veya `measure_type='unknown'` olan seri **kabul edilmiyor**.
- Provenance dörtlüsü (`source_id`, `dataset_id`, `artifact_sha256`, `fetched_at`) ve Bronze
  `schema_version` eksiksiz taşınıyor.
- Dört seri tek kanonik şemada anlam kaybı olmadan bir arada duruyor.

Bulunan altı eksiğin **beşi gizli**: bugünkü kapsamda yanlış veri üretmiyorlar, kapsam
genişlediğinde veya downstream'de üretecekler. Biri (**B1, uyarı kaybı**) bugün gerçek,
ancak değer bozulması değil, güven beyanı hatası.

Merge'i bloklamak, Gold ve agent yüzeyini 10 günden az kalan kritik yolda bekletirdi;
oysa B1'in düzeltmesi Silver'ın üstüne ayrı bir değişiklik olarak rahatça oturur.

### Kabul koşulları

| # | Koşul | Ne zaman |
|---|---|---|
| K1 | **B1 düzeltilmeli** — parser uyarıları `source_warning`'e taşınmalı, uyarılı satır `ok` görünmemeli | **Demo öncesi zorunlu** |
| K2 | **B2 + B3 gate'i** — ikinci bir `taraf`, para birimi veya BDDK tablosu eklenmeden önce `series_id`/`entity_id` kimlik boyutları çözülmeli ve kaynak birimi mutabakatı eklenmeli | **Kapsam genişletmeden önce** |
| K3 | **B4 gate'i** — Gold'da veya yayın katmanında `SUM`/`JOIN` yapılmadan önce vintage ayrımı çözülmeli | **Gold öncesi** |
| K4 | **EVDS resmî uç noktası bir kez çağrılmalı**; `test_c2` yeşil kalmalı | **Mümkün olan en kısa sürede** |
| K5 | Mevcut testlerdeki iki sabitlenmiş varsayım (§15) B1 ve B5 düzeltilirken güncellenmeli | B1/B5 ile birlikte |
| K6 | B5 ve B6 fırsat bulundukça kapatılmalı | Bloklamaz |

### Bu kabul paketinin Silver'a bıraktığı kalıcı koruma

İlk denetimde `tests/acceptance/test_silver_v1_acceptance.py` içindeki 37 testin 30'u yeşildi ve
regresyon koruması olarak kalır. Özellikle:

- `test_c2` — EVDS tarih belirsizliğini `UNIXTIME` ile sürekli çapraz kontrol eder; resmî
  uç noktaya geçildiğinde biçim değişirse **sessiz kalmaz**.
- `test_b2` — tatil Perşembe'sinin Cuma'ya kaymadığını kalıcı olarak izler.
- `test_e1`/`test_e2` — `NULL → 0` ve sessiz sayısal bozulmaya karşı kilit.

İlk incelemede kalan 7 test kırmızıydı. Kapanış geliştirmesinden sonra bu testlerin tamamı
yeşile dönmüş ve kalıcı regresyon koruması haline gelmiştir.

---

*Kabul paketi `feature/lakehouse-data-trust-acceptance` branch'inde, `4cba3bf` tabanında
hazırlanmıştır. Silver production kodu, connector'lar, parser'lar, katalog, şemalar, SQL
modelleri, mevcut testler ve fixture'lar değiştirilmemiştir. Commit, push, merge veya rebase
yapılmamıştır.*

---

## 21. Kapanış doğrulaması

İlk denetimden sonra production yolu ayrı bir geliştirme turunda düzeltilmiştir:

| İlk bulgu | Kapanış davranışı |
|---|---|
| B1 — parser uyarısı kayboluyor | `stage_ingestion_result` warning listesini adapter'a taşır; satırlar `source_warning` olur ve ayrıntı `run_id` ile `meta.ingest_warning` üzerinden erişilir. |
| B2 — entity çökmesi | BDDK aylık etiketleri ve haftalık taraf kodları source-namespaced `entity_id` üretir; Sektör iki kaynakta da `bddk:10001` olur. |
| B3 — birim mutabakatı yok | Aylık BDDK mapping'i kaynak `unit_label` değerini `milyon TL` ile fail-closed doğrular; uyuşmazlık yayınlanmadan reddedilir. |
| B4 — vintage yok | Native vintage verilmezse foundation `artifact:<sha256>` üretir; iki farklı artifact iki ayrı vintage olur. |
| B5 — Silver dosyası Bronze kimliği taşıyor | Silver Parquet `representation=silver` ve `schema_version=fact_observation.v1` metadata'sı ile yazılır. |
| B6 — run bağlanmamış | Observability birleştirilmiştir; `IngestionResult.run_id` production staging bridge üzerinden Silver satırına ulaşır. |

Sonuç: kabul suite'i **37/37 PASS**. İlk rapordaki altı bulgu kapanmıştır. K4'teki canlı
EVDS çağrısı kod kabulünden ayrı bir dış-sistem smoke testidir; API anahtarı erişilebilir
olduğunda ayrıca kayda alınmalıdır.

# Nihai karar: `ACCEPT`
