# Veri dalları incelemesi — 3. tur

**Tarih:** 2026-09-11 · **İnceleyen:** Baran (agent tarafı) · **Yöntem:** dalları birleştirip
gerçek kaynaklardan veri çekerek ölçüm; hiçbir iddia okumaya dayanmıyor.

---

## Kısa cevap

**Hayır, veri tarafı henüz "tamamlandı" diyemeyiz** — ama sebebi kimsenin işini yarım
bırakması değil. İki bacak ayrı ayrı sağlam; **birbirine bakmıyorlardı**.

Bu incelemede iki dal birleştirildi, aradaki dört kopuk halka kapatıldı ve sistem ilk kez
**kaynak → RAW → Bronze → Silver → agent → cevap** olarak uçtan uca gerçek veriyle çalıştı.
Geriye kalanlar aşağıda, sahibiyle birlikte listeli.

---

## 1. Başlangıç durumu: iki dal, iki eksik yarım

| | Sena — `feature/lakehouse-operationalization` | Zümral — `feature/lakehouse-finturk-evds-housing` |
|---|---|---|
| Taban | `ae22de7` üstüne 17 commit | **aynı `ae22de7`'ten ayrı çatal**, 1 commit |
| Silver / Gold / ad-hoc / CLI | var | **hiç yok** |
| Katalog | 5 seri | **1619 seri** |
| FinTürk | yok | connector + parser + 81 il, canlı doğrulanmış |
| Gerçek veri | yok (`meta.artifact` 0 satır) | Bronze'a yazılmış |

Zümral'ın dalı Silver'ın yazıldığı commit'lerden **önceki** bir noktadan çatallanmış. Bu
yüzden "Silver hâlâ `series_id` üzerinden `meta.series`'e bakacak, değişen bir şey yok"
varsayımı dalın içinden test edilemiyordu — o dalda Silver diye bir şey yok.

Birleştirme yapıldı: **iki çakışma**, ikisi de önemsiz (`pyproject.toml` bağımlılıkları,
bir test eşiği). Katalog temiz birleşti: **1620 seri, kimlik çakışması yok**.

---

## 2. Birleştirmenin ortaya çıkardığı dört kopuk halka

### 2.1 Katalog 300 kat büyüdü, Silver'a girebilen seri sayısı değişmedi

Silver adaptörleri seriyi **ada göre** kabul ediyordu:

```python
if any(v != SUPPORTED_SERIES_ID for v in frame["series_id"]):
    raise SilverValidationError("only ... is mapped")
```

Yayınlanabilir seri sayısı = birinin yazdığı fonksiyon sayısı. Ölçüm:

```
katalogdaki seri                                     1620
measure_type ve unit'i birlikte tanımlı olan            5
Silver adaptörünün adıyla kabul ettiği                  5
```

1534 serinin `measure_type`'ı `unknown`, `unit`'i `null` — EVDS'in kendi metadata'sından
otomatik üretildikleri için. Bu **doğru bir kayıt**, uydurmaktan iyidir; ama o hâlleriyle
ne Silver'a girebilirler ne Gold onları işler.

