# Agentic Analytics Engine — teknik doküman

> Projenin genel tanıtımı için ana [README](../README.md)'ye bakın.

Agent katmanı: doğal dildeki soruyu anlayan, doğru veri kaynağını ve aracı seçen,
analizi çok adımlı yürüten ve sonucu **kanıtıyla** sunan motor.

> Bu dizin projenin **agent** ayağıdır. Data Lakehouse ayrı bir iş kolu olarak
> yürütülmektedir; iki katman [LAKEHOUSE_CONTRACT.md](LAKEHOUSE_CONTRACT.md)
> ile tanımlı sözleşme üzerinden buluşur.

## Mimari

```
Soru
 └─> AnalyticsAgent (harness: planla → araç çağır → gözlemle → onar)
      ├─ ToolRegistry ......... araçlar burada kayıtlı; yeni yetenek = yeni sınıf
      ├─ AnalysisWorkspace .... konuşma boyunca yaşayan analiz tablosu
      └─ LLMClient ............ OpenAI-uyumlu; Ollama (geliştirme) / Kloudeks (demo)
           └─> LakehouseClient (Protocol) ── DuckDBLakehouse | <veri ekibinin adaptörü>
```

**Tasarım ilkesi:** harness güçlü, modelin işi az. Model hesap yapmaz (SQL yapar),
ham veri görmez (şema + örnek satır görür), hatasını sessizce yutmaz (hata metni
geri verilir, düzeltir). Böylece 8B'lik bir modelle çalışan sistem, demo gününde
daha güçlü modelle daha da iyi çalışır.

## Kurulum

Tüm komutlar `agent-core/` dizininden çalıştırılır.

```bash
cp ../.env.example ../.env    # değerleri doldurun; .env asla commit edilmez
ollama pull qwen3:8b          # geliştirme modeli

uv venv && uv pip install duckdb httpx pandas pydantic openai python-dotenv
python scripts/dev_seed.py    # gerçek BDDK verisiyle geliştirme lakehouse'u
```

## Kullanım

```bash
PYTHONPATH=src python -m kkb_agent.cli --health
PYTHONPATH=src python -m kkb_agent.cli --trace "2025'te konut kredisi nasıl değişti?"
PYTHONPATH=src python -m kkb_agent.cli          # etkileşimli
```

## Golden set — ilerlemenin objektif ölçüsü

```bash
PYTHONPATH=src python scripts/run_golden.py
PYTHONPATH=src python scripts/run_golden.py G2 G4      # seçili vakalar
```

Vakalar serbest metni değil, agent'ın ürettiği **analiz tablosunu** denetler
(satır sayısı, kolonlar, BDDK'dan doğrulanmış gerçek değerler). Her değişiklikten
sonra koşulmalıdır — "iyileştirdim" iddiasının tek objektif kanıtı budur.

## Kloudeks'e geçiş

Kod değişmez, yalnızca `.env`:

```
LLM_BASE_URL=https://<kloudeks-endpoint>/v1
LLM_API_KEY=<takıma özel key — repoya asla yazılmaz>
LLM_MODEL=<model adı>
```

## Dizin düzeni

| Yol | İçerik |
|---|---|
| `agent-core/src/kkb_agent/contracts/` | Veri katmanıyla sözleşme (Protocol + semantic catalog) |
| `agent-core/src/kkb_agent/core/` | Harness, workspace, araç soyutlaması, kayıt defteri |
| `agent-core/src/kkb_agent/tools/` | Araçlar — her yetenek bağımsız bir modül |
| `agent-core/src/kkb_agent/adapters/` | Lakehouse uygulamaları (şimdilik DuckDB) |
| `agent-core/src/kkb_agent/llm/` | Sağlayıcıdan bağımsız LLM katmanı |
| `agent-core/tests/golden/` | Golden set vakaları |
| `docs/` | Sözleşme dokümanı, açılış toplantısı slaytları (repo kökünde) |

## Kurallar (KKB şartnamesi)

- Hazır/lisanslı bulut Lakehouse (Snowflake, BigQuery vb.) **kullanılmaz**.
- Dış LLM servisi (OpenAI, Anthropic, OpenRouter) **kullanılmaz**; yalnızca Kloudeks.
- API key'leri `.env` dosyasında tutulur, private repoya bile **commit edilmez**.
