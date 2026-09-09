# ADR-0004: Sağlayıcıdan bağımsız LLM katmanı

**Durum:** Kabul edildi · **Tarih:** 2026-09-08

## Bağlam
Geliştirme yerel modelle yapılıyor; demo KKB'nin Kloudeks platformunda olacak.
Şartname dış LLM servislerini (OpenAI, Anthropic, OpenRouter) yasaklıyor.

## Karar
`LLMClient` protokolü tanımlandı; tek uygulama `OpenAICompatClient` hem Ollama'ya
hem Kloudeks'e bağlanıyor. Sağlayıcı değişimi yalnızca `.env` değişikliğidir:
`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.

## Gerekçe
- Kloudeks OpenAI-uyumlu format sunuyor (toplantıda belirtildi), dolayısıyla tek
  istemci yeterli.
- Agent kodunun hiçbir yerinde sağlayıcı adı geçmemeli; aksi halde geçiş
  sırasında kod değişikliği gerekir ve demo öncesi risk doğar.
- Geliştirmeyi kasıtlı olarak zayıf modelle yapıyoruz: *"zayıf modelde çalışan
  sistem güçlü modelde daha da iyi çalışır."*

## Ölçüm — MIA/Kloudeks, 2026-09-10
İki bilinmeyen de kapandı, kod değişikliği olmadan:
- `reasoning_effort=none`: **çalışıyor** (51 token/1,0 s → 4 token/0,1 s)
- Native tool-calling: **çalışıyor** (`topla(a=7,b=5)` doğru döndü)
- Embedding: 4096 boyut, 0,2 s. Rate-limit header'ı yok; kota mentörde.

Tek uyumsuzluk: vLLM ikinci bir `system` mesajını reddediyor
("System message must be at the beginning"). Workspace durumu artık ilk
system mesajının içine ekleniyor; Ollama tolere ettiği için fark edilmemişti.

Golden set MIA'da: **7/7, her vaka 3/3 kararlı, 4–12 s** (yerelde 12 dakika,
%100 → aynı kodla 30 saniye). Sağlayıcı soyutlaması amacına ulaştı.