**Kapatıldı:** `silver/adapters/catalog_driven.py`. "Bu serinin anlamını bir insan onayladı
mı?" sorusunu artık Python sabiti değil `meta.series` yanıtlıyor. Gerçekten kaynağa özgü
olan (tarihin yazımı, entity'nin satırdaki yeri, kaynağın bildirdiği birim etiketi) kaynak
başına kalıyor. Dört kaynak: `bddk_monthly`, `bddk_weekly`, `bddk_finturk` (yeni), `evds`.

Güvenlik kaybı yok: yeni yolun daha önce gözden geçirilmiş dört adaptörün ürettiği
çerçevenin **aynısını** ürettiği testle sabit (`assert_frame_equal`).

### 2.2 Silver'ı üretimde kimse yazmıyordu

`materialize_fact_observation_snapshot`'ın **bütün çağrı yerleri `tests/` altındaydı**.
Başarılı bir ingest bile Bronze'da bitiyor, `silver.fact_observation` boş kalıyordu. Agent
Silver'ı okur; yani ne kadar veri çekilirse çekilsin agent hiçbirini göremiyordu.

**Kapatıldı:** `silver/build.py` + `python -m lakehouse silver`. Bronze ağacının tamamını
kataloğa göre haritalayıp tek anlık görüntü yayınlar. EVDS pencerelerinin paylaştığı sınır
gözlemi burada da uzlaştırılıyor (aynı değer → tek gözlem, farklı değer → revizyon hatası).
Yayınlanamayan seriler **sebebiyle birlikte** raporlanıyor, sessizce düşmüyor.

### 2.3 EVDS'in resmî ucu fixture'larla aynı tarihi ters yazıyor

`tests/fixtures/raw/evds/README.md` kendi uyarısını yazmıştı: fixture'lar EVDS web
uygulamasının ucundan alındı, *"resmî anahtarlı uç hiç canlı çağrılmadı"*, *"anahtar
bulununca yeniden yakalayın, bir şey farklıysa dosyaları değiştirin"*.

Anahtarla çağırdık. Üç fark:

| frekans | web uygulaması | resmî anahtarlı uç |
|---|---|---|
| haftalık / günlük | `01-08-2021` | `08-01-2021` |
| aylık | `01-2021` | `2021-1` |
| `seriesNames` | var | **hiç yok** |

Aynı gözlem — 8 Ocak 2021 — gün ve ay yer değiştirmiş. **İkisinden yalnızca biri sesini
çıkarıyordu:** aylık biçim ayrıştırılamayıp hata verdi; haftalık biçim `%m-%d-%Y` ile
pürüzsüz okundu ve **1 Ağustos 2021** üretti. Ayın on ikisinden sonraki her haftalık gözlem
sessizce yanlış tarihe düşüyordu — hem de katalogda `verified` işaretli tek EVDS serisinde.

Ekibin kendi kabul testi (C2) tam bunu yakalamak için yazılmıştı: *"so a future keyed-endpoint
response in the other order cannot pass unnoticed."* Test doğruydu; sadece hiç canlı yanıta
karşı koşmamıştı.

**Kapatıldı:** `_evds_time.py` — tarih `UNIXTIME`'dan okunuyor (iki uç da gönderiyor, alan
sırası belirsizliği yok). `Tarih` hâlâ okunuyor ama **karşılaştırılmak için**: uyuşmazsa
kaynak değişmiş demektir, hata verir. Canlı uçtan alınan gerçek yanıtlar fixture olarak
commit edildi.

### 2.4 Amiral gemisi aylık seri Silver'a hiç girmiyordu

`ingestion_registry` `kalemSutun`'u `"<native_code>?Toplam"` diye kuruyordu; kataloğun
`native_code`'u zaten `"1534?Toplam"`. Telde `1534?Toplam?Toplam` gitti, BDDK **doğru
değerleri** döndürdü, parser istekten türettiği için `series_id` `bddk_monthly:1534_Toplam_Toplam`
oldu — hiçbir katalog satırıyla eşleşmeyen bir seri. Her log satırı `OK` derken seri
yayınlanmadı.

**Kapatıldı:** sütun yalnızca `native_code` bir sütun adı içermiyorsa ekleniyor.

---

## 3. FinTürk'ün birimi kanıtlandı: Bin TL

Şartnamenin üçüncü BDDK kaynağı, birimi doğrulanamadığı için Silver'a giremiyordu
(`unit: null`, ve sözleşme birimi bilinmeyen seriyi yayınlamıyor — doğru davranış).
Kaynağın kendisi soruyu yanıtlıyormuş. İki bağımsız kanıt:

**(a) Kaynağın kendi etiketi.** FinTürk sayfasındaki tablo seçicisinin `option` değerleri,
connector'ın tel üzerinde gönderdiği `tabloNo`'nun ta kendisi:

```html
<option value="3">Bireysel Bankacılık (Bin TL)</option>
```

