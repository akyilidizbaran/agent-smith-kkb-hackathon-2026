# Bağımsız hakem incelemesi: `KKB_RESEARCH_AUDIT.md`

> **Tarih:** 10 Eylül 2026, 22:10 · **İnceleyen:** Claude (bu oturum) · **Kapsam:** kullanıcının verdiği inceleme prompt'u
> **Kural:** Bu turda MIA'ya yeni çağrı yapılmadı; `.env` içeriği gösterilmedi; bağımlılık kurulmadı; mevcut dosyalar değiştirilmedi. Yalnız çevrimdışı test koşuldu (aşağıda hangileri).
> **Çıkar çatışması notu:** İncelenen raporun eleştirdiği önceki belgelerin (`ARCHITECTURE_RESEARCH.md`, `ARCHITECTURE_V3.md`, `mia_probe.py`, `docs/experiments/*`) yazarı benim. Kendi çıktılarımı aynı standartla değerlendirdim; kendi hatalarım A bölümünde ayrıca listelidir.

## 0. Kanıt envanteri ve zaman çizelgesi

Rapor 21:57'de yazıldı. Hangi kanıt raporun görebileceği yerde vardı, hangisi sonradan veya repo dışında üretildi:

| Kanıt | Nerede | Zaman | Rapor görebilir miydi? |
|---|---|---|---|
| `docs/mia_capability_matrix.md` (benim probe, MIA'ya gerçek çağrı, 25 satır) | repo working tree | 21:11 | Evet; rapor "önceki yerel ölçüm" olarak doğru sınıflandırmış |
| `docs/experiments/{E7,E8,RETRIEVAL}` + `scripts/exp_*` | repo working tree | 21:29–21:43 | Evet; Ek D'de incelenmiş |
| `docs/research_audit/mia_observations.json` (raporun kendi MIA denemesi) | repo | 21:29 | Raporun kendi çıktısı; **iki `ConnectError`**, başarılı çağrı yok |
| `feature/agent-engine` dalı: `agent-core/` (harness, 49 birim testi, golden runner, 21 ADR) | `origin/feature/agent-engine` (remote branch) | dal 10 Eylül öncesi | **Görebilirdi** (remote branch), ama yalnız working tree'ye baktı; "checkout'ta yok" ifadesi working tree için doğru, repo için eksik |
| Golden set MIA taban çizgisi 7/7, 56 s, `golden_baseline.json` | **repo dışı** scratchpad kopyası | 21:50 | Hayır (repo dışı) |
| Blok C konfigürasyon deneyleri (`experiments_blockC.md`, kısmi) | repo dışı scratchpad | 22:00–devam | Hayır; **rapor sonrası kanıt** |

Bu ayrım aşağıda her bulguda korunmuştur.

Çevrimdışı koşulan testler (bu inceleme sırasında): `python -m unittest discover -s tests -p test_research_audit.py` → **4/4 geçti**; `scripts/retrieval_evidence_audit.py` **scratchpad kopyasında** koşuldu (orijinal `docs/research_audit/retrieval_results.json`'u üzerine yazdığı için) → raporun BM25 özetiyle birebir aynı sonuç (R@1 0,625 · R@3 0,8125 · R@5 0,844 · MRR 0,746 · nDCG@5 0,756). Tokenizer davranışı ayrıca doğrulandı (A-3).

---

## A. En önemli bulgular

### A-1 · Yüksek · Rapor §0, §10, §23, Ek C — "Çalışan harness/golden kodu bu checkout'ta yok"

- **İddia:** `src/kkb_agent`, `scripts/run_golden.py` ve 7/7 golden çıktıları bulunmuyor; dolayısıyla harness'ın çalıştığı doğrulanmamış; "mevcut kodu korumak daha hızlı" argümanı kullanılamaz; custom vs LangGraph spike gerekir.
- **Kanıt:** Kod `origin/feature/agent-engine` dalında (`agent-core/src/kkb_agent/…`, `agent-core/scripts/run_golden.py`, `tests/golden/cases.py`, `docs/adr/0001–0021`). Bu oturumda dal repo dışına arşivlendi; **49/49 birim testi** geçti; golden set MIA üzerinde **7/7, toplam 56 s, vaka başına ort. 8 s, 5,7 araç adımı** (21:50, repo dışı). Rapor sonrası ek: Blok C kısmi sonuçları (aşağıda A-12).
- **Etki:** Raporun "en büyük teslim riski gerçek veri ve executable contract eksikliği" tespiti kısmen doğru kalır (agent lakehouse'unda yalnız BDDK Tablo 3–4 var; TÜFE/KFE/faiz yok), ama "framework seçimi/spike" önerisi ve "çalışan uygulama yok" çerçevesi geçersizleşir. Karar: harness korunur, spike yapılmaz.
- **Düzeltme:** Rapora "remote branch incelenmedi" notu; §10'daki spike önerisi "gerekmez" olarak güncellenmeli. Kanıtın kendisi repo dışı olduğu için bu inceleme de onu "rapor sonrası, repo dışı" etiketliyor.

### A-2 · Yüksek · Rapor §7 ve Ek A-11 — BM25'in "lexical boşluk gösterdiği" iddiası tokenizer artefaktıyla şişirilmiş

- **İddia:** Raporun kendi 20 belge/36 sorgu fixture'ında BM25 R@3 = 0,81; buradan "tanı testi lexical boşluk gösteriyor; hybrid'in kapatıp kapatmadığı gösterilmedi" (Ek A-11) çıkarımı.
- **Kanıt:** `retrieval_evidence_audit.py::tokens()` yalnız `I/İ/ı`'yı katlıyor; `Ü/Ö/Ç/Ş/Ğ` katlanmıyor ve stemming yok; `\w+` alt çizgili kodları tek token yapıyor. Doğrulandı: `tokens("TÜFE") = ['tüfe']` ama belge `TUFE` → `['tufe']` (Q04 kaçırması); `mortgage_balance` tek token, sorgu `mortgage` (Q08 kaçırması); `fiyatları` ≠ `fiyatlarının` (Q07 kaçırması). 6 kaçırmanın **3'ü** fixture/tokenizer uyumsuzluğu, yalnız 3'ü (Q11 negasyon, Q14 stok/akım, Q28 dil geçişi) gerçek lexical sınır.
- **Etki:** Rapor §15'te "query ve document aynı normalizasyonu kullanmalı" diyor ama kendi evaluator'ı bunu yapmıyor; "lexical boşluk" büyüklüğü abartılı. Benim bake-off'umda (Türkçe karakter katlamalı tokenizer) BM25 R@3 0,96 çıkmasının bir nedeni bu.
- **Düzeltme:** Evaluator'a diacritic folding + alt çizgi bölme; sonra yeniden koş. Q11/Q14/Q28 türü sorgular hard-negative seti olarak ayrı raporlansın; "lexical boşluk" yalnız o alt kümeyle iddia edilsin.

### A-3 · Yüksek · Rapor §4 tablosu ve Ek C — Önceki probe'un `json_schema` sonucu "çalışıyor" değil "kabul ediliyor"dur (kendi hatam)

- **İddia (rapor):** Eski betik tam şema doğrulaması yapmıyor, yalnız required anahtarlar.
- **Kanıt:** `scripts/mia_probe.py::test_response_format` → `good = all(k in obj for k in PLAN_SCHEMA["required"])`. Doğru: enum/tip/`additionalProperties` sınanmadı. Raporun `mia_evidence_audit.py`'deki tasarımı (çelişen prompt + `strict` schema + kontrol kolu + `Draft202012Validator`) doğru tasarım; ama **hiç koşmadı** (ConnectError).
- **Etki:** V3'te "`json_schema` çalışıyor → `extract_table`/`clarify` için kullanılabilir" ifadesi "sunucu parametreyi kabul ediyor ve anahtarlar geliyor" seviyesine indirilmeli. Yerel Pydantic doğrulaması her durumda zorunlu (V3 zaten böyle).
- **Düzeltme:** `mia_capability_matrix.md`'de satır etiketini "REJECT değil, ZORLAMA DOĞRULANMADI" yap; raporun çelişen-şema testini koş (D-1).

### A-4 · Orta · Rapor §4, Ek C — Prefix caching ve determinizm çıkarımlarım tasarımın gösterebileceğinden güçlü (kendi hatam, kısmen)

- **İddia (rapor):** "Birkaç total-latency örneği cache açık/kapalı sonucunu desteklemez; TTFT ve kontrol kolları gerekli." "Tek görevde 5 aynı çıktı determinizm garantisi değil."
- **Kanıt:** E3: n=5, 6k token birebir aynı önek, 20 çıktı token; 0,90 s → 0,92 s. Prefill ≈ 6k×0,072 ms ≈ 0,43 s olduğundan cache açık olsa toplam sürede ~%45 düşüş beklenirdi; **etkinin yokluğu** bu tasarımla yakalanabilir, ama randomizasyon/TTFT yok ve "prompt düzeni önemsiz" genellemesi fazla. Determinizm: T=0+seed, tek görev; seed'in katkısı izole değil (T=0 tek başına açıklayabilir).
- **Etki:** V3 §3.5 "sabit önek düzeni gereksiz" → "bu deployment'ta cache kazancı gözlenmedi (n=5)" olmalı; "deterministik" → "T=0'da tekrarlanabilir gözlendi".
- **Düzeltme:** İfade yumuşatma; cache için 20 sorgu × (soğuk/sıcak, karıştırılmış sıra) ve `usage`/TTFT kaydı istenirse D'ye eklenebilir, ama **kararı değiştirmez** (prompt kısaltma her koşulda doğru).

### A-5 · Orta · Rapor §4 — "Tool proposal ≠ tool-result round-trip" doğru ayrım; ancak round-trip kanıtı vardı

- **İddia:** Eski betik round-trip yapmıyor; yeni betik henüz çalışmadı; framework uyumunun eksik kabul testi.
- **Kanıt:** `mia_probe.py` gerçekten yalnız proposal ölçüyor (doğru). Ancak ekibin harness'ı her golden vakasında 4–10 tam round-trip (`role=tool`, aynı `tool_call_id`, devam) yapıyor; bu oturumda 7/7 tekrarlandı (repo dışı, A-1). Round-trip **fiilen doğrulanmış**, yalnız rapor bunu göremedi.
- **Düzeltme:** Matris satırı "round-trip: harness golden koşusuyla doğrulandı (tarih, ortam)" olarak güncellensin; raporun izole round-trip testi yine faydalı (tek çağrı, sentetik, hash'li).

### A-6 · Orta · Rapor Ek D — E7 "416 vs 421 rakam → OCR uydurmadı" çıkarımı geçersiz (kendi hatam) ve E7'nin iki çelişen karar metni

- **İddia (rapor):** Rakam sayısı eşitliği hücre doğruluğunu göstermez; raporun otomatik kararı "text-first", ek analiz "paralel" diyor.
- **Kanıt:** Her ikisi doğru. `scripts/deney_ocr.py` otomatik karar metni yalnız "metin katmanı dolu mu" bakıyor; E7 raporuna sonradan eklediğim analiz (pandas 15×11 DataFrame) yapıyı doğruluyor ama hücre-hücre metin katmanıyla eşleme yapmadım. Rakam sayısı argümanı zayıf.
- **Düzeltme:** E7'ye hücre-düzeyi doğrulama (OCR DataFrame'inin her sayısal hücresi metin katmanı sayı havuzunda var mı; en az 5 hücre elle) eklenmeli; script'in otomatik karar metni "yapı var mı" kontrolünü de içermeli. Karar (paralel, yapı OCR'dan, sayı doğrulaması metin katmanından) makul fakat **hücre bağlama** olmadan tamamlanmış sayılmaz.

### A-7 · Orta · Rapor Ek D, §7 — Bake-off süre ve MRR yorumu (kendi hatam)

- **İddia (rapor):** Dense süresi 50 sorgunun tek batch'i / 50; BM25 süresi index build'i amortize ediyor; MRR top-10 ile sınırlı; iki benchmark birleştirilemez.
- **Kanıt:** `exp_retrieval_bakeoff.py`: `Q = embed([...])` tek batch, `timing["dense"] = (…)/len(queries)`; BM25 `t0` tokenizasyon+index öncesinde; `rrf(...)[:10]` ile MRR top-10. Hepsi doğru. Tek MIA embedding çağrısı probe'da 0,1 s ölçülmüştü; online sorgu maliyeti 28 ms değil ~100+ ms.
- **Etki:** ADR-15'teki "BM25 2 ms vs dense 28 ms" gerekçesi yön olarak doğru ama sayılar yanlış türden. Karar (BM25+alias P0) değişmez.
- **Düzeltme:** Raporda süre sütununu "amortize batch, online değil" diye etiketle; MRR'yi tam sıralamada hesapla.

### A-8 · Orta · Rapor §6, Ek C — Finansal kurallarda iki doğru düzeltme, bir eksik

- **Doğru:** (i) `count → last` genel kuralı yanlış: adet stok da (şube sayısı) akım da (aylık konut satışı) olabilir; `measure_type` adet için `stock_count`/`flow_count` ayrımı gerekir. (ii) "Stok'a diff yasağı" aşırı: net bakiye değişimi geçerli analizdir; yasak olan bunu "yeni kullandırım" diye etiketlemek. Ekibin golden G3'ü tam da net değişimi hesaplıyor; kontrat metni bununla çelişiyor.
- **Eksik:** Rapor haftalık akım faizinin "sabit faizli kredileri kapsadığı, efektif yıllık orandan ağırlıklandırıldığı" iddiasını TCMB metaveri PDF'ine (S30) dayandırıyor. Bu turda dış kaynak açmadığım için **doğrulayamadım**; yanlış demiyorum, doğrulanmamış diyorum. Doğruysa V3'teki `default_agg=avg` (haftalık→aylık) "analitik özet" etiketiyle sunulmalı; kontrat zaten "verified default_agg" istiyor.
- **Düzeltme:** `LAKEHOUSE_CONTRACT_FILLED.md` §5 tablosunda `count` satırı ve §6 "diff yasağı" cümlesi veri ekibiyle revize edilmeli (dosyaya dokunmadım).

### A-9 · Orta · Rapor §28 R2, §19 — Regex grounding guard'ın "aynı sayı yanlış dönem/birim" açığı; rapor sonrası kanıt bunu destekliyor

- **İddia (rapor):** Serbest metinde sayı arayan guard, yanlış ölçüye/döneme bağlanmış doğru sayıyı geçirir; typed claim binding gerekir.
- **Kanıt:** Doğru. Rapor sonrası (repo dışı, kısmi) Blok C gölge-mod ölçümü: baseline'da 14 koşunun yalnız 6'sında cevaptaki tüm sayılar araç çıktısında bulundu; preload'da 10/14. Bu, guard'ın **yanlış pozitif** (biçim/yuvarlama/yüzde) ve **yanlış negatif** (birim çevrimi) davranışının henüz ayrıştırılmadığını gösterir; "enforce" modu sonucu bekleniyor.
- **Etki:** Regex guard P0'da yalnız gölge/uyarı olarak kalmalı; başlık sayıları için typed claim (metric, period, unit, value) V3'e alınmalı.
- **Düzeltme:** E5'i FP/FN ayrımıyla raporla; typed claim'i `lakehouse_query` sonucu + `purpose` alanından türetmek ucuz bir başlangıç.

### A-10 · Orta · Rapor §13, §17 — Compare-and-swap commit ve `depends_on` denetimi bu ölçekte gereksiz karmaşıklık

- **İddia:** `commit_workspace` compare-and-swap; controller read/write set çıkarımı; `STALE_WORKSPACE`.
- **Kanıt:** Harness tek iş parçacıklı ReAct; workspace tek sahipli (ADR-0006, İlke 4). Rapor sonrası paralel executor denemesinde (repo dışı) mutasyon yapan araçlar zaten çağrı sırasıyla ardışık koşuyor; "aynı turda iki kolon önerisi" yalnız model iki mutasyon çağrısı verirse oluşur ve sırayla uygulanır. CAS'ın çözdüğü problem (eşzamanlı yazıcılar) demoda yok.
- **Etki:** P0'a alınırsa mühendislik zamanı yanlış yere gider. **Makul fakat koşullu:** çok kullanıcılı/çok oturumlu sürüm gelirse.
- **Düzeltme:** V3'teki "mutating tools sıralı, read-only paralel" kuralı + workspace `version` alanı yeter; CAS P2.

### A-11 · Düşük · Rapor §4, `mia_evidence_audit.py` — "Uzun prompt" testi uzun değil; OCR testi belge değil

- **Kanıt:** `long_position_*` 200 satır × ~6 token ≈ 1,2k token; rapor §4 "artan uzunluk; truncation+usage" tasarımını vaat ediyor ama betik bunu ölçmüyor. `ocr_one` sentetik "KKB TEST 7429" görseli; belge yapısı yok, hücre oracle'ı yok. Betik genel olarak sağlam (redaksiyon, hash, strict JSON, çelişen şema kolu, round-trip, 2'li concurrency).
- **Düzeltme:** Uzun prompt kolunu 6k/28k/50k'ya çıkar (benim probe 49,9k'yı ölçtü); OCR için `data/adhoc/altin.pdf` sayfa görselini kullan.

