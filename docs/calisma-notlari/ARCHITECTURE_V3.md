# Architecture V3 — Batched ReAct + Boundary Validation

> **Tarih:** 10 Eylül 2026 · **Durum:** Deney öncesi son tasarım · **Önceki:** `ARCHITECTURE_RESEARCH.md` (V2, araştırma tabanı)
> **Hedef:** En generic tasarımda, en çok edge case'i yakalayarak, **en hızlı** cevap.
> **Tek cümle:** Mevcut ReAct harness'ı korunur; hız üç kaldıraçla gelir (tur sayısı, üretilen token, prefill), güvenlik araç sınırındaki referans doğrulamayla gelir, genericlik katalogdan türeyen domain profiliyle gelir.

Kanıt etiketleri `ARCHITECTURE_RESEARCH.md` ile aynıdır: `[ORG] [DOC] [EMP] [SRC] [INF] [ASM] [REC]`. Bu dokümanda `[EMP]` etiketi ekibin devam notundaki MIA ölçümlerine işaret eder; ben tekrar ölçmedim.

---

## 1. Dört mimarinin karşılaştırması

### 1.0 Karşılaştırılan dört mimari nedir?

| Kısaltma | Nedir | Nerede | Durum | Bu dokümanda neye dayanarak tarif edildi |
|---|---|---|---|---|
| **R** | Repoda **kurulu, çalışan** mimari: `AnalyticsAgent.ask()` ReAct döngüsü, ToolRegistry, AnalysisWorkspace, DomainProfile, 5 guard, golden set | `feature/agent-engine` dalı (Baran); `main`'deki README aynı tasarımı anlatır | Çalışıyor; golden 7/7, pass^3, MIA'da native tool calling `[EMP]` | Ekibin devam notundaki tanım; **kod okunmadı** (git'e bakılmaması istendi) |
| **V1** | Önceki bir Claude oturumunun çizdiği çok rollü taslak (Intent Classifier, Planner, Discovery/Ingestion ajanları, metrics.yaml, LanceDB, OTel+Langfuse) | `Claude outputs/architecture.mmd`, **commit edilmemiş** | Öneri; ekibin ADR'ları büyük bölümünü reddetti (Plan DSL, metrics.yaml, LanceDB, Langfuse, 3 ajan, placeholder narration) | Dosyanın kendisi |
| **V2** | Bu oturumun ilk önerisi: Planner JSON planı → deterministic executor → verifier → Narrator | `docs/calisma-notlari/ARCHITECTURE_RESEARCH.md` | Araştırma tabanı olarak kalıyor; omurgası V3 ile değiştirildi | Literatür + organizatör kısıtları; MIA ölçümü yokken yazıldı |
| **V3** | Bu doküman: R'nin döngüsü + paralel araç çağrısı + araç sınırında doğrulama + grounding guard | `docs/calisma-notlari/ARCHITECTURE_V3.md` | Deney öncesi nihai tasarım | R + V2 + son literatür + ekibin MIA ölçümleri |

Tablodaki "mevcut koddan fark" satırları ve §6'daki geçiş deltası **R'ye göre** yazılmıştır.

| Boyut | R — mevcut ReAct | V1 — çok rollü taslak | V2 — Plan·Execute·Verify | V3 — Batched ReAct + boundary validation |
|---|---|---|---|---|
| Kontrol döngüsü | Tek agent, adım başına 1 LLM turu, native tool calling `[EMP]` | Intent → Planner → Validator → Executor → Verifier → Narrator + 2 ajan | Planner JSON planı → deterministic executor → verifier → Narrator | ReAct korunur; **tur başına birden çok araç çağrısı** (paralel), araç sınırında doğrulama |
| Tipik soru için LLM turu | 4–8 (adım sayısı kadar) | 4–6 | 2 (+replan) | **2–3** (keşif+veri turu, analitik turu, cevap turu); verified-query replay'de **0** |
| Planın görünürlüğü | Yok (trace'ten çıkarılır) | Var (AnalysisPlan) | Var (AnalysisPlan) | Turdaki araç çağrı kümesi = plan katmanı; trace panelinde "tur → çağrılar" olarak gösterilir |
| Doğrulama noktası | 5 guard (cevap, dönem filtresi reddi, kapsam, birim etiketi, çıktı sınırı) | Plan validator + verifier + 6 guard | Plan validator + verifier | **Her araç çağrısında** şema + **referans** (seri/kolon var mı, coverage, tip uyumu) + politika (index kilidi, SQL allowlist) + çıkışta grounding guard |
| Halüsine argüman (şemaya uyan ama var olmayan seri) | Araç hata döndürür, model düzeltir | Plan validator yakalar | Plan validator yakalar | Referans doğrulama yakalar, `hint` ile yapılandırılmış gözlem döner; 2. başarısızlıkta reasoning yükseltilir |
| Workspace | `AnalysisWorkspace` set/add/replace/revert; "bozmadan" garantisi kodda | Sürümlü + index kilidi | Aynı | R'nin workspace'i korunur; sürüm numarası ve kolon soyağacı eklenir (ledger için) |
| Anlatım / sayı güvenliği | Cevap guard'ı | Placeholder narration | Placeholder narration | **Grounding guard**: cevaptaki her sayı araç çıktılarıyla eşleşmeli (toleranslı); tablo kod tarafından üretilir, anlatım ≤150 token |
| Retrieval | Katalog prompt'ta; FTS P0 | LanceDB P0 | FTS P0, embedding/reranker bake-off'a bağlı | Katalog **özeti** prompt'ta (token bütçeli); eşik aşılınca `search_series` (FTS → hybrid) devreye girer; eşik seri sayısı değil **token** |
| Search soyutlaması | Araç olarak web search/URL | Yok | `SearchProvider` (Tavily/Firecrawl/cache) | V2 ile aynı; **spekülatif ön-çekim**: soruda URL varsa model turuyla paralel indirilir |
| Ad-hoc URL | Yok | Ingestion Agent + insan onayı | Document Reader ≤4 adım + quarantine | Metin katmanı → tablo tespiti → (boşsa) OCR; LLM yalnızca tablo yapısı belirsizse; quarantine + onay |
| Analitik araçlar | Yalnız Lakehouse | 6 aile | 6 aile | 6 aile; **kompozit araçlar** (`fetch_aligned`, `compare_series`) tur sayısını düşürür |
| Thinking politikası | `reasoning_effort=none` `[EMP]` | "think-strip" | Non-thinking planner | **Araç turları her zaman non-thinking** (vLLM: thinking + tools → tool_calls parse edilmiyor `[SRC]`); cevap turu non-thinking; **yükseltme** yalnızca 2. doğrulama hatası veya belirsizlik sınıfında `low` |
| Hız kaldıraçları | Reasoning kapalı | Gateway cache | 2 tur | Tur sayısı (paralel çağrı + kompozit araç), üretilen token (kısa anlatım, tablo kodda), prefill (sabit önek + prefix caching testi), replay cache, spekülatif ön-çekim, streaming |
| Edge-case kurtarma | Hata metni modele döner | Replan ≤2 | Replan ≤2 | Araç başına ≤2 onarım, soru başına ≤8 tur, yükseltmeli reasoning, güvenli başarısızlık şablonu |
| Genericlik | `DomainProfile.from_catalog`, motorda finans terimi yok (testli) | metrics.yaml (finansa yakın) | Domain Knowledge Layer plugin | R'nin DomainProfile'ı + **domain plugin** (alias sözlüğü, tip kuralları, tarihli notlar, anlatım şablonları); motor değişmez |
| Observability | Golden set + `--repeat` | OTel + Langfuse | JSONL trace | JSONL trace + tur/çağrı görünümü + **pass^3** raporu |
| Mevcut koddan fark | — | Yeniden yazım | Planner katmanı yazımı | **Ekleme**: paralel executor, boundary validator, grounding guard, kompozit araçlar, 5 yeni araç ailesi; ReAct döngüsü ve workspace aynen |
| En büyük risk | Uzun sorularda tur sayısı ve hata birikimi | 10 günde bitmez; 5 LLM rolü | Plan şeması demo sürprizlerinde katı | Paralel tool call MIA'da çalışmazsa tur sayısı R'ye döner (yine de çalışır) |
| Jüri değeri | Çalışan demo | Kâğıt üstünde etkileyici | Plan görünürlüğü | Trace'te "tur → paralel çağrılar → doğrulama → kaynak" zinciri + hız |

**Sonuç:** V3, R'nin kanıtlanmış döngüsünü ve V2'nin doğrulama/provenance fikirlerini birleştirir; V1 ve V2'nin ayrı planner/narrator turlarını kaldırır. Kaybedilen tek şey "plan önceden görünür" özelliği; bunun yerine tur içi çağrı kümesi plan olarak sunulur.

---

## 2. Son literatür turu — bu tasarımı ne belirledi?

| Bulgu | Kaynak | V3'e etkisi |
|---|---|---|
| Paralel araç çağrısı + bağımlılık grafiği ReAct'e göre 1.8–3.7× hız, 3–7× maliyet düşüşü, ~+9 puana kadar doğruluk | LLMCompiler (ICML 2024) `[SRC]` | Tur = paralel çağrı katmanı; executor eşzamanlı yürütür |
| Gözlemsiz planlama token'ı %64 azaltıyor, doğruluk +4.4 | ReWOO (2023) `[SRC]` | Modelden "bu turda gereken tüm bağımsız çağrıları" istemek; gözlemleri kısa özetle döndürmek |
| Prefix caching yalnızca **birebir aynı önek**te prefill'i atlar; sunucu tarafında açık olmalı | vLLM docs `[DOC]` | Prompt düzeni: sabit içerik önce (system + araç şemaları + domain profili + katalog özeti), değişken içerik sonda; MIA'da açık mı → deney E3 |
| Thinking açıkken Qwen3.5-27B tool call'ları `content` içinde XML döner, `tool_calls` boş; `qwen3_xml` parser `qwen3_coder`'dan daha güvenilir | vLLM issue #42021 ve parser docs `[SRC]` | Araç turları kesinlikle non-thinking; `tool_calls` boşsa content'te `<tool_call>` XML fallback parse |
| Şema doğrulaması "şekli" doğrular, "referansı" değil; halüsine argümanlar şemadan geçip retry ile temiz iz bırakır | 2026 mühendislik analizi `[SRC]` | Araç sınırında referans doğrulama (seri/kolon/coverage) zorunlu; hata yapılandırılmış gözlem |
| Kolay sorguda düşük, zorlaştıkça yüksek reasoning effort; başarısızlıkta yükseltme | Ares (2026), BoundaryRouter (2026) `[SRC]` | Varsayılan `none`; 2. hata veya belirsizlik sınıfında `low` |
| pass^k: %90 pass@1 olan sistem k=8'de %57'ye düşer | τ-bench `[SRC]` | Golden set raporu pass^3 ile; ekibin `--repeat` uygulaması zaten bu |
| Gerçek çok adımlı veri analizi görevlerinde en iyi ajanlar ~%16 | DABstep (2025) `[SRC]` | Zor sorularda "kısmi cevap + neyin doğrulanamadığı" şablonu; overclaim yok |
| Sütun semantik tipi tespiti değerlerden + bağlamdan öğrenilebilir (F1 .89–.93) | Sherlock/Sato `[SRC]` | Bilinmeyen dataset onboarding'inde deterministic profil + LLM tip önerisi (`derived`), insan onayı |
| Katalog nesnelerinin ayrı şablonlarla retrieval'ı ve sorgu geçmişi recall'ı 52→92 | Schema-First Retrieval `[SRC]` | Verified-query cache hem hız hem doğruluk kaldıracı |

---

## 3. V3 tasarımı

### 3.1 Akış

```text
Soru (+URL?) ─► 0 INPUT GUARD (kapsam · injection · URL tespiti)            [LLM yok, <5 ms]
            ─► 0' FAST PATHS
                 · verified-query replay: normalize(soru)+workspace imzası+katalog vintage eşleşirse
                   kayıtlı çağrı dizisi yeniden yürütülür, cevap şablondan             [LLM yok]
                 · spekülatif ön-çekim: URL varsa fetch/parse model turuyla paralel başlar
            ─► 1 PROMPT (sabit önek → değişken sonek)
                 [system: motor kuralları + araç şemaları + domain profili] [katalog özeti ≤ N token]
                 [workspace projeksiyonu] [konuşma özeti] [soru]
            ─► 2 TUR k (non-thinking): model bağımsız çağrıları TEK turda verir
                 ─► BOUNDARY VALIDATOR (her çağrı): şema → referans → politika
                      geçer ─► PARALLEL EXECUTOR (thread pool, DuckDB read-only bağlantı/iş parçacığı)
                      geçmez ─► yapılandırılmış hata gözlemi {error_code, hint, retryable}
                 ─► gözlemler kısa özetle modele döner (tam veri workspace'te kalır)
                 döngü: soru başına ≤8 tur, araç başına ≤2 onarım; 2. hatada reasoning=low
            ─► 3 CEVAP TURU (non-thinking, ≤150 token anlatım; tablo/grafik kod üretir)
            ─► 4 GROUNDING GUARD: cevaptaki sayılar ↔ ledger (toleranslı); nedensellik dili filtresi
                 geçmez ─► 1 yeniden üretim (hatalı sayılar listelenir) ─► yine geçmez ─► tablo + caveat
            ─► 5 ÇIKTI: tablo · grafik · anlatım · kaynaklar · trace (tur → çağrılar → doğrulama)
```

### 3.2 Araç registry (6 slayt ailesi + kompozitler)

| Aile (slayt ismi) | Atomik araçlar | Kompozit (tur düşürücü) |
|---|---|---|
| Lakehouse Tool | `search_series`, `describe`, `get_series`, `execute_sql` (guarded) | `fetch_aligned(concepts[], start, end, freq)`: concept→seri çözümü (yüksek güvende), tip-uyumlu align, tek tablo; düşük güvende adayları döndürür ve model seçer |
| Web Search Tool | `search_web`, `fetch_page` | `evidence_lookup(topic, period)`: resmî domain önceliği + tarih aralığı + alıntı çıkarımı |
| Web URL Agent Tool | `ingest_url` (metin katmanı → tablo → OCR fallback), `extract_table` | — |
| Anomali Tool | `detect_anomalies` (STL + robust MAD/ESD; revizyon anomalisi ayrı sınıf) | — |
| Causality Tool | `stationarity`, `lagged_correlation`, `granger_causality` (Toda-Yamamoto, d_max) | `compare_series(x, y, max_lag)`: durağanlık + lag korelasyon + rejim etiketleri tek çağrıda; Granger yalnızca n ≥ 30'da eklenir |
| Change Detection Tool | `detect_changepoints` (PELT) | — |
| Dönüşüm / DQ / Chart | `align`, `decumulate`, `deflate`, `rebase_index`, `pct_change`, `pp_change`, `check_coverage`, `plot_*`, `emit_table` | — |

Kompozitler yalnızca deterministic bileşenlerin sıralı çağrısıdır; provenance her alt adımı ayrı kaydeder. Model atomik araçlara da erişebilir (kompozit düşük güven döndürürse).

### 3.3 Boundary validator — üç katman

1. **Şema:** Pydantic; hatalı tip/eksik alan → `INVALID_ARGS` + alan listesi.
2. **Referans:** `series_id` katalogda var mı; `column` workspace'te var mı; tarih aralığı `first_obs..last_obs` içinde mi; `frequency` hedefi upsample mı; `measure_type=unknown` ise dönüşüm istenmiş mi; subtotal + bileşen aynı toplamda mı. Hata → `SERIES_NOT_FOUND / OUT_OF_COVERAGE / SEMANTIC_VIOLATION` + `hint` (en yakın 3 aday, gerçek kapsam).
3. **Politika:** index kilidi (`extend` modunda mevcut kolon silinemez), SQL AST allowlist, satır limiti, timeout, side-effect yok.

Retry politikası: `retryable=true` olan hatalar modele döner (≤2); `retryable=false` (politika ihlali, kapsam dışı) doğrudan güvenli başarısızlık şablonuna gider: bir sonraki tur **araçsız** çağrılır, model yalnızca cevap yazabilir.

**Tek hata zarfı (10 Eylül, 2. oturum, `kkb_agent_v3/errors.py`).** Üç katman ve tüm araçlar aynı Pydantic modelini döndürür:

```python
ToolError(error_code, message, hint, candidates[], retryable, needs_user_input, source_id, layer)
```

- `error_code`: data ekibinin sözleşmesindeki 14 kod (`LAKEHOUSE_CONTRACT_FILLED.md §18`) + motor kodları (`INVALID_ARGS, UNKNOWN_TOOL, COLUMN_NOT_FOUND, OUT_OF_COVERAGE, DOUBLE_COUNT, MISSING_PERIOD_FILTER, WORKSPACE_EMPTY, POLICY_VIOLATION, TOOL_FAILED`). Kod başına varsayılan `retryable` tablosu var; araç gerekçeyle ezebilir.
- Modele dönen gözlem zarfın kısa özetidir (`observation()`: kod + mesaj + en fazla 5 aday + "YAPACAĞIN" ipucu); tam zarf trace'e ve benchmark'ın hata-kodu dağılımına gider.
- `needs_user_input`: audit review §F-3'ten kalan tek ek alan (L10 `clarify` yolu). `replan_possible` düşürüldü — ReAct'te `retryable=true` zaten yeniden plan demektir `[INF]`.
- Katman sırası uygulamada **şema → SQL guard → referans → araç politikası**: yasak bir ifadenin referanslarını doğrulamak anlamsız, "dönem filtresi ekle" deyip DROP'u tekrar denetmek bir tur yakar (test: `tests/v3/test_validator.py`).

Aynı kalıp — sınırda doğrulama, satır limiti, hint'li yapılandırılmış hata — **WrenAI**'de de kullanılıyor: README'de *"dry-plan validation, row limits, and structured errors keep agent-generated SQL inside guardrails"* `[SRC]` (github.com/Canner/WrenAI). Fark: WrenAI SQL planı düzleminde doğruluyor (`dry-plan` = planı çalıştırmadan doğrulama), biz seri/kolon/dönem düzleminde; SQL karşılığımız politika katmanındaki AST allowlist + satır limiti (`guard_sql`, ekip adaptörü). Ekip motorunda `ToolResult.error("HATA: ...")` serbest metindi `[SRC]`; V3 motoru ekip workspace araçlarını değiştirmeden sarar ve hata metnini koda çevirir (`tools/workspace.py`).

### 3.4 Thinking ve effort politikası

Ölçüm (10 Eylül, `docs/calisma-notlari/mia_capability_matrix.md`) `[EMP]`: thinking varsayılan **açık** (`reasoning_tokens` > 0, içerik `reasoning_content` alanında); `enable_thinking=false` ve `reasoning_effort=none` ikisi de kapatıyor; `reasoning_effort=low` açıyor. Thinking açıkken de `tool_calls` doğru parse ediliyor; kural parser için değil, **latency** için (araç turu 0.5 s vs 1.1 s).

| Durum | Ayar |
|---|---|
| Araç turu | `reasoning_effort=none` — latency için (parser uyumu sorunu bu deployment'ta yok) |
| Cevap turu | non-thinking varsayılan |
| 2. doğrulama hatası aynı turda | cevap turunda `reasoning_effort=low` |
| Input guard "belirsiz" sınıfı (L10) | ilk tur `low` + `clarify` aracı serbest |
| Nedensellik sınıfı soru | `compare_series` zorunlu; anlatım şablonu "öncülük/ilişki" dili |

### 3.5 Prompt düzeni ve bütçe

| Bölüm | Değişkenlik | Tahmini token | Not |
|---|---|---|---|
| System: motor kuralları | Sabit | ~600 | Tek system mesajı (vLLM ikinci system'i reddediyor `[EMP]`) |
| Araç şemaları | Sabit | ~1.500 | 6 aile + kompozit; açıklamalar kısa |
| Domain profili | Katalog vintage'ına bağlı sabit | ~300 | Katalogdan türetilir |
| Katalog özeti | Vintage'a bağlı sabit | ≤6.000 (≈200 seri satırı) | E8 `[EMP]`: 200 seri 0.57 s, 1000 seri 2.4 s; eşik aşılırsa BM25 top-30 aday listesi girer, tam katalog girmez |
| Workspace projeksiyonu | Değişken | ~200 | Kolon adı, tip, birim, satır sayısı, sürüm |
| Konuşma özeti + soru | Değişken | ~300 | Ham geçmiş değil, özet |

Ölçülen maliyet modeliyle (`142 ms + 0.072 ms/token prefill + 10 ms/çıktı token`) `[EMP]`: 5k token prompt = 360 ms; 120 token çıktı = 1.2 s. **Üretilen token maliyeti prefill'in ~15 katı** → asıl kaldıraç kısa üretim.

Probe teyidi (10 Eylül) `[EMP]`: kısa istek p50 0.16 s; 49.9k token prompt 4.7 s (≈0.09 ms/token, doğru seri bulundu); plan JSON'u (~150–200 token) medyan 2.0 s; 5 paralel istek 429 üretmedi; prefix caching kazancı yok. Sonuç: sabit önek düzeni gereksiz, **prompt uzunluğu ve çıktı uzunluğu** tek kaldıraç.

Diğer ölçülen yetenekler `[EMP]`: `response_format=json_schema` **çalışıyor** (şemaya uygun anahtarlar) → `extract_table` ve `clarify` gibi yapılandırılmış çıktı gereken yerlerde kullanılabilir; prompt-only JSON ham 27/30, extract sonrası 30/30; T=0+seed deterministik (5/5 aynı); streaming SSE var; embedding 4096 boyut, `dimensions` parametresi **reddediliyor** (400) → MRL client-side kesme+normalize ile; embedding 64'lük batch OK, "konut kredisi faizi" sorgusu doğru seriye (0.667) yanlış olandan (0.536) daha yakın; yanlış model isteği 403 + `allowed_models` listesi döndürüyor; rate-limit header'ı yok; system mesajı talimatına uyum 7/10 (**zayıf** → kritik format talimatları user mesajında da tekrarlanmalı); ikinci system mesajı 400 "System message must be at the beginning".

### 3.6 Latency bütçesi (hedef)

| Senaryo | Turlar | Tahmin |
|---|---|---|
| Verified-query replay (aynı soru sınıfı) | 0 | < 1 s |
| Tek seri lookup (L1) | 1 araç turu + cevap | ~3 s |
| Slayt sorusu 1 (iki seri + karşılaştırma + dış kanıt) | `fetch_aligned` + `evidence_lookup` (paralel) → `compare_series` + `detect_changepoints` (paralel) → cevap | ~7–9 s |
| Takip: "bozmadan deflate" (L5-02) | `fetch_aligned(TÜFE)` + `deflate` → cevap | ~4 s |
| Ad-hoc PDF (L12-03) | ön-çekim paralel; `extract_table` → cevap | ~6–15 s (OCR'sız/OCR'lı) |

Bunlar deneyle doğrulanacak hedeflerdir; ekibin 4–12 s golden ölçümü R için taban çizgisidir.

### 3.7 Genericlik

- Motor katmanında domain terimi yok (R'deki test korunur; V3 için `tests/v3/test_generic.py`).
- `DomainProfile.from_catalog` (ekibin, ADR-0012 ölçümlü; değiştirilmez) + **domain markdown dosyası** (`kkb_agent_v3/domain/finance.md`, `health.md`). YAML yerine başlıklı markdown: Text2SqlAgent'ın `scenarios.md` kalıbı — *"a markdown file where each `## heading` contains domain knowledge the agent can't infer from the schema alone"*, başlık listesi prompt'ta, bölüm `lookup` aracıyla `[SRC]` (github.com/Text2SqlAgent/text2sql-framework).
- **İki tür bölüm, iki okuyucu** (10 Eylül, 2. oturum kararı; brief'in "her şey lookup" önerisinden fark):

  | Bölüm | Kim okur | Neden |
  |---|---|---|
  | `## measure_rules` (markdown tablosu: semantic_type → allowed/forbidden/hint) | Boundary validator (kod) | Tip kuralı deterministik kalmalı; LLM'in lookup'ı atlaması validator'ı boşa çıkarırdı |
  | `## evidence_domains` (tablo) | SearchProvider politikası (kod) | Aynı |
  | `## note: <başlık>` (tarihli notlar), `## template: <başlık>` (anlatım şablonları) | Model | Bütçeye göre gömülü **veya** `lookup_domain_note(topic)` |
  | `aliases` | **dosyada yok** | Katalog (`ColumnSpec.aliases`) tek kaynak; ikinci kopya vintage uyuşmazlığı `[INF]` |

- **Bütçe kuralı** (E8 ile aynı mantık): model bölümlerinin toplamı `KKB_V3_DOMAIN_BUDGET` (varsayılan 1.500 token) altındaysa prompt'a gömülür; üstündeyse yalnız başlık dizini girer ve `lookup_domain_note` aracı kayıt edilir (aksi hâlde şeması bile prompt'a girmez). Gerekçe ölçülmüş maliyet modeli `[EMP]`: bir araç turu ≈ 142 ms + ~30 çıktı token (300 ms) + gözlem prefill ≈ 0,5 s ≈ **~7k token prefill karşılığı**; bugünkü finans notları 418 token (`[EMP]`, 10 Eylül, 2. oturum smoke) → gömmek 30 ms, lookup 500 ms. Lookup ancak notlar büyüyünce veya sorguların çoğunda gereksizse kazandırır. Ek risk: MIA'da system-talimat uyumu 7/10 `[EMP]` — "gerekince lookup çağır" talimatı atlanabilir; gömülü not atlanamaz. Kırılma noktası **E11** ile ölçülecek (gömülü vs lookup, L5/L6 golden'ları, tur/süre/pass^3).
- Sağlık dataset'i: `health.md` yalnız boş başlıklar; `DomainProfile.generic()` + boş notlarla motor değişmeden çalışır (`tests/v3/test_domain_md.py`).
- Bilinmeyen dataset onboarding'i: deterministic profil (tip, null, min/max, tarih kapsamı, aday anahtar) → LLM tip/alias önerisi (`semantic_confidence=derived`) → insan onayı → katalog. Unseen-schema golden vakaları (L8) bunu ölçer.
- Bilinmeyen dataset onboarding'i: deterministic profil (tip, null, min/max, tarih kapsamı, aday anahtar) → LLM tip/alias önerisi (`semantic_confidence=derived`) → insan onayı → katalog. Unseen-schema golden vakaları (L8) bunu ölçer.

### 3.8 Web erişim politikası — mentör kararıyla (12 Eylül)

11 Eylül taslağı (üç madde) 12 Eylül'de iki girdiyle değişti: **(a)** gerçek sitelerde ölçüm `[EMP]` (`docs/experiments/web_access_evidence_2026-09-11.md`: Moody's → login yönlendirmesi; S&P → 403 "Security Controls Triggered", hesap olsa da; Statista/REIDIN → ücretli üyelik + reCAPTCHA; Borsa İstanbul DataStore → üyelik + JS'siz boş kabuk); **(b)** mentörün yazılı cevabı `[ORG]` (bellek: `kkb-mentor-guidance-2026-09-12`). Baran aynı gün bunları ortak katmana kodladı: **ADR-0028** (`contracts/access.py`, `core/access_policy.py`, 19 test) ve **ADR-0034** (`tools/web.py`, `web/*`, golden G11a/b/c 3/3) `[SRC]`. V3 bunları **yeniden yazmaz, import eder** (ADR-15 "modüller ortak katmana" ilkesi).

| # | Karar | 11 Eylül taslağından fark | Kaynak |
|---|---|---|---|
| 1 | **Hesap açma, CAPTCHA aşma, bot denetimi dolanma yok.** Önceden açılmış ekip hesabı/anahtarı kabul; **yalnız env/secret katmanında**, config dosyasında asla. Kod anahtarın *var olup olmadığına* bakar, değerini okumaz ve mesaja koymaz (`credential_available(host)`). | Aynı; "config'e gömme" sınırı netleşti | Mentör 1 `[ORG]`, ADR-0028 |
| 2 | **Üç engel sınıfı, üç ayrı davranış.** `needs_credential` (401, login yönlendirmesi, işaretsiz 403) → ekip anahtarı seçenek; `blocked` (bot işaretli 403, CAPTCHA, paywall, robots) → anahtar seçenek **değil**, dolanılmaz; `not_found` (404/410, ulaşılamadı). Üçü de `retryable=false`. | Taslakta tek kod (`AUTH_REQUIRED`) vardı; ölçüm üç sınıf gösterdi | `[EMP]`, ADR-0028 |
| 3 | **Erişilemeyince açıkça söyle, seçenek sun:** yetkili anahtar → dosya yükle → alternatif kaynak. Alternatif bulmak artı; **sessizce değil**. Hiçbir hesabın açmadığı URL'de de kontrollü geriler; mimari "biz önceden üye oluruz" varsayımına bağlı değil. | (b) ve (c) seçenekleri aynı; "alternatif kaynak" eklendi; ekip hesabı varsayılan yol olmaktan çıktı | Mentör 1 |
| 4 | **Kaynak sadakati bir kısıttır.** Soruda URL, "bu siteden / şu linkten", ya da "TCMB'den getir" kalıbı varsa `SourceConstraint.pinned=true`: erişilemez/yoksa **sorulur**, başka kaynağın verisi ilk kaynaktan gelmiş gibi sunulmaz. "2025 enflasyonunu bul" gibi serbest soruda alternatif kaynağa geçilebilir, **açıklamayla** ("belirttiğiniz kaynakta yok, TCMB'de var, onunla devam edebilirim"). Tespit tutucu: emin değilse serbest. | Yeni | Mentör 3, ADR-0028 `detect_source_constraint` |
| 5 | **Sabit derinlik yok; bütçe + ilgi tabanlı tarama.** Aynı alan adı, robots.txt, özel IP yok (SSRF), sayfa/derinlik/süre bütçesi; **önce doğrudan veri bağlantıları** (.csv/.xlsx/.json/PDF/tablo), sonra soru ve amaç sözcükleriyle örtüşen linkler; menü ağacı taranmaz. Her linke *neden* gidildiği deterministik ve izde. 2–3 seviye yalnız üst sınır. | Taslak "manifest + derinlik ≤2" diyordu; derinlik sayısı yerine bütçe ve öncelik sırası | Mentör 2, ADR-0034 |
| 6 | **Kapsam beyanı cevapta değil, kanıt panelinde.** Taranıp kullanılmayan ve erişilemeyen sayfalar `artifacts["web"]` → kanıt paneli (ADR-0033 "TARANDI, KULLANILMADI / ERİŞİLEMEDİ"). Final cevap sade kalır. | **Ters döndü:** taslağın zorunlu "incelenmeyenler: …" satırı kaldırıldı (Baran'ın itirazı doğruydu) | Mentör 3 |
| 7 | **Web tablosu sayı olarak değil metin olarak çıkarılır**; sayıya çevirme profilcinin dilbilgisiyle (hangi ondalık/binlik çifti kolonun %100'ünü ayrıştırıyor). pandas `thousands="."` tahmini TCMB'nin 31,51'ini 3151 yaptı `[EMP]`. Soruda geçen yıl sayfada hiç geçmiyorsa liste çıktısına "DİKKAT: … GEÇMİYOR" notu düşer. | Yeni | ADR-0034 |
| 8 | **`web_search` yalnız `TAVILY_API_KEY` varsa kayıt edilir**; sonuç veri değildir (başlık + adres + alıntı), sayı `web_url` ile sayfadan okunur. | Aynı ilke (ADR-0023) | ADR-0034 |

**Jüri sorusu ve cevabı** (mentörün önerisi): *"Yarın URL yerine REST API / veritabanı / stream / farklı kimlik doğrulaması verirsek ne değişir?"* → Yeni kaynak türü = yeni **adaptör/yetenek** (`LakehouseClient`, `EvidenceCapable`, `GoldCapable` sözleşmeleri; ingest için veri ekibinin connector'ı); erişim sözleşmesi (`AccessOutcome` → `FallbackDecision`), doğrulayıcı ve döngü değişmez. Bu cevabın kodda karşılığı olması, "agent sayısı"ndan daha çok puan getirir `[ORG]`.

**Alt-ajan kararı:** 11 Eylül'de düşünülen "Web URL alt-ajanı" **iptal** — mentör "multi-agent yapmaya çalışmazdım" dedi `[ORG]`; bağlam izolasyonu araç çıktısını kısa tutarak (liste modu: başlık, tablolar, ilk 3 satır, sha256) zaten sağlanıyor `[EMP]` (G11a 2 adım). Planner/Retriever/Validator/Narrator **rol etiketi** olarak izde görünür (ADR-0029 `AgentStep.role`), ayrı LLM değil.

**Açık kalan (ADR-0034 §"Açık kalan"):** tarama derinliği şimdilik 1; PDF okunmuyor (E7 sonucu — metin katmanı + OCR paralel — burada devreye girecek, bizim işimiz); JS ile dolan sayfa boş gelir ve tarayıcı **olmayacak** (bot denetimi çizgisi).

<details><summary>11 Eylül taslağı (tarihçe; yukarıdaki tabloyla değiştirildi)</summary>

1. **Kimlik model tarafından üretilmez.** Ajan hiçbir sitede hesap açmaz, rastgele e-posta kullanmaz (ToS, KVKK, bot tespiti, organizatör "web search / URL" çerçevesi dışı, demoda CAPTCHA/2FA riski). Kimlik **platform düzeyinde, bir kez, insan eliyle** tanımlanır: demo senaryosunda geçebilecek kaynaklara ekip önceden üye olur, anahtar/oturum `.env`'de durur (EVDS API anahtarı bugün böyle), ajan o alan adını görünce kullanır ve cevapta "ekip hesabıyla alındı" der. `ingest_url` 401/403/giriş formu görünce **`AUTH_REQUIRED`** (`retryable=false`, `needs_user_input=true`) döner ve kullanıcıya üç seçenek sunar: (a) dosyayı indirip ver (`ingest-file`, data ekibinin yolu `[SRC]`), (b) ekip hesabı tanımlıysa otomatik, (c) kendi anahtarını ayarlara ekle. Kullanıcı hesabının ajana verilmesi P0 dışı (oturum + prompt injection riski).
2. **Keşfi harness yapar, seçimi model.** `discover_url(url)` deterministik ve LLM'siz: aynı alan adındaki alt sayfalar, tablolar, PDF/XLSX bağlantıları, varsa `sitemap.xml` → **manifest** ("12 alt sayfa, 3 tablo, 5 PDF"); derinlik sınırı, robots.txt, aynı-alan-adı ve SSRF politikası kodda (review D). `ingest_url(resource)` manifestteki tek kalemi alır. Manifest cache'lenir; "alt başlıkları da incele" takip sorusu yeniden taramaz. Katalog ön-yüklemesiyle aynı ilke: modelin "yeterince baktım" hissine güvenilmez.
3. **Kapsam beyanı zorunlu.** Manifestte N kaynak varken K'sı kullanıldıysa cevap "incelenmeyenler: …" satırı olmadan geçmez (edge-case 19 şablonu, grounding guard'a kural). "Ben sormasaydım eksik kalacaktı" durumu bu satırla önlenir.

</details>

### 3.9 Kullanıcının yüklediği dosya: yanlış, fazla, çelişen (12 Eylül tasarımı; 13 Eylül ilgi kapısı, 15 Eylül uygunluk kapısı uygulandı)

Soru: kullanıcı yanlış dosya yüklerse, ya da doğru dosyayla birlikte yanlış bir dosya da yüklerse ne olur? İlke: **yüklenen dosyaya güvenilmez; karantina → profil → soruyla eşleştirme → onay → kaynak beyanı.** Baran'ın `ingest_from_url` akışı (ADR-0030: erişim → profil → öneri → doğrulama → belirsizse sor → CLI taslağa yazar → belge kartı) bunun ilk halkalarını zaten deterministik yapıyor `[SRC]`; eksik olan **soruyla ilişki** ve **çoklu dosya** kapıları (koda bakıldı: araç tek dosya alır, soruyla ilgi puanı yok, dosya-katalog mutabakatı yok `[EMP]`). Yeni araç değil, aynı aracın önüne iki kapı:

| Durum | Yakalayan | Mekanizma | Kullanıcıya |
|---|---|---|---|
| **A. Alakasız dosya** (kredi sorusu, otobüs tarifesi PDF'i) | İlgi kapısı (kod) | Profil çıktısından: dönem kolonu var mı; soruda geçen yıl(lar) dosyanın aralığında mı; soru sözcükleri / katalog alias'ları kolon adlarında ya da başlıkta geçiyor mu → 0–3 puan. Puan 0 → `FILE_IRRELEVANT` (`retryable=false`, `needs_user_input`) | "Bu dosyada sorunuzla ilgili bir seri bulamadım. Dosyada şunlar var: … Doğru dosya bu mu?" Tahmin yok, yazma yok |
| **B. Doğru + yanlış dosya birlikte** | Çoklu dosya sıralama (kod) | Her dosya ayrı profillenir ve puanlanır; en yüksek puanlı **tek** dosya öneriye gider, diğerleri "danışıldı, kullanılmadı" olarak kanıt paneline (ADR-0033 satırı, §3.8 #6 ile aynı ilke). İki dosya da yüksek puanlı ve **aynı seri/dönem için farklı değer** veriyorsa birleştirilmez → `DATA_CONFLICT`, sorulur | "X dosyasını kullandım (2024, 12 satır, milyon TL). Y dosyasında dönem kolonu yok, kullanmadım." |
| **C. Doğru görünen, yanlış içerik** (2023 verisi 2024 diye; ticari kredi tüketici diye; bin TL milyon diye) | Dönem çakışması (kod) · birim büyüklük kontrolü (kod) · onay cümlesi (insan) | Soruda 2024, dosyada 2023 → `OUT_OF_COVERAGE` mantığı, sorgu hiç kurulmaz. Katalogda aynı kavramda seri varsa büyüklük sırası karşılaştırılır; ~1000× fark → birim uyarısı. **Kavram uyuşmazlığı kodla tam yakalanamaz** `[INF]`; savunma ADR-0030'un onay adımı: "B kolonunu *tüketici kredisi bakiyesi* olarak alıyorum, birim başlıktan *milyon TL*" — kullanıcı yanlışı burada görür | Onay cümlesi + belge kartı; taslak seri notunda TASLAK |
| **D. Okunamayan dosya** (bozuk, şifreli, boş, OCR'sız görüntü) | `read_table_for_profiling` (kod) | `ReadRefused` → `ACCESS_BLOCKED`/`FILE_UNREADABLE`, tekrar denenmez | "Dosya açılamadı (…). CSV/XLSX olarak tekrar yükleyin." |
| **E. Dosya ile katalog çelişiyor** (aynı seri, aynı dönem, farklı değer) | Mutabakat kontrolü (kod, taslak yazıldıktan sonra) | Sessizce biri seçilmez. Katalogdaki (küratörlü) varsayılan; fark cevapta tek satır; kullanıcı dosyayı istemişse dosya kullanılır ve **kaynak beyanı** bunu söyler | "Yüklediğiniz dosya Aralık 2024 için 680.100 diyor, katalog 678.970. Katalog değerini kullandım; dosyayı tercih ederseniz söyleyin." |

**15 Eylül uygulaması (`docs/calisma-notlari/HUMAN_ERROR_RESEARCH_2026-09-14.md` PART 30–37, 40) `[SRC]`:** A satırındaki 0–3 puanlık ilgi kapısı (`builder/relevance.py`, 13 Eylül) ölçüldü ve yetersiz bulundu (anlamca yakın yanlış dosyayı — fiyat endeksi ≠ bakiye, 459.904'lük "faiz oranı" — hard-negative'lerin yalnız %6'sında reddediyordu). Yerine **uygunluk kapısı** `core/fitness.py`: sorudan GEREKLİ kavramlar (ölçüm / varlık / dönem / granülarite), veriden İMZA (ad + başlıklar + tarih aralığı + frekans + kolon medyanları + tek değerli boyutlar) → `accept | partial | reject`. Kavram sözlüğü kodda değil `config_data/concepts.json`'da (+ katalog alias'ları gevşek kavram olarak; `CONCEPTS_FILE` ile değiştirilir). Aynı kapı **iki yolda**: `web_url` `table_index` yüklemesinden ÖNCE (ret → tablo aktif olmaz, kart tabloda ne olduğunu söyler, `FILE_IRRELEVANT`, kullanıcı "yine de yükle" derse `user_confirmed`) ve `ingest_from_url`'de (ilgi kapısı yalnız gereksiz çıkarılamayan "bu dosyayı ekle" isteğinde yedek). Yanında: `builder/quality.py` (eksik/mükerrer dönem, toplam satırı, kısmi yıl, birim, etiket-değer → `UYARI:` satırları, engellemez), `core/question_preflight.py` (katalogda olmayan ölçüm/kırılım, ince frekans, tahmin yetkisi, öncül → soruya "ÖN-KOŞUL" satırı) ve `core/agent.py`'de kapsam beyanı (dış kaynaktan yüklenen tabloda cevabın ilk satırı "(Veri: … | UYARI: …)", deterministik) + "uyarı sayıdan önce" kuralı. Ablation'da eski H koluyla birebir (top-1 1,0; ilgisiz ret 0,99; yakın-yanlış ret 0,98; doğru kabul 1,0). Uçtan uca "sonra" ölçümü: `docs/experiments/ueb_after_2026-09-15.*`.

**16 Eylül tamamlaması (PART 42) `[SRC]`:** kapının etrafındaki üç boşluk kapatıldı. (1) **`check_premise`** (`tools/premise.py`): soru bir yön varsayıyorsa ("düştüğü için", "neden arttı") model cevap yazmadan önce yönü veriden sınar — seçtiği serinin dönemdeki ilk/son gözlemi, karar `DESTEKLİYOR / ÇELİŞİYOR / BİLİNMİYOR`, tepe/dip; alan sabiti yok (seri, kırılım, yıl modelden, ölçüm araçtan). Araç kapısında "öncül" ailesi (`tool_gate.PREMISE`, kalıp `question_preflight._PREMISE` ile tek yerde), veri getirdiyse araç çağrılmadan yazılan öncül cevabı bir kez geri gönderilir (`_REQUESTED_CAPABILITIES`), ön-koşul satırı aracı adıyla anar. (2) **`clarify`** (`tools/clarify.py`): TEK netleştirme sorusu, yalnız uygunluk kapısı *bu turda* "kısmen" demişse ve belirsizlik ölçüm/alt küme boyutundaysa (sayıyı değiştirir), tur başına bir kez (`CLARIFY_NOT_ALLOWED`, `terminal=False`: model eldeki veriyle cevap yazar); başarılı çağrı turu bitirir — model yeniden çağrılmaz, sayı üretilmez, kullanıcının cevabı `pending_question` ile sonraki tura bağlanır. (3) **G5/G6** (`core/claim_check.py`, kanca `core/agent.py` grounding noktasında): `claim_cell` — cevaptaki (dönem, sayı) çifti tabloda varsa ama BAŞKA dönemin değeriyse (A06: Ekim değeri "Aralık" diye) "yanlış hücre"; `range_claim` — kapsam beyanı ("veri 2024-01 → 2024-10") tablonun gerçek aralığıyla çelişiyorsa; MISS gibi iki geri gönderme, sonra deterministik not. Yanlış pozitif kuralları PART 22'den (en yakın dönem, tek dönem + tek sayı, kapsam sözcüğü şartı). Golden: `G12a` yanlış öncül, `G12b` gömülü nedensellik, `G12c` netleştirme, `G12d` önizleme/tam yıl, `G12e` anlamca yakın yanlış dosya (B02), `G12f` yanlış etiketli kolon (B07) — yerel fikstür, seed DB. Windows'ta `C:\…` yerel yolunun şema sanılması (`web/fetch.py`) düzeltildi; bu, iki bilinen `test_web` hatasını da kapattı. İkinci tam UEB koşusu: `docs/experiments/ueb_after2_2026-09-15_0110.*` — sessiz 0/37, kontrol 18/18, aşırı bloklama 0; üçüncü koşu (aynı kod) `ueb_after3_2026-09-15_0124.*` — sessiz 1 (B06: dosya adı "bin", soru "milyon"; `builder/quality.py`'ye ölçek uyuşmazlığı bayrağı eklendi, B06 canlı 2/2 SAFE), kontrol 18/18; dördüncü koşu (düzeltme sonrası tam 55) B06 SAFE, sessiz 2 (A07 yapay, A08 "puan" → ön-koşul satırı eklendi, A08 canlı 2/2 SAFE); üç koşuda 50/55 katı kararlı; sayılar PART 42.

Değişmeyen sınırlar (ADR-0030): yazma yalnız `adhoc` + `draft`, küratörlü Silver'a bu yoldan girilmez; birim veriden çıkarılamıyorsa yazılmaz; `measure_type` belirsizse `unknown` kalır ve kartta söylenir. 12 Eylül'de planlanan dört golden (alakasız / çift dosya / yıl uyuşmazlığı / bozuk dosya) yerine UEB'nin ölçülmüş sessiz vakalarının eşdeğerleri eklendi (yukarıdaki G12a–f); çift dosya ve bozuk dosya golden'ı hâlâ açık.

---

## 4. Edge-case matrisi

| # | Durum | Yakalayan | Mekanizma | Maks. maliyet |
|---|---|---|---|---|
| 1 | Olmayan seri/kolon (halüsine referans) | Boundary validator (referans) | `SERIES_NOT_FOUND` + en yakın 3 aday | +1 tur |
| 2 | Kapsam dışı dönem (2019, 2026-08) | Validator | `OUT_OF_COVERAGE` + gerçek kapsam; cevap "veri yok" | +1 tur |
| 3 | Ratio'ya avg, stok'a diff, upsample | Validator (tip) | `SEMANTIC_VIOLATION` + hint | +1 tur |
| 4 | `measure_type=unknown` | Validator | dönüşüm reddi + caveat | 0 |
| 5 | Subtotal + bileşen toplama | Validator | `DOUBLE_COUNT` | +1 tur |
| 6 | Birim karışması (bin/milyon) | `get_series` canonical birim; anlatımda birim etiketi guard'ı | — | 0 |
| 7 | Cevapta ledger dışı sayı | Grounding guard | 1 yeniden üretim, sonra tablo+caveat | +1 tur |
| 8 | Nedensellik dili | Anlatım filtresi | yeniden üretim | +1 tur |
| 9 | Belirsiz soru (L10) | Input guard sınıfı + `clarify` aracı | tek soru sorulur | 1 tur |
| 10 | Prompt injection / DROP / read_csv | Input guard + SQL AST guard | `retryable=false` → güvenli ret | 0 |
| 11 | Tool call parse edilemedi (`tool_calls` boş) | Gateway | content'te `<tool_call>` XML fallback parse; yine yoksa tur tekrarı | +1 tur |
| 12 | MIA 429/5xx/timeout | Gateway | exponential backoff + jitter (≤4); sonra güvenli başarısızlık | süre |
| 13 | MIA tamamen kapalı | Gateway | replay cache varsa cevap; yoksa "servis erişilemez" | 0 |
| 14 | Search provider arızası | `SearchProvider` zinciri | Tavily → Firecrawl → cache → "dış kanıt alınamadı" | süre |
| 15 | Demo URL: PDF (tablolu) | `ingest_url` | **E7 sonucu `[EMP]`:** metin katmanı ve OCR paralel; yapı OCR'ın HTML tablosundan (`pandas.read_html`), her sayısal hücre metin katmanında doğrulanır; metin katmanı boşsa yalnız OCR; OCR düşerse `find_tables(strategy="text")` + "başlık doğrulanamadı" uyarısı | ~2.5 s/sayfa, LLM turu yok |
| 16 | Demo URL: Excel/CSV | `ingest_url` | indir + pandas/openpyxl; şema önerisi | 0 LLM |
| 17 | Demo URL: görsel | `ingest_url` | OCR; tablo yoksa Qwen görsel yorum | 1 tur |
| 18 | Ad-hoc tablo yapısı belirsiz | `extract_table` | LLM ≤2 tur, quarantine, onay | 2 tur |
| 19 | Tur limiti aşıldı (≤8) | Orkestratör | kısmi sonuç + "doğrulanamayanlar" listesi | 0 |
| 20 | Aynı hata 2. kez | Orkestratör | reasoning `low` yükseltme | +latency |
| 21 | Takip sorusunda tablo bozulma isteği ("yeniden hesapla") | Workspace politikası | `replace_column` yalnızca açık istekle; aksi `add_column` | 0 |
| 22 | Katalog büyüdü, prompt bütçesi aşıldı | Context builder | **E8 `[EMP]`:** katalog ≤ ~6k token ise tamamı prompt'ta (%98, 0.6 s); üstünde `search_series` (BM25) top-30 aday prompt'a girer; 1000+ seride tam katalog 2.4 s, 3000+ seride hem yavaş (10.9 s) hem hatalı (%92) | 0 |
| 23 | Yeni dataset / şema | Onboarding | profil + öneri + onay; motor değişmez | — |
| 24 | Veri revizyonu (vintage değişti) | Ledger | `vintage_id` cevapla döner; replay cache geçersizleşir | 0 |

---

## 5. Birlikte yapılacak deneyler (sıra önemli)

| ID | Hipotez | Yöntem | Başarı kriteri | Kararı etkilediği yer |
|---|---|---|---|---|
| E1 | MIA tek turda birden çok `tool_calls` döndürür | İki seri isteyen soru; `tool_calls` sayısı | ≥2 | **SONUÇ (10 Eylül) `[EMP]`: 3 koşuda 3/3/3 çağrı/tur → paralel executor onaylandı** |
| E2 | Thinking açıkken tool_calls bozulur | Aynı istek `enable_thinking` true/false | Bozuluyorsa non-thinking kuralı `[EMP]` olur | **SONUÇ `[EMP]`: bozulmuyor; thinking açıkken de `tool_calls` parse ediliyor (reasoning ayrı alanda). Non-thinking kuralı artık parser için değil, latency için (0.5 s vs 1.1 s)** |
| E3 | Prefix caching MIA'da açık | 6k token sabit önek + farklı sonek ×5; 1. vs sonraki prefill süresi | ≥%50 düşüş → açık | **SONUÇ `[EMP]`: kazanç yok (0.90 s → 0.92 s). Prompt düzeni önemsiz; prompt uzunluğu önemli → katalog özeti bütçesi ve kısa gözlem özetleri** |
| E4 | Kompozit araç tur sayısını düşürür, doğruluğu düşürmez | L5-01 için atomik vs kompozit; tur, süre, pass^3 | tur −1, pass^3 eşit | 3.2 |
| E5 | Grounding guard yanlış pozitif vermez | 36 sorgu; guard'ın bloklayıp aslında doğru olan sayı oranı | <%3 | 3.1 adım 4 — **Bulgu (10 Eylül, 2. oturum) `[EMP]`:** Blok C gölge kayıtlarındaki `MISS:2,21, 2,50…` türü eşleşmezlerin kaynağı regex'ti: pandas'ın İngiliz ondalığı ("1.357539") Türkçe binlik ("1.357"→1357) okunuyordu, model "%1,36" yazınca havuzda bulunamıyordu. Düzeltme `kkb_agent_v3/core/grounding.py` (binlik alternatifi rakamla devam etmiyorsa) + test. L4-01: 9 tur/limit → 3 tur/OK. Blok C'nin "grounding enforce +2 tur" maliyeti bu FP'yi içeriyor; E5 V3 motorunda yeniden ölçülecek (benchmark r3'ün `grounding temiz` sütunu) |
| E6 | Reasoning yükseltme L10/L11'de fayda sağlar | none vs low, pass^3 | fark yoksa kaldır | 3.4 |
| E7 | Metin katmanı Borsa İstanbul PDF'inde dolu | `scripts/deney_ocr.py` (rakam metriği `<\|det\|>` temizlenerek) | doluysa OCR fallback | **SONUÇ `[EMP]`: metin katmanı dolu (59 ms, 416 rakam) ama tablo yapısı yok; OCR 2.4 s'de doğru `rowspan/colspan`'lı HTML tablo → 15×11 DataFrame. Karar: paralel çalıştır, yapı OCR'dan, sayı doğrulaması metin katmanından (`docs/experiments/E7_ocr_vs_text.md`)** |
| E8 | Katalog özeti kaç token'a kadar retrieval'sız çalışır | 60/200/1000/3000 seri; seri seçim doğruluğu ve süre | kırılma noktası | **SONUÇ `[EMP]`: 60 seri (2k tok) %98 / 0.27 s · 200 (6k) %98 / 0.57 s · 1000 (28k) %98 / 2.4 s · 3000 (91k) %92 / 10.9 s. Tek sabit hata "NPL" etiket belirsizliği (brüt tutar mı, oran mı). Kırılma: doğruluk 1000'den sonra, latency 200'den sonra. Karar: prompt'a giren katalog ≤ ~6k token (≈200 satır); üstünde `search_series` (BM25, 2 ms) top-30 adayı seçer, model adaylar arasından karar verir (`docs/experiments/E8_catalog_threshold.md`)** |
| E8-10k | Eşik üstü geçiş modu (aday listesi → model) EVDS ölçeğinde doğruluğu korur | `scripts/exp_e8_10k.py`: 3k/10k/30k seri, kavram başına ≤48 gerçekçi varyant + ilgisiz filler; 50 standart + 20 hard_variant sorgu; kollar `bm25` (düz top-30) ve `grouped` (kavram top-8 × ≤4 varyant) | uçtan uca ≥%96, R@30 ≥%98, p50 <1 s | **SONUÇ (10 Eylül, 2. oturum) `[EMP]`** — `docs/experiments/E8_10k_results.md`: **ölçekten bağımsız** — `bm25` 3k/10k/30k'da R@30 %96/%96/%96, uçtan uca %90/%90/%90; `grouped` %96/%96/%97, uçtan uca %93/%91/%91, prompt ~940 token (bm25 ~1.150); p50 0,18 s. H3 sağlandı; H1/H2 **sağlanmadı ama nedeni ölçek değil**: her boyutta aynı 3–4 sorgu düşüyor ("bankaların özkaynağı ne kadar", "işletmelere verilen krediler" → alias/çekim boşluğu; bake-off'taki kalan hatayla aynı sınıf). Düz `bm25` "mortgage bakiyesi"de kanonik seriyi varyanta kaptırıyor, `grouped` düzeltiyor. İlk koşu (v1, kavram başına ~500 varyant) R@30'u %69'a düşürmüştü — üreteç kusuru, `E8_10k_design.md §6`. **Karar:** eşik üstü mod EVDS ölçeğinde çalışır; `search_series` iki aşamalı (kavram → boyut) tasarlanır, bunun için `meta.series`'te kavram/ebeveyn anahtarı gerekir (data ekibine istek); kalan 5–7 puan alias kalitesi + Türkçe çekim (basit ek kırpma) + gerekirse hybrid (D-3) ile kapanır, K büyütmekle değil |
| E-RET | Retrieval bake-off (küçük): alias / BM25 / Qwen3-Embedding / hybrid RRF | 300 sentetik seri (60 gerçekçi hedef), 50 el yazımı sorgu, 7 kategori | Hybrid − BM25 ≥ 3 puan R@3 ise embedding P1'e girer | **SONUÇ `[EMP]`: BM25 R@3 0.96 (2 ms), dense 0.96 (28 ms + MIA çağrısı), hybrid 0.98, alias-exact 0.64. Fark +2 puan → embedding zorunlu değil, P1 opsiyon. Kalan tek hata her sistemde aynı (alias eksikliği). Uyarı: sorgu ve alias'lar aynı kişi tarafından yazıldı, iki sistem lehine iyimser; gerçek `meta.series` ile tekrarlanacak (`docs/experiments/RETRIEVAL_bakeoff.md`)** |
| E9 | 36 sorguluk set pass^3 | `tests/benchmark/queries_v0.jsonl` ×3 | ≥%80 L1–L7, L8 ≥%60 | Genel — seed üzerinde koşabilen 11 sorgu E-BENCH'te; kalan 25 data ekibinin serilerini bekliyor |
| E-BENCH | V3 motoru ekip motoruna göre pass^3'ü düşürmeden daha az tur/süre | `scripts/run_benchmark.py --engine team --engine v3 --set all --repeat 3`: golden 7 + seed alt-kümesi 11 = 18 vaka, aynı DuckDB, aynı durum kontrolleri | pass^3 eşit veya yüksek; tur ve süre düşük | **SONUÇ (10 Eylül, 2. oturum) `[EMP]`** — `docs/experiments/benchmark_all_2026-09-10_r3.md` (ekip) ve `_r3_v3fix.md` (V3, döngü kilidi sonrası): **ekip 17/18 vaka (51/54 koşu), 5,7 s, 5,6 LLM turu, 4,8 araç adımı · V3 17/18 (51/54), 4,1 s, 3,2 tur, 1,6 adım, grounding temiz 41/45.** İki motorda da düşen tek vaka L10-01 (belirsiz soru; `clarify` aracı yok). V3'ün ilk r3'ünde L4-01 0/3'tü: model aynı sorguyu 7 kez tekrarlayıp tur limitini yaktı (sonuç özeti 12 satırın 10'unu gösteriyordu) → `DUPLICATE_CALL` döngü kilidi + ≤24 satır tam özet; sonrası 3/3, 4 tur. G5'te grounding guard kafadan hesaplanan farkları yakalayıp modeli `workspace_compute_column`'a yönlendirdi (+2 tur, doğrulanmış anlatım); ekip motorunda anlatı doğrulanmıyor. Hata kodu dağılımı V3: `MISSING_PERIOD_FILTER×6, OUT_OF_COVERAGE×3, EMPTY_DATASET×3` — hepsi tasarlanmış ret, hiçbiri araç istisnası değil. Sınır: 18 vaka tek tablo (BDDK Tablo 3–4) üzerinde; çok serili/dış kanıtlı sorular (L5, L7, L12) henüz koşulamıyor. **Tekrar (11 Eylül) `[EMP]`** — ekip motoru ADR-0024/0025 (zarf + döngü kilidi + Silver adaptörü) sonrası, iki şema: seed **ekip 14/18 · 9,5 s · 5,7 tur — V3 17/18 · 7,9 s (G5'te 103 s'lik tek bozuk koşu; sonrasında `max_tokens=700`) · 3,1 tur**; Silver (data ekibi şeması, `dev_seed_silver.py`) **ekip 13/18 · 8,4 s · `SQL_FAILED×21` — V3 16/18 · 3,7 s · 2,9 tur · grounding 45/45**. V3'ün Silver'da düştüğü G3: LAG çapası için 13. satır (Aralık 2024) — golden 12 istiyor. Ayrıntı ve karşı motorun düşme nedenleri: `docs/calisma-notlari/BENCHMARK_PROTOCOL.md §3` |
| E10 | Çıktı token bütçesi (≤150) doğruluğu düşürmüyor | anlatım uzunluğu 150 vs 400; jüri rubriği | fark yok | 3.5 |

E1–E3 `scripts/mia_probe.py` ile bugün koşulabilir; E4–E10 harness'a bağlı.

---

## 6. Mevcut koddan V3'e geçiş (delta)

| Bileşen | Durum | İş |
|---|---|---|
| ReAct döngüsü (`core/agent.py`) | Korunur | Tur içinde birden çok `tool_calls` → executor'a liste; gözlemleri özetle döndür; tur/onarım sayaçları; effort yükseltme |
| Executor | Yeni | Thread pool; araç başına timeout; DuckDB bağlantısı iş parçacığı başına |
| Boundary validator | Yeni (5 guard genişler) | Referans + politika katmanı; yapılandırılmış hata |
| Grounding guard | Yeni (cevap guard'ı genişler) | Sayı çıkarımı + ledger eşleşmesi + nedensellik filtresi |
| Kompozit araçlar | Yeni | `fetch_aligned`, `compare_series`, `evidence_lookup` |
| 5 araç ailesi | Yeni | search/URL/anomali/causality/changepoint |
| `SearchProvider` | Yeni | Tavily + Firecrawl + cache |
| Ledger + trace | Genişler | Kolon soyağacı, `vintage_id`, tur görünümü |
| Domain plugin | R'nin DomainProfile'ı üstüne | Arayüz + finans plugin'i |
| Katalog özeti / bütçe | Yeni | Token sayımı; eşik aşımında `search_series` modu |

Harness'ın omurgası değişmediği için golden set (7/7) regresyon testi olarak ilk günden koşabilir.

**Uygulama (10 Eylül, 2. oturum, `feature/busra/agent-v3`).** V3 motoru ekip motoruna dokunmadan **paralel paket** olarak yazıldı: `agent-core/src/kkb_agent_v3/`. Paylaşılan (değiştirilmeyen): `kkb_agent.contracts/*`, `adapters/duckdb_lakehouse.py`, `core/workspace.py`, `domain.DomainProfile`, `tools/workspace.py` (V3 zarfına sarılır), `tests/golden/cases.py`, dev seed verisi. Bize ait: döngü (`core/agent.py`), araç sözleşmesi + sınır doğrulayıcı (`core/tool.py`, `core/validator.py`), hata zarfı (`errors.py`), katalog bağlamı (`core/context.py`), grounding (`core/grounding.py`), LLM istemcisi alt sınıfı (`llm.py`), lakehouse araçları (`tools/lakehouse.py`), domain markdown (`domain/`). İki motor `scripts/run_benchmark.py --engine team --engine v3` ile aynı DuckDB üstünde, aynı golden kontrolleriyle karşılaştırılır. LLM'siz testler: `tests/v3/` (34), ekip testleri değişmeden geçer (49).

| Bileşen | Durum (10 Eylül, 2. oturum) | Not |
|---|---|---|
| Batched ReAct + paralel executor | **Var** | Blok C bayrakları varsayılan açık (`AgentConfig`) |
| Boundary validator (şema → SQL guard → referans → politika) | **Var** | `SERIES_NOT_FOUND / COLUMN_NOT_FOUND / OUT_OF_COVERAGE / MISSING_PERIOD_FILTER / UNSAFE_SQL / EMPTY_DATASET / DOUBLE_COUNT` (SUM var, `is_alt_toplam` filtresi ve kalem eşitliği yok → reddet; benchmark r3'ten SONRA eklendi, r3 sonuçlarına dahil değil) |
| Grounding guard (sayı + nedensellik dili) | **Var** | `enforce` varsayılan; bir kez yeniden üretim |
| Güvenli başarısızlık | **Var** | `retryable=false` → araçsız cevap turu |
| Reasoning yükseltme | **Var** | 2. ardışık hatada `low` |
| Katalog bütçesi (E8) | **Var** | ≤6k token tam; üstünde tablo dizini + keşif araçları |
| Domain markdown + bütçeli lookup | **Var** | `finance.md` 418 token → gömülü |
| Kompozit araçlar, 5 yeni araç ailesi, SearchProvider, ingest, replay cache, JSONL trace | **Yok** | Sıradaki iş; benchmark önce |

---

## 7. Kısa ADR eki (V2'den farklılaşanlar)

- **ADR-11 Plan DSL yerine tur-içi paralel çağrı.** Kanıt: LLMCompiler/ReWOO hız ve token kazanımı; R'nin 7/7 kararlılığı; native tool calling `[EMP]`. Trade-off: plan önceden görünmez; trace ile telafi. Geri dönüş koşulu: E1 başarısız olursa (tek çağrı/tur) kompozit araçlar tur sayısını yine düşürür; Plan DSL'e dönülmez.
- **ADR-12 Placeholder narration yerine grounding guard.** Kanıt: ekibin ölçümünde çıktı token'ı pahalı; placeholder şablonu ikinci tur gerektiriyordu. Trade-off: guard yanlış pozitif riski → E5.
- **ADR-13 Tek hata zarfı (`ToolError`), serbest "HATA: ..." metni yerine.** (10 Eylül, 2. oturum) Kanıt: WrenAI aynı kalıbı kullanıyor `[SRC]`; data ekibi sözleşmesi §18 zaten kod+hint tanımlıyor; ekip harness'ında retry kararı modele bırakılıyordu. Karar: kod başına varsayılan `retryable`, `retryable=false` → araçsız cevap turu; `needs_user_input` eklendi, `replan_possible` düşürüldü. Trade-off: ekip workspace araçları sarılarak (metin→kod eşlemesi) kullanılıyor; eşleme kırılgan, yeni araçlar doğrudan zarfı döndürmeli.
- **ADR-14 Domain bilgisi YAML değil markdown; makine/model bölümleri ayrı; lookup yalnız bütçe üstünde.** (10 Eylül, 2. oturum) Kanıt: Text2SqlAgent scenarios.md `[SRC]`; maliyet modeli `[EMP]` (araç turu ≈ 7k token prefill); MIA system-talimat uyumu 7/10 `[EMP]`. Karar: `measure_rules`/`evidence_domains` kod okur, `note:`/`template:` bütçeye göre gömülü veya `lookup_domain_note`; alias'lar katalogda. Geri dönüş: E11 lookup'ın kazandırdığını gösterirse bütçe düşürülür.
- **ADR-15 Paralel motor, paylaşılan veri katmanı.** (10 Eylül, 2. oturum) Ekip motoru ve V3 aynı repoda ayrı dallarda, aynı `LakehouseClient`/katalog/golden set üstünde; `run_benchmark.py` ile karşılaştırılır. Kanıt: brief'in "ölçmeden değiştirme" kuralı; 10 günde iki motor riski kabul edildi — benchmark koşulmazsa bu ADR geçersizdir. Sınır: `kkb_agent/` paketi, `contracts/`, `adapters/`, `tests/golden/`, `docs/adr/` değiştirilmez.
- **ADR-13 Araç turlarında thinking kapalı.** Kanıt: vLLM parser davranışı `[SRC]`; Ares yükseltme stratejisi `[SRC]`.
- **ADR-14 Retrieval eşiği token bazlı.** Kanıt: prefill maliyeti ölçüldü `[EMP]`; "100 seri" eşiği yerine katalog özeti token bütçesi.
- **ADR-15 Retrieval motoru: alias + BM25 P0, embedding opsiyonel P1.** Kanıt: bake-off `[EMP]` — BM25 ve Qwen3-Embedding R@3'te eşit (0.96), hybrid +2 puan (eşik 3); BM25 2 ms ve MIA'sız, dense 28 ms + ağ çağrısı. Asıl belirleyici alias kalitesi: alias-exact tek başına 0.64, "natural" paraphrase sorgularda 0/10. Karar: `search_series` = normalize + alias + BM25 (Türkçe karakter katlama; stemmer sonraki adım); embedding yalnızca gerçek katalogda BM25 R@3 < 0.90 çıkarsa eklenir. Alias üretimi onboarding'de LLM önerisi + onay (`derived`).