**(b) Kaynaklar arası kimlik, canlı ölçüldü.** 81 ilin tamamı üretim connector/parser'ıyla
2025-09 için çekildi (81/81 HTTP 200) ve toplandı. Karşılaştırma, birimi kendi yanıtında
yazan ve ayrıca doğrulanmış olan `bddk_monthly:1534_Toplam`'a karşı:

| | |
|---|---|
| 81 il ham toplam | `623.770.000` |
| **Bin TL** okunuşu | `623.770` milyon TL |
| BDDK Aylık ulusal (milyon TL) | `623.765` |
| **fark** | **%0,0008** |

Diğer iki okunuş yakın bile değil: milyon TL olsa İstanbul tek başına ulusal stokun 294 katı;
düz TL olsa 81 il toplam 624 milyon lira.

Aynı koşu kataloğun **ilk il-bazlı doğrulaması** da oldu: 81 girişin hepsi canlı yanıta
çözüldü. Katalog: 81 giriş `unit: null` / `derived` → `unit: TRY_th` / `verified`.

---

## 4. Uçtan uca ölçüm — sistem ilk kez tam çalıştı

15 seri gerçek kaynaklardan çekildi (10 il + BDDK aylık + BDDK haftalık + 3 EVDS serisi):

```
$ python -m lakehouse silver
status: success
bronze artifacts found : 225
bronze artifacts staged: 225
rows staged            : 987
rows published         : 987
series published       : 15
series withheld        : 70 (1540 rows)
  - not in meta.series: 70
```

Üç kaynak yan yana, birbirini doğruluyor:

