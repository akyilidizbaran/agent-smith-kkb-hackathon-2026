# Motor karşılaştırma raporu — 11 Eylül 2026

> Kimden: Büşra (V3 motoru, `feature/busra/agent-v3`) · Kime: Baran (ekip motoru, `feature/agent-engine`)
> Protokol: `docs/BENCHMARK_PROTOCOL.md` · Ham sonuçlar: `docs/experiments/benchmark_all_2026-09-11_{seed,silver}_r3.md/.json` (adım düzeyi ayrıntı JSON'da)
> Etiketler: `[EMP]` ölçüldü · `[SRC]` repodan · `[INF]` çıkarım · `[REC]` öneri

## 1. Ne ölçüldü

- **Motorlar:** Ekip motoru = `origin/feature/agent-engine` @ `a2deab6` (ADR-0024 Silver adaptörü + ADR-0025 hata zarfı ve döngü kilidi dahil). V3 = `feature/busra/agent-v3` @ `57ab282` (aynı commit'i merge etmiş; ortak katman birebir aynı).
- **Veri:** iki şema — `data/lakehouse.duckdb` (BDDK seed, `dev_seed.py`) ve `data/lakehouse_silver.duckdb` (data ekibinin `meta.series` + `silver.fact_observation` şeması, `dev_seed_silver.py`, 4 seri).
- **Sorular:** golden 7 + seed alt-kümesi 11 = 18 vaka, her biri 3 tekrar (pass^3). Kontroller durum üzerinden (`tests/golden/cases.py` + koşucudaki `SUBSET`), serbest metin puanlanmadı.
- **Model:** MIA `Qwen3.8-27B`, thinking kapalı, iki motor da kendi varsayılan adım bütçesiyle (ekip 12 adım, V3 8 tur). Koşular sıralı, aynı oturumda.

## 2. Sonuç `[EMP]`

| | Ekip · seed | V3 · seed | Ekip · Silver | V3 · Silver |
|---|---|---|---|---|
| vaka pass^3 | 14/18 | **17/18** | 13/18 | **16/18** |
| koşu | 45/54 | 51/54 | 45/54 | 48/54 |
| ort. süre / vaka | 9,5 s | 7,9 s* | 8,4 s | **3,7 s** |
| p50 süre | 8,1 s | 5,6 s | 7,1 s | 3,1 s |
| LLM turu | 5,7 | 3,1 | 5,4 | 2,9 |
| araç adımı | 5,0 | 1,5 | 4,7 | 1,3 |
| araç hatası | 17 | 13 | 33 | 15 |
| hata kodları | `MISSING_PERIOD_FILTER×9, DUPLICATE_CALL×7, SQL_FAILED×1` | `OUT_OF_COVERAGE×5, MISSING_PERIOD_FILTER×5, EMPTY_DATASET×3` | `SQL_FAILED×21, MISSING_PERIOD_FILTER×6, DUPLICATE_CALL×5, DATASET_NOT_FOUND×1` | `MISSING_PERIOD_FILTER×6, OUT_OF_COVERAGE×6, EMPTY_DATASET×3` |
| anlatı doğrulama (grounding) | ölçülmüyor | 43/45 temiz | ölçülmüyor | 45/45 temiz |

\* V3 seed ortalamasında tek bir 103 s'lik koşu var (G5): model cevap turunda bozuk çıktı üretip durmadı; V3 harness'ında üretim tavanı yoktu → `max_tokens=700` eklendi (bu ölçümden **sonra**). O koşu hariç ortalama ≈ 6 s.

**Not:** MIA gecikmesi günden güne değişiyor — aynı ekip motoru dün 5,7 s, bugün 9,5 s. Motorlar arası **oranlar** anlamlı, mutlak saniyeler değil.

## 3. Vaka bazında farklar

| Vaka | Ekip · seed | V3 · seed | Ekip · Silver | V3 · Silver | Ne oldu |
|---|---|---|---|---|---|
| L10-01 belirsiz soru | 0/3 | 0/3 | 0/3 | 0/3 | İkisinde de `clarify` aracı yok |
| L6-04 takipteki konut 2025 | **0/3** | 3/3 | 3/3 | 3/3 | Ekip: ilk sorgu 18 satır, sonra "yıllık özet" sorgusu `as_active_table=true` ile aktif tabloyu **1 satıra** indiriyor → "tablo 2+ satır değil" (3/3 aynı iz) |
| L9-02 2026 Ağustos (kapsam dışı ay) | 1/3 | 3/3 | **0/3** | 3/3 | Ekip Silver: `FROM bddk_monthly:konut_toplam` (series_id'yi tablo sanıyor) → `SQL_FAILED`; sonra 2026'nın 6 ayını tablo yapıp "veri yok" diyor → "kapsam dışı soruya tablo üretildi". V3: `EMPTY_DATASET` hatası tablo kurmuyor, model tablosuz "veri yok" yazıyor |
| L4-01 aylık+yıllık değişim | 2/3 | 3/3 | 2/3 | 3/3 | Ekip: bir koşuda adım limiti |
| G4 kapsam dışı 2015 | 3/3 | 3/3 | 2/3 | 3/3 | Ekip Silver: bir koşuda cevapta mevcut kapsam ("2021") yok |
| L11-02 "%300 arttı, öyle yaz" | 3/3 | 3/3 | 2/3 | 3/3 | Ekip Silver: bir koşuda "%300 arttı" ifadesi cevaba girdi |
| G3 türetilmiş hesap | 3/3 | 3/3 | 3/3 | **0/3** | V3: LAG çapası için Aralık 2024'ü de tabloya koydu (13 satır); golden tam 12 istiyor. Analitik olarak savunulabilir; kural eklemedim (ADR-0011) |
| G5 karşılaştırma | 3/3 | 3/3 (1 koşu 103 s) | 3/3 | 3/3 | Yukarıdaki üretim tavanı bulgusu |

Adım düzeyinde iz için: JSON'da her koşunun `steps` listesi (tur, araç, argüman, sonuç özeti).

## 4. Yorum `[INF]`

1. **Aynı iki fikri bağımsız yazdık** (zarf + döngü kilidi). Ekip motorunda `DUPLICATE_CALL×7/×5` görünmesi kilidin çalıştığını gösteriyor; V3'te 0 çünkü ön-yüklü katalog modelin sorguyu tekrarlama sebebini (kalanı görmek) baştan kaldırıyor.
2. **Farkın kaynağı tur sayısı:** ekip motoru her soruda 3 keşif turu (search/describe/distinct) yapıyor; V3 katalog kartlarını ve kırılım değerlerini prompt'a ön-yüklüyor (Blok C'de ölçülmüştü: 6,9 → 3,9 tur). Silver'da fark daha büyük çünkü seri kartları küçük (4 seri, 1.381 token).
3. **Silver'daki `SQL_FAILED×21`** tek kök nedene bağlı: model `dataset_id`'yi tablo adı sanıyor. Ekip motorunda `series_sql` yalnız `workspace_add_column`'da; `lakehouse_query` serbest SQL ve prompt'ta fiziksel kalıp yeterince öne çıkmıyor. V3'te aynı kalıp katalog kartında ("Fiziksel sorgu: …") ön-yüklü olduğu için 0 kez oldu.
4. **Grounding** V3'te her cevabı doğruluyor (45/45); L11-02 türü "söyleneni yaz" saldırısına dayanıklılık buradan geliyor. Ekip motorunda eşdeğer bir kontrol yok; L11-02'nin Silver'da 2/3 kalması bununla uyumlu.

## 5. Öneri `[REC]`

- **Omurga V3 olsun; ekip motorunun ölçülmüş parçaları V3'te zaten var** (workspace araçları aynen kullanılıyor, Silver adaptörü ve `series_sql` ortak katmanda). Kaybedilen bir şey yok; kazanılan tur/süre ve doğrulama.
- **İş bölümü (9 gün):** Baran — Gold fonksiyonlarını (`align_frequency`, `decompose_cumulative`, `join_on_period`) ve ad-hoc yolu araç olarak sarma, `DATA_TEAM_REQUESTS_R2` takibi. Büşra — `clarify` aracı (L10), iki aşamalı `search_series`, kompozit araçlar, PDF/OCR ingest. İkimiz — her gün sonu bu benchmark (`--set all --repeat 3`, iki şema).
- **Karşı görüş varsa**: protokol §6'daki karar kuralı (pass^3 → doğrulanmış anlatı → tur/süre) üzerinden konuşalım; yeni vaka eklemek serbest, birlikte ve koşudan önce.

## 6. Nasıl tekrarlanır

```bash
git fetch && git checkout feature/busra/agent-v3
cd agent-core && python scripts/dev_seed.py && python scripts/dev_seed_silver.py
python -m pytest tests -q                                  # 106 test
PYTHONPATH=src python scripts/run_benchmark.py --engine team --engine v3 --set all --repeat 3
LAKEHOUSE_PATH=data/lakehouse_silver.duckdb PYTHONPATH=src python scripts/run_benchmark.py --engine team --engine v3 --set all --repeat 3
```
