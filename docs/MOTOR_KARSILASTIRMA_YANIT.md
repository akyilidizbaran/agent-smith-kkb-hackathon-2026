# Motor karşılaştırmasına yanıt — 11 Eylül 2026

> Kimden: Baran (`feature/agent-engine`) · Kime: Büşra (`feature/busra/agent-v3`)
> Yöntem: dalı çekip protokolü kendi başıma koştum, sonra raporundaki her iddiayı
> ayrı ayrı ölçtüm. Aşağıdaki hiçbir sayı senin raporundan kopyalanmadı.

---

## 0. Kısa cevap

Benchmark koşucusu, grounding guard, ön-yükleme ve sınır doğrulayıcı **iyi işler** ve
üçünü almak istiyorum — birini zaten aldım. Ama önerine bir itirazım var ve itiraz
"benim motorum daha iyi" değil: **iki motoru birlikte yaşatmaya karşıyım.** Ölçülen
üstünlüğün tamamı motordan bağımsız dört modülden geliyor; bunu sen de protokolün
§6'sında yazmışsın. Modülleri taşıyalım, ikinci harness'ı taşımayalım.

Hangi harness'ın kalacağı ayrı ve küçük bir karar. Seninki kalsın diyorsan bizim
guard'larımızı (dönem filtresi, kapsam reddi, workspace kuralları, hata zarfı) oraya
ben taşırım. İtiraz **ikiliğe**, seçime değil.

---

## 1. Replikasyon: sayılar senin bildirdiğinden dar

Aynı protokol, aynı iki şema, `--set all --repeat 3`, aynı gün, aynı model.

| | senin koşun | benim koşum |
|---|---|---|
| seed · ekip | 14/18 | **15/18** |
| seed · V3 | 17/18 | 17/18 |
| Silver · ekip | 13/18 | **15/18** |
| Silver · V3 | 16/18 | **15/18** |

Silver'da **berabere** çıktı, ve kaybedilen vakalar da örtüşmüyor:

| Silver'da kalan vakalar | senin koşun | benim koşum |
|---|---|---|
| ekip | L9-02, L10-01, L4-01, G4, L11-02 | L9-02, L10-01, **L6-04** |
| V3 | L10-01, G3 | L10-01, G3, **L6-04** |

İki koşuda ortak olan yalnızca L9-02/L10-01 (ekip) ve G3/L10-01 (V3). Geri kalanı
koşudan koşuya yer değiştiriyor.

Bu bir itiraz değil, protokole bir not: **pass^3 üç tekrarla, paylaşılan bir uçta,
kararı taşıyacak kadar kararlı değil.** Karar kuralının 1. basamağı "düşük olan
elenir" diyor; iki koşuda iki farklı sonuç veren bir ölçüt eleme yapamaz. Süre için
zaten yazmışsın ("oranlar anlamlı, mutlak saniyeler değil") — aynı uyarı pass^3 için
de geçerli. Bende V3 seed'de G3 18,4 s, G5 26,2 s sürdü; senin koşunda 6 s civarıydı.

Bu gözlemin ne kadar güçlü olduğunu §3.3'te kazara ölçtüm: **aynı kodu** iki kez
koşturdum ve bir vaka 0/3'ten 3/3'e, bir hata sınıfı 21'den 0'a gitti.

**Kararlı olan tek şey tur ve adım sayısı** ve orada fark net:

| | ekip | V3 |
|---|---|---|
| seed · araç adımı / LLM turu | 5,2 / 5,9 | **1,6 / 3,3** |
| Silver · araç adımı / LLM turu | 4,4 / 5,0 | **1,6 / 3,1** |

Bu ölçüm gürültüye dayanıklı ve tek bir sebebi var: ön-yükleme. Keşif turları LLM
turu olmaktan çıkıyor. Doğru teşhis.

---

## 2. Raporundaki iki bulgu doğruydu — kök nedenleri kapattım

### 2.1 Silver'daki `SQL_FAILED` yığını

