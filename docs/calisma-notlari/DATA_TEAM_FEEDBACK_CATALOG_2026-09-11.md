# Agent ekibinden data ekibine — katalog ve veri (11 Eylül 2026)

> Kime: Sena. Referans dal: `feature/lakehouse-operationalization` (Elif + Sena hattı; agent tarafı bunu kanonik alıyor).
> Neden şimdi: Elif'in devir mesajına göre kalan işler Sena'da; 9 gün var. Bu belge **üç küçük, kesin istek** içerir; hepsi mevcut sözleşmelerin içinde.
> Etiketler: `[SRC]` repodan okundu · `[EMP]` ölçtük · `[INF]` çıkarım · `[REC]` öneri

## 0. Teyit: teslimleriniz agent tarafında çalışıyor

- Baran'ın `SilverLakehouse` adaptörü `meta.series` + `silver.fact_observation` üzerinde golden 7/7 `[SRC]`; V3 motoru aynı şemada çalışıyor `[EMP]` (11 Eylül).
- Gold'un "kural katalogda, hesap kodda, model yalnız soruyu seçer" ilkesi bizim boundary validator'la birebir; Gold fonksiyonlarını araç olarak saracağız, yeniden yazmayacağız.
- Generic/ad-hoc yol sayesinde CSV/XLSX/JSON/HTML alımı agent'ta yeniden yazılmıyor; bizde yalnız PDF/OCR kalıyor (E7).

## 1. Mevcut katalog: 5 seri, hepsi kullanılabilir `[SRC]`

| series_id | Ne | measure_type · unit | confidence |
|---|---|---|---|
| `bddk_monthly:1534_Toplam` | Konut kredisi bakiyesi, aylık | stock · TRY_mn | verified |
| `bddk_weekly:5690_3` | Konut kredisi bakiyesi, haftalık | stock · TRY_mn | verified |
| `evds:TP.KTF12` | Konut kredisi faiz oranı (akım) | rate · pct | verified |
| `evds:TP.KFE.TR` | Konut fiyat endeksi | index · index | **derived** |
| `evds:TP.FG.J0` | TÜFE | index · index | **derived** |

Slayt-5 senaryosunun (konut kredisi × faiz × enflasyon × konut fiyatı) tamamı bu beşle karşılanıyor. Sorun değil, iki not:

- KFE ve TÜFE `derived` olduğu için Gold `align_frequency`/`join_on_period` bunları `UNVERIFIED_SEMANTICS` ile reddeder `[SRC]` (`gold-contract.md` §1.2); agent `allow_unverified_semantics=True` ile geçip cevaba **caveat** yazar. Demo için kabul edilebilir; `verified` yapılabilirse (resmî baz yılı kanıtı — `agent-data-p0.md`'de zaten listeli) daha iyi.
- Demoda kullanılacak her seri kadar semantik gerekiyor, fazlası değil. Beş seri doğru başlangıç.

## 2. İstek A — üç BDDK aylık serisi daha (P0, ~1 saat) `[REC]`

Golden set ve benchmark'ımızdaki 18 vakanın 4'ü (G5 karşılaştırma, G6 sütun ekleme, L3-02 alt toplam, L6-04 takipteki) şu kalemleri kullanıyor; bugün yalnız Baran'ın geliştirme seed'inde var, sizin katalogda yok:

| Kavram | BDDK Aylık Bülten | Beklenen |
|---|---|---|
| İhtiyaç kredisi bakiyesi | Tablo 4, "Tüketici Kredileri - İhtiyaç", Toplam, Sektör | stock · TRY_mn · verified |
| Taşıt kredisi bakiyesi | Tablo 4, "Tüketici Kredileri - Taşıt", Toplam, Sektör | stock · TRY_mn · verified |
| Takipteki konut kredileri | Tablo 4, "Takipteki ... Konut" satırı | stock · TRY_mn · verified |

`bddk_monthly.yml`'deki mevcut kayıt şablonu (`1534_Toplam`) birebir kopyalanıp satır kodu değiştirilerek eklenebilir; connector/parser aynı `[INF]`. Alias'lar: "ihtiyaç kredisi, tüketici kredisi ihtiyaç, personal loan" · "taşıt kredisi, araç kredisi, araba kredisi, vehicle loan" · "takipteki konut kredisi, batık konut kredisi, NPL konut".

## 3. İstek B — gerçek veriyle üretilmiş `lakehouse.duckdb` (P0) `[REC]`

Baran'ın `DATA_TEAM_REQUESTS_R2.md` madde 1 ile aynı: `python -m lakehouse bootstrap` + `ingest` ile sıfırdan üretilebilen, 2021-01 → 2026-06 aralığını beş (+ İstek A ile sekiz) seri için içeren veritabanı. Dosya repoya girmesin; **üretim komutları ve süresi** `docs/calisma-notlari/branches/lakehouse-operational-cli.md`'de olsun. Agent tarafında değişecek tek şey `LAKEHOUSE_PATH` `[SRC]` (ADR-0024).

Bugün EVDS için `evds_cpi` dispatch edilebiliyor `[SRC]`; `TP.KTF12` ve `TP.KFE.TR` için de kayıt gerekiyor (`(source_id, dataset_id)` registry'sine iki satır `[INF]`).

## 4. İstek C — `meta.series.concept_id` (P1, şema + 1 alan) `[REC]`

Katalog büyüyünce (il/bölge/banka grubu kırılımları) aynı kavramın onlarca yakın kopyası oluşuyor; ölçtük `[EMP]` (`docs/experiments/E8_10k_design.md` §6–7): düz arama kanonik seriyi kaybediyor, **kavram → kırılım** iki aşamalı arama düzeltiyor. Bunun için kavramı söyleyen bir alan gerek:

```yaml
- series_id: evds:TP.KFE.TR
  concept_id: kfe          # kavram
  entity_label: Türkiye    # kırılım (opsiyonel)
```

Beş seride bugün önemi yok; katalog genişlerken (ek §A) şart olacak. Şimdi eklenirse geriye dönük doldurma derdi kalmaz.

## 5. Bizim tarafta, beklemeden yapılanlar

- Gold fonksiyonları ve ad-hoc yol agent aracı olarak sarılıyor (Baran, `DATA_TEAM_REQUESTS_R2.md`).
- `search_series` iki aşamalı tasarlanıyor; `concept_id` gelene kadar `dataset_id` üzerinden geçici gruplama.
- Sorularınız için: `docs/calisma-notlari/BENCHMARK_PROTOCOL.md`, `docs/calisma-notlari/PROGRESS_2026-09-10.md`.

---

## Ek A — Zümra'nın dalı birleşince geçerli olacak not (`feature/lakehouse-finturk-evds-housing` @ `6e90bd1`)

Bu dal şimdilik agent tarafının referansı değil; birleştiğinde aşağıdaki durum ortaya çıkar `[SRC]`:

| | Sayı |
|---|---|
| EVDS serisi | 1.536 |
| `unit: null` | 1.534 |
| `measure_type: unknown` | 1.534 |
| `semantic_confidence: derived` | 1.536 |
| Alias | yalnız kaynak adı ("TR10 (İstanbul)") |

Sonuç: Gold tasarım gereği bu 1.534 seriye dokunmaz (`UNSUPPORTED_MEASURE_TYPE` / `UNVERIFIED_SEMANTICS`); arama "İstanbul konut fiyat endeksi"ni bulamaz (alias'sız BM25 R@3 0,64 `[EMP]`). Kod hatası değil, üretecin doğru davranışı; eksik olan insan eli. Birleştirme kararı verilirse: demoda kullanılacak ~10 seri (KFE bölgeleri, konut satışları, YKFE) elle doldurulur, kalan 1.500 `draft` kalır; `concept_id` (İstek C) o gün zorunlu olur. Ayrıca FinTürk **çeyreklik** yayınlanıyor ve birim kaynakta yok `[SRC]` — il bazlı konut kredisi sorularında bu iki nüans cevaba yazılmalı.
