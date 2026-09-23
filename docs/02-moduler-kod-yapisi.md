# 2. Modüler kod yapısı

Repo iki bağımsız Python paketinden oluşur. Her birinin kendi `pyproject.toml` ve `uv.lock` dosyası, kendi testleri ve CI
iş akışı vardır.

```text
KKB/
├── agent-core/              Agentic analitik motoru (paket: kkb_agent, Python ≥ 3.11)
│   ├── src/kkb_agent/       motor, araçlar, arayüz
│   ├── tests/               1168 test (pytest)
│   └── scripts/             kabul ve benchmark betikleri
├── lakehouse-core/          Data Lakehouse (paket: lakehouse, Python 3.12)
│   ├── src/lakehouse/       bağlayıcı, ayrıştırıcı, depolama, katalog, Silver, Gold
│   ├── catalog/             seri kataloğu (YAML) ve Gold metrikleri
│   ├── scripts/             toplu çekim, katalog üreticileri, kalite kapıları
│   └── tests/               birim, sözleşme, güvenlik, entegrasyon testleri
├── docs/                    bu belgeler, ADR'ler (docs/adr), çalışma notları (docs/calisma-notlari)
├── data/                    (git dışı) RAW, Bronze, lakehouse.duckdb, yüklemeler, sohbetler
└── Makefile                 kurulum, veri, sunucu ve test hedefleri
```

Bağımlılık tek yönlüdür: `agent-core` → (SQL ve komut satırı) → `lakehouse-core`. Ajan `lakehouse` paketini import
etmez.

## 2.1 `agent-core/src/kkb_agent`

| Modül | Sorumluluk | Başlıca adlar |
|---|---|---|
| `core/agent.py` | Orkestrasyon döngüsü: araç turu, fazlar, istenen yetenekler, kurtarma, cevap doğrulama | `AnalyticsAgent`, `AgentStep`, `AgentAnswer` |
| `core/turn_intent.py` | Tur niyeti tek yerde (grafik, analitik, dönüşüm, birleştirme, yorum…) | `classify`, `TurnIntent` |
| `core/tool_gate.py` | Soruya göre modele sunulan araç aileleri (yetki değil, şema daraltma) | `decide`, `ALWAYS`, `WEB`, `ARCHITECT` |
| `core/validator.py`, `core/errors.py` | Her çağrı tek hattan geçer: şema → SQL guard → referans → politika → çalıştır; yapılandırılmış hata zarfı | `BoundaryValidator`, `ToolError` |
| `core/registry.py`, `core/tool.py` | Araç kaydı ve araç sözleşmesi | `ToolRegistry`, `Tool`, `ToolResult` |
| `core/retriever.py`, `core/lexical.py`, `core/context.py` | Katalog araması (küçük katalog: tümü; orta: BM25; büyük: BM25 + embedding, RRF) ve bütçeli ön-yükleme | `CatalogRetriever`, `Bm25Index`, `build_question_context` |
| `core/workspace.py` | Konuşma boyunca yaşayan analiz tablosu, kaynak tabloları (k1…kN), kolon bazında provenance, geri alma | `AnalysisWorkspace` |
| `core/grounding.py`, `core/claim_check.py`, `core/completion.py` | Cevap doğrulama: sayı araç çıktısında mı, dönem doğru mu, istenen kapsam geldi mi | `grounding_check`, `claim_cell`, `check_completion` |
| `core/evidence.py` | Kanıt zinciri: sayı → hücre → SQL → gözlem → artifact → RAW/URL | `EvidenceBuilder` |
| `core/access_policy.py`, `core/intent.py`, `core/approvals.py` | Erişim sonucu (ok/needs_credential/blocked/not_found), yazma niyeti kapısı, işlem başına onay | `classify_access`, `write_intent`, `ApprovalBook` |
| `core/fitness.py` | Tablo soruya uygun mu (ölçüm, varlık, dönem, granülarite, birim) | `assess`, `DataSignature` |
| `tools/` | Araç uygulamaları (aşağıdaki tablo) | — |
| `builder/` | Dosya okuma ve Architect kayıt hattı (LLM yok) | `read.py`, `tabular.py`, `temporal.py`, `profile.py`, `verify.py`, `ingest.py` |
| `web/` | Bütçeli, robots'a saygılı web erişimi; isteğe bağlı gerçek tarayıcı katmanı | `fetch.py`, `crawl.py`, `html.py`, `search.py`, `browser.py` |
| `vision/` | PDF metin katmanı (pdfplumber) ve OCR | `extract_pdf_tables`, `ocr_document` |
| `analytics/` | Deterministik analitik (aykırı değer, kırılma noktası, öncül-ardıl) | `detect_anomalies`, `ChangePointResult` |
| `charts/` | Vega-Lite grafik: kurallar, lint, PNG | `lint_spec`, `render_chart` |
| `adapters/` | Lakehouse adaptörleri ve embedding istemcisi | `SilverLakehouse`, `GoldCLI`, `MiaEmbedder` |
| `llm/` | Sağlayıcıdan bağımsız LLM arayüzü ve OpenAI uyumlu tek istemci | `LLMClient`, `OpenAICompatClient` |
| `contracts/` | Katmanlar arası sözleşmeler (aşağıda) | `LakehouseClient`, `DatasetSpec`, `AccessOutcome` |
| `config_data/` | Kodun dışında tutulan alan bilgisi: kaynak ipuçları, kavram sözlüğü | `source_hints.json`, `concepts.json` |
| `domain.py` | Alan profili katalogdan türetilir; prompt ve şema yer tutucularını doldurur | `DomainProfile` |
| `cli.py` | Bileşim kökü: ajanı ve araçları kurar; komut satırı (`--preflight`, `--trace`, `--evidence`) | `build_agent` |
| `web_app.py`, `serve.py`, `live_steps.py`, `conversations.py` | Arayüz (FastAPI), canlı adım akışı, sohbet kaydı | `create_app`, `Session`, `live_hooks`, `ConversationStore` |
| `static/index.html` | Tek sayfalık arayüz (dış kütüphane yok, çevrimdışı çalışır) | — |