| seri | tarih | değer | birim |
|---|---|---|---|
| `bddk_monthly:1534_Toplam` | 2026-06-30 | 801.438 | milyon TL |
| `bddk_weekly:5690_3` | 2026-06-26 | 800.464 | milyon TL |
| `bddk_finturk:ISTANBUL_KonutKredisi` | 2026-06-30 | 228.383.471 | bin TL (= ulusalın %28,5'i) |

Sonra **bizim agent** aynı veritabanına bağlandı ve canlı soru aldı:

> **"2026 ikinci çeyrek itibarıyla hangi ilde konut kredisi bakiyesi en yüksek? İlk üçü sırala."**
>
> 1. İstanbul — 228.383.471 bin TL
> 2. Ankara — 108.927.596 bin TL
> 3. İzmir — 59.970.021 bin TL
>
> *Kaynak: BDDK FinTürk (İllere Göre), Bireysel Bankacılık tablosu, 2026-06-30 dönem sonu.*

İkinci soru, tarih düzeltmesini sınayan:

> **"Konut kredisi faiz oranı 2026 içinde nasıl değişti?"**
> İlk gözlem 2 Ocak 2026 %36,38 · en düşük 6 Mart %34,17 · en yüksek 26 Haziran %41,56 ·
> son gözlem 3 Temmuz %41,45. **Hepsi cuma.** Eski eşlemeyle `02-01-2026` → 1 Şubat olurdu.

Agent tarafında da bir kapasite arızası çıktı ve kapatıldı: adaptör 1620 serinin tamamını
kataloğa alıyordu, 15'inde veri varken. Artık **sorgulanabilir** seri ile **kataloglu** seri
ayrı (ADR-0026); "böyle bir seri yok" ile "verisi henüz yüklenmemiş" ayrı cevaplar.

**Regresyon yok:** golden **7/7, 3/3 tekrarda %100 kararlı**; agent birim testleri 71;
lakehouse birim testleri **1015 → 1050**.

---

## 5. Sena'nın backlog'u, madde madde

| madde | durum |
|---|---|
| FinTürk kaynak keşfi | ✅ Zümral — endpoint, çeyreklik yayın, 81 il |
| FinTürk ingestion yolu | ✅ Zümral (Bronze) + Silver eşlemesi ve birim kanıtı bu turda |
| Authenticated EVDS CPI live smoke | ✅ bu turda — üç sözleşme farkı bulundu |
| TP.FG.J0 confidence terfisi | ⚠️ kapının 1. ve 2. adımı kapandı; **4. adım açık** (aşağıda) |
| Final E2E / demo acceptance | ⚠️ bir kez elle koşuldu ve geçti; **commit'li kabul testi yok** |
| BDDK Monthly Tablo 3/4 kalem keşfi | ❌ yapılmadı |
| BDDK Weekly kredi kalemi keşfi | ❌ yapılmadı |
| EVDS döviz kuru katalog kaydı | ❌ yapılmadı (1536 otomatik seri `unknown`, sayılmaz) |
| EVDS politika faizi native kod keşfi | ❌ yapılmadı |

---

## 6. Açık kalanlar — sahibiyle

### Veri ekibi

1. **`run_catalog_ingestion.py` provenance yazmıyor.** 1619 seriyi Bronze'a indiren tek yol
   aynı zamanda `meta.run`, `meta.run_artifact` ve `meta.ingest_warning`'i **hiç
   doldurmayan** yol. Ölçüldü: 225 artifact indi, `meta.run` **0 satır**. Script
   `IngestionPipeline.run()`'ı bilerek atlıyor (asset başına bağımsızlık için) ve
   provenance de onunla birlikte gidiyor. Sonuç: Silver satırlarında `run_id` boş,
   `quality_flag` kaynak uyarısı taşıyan satırlarda bile `ok`. Sena'nın teslim belgesinde
   tamamlanmış sayılan güvencelerden biri bu. `python -m lakehouse ingest` doğru yazıyor —
   sorun yalnızca toplu script'te.
2. **1534 serinin anlamı yok.** `measure_type: unknown` + `unit: null` oldukları sürece ne
   Silver'a girerler ne Gold işler. Dürüst bir kayıt, ama kapasite iddiası için sayılmazlar.
   Sena'nın notu burada doğru: *"her şeyi ekleyelim yerine birkaç iyi kanıtlanmış seri"* —
   hangi ailelerin elle doğrulanacağına karar verilmeli.
3. **95 EVDS serisi artifact kimlik çakışmasıyla düşüyor** (Zümral'ın notu). Kataloğdan
   çıkarılacak mı, yoksa `ArtifactRepository` aynı baytları farklı seriler için kabul edecek
   mi — karar verilmedi.
4. **EVDS çeyreklik yanıt biçimi doğrulanmadı.** Katalogda 233 çeyreklik seri var, hiçbirinin
   `Tarih` biçimi görülmedi. Silver o frekansı tahmin etmek yerine reddediyor.
5. **TP.FG.J0 kapı adımı 4:** `test_evds_cpi_silver.py` yeni canlı fixture'a yöneltilip
   sentetik yük silinmeli. O ana kadar sunumda bu seri için "live provider verified"
   denmemeli.
6. **Commit'li demo kabul testi.** Bu turda elle koşulan zinciri (bootstrap → ingest →
   silver → sorgu) tek komutla tekrarlayan bir kabul testi yok.

### Agent tarafı (bizde)

7. **Katalog token eşiği.** Sorgulanabilir seri sayısı üç haneye çıktığında kataloğun tamamı
   sistem promptuna sığmayacak (ADR-0013: ≈1000 seri = 28k token, %98 doğruluk; 3000 = %92).
   Ön-yükleme + retrieval kararı sıradaki iş.
8. **İl bazlı seriler 81 ayrı `DatasetSpec`.** `entity_id` boyutu şemada var ama FinTürk ili
   `series_id` içinde taşıyor. "Hangi ilde en yüksek?" sorusu bu turda `LIKE` ile çözüldü ve
   çalıştı; 81 ilin tamamı yüklendiğinde retrieval açısından yeniden bakılmalı.

---

## 7. Dal

Bu turun tamamı: `feature/lakehouse-integration-r3`
(taban: `feature/lakehouse-operationalization` + `feature/lakehouse-finturk-evds-housing`).

Beş commit, hepsi okunabilir ve ayrı: birleştirme · Silver üretim yolu · FinTürk birimi ·
EVDS tarih düzeltmesi · TÜFE canlı yakalama.
