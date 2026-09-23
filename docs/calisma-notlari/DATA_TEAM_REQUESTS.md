# Agent ekibinden veri ekibine — somut istekler

> **Tarih:** 10 Eylül 2026 · **Teslime:** 10 gün
> **İncelenen dallar:** `feature/silver-v1` (4cba3bf), `feature/lakehouse-integration` (2f9234d),
> `feature/lakehouse-ingestion-observability` (29bbf6f), `feature/lakehouse-metadata-catalog`
> **Bağlam:** `docs/LAKEHOUSE_CONTRACT.md` (sözleşme), `docs/calisma-notlari/LAKEHOUSE_BUILD_PLAN.md` (inşa planı),
> `lakehouse-core/docs/audits/…denetim-raporu-2026-09-10.md` (kendi denetiminiz)

Bu belge "ne yapmalısınız" değil, **"agent şu an neyi yapamıyor ve neden"** listesidir.
Her madde bir demo senaryosuna veya jüri kriterine bağlanmıştır; öncelik ona göre.

---

## 0. Önce: ne hazır, ne çalıştırdık

Kodunuzu okumakla kalmadık, çalıştırdık. `silver-v1` dalında **420 test geçiyor**, Silver
kabul testleri (59) geçiyor, `bootstrap_database` ile `meta.series` 4 seriyle doluyor.

Sizin önerdiğiniz iş bölümüne uyuyoruz: **yayın katmanı ve Gold sizde, `LakehouseClient`
adaptörü bizde.** Aşağıdaki liste bu bölünmeye göre.

Denetiminizdeki iki bulguyu bizim tarafta kapatabiliriz — iletmek için:
- **D3 (EVDS canlı çağrılmadı):** Gerçek key ile `evds3/igmevdsms-dis/series=TP.FG.J0&startDate=…&type=json`
  doğrulandı, TÜFE 2025-01 = 2819,65 döndü. URL biçiminiz doğru.
- **D8 (BDDK TLS):** `truststore.inject_into_ssl()` ile doğrulama **açıkken** HTTP 200
  alındı; `verify=False`'a gerek yok. Detay: `docs/adr/0020`.

---

## P0 — demo senaryosunu bloke edenler

### 1. TÜFE serisi katalogda yok → enflasyondan arındırma yapılamıyor

Örnek senaryonun 2. sorusu: *"konut kredisi tutarlarını enflasyondan arındır."* Bunun için
TÜFE gerekir. Katalogda `evds:TP.KTF12` (faiz) ve `evds:TP.KFE.TR` (KFE) var; **`TP.FG.J0`
(TÜFE) yok.**

**İstek:** `catalog/series/evds.yml`'e `evds:TP.FG.J0` kaydı + Silver adapter eşlemesi.
Öneri:

```yaml
  - series_id: evds:TP.FG.J0
    native_code: TP.FG.J0
    dataset_id: evds_cpi
    name_tr: Tüketici Fiyat Endeksi (TÜFE, 2003=100)
    description: >-
      TÜİK/TCMB TÜFE genel endeksi, aylık, baz 2003=100. Reel dönüşümde bölen
      olarak kullanılır: reel = nominal / (TÜFE / TÜFE_baz). Endeks seviyesidir,
      aylık değişim oranı DEĞİLDİR.
    aliases: [tüfe, enflasyon, tüketici fiyat endeksi, fiyat endeksi, TÜFE endeksi]
    tags: [enflasyon, fiyat, tcmb, tuik]
    frequency: monthly
    unit: index
    measure_type: index
    default_agg: last
    semantic_confidence: verified
    semantic_source: source_service
    metadata_url: https://evds3.tcmb.gov.tr/igmevdsms-dis/serieList/type=json&code=TP.FG.J0
    status: active
```

Baz yılı `docs/sources/evds.md`'ye kanıtla girerse `verified`, girmezse `derived` — sizin
kuralınız.

### 2. `first_obs` / `last_obs` hiç hesaplanmıyor → kapsam kontrolü boş

Katalog sözleşmeniz doğru olarak diyor: bunlar operasyonel, loader yazmaz. Ama **hiçbir
kod da yazmıyor.** Agent'ın halüsinasyon koruması (ADR-0010: "2015 sorulursa 'veri 2021'de
başlıyor' de") kapsamı katalogdan okuyor; boşsa koruma çalışmaz.

**İstek:** Silver materyalizasyonundan sonra `meta.series.first_obs/last_obs`'u
`silver.fact_observation`'dan hesaplayıp yazan bir adım:

```sql
UPDATE meta.series m SET
  first_obs = s.lo, last_obs = s.hi
FROM (SELECT series_id, MIN(observation_date) lo, MAX(observation_date) hi
      FROM silver.fact_observation GROUP BY series_id) s
WHERE m.series_id = s.series_id;
```

`materialize_fact_observation_snapshot` sonunda ya da ayrı bir `refresh_coverage()`.

### 3. `connect_untrusted` ile `silver.fact_observation` okunabildiğinin teyidi (D1)

Denetiminiz D1'de "untrusted bağlantı yalnız `meta.*` görüyor" demişti; Silver
materyalizasyonu register + `CREATE TABLE` yoluyla aynı dosyaya yazıyor, dolayısıyla görünür
olması gerekir. **İstek:** bunu kanıtlayan tek bir entegrasyon testi — Silver'ı materyalize
et, `connect_untrusted` + `QueryExecutor` ile `SELECT … FROM silver.fact_observation` çalıştır,
satırları doğrula. Bizim adaptör tam bu yolu kullanacak.

---

## P0 — Gold: tablo değil, **fonksiyon** olarak

Gold henüz yok (`models/gold/.gitkeep`). Nasıl inşa edildiği, agent'ın yeni veriyle ne
yapabileceğini belirliyor.

| | Gold = SQL tablo | Gold = parametreli fonksiyon |
|---|---|---|
| Bilinen 4 seri | çalışır | çalışır (tablo fonksiyonla üretilir) |
| **Jürinin getireceği yeni seri** | **çalışmaz** — tablo o seri için yok | çalışır — agent fonksiyonu yeni seriye uygular |

**İstek:** Gold dönüşümlerini önce fonksiyon olarak yazın, tabloları onlardan üretin:

```python
align_frequency(series_id, target: "monthly"|"quarterly", *, measure_type, default_agg,
                week_anchor) -> DataFrame
    # stock → last, flow_periodic → sum, rate → default_agg, ratio → reddet (yeniden hesapla)
decompose_cumulative(series_id, *, measure_type) -> DataFrame
    # flow_ytd → yıl içi fark, flow_cumulative → düz fark, diğer → olduğu gibi
join_on_period(series_ids: list, target) -> DataFrame
    # observation_date = dönem sonu kuralıyla
```

Kural katalogdan (`measure_type`, `default_agg`) gelir, fonksiyona gömülmez.
`semantic_confidence` in `('derived','unknown')` olan seride fonksiyon **otomatik
uygulanmaz** — agent önce kullanıcıya sorar. Bu sizin "unknown'da otomatik dönüşüm yapma"
kuralınızın uzantısı.

Agent bu fonksiyonları araç olarak çağıracak; kararı model, hesabı fonksiyon, kuralı katalog.

---

## P1 — ad-hoc veri: "yeni veriyi getir ve belgele"

Jüri bunu sınayacak; format her şey olabilir (CSV, Excel, HTML, PDF, görsel, "şu seriyi çek").
İş bölümü: **biz** alt-agent'ı, biçim tespitini, profilleme ve semantik öneriyi yazıyoruz;
**siz** pipeline'ın generic girişini.

### 4. Generic connector + parser

Mevcut connector/parser'lar kaynağa özel. Gereken: URL/dosya alan, `media_type`'a göre
CSV/Excel/HTML-tablo/JSON'u Bronze'a indiren bir `GenericTabularConnector` +
`GenericTabularParser`. PDF/görsel bizde (OCR/vision), çıktısı size CSV olarak gelir.

### 5. Katalog loader'a programatik giriş

`load_series_catalog` yalnız Git'teki YAML'ı okuyor — doğru, `verified` için. Ama
otomatik çıkarılmış bir kayıt için sözlüğünüzde zaten yer var: `semantic_confidence:
derived`, `semantic_source: profiler`, `status: draft`. **İstek:** `register_series(record,
*, confidence="derived", source="profiler", status="draft")` — 18 doğrulama kuralından
geçen, YAML'a değil doğrudan `meta.series`'e yazan bir yol. Sözleşmenizdeki "insan yazar"
kuralı `verified` için geçerli kalır.

### 6. `adhoc` şeması ya da Silver'a ekleme yolu