> `agent-core/src/kkb_agent_v3` ayrı bir deney motorudur; yalnız kıyas betiklerinde kullanılır, çalışan uygulama onu
> import etmez.

### Araçlar

| Aile | Araç | Ne yapar |
|---|---|---|
| Lakehouse | `lakehouse_search`, `lakehouse_describe`, `lakehouse_distinct_values`, `lakehouse_query` | Katalog araması, seri kartı, kırılım değerleri, salt-okunur SQL |
| | `lakehouse_breakdown_panel` | Serileri ve vade gruplarını tek aylık eksende deterministik kurar; aylık hareket, reel değer, taban ayı endeksi (ADR-0108, ADR-0110) |
| Çalışma tablosu | `workspace_add_column`, `workspace_compute_column`, `workspace_show`, `workspace_query`, `workspace_real_value`, `workspace_join` | Tabloyu bozmadan kolon ekleme/hesaplama, reel değer, ay anahtarıyla birleştirme |
| Gold | `gold_align`, `gold_decompose`, `gold_join` | Frekans hizalama, kümülatiften akım, dönem üzerinden birleştirme |
| Analitik | `anomaly_detect`, `change_points`, `lead_lag` | Aykırı ay, rejim/kırılma noktası, öncül-ardıl ilişkisi |
| Öncül / netleştirme | `check_premise`, `clarify` | Sorudaki varsayımı veriyle sınama; tek kısa netleştirme sorusu |
| Grafik | `chart` | Vega-Lite grafik ve PNG |
| Web | `web_url`, `web_search` | Adres/dosya okuma; arama (anahtar varsa) |
| Kayıt (Architect) | `ingest_from_url`, `ingest_source`, `promote_draft` | Dosyayı taslak seri olarak kaydetme; kayıtlı kaynaktan eksik dönem; onaylı kataloğa alma |

Toplam 25 araç. Analyst profilinde kayıt araçları kayıt defterine hiç eklenmez; model adıyla çağırsa `UNKNOWN_TOOL`
alır.

## 2.2 Değiştirilebilir parçaları mümkün kılan sözleşmeler

| Sözleşme | Dosya | Uygulayan | Ne sağlar |
|---|---|---|---|
| `LakehouseClient` (Protocol) | `contracts/lakehouse.py` | `SilverLakehouse`, `DuckDBLakehouse` | `list_datasets`, `get_dataset`, `search_datasets`, `execute_sql` (salt-okunur), `preview`, `series_sql`, `health` |
| `GoldCapable` | `contracts/lakehouse.py` | `SilverLakehouse` | Gold fonksiyonları; yoksa Gold araçları kaydedilmez |
| `EvidenceCapable` | `contracts/evidence.py` | `SilverLakehouse` | Gözlem → artifact → RAW kanıtı; yoksa zincir SQL'de biter |
| `DatasetSpec`, `ColumnSpec`, `Coverage` | `contracts/catalog.py` | katalog | Anlamsal katalog: frekans, ölçüm tipi, birim, kapsam, ilişki |
| `Tool` + `ToolResult` | `core/tool.py` | 25 araç | `name`, `description`, Pydantic `Params`, `run()`; şema `Params`'tan otomatik |
| `LLMClient` | `llm/base.py` | `OpenAICompatClient` | `chat(messages, tools, temperature, max_tokens)` |
| `Embedder`, `LexicalIndex` | `contracts/retrieval.py` | `MiaEmbedder`, `Bm25Index` | Katalog araması |
| `AccessOutcome` | `contracts/access.py` | erişim politikası | Erişim sonucu, sebep, seçenekler |

