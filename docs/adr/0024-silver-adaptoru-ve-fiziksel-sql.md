# ADR-0024: Silver adaptörü; fiziksel SQL üretimi adaptörün işidir

**Durum:** Kabul edildi · **Tarih:** 2026-09-11

## Bağlam
Veri ekibinin `silver.fact_observation` + `meta.series` yapısı hazır ama gerçek veri
henüz yok ve kurulum/paketleme sözleşmesi netleşmedi (`DATA_TEAM_REQUESTS_R2` madde 1–2).
Beklemek yerine adaptörü yazdık: `lakehouse-core` paketini **import etmeden**, çünkü
ihtiyacımız olan tek şey iki tablo ve salt-okunur bir bağlantı — ikisi de SQL'le erişilebilir.
Sertleştirilmiş bağlantımız (ADR-0020) onların `connect_untrusted`'ıyla aynı sınırlara sahip.

Geliştirme için kendi BDDK seed'imiz Silver şemasına çevrildi (`scripts/dev_seed_silver.py`,
4 seri × 66 gözlem). Gerçek veritabanı geldiğinde değişen tek şey `LAKEHOUSE_PATH`.

## Karar 1 — her SERİ bir `DatasetSpec`
`meta.series` seri-merkezli; `unit` ve `measure_type` serinin özelliği, tablonun değil.
Tek bir "fact_observation" spec'i üretilseydi bu alanlar kaybolur, `lakehouse_search`
tabloyu bulup seriyi bulamazdı. Katalog büyüdüğünde aranan şey seri olacağı için doğru
granülarite budur.

Çeviriler tek noktada: `measure_type` → `SemanticType` + `CumulativeKind`
(`flow_ytd` → FLOW + YTD), `TRY_mn` → "milyon TL" + çarpan 1e6, `frequency` → bizim enum.

`semantic_confidence != verified` olan seri, spec'inin `notes` alanında **uyarı taşır**:
"frekans dönüşümü, kümülatif çözme ve birim çevirisi otomatik yapılmaz". Veri ekibinin
Gold katmanındaki `UNVERIFIED_SEMANTICS` kapısının agent tarafındaki karşılığı.
`quality_flag` 'ok' değilse sorgu sonucu uyarı taşıyor — güven katmanının parçası.

## Karar 2 — `series_sql` protokole eklendi
Golden'ı Silver üzerinde koşarken G6 düştü: `workspace_add_column` `dataset_id`'yi doğrudan
tablo adı sanıp `FROM bddk_monthly:tasit_toplam` üretiyordu. Eski adaptörde doğruydu
(dataset = tablo), Silver'da değil (dataset = uzun formatlı tablodaki seri).

Bu bir **soyutlama sızıntısıydı**: araç, fiziksel yerleşimi biliyordu. Düzeltme, SQL üretimini
araçtan alıp adaptöre vermek:

```python
LakehouseClient.series_sql(dataset_id, *, key_column, value_column,
                           filter_column=None, filter_value=None) -> str
```

Aynı çağrı iki adaptörde farklı SQL üretiyor:

```
Silver : SELECT observation_date, value FROM silver.fact_observation
         WHERE series_id = 'bddk_monthly:tasit_toplam' ORDER BY observation_date
Seed   : SELECT donem, toplam FROM bddk_aylik_krediler
         WHERE kalem = 'Tüketici Kredileri - Taşıt'
```

Kolon doğrulaması da adaptöre taşındı; katalogdan yapılıyor, model var olmayan kolon
uyduramıyor. Araç yalnız *ne istediğini* söylüyor, *nereden geldiğini* bilmiyor.

## Ölçüm
Golden set **iki şemada da 7/7**: Silver 54 s (vaka başına 8 s), eski seed 67 s.
Birim testleri 49 → 60; `tests/test_silver_lakehouse.py` şema varsayımlarımızın kaydı —
gerçek veritabanı geldiğinde aynı testler ona karşı da koşar.

Yol boyunca ikinci bir hata: adaptör seçimi için ayrı bir bağlantı açan yoklama, DuckDB'nin
"aynı dosyaya farklı yapılandırmayla ikinci bağlantı" reddine takıldı. `open_lakehouse()`
artık Silver adaptörünü kurmayı deneyip beklenen ilişkiler yoksa düşüyor — tek bağlantı.

Golden kontrollerinden biri kolon adına bağlıydı (`_has_cols("donem")`); Silver'da o kolon
`observation_date`. Şema-bağımsız hale getirildi (`_has_time_column`): vakalar şemaya değil
**davranışa** bakıyor. Gerçek Lakehouse'a geçişte yeniden yazılmamalarının sebebi bu.

## Sonuç
Agent bugün iki veri yerleşiminde de çalışıyor. Gerçek Lakehouse geldiğinde beklenen iş:
`.env`'de yol değişikliği + `tests/test_silver_lakehouse.py`'ın gerçek veriye karşı koşması.
Gold fonksiyonlarını araç olarak sarmak ayrı bir iş ve `lakehouse-core` import'u gerektiriyor —
kurulum sözleşmesi (madde 2a) oraya bakıyor.
