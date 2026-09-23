# Literatür Taraması — Agentic Data Analytics Yaklaşımları

> **Tarih:** 10 Eylül 2026 · **Amaç:** İnsanlar "doğal dilden yapılandırılmış veri üzerinde
> analiz" problemine hangi yollarla yaklaşmış, bu yollar birbirinden nerede ayrılıyor, biz
> hangisindeyiz ve her aileden ne alıyoruz.
> Bu doküman `docs/adr/` kayıtlarının kavramsal referansıdır.

---

## 0. Haritanın tamamı — dokuz aile

Aynı probleme dokuz farklı açıdan yaklaşılmış. Aileler birbirini dışlamıyor; üretim
sistemleri genellikle üç-dördünü birleştiriyor.

| # | Aile | Temel fikir | Temsilciler |
|---|---|---|---|
| A | **Text-to-SQL pipeline** | Soruyu aşamalı olarak SQL'e çevir | DIN-SQL, CHESS, XiYan-SQL, MAG-SQL, SQL-o1 |
| B | **Kod üreten data-science agent'ı** | Python/pandas yaz, sandbox'ta çalıştır | Data Interpreter, DatawiseAgent, Jupiter, DAAgent |
| C | **Semantic / metrics layer** | LLM SQL yazmasın, metrik+boyut seçsin | dbt Semantic Layer, Cube, Databricks Genie, Snowflake Cortex |
| D | **Agent kontrol desenleri** | Döngü nasıl kurulur | ReAct, Plan-and-Execute, ReWOO, LLMCompiler, Reflexion |
| E | **Tek vs çok agent** | İş kaç agent'a bölünür | Cognition, MAG-SQL, SAGE |
| F | **Güvenilirlik / abstention** | Yanlış cevap yerine cevapsızlık | RTS, TrustSQL, PV-SQL, "Never the Number" |
| G | **Zaman serisi agent'ları** | İstatistik tespit eder, LLM açıklar | LLM-Augmented Changepoint, SAGE, CALM, Argos |
| H | **Retrieval** | Modele her şeyi değil ilgili kısmı ver | schema linking, tool retrieval, hibrit arama |
| I | **Üretim sistemleri** | Gerçek kurumlarda ne çalıştı | Uber QueryGPT, LinkedIn SQL Bot, Databricks/Snowflake |

---

## A. Text-to-SQL pipeline ailesi

**Temel fikir:** Uçtan uca "soru → SQL" yerine işi aşamalara böl: şema bağlama (hangi
tablo/kolon?) → üretim → seçim/düzeltme.

**Temsilciler ve farkları:**

| Sistem | Ayırt edici özelliği |
|---|---|
| **DIN-SQL** | 4 modül: schema linking → soru sınıflandırma/ayrıştırma → SQL üretimi → öz-düzeltme. Ailenin kurucu deseni. |
| **CHESS** | 3 aşamalı *huni*: şema elemanlarını kademeli daraltır. Büyük şemalarda güçlü. |
| **XiYan-SQL** | *Multi-generator ensemble*: birden çok aday SQL üret, seçici model en iyisini seçsin. BIRD'de %75,63 ile bir dönem SOTA. |
| **MAG-SQL** | Çok-agent: Sub-SQL Generator + Refiner. *Soft schema linking* (tablo özetleriyle varlık bazlı seçim). Vanilla GPT-4'e karşı **+14,7 puan** (46,35 → 61,08). Ek maliyet raporlanmamış. |
| **SQL-o1** | Arama tabanlı: self-reward ile MCTS. Üretim yerine keşif. |
| **BASE-SQL / OpenSearch-SQL** | Açık kaynak, güçlü baseline; dinamik few-shot + tutarlılık hizalama. |

**Ortak sonuç:** Modüler pipeline, uçtan uca ajanı tutarlı olarak yeniyor. Schema linking
neredeyse her çalışmada anlamlı kazanç veriyor (+5,4–5,8 puan seçilmiş şema vs tam şema).