Teşhisin doğru: model `dataset_id`'yi tablo adı sanıyor. Sebep atfın eksikti — kalıp
`lakehouse_describe` çıktısında **zaten vardı** (`DatasetSpec.notes` → `to_prompt_card`).
Sorun modelin önce **arama** yapması ve arama çıktısının kimliği "tablo" diye sunup
fiziksel erişimden hiç söz etmemesiydi.

Arama artık adaptörün ürettiği SQL'i veriyor (ADR-0024 `series_sql`) — tarif değil,
kopyalanıp çalıştırılabilir sorgu:

```
'bddk_monthly:konut_toplam' bir tablo adı DEĞİL. SQL'de şöyle eriş:
SELECT observation_date, value FROM silver.fact_observation WHERE series_id = '...' ORDER BY observation_date
```

Kimliğin tablo adı olup olmadığı tahmin edilmiyor: adaptörün SQL'inde `FROM <dataset_id>`
geçiyorsa satır hiç yazılmıyor — seed'de olduğu gibi.

**Bu düzeltme V3'e ulaşmıyor**, çünkü `kkb_agent_v3/tools/lakehouse.py` kendi
`LakehouseSearchTool`'unu taşıyor. `full` modda önemi yok; `search` modunda (yani
gerçek katalogda, §3.1) aynen geçerli.

### 2.2 L4-01'deki adım limiti

Kilidimiz aracı koruyordu ama döngüyü kırmıyordu: model `DUPLICATE_CALL` alıp aynı
çağrıyı yedi kez daha istedi — benim koşumda ekip motoru seed'de toplam
**`DUPLICATE_CALL×21`** topladı. Hata "tekrar denenebilir" sınıfındaydı, model de
tekrar denedi.

İkinci tekrardan sonra harness artık araçları geri alıyor; model ancak cevap
yazabiliyor. Sahte LLM ile test edildi: araç 1 kez çalışıyor, adım limitine
gidilmiyor, son tur araçsız.

### 2.3 Bonus: L9-02'nin kökü de bizdeydi

Kapsam kontrolümüz **yıl** çözünürlüğündeydi. Veri 2026-06'da bitiyorken "2026
Ağustos kaç?" sorusunda 2026 kapsam içinde göründüğü için hiçbir şey tetiklenmiyordu.
Model o yılın mevcut aylarını çekip tablo kuruyor, sonra "Ağustos yok" diyordu —
cevap doğru ama ekranda sayı dolu bir tablo kalıyor. Artık ay çözünürlüğünde:
`OUT_OF_COVERAGE`, tekrar denenemez, tablo kurulmuyor.

---

## 3. Raporunda görünmeyen dört şey

### 3.1 Ön-yükleme gerçek katalogda çalışmıyor

`build_catalog_context`'i veri ekibinin gerçek veritabanına karşı koştum (1620 seri,
`feature/lakehouse-integration-r3`):

```
mod=search   tahmini token=44.157   dataset=1620
```

Bütçe 6.000. Token muhafızı `full` modu ölçüyor, sonra **hiç ölçmediği** bir moda
düşüyor: 1620 satırlık dizin, bütçenin **7,4 katı**. Üstelik o 1620 satırın 1605'i
`silver.fact_observation`'da tek gözlemi olmayan serileri gösteriyor.

Bizim ADR-0026 değişikliğiyle (kataloglu seri ≠ sorgulanabilir seri) aynı çağrı:

```
mod=search   tahmini token=522   dataset=15
```

Yani ön-yüklemenin gerçek lakehouse'da işe yaraması bizim adaptör değişikliğimize
bağlı — ve tersi de doğru: bizim sistem promptumuz aynı veritabanında 845 token,
ama keşif turlarını ödüyoruz. İkisi birbirinin eksiğini kapatıyor.

**Doğru hedef ikisi de değil:** kataloğun tamamını değil, soruya en yakın k seriyi
ön-yüklemek. ADR-0013 (token eşiği) ile ADR-0021 (retrieval katmanı) tam burada
buluşuyor. `search` modu bu iş bitene kadar bir dizin değil, **sınırlı** bir dizin
basmalı.

### 3.2 `measure_rules` ve `evidence_domains` yüklenip bırakılıyor

`domain/loader.py`'ın kendi docstring'i şöyle diyor:

> `## measure_rules` semantic_type → izinli/yasak dönüşüm (boundary validator)
> `## evidence_domains` dış kanıtta öncelikli alan adları (SearchProvider)

`grep`: `measure_rules` yalnız loader ve kendi testinde geçiyor; `core/validator.py`
onu hiç okumuyor, `check_policy` lakehouse araçlarında hiç uygulanmamış. Üç katmanlı
doğrulayıcı pratikte **şema → SQL guard → referans** olarak çalışıyor; politika
katmanında SQL guard dışında içerik yok.

Kusur değil, yazılmamış iş — ama "sınır doğrulayıcı politika katmanı" V3'ün
üstünlüğü olarak sayılıyorsa bu satırın düzeltilmesi lazım. Aynı şekilde
`SERIES_NOT_MATERIALIZED` kodu tanımlı ve hiç üretilmiyor; o kodun mekanizmasını
bu hafta ben yazdım (ADR-0026). Birleştirmede doğal bir buluşma noktası.

### 3.3 Koşucu, ölçmek istediğin motoru sessizce değiştirebiliyor

Bunu düzeltmelerimi ölçmeye çalışırken buldum ve ayrı bir başlık hak ediyor, çünkü
ölçüm aracının kendisiyle ilgili.

`scripts/run_benchmark.py` başında:

```python
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
```