## 2.3 `lakehouse-core/src/lakehouse`

| Paket | Sorumluluk |
|---|---|
| `connectors/` | Kaynak erişimi (`BaseConnector.fetch`): `bddk_monthly`, `bddk_weekly`, `bddk_finturk`, `evds` |
| `parsers/` | RAW → tablo (`BaseParser.parse`) |
| `storage/` | RAW dosyaları (sha256) ve Parquet (Bronze) |
| `ingestion/` | Kaynak → RAW → Bronze orkestrasyonu, gözlemlenebilirlik, pencereleme |
| `silver/` | Silver V1: `silver.fact_observation`, kapsam yenileme, kaynak eşlemeleri |
| `catalog/` | Seri kataloğu yükleme, kayıt, taslak → aktif terfi, ilişki grafı (`relations.py`), artifact deposu |
| `gold/` | `align_frequency`, `decompose_cumulative`, `join_on_period`, Gold tablolarının kurulumu |
| `generic/`, `adhoc/` | Bağlayıcısı olmayan dosya/adres (CSV, TSV, JSON, XLSX, HTML) → taslak ad-hoc tablo |
| `quality/` | Kalite kapıları (ör. vade kovaları toplamı = Toplam) |
| `security/`, `query/` | Salt-okunur SQL koruması ve sorgu yürütücü |
| `db/` | DuckDB bağlantısı, şema kurulumu (`bootstrap_database`) |
| `cli.py`, `application.py` | Komut satırı: `bootstrap`, `ingest`, `silver`, `gold`, `gold-run`, `ingest-file`, `promote-draft` |

## 2.4 Nasıl genişletilir

**Yeni veri kaynağı (lakehouse-core)**
1. `connectors/base.BaseConnector` alt sınıfı yazın (`fetch(FetchSpec) -> list[FetchedAsset]`).
2. `parsers/` altında `BaseParser.parse(FetchedAsset) -> ParsedBatch` uygulayın.
3. `catalog/series/<kaynak>.yml` dosyasına serileri ekleyin (sözleşme: `lakehouse-core/docs/catalog-contract.md`).
4. `scripts/ingestion_registry.py` → `CONNECTOR_REGISTRY` ve `silver/adapters/catalog_driven.py` → `SOURCE_MAPPINGS`
   kayıtlarını ekleyin.

Ajan tarafında hiçbir kod değişmez; yeni seriler katalogdan aranır ve sorgulanır.

**Yeni araç (agent-core)**
1. `core.tool.Tool` alt sınıfı yazın: `name`, `description`, Pydantic `Params`, `run() -> ToolResult`.
2. `cli.build_agent` içinde `registry.register(...)` ile kaydedin.
3. Araç bir sinyalle açılacaksa `core/tool_gate.py` içinde bir aileye ekleyin.

**Yeni alan (finans dışı)**
1. `python -m lakehouse bootstrap --catalog none` ile boş kataloglu bir havuz kurun.
2. Veriyi `ingest-file` → `promote-draft` ile ekleyin; ya da arayüzden Architect profilinde dosya yükleyin.
3. Alan profili katalogdan türetilir; isterseniz `DOMAIN_DESCRIPTION` / `DOMAIN_AUDIENCE` ile ton verin.

Kaynak adları ve kurum adresleri `config_data/source_hints.json` içindedir; `SOURCE_HINTS_FILE` ile başka bir dosya
verilebilir.

**Web kaynağı adaptörü**
1. `config_data/source_hints.json` → `financial_sources` altına kaynağı ekleyin: `aliases`, `hosts`, `canonical_url`,
   `access_mode`, `adapter_key`, isteğe bağlı `manual_export`.
2. Sayfaya özel form etkileşimi gerekiyorsa `web/browser.py` → `_ADAPTERS` içine bir fonksiyon ekleyin.

## 2.5 Testler

| Paket | Komut | Kapsam |
|---|---|---|
| agent-core | `cd agent-core && uv run --frozen --extra dev pytest -q` | 1168 test (~8 sn), sahte LLM ile deterministik |
| lakehouse-core | `cd lakehouse-core && uv run --frozen pytest -q` | birim, sözleşme, güvenlik, altyapı, entegrasyon (~1100+ test, uzun) |

CI iki iş akışıyla koşar: `.github/workflows/tests-agent.yml` ve `.github/workflows/tests-lakehouse.yml` (8 paralel
parça).