**Karşı görüş:** [*"The Death of Schema Linking?"*](https://arxiv.org/pdf/2408.07702) —
güçlü akıl yürüten modellerde bu adım gereksizleşebilir. Zayıf modelle çalışanlar için
geçerli değil.

**Ciddi uyarı:** [VLDB/CIDR 2026 analizi](https://www.vldb.org/cidrdb/papers/2026/p5-jin.pdf)
BIRD'de **%52,8**, Spider 2.0-Snow'da **%66,1** etiket hatası buldu. Yeniden değerlendirme
sıralamaları 3 basamağa kadar değiştiriyor. Yani bu ailenin leaderboard sayılarına
tek başına güvenilmez; kendi golden set'ini kurmak şart.

---

## B. Kod üreten data-science agent'ları

**Temel fikir:** SQL yerine Python (pandas/matplotlib) üret, sandbox'ta çalıştır, çıktıyı
modele oku. Daha esnek — istatistik, görselleştirme, ML hepsi mümkün.

**Temsilciler:**

| Sistem | Ayırt edici özelliği |
|---|---|
| **Data Interpreter** | *Hiyerarşik graf*: problemi alt problemlere ayırır, düğümler dinamik oluşur. Her düğümde kod üret-doğrula-iyileştir. InfiAgent-DABench'te **%75,9 → %94,9**. |
| **DatawiseAgent** | *Notebook-merkezli*: durum bir Jupyter defteri, hücreler adım. |
| **Jupiter** | Analizi *notebook durumları üzerinde arama* olarak kurar; MCTS + değer modeli. |
| **DAAgent** | InfiAgent-DABench'in referans agent'ı; ReAct tabanlı. |

**Benchmark:** [InfiAgent-DABench](https://arxiv.org/pdf/2401.05507) (603 soru, 124 CSV,
34 model). [DataSciBench](https://github.com/THUDM/DataSciBench) (ACL 2026 Findings).

**SQL ailesinden farkı — trade-off:**

| | SQL üretimi | Kod üretimi |
|---|---|---|
| Esneklik | dar (sorgu) | geniş (istatistik, ML, grafik) |
| Güvenlik | salt-okunur SQL kolay kısıtlanır | sandbox şart, whitelist, timeout |
| Determinizm | yüksek | düşük |
| Hata modu | çalışmayan sorgu (görünür) | *"sözdizimsel olarak doğru pandas, yanlış soruya cevap"* (görünmez) |
| Token | şema + örnek satır | her çağrıda kolon/dtype/örnek; geniş DataFrame'de patlar |

Literatürdeki en sert uyarı: model *istatistiksel fonksiyonu nasıl çağıracağını* biliyor,
*hangi testin bu dağılım için yanlış olduğunu* her zaman bilmiyor.

---

## C. Semantic / metrics layer ailesi

**Temel fikir:** LLM ham SQL yazmasın; önceden tanımlı metrik ve boyutlardan seçim yapsın,
SQL'i katman deterministik üretsin.

**Ölçülmüş etki:**

| Kurulum | Doğruluk |
|---|---|
| Yalnız şema | %8,3 |
| + iş bağlamı dokümanı | **%78,3** |
| Frontier LLM, yalnız şema | %45–51 |
| + 4 KB semantic layer | %68–69 (**+17–23 puan**) |
| Semantic layer kapsamındaki sorular | ~%100 |

**Kritik özellik — yapısal abstention:** Katman dışı bir kavrama referans verilirse
runtime *makul görünen yanlış cevap* yerine **hata** döner. Ve hata LLM-okunabilir
biçimde geri verilir → öz-düzeltme döngüsü.

**Trade-off:** Kapsam vs esneklik. Katman dışı soru cevaplanamaz. Enterprise uyarısı
([Colrows](https://colrows.com/blogs/snowflake-databricks-semantic-layer/)): katman tek
ürüne (Cortex, Genie) yapışırsa *"her yüzey kendi gerçeğini icat eder"*.

**Kaynaklar:** [dbt 2026 benchmark](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026),
[paired hallucination benchmark](https://arxiv.org/pdf/2604.25149).

---

## D. Agent kontrol desenleri

Bir agent'ın döngüsü dört farklı biçimde kurulabilir; fark "ne zaman düşünüyor"da.

| Desen | Nasıl | LLM çağrısı | Güçlü | Zayıf |
|---|---|---|---|---|
| **ReAct** | her adımda düşün → çağır → gözle | adım başına 1 | uyarlanabilir, beklenmedik sonuca tepki verir | bütünü görmez, token israfı |
| **Plan-and-Execute** | önce tüm planı çıkar, sonra sırayla çalıştır; hata olunca yeniden planla | 1 + hata sayısı | az çağrı, plan önceden görülebilir | yeniden planlama karmaşıklığı |
| **ReWOO** | bir kez planla (yer tutucularla), tüm araçları paralel koş, sonda sentezle | **toplam 2** | **5x token verimi** | araç beklenmedik dönerse *kırılır* |
| **LLMCompiler** | planlayıcı bir DAG akıtır, görevler bağımlılıkları çözülünce paralel koşar | plan + sentez | **3,6x hız**, OpenAI paralel çağrıdan ucuz | en karmaşık altyapı |
| **Reflexion** | denemeler arası öz-eleştiri | çok | öğrenir | gecikme |

Ailenin kendi özeti: *"Yaşayabileceğin hata moduna göre seç: boşa token (ReAct), katılık
(ReWOO), gecikme (Reflexion), yeniden planlama karmaşıklığı (Plan-and-Execute)."*

**Kaynaklar:** [4 desen karşılaştırması](https://theaiengineer.substack.com/p/the-4-single-agent-patterns),
[LLMCompiler](https://arxiv.org/pdf/2312.04511), [LangChain planning](https://www.langchain.com/blog/planning-agents).

---

## E. Tek agent mı, çok agent mı

**Çok-agent lehine:** MAG-SQL +14,7 puan; SAGE (anomali için uzman analizör grubu);
paralel keşif işlerinde hız.

**Tek-agent lehine:**
- [Cognition — *Don't Build Multi-Agents*](https://cognition.com/blog/dont-build-multi-agents):
  karar dağılıyor, bağlam yeterince paylaşılmıyor, sistem kırılganlaşıyor.
- 2026 tablosu: *"multi-agent ile başlamak en yaygın mimari hata"*; tek agent 8–12 araçtan
  sonra bozuluyor; bir örnekte 5 agent → 1 agent: **daha iyi cevap, 4x hız, ¼ maliyet**.
- Çok-agent'a geçiş için üç sinyal: araç aşırı yükü, bağlam tükenmesi, gerçek paralellik.

**Uzlaşma — Cognition'ın güncel formülü:** *"multiple agents contribute intelligence,
writes stay single-threaded."* Çok-agent, alt soruların **bağımsız olduğu ve paylaşılan
durumu değiştirmediği** keşif işlerinde kazanıyor; yazma tek iş parçacığında kalmalı.

**Kaynaklar:** [Cognition — what's working](https://cognition.com/blog/multi-agents-working),
[2026 rehberi](https://www.alexcloudstar.com/blog/multi-agent-vs-single-agent-architecture-2026/),
[MAS empirik değerlendirme](https://arxiv.org/pdf/2601.03328).

---

## F. Güvenilirlik ve abstention ailesi

**Temel fikir:** Yanlış cevap, cevapsızlıktan pahalıdır — çünkü *"akıcı yanlış cevap,
kullanım anında doğrusundan ayırt edilemez."*

| Sistem | Mekanizma |
|---|---|
| **RTS — Reliable Text-to-SQL** | Schema linking aşamasında, modelin *gizli katmanları* üzerinde **conformal** teknik → olasılıksal garanti. Branching Point Prediction hata olasılığını değerlendirir; ya cevapsız kalır ya insana devreder. BIRD'de "near-perfect schema linking"; **küçük modeller büyüklere yaklaşıyor**. |
| **TrustSQL** | *Ceza tabanlı* skor: yanlış cevap, cevapsızlıktan daha çok puan kaybettirir. Doğru teşvik yapısı. |
| **PV-SQL** | Veritabanı *probing* + kural tabanlı doğrulama. |
| **"Never the Number"** | Çıktısı *gerçek olarak tüketilen* sistemler için yapısal abstention. |
| **Semantic layer** | Katman dışı → hata (bkz. C). |

**Ortak sonuç:** Abstention prompt'la değil, **yapısal olarak** kurulmalı. Model "emin
değilim" demeyi öğrenmez; sistem emin olmadığı yerde cevap üretemez hale getirilir.

**Kaynaklar:** [RTS](https://arxiv.org/pdf/2501.10858), [TrustSQL](https://arxiv.org/pdf/2403.15879),
[PV-SQL](https://arxiv.org/html/2604.17653v1), [Never the Number](https://arxiv.org/html/2608.13926).

---

## G. Zaman serisi agent'ları

**Temel bulgu:** *"Tek bir genel amaçlı LLM, uzun sayısal girdiler ve changepoint analizi
gibi hassas istatistiksel işlemler üzerinde sınırlı kontrol sağlar."* Yani sayıları modele
okutup "anomali var mı?" diye sormak çalışmıyor.

**Çalışan desen — iş bölümü:**

```
istatistik  →  tespit         (ensemble: 10 changepoint algoritması)
LLM         →  açıklama       (tespit edilen kırılmayı gerçek olaylarla bağla)
RAG         →  bağlam         (özel dokümanlardan neden)
```

| Sistem | Ayırt edici |
|---|---|
| **LLM-Augmented Changepoint** | 10 algoritmalık ensemble tespit; LLM yalnız açıklama + nedensel atıf; RAG ile özel veri. Finans, siyaset bilimi, çevre. |
| **SAGE** | Çok-agent: uzman analizörler (trend, mevsimsellik, aykırı) + sentez. |
| **CALM** | Sürekli, adaptif, LLM-aracılı akış anomali tespiti. |
| **Argos** | LLM ile *otonom kural üretimi*. |
| **TraceBench** | Kök-neden atfı için kontrollü değerlendirme. |

**Survey taksonomisi** ([2509.11575](https://arxiv.org/pdf/2509.11575)): LLM'in rolü üçe
ayrılıyor — **tool-caller** (dış sistemleri yönetir), **reasoner** (zamansal örüntü
üzerinde çıkarım), **explainer** (yorumlanabilir anlatı). Akıl yürütme topolojisi:
doğrudan / doğrusal zincir / dallı. Açık problemler: sadakat, maliyet-tekrarlanabilirlik
dengesi, dağılım kayması altında benchmark.

**Kaynaklar:** [LLM-Augmented Changepoint](https://arxiv.org/pdf/2601.02957),
[SAGE](https://arxiv.org/html/2605.05725v1), [TS agents survey](https://arxiv.org/html/2608.26226).

---

## H. Retrieval ailesi

Daha önce ayrıntılı bakıldı (ADR-0013, 0015). Özet:

- Seçilmiş şema > tam şema: **+5,4–5,8 puan**
- Araç retrieval: tam katalog %13,6 → filtreli **%43,1**; prompt token yarıya
- Araç sayısı 4 → 51 olunca doğruluk %43 → **%2** (Berkeley)
- **Hibrit > saf semantik** — şema/araç dokümantasyonunda kesin terminoloji var,
  keyword orada embedding'i yeniyor
- Bizim ölçümümüz aynı yönde: `ILIKE` filtresi bi-encoder'dan iyi çıktı

Ek: **Constraint tax** ([2606.25605](https://arxiv.org/pdf/2606.25605)) — yapılandırılmış
çıktı kısıtları tool-calling'i bastırabiliyor. Constrained decoding ölçmeden uygulanmamalı.

---

## I. Üretim sistemleri

| Sistem | Mimari | Ders |
|---|---|---|
| **Uber QueryGPT** | Intent Agent → Workspaces (alan başına küratörlü tablo+örnek SQL) → Table Agent → Column Prune Agent → üretim | %70 süre azalması (10 dk → 3 dk). Her adım dar bir işten sorumlu, çıktısı doğrulanıyor. |
| **LinkedIn SQL Bot** | 300+ haftalık kullanıcı | *"Prompting'den fazlası gerekir: retrieval, ranking, validation, optimization."* Kullanıcı zaten SQL biliyorsa hata ayıklama yardımı, sıfırdan üretim değil. |
| **Databricks / Snowflake** | Semantic layer + governance + memory | *"Agent'lar hazır, mimariniz muhtemelen değil."* Enterprise önce veri tanımları, izinler, semantik, sonra agent. Bellek olmadan agent bağlamı kaybeder, hataları tekrarlar. |

**Kaynaklar:** [Uber](https://www.uber.com/en-ES/blog/query-gpt/), [LinkedIn](https://www.getdot.ai/blog/linkedin-sql-bot-data-agent),
[Databricks](https://www.databricks.com/blog/agents-are-ready-your-architecture-probably-isnt).

---

## Aileleri ayıran eksenler

| Eksen | Uç 1 | Uç 2 | Bizim konum |
|---|---|---|---|
| **LLM ne üretir** | ham SQL / kod (A, B) | metrik seçimi (C) | SQL, ama katalogla kısıtlı; `add_column` yapısal |
| **Ne zaman düşünür** | her adım (ReAct) | bir kez (ReWOO) | ReAct; plan-then-execute tetikleyicili |
| **Kaç iş parçacığı** | tek (Cognition) | çok (MAG-SQL) | tek; alt-agent = araç |
| **Hata karşısında** | düzeltir (self-correction) | cevapsız kalır (abstention) | ikisi: onarım döngüsü + yapısal ret |
| **Şema nasıl gelir** | tam | retrieval | keyword retrieval; embedding ertelendi |
| **Zaman serisi** | LLM sayı okur | istatistik tespit, LLM açıklar | ikincisi (planlı) |
| **Güven** | "kaynak: X" | hücre düzeyi provenance | sütun düzeyi, artifact hash'e bağlanacak |

---

## Bize ne söylüyor

**Hangi ailedeyiz:** A (pipeline) + F (abstention) + H (retrieval) kesişimi, D'de ReAct.
B'yi (kod üretimi) bilinçli olarak almadık: esneklik kazancı, "doğru pandas yanlış soru"
riskine ve sandbox maliyetine değmiyor; ihtiyaç duyulan istatistik, ayrı deterministik
araçlar olarak geliyor (G ailesi deseni).

**Her aileden aldığımız:**
- **A**'dan: modüler pipeline, schema linking. XiYan'ın multi-generator fikri ileride
  "birden çok SQL adayı üret, çalıştır, tutarlı olanı seç" olarak denenebilir.
- **C**'den: semantic catalog (`measure_type`, `unit`, `aliases`) ve **yapısal
  abstention** — kapsam kontrolü, dönem filtresi reddi bunun uygulaması.
- **D**'den: ReAct şimdi; plan-then-execute adım sayısı 12'yi geçince.
- **E**'den: tek iş parçacığı, yazma tek sahipli, alt-agent yalnız bağımsız keşif için.
- **F**'den: TrustSQL'in ceza fikri golden set'e taşınabilir — halüsinasyon, cevapsızlıktan
  daha ağır sayılmalı. RTS'in conformal yaklaşımı ilginç ama gizli katman erişimi gerektiriyor,
  MIA'da yok.
- **G**'den: anomali/changepoint/causality araçlarında **LLM yok**; ensemble tespit +
  LLM açıklama + web search ile bağlam. Transkriptteki *"o dönemde ne olmuş"* sorusunun
  cevabı tam bu desen.
- **H**'den: hibrit retrieval, embedding'i katalog büyüyünce.
- **I**'dan: Uber'in Column Prune adımı (bizde value pruning olacak), LinkedIn'in
  "prompting yetmez" dersi.

**Neyi almadık ve neden:**
- Kod üretimi (B): güvenlik ve determinizm.
- Orchestrator LLM (E): her soruya ekstra tur, bugünkü sorunlarımız yönlendirme sorunu değil.
- Saf embedding retrieval (H): ölçüldü, keyword'den kötü.
- Persona prompting: ölçüldü, etkisiz (EMNLP 2024).
- Constrained decoding: constraint tax ölçülmeden değil.

**Literatürün bizden istemediği ama şartnamenin istediği:** jeneriklik. Hiçbir aile
"içi boşaltılıp başka alanda çalışsın" diye tasarlanmamış; hepsi tek alan varsayıyor.
`DomainProfile` + katalogdan türeyen bağlam bu boşluğu dolduruyor ve ayrışma noktası.
