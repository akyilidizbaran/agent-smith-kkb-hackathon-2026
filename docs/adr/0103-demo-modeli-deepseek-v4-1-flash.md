# ADR-0103: Demo metin modeli Kloudeks'teki DeepSeek-V4.1-Flash

**Durum:** Kabul edildi · **Tarih:** 2026-09-23

## Bağlam
Repo varsayılanı (`.env.example`) Kloudeks'teki `kkbhackathon2026/Qwen3.8-27B` idi. 22 Eylül'de aynı MIA/Kloudeks anahtarıyla
`/v1/models` listesinde `deepseek-ai/DeepSeek-V4.1-Flash` görüldü (PROJECT_MEMORY 2.130):
- düz sohbet denemesi HTTP 200 döndü;
- yerel araç çağırma (native function-tool) denemesi `tool_calls` üretti.

O günden beri ekip demoyu yerel `.env`'de bu modelle koşturuyor (2.131–2.140).

Kullanıcı 23 Eylül'de repo varsayılanının da bu model olmasına karar verdi.

## Karar
- `.env.example`: `LLM_MODEL=deepseek-ai/DeepSeek-V4.1-Flash`. Adres (`https://mia.csp.kloudeks.com/v1`), anahtar (`MIA_API_KEY`),
  `LLM_DISABLE_THINKING=true` ve süre ayarları değişmedi.
- Embedding (`Qwen3-Embedding-8B`) ve OCR (`Unlimited-OCR`) modelleri aynı kaldı; yalnız metin ve araç çağırma modeli değişti.
- Kodda modele bağlı bir yol yok: `OpenAICompatClient` aynı OpenAI uyumlu protokolü konuşur, model adı yalnız `.env`'den gelir.
  `config.py`'deki `.env` yokken kullanılan yerel geliştirme varsayılanı (Ollama `qwen3:8b`) değişmedi.
- README ve `docs/ARCHITECTURE.md` bu varsayılana göre güncellendi. Geçmiş ölçüm raporları ve eski ADR'lerdeki Qwen3.8-27B
  kayıtları o günün ölçümü olduğu için değiştirilmedi.

## Kırmızı çizgi
Model yine KKB'nin Kloudeks platformundan, aynı hackathon anahtarıyla çağrılır. Dış bir LLM servisi (OpenAI, Anthropic,
OpenRouter, DeepSeek'in kendi API'si) kullanılmaz.

## Sonuçlar
- Qwen3.8-27B ile alınmış kabul ve benchmark sayıları DeepSeek için geçerli sayılmaz. Demo öncesi kabul koşuları bu modelle
  yeniden alınmalıdır.
- Geri dönüş tek satırdır: `.env`'de `LLM_MODEL=kkbhackathon2026/Qwen3.8-27B`, sonra sunucu yeniden başlatılır.