### A-12 · Bilgi · Rapor sonrası, repo dışı — Blok C kısmi sonuçları (kararı etkiler, rapor göremezdi)

| Konfig (golden 7 vaka × 2) | pass^2 | s/vaka | LLM turu | token |
|---|---|---|---|---|
| baseline (mevcut harness) | 7/7 | 6,9 | 6,9 | 29,9k |
| + katalog ön-yükleme | 7/7 | 5,3 | 3,9 | 22,4k |
| + yalnız paralel çağrı | **6/7** | 8,5 | 7,0 | 30,7k |
| ön-yükleme + paralel | 7/7 | 6,9 | 3,6 | 20,6k |
| ön-yükleme + paralel + kısa cevap | 7/7 | **3,3** | **2,9** | **15,8k** |

Yorum: ADR-0013'ün ön-yükleme fikri ve E8 eşiği doğrulanıyor (tur 6,9→3,9). Tek başına paralel çağrı **zararlı** (model bir vakada gereksiz çağrı üretiyor) — raporun "paralel öneri sayısı bağımsızlık kanıtı değil" uyarısıyla uyumlu. En büyük süre kazancı kısa cevap (çıktı token'ı). Kalan iki konfig (enforce grounding, escalate) koşuyor. Bunlar 2 tekrar; pass^3 ile tekrarlanmalı.

