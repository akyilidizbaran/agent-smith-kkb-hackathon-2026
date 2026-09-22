# ADR-0094 — Model ve araç gecikmesinin ayrı ölçülmesi

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-20
- **İlgili çalışma:** MIA benchmark timeout ve fallback analizi

## Bağlam

Toplam adım süresi LLM sağlayıcı beklemesini ve yerel araç çalışmasını birbirine karıştırıyordu. Bu nedenle yavaş bir araç ile yavaş bir model çağrısını benchmark izinden ayırmak mümkün değildi. Anlatım çağrısı kesilince doğrulanmış tabloyu başarısız istek gibi göstermek de gereksiz tekrar ve uzun bekleme yaratıyordu.

## Karar

1. Her agent adımı end-to-end `duration_ms` değerini korur; ayrıca `llm_duration_ms` ve `tool_duration_ms` üretir.
2. Model çağrı süresi, başarısız çağrılar dahil, kullanım toplamında `llm_call_ms` olarak tutulur. Bir model yanıtındaki çoklu araç çağrılarında model süresi bir kez sayılır; araç süreleri ayrı ölçülür.
3. Anlatım sağlayıcısı kesilse bile doğrulanmış tablo/araç çıktısı korunur. İstenen analitik yetenek tamamlanmadıysa cevap bunu açıkça belirtir; sayı veya analiz uydurulmaz.
4. Anlatım promptu bu kararla değiştirilmez; token/prompt optimizasyonu ayrı çalışma olarak kalır.

## Sonuçlar

- Benchmark latency analizinde model sağlayıcısı ve harness/araç gecikmeleri ayrıştırılabilir.
- Anlatım kesintisi tamamlanmış veri alımını geri almaz; kullanıcıya tablo dışı yorumun üretilmediği açık kalır.

## Doğrulama

- Agent adım metrikleri, başarısız model çağrısı süreleri ve anlatım kesintisinde tablo/provenance korunumu testleri.
- Tam agent-core test paketi ve benchmark sözleşmesi doğrulayıcısı.

