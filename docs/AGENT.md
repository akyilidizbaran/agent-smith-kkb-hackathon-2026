# Agentic Analytics Engine — teknik doküman

> Projenin genel tanıtımı için ana [README](../README.md)'ye bakın.

Agent katmanı: doğal dildeki soruyu anlayan, doğru veri kaynağını ve aracı seçen,
analizi çok adımlı yürüten ve sonucu **kanıtıyla** sunan motor.

> Bu dizin projenin **agent** ayağıdır. Data Lakehouse ayrı bir iş kolu olarak
> yürütülmektedir; iki katman [LAKEHOUSE_CONTRACT.md](LAKEHOUSE_CONTRACT.md)
> ile tanımlı sözleşme üzerinden buluşur.

## Mimari

```
Soru (arayüz: kkb_agent.serve  ·  CLI: kkb_agent.cli)
 └─> AnalyticsAgent (harness: planla → araç çağır → gözlemle → onar → guard'lar → kanıt paneli)
      ├─ ToolRegistry ......... profile göre kayıt: Analyst 19 araç, Architect +ingest +terfi = 21
      ├─ AnalysisWorkspace .... aktif tablo + kimlikli oturum tabloları k1…k8, kolon başına provenance
      ├─ EvidencePanel ........ sayılar tabloda mı · sorgu izi · RAW dosya zinciri
      └─ LLMClient ............ OpenAI-uyumlu; MIA/Kloudeks (demo) · Ollama (isteğe bağlı geliştirme)
           └─> LakehouseClient (Protocol) ── SilverLakehouse (lakehouse-core DuckDB) | bellek-içi test adaptörleri
```

Araç aileleri: lakehouse (search, describe, distinct_values, query) · workspace (add_column, compute_column, show, query,
real_value, join) · analitik (anomaly_detect, change_points, lead_lag) · gold (align, decompose, join) · chart ·
web (web_url, web_search) · Architect: ingest_from_url, promote_draft.

**Tasarım ilkesi:** harness güçlü, modelin işi az. Model hesap yapmaz (SQL yapar),
ham veri görmez (şema + örnek satır görür), hatasını sessizce yutmaz (hata metni
geri verilir, düzeltir). Böylece 8B'lik bir modelle çalışan sistem, demo gününde
daha güçlü modelle daha da iyi çalışır.

Tasarım kararlarının gerekçeleri: [`docs/adr/`](adr/)

## Kurulum

Tüm komutlar `agent-core/` dizininden çalıştırılır.

Önerilen yol repo kökündeki `make setup → make preflight → make demo-data → make serve` zinciridir
([OPERASYON_TARIFI.md](OPERASYON_TARIFI.md)). Yalnız ajan paketi için:

```bash
cp ../.env.example ../.env    # değerleri doldurun; .env asla commit edilmez
uv sync --frozen --extra dev  # uv.lock'taki sabit sürümlerle kurar
```

## Kullanım

```bash
uv run python -m kkb_agent.cli --preflight                            # salt-okunur ön kontrol
uv run python -m kkb_agent.cli --trace "2025'te konut kredisi nasıl değişti?"
uv run python -m kkb_agent.cli                                        # etkileşimli
uv run python -m kkb_agent.serve                                      # arayüz http://127.0.0.1:8765
```

## Testler

İki katmanlı doğrulama:

```bash
uv run pytest -q                                    # birim/sözleşme testleri, saniyeler (CI'da da koşar)
uv run python scripts/run_golden.py                 # uçtan uca davranış, dakikalar
uv run python scripts/acceptance_m16.py             # çok turlu kabul: finans, finans dışı, sınır vakaları
uv run --with playwright python scripts/ui_e2e_m16.py   # arayüz uçtan uca (sunucu açıkken)
```

Birim testleri deterministiktir ve bir aracın bozulduğunu golden set'i beklemeden söyler.
Golden set ise gerçek modelle uçtan uca davranışı ölçer; stokastiktir, tek koşuya
bakılarak "düzeldi" denmemelidir.

## Golden set — ilerlemenin objektif ölçüsü

```bash
uv run python scripts/run_golden.py
uv run python scripts/run_golden.py G2 G4      # seçili vakalar
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
| `agent-core/tests/` | Araç birim testleri |
| `agent-core/src/kkb_agent/adapters/` | Lakehouse uygulamaları (şimdilik DuckDB) |
| `agent-core/src/kkb_agent/llm/` | Sağlayıcıdan bağımsız LLM katmanı |
| `agent-core/tests/golden/` | Golden set vakaları |
| `docs/` | Sözleşme dokümanı, açılış toplantısı slaytları (repo kökünde) |

## Kurallar (KKB şartnamesi)

- Hazır/lisanslı bulut Lakehouse (Snowflake, BigQuery vb.) **kullanılmaz**.
- Dış LLM servisi (OpenAI, Anthropic, OpenRouter) **kullanılmaz**; yalnızca Kloudeks.
- API key'leri `.env` dosyasında tutulur, private repoya bile **commit edilmez**.