---

## B. Doğru bulduğum ve korunması gereken kararlar (raporda)

1. Kanıt sınıflarının ayrımı ve "aktarım" etiketi (organizatör Q&A'nın orijinal metni checkout'ta yok) — doğru ve titiz.
2. HTTP 200 / geçerli JSON / şema zorlaması ayrımı; `strict_json` ile duplicate key ve NaN reddi.
3. Tool proposal ile round-trip ayrımı (A-5'teki bağlamla).
4. 401/403/kalıcı 400'ün retry edilmemesi — ekibin `OpenAICompatClient`'ında gerçekten tüm `APIError` retry ediliyordu (rapor kodu görmeden doğru noktayı vurmuş).
5. Finans: `count` kuralı, stok farkı vs kullandırım, TÜFE deflatörünün anlamı, pp/% ayrımı, Granger'ın "n≥30" ile değil varsayım+lag+etkin n ile gate'lenmesi; çoklu lag/rejim denemesinden yalnız anlamlı olanı seçmeme uyarısı.
6. Retrieval: fixture'ın model çağrısından önce yazılması ve hash'lenmesi; eksik/belirsiz/adversarial sorguların IR metriğinden ayrılması; metrik tanımları (Recall/Precision/MRR/nDCG) ve birim testleri doğru.
7. Reranker'ın aday havuzuna doğru belgeyi geri getiremeyeceği; cosine eşiğinin güven olmadığı.
8. Ingest: OCR sayısının metinde geçmesi ≠ hücre doğrulaması; page/table/row/column/header bağlama; Excel formüllerini çalıştırmama.
9. SQL güvenliği: `SELECT` ile başlamak yetmez; AST + process/OS sınırı; DuckDB belgesine dayalı.
10. Fetch politikası (loopback/private IP, redirect, boyut) — V3'te eksikti; alınmalı.
11. Trace ile provenance ayrımı; telemetri dışarı gitmesin.
12. Catalog ve FTS index'in aynı `generation_id` ile yayınlanması — DuckDB FTS otomatik yenilenmediği için gerekli.
13. pass^3 tanımı ve "her koşu temiz state".
14. "Agent sayısını jüri özelliği olarak sunma"; retriever/validator'ın agent sayılmaması.

## C. Katılmadığım veya kanıtı yetersiz bulduğum kararlar

**Yanlış**
- "Checkout'ta çalışan harness yok → spike gerekli" (A-1). Kod remote branch'te; 49 test + golden 7/7.
- "BM25 R@3 0,81 lexical boşluk gösteriyor" ölçüsünde (A-2); üç kaçırma evaluator artefaktı.
- Ek C'de "V3/AGENT: 7/7 golden doğrulanmamış yerel iddia" — rapor anında görünür olmayan ama var olan kanıt; şimdi tekrarlandı (repo dışı).

**Kanıt yetersiz**
- "Custom controller'ın restart testi LangGraph'tan pahalıysa LangGraph seç" — restart/resume yarışma gereksinimi değil; iki taraf için de ölçüm yok. Karar: spike yapılmaz.
- "Hybrid'in boşluğu kapattığı gösterilmedi" — doğru ama simetrik: kapatmadığı da gösterilmedi. Benim +2 puanım (1 sorgu) da kanıt değil. Karar D-3'e bağlı.
- Rapor §7 "en az 120 query, iki bağımsız etiketleyici, relevance 0/1/2" — doğru standart, ama 10 günlük takvimde uygulanabilirliği yok; küçültülmüş versiyonu D-3.
- S30'a dayanan faiz metaveri iddiaları — bu turda doğrulanmadı (A-8).

**Makul fakat koşullu**
- Compare-and-swap / read-write set çıkarımı (A-10) — çok oturumlu sürümde.
- `retry_same_request / replan_possible / needs_user_input` ayrı alanları — ucuz ve iyi; ekibin `ToolResult`'una ek alan olarak alınabilir.
- "İki hata olunca effort yükselt tek başına iyi politika değil" — katılıyorum; E6 tasarımı hata sınıfına göre (ör. `SEMANTIC_VIOLATION` → yükselt, `OUT_OF_COVERAGE` → yükseltme) olmalı.
- Typed claim ledger'ın **tam** hali (formula_id, input_refs) P0 için ağır; başlık sayıları için hafif sürümü P0 (A-9).
- LangGraph'ın "E, diğerleriyle aynı eksende değil" düzeltmesi doğru; ama raporun kendi §9 tablosu yine E'yi aynı sütunlarda puanlıyor.

## D. Kararı gerçekten değiştirebilecek en fazla 5 deney

| # | Hipotez | Kontrol / baseline | Veri | Metrik | Kabul | Değiştireceği karar |
|---|---|---|---|---|---|---|
| D-1 | MIA `response_format=json_schema` şemayı **zorluyor** (yalnız kabul etmiyor) | Aynı çelişen prompt, `response_format`'sız kontrol kolu (raporun `conflicting_schema_*` + `_control_*`) | Sentetik; 6+3 koşu, ayrıca `limit=999`, `extra` alanı, enum ihlali | `strict_schema_valid` oranı, kontrol kolunda ihlal oranı | Zorlama: 6/6 geçerli **ve** kontrol kolu ≥1 ihlal | `extract_table`/`clarify` için `json_schema`'ya güvenilip güvenilmeyeceği; Pydantic yerel doğrulama her durumda kalır |
| D-2 | PDF ingest'te "OCR yapı + metin katmanı değer doğrulama" hücre düzeyinde ≥%98 doğru | Yalnız metin katmanı (`find_tables(strategy="text")`) ve yalnız OCR | `altin.pdf` + bir aylık piyasa raporu (çok sayfa) + bir taranmış sayfa; her belge için ≥20 elle etiketli hücre (değer+başlık+birim) | Hücre doğruluğu, başlık bağlama doğruluğu, süre | Paralel yol hücre ≥%98 ve başlık ≥%95; aksi hâlde yol değişir | Varsayılan ingest yolu (V3 edge-case 15) |
| D-3 | Türkçe-katlamalı tokenizer ve alias'sız belgelerle BM25 ile dense arasında R@5 farkı yok | BM25 (katlamalı) vs dense vs RRF, aynı aday havuzu | Kör set: benim 60 gerçekçi seri + raporun 20 belgesi birleşik; alias alanı **çıkarılmış** belge varyantı; hard-negative alt kümesi ayrı | R@5, nDCG@5, sorgu-eşleşmeli bootstrap CI | Dense/hybrid kazancı CI'ı sıfırın üstünde ve ≥3 puan ise P1'e girer | ADR-15 (embedding P1 mi, yok mu) |
| D-4 | Başlık sayıları için typed claim (metric+period+unit), regex guard'a göre "aynı sayı yanlış birim/dönem" hatalarını yakalar; FP artmaz | Regex guard (gölge) | Golden 7 + L11-02 türü 6 adversarial cevap (elle yazılmış, yanlış birim/dönem) | FP, FN, ek tur sayısı | Typed: FN=0 adversarial'da, FP ≤ regex'in FP'si | Grounding tasarımı (A-9), P0 kapsamı |
| D-5 | Hata sınıfına göre reasoning yükseltme, sayaç tabanlı yükseltmeden iyi; kısa cevap kalite düşürmüyor | Yükseltme yok; `none` sabit | Golden 7 + seed üzerinde koşabilen 11 benchmark sorgusu (L9–L11 dahil), ×3 | pass^3, s/vaka, tur, jüri rubriğiyle anlatım kalitesi (2 değerlendirici) | pass^3 eşit veya iyi, süre ≤ baseline | V3 §3.4 thinking politikası ve §3.5 çıktı bütçesi (Blok C'nin devamı) |

## E. Revize mimari önerisi (yalnız incelemenin gerektirdiği değişiklikler)

Omurga değişmez: mevcut ReAct harness + tipli araç sınırı doğrulaması + sürümlü workspace + deterministik hesap (V3 = raporun C'si). Eklenenler ve çıkarılanlar:

**Ekle**
1. **Katalog ön-yükleme** varsayılan yol (A-12; ADR-0013'ün uygulanması): ≤6k token'a kadar kartlar + kırılım değerleri prompt'ta; üstünde BM25 top-30. Keşif araçları kayıtlı kalır (ADR-0014 kaçış yolu).
2. **Hafif typed claim**: nihai cevaptaki her başlık sayısı `{value, unit, period, source_result_id}` ile bağlanır; regex guard yalnız gölge (A-9, D-4).
3. **Hata taksonomisi alanları**: `ToolResult`'a `retry_same_request`, `replan_possible`, `needs_user_input`; istemcide 4xx retry yok (zaten scratchpad'de yamalı, dala taşınacak).
4. **Ingest hücre bağlama**: OCR HTML tablosu → DataFrame → her sayısal hücre metin katmanı + başlık/birim ile eşlenir; eşleşmeyen hücre işaretlenir (A-6, D-2).
5. **Catalog+FTS index `generation_id`** ve rebuild sonrası görünürlük testi (B-12).
6. **Fetch ağ politikası** (SSRF): loopback/private/link-local red, redirect sonrası yeniden kontrol, boyut/MIME sınırı, provider anahtarı yalnız provider hostuna.
7. **Tool zaman aşımı**: DuckDB için `connection.interrupt()` tabanlı iptal; CPU görevleri için process sınırı (raporun `Future.result(timeout)` uyarısı doğru).
8. **Paralel yürütme yalnız salt-okunur araçlarda ve yalnız ön-yükleme ile birlikte** (A-12: tek başına zararlı).

**Çıkar / erteleme**
- Compare-and-swap commit, read/write set çıkarımı → P2 (A-10).
- LangGraph spike → yapılmaz (A-1).
- Tam claim ledger (formula_id, input_refs, replay) → P1; başlık sayıları için hafif sürüm P0.
- Sayaç tabanlı reasoning yükseltme → hata sınıfı tabanlı (D-5 sonucuna kadar kapalı).

Yeni agent/framework eklenmiyor.

## F. Öncelik sırasıyla ilk 5 uygulama işi

1. **Veri: TÜFE, KFE ve konut faizi serilerinin agent lakehouse'una girmesi** (adapter + `meta.series`). Slayt 5'in 2. ve 3. sorusu bunlar olmadan çalışmaz; raporun "en büyük risk" tespitinin geçerli kalan kısmı budur. Bitiş kanıtı: G7 benzeri golden'da gerçek deflate ve KFE kolonu.
2. **Harness kaldıraçlarını dala taşımak**: ön-yükleme + kısa cevap + 4xx retry düzeltmesi + `extra` parametresi + read-only paralel (scratchpad yaması → `feature/agent-engine`, golden pass^3 ile). Bitiş kanıtı: 7/7 pass^3, vaka başına ≤4 s.
3. **Beş eksik araç ailesinin minimum tipli sürümü**: `web_search`/`web_url` (SearchClient + fetch politikası), `detect_anomalies` (rolling median/MAD), `detect_changepoints` (PELT), `analyze_relationship` (lag korelasyon + önkoşul kartı; Granger yalnız gate geçince). Bitiş kanıtı: her aile için sentetik seri birim testi + 1 golden.
4. **`ingest_url` metin→tablo→OCR zinciri, hücre bağlama ile** (D-2 fixture'larıyla). Bitiş kanıtı: `altin.pdf` ve bir XLSX'ten doğrulanmış hücrelerle quarantine tablo.
5. **Hafif typed claim + gölge regex guard + hata taksonomisi** (D-4). Bitiş kanıtı: adversarial 6 cevapta FN=0, golden'da FP ≤ gölge guard.

---

## Ek — Bu incelemede koşulan çevrimdışı komutlar

```text
python -m unittest discover -s tests -p test_research_audit.py      → 4 test OK
<scratchpad kopyası>/scripts/retrieval_evidence_audit.py            → BM25 özeti raporla aynı
python (tokenizer kontrolü)                                         → 'tüfe'≠'tufe', 'mortgage_balance' tek token, 'fiyatlari'≠'fiyatlarinin'
```

Rapor sonrası ve repo dışı kanıtlar (golden 7/7 tekrarı, Blok C kısmi tablosu) scratchpad'de durur; repoya taşınmadı, commit edilmedi.
