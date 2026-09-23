# Agent ekibinden veri ekibine — ikinci tur

> **Tarih:** 11 Eylül 2026 · **Teslime:** 9 gün
> **İncelenen dal:** `feature/generic-adhoc-ingestion-v1` @ `84919cb` — diğer beş dalın
> hepsini içeriyor, kanonik dal olarak bunu alıyoruz.
> **Önceki tur:** [`DATA_TEAM_REQUESTS.md`](DATA_TEAM_REQUESTS.md)

---

## 0. Önce: birinci turun tamamı kapandı

Dalları okuduk ve çalıştırdık. Birinci turdaki P0 ve P1 maddelerinin **tamamı** teslim
edilmiş durumda:

| İstek | Teslim | Not |
|---|---|---|
| TÜFE serisi | `evds:TP.FG.J0` | Baz yılı kanıtlanana kadar `derived` — doğru karar |
| `first_obs` / `last_obs` | `silver/coverage.py` | Materyalizasyonla **aynı transaction'da**; boş snapshot kapsamı temizliyor |
| Untrusted → Silver okuma | `test_agent_untrusted_silver_read.py` | Üç test: okuma, kapsam, **Silver ⋈ katalog join** |
| Gold = fonksiyon | `gold/{align,cumulative,join,periods}.py` | Aşağıda ayrıca |
| Generic connector/parser | `generic/` | CSV · JSON · XLSX · HTML; signature > explicit > extension∧content-type |
| `register_series` | `catalog/registration.py` | `derived`/`profiler`/`draft` dışı **reddediliyor** |
| `adhoc` şeması | `020_adhoc_observations.sql` | Silver snapshot-replace gerekçesi sözleşmeye yazılmış |

**Gold imzası konusunda haklısınız, biz yanılmışız.** Önerimiz
`align_frequency(series_id, target, *, measure_type, default_agg, week_anchor)` idi;
siz bu parametreleri reddedip katalogdan okumayı seçtiniz. Gerekçeniz doğru: çağıran bir
dil modeli, ve `default_agg="sum"` geçen bir faiz serisi cevaba benzeyen bir sayı üretir.
`allow_unverified_semantics` kapısının `"false"` string'ini bile reddetmesi de aynı
disiplinin devamı. Bizim "kural katalogda, hesap kodda, karar modelde" ilkemizle birebir
örtüşüyor; agent tarafında bu fonksiyonları araç olarak saracağız.

Ad-hoc paketindeki dört eleştiriniz de yerinde — `adhoc` şemasının gerekçesini yazmamıştık,
`register_series` imzamız parametreleri seçilebilir gösteriyordu, format tespitine
değinmemiştik, SSRF sınırı kapsamımızda yoktu. Dördü de düzeltilmiş.

Bu turda dört madde kaldı. İlki demoyu durdurur.

---

## 1. Gerçek veri yüklenmiş bir veritabanı · **P0 — en kritik**

### Durum
Repoda **hiçbir yerde gerçek veri yok.** Bütün testler fixture ile koşuyor; Silver'da tek
bir gerçek BDDK/EVDS satırı üretilmemiş. `git ls-tree` ile doğruladık: commit edilmiş
`.parquet` / `.duckdb` yok (ki olmamalı — istediğimiz commit değil, **üretilebilirlik**).

### Neden bloke ediyor
Jüriye söylediğimiz kurulum şu: *"Şartnamedeki veriler demo ortamında halihazırda
yüklü olacak; dış kaynak istendiğinde canlı çekilecek."* Yani demo başlarken
2021-01 → 2026-06 aralığı Silver'da hazır olmalı. Bugün o veriyi üretecek çalıştırılabilir
bir yol yok — denetiminizdeki **D6** (giriş noktası) ile aynı iş.

Agent tarafında bugün kendi `dev_seed.py`'ımızla çalışıyoruz (BDDK Tablo 3-4, 4.002 satır).
Demo bununla yapılamaz; sizin Silver'ınıza bağlanmamız gerekiyor ve orada veri olmalı.

