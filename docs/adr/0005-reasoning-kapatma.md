# ADR-0005: Reasoning zincirinin kapatılması

**Durum:** Kabul edildi · **Tarih:** 2026-09-08

## Bağlam
İlk uçtan uca koşuda adım başına 26–60 saniye harcanıyordu; tek bir soru ~3
dakika sürüyordu. Demo için kabul edilemez.

## Karar
İstemci varsayılan olarak `reasoning_effort: "none"` gönderiyor
(`LLM_DISABLE_THINKING` ile kapatılabilir).

## Ölçüm
qwen3:8b, Apple M5. "Sadece 'merhaba' yaz" istemi:

| Ayar | Süre | Üretilen token |
|---|---|---|
| Varsayılan | 12,7 s | 162 |
| `chat_template_kwargs.enable_thinking=false` | 12,3 s | 162 (etkisiz) |
| Prompt'a `/no_think` | 13,3 s | 157 (etkisiz) |
| **`reasoning_effort: "none"`** | **0,5 s** | **4** |

Uçtan uca etki: tek değerli bir soru ~180 s → **26 s**.

## Gerekçe
Araç seçimi gibi kısa kararlarda düşünce zinciri gecikmeden başka bir şey
üretmiyordu. `reasoning_effort` OpenAI-standart bir alan olduğu için Kloudeks'te
de geçerli olması bekleniyor; tanımayan sunucu alanı sessizce yok sayar.

## Riskler
Karmaşık SQL üretiminde düşünce zincirinin faydası olabilir. Kapatmanın kalite
maliyeti ölçülmedi; golden set'te bir gerileme görülürse `.env` üzerinden
açılabilir.