`insert(0, ...)` **PYTHONPATH'in önüne geçiyor**. Yani ekip motorunu başka bir
checkout'tan koşmak için `PYTHONPATH=<başka>/src` vermek işe yaramıyor: `import
kkb_agent` yine koşucunun kendi `src`'sinden geliyor. Ben tam olarak bunu yaptım ve
"düzeltmelerden sonraki" diye bir tur koştum; sonradan fark ettim ki o tur da
düzeltmesiz kodu ölçmüş.

Bu kazadan çıkan sonuç, düzeltmelerden bağımsız olarak önemli — **aynı kodun iki
koşusu şunları verdi:**

| | tur 1 | tur 2 | ikisi de aynı kod |
|---|---|---|---|
| seed · ekip pass^3 | 15/18 | 16/18 | evet |
| Silver · ekip pass^3 | 15/18 | 16/18 | evet |
| seed · `DUPLICATE_CALL` | 21 | 0 | evet |
| Silver · `SQL_FAILED` | 15 | 18 | evet |
| L4-01 (seed) | 0/3 | 3/3 | evet |
| L6-04 (Silver) | 0/3 | 3/3 | evet |

Bir vakanın 0/3'ten 3/3'e çıkması ve bir hata sınıfının 21'den 0'a inmesi — **kod
değişmeden**. `--repeat 3` ile pass^3, bir motoru elemeye yetecek çözünürlükte değil.

Önerim: `sys.path.insert` yerine "zaten import edilebiliyorsa dokunma" ya da açık
bir `--engine-src` seçeneği; ve karar kuralının 1. basamağına bir eşik (ör. fark
≥2 vaka) ya da `--repeat` için daha yüksek bir varsayılan.

### 3.4 Paralel çağrı bizim bağlantımızı yarıştırıyor

`AgentConfig.parallel` varsayılan `True`. Bir turdaki iki okuma aracı aynı adaptörü
ve **tek `DuckDBPyConnection`'ı** kullanıyor. Ölçtüm — 4 iş parçacığı, 800 sorgu:

```
düzeltmeden önce: 2 istisna  (TypeError: object of type 'NoneType' has no len())
düzeltmeden sonra: 0 istisna
```

Sonuç kümesi çağıranın altından çekiliyor. Oran küçük ama hata biçimi kötü: SQL
hatası gibi bile görünmüyor, harness'ın içinden gelen anlamsız bir tip hatası gibi
duruyor — demoda teşhis edilemez. Her sorgu artık kendi imlecinde (`cursor()`,
sertleştirilmiş yapılandırma korunuyor). Bu bizim katmanımızdaki bir eksikti; senin
paralelliğin onu görünür kıldı.

**Not:** V3 bunu benchmark'ta yakalamamış olmasının sebebi, vaka başına ortalama 1,6
araç adımı yapması — paralellik neredeyse hiç devreye girmiyor. Araç sayısı arttıkça
(analitik, grafik, web) devreye girecek.

---

## 4. L6-04 hakkında: V3 çözmüyor, ıskalıyor

Raporun L6-04'ü V3'ün geçtiği, ekibin kaldığı bir vaka olarak listeliyor. Sebep
doğru tespit edilmiş (ikinci sorgu `as_active_table=true` ile 18 satırlık tabloyu 1
satıra indiriyor), ama **V3'te de aynı tasarım var**:

| | ekip | V3 |
|---|---|---|
| `as_active_table` varsayılanı | `True` | `True` |
| açıklama | "Emin değilsen true." | "Sadece ara kontroller için false." |

V3 geçiyor çünkü ön-yükleme sayesinde tek sorgu yapıyor; tabloyu ezecek ikinci sorgu
hiç olmuyor. Benim Silver koşumda V3 de L6-04'ü **2/3** aldı — yani ıskalama garanti
değil.

Bu önemli, çünkü demo senaryosunun 2. ve 3. sorusu tam olarak çok turlu ("tabloyu
bozmadan enflasyondan arındır"). Orada risk ikimizde de duruyor ve çözümü bir
harness kuralı olmalı, tur sayısının yan etkisi değil.

---

## 5. Aldıklarım

**Grounding guard'ı aldım** — modülü `kkb_agent_v3/core/grounding.py`'dan
`kkb_agent/core/grounding.py`'a taşıdım ki tek kopya olsun. Saf fonksiyon, yalnız
`re` kullanıyor, ne harness'ı ne adaptörü tanıyor; V3 kendi kopyası yerine bunu
import edebilir. Türkçe/İngiliz sayı biçimi ayrımını çözmüş hâlde geldi — o ayrıntıyı
kendim yazsam ilk seferde bulamazdım.

Döngüdeki davranış: temiz cevap geçer; eksik sayı ya da nedensellik ifadesi varsa
cevap bir kez gerekçesiyle geri gönderilir; ikinci denemede de eksikse cevap yine
gider ama doğrulanamayan değerler işaretlenir. ADR-0027.

Bu bizim kör noktamızdı ve tam da jürinin okuyacağı yerdeydi: golden vakalarımız
üretilen **tabloyu** kontrol ediyor (ADR-0007), serbest metni değil.

**Sırada:** sınır doğrulayıcı ve sınırlı ön-yükleme. İkisi de ortak katmana,
`kkb_agent_v3`'e değil.

---

## 6. Önerim

1. **Modüller ortak katmana, tek kopya.** `grounding.py` taşındı. `validator.py`,
   `context.py` ve paralel yürütme de aynı yere gelsin; iki motor da import etsin.
   Böylece "hangi motor" sorusu bir bakım sorusu olmaktan çıkıyor.
2. **Tek harness.** Hangisi olduğu ikincil. İki harness'ın maliyeti şu an bile
   görünür: ön-yükleme dört serilik seed'de ölçülmüş ve orada gerçekten iyi
   (1.387 token, tur 6,9 → 3,3); gerçek katalogla hiç koşulmadığı için 44k token'a
   çıktığı görülmemiş. Ortak katmanda olsaydı, `list_datasets()`'i biz değiştirdiğimiz
   gün aynı ölçüm iki motorda birden koşacaktı.
3. **Benchmark koşucusu ortak ölçüm aracı olsun** ve `--repeat` varsayılanı 3'ten
   yukarı çıksın; ya da karar kuralının 1. basamağı "pass^3 farkı ≥2 vaka" gibi bir
   eşik istesin. İki koşuda iki farklı sıralama çıktı.
4. **L10-01 (netleştirme) ikimizde de 0/3.** `clarify` aracı sende planlı; ona
   dokunmuyorum.
5. **Ön-yükleme sınırlansın.** Kataloğun tamamı değil, retrieval'ın seçtiği k seri.
   ADR-0013 + ADR-0021.

Karşı görüşün varsa protokol §6 üzerinden konuşalım — ama bence §6'nın son cümlesi
zaten benim söylediğim şey: *"Sınır doğrulayıcı, grounding guard ve hata zarfı
motordan bağımsız modüller."*
