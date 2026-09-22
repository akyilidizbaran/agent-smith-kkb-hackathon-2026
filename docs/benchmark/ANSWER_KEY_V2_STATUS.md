# V2.1 Cevap ve Oracle Durumu

Bu dosya `TEST_PROMPTLARI_V2.md` ve `CONTRACT_V2_1.md` için oracle üretim durumunu, çalıştırma yüzeylerini ve harici girdi gereksinimlerini takip eder.

## Kanonik kaynaklar

- Prompt aynası: [`TEST_PROMPTLARI_V2.md`](TEST_PROMPTLARI_V2.md)
- Normatif sözleşme: [`CONTRACT_V2_1.md`](CONTRACT_V2_1.md)
- Makine manifesti: [`../../tests/benchmark/prompts_v2.jsonl`](../../tests/benchmark/prompts_v2.jsonl)
- Lakehouse referans verisi: `data/lakehouse.duckdb`

## Üretim kuralı

Referans cevap, LLM'in tek bir anlatı cümlesi değildir. Her vaka için kaynak veriden doğrulanmış tablo/artifact, beklenen dönem ve kolon sözleşmesi, provenance durumu, beklenen araç sınıfları ve kısa grounded özet üretilir. Harici URL ve dosyalar snapshot alınmadan sayı yazılmaz.

## Mevcut durum

- Toplam V2 vakası: **120**
- Açık fixture/snapshot placeholder'ı gerektiren vaka: **38**
- Prompt içinde placeholder bulunmayan vaka: **82** (76 yerel/politika + 6 canlı web)
- Canlı web snapshot'ı gerektiren vaka: **6**
- Gerçek fixture veya canlı web snapshot'ı olmadan doğrudan çalıştırılabilecek yerel/politika vaka: **76**
- Eski iki demo sorusu: bu cevap anahtarında yok; ayrı regresyon kontrolü.

Bağımsız yerel cevap paketi [`ANSWER_KEY_V2_LOCAL.md`](ANSWER_KEY_V2_LOCAL.md) ve makine çıktısı [`answers_v2_local.jsonl`](answers_v2_local.jsonl) içindedir. **31** bağımsız sayısal artifact (28 DuckDB snapshot’ı + 3 prompt içi fixture) ve ölçüm/kapsamı belirsiz vakalar için netleştirme/politika sözleşmeleri [`reference/INDEX.md`](reference/INDEX.md) altında bulunur. V2'nin 120 vaka durum manifesti [`tests/benchmark/reference_status_v2.jsonl`](../../tests/benchmark/reference_status_v2.jsonl) dosyasındadır.

Durum manifestinde yerel vakalar: `reference_artifact_ready` (31), `reference_contract_ready` (26), `policy_reference` (14) ve `integration_contract_ready` (5). Bu beş vaka CLI’da puanlanmaz; performans, concurrency, arıza enjeksiyonu ve UI/artifact dışa aktarma yüzeylerinde sınanır.

Harici girdilerin güncel ID/placeholder listesi [`EXTERNAL_INPUTS_PENDING_V2.md`](EXTERNAL_INPUTS_PENDING_V2.md) dosyasındadır.

## Bekleyen girdiler

`prompts_v2.jsonl` içindeki `placeholders` alanları için fixture veya snapshot sağlanmalıdır. Bunlar sağlanmadan E/U/D/C/W/I/S ailelerinin ilgili vakalarında gerçek sayısal cevap üretmek yerine yalnız sözleşme düzeyinde beklenen davranış yazılabilir.

## Cevap üretim sırası

1. Placeholder içermeyen vaka ve güvenlik vakaları mevcut lakehouse üzerinde deterministik koşulur.
2. CSV/XLSX/HTML/PDF/iklim ve revision fixture'ları hash'leriyle birlikte eklenir.
3. URL vakaları erişim zamanı, son URL, durum kodu ve response SHA-256 ile snapshot'lanır.
4. Aynı vaka için tablo, CSV, XLSX ve kanıt zinciri parity'si doğrulanır.
5. Sonuçlar `answers_v2.jsonl` ve okunabilir HTML/Markdown raporuna yazılır.