### İstek
```
python -m lakehouse bootstrap
    şema + katalog yükleme (mevcut bootstrap_database'in CLI yüzü)

python -m lakehouse ingest --source bddk_monthly --dataset bddk_monthly_housing_loans \
                           --start 2021-01 --end 2026-06
python -m lakehouse ingest --source evds --dataset evds_cpi --start 2021-01 --end 2026-06
    RAW → Bronze → Silver, meta.run ve meta.ingest_warning kalıcı

python -m lakehouse status
    seri başına first_obs/last_obs, satır sayısı, son run durumu
```

Ve bu komutlarla üretilmiş, katalogdaki **5 serinin tamamının** gerçek veriyle dolu olduğu
bir `lakehouse.duckdb`. Nasıl üretildiği belgede kalsın; dosyanın kendisi repoya girmesin.

### Kabul
`make demo-check` ya da eşdeğeri, sıfırdan başlayıp veritabanını üretebiliyor; sonunda
`meta.series`'te 5 serinin `first_obs`/`last_obs` alanları dolu ve `silver.fact_observation`
beş serinin de satırlarını içeriyor.

---

## 2. Kurulum ve bağlanma sözleşmesi · **P0**

`tools/` altındaki `LakehouseClient` uygulamasını **biz yazacağız** — `meta.series` →
`DatasetSpec` dönüşümü bizim tarafımızın modeli, sizde olmasının anlamı yok. Sizden
istediğimiz kod değil, üç netleştirme:

**(a) Import yolu.** `pyproject.toml`'da `package = false`, testler `from src.lakehouse…`
diye import ediyor. `agent-core` içinden `lakehouse` paketini nasıl göreceğiz? Üç seçenek:
uv workspace üyesi yapmak, `lakehouse-core`'u kurulabilir paket haline getirmek
(`package = true` + `[tool.hatch.build]`), ya da `PYTHONPATH`. Tercihiniz hangisi?

**(b) Veritabanı yolu.** `DEFAULT_DB_PATH` nedir, repo köküne göre nerede durur, ve
`.env`'de hangi değişkenle paylaşılır? Biz `LAKEHOUSE_PATH` kullanıyoruz.

**(c) Bağlantıyı kim açar.** Biz `connect_untrusted(db_path)` çağırıp sonucu
`QueryExecutor`'a sarmayı planlıyoruz — `test_agent_untrusted_silver_read.py`'daki
kalıbın aynısı. Doğru mu, yoksa bir fabrika fonksiyonu mu vereceksiniz?

Bu üçü bir sayfalık not; kod gerekmiyor.

---

## 3. Gold ve ad-hoc'un agent yüzeyinden erişilebilirliği · **P1**

İki boşluk, ikisi de aynı sınıftan: **untrusted bağlantıdan test edilmemiş.**

**(a) Gold fonksiyonları.** `align_frequency(connection, …)` bir `connection` alıyor.
Silver ve `meta.series` okuduğu için `connect_untrusted` yeterli olmalı — ama `tests/gold/`
altındaki testlerin hepsi trusted bağlantıyla koşuyor. Agent yüzeyinden çağrılabildiğini
gösteren **bir** entegrasyon testi isteriz: `connect_untrusted` ile açılmış bir bağlantıda
`align_frequency` haftalık faizi aylığa indiriyor.

Fonksiyonlar `read_only` bağlantıda geçici tablo/CTAS gerektiriyorsa bunu bilmemiz gerekir;
o durumda agent yüzeyi farklı kurulur.

**(b) `adhoc.fact_observation`.** Güvenlik testlerinde ve `connection.py`'de `adhoc` hiç
geçmiyor. Untrusted bağlantı bu şemayı görebiliyor mu? Göremiyorsa jürinin "yeni veriyi
getir ve analiz et" senaryosu yarım kalır: veri yüklenir, agent sorgulayamaz.
Bir test yeter.

---

## 4. Katalog genişletme · **P1 — kapasite iddiası için**

