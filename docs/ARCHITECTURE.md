# Agentic Analytics Engine — Mimari

> **Güncel özet:** Jüriye yönelik güncel anlatım [01-genel-mimari](01-genel-mimari.md), [02-moduler-kod-yapisi](02-moduler-kod-yapisi.md),
> [03-agent-karar-ve-gorev-isleme](03-agent-karar-ve-gorev-isleme.md) ve [04-dokuman-okuma](04-dokuman-okuma.md) belgelerindedir. Bu belge
> ayrıntılı tarihçeli başvuru olarak korunur.
>
> **Durum:** 22 Eylül 2026 · 856 ajan birim testi + ~1.150 lakehouse testi (CI'da) · 80+ ADR · 6.306 seri (2021-01 → 2026-06) canlı yüklü ·
> tamamlanma sözleşmesi ve arama defteri (`core/completion.py`, `core/search_ledger.py`, 22 Eyl) ·
> birleşik kabul: [M16_KABUL_RAPORU.md](calisma-notlari/M16_KABUL_RAPORU.md). §1 çizimindeki "planlı" etiketleri 10 Eylül tarihlidir;
> güncel araç ve katmanlar §15 sonrasındaki "YAZILDI" bölümlerinde ve §14–15'tedir.
> Bu belge kodun *ne yaptığını* değil, *neden öyle yapıldığını* anlatır; her karar
> `docs/adr/` altındaki kayda atıfla gelir. Kodla birebir örtüşmesi için modül, sınıf ve
> metot adları gerçek adlarıyla verilmiştir.

---

## 0. Beş tasarım ilkesi

Bütün mimari bu beş cümleden türer. Bir tasarım tartışmasında hangi seçeneğin doğru olduğu,
bu ilkelerden hangisini koruduğuna bakılarak karara bağlanır.

| # | İlke | Kodda karşılığı |
|---|---|---|
| 1 | **Harness güçlü, model az düşünür.** Model hesap yapmaz, ham veri görmez, kategori uydurmaz, hatasını yutmaz. | `Tool.validate_and_run`, `AnalysisWorkspace`, kapsam/dönem kontrolleri |
| 2 | **Her şey bir araçtır — agent dahil.** Harness için atomik bir fonksiyon ile izole bir alt-agent aynı arayüze sahiptir. | `Tool` taban sınıfı, `SubAgentTool` (planlı) |
| 3 | **Alan bilgisi koddan değil katalogdan gelir.** Motor hiçbir alan terimi içermez; profil katalogdan türer. | `DomainProfile.from_catalog`, `tests/test_domain_profile.py` |
| 4 | **Yazma tek sahiplidir.** Analiz tablosunu yalnız ana agent değiştirir. | `AnalysisWorkspace` tek örnek, alt-agent'lar kendi workspace'ini kullanır |
| 5 | **Ölçülmeyen değişiklik yapılmaz.** Her davranış değişikliği golden set + kararlılık ölçümünden geçer. | `scripts/run_golden.py --repeat`, ADR-0008, ADR-0011 |

İlke 1'in kaynağı açılış toplantısındaki yönlendirmedir: *"harness yapısını daha güçlü
yapın, LLM'e en az işi bırakın."* İlke 3 şartnamenin *"içi boşaltılıp bambaşka bir sağlık
verisiyle çalışabilmeli"* maddesinden gelir.

---

## 1. Kuşbakışı

```
 kullanıcı (canlı jüri)
    │  doğal dil soru
    ▼
┌──────────────────────────────────────────────────────────────────┐
│ RETRIEVAL KATMANI  (planlı — ADR-0013)                LLM YOK    │
│ BM25 + embedding → ilgili tablolar, aday kalemler, kapsam        │
│ güven eşiği: ├─ yüksek → HIZLI YOL (bağlam enjekte, doğrudan SQL)│
│              └─ düşük  → ReAct (araçlar açık)                    │
└──────────────────────────────┬───────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ AnalyticsAgent  (core/agent.py)          tek iş parçacığı        │
│  · DomainProfile ile doldurulmuş system prompt                   │
│  · ToolRegistry'den araç şemaları                                │
│  · AnalysisWorkspace'in tek sahibi                               │
│  · döngü: mesajları kur → LLM → çağrıları ayrıştır → çalıştır    │
│           → guard'lar → tekrar / cevap                            │
└──────────────────────────────┬───────────────────────────────────┘
                               │ ToolRegistry (core/registry.py)
    ┌──────────┬───────────────┼──────────────┬───────────────┬────────────┐
    ▼          ▼               ▼              ▼               ▼            ▼
 lakehouse  workspace      analytics       web            vision       ingest
 (4 araç)   (3 araç)       (3, planlı)     (2, planlı)    (1, planlı)  (SubAgent,
    │          │            LLM YOK          │               │          planlı)
    ▼          ▼            pandas/          ▼               ▼            │
┌────────┐ ┌──────────┐    statsmodels   arama API    Qwen3.8 vision      ▼
│Lakehouse│ │Analysis  │                                            ┌──────────┐
│Client   │ │Workspace │                                            │ iç agent │
│(Protocol)│ │          │                                            │ fetch→OCR│
└────┬────┘ └──────────┘                                            │ →parse   │
     │                                                              │ →katalog │
     ▼                                                              └────┬─────┘
 DuckDBLakehouse (referans)  ◄──── veri ekibinin adaptörü ────────────────┘
                                   (aynı Protocol, sıfır kod değişikliği)
```

**Üç dış sağlayıcı katmanı birbirinden ayrıdır** (mentör kararı, 10 Eylül):

```
 LLM (MIA)            Search (Tavily/Firecrawl/…)     Retrieval (BM25 · embedding · reranker)
 llm/LLMClient        contracts/SearchClient           contracts/{Embedder, LexicalIndex, Reranker}
      │                       │                                  │
      └───────────────────────┴──────────────────────────────────┘
                              agent yalnız Protocol'leri görür; sağlayıcı .env'de
```

Ana LLM MIA olarak kalır; arama ve sıralama bileşenleri ayrı katmanda, değiştirilebilir.
Servis veya yöntem değişse de ana yapı değişmez.

Bağımlılık yönü tek taraflıdır ve içeriden dışarıya doğrudur:

```
contracts ◄── core ◄── tools ◄── cli
    ▲           ▲
    │           └── llm
    └── adapters, domain, (search, retrieval uygulamaları)
```

`contracts/` hiçbir şeye bağımlı değildir; `core/` yalnız `contracts/`, `llm/` ve
`domain/`'e; `tools/` yalnız `core/` ve `contracts/`'a. Bir aracı silmek hiçbir şeyi kırmaz;
`core/`'u değiştirmeden yeni araç eklenebilir.

---

## 2. Sözleşmeler — `contracts/`

Jeneriklik burada başlar. Motor, veriyi **nasıl** saklandığını değil, **nasıl sorulacağını**
bilir.

### 2.1 `LakehouseClient` (Protocol)

```python
class LakehouseClient(Protocol):
    def list_datasets(self) -> list[DatasetSpec]
    def get_dataset(self, dataset_id: str) -> DatasetSpec
    def search_datasets(self, query: str, limit: int = 5) -> list[DatasetSpec]
    def execute_sql(self, sql: str, *, max_rows: int = 10_000) -> QueryResult
    def preview(self, dataset_id: str, n: int = 5) -> QueryResult
    def health(self) -> dict[str, Any]
```

**Neden `Protocol`, `ABC` değil:** Yapısal tipleme. Veri ekibi bizim paketimizi import
etmeden, aynı imzalara sahip bir sınıf yazarak sözleşmeyi karşılar. İki ekip birbirinin
koduna bağımlı olmadan paralel çalışır (ADR-0002).

**`execute_sql` şartları:** Salt okunur. DDL/DML, çoklu ifade, dış dosya erişimi
(`read_csv`, `read_parquet`, `glob`) reddedilir. Bu şart veri ekibinin adaptöründe
sertleştirilmiş bağlantıyla (`access_mode=read_only`, `enable_external_access=false`,
`lock_configuration=true`) desteklenir; SQL guard tek bariyer değildir.

### 2.2 `DatasetSpec` / `ColumnSpec` — Semantic Catalog

Ham şema (tablo + kolon adı) bir dil modeli için yetersizdir. Her veri seti kendini
`DatasetSpec` ile tanıtır:

```
DatasetSpec
  dataset_id, name, description          ← agent tablo seçimini description'dan yapar
  source, source_url, source_detail      ← provenance
  frequency, time_column, grain          ← hizalama ve join
  columns: list[ColumnSpec]
  coverage: Coverage(start, end)         ← kapsam dışı soruya "veri yok" diyebilmek için
  tags, notes, last_refreshed

ColumnSpec
  name, role (TIME | DIMENSION | MEASURE | METADATA), dtype, description
  semantic_type (stock | flow | rate | index | ratio | count)  ← frekans dönüşüm kuralı
  cumulative (none | ytd | since_inception)                    ← BDDK'nın iki rejimi
  unit, unit_multiplier                                        ← "bin TL" vs "milyon TL"
  aliases: list[str]                                           ← "mortgage", "ev kredisi"
  example_values
```

**Kritik dört alan ve neden:** `semantic_type` yanlışsa aylık→çeyreklik dönüşüm sessizce
yanlış çıkar (stok toplanmaz, akım son değeriyle alınmaz). `cumulative` BDDK slaytındaki
uyarının karşılığıdır. `unit_multiplier` varsayım değil ölçümdür: BDDK aynı bültende
Tablo 3/4 "milyon TL", Tablo 5 "bin TL" yayınlar. `aliases` agent'ın kalem seçimindeki
isabetini en çok etkileyen alandır (ADR-0003).

`DatasetSpec.to_prompt_card()` kataloğu modele verilecek kompakt metne çevirir. Kataloğun
tamamı asla prompt'a konmaz — ölçüldü: 1 tablo ≈ 1.500 token, 25 tabloda pencere dolar.

### 2.3 `QueryResult` / `QueryProvenance`

Her sorgu sonucu veriyle birlikte **nereden geldiğini** taşır: çalıştırılan SQL, kaynak
tablo kimlikleri, kaynak kurum ve URL, satır sayısı, süre, uyarılar. Şartnamedeki
*"Güven katmanı: Kaynak gösterimi – İzlenebilirlik – Doğruluk Kontrolü"* maddesinin kod
karşılığı. Veri ekibinin `meta.artifact` (SHA-256, vintage) tablosuyla birleştiğinde
"bu rakam hangi indirmeden geldi" sorusu ham dosyaya kadar izlenebilir olur.

---

## 3. Alan profili — `domain.py`

**Problem:** Modele giden metinler (system prompt, araç şemalarının `description`
alanları) finansa çakılıydı. Bunlar yorum değil, her turda prompt'a giren içerik.

**Çözüm:** `DomainProfile` — yedi alan (`domain`, `audience`, `example_table`,
`example_time_column`, `example_category_column`, `example_measure`, `example_entity`).
Bütün metinler `{domain}`, `{example_measure}` gibi yer tutucularla yazılır;
`ToolRegistry` şema üretirken `profile.render()` ile doldurur.

**Profil nereden gelir:** `DomainProfile.from_catalog(datasets)` — **deterministik**.
Kaynak adları alanı, en zengin tablonun kolon rolleri örnekleri verir. Yeni bir veri seti
yüklendiğinde profil kendiliğinden ona uyar. Üslup tercihleri (`DOMAIN_DESCRIPTION`,
`DOMAIN_AUDIENCE`) `.env`'den geçilebilir.

**Neden modelle tahmin edilmiyor:** EMNLP 2024 Findings (4 model ailesi, 2.410 soru,
162 rol) — system prompt'a persona eklemek performansı iyileştirmiyor ve "en iyi rolü
seçme" rastgele seçmekten iyi değil. Ölçülebilir kazanç rolde değil, veri bağlamında
(ADR-0012).

**Ölçülmüş bir tuzak:** `example_entity` kanonik tam ad olarak türetildiğinde
("Tüketici Kredileri - Konut") model bunu `contains` filtresine birebir yazdı, golden
5/7'den 1/7'ye düştü. `kisa_terim()` bunu kısa arama terimine indirger ("Konut").
Örneğin gerçek olması yetmez, iyi olması gerekir.

**Kanıt:** `tests/test_domain_profile.py` aynı motoru bir sağlık kataloğuyla kurar;
araç şemalarında `hastane_basvurulari`, `basvuru_sayisi`, `Kardiyoloji` görünür, hiçbir
finans terimi görünmez. Ayrı bir test nötr profilde motorun tamamını tarar — kod
tabanına yeniden alan terimi sızarsa yakalanır.

---

## 4. LLM katmanı — `llm/`

`LLMClient` (Protocol): `chat(messages, tools, temperature, max_tokens) -> LLMResponse`
ve `supports_native_tools() -> bool`.

Tek uygulama: `OpenAICompatClient`. Ollama (geliştirme) ve MIA/Kloudeks (demo) aynı
protokolü konuştuğu için kod değişmez, yalnız `.env` değişir:

```
LLM_BASE_URL=https://mia.csp.kloudeks.com/v1
LLM_MODEL=deepseek-ai/DeepSeek-V4.1-Flash   # ADR-0103; önceki: kkbhackathon2026/Qwen3.8-27B
```

**`reasoning_effort: "none"`** varsayılan olarak gönderilir (`LLM_DISABLE_THINKING`).
Ölçüm: "merhaba" yazdırmak için 162 token / 12,7 s → 4 token / 0,5 s. Araç seçimi gibi
kısa kararlarda düşünce zinciri yalnız gecikme üretiyordu (ADR-0005). Planlı iyileştirme:
nihai sentez turunda reasoning'i **açmak** — orada kalite hıza değer.

**Native tool-calling yoksa:** harness JSON-protokol moduna düşer; system prompt'a araç
kataloğu eklenir, model `{"tool": ..., "args": ...}` döndürür, `_parse_json_call`
ayrıştırır. MIA'da native tool-calling **çalıştığı ölçüldü** (10 Eylül); fallback
yalnız sağlayıcı değişirse devreye girer.

`ToolCall.from_openai` bozuk JSON'u yakalar ve `{"__raw__": ...}` olarak taşır;
onarım döngüsü devreye girer.

---

## 4b. Search katmanı — `contracts/search.py`

`SearchClient` (Protocol): `search(query, max_results) -> list[SearchHit]` ve
`fetch(url, max_chars) -> PageContent`. `web_search` ve `web_url` araçları bu sözleşmeye
karşı yazılır; Tavily, Firecrawl ya da DuckDuckGo arkada değişebilir, araç kodu değişmez.
`PageContent` ham HTML değil temizlenmiş metin + ayıklanmış tablolar taşır; PDF/görsel
OCR'ı bu katmanın değil vision katmanının işidir.

Mentör netleştirmesi: web search/scraping servisleri serbest; kısıt yalnız cloud
warehouse'larda (Snowflake, BigQuery). Bu katman o sınırın dışında.

## 5. Çekirdek — `core/`

### 5.1 `Tool` — tek soyutlama

```python
class Tool(ABC):
    name: str
    description: str          # {placeholder} içerebilir
    Params: type[BaseModel]   # Pydantic modeli
    def run(self, params) -> ToolResult
```

Üç işi vardır:

- **`openai_schema(profile)`** — Pydantic modelinden OpenAI function-calling şemasını
  üretir, `description` alanlarını profille doldurur. Elle JSON şema yazılmaz; parametre
  modeli değişince şema kendiliğinden güncellenir.
- **`validate_and_run(raw_args)`** — LLM'in ürettiği argümanları Pydantic ile doğrular.
  Doğrulama hatası **istisna değil, `ToolResult.error(...)`** olarak döner ve modele
  okunabilir biçimde geri verilir. Harness'ın onarım döngüsü budur: model hatayı okur,
  çağrıyı düzeltir.
- **`ToolResult`** — `content` (modele giden KISA metin), `ok`, `data` (DataFrame,
  workspace'e gider, modele gitmez), `provenance`, `artifacts`.

**Neden `content` kısa olmalı:** Her turda konuşmanın tamamı yeniden gönderilir. Bir
aracın döndürdüğü uzun metin, kalan her turda tekrar ödenir. Ölçüldü: 50 kalemlik
`distinct_values` çıktısı sonrası model sorgu yazmadan cevaba geçti (ADR-0019).

### 5.2 `ToolRegistry`

Araçların kayıt defteri. `register`, `schemas(profile)`, `describe()` (JSON modu için),
`execute(name, args)`. İki ek durum taşır: `profile` (şema render'ı için) ve
`active_question` (bazı araçlar sonucu soruyla karşılaştırır — atlanan dönem filtresi).

**Planlı:** `Tool.group` alanı ve `subset(groups)` — alt-agent'a daraltılmış kayıt
defteri, ileride tool retrieval.

### 5.2b `BoundaryValidator` — her araç çağrısı aynı boru hattından

`core/validator.py`. Sıra: **şema → SQL guard → referans → politika → run** (ADR-0029).
Araç yalnız `validate_refs` ve `check_policy` hook'larını yazar; sırayı ve hataya
sarmayı doğrulayıcı bilir. `sql` alanı taşıyan her araç guard'dan geçer — araçtan
bağımsız, adaptörün kendi guard'ına ek (savunma derinliği, ADR-0020).

Mentörün sorduğu dört rol burada **rol** olarak tutuluyor, agent olarak değil:

| rol | nerede |
|---|---|
| Planner | LLM'in kendisi; hangi aracı seçtiği izdeki adım sırasında okunur |
| Retriever | `lakehouse_search / describe / distinct_values` (`Tool.role = "retrieve"`) |
| Validator | `core/validator.py` + döngüdeki guard'lar; izde `[validate]` |
| Narrator | son tur; anlatı doğrulama ve nedensellik filtresinden geçer; izde `[narrate]` |

### 5.3 `AnalysisWorkspace` — konuşma boyunca yaşayan tablo

Örnek senaryo: *"tabloyu göster → tabloyu bozmadan enflasyondan arındır → bu tabloyu hiç
bozmadan yeni sütun ekle."* Her soruda sıfırdan sorgu üreten agent burada başarısız olur.

```
set_table(df, description, provenance)      yeni analiz başlatır
add_column(name, values, join_on, ...)      mevcut tabloyu BOZMADAN sütun ekler
replace_column(name, values, keep_original_as)  dönüştürür, orijinali korur
revert()                                    son işlemi geri alır
column_provenance(col)                      "bu sütun nereden geldi?"
describe_for_llm(max_rows=5)                modele giden özet — tablonun tamamı değil
```

Her işlem `WorkspaceStep` olarak geçmişe kaydedilir (`order, action, description,
provenance, columns_added`). Snapshot'lar `revert` için tutulur (son 20).

**Kasıtlı kısıt:** Modele açılan araçlar tabloyu **yeniden kuramaz**, yalnız üstüne
ekleyebilir. "Tabloyu bozmadan" garantisi prompt'a değil, aracın imkânlarına yazılıdır
(ADR-0006).

### 5.4 `AnalyticsAgent` — harness döngüsü

`ask(question)` adım adım:

```
 1. registry.active_question = question
 2. _build_messages():
      system prompt (profile.render) 
      + son 8 tur geçmiş
      + workspace varsa: describe_for_llm() → "MEVCUT ANALİZ DURUMU"
      + user: soru
 3. for i in 1..max_steps:
      response = llm.chat(messages, tools=registry.schemas())
      calls = native ? response.tool_calls : _parse_json_call(content)

      if not calls:                         ← model cevap vermek istiyor
          if not produced_data and not nudged:
              nudged = True
              "Henüz veri çekmedin" → geri gönder, continue   ← CEVAP GUARD'I
          if produced_data:
              grounding_check(soru, cevap, araç çıktıları)     ← ANLATI GUARD'I
              MISS ya da nedensellik → bir kez geri gönder
              ikinci kez de MISS → cevap gider, değerler işaretlenir
          return AgentAnswer(_strip_reasoning(content))

      for call in calls:
          if (call.name, args) daha önce görüldüyse:
              DUPLICATE_CALL; ikinci tekrarda araçlar geri alınır  ← DÖNGÜ KİLİDİ
          result = registry.execute(call.name, call.arguments)
          if result.ok and call.name in DATA_PRODUCING_TOOLS:
              produced_data = True
          messages.append(tool mesajı: result.content)     ← data DEĞİL, content
          steps.append(AgentStep(...))                       ← izlenebilirlik

      if terminal hata (retryable değil):
          araçsız son tur: "durumu açıkla, sayı uydurma"     ← ÇIKMAZ GUARD'I

 4. max_steps aşıldı:
      "Elindekiyle en iyi cevabı ver, neyi tamamlayamadığını söyle" → son tur
```

Yedi guard, hepsi ölçülmüş bir hata moduna karşılık:

| Guard | Hata modu | ADR |
|---|---|---|
| Cevap guard'ı (`produced_data`) | Model katalogu okuyup veri çekmeden cevap yazıyordu | 0010 |
| `DATA_PRODUCING_TOOLS` araç adına göre | İlk sürüm DataFrame varlığına bakıyordu; `describe` de DataFrame döndürüyor, guard hiç tetiklenmedi | 0010 |
| Anlatı guard'ı (`grounding_check`) | Tablo doğru, anlatıda tabloda olmayan sayı: "155.515 milyon TL arttı" | 0027 |
| Nedensellik filtresi | "faiz indirimi buna yol açtı" — veriden çıkarılamaz | 0027 |
| Döngü kilidi + kırılması | Aynı çağrı tekrar tekrar; kilit aracı korudu ama model yedi kez daha istedi ve adım limitini yaktı | 0025 |
| Çıkmaz guard'ı (araçsız son tur) | Tekrar denemeyle çözülmeyen hatada model aynı yolu farklı yazımlarla deniyordu | 0017, 0025 |
| `max_steps` + son tur | Sessiz kesilme yerine "neyi tamamlayamadım" | — |
| `_strip_reasoning` | Qwen3/DeepSeek `<think>` blokları kullanıcıya sızmasın | — |

`AgentAnswer` cevap metni + `steps` (trace) + `workspace` + `hit_step_limit` +
`grounding` taşır.
Trace yalnız hata ayıklama için değil; demoda "bu sonuca nasıl vardın?" sorusunun cevabı.

---

## 6. Mevcut araçlar — `tools/`

Her araç bağımsız bir sınıf; `cli.build_agent()` içinde `registry.register_all([...])`.
Yeni yetenek = yeni sınıf + bir satır kayıt. Agent kodu değişmez.

### Lakehouse ailesi — `tools/lakehouse.py`

Şartname bunu tek "Lakehouse Tool" sayar; dört tek-amaçlı araca bölündü. Sebep ölçülmüş:
dar parametreli araçlarda küçük modelin isabeti belirgin yüksek. System prompt sırayı
dayatır: **search → describe → distinct_values → query**.

| Araç | Ne yapar | Harness kuralı |
|---|---|---|
| `lakehouse_search(query)` | Katalogda tablo arar, kartları döndürür | — |
| `lakehouse_describe(dataset_id)` | Kolonlar, birimler, kapsam + 5 örnek satır | SQL yazmadan önce zorunlu |
| `lakehouse_distinct_values(dataset_id, column, contains?, limit=20)` | Kırılım kolonundaki gerçek değerler, alt toplamlar ⚠ işaretli | Filtresiz çağrıda >15 değer varsa tam liste değil, daraltma yönergesi (ADR-0019) |
| `lakehouse_query(sql, purpose, as_active_table=True)` | SQL çalıştırır, sonucu workspace'e yazar | Aşağıda |

`lakehouse_query`'nin üç kontrolü, üçü de yapısal abstention:

1. **Dönem filtresi reddi** — soruda yıl geçiyor, SQL'de geçmiyorsa sorgu çalışmadan
   reddedilir. Uyarı olarak denendi: 0/2. Ret: 2/2 kararlı (ADR-0017).
2. **Kapsam kontrolü** — sorgu boş döndüyse ve sorgudaki yıllar katalog kapsamının
   dışındaysa kesin dille "bu veri yok, tekrar deneme" (ADR-0010). Mesaj modele ne
   *yapacağını* değil ne *söyleyeceğini* verir — ilk sürümde model uyarıyı "SQL hatası"
   sanıp kullanıcıya hata ayıklama tavsiyesi yazmıştı.
3. **Birim etiketi** — sonuca `Birimler: toplam = milyon TL` eklenir; model çeviri yapmaz.

Modele dönen içerik: sütunlar + ilk 10 satır + birimler + kaynak özeti. 4.002 satırlık
sonuç workspace'e gider, modele 10 satır.

### Workspace ailesi — `tools/workspace.py`

| Araç | Ne yapar |
|---|---|
| `workspace_add_column(dataset_id, key_column, value_column, column_name, join_on, filter_column?, filter_value?, purpose)` | Lakehouse'tan bir ölçümü çekip mevcut tabloya hizalar |
| `workspace_compute_column(expression, column_name, purpose)` | Mevcut sütunlardan DuckDB ifadesiyle yeni sütun hesaplar |
| `workspace_show(max_rows)` | Tablonun güncel hali + işlem geçmişi |
| `workspace_query(sql, purpose, as_active_table=false)` — `tools/workspace_query.py` (ADR-0039) | Aktif tablo `t` üzerinde SELECT, sertleştirilmiş bellek-içi DuckDB; veri havuzuna dokunmaz. Varsayılan bakış modu (tablo değişmez, sonuç kanıt için not edilir); `as_active_table=true` kırpma |

**`add_column` neden SQL almıyor:** Serbest SQL alan sürümde model, eklemek istediği yeni
sütunun adını SELECT listesine var olan kolon gibi yazdı, hatadan çıkamadı ve
`lakehouse_query`'ye kaçıp tabloyu yeniden kurdu — aracın var oluş sebebi çöktü. Artık
yapılandırılmış parametreler alır, kolon adları katalogla doğrulanır; model var olmayan
kolon uyduramaz (ADR-0016). Semantic layer literatürünün küçük ölçekli uygulaması.

`compute_column` ifadeyi `SELECT (<expr>) FROM analiz` olarak DuckDB'de çalıştırır;
veri değiştiren/dosya okuyan ifadeler regex ile reddedilir; satır sayısını değiştiren
ifade reddedilir.

---

## 7. Araç aileleri (analitik yazıldı; web, grafik, ingest aşağıda ve §15'te)

### Analitik ailesi — `tools/analytics.py` + `analytics/methods.py` (LLM YOK, ADR-0040) — YAZILDI

Yarışmanın asgari araç listesindeki üç ad (Anomali, Change Detection, Causality). Literatürün
tutarlı bulgusu ve bizim ölçümümüz (ADR-0027): model sayısal girdi üzerinde kendi aritmetiğini
yapınca uydurur. İstatistik tespit eder, model kartı anlatır.

| Araç | Yöntem | Döner |
|---|---|---|
| `anomaly_detect(column, method=iqr|zscore, basis=auto|level|change)` | Tukey çiti (k=1.5) ya da z-skoru (|z|>3); trendli seride (Spearman rho ≥ 0.8) dönemlik yüzde değişim üzerinde | `<sütun>_anomali` ('ok'/'aykırı'), `<sütun>_skor` (+ `_degisim_yuzde`); kartta aykırı dönemler |
| `change_points(column, basis, max_breaks, min_size)` | ikili bölütleme, parçalı sabit ortalama, ceza 2·log(n)·σ² (σ birinci farkların MAD'ı) | `<sütun>_rejim` (1..k); kartta kırılma tarihleri ve rejim ortalamaları |
| `lead_lag(column_a, column_b, max_lag, basis)` | gecikmeli Pearson (−k..+k; +k: A önce) + iki yönlü Granger F-testi (OLS, scipy F) | tablo değişmez; kartta en güçlü gecikme, r, gecikme tablosu, Granger F/p/n |

Hepsi `AnalysisWorkspace.table` üzerinde; hangi veri olduğu umurlarında değil; sentetik seriyle
test edilir. Sonuç sütunları "türetilmiş:" provenance taşır (kanıt zinciri kopmaz), kart sayıları
kanıt paneli için not edilir. Grafik `_anomali` sütununu `quality_flag` gibi halka ile işaretler.
"Causality" dürüst: kart "öncülük, nedensellik değil" der; anlatı guard'ı "neden oldu" cümlesini
yine geri çevirir. Kullanıcı aykırılık/kırılma/öncülük sorup model aracı çağırmadan cevap yazarsa
harness bir kez geri gönderir (grafik kuralıyla aynı mekanizma).

### Web ailesi — `tools/web.py`

`web_search(query)` → başlık + özet listesi (dış servis politikası mentörde).
`web_url(url)` → sayfa metni / tablo. Paylaşılan durumu değiştirmez; ileride alt-agent
adayı.

### Görselleştirme — `tools/chart.py`

`render_chart(kind, x, y[], title, highlight_periods?)` → Vega-Lite spec (frontend
render eder) + PNG (yedek). Çizgi, çubuk, **çift eksen** (kredi + faiz), vurgulanmış
dönemler (anomali çıktısı). Workspace tablosundan beslenir, kaynak notu otomatik eklenir.

### Ingest — `tools/ingest.py` (`ingest_from_url`, ADR-0030) — YAZILDI, deterministik; LLM'li alt-agent hâli planlı

Jürinin sınayacağı yetenek: *"şu URL'den veriyi al, belgele, analiz et."*

```
ingest_from_url(url, hint?)
  iç agent (kendi registry'si: fetch, detect_format, ocr, parse_table,
            profile_columns, propose_spec, register_dataset; kendi workspace'i)
    1. fetch          → HTTP, zaman aşımı, hata → zarif mesaj
    2. detect_format  → CSV / Excel / PDF / HTML / görsel
    3. ocr            → PDF: sayfa→PNG→Unlimited-OCR (3 görsel/çağrı)
    4. parse_table    → DataFrame
    5. profile        → kolon rolleri (tarih tespiti, sayısal/kategorik), kapsam
    6. propose_spec   → LLM önerisi: description, aliases, measure_type, unit
                        → semantic_confidence = "derived"
    7. register       → lakehouse'a geçici tablo + katalog kaydı
    8. refresh        → ana agent katalogu yeniden görsün
  döner: "gold.adhoc_<ad> hazır — 12 satır, aylık, kolonlar: …; belge: <DatasetSpec>"
```

Ana agent için sıradan bir araç: çağırır, kısa özet alır. OCR'ın sayfalarca çıktısı ana
bağlama **hiç girmez**. Ürettiği `DatasetSpec` "yeni verinin belgesi" olarak kullanıcıya
gösterilir.

---

## 8. Alt-agent deseni — `SubAgentTool`

```python
class SubAgentTool(Tool):
    def __init__(self, llm, tools: list[Tool], profile, max_steps=8): ...
    def run(self, params) -> ToolResult:
        inner = AnalyticsAgent(self.llm, ToolRegistry(profile).register_all(tools),
                               workspace=AnalysisWorkspace(), max_steps=...)
        answer = inner.ask(self._compose_task(params))
        return ToolResult(content=self._summarize(answer), data=..., artifacts=...)
```

Üç garanti: **bağlam izolasyonu** (iç agent'ın `_history`'si dışarı çıkmaz),
**kendi workspace'i** (ana tabloya dokunmaz — İlke 4), **kısa dönüş** (`content` özet).

Bu, literatürün "çalışan tek multi-agent biçimi" dediği desen: birden çok agent zekâ
katar, yazma tek iş parçacığında kalır. Üstte bir orchestrator LLM turu **yok** — her
soruya ekstra tur maliyeti ve bugünkü sorunlarımızın yönlendirme sorunu olmaması sebebiyle
(ADR-0020, planlı).

---

## 9. Retrieval katmanı — `contracts/retrieval.py`

Üç bağımsız Protocol, üç bağımsız yetenek:

| Protocol | İş | Aday uygulamalar |
|---|---|---|
| `LexicalIndex` | BM25/FTS; kesin terimlerde güçlü | DuckDB FTS, `rank_bm25` |
| `Embedder` | metin → vektör, toplu | MIA `Qwen3-Embedding-8B` (4096), yerel sentence-transformer |
| `Reranker` | kısa listeyi soruya göre sırala | yerel cross-encoder, LLM-as-reranker |

`reciprocal_rank_fusion()` sıralamaları modelsiz birleştirir — "hibrit > saf semantik"
bulgusunun en ucuz uygulaması. Mentör kararıyla yerel yardımcı modeller serbest; ADR-0015'in
kural engeli kalktı, karar ölçümle verilir.

**Neden hâlâ öncelik değil:** MIA'da sorular 4–12 s; retrieval'ın kazandıracağı 3 tur artık
demo için belirleyici değil. Katalog büyüdüğünde (veri ekibi 4 → onlarca seri) ve
`ingest_from_url` yeni tablolar eklediğinde devreye girer. Sözleşme şimdi tanımlı ki o gün
agent'a dokunmadan eklensin.

**Bağlam ön-yükleme akışı (uygulandığında):**

```
soru → LexicalIndex + Embedder → RRF → (Reranker) → aday tablo/kalem, dönem, kapsam
     → güven yüksek: bağlam enjekte, LLM tek turda SQL     (hızlı yol)
     → güven düşük:  ReAct, araçlar açık
```

## 10. Adaptör — `adapters/duckdb_lakehouse.py`

`LakehouseClient`'ın referans uygulaması. `catalog.json` + DuckDB (read_only).
`search_datasets` anahtar kelime skorlaması (embedding gelince aynı imza, farklı iç).
`execute_sql` yasak ifade regex'i + `read_only=True`; veri ekibinin sertleştirilmiş
bağlantı doğrulaması (`_verify_untrusted_connection`) buraya alınacak.

Veri ekibinin adaptörü hazır olduğunda `cli.build_agent()` içinde tek satır değişir:
`DuckDBLakehouse(...)` → onların sınıfı. Agent kodu sıfır değişiklik.

---

## 11. Bir sorunun yolculuğu

*"2025 yılında konut kredisi bakiyesini aylık olarak göster."* — bugünkü akış:

```
 0. cli.build_agent()
      DuckDBLakehouse → katalog → DomainProfile.from_catalog
      → ToolRegistry(profile) → 7 araç → AnalyticsAgent
 1. ask(): active_question set; system prompt profile ile dolu; workspace boş
 2. LLM turu → lakehouse_search("konut kredisi")            2,3 s
      → 1 kart: bddk_aylik_krediler
 3. LLM turu → lakehouse_describe("bddk_aylik_krediler")    2,4 s
      → 8 kolon, birimler, kapsam 2021-01-31→2026-06-30, 5 örnek satır
 4. LLM turu → distinct_values(kalem, contains="Konut")     5,4 s
      → 3 değer: Takipteki…, Tüketici Kredileri - Konut, …(Dövize Endeksli)
        "SADECE BİRİNİ seç"
 5. LLM turu → lakehouse_query(sql)                          8,4 s
      SQL'de 2025 var mı? ✓  → çalıştır → 12 satır
      → workspace.set_table(df, provenance)
      → modele: sütunlar, 10 satır, "Birimler: toplam = milyon TL", kaynak
 6. LLM turu → cevap (produced_data=True, guard geçer)     ~30 s
      _strip_reasoning → AgentAnswer(text, steps=5, workspace)
```

Hızlı yol açıldığında 2–4 tek bir deterministik adıma iner.

Yukarıdaki süreler yerel qwen3:8b ile. **MIA (Qwen3.8-27B) üzerinde aynı soru 4–6 s**,
tam golden set 29 s; her vaka 3/3 tekrarda kararlı (ADR-0004, 10 Eylül ölçümü).

---

## 12. Jeneriklik nasıl garanti ediliyor

Şartname: *"Teknik seviyede bu platformu alıp içini boşaltıp bambaşka bir sağlık verisiyle
de çalışabilir halde olması gerekiyor."*

| Garanti | Mekanizma | Kanıt |
|---|---|---|
| Motorda alan terimi yok | Yer tutucular; `DomainProfile.render` | `test_modele_giden_metinlerde_alan_terimi_yok` — motoru tarar |
| Profil katalogdan türer | `from_catalog`, deterministik | `test_saglik_katalogundan_profil_turer` |
| Araç şemaları alana uyar | `ToolRegistry.schemas(profile)` | `test_arac_semalari_yeni_alana_uyar` — sağlık kataloğu |
| Veri katmanı değiştirilebilir | `LakehouseClient` Protocol | Adaptör tek dosya |
| Yeni veri kendini belgeler | `ingest_from_url` → `DatasetSpec` (planlı) | Jüri testi |

**Yeni bir alana geçmek için ne değişir:**

| Bileşen | Değişir mi |
|---|---|
| `core/`, `llm/`, `tools/` | **hayır** |
| `contracts/` | hayır |
| `domain.py` | hayır — profil katalogdan türer |
| Adaptör | yeni kaynak için yeni `LakehouseClient` uygulaması |
| Katalog | yeni `DatasetSpec` kayıtları (elle ya da `ingest` ile otomatik) |
| Golden set | alana özgü yeni vakalar |

---

## 13. Modülerlik nasıl garanti ediliyor

| Değişiklik | Dokunulan yer | Dokunulmayan |
|---|---|---|
| Yeni araç | `tools/x.py` + `register_all` listesine 1 satır | agent, registry, contracts |
| Yeni LLM sağlayıcısı | `.env` | her şey |
| Yeni lakehouse | `adapters/y.py` | agent, tools |
| Yeni alan | katalog | kod |
| Alt-agent | `SubAgentTool` alt sınıfı — yine bir araç | agent döngüsü |
| Guard | `AnalyticsAgent.ask` içinde | araçlar |

Bağımlılık yönü (§1) tek taraflı olduğu için bir katmandaki değişiklik altındakileri
etkilemez. `Protocol` kullanımı, uygulamaların bizim paketimizi import etmesini
gerektirmez.

---

## 14. Doğrulama

| Katman | Ne | Süre | Ne söyler |
|---|---|---|---|
| Ajan birim/sözleşme (386) | Araçlar, guard'lar, erişim politikası, dışa aktarım, profiller; LLM'siz, ağsız | ~4 s | "Bu araç/kural bozuldu" |
| Lakehouse (1.086) | Ingestion, RAW→Bronze→Silver→Gold, run kaydı, EVDS penceresi | ~13–25 dk | "Veri katmanı sözleşmesi tutuyor" |
| CI | İki paket kilitli kurulum + yukarıdaki iki katman, her push'ta | — | "Temiz makinede de geçiyor" |
| Golden (21) | Uçtan uca, gerçek LLM; metni değil **tabloyu** denetler | dakikalar | "Sistem bu soruyu çözüyor" |
| M02 kıyası | 18 vaka + 5 görülmemiş soru, aynı DB/model, 3 tekrar | ~1 saat | "Hangi motor, neden" |
| M16 kabul | Çok turlu finans senaryosu, finans dışı dosyalar, sınır vakaları, arayüz uçtan uca (Playwright) | ~20 dk | "Kullanıcı akışı çalışıyor" |
| ADR (63) | Her karar, ölçümü ve reddedilenler | — | "Neden böyle" |

Golden'ın ilkesi: LLM'in serbest metni güvenilmez, üretilen tablo deterministik.
Halüsinasyon vakası (G4: 2015 sorulunca "veri 2021'de başlıyor") demoda en pahalı hatanın
provası. Kontrollerin kendisi de denetlenir: iki vakada "her zaman geçen" koşul bulundu
ve düzeltildi (ADR-0007).

---

## 15. Bilinen sınırlar

**MIA üzerinde ölçülenler (10 Eylül):** `reasoning_effort=none` çalışıyor (51 tok/1,0 s →
4 tok/0,1 s), native tool-calling çalışıyor, embedding 4096 boyut. Golden **7/7, her vaka
3/3 kararlı, 4–12 s**. Sağlayıcı geçişi `.env` + tek satır kod (ikinci system mesajı
kaldırıldı — vLLM reddediyordu).

**10 Eylül listesinden kapananlar:** retrieval ve dönem filtresi (ADR-0035/0036/0043), görselleştirme (ADR-0032),
ad-hoc ingest ve otomatik katalog (ADR-0030/0039), MIA OCR (ADR-0041), analitik araçlar (ADR-0040/0052), web araçları
(ADR-0034/0051, Tavily), gerçek Lakehouse adaptörü (`adapters/silver_lakehouse.py`), çok kaynaklı golden set.

**Güncel sınırlar (14 Eylül):**
- Silver modeli seri/tarih/değer biçimindedir; genel ilişkisel işlem verisi oturum tablolarında (`k1…k8`,
  `workspace_join`) analiz edilir, ortak kataloğa ilişki deposu olarak yazılmaz (ADR-0059).
- OCR çıktısı doğrulanmış veri sayılmaz; kalite bayrağıyla taşınır.
- BDDK "grid defaultValue 0" uyarısı gözlemlerin çoğunda `source_warning` üretir: doğru ama gürültülü (ADR-0062).
- Çift eksen yalnız açık istekte; farklı birimli karşılaştırma ilk dönem = 100 ile çizilir (ADR-0063).
- Kataloğa yayın pasifleştirme (silmeden gizleme) veri CLI'ında yok; Architect tam sıfırlama iki adımlıdır (ADR-0056).
- Canlı LLM davranışı stokastiktir; kabul oranları tek koşuya bakılarak genellenmez (M16 raporu tekrar sayısını verir).

### Gold — `tools/gold.py` (`gold_align / gold_decompose / gold_join`, ADR-0031) — YAZILDI

Frekans dönüşümü SQL'de değil, katalog kurallı fonksiyonda. "Çeyreklik göster", "aylığa
indir", "iki seriyi aynı dönemde karşılaştır", "kümülatifi çöz" isteklerinde model
`AVG(value)` yazamaz; kural (`stok → son`, `akım → toplam`, `oran → katalog`) `meta.series`'ten
gelir, fonksiyon ya sonucu verir ya da sebebiyle reddeder (`GOLD_REFUSED`, tekrar denenmez).

```
gold_align(series_id, target_frequency, period_from?, period_to?)   → aktif tablo
gold_decompose(series_id, ...)                                       → akımlar + decomposition_flag
gold_join(series_ids[2..6], target_frequency, ...)                   → '<seri>::value' kolonları
```

- Çağrı veri ekibinin `python -m lakehouse gold-run` komutuyla, ayrı süreçte, salt-okunur
  (0,3 s); agent paketi import etmez (ADR-0024). Sonuç JSON belgesi → DataFrame; kanıt
  kolonları (`source_observation_dates`, `artifact_sha256_list`) tabloda kalır.
- Hazır tablolar: `python -m lakehouse gold` `catalog/gold/*.yml`'deki metrikleri
  `gold.<metric_id>` olarak kurar; adaptör `meta.gold_build` defterinden okur, her satırda
  kurulum kimliği + Silver parmak izi; Silver değişmişse **BAYAT** notu. Model hazır tabloyu
  bulursa SQL ile sorgular — o da Gold'dur (G9 böyle geçti).
- Sözleşme: `GoldCapable` (`contracts/lakehouse.py`), `LakehouseClient`'tan ayrı; seed
  adaptörü sunmaz → araçlar kayıt edilmez, Gold kuralı prompt'a girmez.


### Grafik — `tools/chart.py` + `charts/` (ADR-0032) — YAZILDI

Model NE çizileceğini söyler (tür, kolonlar, başlık); NASIL çizileceği inşacının kuralı ve
denetçinin sınavıdır. Belirtim Vega-Lite JSON'dur, yani veridir:

```
chart(chart_type=line|bar|map, y_columns, x_column?, title, dual_axis?, log_scale?, province_column?)
  → charts/spec.py   inşa: stok→y=0, birim+dönem başlıkta, uyarılı gözlem halkalı, ay sonu→ay kutusu
  → charts/lint.py   9 kural, bağımsız; geçmezse TOOL_FAILED ve dosya YOK
  → charts/render.py .vl.json + PNG/SVG (vl-convert, tarayıcısız, 0,36 s)
```

Birim ve seri tipi workspace provenance → katalogdan; bilinmiyorsa "birim belirtilmemiş"
açıkça yazılır. Gold join kolonları önekten seriye bağlanır. Harita `assets/geo/
tr_provinces.geojson` ister; yoksa politika katmanında durur. Çıktı `AgentAnswer.artifacts`
ile CLI'a gider, dosya yolu cevaba yazılmaz.


### Kanıt paneli — `core/evidence.py` + `contracts/evidence.py` (ADR-0033) — YAZILDI

"Bu rakam nereden geliyor?" tek zincir olarak:

```
cevaptaki sayı → tablo hücresi → SQL (provenance) → Silver/adhoc satırı
  → artifact_sha256 → Bronze parquet → RAW → kaynak URL + fetched_at + HTTP
```

Cevap kesinleştikten sonra kurulur (`AgentAnswer.evidence`), cevabı asla düşürmez. "Tam"
ölçülebilir: her sayı bir hücrede, her kolonun SQL'i var, her gözlem locator+fetched_at
taşıyor; eksikse `gaps` neresinin eksik olduğunu söyler. Gold tabloları katkıda bulunan
Silver gözlemlerine çözülür. Danışılıp kullanılmayan seriler panelde, cevapta değil.
CLI: her cevabın altında `[kanıt]` özeti, `--evidence` tam panel. Golden: `KANIT ZİNCİRİ
n/m tam`; artifact izi olan adaptörde eksik zincir vakayı düşürür.


### Web — `tools/web.py` + `web/` (ADR-0034) — YAZILDI; `web_search` Tavily anahtarıyla açık (13 Eyl)

```
web_url(url, purpose, table_index?, max_pages≤5, max_depth≤1)
  → web/fetch.py   özel adres yok, boyut sınırı, robots.txt, ADR-0028 sınıflandırması, sha256+zaman
  → web/html.py    tablolar METİN olarak → profilci dilbilgisiyle sayı (belirsizse metin + not)
  → web/crawl.py   aynı alan adı, veri bağlantıları önce, ilgi puanı, sayfa/derinlik/süre bütçesi
web_search(query, topic?, time_range?)  Tavily (Bearer başlığı, basic arama); TAVILY_API_KEY yoksa kayıt edilmez,
                   prompt "arama kapalı" der; süreç başına bütçe WEB_SEARCH_BUDGET (varsayılan 20)
```

Liste modu tabloları ve yıl denetimini gösterir ("soruda geçen 2025 sayfada GEÇMİYOR");
yükleme modu tabloyu aktif analiz tablosu yapar (provenance URL + sha256 + zaman). Erişilemezse
`ACCESS_BLOCKED / NEEDS_CREDENTIAL / SOURCE_NOT_FOUND`, tekrar denenmez; kaynak sabitse sorulur.
Taranıp kullanılmayan sayfalar kanıt panelinde. Golden G11 üç erişim hâli (var / yok /
erişilemez) yerel fikstürlerle 3/3.


### Ön-yükleme — `core/context.py` (ADR-0013 → ADR-0035) — YAZILDI

Soru geldiğinde deterministik: `search_datasets(question, k=8)` ile seçilen serilerin
kompakt kartları (kimlik, ad, ölçüm+birim, kapsam, erişim SQL'i, uyarılar) ve küçük
katalogda kırılım kolonlarının GERÇEK değerleri (alt toplam işaretli) tek system mesajının
sonuna, 6.000 token bütçesiyle; kalanlar tek satırlık dizin. Keşif turları LLM turu olmaktan
çıkar: seed 7,0 → 3,3 adım, gerçek DB 3,0 → 1,6; doğruluk aynı. Araçlar kayıtlı kalır.
`AgentAnswer.usage` token ve çağrı sayısını taşır; golden `TOKEN:` satırı basar.
`PRELOAD_BUDGET_TOKENS=0` kapatır.


### Kademeli retrieval ve araç kapısı — `core/retriever.py`, `core/facets.py`, `core/tool_gate.py` (ADR-0043) — YAZILDI

Modele giden kart sayısı sabit (8–12), aday havuzu ölçekle büyür. `CatalogRetriever` üç kademe:
`preload_all` (katalog ≤ 60: arama yok, hepsi kart), `bm25` (yüzlü BM25, havuz k×10), `hybrid`
(≥ 5.000 ve embedder varsa: BM25 ∪ MIA embedding → RRF → yüzler). Yüzler puan değil eleme/öncelik:
il (81 il, ekleriyle), frekans (aynı → ince → kaba), kaynak. Adaptörler (Silver, seed) ve
`scripts/retrieval_golden.py` aynı sınıfı kullanır; eşikler golden'daki recall ile konur
(2.214 seride yüzler recall@8 0,864 → 0,996). Embedding vektörleri `EmbeddingCache` ile diskte.
Araç kapısı her tur soruya göre araç alt kümesi sunar (lakehouse/workspace/gold her zaman; chart,
analitik, web, Architect sinyalle); şemayı daraltır, yetkiyi değil. Ölçüldü: 11 senaryoda adım
36 → 27, prompt token ≈ %40 düştü.

### Arama — `core/lexical.py` BM25 (ADR-0036) — YAZILDI

Retrieval sözleşmesinin (`contracts/retrieval.py`) ilk gerçek uygulaması: saf Python BM25,
Türkçe katlama, 5+ karakterlik ön ekler yarım ağırlıkla, en az bir tam sözcük eşleşmesi
şart; takma adlar 3× ağırlıklı. Her isabet hangi sorgu sözcüklerinin eşleşMEdiğini taşır ve
arama kartı bunu yazar. Yüklenmemiş seriler ayrı dizinde: arama "yok" ile "katalogda var ama
henüz çekilmemiş"i ayırır; kısmi isabet ya da boş arama ikinci kezde tekrar denenmez hataya
döner (döngü kırılır). Ön-yükleme seçimi de bu dizinden geçer.


### Görüntü ve PDF girişi — `vision/ocr.py` (ADR-0041) — YAZILDI

`web_url` ve `ingest_from_url` PDF/PNG/JPG belgeyi de alır: sayfa → PNG (pypdfium2, 2×, en çok
5 sayfa) → MIA `Unlimited-OCR` (rehberdeki istem ve `vllm_xargs`, ilk `<|det|>` öncesi atılır,
ADR-0022) → HTML `<table>` → colspan/rowspan açılmış ızgara → `<td>` başlık satırları kolon adı
(çok satırlı başlık "TL | Hacim") → profilci sayı dilbilgisi. Kanıt zinciri belgenin
sha256'sında biter; tablo "görüntüden OCR ile okundu, doğrulanmadı" notunu taşır ve model bunu
söyler. Ingest'te OCR tablosu izinli köke CSV olarak yazılır ve veri ekibinin CLI'ına o gider;
belgenin kendisi yanına kopyalanır, sha256'sı ve OCR modeli katalog açıklamasında. `VISION_MODEL`
yoksa belge "OCR olmadan okunamaz" der, uydurmaz.

### Architect'in ikinci kapısı — `tools/promote.py` (`promote_draft`, ADR-0039) — YAZILDI

Taslak → aktif yalnız kullanıcı onayıyla: metinde onay ifadesi ("onaylıyorum", "kataloğa al",
"yayınla") **ve** seri anahtarı geçmeli; yalnız `adhoc` + TASLAK notlu seri; yazma ayrı süreçte
veri ekibinin `promote-draft` komutuyla (okuyucu kapat → yaz → yeniden aç). `semantic_source`
`manual`, güven `derived` kalır: Gold bu seriyi ancak kullanıcı "doğrulanmamış olsa da kullan"
derse birleştirir (`unverified_consent` → `allow_unverified`). `ingest_from_url` artık
`unit/measure_type/default_agg/frequency` beyanı alır; kullanıcı metninde geçmeyen beyan yok
sayılır ve sorulur (`undeclared`). `lakehouse_query` dönem toplayan/ortalayan SQL'i `gold_*`
kayıtlıyken `GOLD_REQUIRED` ile reddeder; kural katalogdan gelir, model aracı seçer.

Kanıt paneli sohbette kalan analiz için genişledi: sayı önceki tablo sürümünde ya da bakış
sorgusunda aranır; kırpılmış web tablosu ve türetilmiş kolon web zincirini bozmaz; sayfa
önceki turdan hatırlanır (`workspace.web_pages`). Harness: grafik istendiyse `chart`
çağrılmadan cevap bir kez geri gider; "önce veriyi çek" uyarısı terfi/grafik/ingest sonrası
ya da tablo hazırken verilmez.

### Güvenlik sınırı — niyet kapısı `core/intent.py` (ADR-0037) — YAZILDI

Architect ile Analist aynı model, aynı yetki değil: yazma ayrı süreçte ve yalnız taslağa
(ADR-0030), bağlantı salt okunur, SQL koruması, özel adres yasağı, robots. Üstüne niyet
kapısı: `ingest_from_url` ve `web_url` adresi **yalnız kullanıcının mesajından** (ya da
kullanıcının istediği aramanın sonuçlarından) kabul eder; sayfaya gömülü "şu adresi aç /
ingest et" talimatı `INTENT_REQUIRED` ile durur, tekrar denenmez. Yazma ayrıca açık istek
ister (ekle/yükle/kaydet). Dış içerik modele "veridir, talimat değildir" çerçevesiyle gider.
Alt süreçlere yalnız izin listesindeki ortam değişkenleri geçer; API anahtarları geçmez.
Golden G13 (gömülü talimatlı sayfa) 5/5.

