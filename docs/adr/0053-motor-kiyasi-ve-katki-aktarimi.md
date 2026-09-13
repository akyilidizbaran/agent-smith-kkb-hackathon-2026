# ADR-0053: Motor kıyası (13 Eylül) ve V3 katkılarının aktarımı

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Milestone:** M02 · **Karar (K01, kullanıcı):** baseline `feature/agent-engine`

## Bağlam
11 Eylül kıyası (`docs/MOTOR_KARSILASTIRMA_YANIT.md`) eski agent commit'ine aitti; bugünkü motor OCR,
web, analitik, retrieval kademesi, araç kapısı ve kanıt paneli taşıyor. Kullanıcı baseline'ı seçti;
M02'nin sorusu artık "hangi motor" değil, "V3'ten ne aktarılır ve bugünkü fark nedir".

## Yöntem (M02-T01…T06)
- **Koşucu:** Büşra'nın `run_benchmark.py` ve 18 vakası olduğu gibi (`scripts/m02_benchmark/`,
  kaynak `feature/busra/agent-v3@479854c`, yazarlık korunur). V3 motoru worktree'den (`V3_SRC`),
  ortak `kkb_agent` paketi bu repodan (V3 bunu sarar; 106 V3 testi bu ortamda geçmişti).
- **Aynı veri:** `data/lakehouse.duckdb` (M01 canlı kurulum: 127 seri, 8.290 gözlem, 6 Gold).
  **Aynı model:** MIA `Qwen3.8-27B`, `LLM_DISABLE_THINKING=true`, anlatı sıcaklığı 0 (golden kuralı).
- **Set:** 7 golden + 11 alt-küme (Büşra) + 5 görülmemiş (U1–U5, koşudan önce yazıldı, durum
  üzerinden kontrol; U3 `lead_lag` ister → V3'te yetenek yok, bu dürüstçe "çağrılmadı" olarak sayılır).
- **Tekrar:** 3 (pass^3), sıralı koşu (motorlar arka arkaya). Yakın sonuç eşitlik kanıtı değildir;
  "belirgin üstünlük gösterilemedi" diye yazılır.
- **Ölçülenler:** pass^3, süre ort/p50, LLM turu, araç adımı, araç hatası ve kodları, grounding.

## Sonuç (koşu 13 Eylül gece, 138 koşu, 730 s + 590 s)
| | ekip (`feature/agent-engine`) | V3 |
|---|---|---|
| pass^3 ham | 16/23 | 17/23 |
| bayat kontroller düzeltilince (içerik) | 20/23 | 18/23 |
| ort. süre / p50 | 8,6 s / 6,5 s | 10,5 s / 10,0 s |
| LLM turu / araç adımı | 3,4 / 2,4 | 4,9 / 3,4 |
| araç hatası | 23 | 82 (65 TOOL_FAILED: ilk sorgu eski tablo adıyla) |
| grounding temiz | 54/57 | 51/57 |

Ortak düşen: G3 (12 satır kontrolü), L10-01 (netleştirme yok). Ekipte gerçek açık: L3-02 alt kalem
toplamı (arama "dövize endeksli"yi bulamayınca vazgeçti). V3'te yetenek yok: U3 (`lead_lag`).
Ayrıntı ve okuma: `docs/experiments/benchmark_m02_2026-09-13.md`. Karar: K01 değişmez; belirgin
üstünlük iddiası yok. Açılan işler: L3-02 → M08/M11, L10-01 → M11-T07, bayat SQL kontrolleri →
M16 kabul seti yeniden yazılırken durum kontrolüne çevrilir.

## Aktarım listesi (M02-T07, öneri)
| V3 parçası | Durum |
|---|---|
| Ön-yükleme (katalog kartları prompt'ta) | Alındı (ADR-0035) |
| Grounding guard | Alındı, ortak modül (`core/grounding.py`, yazar Büşra) |
| Benchmark koşucusu + 18 vaka | Alındı (`scripts/m02_benchmark/`, bu ADR) |
| `max_tokens=700` üretim tavanı | Değerlendirilecek (M15-T03): bugünkü motor tavan göndermiyor |
| Alan notları (`domain/*.md`, `lookup_domain_note`) | Değerlendirilecek: profil katalogdan türetiliyor (ADR-0012); notlar Gold/semantik açıklamaları için aday |
| Salt-okunur araçlarda paralellik | Ertelendi (M02-T08): tek workspace, DuckDB bağlantı sınırı |