Katalog şu an **5 seri**. Demo senaryosu için tam isabet (konut kredisi aylık + haftalık,
konut faizi, KFE, TÜFE) — ama bizim iddiamız "büyük bir sistemi kaldırır" ve bunu
gösterecek ölçek yok.

Ekip içindeki bir ölçüm (E8, `busra/agent-v3` dalında) eşiği veriyor: katalog prompt'a
gömüldüğünde ~1000 seriye kadar seri seçme doğruluğu %98; 3000 seride %92'ye düşüyor ve
prompt 91k token'a çıkıyor. Yani **retrieval katmanının gerekli olduğunu göstermek için
bile** birkaç yüz seri gerekiyor.

### İstek, öncelik sırasıyla
1. **BDDK aylık Tablo 3 ve 4'ün tüm kalemleri** — 63 kalem, `is_subtotal` bayrağıyla.
   Parser bu bayrağı `BasitFont == "bold"` sinyalinden zaten üretebiliyor.
2. **BDDK haftalık bültenin kredi kalemleri.**
3. **EVDS'den birkaç makro seri** — USD/TRY, politika faizi, mevduat faizi, konut satışları.

Her biri için `aliases` alanı dolu olsun; seri seçimindeki isabeti en çok o belirliyor.
`semantic_confidence` dürüst kalsın — emin olunmayan seri `derived`.

Bu aynı zamanda jeneriklik iddiamızı da güçlendirir: katalog büyüdükçe motorun aynı kalması
gösterilebilir hale gelir.

---

## Kapsam dışı bıraktığınız ve bizim de beklemediğimiz

- **EVDS pencereleme (D4)** — sessiz veri kaybı riski, ama end-to-end'i bloke etmiyor.
  5 yıllık günlük seri çekildiğinde tetiklenir; şimdilik aylık/haftalık serilerle çalışıyoruz.
- **FinTürk** — şartnamedeki üçüncü BDDK kaynağı. İl bazlı sorular ancak bununla
  cevaplanır; demo senaryosunda geçmiyor.
- **PDF / OCR / VLM** — bizde. Borsa İstanbul altın PDF'i MIA'nın OCR modeliyle ölçüldü:
  2,4 s/sayfa, `<table>` çıktısı `pandas.read_html` ile DataFrame'e dönüyor. Ad-hoc
  akışında PDF'i biz tabloya çevirip size vereceğiz.

---

## Biz bu sırada ne yapıyoruz

Sizi beklemeden ilerleyen işler:

| İş | Bağımlılık |
|---|---|
| `LakehouseClient` adaptörü (`meta.series` + `silver.fact_observation`) | Madde 2'nin cevabı; o gelene kadar varsayımla yazıyoruz |
| Gold fonksiyonlarını araç olarak sarma | Madde 3(a) |
| Yapılandırılmış hata zarfı, döngü kilidi, grounding guard | yok |
| Katalog ön-yükleme + token eşiği | Madde 4 ölçüm için |
| Analitik araçlar (anomali, changepoint, korelasyon) | yok |
| Grafik üretimi | yok |
| Ad-hoc alt-agent (PDF/OCR tarafı) | Madde 3(b) |

---

## Zaman önerisi

| Ne zaman | Ne |
|---|---|
| **11 Eyl** | Madde 2 (üç netleştirme — bir sayfa) ve madde 1'in CLI'ı |
| **12 Eyl** | Madde 1: gerçek veri yüklenmiş veritabanı üretilir, `status` ile doğrulanır |
| **13 Eyl** | Madde 3: iki entegrasyon testi |
| **14–15** | Madde 4: katalog genişletme |
| **16** | Ortak entegrasyon: adaptör ↔ gerçek Lakehouse, örnek senaryonun dört serisiyle uçtan uca |

Madde 2'nin cevabı en acil olan; adaptörü bugün yazmaya başlıyoruz ve varsayımlarımız
yanlışsa yeniden yazmak gerekir.
