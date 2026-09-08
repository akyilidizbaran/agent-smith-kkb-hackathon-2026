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

## Açık riskler
Demo öncesi ölçülmesi gereken iki bilinmeyen:
1. `reasoning_effort` Kloudeks'te destekleniyor mu (bkz. ADR-0005)?
2. Native tool-calling var mı? Yoksa harness'ın JSON fallback modu devreye
   girmeli — kod yazılı ama gerçek koşulda hiç denenmedi.