`materialize_fact_observation_snapshot` **tam snapshot değiştiriyor** (README: "not append,
upsert, merge"). Ad-hoc bir seri eklemek için ya tüm staging'i birleştirip Silver'ı yeniden
üretmek gerekir, ya da ayrı bir yer.

**Öneri:** `adhoc.fact_observation` — aynı şema, ayrı şema adı. Ana veri kirlenmez, demo
sonrası silinir, "kaynak: kullanıcı yükledi" ayrımı yapısal olur. Agent iki şemayı da
sorgular; katalogda `source_id: adhoc`.

### 7. Çalıştırılabilir giriş noktası (denetim D6)

Her ingestion şu an test içinde elle kuruluyor. Demo öncesi ve ad-hoc akışta tek bir
komut lazım: `python -m lakehouse ingest --source evds --dataset evds_cpi` ve
`python -m lakehouse ingest-file <yol|url> --dataset-id …`. Ayrıca `python -m lakehouse
bootstrap` (şema + katalog + ilk 5 seri).

---

## P1 — güvenilirlik

### 8. EVDS pencereleme (denetim D4)
İstek başına gözlem sınırı aşılınca sessiz kırpma. 5 yıllık günlük seri bunu tetikler.
Parser uyarıyor, observability artık kaydediyor — ama veri yine eksik. Tarih penceresiyle
çoklu istek + birleştirme.

### 9. `quality_flag`'in agent'a görünmesi
Silver'da var. Adaptör `source_warning` / `missing_value` satırlarını provenance uyarısı
olarak taşıyacak; sizden ek iş yok, yalnız bilginiz olsun — jüri "veriyi nasıl
doğruluyorsunuz" dediğinde gösterilecek şey bu.

---

## P2 — kapsam

### 10. Katalog genişletme
4 seri demo senaryosu için yeter, jeneriklik ve retrieval ölçümü için yetmez. Hedef:
BDDK aylık Tablo 3 ve 4'ün tüm kalemleri (`is_subtotal` bayrağıyla), haftalık bültenin
kredi kalemleri, EVDS'den kur ve politika faizi. Retrieval katmanının (BM25 + embedding)
kazancı ancak onlarca seriyle ölçülebilir.

### 11. FinTürk (denetim D7)
Şartnamede üç BDDK kaynağından biri; hiç yok. İl bazlı sorular ("İstanbul'da konut
kredisi") ancak bununla cevaplanır. P2 çünkü demo senaryosunda geçmiyor; ama jüri
"üç kaynağı da aldınız mı" diye sorabilir.

---

## Bizim tarafta değişenler — sizin için bilgi

| Bizim alan | Sizin sözlüğünüze uyum |
|---|---|
| `semantic_type` + `cumulative` (iki alan) | → `measure_type` tek enum (`flow_ytd`, `flow_cumulative`) |
| `unit: "milyon TL"` + `unit_multiplier` | → `unit: TRY_mn` sözlüğü, çarpan adaptörde |
| `donem` = ayın ilk günü | → dönem sonu (yapıldı, ADR-0018) |
| `DatasetSpec` (veri-seti merkezli) | `meta.series` satırları `dataset_id`'ye göre gruplanır → her grup bir `DatasetSpec`, her seri bir kalem |

Adaptör `silver.fact_observation` + `meta.series` üstüne yazılıyor; Gold geldiğinde
`execute_sql` yüzeyi genişler, kod değişmez.

---

## Kabul kriterleri — "hazır" demek için

| # | Test |
|---|---|
| 1 | `meta.series`'te `evds:TP.FG.J0` var, Silver'da satırları var |
| 2 | Materyalizasyon sonrası her seride `first_obs/last_obs` dolu |
| 3 | `connect_untrusted` ile `silver.fact_observation` sorgulanabiliyor (test) |
| 4 | `align_frequency("evds:TP.KTF12", "monthly", …)` haftalık faizi aylık ortalamaya indiriyor; `("bddk_weekly:5690_3", …)` haftalık krediyi ay sonu değerine |
| 5 | `register_series(…, confidence="derived")` 18 kuraldan geçip `meta.series`'e `draft` yazıyor |
| 6 | `python -m lakehouse bootstrap && python -m lakehouse ingest --source evds --dataset evds_cpi` sıfırdan çalışıyor |

## Zaman önerisi

| Ne zaman | Ne |
|---|---|
| **11 Eyl** | 1, 2, 3 — üçü de küçük; adaptörün hemen ihtiyacı var |
| **12–13** | Gold fonksiyonları (4 numaralı blok) |
| **14–15** | Generic connector/parser, `register_series`, `adhoc` şeması, giriş noktası |
| **16–17** | Pencereleme, katalog genişletme |
| **18** | Ortak entegrasyon: adaptör ↔ gerçek Lakehouse, uçtan uca demo senaryosu |

Sorular için sözleşme belgesi ve `docs/adr/`; her kararın gerekçesi orada.
