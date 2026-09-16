# Kullanıcı Hatası, Yanlış Kullanım ve Sessiz Semantik Hata — Araştırma, Adversarial Test ve Mimari Evrim

**Tarih:** 14 Eylül 2026 · **Dal:** `feature/busra/agent-v3` (Baran'ın `ab87563` merge'i dâhil) · **Yazar:** Büşra (Claude ile)
**Soru:** *Kullanıcı yanlış dosya, yanlış varsayım, yanlış dönem, yanlış terim getirirse — sistem "matematiksel olarak doğru ama niyet açısından yanlış" bir cevabı ne kadar erken yakalar?*

Kanıt etiketleri: `[PAPER]` hakemli/arXiv makale · `[USER STUDY]` kullanıcı deneyi · `[POSTMORTEM]` gerçek olay/GitHub issue · `[OSS]` açık kaynak uygulama · `[DOC]` resmî ürün belgesi · `[ANECDOTAL]` forum/blog · `[OUR EXPERIMENT]` bu çalışmada ölçüldü · `[SRC]` depodaki kod · `[ORG]` organizatör/mentör · `[INF]` çıkarım · `[REC]` öneri.
Depodaki koda yapılan atıflar `dosya:satır` biçimindedir ve 14 Eylül ağacına göre doğrulanmıştır.

Ölçüm dosyaları: `docs/experiments/ueb_baseline_2026-09-14_*.json|md` (54 vaka, canlı MIA), `docs/experiments/ueb_wrongfile_ablation_2026-09-14.json` (12 soru × 28 dosya, 10 kol). Betikler: `scripts/ueb_fixtures.py`, `scripts/ueb_cases.py`, `scripts/ueb_run.py`, `scripts/ueb_wrongfile_ablation.py`.

> **DURUM (16 Eylül — P0 tamamlandı, PART 42):** `check_premise` (öncül yönü veriden), `clarify` (uygunluk "kısmen" iken tek soru, turu bitirir), G5/G6 iddia–hücre ve aralık beyanı (`core/claim_check.py`), golden G12a–f (canlı 6/6), Windows yerel yol düzeltmesi. İkinci tam UEB koşusu (`ueb_after2_2026-09-15_0110`): sessiz **0/37** (otomatik de 0), SAFE 35 / PARTIAL 2, kontrol **18/18**, aşırı bloklama 0, ort. 12,1 s; A24 PASS, A07 SAFE, B02 SAFE. Üçüncü koşu (`ueb_after3_2026-09-15_0124`): sessiz 1 (B06 — bin/milyon ölçek; `builder/quality.py` bayrağı eklendi). Dördüncü koşu (`ueb_after4_2026-09-15_0142`, düzeltme sonrası tam 55): B06 SAFE, sessiz 2 (A07 yapay; A08 "puan" — ön-koşul satırı eklendi, A08 canlı 2/2 SAFE), kontrol 18/18. Üç koşuda 50/55 katı kararlı, 52/55 hiç sessiz değil. PR bu oturumda açıldı.
>
> **DURUM (15 Eylül akşamı — P0 uygulandı ve ölçüldü, PART 40):** uygunluk kapısı + tablo kalitesi + soru ön-koşulu + kapsam beyanı kodda (`core/fitness.py`, `builder/quality.py`, `core/question_preflight.py`; `web_url`/`ingest`/ajan kancaları). Uçtan uca "sonra": elle sessiz **0/37** (önce 3), otomatik 1 (yapay), aşırı bloklama 0, kontrol 17/18 (A24 gerileme: 10 satırlık sorgu kartı önizlemesi, kapı dışı; baseline da 17/18, A26). Önizleme kuralı sonra PART 41 ile düzeltildi (`core/preview.py`, ≤24 satır tamamı; A24 canlı tekrarında PASS). Kalan: `check_premise`, G5/G6, golden'lar, `clarify`, ikinci koşu.
>
> **DURUM (15 Eylül sabahı — rapor tamamlandı):** 38 bölüm; iki deney (55 vakalık UEB ×2 koşu, 336 çiftlik ablation), çevrimdışı "sonra" projeksiyonu. Sonuç sayıları PART 19–22'de; öneri PART 30 (Mimari B), yol haritası PART 37. Kural setinin aynı sette ayarlandığı ve "sonra"nın uçtan uca ölçüm olmadığı her yerde işaretlidir.
>
> **Özet sayılar:** korumalı 37 vakada sessiz hata run 1 = 3 (%8,1; şiddet ağırlıklı %8,8), run 2 = 2 (%5,4); pass² %89; kontrol 18/18, aşırı bloklama 0. Tespitlerin 26/37'si yalnız modele bağlı. Yanlış-dosya: mevcut ilgi kapısı hard-negative ret %6, embedding ayıramıyor, deterministik gereksinim sözleşmesi %98 ret / %92 kabul (iyimser), kademeli LLM 12 çağrı. Çevrimdışı deterministik denetimler sessiz/geç 4 vakanın 4'ünde tetiklendi, kontrollerde 0.

---

## PART 1 — Executive Summary

*(Sayısal özet PART 19–22 tamamlandığında bu bölümün sonundaki tabloya işlenir; aşağıdaki bulgular ölçümlerden bağımsız olarak doğrulanmıştır.)*

1. **Sistem bugün "hata yaparsa" iyi korunuyor, "kullanıcı hata yaparsa" büyük ölçüde LLM'in dikkatine bağlı.** Deterministik kapılar (kapsam, dönem filtresi, frekans, alt toplam, grounding, niyet, erişim) sistem hatalarını yakalamak için tasarlandı; kullanıcı-niyet ↔ veri-anlam uyuşmazlığını yakalayan tek deterministik parça 13 Eylül'de yazılan ilgi kapısı (`builder/relevance.py`) ve o yalnız `ingest_from_url` yolunda; `web_url` ile yüklenen dosya (jürinin "şu dosyadan" akışı) hiçbir ilgi kontrolünden geçmiyor `[SRC]` (`tools/web.py:121-243`).
2. **En tehlikeli sınıf "anlamca yakın yanlış veri"dir ve embedding benzerliği bunu ayıramıyor** `[OUR EXPERIMENT]`: 12 soru × 28 dosyada, doğru dosyaların en düşük kosinüsü (0,51) ile hard-negative'lerin en yükseği (0,79) örtüşüyor; hiçbir eşik ikisini ayırmıyor (PART 14). Deterministik "gereksinim sözleşmesi" (soru → gerekli ölçüm/varlık kavramları → dosyada var mı) aynı sette hard-negative'lerin %98'ini reddediyor, doğru dosyayı %92 kabul ediyor — kural seti aynı sette ayarlandı, dış geçerlilik ölçülmedi.
3. **Mevcut ilgi kapısı (13 Eylül) çok gevşek**: hard-negative'lerin %6'sını, ilgisiz dosyaların %28'ini reddediyor `[OUR EXPERIMENT]`. Tasarım gereği "hiçbir ölçüt tutmazsa" tetikleniyor; "kredi" kökü "kredi kartı"nı da geçiriyor. Bu bir hata değil, kapsam kararıydı; artık yetersiz olduğu ölçüldü.
4. **Literatürün en güçlü iki mesajı birbirine zıt yönde çekiyor:** (a) LLM'ler belirsizliği tanısa bile soru sormuyor (Su & Cardie 2026 `[PAPER]`), yanlış öncülleri açıkça reddetmiyor (FalseQA `[PAPER]`), kendi güvenlerini abartıyor (Xiong 2024 `[PAPER]`) → validator LLM olamaz; (b) uyarı yorgunluğu gerçek: klinik karar desteğinde uyarıların %46–96'sı geçiliyor (Ray-Wilson 2026 sistematik derleme `[PAPER]`), açıklamalar aşırı güveni artırabiliyor (Bansal 2021 `[USER STUDY]`) → her şeyi uyarıya çevirmek de çözüm değil. Çıkış: **az sayıda, deterministik, kanıt gösteren, seçici** kapı.
5. **Önerilen mimari değişiklik küçük ve ölçülebilir:** tek yeni deterministik modül (`core/fitness.py`: soru gereksinimi × veri imzası → 6 boyutlu uyum + PROCEED/WARN/CLARIFY/STOP politikası), `web_url` ve `ingest_from_url`'in önüne aynı kapı, cevap-öncesi "kapsam beyanı" satırı, öncül kontrolü için tek deterministik araç (`check_premise`), `clarify` aracı. Yeni ajan yok, yeni LLM çağrısı yalnız "kısmen" durumunda (ablation: çiftlerin ~%15'i). Ayrıntı PART 30–37.

---

## PART 2 — Araştırma Yöntemi

| Kaynak türü | Ne yapıldı | Nerede |
|---|---|---|
| Depo | 31 modül okundu (`core/*`, `tools/*`, `builder/*`, `web/*`, `adapters/duckdb_lakehouse.py`), 18 golden vaka, ADR-0028…0048 başlıkları, V3 §3.9 | PART 9 |
| Literatür | HCI/human factors (otomasyon önyargısı, güven kalibrasyonu, uyarı yorgunluğu, bilişsel zorlama), NLP (belirsizlik, yanlış öncül, çekimserlik, NL2SQL semantik hata), veri mühendisliği (veri doğrulama, gözlemlenebilirlik, veri sözleşmeleri, şema eşleme, semantik tip), IR (negasyon, hard-negative) — 40+ kaynak, hepsi URL ile PART 38'de | PART 3 |
| Gerçek sistemler | Snowflake Cortex Analyst, Databricks Genie, Power BI Copilot, Looker, dbt Semantic Layer, Great Expectations/Deequ/TFDV, Monte Carlo, FRED/ALFRED | PART 4 |
| Arıza raporları | PHE Excel kesmesi (2020), Reinhart-Rogoff (2013), JPMorgan London Whale (2012), Ziemann gen adı (2016/2021), LangChain/pandas-ai GitHub issue'ları, pandas leading-zero/dayfirst issue'ları, ChatGPT ADA kullanıcı raporları | PART 5 |
| Deney 1 (UEB) | 54 vakalık kullanıcı-hatası benchmark'ı; 4 kulvar (sorgu / dosya / DB varyantı / yanlış-pozitif kontrolü); canlı MIA, seed DB + 4 DB varyantı + 18 fikstür | PART 18–22 |
| Deney 2 (ablation) | Yanlış-dosya tespiti, 10 kol, 336 (soru, dosya) çifti; R/H/I altın etiket | PART 14, 20 |

Sınırlar: (a) Seed DB tek tablo (BDDK aylık krediler); Silver/gerçek katalogda ingest yolu bu makinede kapalı (`LAKEHOUSE_CORE_DIR` yok) → `ingest_from_url` ve ilgi kapısı uçtan uca değil, birim testleri ve ablation ile ölçüldü. (b) Benchmark vakaları ve altın etiketler tek kişi tarafından yazıldı. (c) Otomatik sınıflama anahtar sözcükle; her vaka elle de okundu (PART 19). (d) Deterministik kol aynı sette 3 turda ayarlandı → iyimser.

---

## PART 3 — Literatür İncelemesi

### 3.1 İnsan hatası ve otomasyon: neden "uyarı ekle" yetmez

- **Otomasyon önyargısı ve rehavet** — Parasuraman & Manzey 2010 `[PAPER]`: karar desteği kusurluyken kullanıcılar hem *ihmal* (uyarı yokken hatayı görmeme) hem *komisyon* (yanlış öneriyi uygulama) hatası yapar; bu hem acemide hem uzmanda görülür ve eğitimle giderilemez. Bizim bağlam: "AI hesapladıysa doğrudur" (brief §110) bir varsayım değil, ölçülmüş bir davranış.
- **Güven kalibrasyonu** — Lee & See 2004 `[PAPER]`: uygun güven, güvenin sistemin gerçek güvenilirliğiyle örtüşmesidir; hem aşırı güven hem yetersiz güven maliyetlidir. **Algoritma kaçınması** — Dietvorst, Simmons & Massey 2015 `[USER STUDY]`: insanlar algoritmayı *bir kez* hata yaparken gördükten sonra ondan, aynı hatayı yapan insandan daha hızlı vazgeçer; algoritmanın çıktısını *biraz değiştirebilmek* kaçınmayı azaltır (2016). Bizim bağlam: yanlış-pozitif bir engelleme, sessiz bir hatadan daha görünürdür ve güveni daha hızlı yıkabilir → yanlış-pozitif oranı birinci sınıf metrik olmalı (PART 22).
- **Açıklama aşırı güveni artırabilir** — Bansal ve ark. 2021 (CHI) `[USER STUDY]`: açıklamalar, öneri doğru ya da yanlış olsun, kabul oranını artırdı; tamamlayıcı performans sağlamadı. **Bilişsel zorlama** — Buçinca, Malaya & Gajos 2021 `[USER STUDY]`: kullanıcıyı önce kendi kararını vermeye zorlayan tasarımlar aşırı güveni en çok azalttı ama en düşük memnuniyeti aldı. Bizim bağlam: "doğru dosya bu mu?" sorusu bilişsel zorlamadır; sık kullanılırsa memnuniyet düşer → yalnız yüksek etkili durumlarda.
- **Uyarı yorgunluğu** — Ray-Wilson ve ark. 2026 (JAMIA sistematik derleme) `[PAPER]`: klinik karar desteği uyarılarında geçme (override) oranı %46–96; yalnız bir makale uyarı yorgunluğunu işlemsel tanımlamış. Öneri: "uygun uyarıya tepki oranında kalıcı düşüş" ölçülsün. Bizim bağlam: uyarı sayısı değil, *uyarı başına eylem oranı* izlenmeli; sistem her cevaba 3 uyarı satırı eklerse hiçbiri okunmaz.

### 3.2 Belirsizlik, yanlış öncül ve çekimserlik: LLM'in kendisi kapı olamaz

- **Tanıyor ama sormuyor** — Su & Cardie 2026 `[PAPER]`: modeller açıkça sorulduğunda belirsizliği tanıyor; soru-cevap ortamında ise ezici çoğunlukla doğrudan cevap veriyor; *bağlam (retrieval) verildikçe soru sorma eğilimi daha da düşüyor*. Bizim bağlam: ön-yüklenen katalog kartları modeli "cevaplamaya" iter; L10-01 (belirsiz soru) iki motorda da düşüyor `[SRC]` (`docs/BENCHMARK_PROTOCOL.md §3`) — bu literatürle tutarlı.
- **Yanlış öncül** — FalseQA (Hu ve ark. 2023) `[PAPER]`: modeller yanlış öncülü kısmen fark ediyor ama açıkça reddetmiyor; "Judge Before Answer" (2025) çok modlu modellerde aynı; AbstentionBench (2025) `[PAPER]`: 20 veri setinde çekimserlik "çözülmemiş, ölçekle düzelmeyen" bir sorun; akıl yürütme modelleri çekimserlikte daha kötü.
- **Sözlü güven kalibre değil** — Xiong ve ark. 2024 (ICLR) `[PAPER]`: sözlü güven %80–100 bandında, 5'in katlarında kümeleniyor ve doğruluğu çok aşıyor. Bizim bağlam: brief §90 doğru — `confidence = 0.93` üretmeyeceğiz; gözlemlenebilir sinyallerden kategorik durum.
- **Seçici tahmin** — El-Yaniv & Wiener 2010 (risk–kapsam eğrisi) `[PAPER]`; Kamath, Jia & Liang 2020 `[PAPER]`: alan kayması altında softmax güveni işe yaramıyor, ayrı bir *kalibratör* eğitmek gerekiyor. Bizim bağlam: "kapsam" (cevap verilen soru oranı) ile "risk" (yanlış cevap oranı) birlikte raporlanmalı; PART 21'deki "sessiz hata oranı" risk eksenidir, "gereksiz soru oranı" kapsam eksenidir.
- **Ne zaman sorulmalı** — SAGE-Agent (2025) `[PAPER]`: soruyu bilgi değeri (EVPI) − maliyet ile seçince belirsiz görevlerde kapsam %7–39 artıyor, soru sayısı 1,5–2,7× azalıyor; "Ask or Assume?" (2026) `[PAPER]` kodlama ajanlarında aynı. Çıkarım: soru sormanın kendisi bir eylemdir, maliyeti ve getirisi vardır; politika bunu açıkça modellemeli (PART 15).
- **NL2SQL'de semantik hata** — NL2SQL-BUGs (KDD 2025) `[PAPER]`: 2.018 uzman etiketli örnek, 9 ana / 31 alt kategori; LLM'ler semantik hatayı ortalama %75,16 tespit ediyor; BIRD'de 106 (%6,91) daha önce fark edilmemiş etiket hatası buldular. TrustSQL (2024) `[PAPER]`: "yardım − ceza × zarar" güvenilirlik puanıyla yalnız birkaç model pozitif çıkıyor. "Query Carefully" (2025) `[PAPER]`: cevaplanamaz soru tespiti yapısal sınıflarda (şema dışı, SQL dışı) neredeyse mükemmel, **kolon belirsizliğinde 0,3** — tam bizim "RATE hangi oran?" sorunumuz. Reliable Text-to-SQL with Adaptive Abstention (PACMMOD 2025) `[PAPER]`: şema bağlama aşamasında konformal tahminle çekimserlik. TriageSQL (2020) `[PAPER]`: dört cevaplanamaz sınıf (belirsiz, uygunsuz, dış bilgi, SQL dışı), RoBERTa F1 0,60. Çıkarım: cevaplanabilirlik sınıflaması (brief §88) literatürde var ve zor kısmı tam bizim kısım (belirsiz kolon/kavram).

### 3.3 Veri kalitesi, doğrulama, gözlemlenebilirlik

- **Sessiz veri hatası** — Polyzotis, Zinkevich, Roy, Breck & Whang 2019 (MLSys) `[PAPER]`: Google'da 700+ boru hattı; log biçimindeki küçük değişiklik (yeni kolon, beklenmedik değer) modeli *sessizce* bozuyor; şema + dağılım + eğitim/servis kayması denetimi. TFDV/Deequ/Great Expectations (2024–2025 `[OSS]`): beyan edilen kısıtlar (aralık, satır sayısı, tazelik, benzersizlik, ilişki). dbt'nin dört temel testi `unique, not_null, accepted_values, relationships`, `dbt-expectations` ile tazelik ve satır sayısı `[OSS]`. Çıkarım: "veri seti imzası"nın deterministik yarısı (PART 13) zaten endüstri standardı; yeni olan, bunu **soruyla** karşılaştırmak.
- **Beş sütun** — Monte Carlo: tazelik, hacim, şema, dağılım, soy `[DOC]`. Bizim taksonomideki E13/E14/E16/E18 doğrudan tazelik+hacim, E37/E43 dağılım, E44/E47 soy.
- **Veri hazırlığı** — Lawrence 2017 `[PAPER]`: Bant C (varlığı söylenen), B (erişilebilir ama doğrulanmamış), A (analize hazır). Brief §89'daki "PARTIALLY READY" fikri buradan; ama Lawrence bantları *analizden bağımsız*; bizim ihtiyacımız *soruya göre* hazırlık (PART 12).
- **Veri sözleşmeleri / şema kayması** — Sanderson (2022–2025) `[ANECDOTAL/DOC]`: üretici–tüketici arasında şema+anlam sözleşmesi, CI'da zorlanır. **Kavram kayması** — Gama ve ark. 2014 `[PAPER]`. Bizim bağlam: kullanıcının getirdiği dosya bir "sözleşmesiz üretici"dir; sözleşme yerine imza çıkarılır.
- **Veri revizyonu / vintage** — FRED/ALFRED `[DOC]`: her gözlemin `date, realtime_start, realtime_end` üçlüsü; aynı dönem için farklı "vintage"lar. Bizim bağlam: E13 (eski sürüm) ve E47 (çelişen kaynak) için doğru kavram "vintage"; `crosscheck.py`'nin %3 farkı "ÇELİŞİYOR" demesi bir revizyonu da yakalar — bu istenen davranış (fark söylenir, biri sessizce seçilmez).
- **Şema eşleme / semantik tip** — Rahm & Bernstein 2001, Valentine (Koutras 2021, ICDE) `[PAPER]`; Sherlock (KDD 2019, 78 tip, F1 0,89), Sato (VLDB 2020, tablo bağlamı), Doduo (2021) `[PAPER]`. Çıkarım: kolon anlamını başlıktan değil *değerlerden* çıkarmak literatürde olgun; ama 78 DBpedia tipi (isim, şehir, tarih) bizim "faiz oranı mı takip oranı mı" sorusunu çözmez → makullük aralığı (oran ∈ [−100, 1000]) gibi *ölçüm tipi* düzeyi gerekir (`builder/profile.py:_infer_measure_type` zaten bunu yapıyor `[SRC]`).
- **Boyut/birim çıkarımı** — UCheck (Abraham & Erwig 2007), Chambers & Erwig 2008/2009 `[PAPER]`: başlıklardan birim/boyut çıkarıp formüllerdeki uyuşmazlığı bulma. Çıkarım: "milyon TL + bin TL" toplamı bir *boyut hatası*dır ve statik olarak yakalanır; bizde `crosscheck.py`'nin ×10^k ölçek tespiti bunun veriye dayalı versiyonu.

### 3.4 Retrieval: benzerlik ≠ uygunluk

- **Negasyon** — NevIR (Weller ve ark. 2023; reprodüksiyon SIGIR 2025) `[PAPER]`: çoğu IR modeli negasyonda rastgele sıralamanın altında; en iyi bi-encoder %39. "Konut kredisi, fiyat endeksi değil" sorgusunu embedding tersine çevirebilir. Bizim ölçüm (PART 14) aynı yönde: Q11/Q12 (negasyonlu) fikstürleri `tests/benchmark/retrieval_audit_fixture.json`'da zaten var `[SRC]`.
- **Tablo retrieval** — Herzig ve ark. 2021 (NQ-Tables) `[PAPER]`; Wang ve ark. 2022 "tabloya özel model gerekmeyebilir" `[PAPER]`. Çıkarım: dosya seçiminde BM25 güçlü (bizde top-1 0,92) ama *seçim* ile *reddetme* farklı işler; BM25 skoru "en iyi aday" verir, "yeterince iyi mi" demez.
- **Semantic layer LLM doğruluğunu ne kadar artırıyor** — Paired benchmark (arXiv 2604.25149) `[PAPER]`: 100 soru, 3 model; yalnız şema %45–51, 4 KB'lık ölçüm/kural belgesiyle %68–69 (+17–23 puan, p<0,01); model seçimi anlamsızlaşıyor. dbt 2026 `[DOC]`: kapsanan sorgularda ~%100. Çıkarım: "gereksinim sözleşmesi"nin kavram sözlüğü tam olarak bu belgedir; bizde `ColumnSpec.aliases` + `measure_rules` (`domain/finance.md`) bunun tohumu `[SRC]`.

### 3.5 LLM-yargıç güvenilirliği

Zheng ve ark. 2023, "Self-preference bias" (2024), "Judging the Judges" (2026) `[PAPER]`: konum, uzunluk ve kendini tercih önyargıları; yüksek güvenle yanlış hükümler. Çıkarım: validator LLM'i tek başına değil, deterministik kapının "kısmen" dediği dar bantta ve gerekçesi kaydedilerek (PART 17, kol I).

---

## PART 4 — Gerçek Sistemler

| Sistem | Yanlış veri/soru için mekanizma | Kaynak | Bizim için ders |
|---|---|---|---|
| Databricks Genie | **Trusted assets**: önceden onaylı parametrik SQL/UDF; eşleşen cevap "güvenilir" etiketiyle döner; eşleşmeyen için model serbest; kullanıcı netleştirmesiyle yinelemeli | `[DOC]` docs.databricks.com/genie/trusted-assets | "Doğrulanmış sorgu" = bizim `verified-query replay cache` (V3 §3.6); etiketleme kullanıcıya güven *farkını* gösteriyor |
| Snowflake Cortex Analyst | Semantic model (YAML) + verified query repository; belirsiz sorularda netleştirme | `[ANECDOTAL]` karşılaştırma yazıları; resmî belge doğrudan bulunamadı | Aynı kalıp; `[ASM]` olarak işaretli |
| Power BI Copilot | **Verified answers**: insan onaylı görsel + tetikleyici ifadeler + filtreler, semantic modelde saklanır | `[DOC]` learn.microsoft.com/power-bi/.../copilot-prepare-data-ai-verified-answers | Onaylı cevap havuzu; bizde golden set + replay cache karşılığı |
| Looker | **Symmetric aggregates**: join fan-out'ta çift sayımı `SUM(DISTINCT hash)` hilesiyle engeller; `symmetric_aggregates` explore parametresi | `[DOC]` cloud.google.com/looker/docs/reference/param-explore-symmetric-aggregates | Join güvenliği modelde çözülür, kullanıcıya bırakılmaz; bizde `gold_join` dış birleştirme + `JOIN_MISMATCH`; çoktan-çoğa denetimi yok (PART 10) |
| dbt Semantic Layer | Deterministik SQL üretimi: metrik tanımı katalogda; LLM yalnız metrik seçer | `[DOC]` docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026 | `gold_*` araçları aynı ilke (kural katalogdan) `[SRC]` |
| Great Expectations / Deequ / TFDV | Beyan edilen kısıtlar; tazelik/hacim/şema/dağılım | `[OSS]` | Veri seti imzasının deterministik yarısı |
| Monte Carlo | Beş sütun; tazelik ve hacim anomalisi | `[DOC]` | E14/E16 için "beklenen satır sayısı / beklenen son tarih" |
| FRED/ALFRED | Vintage tarihli gözlem | `[DOC]` | E13/E47 için revizyon dili |
| ChatGPT ADA / Julius | Önizleme adımı yok; "parse edip başlıyor"; yanlış kolonu toplama, tarih yanlış ayrıştırma, satır düşürme, yöntem değişikliğini söylememe | `[ANECDOTAL]` Efron (Medium), cfoimpulse, digitaldialog | Tam olarak brief'in "no exception + valid calculation + wrong meaning" zinciri; bizde eşleme önerisi + kanıt (ADR-0030) bunu kapatır ama yalnız ingest'te |

Not: ThoughtSpot Spotter ve Tableau Agent için resmî "yanlış veri" mekanizması bulunamadı; pazarlama metinleri "governed semantics" diyor, ölçülebilir davranış belirtmiyor `[ANECDOTAL]`.

---

## PART 5 — Arıza Raporları (gerçek olaylar)

| Olay | Mekanizma | Neden sessizdi | Taksonomi |
|---|---|---|---|
| **PHE COVID vaka kaybı (Eki 2020)** `[POSTMORTEM]`: 15.841 pozitif test 25 Eyl–2 Ekim arasında raporlanmadı; laboratuvar CSV'leri `.xls`'e (65.536 satır) aktarılırken taşan satırlar **hatasız düştü**; günlük sayılar 3.049/4.133/4.786 eksik göründü ve artış yavaşlıyor sanıldı | biçim sınırı | Parse başarılı, satır sayısı kimse tarafından beklenen sayıyla karşılaştırılmadı | E16 kesik veri, E14 |
| **Reinhart-Rogoff (2013)** `[POSTMORTEM]`: AVERAGE aralığı 5 ülkeyi dışarıda bıraktı (20 yerine 15); −%0,1 → +%2,2 | formül aralığı | Sonuç makul, tartışılmış, politika belgesi oldu | E49/E52 seçim hatası; makullük yok |
| **JPMorgan London Whale (2012)** `[POSTMORTEM]`: VaR modelinde SUM/AVERAGE karışıklığı, elle kopyala-yapıştır; 6 milyar $ | formül | Risk *düşük* göründü; kimse "neden yarıya indi" diye sormadı | E52; büyüklük kayması makullük kontrolü |
| **Excel gen adı (Ziemann 2016; 2021 "Lessons not learned")** `[POSTMORTEM]`: 35.175 ek dosyada 704 makalede gen adı tarihe dönüştü; 2021'de gen listeli makalelerin %30,9'unda | otomatik tip dönüşümü | Dosya açılıyor, değer "geçerli" tarih | E42/E43 tip dönüşümü |
| **pandas leading zero** (#46895, #54665) `[POSTMORTEM]`: `00123` → `123`; posta kodu, hesap no, FIPS | tip çıkarımı | Join sessizce boş/yanlış | E42 |
| **pandas dayfirst** (#47907, #50231, #53355, #57521) `[POSTMORTEM]`: `01/02/2026` belirsiz; uyarı verilse de kullanıcı "bir şey yapamıyor" | tarih | Tarih geçerli ama yanlış ay | E20 |
| **LangChain SQL agent** (#12458, #18495) `[POSTMORTEM]`: şemayı okumadan olmayan tablo/kolon uydurma; **pandas-ai** (#1179) farklı adlı kolonları join'de uydurma; **pandas agent** (#12925) sonuç yerine kod döndürme | LLM halüsinasyonu | Bazıları hata verir (görünür), bazıları "makul" kolon seçer (sessiz) | E35/E51; bizde referans katmanı bunu hata yapıyor `[SRC]` |
| **ChatGPT ADA kullanıcı raporları** `[ANECDOTAL]`: "Column 4'ü topla" → maliyet 12. kolonda; "impressions"ı "cost" diye toplama; tarih kolonunu yanlış ayrıştırma; encoding'li satırları düşürme; aynı analizde yöntem değiştirip söylememe | yorumlama | Kod doğru, anlam yanlış | E34/E35/E43/E65 |
| **TCMB sayfası "31.51" → 3151** `[OUR EXPERIMENT, 12 Eyl]` `[SRC]` (`web/html.py:141`) | locale | Sayı geçerli | E41 |
| **Model "Kapsam: 2024-01 → 2024-10 (12 satır)"** `[OUR EXPERIMENT, bugün, B01]`: dosya 2024-12'ye kadar; model kartı özetlerken aralığı yanlış yazdı | LLM özetleme | Cevap doğru yöne gitti ama meta-veri cümlesi yanlış | E-yeni: LLM'in kanıtı yanlış aktarması (grounding yalnız sayıları denetliyor, tarih aralığını değil) |

---

## PART 6 — Kullanıcı Hatası Taksonomisi (56 senaryo)

Aşağıda her senaryo için: **mekanizma** (tetikleyici → gerçek girdi), **neden kabul edilir** (sistem neden reddetmez), **neden makul görünür**, **en erken tespit aşaması** (U=upload/erişim, P=profil/imza, I=intent–data uyum, A=analiz önkoşulu, E=yürütme, R=sonuç/cevap), **sinyal**, **yanlış-pozitif riski**, **şiddet** (1–5), **kurtarma**. Brief'teki liste genişletildi; yıldızlı (★) senaryolar brief'te olmayıp literatür/arıza raporlarından eklendi.

| ID | Senaryo | Mekanizma | Neden kabul edilir / makul görünür | En erken | Sinyal | FP riski | Sev | Kurtarma |
|---|---|---|---|---|---|---|---|---|
| E11 | Tamamen yanlış dosya | konut kredisi sorusu → kredi kartı CSV | tarih+sayı var, parse geçer; trend hesaplanır, grafik çizilir | I | soru gereksinimi ∩ dosya kavramları = ∅ | düşük (kavram sözlüğü eksikse orta) | 5 | STOP + "dosyada şunlar var" |
| E12 | Anlamca yakın yanlış dosya | konut kredisi hacmi → konut fiyat endeksi | embedding yüksek; "konut" geçiyor | I | gerekli ÖLÇÜM (bakiye) yok, farklı ölçüm (endeks) var | orta | 5 | STOP + fark açıklaması |
| E13 | Yanlış sürüm (eski/taslak/test) | 2019–21 dosyası 2025 sorusuna; "final_v2" adı | parse geçer | P/I | dönem kapsama; dosya adında taslak/test/eski; vintage farkı katalogla | düşük | 4 | WARN/STOP dönem; DATA_CONFLICT |
| E14 | Bayat veri | "güncel" sorusu, son gözlem 15 ay önce | kapsam guard yıl düzeyinde geçer | I | son gözlem − bugün > frekans×k; "güncel/bugün" sözcüğü | düşük | 4 | WARN: son gözlem tarihi cevapta zorunlu |
| E15 | Kısmi veri | 5 yıl soruldu, 8 ay var | trend yine hesaplanır | I | soru dönemi ⊄ dosya dönemi; kapsanan oran | düşük | 4 | WARN + kapsanan aralık; yıllık büyüme reddi |
| E16 | Kesik veri (export/copy) | PHE: 65.536 satır; son satırlar yok | parse geçer | P | beklenen satır/dönem sayısı ≠ gerçek (frekans×aralık); son dönem eksik; satır sayısı = biçim sınırı | düşük | 4 | WARN + "beklenen 66, var 60" |
| E17 | Yanlış zaman aralığı | "2019–2026", veri 2023+ | filtre uygulanır, 2023+ döner | I | soru yılları − kapsam | düşük | 3 | WARN kapsanan aralık |
| E18 | Eksik dönemler | aylık seride 3 ay yok | LAG farkı "aylık" sanılır | P/A | ardışık tarih farkı > frekans; known_gaps | düşük | 4 | WARN + boşluk listesi; fark hesabı boşluk üstünden yapılmaz |
| E19 | Yanlış frekans | haftalık istendi, aylık var | model aylığı verir | I | soru frekansı < veri frekansı | düşük | 3 | WARN ya da CLARIFY |
| E20 | Tarih yorumu (gg/aa, saat dilimi) | 01/02/2026 | iki biçim de %100 ayrışır | P | belirsiz tarih biçimi | düşük | 3 | CLARIFY (profilci bunu yapıyor `[SRC]`) |
| E21 | Yanlış varlık | "Türkiye" soru, "İstanbul" dosya | sayı var | P/I | tek değerli boyut kolonu; katalog seri adı | orta | 4 | WARN "dosya il=İstanbul'a kısıtlı" |
| E22 | Yanlış nüfus/segment | "tüm bireysel" → "18–25" | aynı | P/I | tek değerli boyut; dosya adı/başlık | orta | 4 | WARN |
| E23 | Yanlış granülarite | müşteri düzeyi istendi, il düzeyi var | aggregate sonuç makul | I/A | istenen kırılım kolonu yok | düşük | 3 | STOP "müşteri kırılımı yok" |
| E24 | Toplulaştırılmış veri ham sanıldı | yıllık dosyadan aylık istendi | yıllık fark verilir | I | frekans; satır sayısı | düşük | 4 | STOP |
| E25 | Örnek/sample tam sanıldı | 5 satır, "ornek" adı | trend çizilir | P/I | satır sayısı ≪ beklenen; ad: sample/ornek/demo/test | orta | 3 | WARN |
| E26 | Sentetik veri gerçek sanıldı ★ | "synthetic/dummy/faker" | değerler makul | P | ad/başlık ipucu; şüpheli düzgünlük (sabit artış) | orta | 3 | WARN |
| E27 | Yanlış birim (0,45 → %45?) | oran/yüzde | her ikisi de makul | P/A | değer aralığı × başlık; katalog birimi | orta | 4 | WARN "oran olarak okundu (%0,14)"; CLARIFY yüksek etki |
| E28 | Yanlış ölçek (bin/milyon) | bin TL dosya milyon sanıldı | sayı büyük ama makul | P | katalogla ×10^k çapraz kontrol (`crosscheck.py` `[SRC]`); başlık | düşük | 5 | WARN + birim sorusu; yazma yok |
| E29 | Yanlış para birimi | TL veri, "kaç dolar" | model kur uydurur | I/R | soruda para birimi ≠ veri birimi | düşük | 4 | STOP çevirme; kur serisi yoksa söyle |
| E30 | Yüzde vs yüzde puanı | "faiz %5 düştü mü 5 puan mı" | ikisi de hesaplanır | A/R | measure_type=rate → pp; anlatıda "puan/yüzde" etiketi | düşük | 4 | ikisini de etiketli ver (`measure_rules`) |
| E31 | Endeks düzeyi vs büyüme | endeks=100 vs %100 | aynı sayı | A/R | measure_type=index; "büyüme" sözcüğü | düşük | 3 | WARN etiket |
| E32 | Nominal vs reel | "reel büyüme", TÜFE yok | nominal verilir | I | "reel/enflasyondan arındır" + deflatör serisi yok | düşük | 5 | STOP ya da nominal+etiket |
| E33 | Stok vs akım | bakiyeyi toplama | SUM çalışır | A | measure_type=stock + SUM (Gold reddediyor `[SRC]`) | düşük | 4 | GOLD_REQUIRED |
| E34 | Yanlış metrik | "müşteri sayısı" → işlem/bakiye | sayı var | I | gerekli ölçüm kavramı (adet) dosyada yok | orta | 4 | STOP |
| E35 | Yanlış kolon yorumu (RATE) | faiz/temerrüt/büyüme/kur | hepsi "rate" | P/I | açıklama/alias; değer aralığı; katalog | orta | 4 | CLARIFY tek soru |
| E36 | Belirsiz kolon | başlık+değerler iki anlama uyar | | P | Sherlock-tipi belirsizlik | orta | 3 | CLARIFY |
| E37 | Yanlış etiketli kolon | "interest_rate" başlıklı, değerler bakiye | başlık retrieval'ı geçer | P | başlık tipi × değer aralığı çelişkisi (oran > 1000) | düşük | 5 | WARN "başlık oran diyor, değerler oran değil" |
| E38 | Yanlış sayfa (xlsx) | ilk sayfa "Notlar" | read_excel sayfa 0 | U/P | sayfa listesi; tarih+sayı kolonu yok | düşük | 3 | CLARIFY hangi sayfa; sayfaları listele |
| E39 | Gizli satır/filtre/toplam satırı/çoklu başlık | "Toplam" satırı ortalamaya girer | parse geçer | P | tarih kolonunda tarih olmayan satır; son satır = kolon toplamı | düşük | 4 | AUTO-FIX (toplam satırını ayır, söyle) |
| E40 | Formül vs gösterilen değer ★ | xlsx cached değer eski | | U | openpyxl data_only farkı | düşük | 2 | WARN |
| E41 | Locale (1.234 / 1,234) | 31,51 → 3151 | sayı geçerli | P | hangi ayraç çifti %100 ayrıştırıyor (`profile.py` `[SRC]`) | düşük | 4 | AUTO-FIX + kanıt satırı |
| E42 | Öndeki sıfır kaybı | 00123 → 123 | | P | metin kolon dtype=str (`_table_from_bytes` `[SRC]`) | düşük | 3 | AUTO-FIX (zaten metin) |
| E43 | Encoding bozulması | "Ä°stanbul" | parse geçer | P | mojibake oranı; `garble_ratio` `[SRC]` | düşük | 2 | AUTO-FIX/WARN |
| E44 | Aynı dosya iki kez | data.csv, data_final.csv | | U/P | içerik sha256; satır parmak izi örtüşmesi | düşük | 3 | AUTO (biri kullanılır, söylenir) |
| E45 | Örtüşen dosyalar | 2021–24 ve 2023–26 | birleşince çift sayım | P/A | dönem örtüşmesi; örtüşen dönemde değer farkı | düşük | 4 | STOP birleştirme; DATA_CONFLICT |
| E46 | Mükerrer satırlar | export tekrarı | SUM/AVG şişer | P | (tarih, entity) tekilliği (`verify.py` `[SRC]`) | düşük | 4 | WARN + tekilleştirme önerisi |
| E47 | Çelişen kaynaklar | dosya vs katalog aynı dönem | | P | crosscheck ÇELİŞİYOR | düşük | 4 | WARN + kaynak beyanı |
| E48 | Kaynak yetkisi | resmî vs kullanıcı düzenlemeli | | U | provenance.source; adhoc/draft etiketi | düşük | 3 | küratörlü varsayılan, açıklama |
| E49 | Yanlış join | doğru iki tablo, yanlış anahtar | sayılar geçerli | A/E | anahtar tekilliği, eşleşme oranı, satır sayısı önce/sonra | düşük | 5 | STOP çoktan-çoğa; JOIN_MISMATCH |
| E50 | Çoktan-çoğa patlaması | satır sayısı katlanır | | E | rows_after > rows_before | düşük | 5 | STOP |
| E51 | Yanlış join anahtarı | aynı ad, farklı anlam | | A | tip/kardinalite uyuşmazlığı; eşleşme %0 | düşük | 4 | STOP |
| E52 | Kullanıcı tipo | 2025 → 2015 | kapsam dışı | I | yıl kapsam dışı ama komşu yıl var | orta | 2 | ABSTAIN + "2025'i mi kastettiniz?" |
| E53 | Terim karışıklığı | faiz/enflasyon/kredi büyümesi/endeks | "faiz" yok, bakiye var | I | gerekli ölçüm yok | orta | 5 | STOP |
| E54 | Yanlış alan varsayımı | "büyüme" (nominal) | | R | etiket | düşük | 3 | etiketli cevap |
| E55 | Yanlış öncül | "faiz düştüğü için" — düşmedi | model öncülü kabul eder | I/A | öncül olgusu deterministik test: seri yönü (`check_premise`) | düşük | 5 | WARN "öncül veriyle uyuşmuyor" |
| E56 | Gömülü nedensellik | "X, Y'ye neden oldu" | | R | nedensellik filtresi `[SRC]`; lead_lag "nedensellik değil" | düşük | 4 | anlatı yeniden üretimi |
| E57 | İmkânsız analiz | korelasyon, tek gözlem | hesap 1 satırla "çalışır" | A | n < min (araç n≥8 `[SRC]`) | düşük | 4 | STOP |
| E58 | Yetersiz örneklem | 6 gözlem korelasyon | r hesaplanır | A | n; anlamlılık | düşük | 4 | WARN "n=6, güvenilir değil" |
| E59 | Eksik değişken | ilişki isteği, tek seri var | | I | gerekli 2 ölçümden 1'i var | düşük | 4 | PARTIAL "ikinci seri gerekli" |
| E60 | Proxy karışıklığı | "konut talebi" → başvuru adedi | | I/R | proxy etiketi | orta | 3 | WARN "proxy olarak" |
| E61 | Yanlış dış kaynak | eski/başka coğrafya sayfa | | U | yıl sayfada geçmiyor (`_year_note` `[SRC]`); ülke/il | düşük | 4 | WARN |
| E62 | İç–dış çelişki | katalog vs web | | R | crosscheck | düşük | 3 | WARN iki değer |
| E63 | Tazelik uyuşmazlığı | iç 2026, dış 2023 | | R | tarih etiketleri | düşük | 3 | WARN |
| E64 | Çok turlu bağlam hatası | "2024 kullan" → sonra 2026 dosyası | eski durum korunur | E | yeni yükleme → workspace/plan geçersizleme | orta | 4 | state invalidation (PART 16) |
| E65 | Dosya değiştirme belirsizliği | yeni yükleme ekler mi değiştirir mi | | U | kullanıcıya tek satır beyan | düşük | 3 | beyan |
| E66 | Kullanıcı düzeltmesi | "yanlış dosya yüklemişim" | önceki sonuç kalır | E | düzeltme kalıbı → bağımlı sonuçlar geçersiz | düşük | 4 | selective invalidation |
| E67 | Niyet değişimi | plan eskir | | E | yeni soru ≠ aktif tablo konusu | orta | 3 | yeni tablo, açıkla |
| E68 | Çoklu niyet | trend + tahmin | tahmin aracı yok | I | niyet listesi × araç kapasitesi | düşük | 4 | kısmi cevap + "tahmin yapılamaz" |
| E69 | Seçim yanlılığı | yalnız alt küme sağlandı | | P | tek değerli boyut; katalogla kapsam farkı | orta | 3 | WARN genelleme |
| E70 | Hayatta kalan yanlılığı | aktif müşteriler | | — | alan bilgisi | yüksek | 2 | domain notu |
| E71 | Kullanıcı etiketi yanlış | "bu dosya konut kredisi" — değil | beyan güvenilir sanılır | I | beyan × dosya kavramları | düşük | 5 | STOP "içerik beyanla uyuşmuyor" |
| E72 | Veri içinde prompt injection | hücrede talimat | | E | DIŞ İÇERİK çerçevesi + niyet kapısı `[SRC]` | düşük | 4 | veri olarak işlenir |
| E73 | Kasıtlı manipülasyon vs kaza | | | — | aynı savunma | — | — | — |
| E74★ | LLM kanıtı yanlış aktarıyor | "kapsam 2024-10" (dosya 2024-12) | grounding yalnız sayı | R | tarih/aralık grounding | düşük | 3 | grounding'e tarih ekle |
| E75★ | Biçim sınırı kesmesi (PHE) | .xls 65.536 | | P | satır sayısı = bilinen sınır | düşük | 4 | WARN |
| E76★ | Otomatik tip dönüşümü (Excel gen adı) | "MARCH1" → tarih | | P | tarih kolonunda tarih-dışı gibi görünen değer; metin kolonunda tarih | orta | 3 | WARN |
| E77★ | Yöntem değişikliğinin söylenmemesi | aynı soru, farklı hesap | | R | provenance farkı iki koşuda | düşük | 3 | replay cache + beyan |
| E78★ | Katalog meta-verisi yanlış | kapsam 2026-06 diyor, veri 2025-03'te bitiyor | kapsam guard geçer, sorgu boş | E | sorgu boş + kapsam "içinde" çelişkisi → gerçek min/max ile karşılaştır | düşük | 5 | WARN + katalog düzeltme kaydı |

56 farklı mekanizma (E11–E78 arasında 68 numara var; birleştirilenler: E44/E45 ayrı tutuldu, E73 mekanizma değil sınıflandırma). Brief'in listesine eklenenler: E74 (LLM'in kanıtı yanlış aktarması), E75 (biçim sınırı), E76 (otomatik tip dönüşümü), E77 (yöntem değişikliğini söylememe), E78 (katalog meta-verisi yanlış) — üçü doğrudan arıza raporlarından, ikisi bugünkü ölçümden.

---

## PART 7 — Risk Sıralaması

Öncelik ≈ Olasılık × Etki × Sessizlik (1–5 her biri; dogmatik değil, sıralama için). Olasılık kanıtı: ChatGPT ADA raporları ve GitHub issue'ları (E34/E35/E43 sık), PHE/Reinhart (E16/E52 nadir ama yıkıcı), bizim golden geçmişimiz (L10 belirsizlik her koşuda, G12 yüklenmemiş seri).

| Sıra | Senaryo | L | I | S | Tespit edilebilirlik | Guard varken sürtünme | Öncelik |
|---|---|---|---|---|---|---|---|
| 1 | E12 anlamca yakın yanlış dosya | 4 | 5 | 5 | orta (kavram sözlüğü gerekir) | düşük (yalnız dosya yolunda) | 100 |
| 2 | E53/E07 terim karışıklığı (faiz ↔ bakiye) | 4 | 5 | 5 | yüksek (gerekli ölçüm yok) | düşük | 100 |
| 3 | E55 yanlış öncül | 4 | 5 | 5 | yüksek (seri yönü testi) | düşük | 100 |
| 4 | E71 kullanıcı etiketi yanlış | 3 | 5 | 5 | yüksek | düşük | 75 |
| 5 | E28 ölçek (bin/milyon) | 3 | 5 | 5 | yüksek (katalog çapraz) | düşük | 75 |
| 6 | E32 nominal/reel | 3 | 5 | 5 | yüksek (deflatör yok) | düşük | 75 |
| 7 | E11 tamamen yanlış dosya | 3 | 5 | 4 | yüksek | düşük | 60 |
| 8 | E14 bayat veri | 4 | 4 | 4 | yüksek (son gözlem tarihi) | düşük | 64 |
| 9 | E15/E17 kısmi kapsam | 4 | 4 | 4 | yüksek | düşük | 64 |
| 10 | E37 yanlış etiketli kolon | 2 | 5 | 5 | orta (makullük) | orta | 50 |
| 11 | E49/E50 yanlış join / patlama | 2 | 5 | 5 | yüksek | düşük | 50 |
| 12 | E78 katalog meta yanlış | 2 | 5 | 5 | yüksek | düşük | 50 |
| 13 | E18 eksik dönem | 3 | 4 | 4 | yüksek | düşük | 48 |
| 14 | E46 mükerrer | 3 | 4 | 4 | yüksek | düşük | 48 |
| 15 | E58 yetersiz örneklem | 3 | 4 | 4 | yüksek | orta | 48 |
| 16 | E21/E22 varlık/segment | 3 | 4 | 4 | orta | orta | 48 |
| 17 | E34 yanlış metrik | 3 | 4 | 4 | yüksek | düşük | 48 |
| 18 | E15 belirsiz soru (E36/L10) | 5 | 3 | 3 | orta | **yüksek** | 45 |
| 19 | E24 toplulaştırılmış | 2 | 4 | 4 | yüksek | düşük | 32 |
| 20 | E39 toplam satırı | 3 | 3 | 4 | yüksek | düşük | 36 |
| 21 | E68 çoklu niyet (tahmin) | 3 | 4 | 3 | orta | düşük | 36 |
| 22 | E64/E66 çok tur / düzeltme | 3 | 3 | 4 | orta | düşük | 36 |
| 23 | E41 locale | 3 | 4 | 2 | yüksek (zaten çözüldü) | düşük | 24 |
| 24 | E72 injection | 2 | 4 | 3 | yüksek (zaten çözüldü) | düşük | 24 |
| 25 | E52 tipo | 3 | 2 | 2 | yüksek (zaten çözüldü) | düşük | 12 |

Okuma: ilk 9 satırın 7'si **"soru ne istiyor × veri ne sunuyor"** karşılaştırmasıyla yakalanır; bu tek mekanizma en yüksek öncelikli riskin çoğunu kapatır (PART 11–12'nin gerekçesi).

---

## PART 8 — Sessiz Semantik Hata Analizi

Zincir (brief §77–78) beş yüksek riskli senaryo için, sistemdeki **hangi katmanın hatayı görebildiği ve neden görmediği** ile:

**E12 — konut fiyat endeksi dosyası, "konut kredisi hacmi" sorusu**
`web_url` okur (dönem+sayı var) → tablo yüklenir → `workspace_compute_column` yüzde değişim → grafik → "2024'te konut kredisi hacmi %38 arttı" → karar. Görebilen katman: yalnız model (kart başlığında "kfe" yazar). Görmeyen: `web_url` (ilgi kontrolü yok `[SRC]`), grounding (sayılar tabloda var), kanıt paneli (zincir tam: hücre → dosya). **Kırılma noktası**: dosya yüklenmeden önce "soru: kredi hacmi; dosya: fiyat endeksi" karşılaştırması.

**E53 — "faiz oranı kaçtı", katalogda yalnız bakiye**
Model arar → tek tablo döner (seed'de arama hep döner `[SRC]` `duckdb_lakehouse.py:224`) → describe → bakiye sorgusu → "678.970" → kullanıcı "faiz oranı 678.970" okur. Bugünkü ölçümde (A07) model kendisi durdu `[OUR EXPERIMENT]`; ama bu modelin dikkatine bağlı, kapı yok. Silver'da `EŞLEŞMEYEN:` satırı yardımcı (`tools/lakehouse.py:86-91` `[SRC]`), seed'de yok.

**E55 — "faiz düştüğü için kredi arttı mı?"**
Model öncülü kabul eder → kredi serisini çeker → artış görür → "evet, faiz düşüşüyle kredi arttı" (nedensellik filtresi "için/yüzünden" yakalayabilir ama "faiz düştüğünde" kalıbı listede yok `[SRC]` `grounding.py:90`). Kırılma: öncül olgusu deterministik test — faiz serisi varsa yönü, yoksa "faiz verisi yok, öncül doğrulanamaz".

**E28 — bin TL dosyası, milyon sanıldı**
`web_url` → "bakiye 512.259.000" → model "512 milyar TL"?? ya da "512.259.000 milyon TL" → 1000× hata. Katalogda aynı seri var; `crosscheck.py` ×1000'i bulur `[SRC]` ama yalnız `ingest_from_url` yolunda çağrılıyor; `web_url` yolunda çağrılmıyor.

**E78 — katalog kapsamı yanlış (2026-06 diyor, veri 2025-03)**
Kapsam guard'ı 2026-05'i "içeride" sayar → sorgu boş → `_out_of_coverage` SQL'deki yılı katalogla karşılaştırır, yine içeride → "filtre yanlış, distinct_values dene" mesajı `[SRC]` (`tools/lakehouse.py:341-347`) → model 2–3 tur dener → ya "yok" der ya son mevcut ayı verir. Kırılma: boş sonuçta katalogla değil **gerçek min/max(donem)** ile karşılaştırma.

Ortak örüntü: **her zincirde hesap doğru, kanıt zinciri tam, provenance tam** — kanıt paneli "bu sayı nereden geldi"yi cevaplar, "bu sayı sorunun cevabı mı"yı cevaplamaz. Provenance ≠ uygunluk.

---

## PART 9 — Mevcut Mimari Denetimi (bileşen × kullanıcı hatası)

Her bileşen için: hangi kullanıcı hatalarını yakalar, hangilerini yakalayamaz, hangi aşamada, hangi yanlış pozitifleri üretir, hangi hatalar sessizce final cevaba ulaşır. Satır referansları 14 Eylül ağacı `[SRC]`.

| Bileşen | Yakalar | Yakalayamaz | Aşama | Bilinen yanlış pozitif | Sessiz geçen |
|---|---|---|---|---|---|
| `core/small_talk` | selamlaşma | — | girdi | — | — |
| `core/tool_gate` (ADR-0043) | soruya göre araç ailesi seçimi | niyet–veri uyumu değil, yalnız yetenek görünürlüğü | girdi | analitik sözcüğü olmayan ilişki sorusu (E59) analitik araçları görmez | E68 tahmin: araç yok ama model SQL ile "tahmin" hesaplıyor (A17) |
| `core/intent` (ADR-0037) | adres/dosya kullanıcıdan mı; yazma niyeti | içerik uygunluğu | politika | — | — |
| `core/context` ön-yükleme + `core/retriever` (BM25/hibrit + yüzler) | seri seçimi, il/frekans yüzü | "aranan ölçüm katalogda yok" durumunu **seed'de** söylemez: arama hep ilk N tabloyu döndürür (`duckdb_lakehouse.py:224`) | retrieval | — | E53/E34: seed'de faiz/adet sorusu bakiye tablosunu bulur; tespit modele kalır |
| `tools/lakehouse.LakehouseSearchTool` | Silver'da `EŞLEŞMEYEN:` sözcükleri, yüklenmemiş seri (`:86-125`) | seed'de eşleşmeyen listesi yok (`last_search_terms` yalnız Silver) | retrieval | — | aynı |
| `BoundaryValidator` (şema → SQL guard → referans → politika) | olmayan seri/kolon, güvensiz SQL, tip | anlam | araç sınırı | — | — |
| `LakehouseQueryTool.check_policy` | ay düzeyinde kapsam dışı (`_soru_kapsam_disi`), dönem filtresi eksik, Gold gerekli, frekans uyuşmazlığı (`:249-286`) | kapsam **katalogdan** okunur (E78: katalog yanlışsa geçer; C02'de sorgu boş döndü ve "filtre yanlış" hint'i geldi `:341`); kısmi kapsam (E15/E17) yalnız "hiç yıl içeride değilse" tetiklenir (`_out_of_coverage:506`) | politika/veri | "2018'den bu yana" tek başına 2018 SQL'de → `_out_of_coverage` "hiçbiri içeride değil" diyebilir (A03'te model BETWEEN yazdı, tetiklenmedi) | E14 bayat: "güncel" sözcüğü kontrol edilmiyor (A02/C01'de model kendisi söyledi) |
| `LakehouseDistinctValuesTool` | alt toplam bayrağı, gerçek değer listesi | — | retrieval | — | — |
| `WorkspaceAddColumnTool` | eşleşme yok (`JOIN_MISMATCH:174`), kısmi eşleşme notu | **kaynakta mükerrer anahtar sessizce ilkini alır** (`series[~series.index.duplicated(keep="first")]` `:170`) — E46'nın join yolu | veri | — | E46 (join yolu); E49/E51: reindex satır sayısını korur, patlama olmaz ama yanlış anahtar eşleşmesi sessiz |
| `WorkspaceComputeColumnTool` | satır sayısı değişimi, güvensiz ifade | anlam (ölçek/birim çarpımı) | veri | — | E28/E30 formül düzeyinde |
| `WorkspaceQueryTool` | bakış modu tabloyu korur | toplam satırı, mükerrer | veri | — | B12'de model kendisi ayıkladı |
| Analitik araçlar (`MIN_POINTS=8`, `analytics.py:39`) | yetersiz gözlem (A12 ✓) | 8–20 gözlemde "anlamlı" dili; eksik dönemli seride ardışıklık varsayımı (E18) | önkoşul | — | E18: `change_points` boşluklu seride çalışır |
| Gold araçları (`REASON_TR`) | doğrulanmamış semantik, üst örnekleme, birikimli, tane çatışması, belirsiz vintage | — | politika | — | — |
| `tools/web.WebUrlTool` | erişim sınıfı, kaynak sabitleme, **soru yılı sayfada yok** (`_year_note:246`), locale dilbilgisi | **ilgi/uygunluk yok**: dosya yüklenir, aktif tablo olur (B01/B02) | erişim | — | E11/E12/E71 (web_url yolu), E28 birim, E37 etiket |
| `tools/ingest` + `builder/{profile,verify,relevance,crosscheck,unit_guess}` | belirsiz tarih, birim yok, ölçüm tipi kanıtı, mükerrer (tarih, entity), ilgi (dönem/terim/katalog), katalogla ×10^k ve çelişki, uydurulmuş beyan | ilgi kapısı gevşek (PART 14: hard-negative ret %6); `ingest` bu ortamda kayıtlı değil (CLI yok) | profil | ilgi kapısı: soruda içerik sözcüğü yoksa sessiz | E12 (ingest yolu) |
| Agent: "veri çekilmeden cevap" geri gönderme (`agent.py:400`) | katalogdan cevap yazma | — | cevap | terfi/grafik sonrası (düzeltildi) | — |
| Agent: yetenek geri gönderme (grafik/analitik) | araç çağrılmadan iddia | — | cevap | — | — |
| `core/grounding` sayı + nedensellik | tabloda olmayan sayı, "neden oldu" dili | **doğru sayının yanlış döneme bağlanması** (A06: 642.144 Ekim'in, "Aralık" yazıldı); tarih/aralık beyanı (B01/C02); "düştüğünde/için" öncül kalıpları | cevap | E5 ölçümü: düşük | E74, E55 |
| Döngü kilidi, `retryable=false` → araçsız son tur | döngü, çıkışsız yol | — | harness | A13/A14: FREQUENCY_MISMATCH ×2 + DUPLICATE ×2 → 24–32 s | — |
| `DIŞ İÇERİK` çerçevesi + niyet kapısı | veri içi talimat (B15 ✓, G13 ✓) | — | güvenlik | — | — |
| Kanıt paneli (ADR-0033) | sayı → hücre → SQL → kaynak | **uygunluk değil köken** | cevap sonrası | — | tüm E1x sınıfı: zincir tam, anlam yanlış |
| `REPEAT_NOTE`, `refresh_profile` | tekrar soru kopyası, katalog değişince profil | — | — | — | — |

Özet: 22 bileşenin **hiçbiri** "soru ne istiyor × veri ne sunuyor" karşılaştırmasını yapmıyor; en yakını ilgi kapısı (yalnız ingest) ve `_year_note` (yalnız yıl). Sessiz geçenlerin ortak yolu `web_url → workspace_query → anlatı`.

---

## PART 10 — Gap Matrisi

| Kullanıcı hatası | Şiddet | Mevcut tespit | Katman | Sessiz hata riski | Gereken iyileştirme | Öncelik |
|---|---:|---|---|---:|---|---|
| E12 anlamca yakın yanlış dosya | 5 | yalnız model (B02: geç uyarı; 2. tekrar PART 19) | — | yüksek | uygunluk kapısı (`web_url` + ingest) | P0 |
| E11 tamamen yanlış dosya | 5 | model (B01 ✓ ama dosya aktif tabloya yüklendi) | — | orta | aynı kapı + reddedilen dosya aktif tablo olmaz | P0 |
| E71 kullanıcı etiketi yanlış | 5 | model (B16: sayı önce, uyarı sonra) | — | orta | kapı: beyan × içerik; uyarı sayıdan ÖNCE | P0 |
| E37 yanlış etiketli kolon | 5 | **yok** (B07 sessiz, iki tekrarda) | — | yüksek | makullük: başlık tipi × değer aralığı | P0 |
| E53/E34 aranan ölçüm katalogda yok | 5 | model (A06/A07 ✓); seed'de arama hep döner | — | orta | ön-koşul: gerekli ölçüm ∉ katalog ölçümleri → STOP/WARN | P0 |
| E55 yanlış öncül | 5 | model (A09/A10 ✓) | — | orta | `check_premise` deterministik | P0 |
| E74 yanlış hücre / aralık beyanı | 4 | **yok** (A06, B01, C02) | — | yüksek | grounding'e dönem→sayı ve aralık beyanı denetimi | P0 |
| E68 yetki dışı tahmin | 4 | grounding MISS + not (A17) | cevap | orta | niyet–yetenek kapısı: tahmin aracı yok → beyan | P1 |
| E28 ölçek/birim (dosya) | 5 | ingest crosscheck ✓; `web_url` yolunda yok (B06'da dosya adı birimi sızdırdı) | profil | yüksek | crosscheck'i `web_url` tablosuna da uygula; birim yoksa "birim beyan edilmedi" satırı zorunlu | P0 |
| E14 bayat | 4 | model (A02/C01 ✓) | — | orta | "güncel/bugün/son" + son gözlem tarihi → zorunlu satır | P1 |
| E15/E17 kısmi kapsam | 4 | `_out_of_coverage` yalnız hiç yıl yoksa; model (A03 ✓) | politika | orta | kapsanan oran hesabı → WARN satırı | P1 |
| E18 eksik dönem | 4 | model (B05/C03 ✓); analitik araçlar boşluğu bilmez | — | orta | tablo kalitesi: ardışık fark > frekans → analitik araçlara önkoşul | P1 |
| E46 mükerrer | 4 | ingest verify ✓; `web_url` yolu model (B08 ✓); add_column sessiz keep-first | — | orta | tablo kalitesi; add_column'da mükerrer anahtar → WARN | P1 |
| E78 katalog meta yanlış | 5 | boş sonuç → "filtre yanlış" hint'i (C02: model yine de doğru dedi) | veri | orta | boş sonuçta gerçek min/max ile karşılaştır | P1 |
| E21/E22 varlık/segment | 4 | model (A04/A05 ✓ ama ulusal sayı verildi) | — | orta | ön-koşul: kırılım ∉ katalog boyutları; dosyada tek değerli boyut | P1 |
| E49/E50 yanlış join | 5 | JOIN_MISMATCH yalnız %0 eşleşme | veri | orta | anahtar tekilliği + eşleşme oranı + satır sayısı öncesi/sonrası raporu | P1 |
| E36/L10 belirsiz soru | 3 | yok (A15: seçim beyan edildi) | — | düşük | `clarify` aracı, yalnız yüksek etki | P1 |
| E24 toplulaştırılmış | 4 | model (B11 ✓) | — | düşük | kapı granülarite | P1 |
| E39 toplam satırı | 4 | model (B12 ✓) | — | düşük | tablo kalitesi: tarih olmayan satır | P2 |
| E38 yanlış sayfa | 3 | araç yalnız ilk sayfa; model "okunamadı" dedi (B17) | okuma | düşük | xlsx sayfa listesi + seçim | P2 |
| E64/E66 çok tur/düzeltme | 4 | workspace geçmişi; A24/A25 ✓ | — | düşük | reddedilen dosya aktif tablo olmaz; düzeltme → bağımlı sonuç geçersiz | P2 |
| E27 oran/yüzde | 4 | yok (B13: 0,00136 "oran") | — | orta | measure_type=ratio → cevapta hem oran hem % | P2 |

---

## PART 11 — Intent–Data Alignment Araştırması

**Literatürdeki karşılıklar.** (a) NL2SQL'de *cevaplanabilirlik* ve *şema bağlama çekimserliği* (TriageSQL 2020; TrustSQL 2024; Adaptive Abstention PACMMOD 2025; Query Carefully 2025) — soru ile şema arasındaki uyumu SQL üretmeden önce sınıflar; en zor sınıf kolon belirsizliği (doğruluk 0,3). (b) Veri hazırlığı (Lawrence 2017) — analizden bağımsız bantlar. (c) Veri sözleşmeleri — üretici–tüketici arasında şema+anlam beyanı. (d) Semantic layer'lı NL2SQL (+17–23 puan) — kavram sözlüğü belirleyici. (e) Belirsizlikte soru sorma (SAGE-Agent EVPI) — kapı çıktısının *ne yapılacağı* bilgi-değeri sorusudur.

**Brief'in hipotezi (§80) ile karşılaştırma.** Akış (soru → niyet → gereksinim → beklenen semantik → gerçek semantik → uyum → PROCEED/WARN/CLARIFY/STOP) literatürle uyumlu; iki düzeltme:
1. "Niyet çıkarımı" bir LLM adımı olmak zorunda değil. Ablation `[OUR EXPERIMENT]`: soru → gerekli kavramlar eşlemesi, katalog alias sözlüğüyle deterministik yapılınca (kol H) hard-negative ayrımı LLM yargıçtan (kol G) daha iyi ve 336 kat ucuz; LLM yalnız "kısmen" bandında gerekli (kol I: 12 çağrı). Sözlük *el yazımı* olduğu sürece bu sonuç iyimserdir; sözlüğün kaynağı katalog (`ColumnSpec.aliases`, `concept_id` — data ekibinden istenen P1 alanı) olmalı.
2. "Uyum" tek skor değil (brief §84 doğru): ölçüm var mı / varlık-segment uyuyor mu / dönem kapsıyor mu / granülarite yeter mi / birim biliniyor mu / veri kalitesi (boşluk, mükerrer, örneklem). Her biri ayrı bir **gerekçe cümlesi** üretir; kullanıcıya skor değil gerekçe gider (brief §112).

**Mevcut sistemde nereye oturur.** Boundary validator'ın önüne değil, *veri kaynağı seçildikten sonra, tablo aktif olmadan önce*: `web_url(table_index=…)`, `ingest_from_url` ve `lakehouse_query` (seed/Silver) üç yolda aynı fonksiyon. Mentörün "tek orkestrasyon ajanı + deterministik katmanlar" kararıyla uyumlu `[ORG]`: yeni ajan değil, `core/fitness.py`.

---

## PART 12 — Analiz Sözleşmesi (Expected Data Signature) Araştırması

Gerekli mi? **Evet, ama minimal.** Brief §81'deki JSON'un alanlarını ablation'da tek tek sınadık:

| Alan | Deterministik çıkarılabilir mi | Değer kattı mı (ablation) | Karar |
|---|---|---|---|
| `required_measures` (bakiye/faiz/endeks/adet…) | evet, kavram sözlüğüyle (soruda tetikleyici kök) | **belirleyici**: H kolunu 0,41 → 0,98 hard-negative rete taşıyan tek kural "aranan ölçüm dosyada yoksa ret" | ZORUNLU |
| `required_entities` (konut/ihtiyaç/taşıt/kart) | evet | ihtiyaç ↔ konut, kart ↔ kredi ayrımını sağladı | ZORUNLU |
| `time_range` | evet (yıl/ay regex) | eski sürüm (E13), yanlış sayfa (B17) | ZORUNLU |
| `frequency/granularity` | evet | yıllık dosya × aylık soru | ZORUNLU |
| `relation` (iki özneli soru) | kaba (regex: düştüğünde/ilişki/karşılaştır) | tek özneli dosyayı "kısmen" yapar (çok dosyalı analiz) | GEREKLİ (kaba) |
| `analysis_type` (trend/korelasyon/tahmin) | evet (regex) | n≥8, tahmin aracı yok (A17) | GEREKLİ (önkoşul için) |
| `unit_requirements` | kısmen (soruda "milyon/dolar/yüzde") | B06/A19 | FAYDALI |
| `minimum_variables` | analysis_type'tan türer | — | TÜRETİLİR |
| `entity_scope` (Türkiye) | hayır (soru söylemez) | İstanbul dosyası ancak "dosya alt kümeye kısıtlı" olarak kısmen | dosya imzasından gelir |

Ne kadarı LLM? Sıfır zorunlu. "Kısmen" bandında LLM yargıç gerekçe üretir (I kolu). Güvenilirlik: sözlük kapsamı dışındaki soru için `req=∅` → "gereksinim çıkarılamadı" → kısmen → LLM'e düşer; bu, yanlış-pozitif yerine *bilinmezliği* beyan eder.

Tip-sistemi benzetmesi (brief §136): faydalı bir *zihinsel model*, mimari olarak fazladan soyutlama. `TimeSeries<InterestRate>` ≠ `TimeSeries<CardTransactions>` tam olarak "aranan ölçüm yok" kuralıdır; `measure_rules` (`domain/finance.md`) zaten semantic_type → izinli işlem tablosu `[SRC]`. Yeni bir tip dili yazmak yerine `semantic_type` + kavram sözlüğü yeter. **Karar: benzetmeyi dokümanda kullan, tip dilini kodda değil.**

---

## PART 13 — Veri Seti İmzası Araştırması

Brief §82'nin listesi karşısında "gerçekten gerekenler" — kanıt: ablation ve çevrimdışı "sonra" (G1/G2) hangi alanı kullandı:

| Alan | Kaynak | Deterministik mi | Kullanıldı mı | Karar |
|---|---|---|---|---|
| kavramlar (dosya adı + başlıklar + katalog alias'ı) | `toks()` + LEX | evet | G1 (her ret) | ZORUNLU |
| tarih aralığı (min/max) | `profile.propose` + `file_year_range` | evet | G1 dönem, G6 aralık beyanı | ZORUNLU |
| frekans | `_infer_frequency` | evet | G1 granülarite | ZORUNLU |
| satır sayısı × beklenen (frekans × aralık) | hesap | evet | G2 kısmi yıl/örneklem/kesik (PHE) | ZORUNLU |
| boşluk/mükerrer dönem | tarih farkları | evet | G2 | ZORUNLU |
| tek değerli boyut kolonu | kardinalite | evet | G1 "alt kümeye kısıtlı" | GEREKLİ |
| sayısal medyan × başlık tipi (makullük) | hesap | evet | G2 etiket-değer (B07) | GEREKLİ |
| birim ipucu (başlık/dosya adı/katalog ölçeği) | `_UNIT_HINTS`, `unit_guess`, `crosscheck` | evet | G2 birim yok | GEREKLİ |
| measure_type tahmini | `_infer_measure_type` | evet (kanıtlı) | Gold/measure_rules | VAR |
| entities, relationships | — | hayır (LLM) | hiçbir kararda | ATLA (P2) |
| source, freshness, version, sha256 | provenance | evet | E13/E47 | VAR (ADR-0033) |
| LLM "olası anlam" | LLM | hayır | yalnız "kısmen" bandı | OPSİYONEL |

İmzanın **tamamı deterministik**; LLM'e kalan tek şey belirsiz bantta gerekçe. Bu, brief §83'ün ayrımını doğruluyor ve §107'nin "LLM tek validator olmasın" kuralını sağlıyor.

---

## PART 14 — Hard-Negative Araştırması

Deney (`scripts/ueb_wrongfile_ablation.py`, `docs/experiments/ueb_wrongfile_ablation_2026-09-14.json`): 12 soru × 28 dosya = 336 çift; altın etiket R (uygun) 37, H (anlamca yakın yanlış) 123, I (ilgisiz) 176. Hard-negative'ler: fiyat endeksi ↔ kredi hacmi, faiz ↔ bakiye, başvuru/satış adedi ↔ bakiye, tüketici toplamı ↔ konut, İstanbul ↔ ulusal, 2019–21 ↔ 2024, yıllık ↔ aylık, "faiz_orani" başlıklı bakiye.

| Kol | top-1 | I'yi ret | H'yi ret | R'yi kabul | dengeli doğruluk | süre | LLM çağrısı |
|---|---:|---:|---:|---:|---:|---:|---:|
| A dosya adı | 0,33 | 0,89 | 0,66 | 0,62 | 0,71 | 3 ms | 0 |
| B şema adları | 0,33 | 0,97 | 0,94 | **0,27** | 0,61 | 3 ms | 0 |
| C embedding (ad + başlık) | 0,50 | 0,89 | 0,50 | 0,73 | 0,73 | 8,7 s* | 0 (3 batch) |
| D BM25 (ad + başlık + örnek) | **0,92** | 0,87 | 0,67 | 0,92 | 0,85 | 2 ms | 0 |
| E embedding + dönem | 0,50 | 0,82 | 0,56 | 0,78 | 0,75 | 8,7 s* | 0 |
| F embedding (tam kart) | 0,75 | 0,78 | **0,39** | 0,92 | 0,77 | 8,7 s* | 0 |
| G LLM yargıç (Qwen3.8-27B) | 0,92 | 0,99 | 0,95 | 0,89 | 0,93 | 125 s | 336 |
| **H deterministik sözleşme** | **1,00** | 0,99 | **0,98** | 0,92 | **0,95** | 83 ms | 0 |
| R depodaki ilgi kapısı (13 Eyl) | 0,17 | 0,28 | **0,06** | 0,92 | 0,55 | 50 ms | 0 |
| I = H, "kısmen"de G | 1,00 | 0,99 | 0,98 | 0,92 | 0,95 | 4,5 s | 12 |

\* üç embedding kolu aynı 3 batch çağrısını paylaşır; skor kolları için eşik τ aynı sette en iyi dengeli doğruluğa göre seçildi (iyimser).

Bulgular:
1. **Embedding tek başına ayıramıyor** `[OUR EXPERIMENT]`: Q01 (konut kredisi bakiyesi) için R en düşük 0,505, H en yüksek 0,632; Q10 (İngilizce) R min 0,51, H max 0,79; Q12 (ilişki) R min 0,40, H max 0,55. Eşik yok. NevIR bulgusuyla tutarlı: negasyon/ince ayrım gömülü temsilde kaybolur.
2. **BM25 seçimde güçlü, reddetmede zayıf**: en iyi adayı bulur (0,92) ama "yeterince iyi mi" demez (H ret 0,67); "kredi" sözcüğü kredi kartını da getirir.
3. **Deterministik sözleşme hard-negative'i kırıyor** ama üç uyarıyla: (i) kural seti aynı sette 3 turda ayarlandı — iyimser; (ii) kavram sözlüğü el yazımı (13 kavram, ~60 kök; `hsg/ln/bal` kısaltmaları dahil) — üretimde katalog alias'ı ve `concept_id` gerekir; (iii) sözlük dışı soru "kısmen"e düşer (bilinmezlik beyanı, yanlış ret değil).
4. **LLM yargıç iyi ama pahalı ve kalıplı hata yapıyor**: İstanbul dosyasını ulusal soruya "evet" dedi (Q01/Q10), ihtiyaç kredisi sorusuna konut dosyasına "evet" dedi (Q08 — `hsg_ln` kısaltmasını çözemedi), yıllık dosyaya "kısmen"; 9 satırlı eksik-ay dosyasını "Aralık'ı kapsamıyor" diye yanlış reddetti. 125 s / 336 çağrı.
5. **Kademeli (I) en iyi oran**: H kesin karar verince G çağrılmıyor; 336 çiftin 12'si (%3,6) LLM'e gitti, sonuç H ile aynı. Beklenen üretim maliyeti: dosya başına 0–1 LLM çağrısı.
6. Kalan "kaçaklar" doğru davranış: İstanbul alt-kümesi "kısmen" (soru ulusal demiyor), yanlış-sayfa xlsx "ret" (okunan sayfa gerçekten 2024 içermiyor).

---

## PART 15 — Netleştirme Politikası (PROCEED / WARN / CLARIFY / STOP / AUTO-FIX)

Literatür girdileri: soru sormak maliyetli bir eylem (SAGE-Agent, EVPI); bilişsel zorlama memnuniyeti düşürür (Buçinca); geçme oranı %46–96 (uyarı yorgunluğu); tanıyor-ama-sormuyor (Su & Cardie). Ölçümümüz: A15'te model sormak yerine "Toplam Krediler" seçip beyan etti ve bu kabul edilebilirdi; B02'de uyarı en sonda kaldı (geç uyarı).

| Durum | Karar | Gerekçe |
|---|---|---|
| Uyum tam, kalite bayrağı yok | PROCEED | sürtünme yok |
| Biçim sorunu, deterministik ve tersinir düzeltme (ayraç, encoding, toplam satırı, aynı değerli mükerrer dönem, öndeki sıfır) | AUTO-FIX + tek kanıt satırı | anlam değişmez, kullanıcı görür |
| Kapsam/kalite eksik ama analiz yine anlamlı (kısmi yıl, boşluk, küçük örneklem, bayat, kısmi dönem) | WARN — **sayıdan önce**, tek satır, ölçülebilir ("2025 için 8 ay var; yıllık büyüme değil Ocak–Ağustos") | Bansal: sayı önce gelirse uyarı okunmaz |
| Gerekli ölçüm var, ikinci özne yok (ilişki sorusu, tek dosya) | PARTIAL → cevabın kapsamı daraltılır + "ikinci seri gerekli" | çok dosyalı analiz |
| Belirsiz kalem/kolon ve **etki yüksek** (birim/ölçek, oran/yüzde, finansal karar) | CLARIFY — tek soru, seçenekli | EVPI yüksek |
| Belirsiz ama etki düşük ya da varsayılan makul (Toplam Krediler) | PROCEED + seçim beyanı ("'kredi' için Toplam Krediler'i aldım; başka kalem istersen söyle") | A15 kanıtı; soru sayısı düşük kalır |
| Aranan ölçüm/varlık yok; dönem hiç kapsanmıyor; granülarite üretilemez; beyan × içerik çelişkisi | STOP — "dosyada şunlar var / katalogda şunlar var" + seçenekler | sessiz hata en tehlikeli sınıf |
| Öncül veriyle çelişiyor | WARN (öncül düzeltmesi cevabın ilk cümlesi) | A09/A10 |
| Yetki dışı istek (tahmin, kur çevirimi) | STOP o parça için; diğer parçalar PROCEED | A17/A19 |

Sürtünme sınırı: soru başına **en çok bir** CLARIFY; aynı oturumda aynı kapı üç kez STOP dediyse dördüncüde "kullanıcı onayıyla devam" seçeneği (`user_confirmed` kalıbı `[SRC]` `tools/ingest.py:68`) — Dietvorst'un "değiştirebilme" bulgusu.

---

## PART 16 — Otomatik Kurtarma ve Durum Geçersizleme

Otomatik düzeltilebilir (deterministik, tersinir, kanıt satırıyla): ondalık/binlik ayracı (`profile.py` zaten `[SRC]`), tarih biçimi belirsiz değilse, encoding, öndeki sıfır (metin dtype zaten), toplam/dipnot satırını ayırma, aynı değerli mükerrer dönemi tekilleştirme (farklı değerliyse WARN → DATA_CONFLICT), kolon adı normalizasyonu (alias). Otomatik düzeltilmez: birim/ölçek varsayımı (bin ↔ milyon), oran ↔ yüzde, müşteri sayısı ↔ işlem sayısı, dosya değiştirme, öncül.

Durum geçersizleme (E64/E66) — bugün `AnalysisWorkspace` geçmiş + snapshot tutuyor `[SRC]`; eksik olan *bağımlılık*: hangi cevap hangi tabloya dayandı. Öneri (P2, küçük): `AgentAnswer`'a `table_version` (workspace history sırası + provenance sha); kullanıcı "yanlış dosya" dediğinde ya da yeni dosya yüklendiğinde (1) reddedilen/eski dosya aktif tablo olmaz — bugün B01'de oluyor; (2) `replay cache` anahtarına `table_version` girer; (3) önceki cevaba dayanan takip sorusu "bir önceki tablo değişti" notu alır. Tam selective invalidation (claim → cell → dataset version) kanıt paneliyle zaten mümkün (ADR-0033); hackathon için bağlama P2.

---

## PART 17 — Doğrulama Mimarisi Alternatifleri

| | A — Hafif deterministik kapı | B — Hibrit uyum motoru (kademeli) | C — Tam analiz sözleşmesi |
|---|---|---|---|
| Ne | `core/fitness.py`: gereksinim × imza (6 boyut) + kalite bayrakları + politika; `web_url`/ingest/query önünde; LLM yok | A + "kısmen" bandında LLM yargıç (JSON gerekçe) + `clarify` aracı + `check_premise` + grounding genişletmesi | B + tam sözleşme nesnesi (JSON), cevaplanabilirlik sınıfı, veri hazırlığı kartı, selective invalidation, LLM imza (entities/relationships) |
| Ablation karşılığı | kol H | kol I | kol I + P2 alanlar |
| Hard-negative ret | 0,98 (aynı sette) | 0,98 | aynı |
| Yanlış ret (R) | 0,08 | 0,08 | aynı |
| LLM çağrısı / soru | 0 | 0–1 | 1–2 |
| Gecikme | < 0,1 s | +2–4 s yalnız "kısmen" | +4–6 s |
| Uygulama | 1 modül (~300 satır) + 3 araca 10'ar satır + golden'lar | A + 2 araç + prompt kuralı | B + durum modeli + UI |
| Genericlik | sözlük katalogdan geldiği sürece tam | aynı | aynı |
| Açıklanabilirlik | gerekçe cümlesi deterministik | + LLM gerekçesi (işaretli) | + hazırlık kartı |
| Hackathon | 1–1,5 gün | 2–2,5 gün | 4+ gün |
| Jüri değeri | "yanlış dosya" demosu | + öncül düzeltme, netleştirme | + "hazırlık kartı" görseli |
| Risk | sözlük boşluğu → "kısmen" → uyarı yok | LLM yargıç önyargısı (işaretli, dar bant) | karmaşıklık, ölçülmemiş alanlar |

Karşılaştırma ve seçim PART 29–30'da; kısa cevap: **B**, C'nin P2 parçaları yol haritasında.

---

## PART 18 — Kullanıcı Hatası Benchmark'ı (UEB v0)

`scripts/ueb_cases.py` — 55 vaka, 4 kulvar, 8 persona (beginner, business, analyst, financial, power, careless, overconfident, exploratory, adversarial). Her vaka: kimlik, taksonomi kodu, persona, soru(lar), beklenen güvenli davranış (abstain / warn / clarify / answer), şiddet 1–5, DB varyantı, tespit sözcükleri, yanlış-cevap sözcükleri (seed'den okunan gerçek değerler), tablo beklentisi, not. Otomatik sınıflama anahtar sözcükle (SAFE / PARTIAL / SILENT / PASS / WRONG / MISS / OVERBLOCK); sonra her cevap elle okundu (PART 19).

| Kulvar | Vaka | İçerik | Nasıl koşuyor |
|---|---:|---|---|
| A sorgu-kaynaklı | 26 | tipo yıl, bayat, kısmi kapsam, yanlış varlık/segment/metrik, faiz↔bakiye, yüzde/puan, yanlış öncül, gömülü nedensellik, imkânsız/yetersiz, frekans/granülarite, belirsiz, çift sayım, tahmin, para birimi, ölçek, reel/nominal, yanlış beyan, göreli dönem, çok tur, düzeltme, soruda injection | seed DB (BDDK aylık, 2021-01→2026-06) |
| B dosya-kaynaklı | 17 | tamamen yanlış, anlamca yakın, eski sürüm, kısmi yıl, eksik ay, birim, yanlış etiketli kolon, mükerrer, locale, örnek, yıllık, toplam satırı, oran/yüzde, çelişen, veri içi injection, kullanıcı etiketi, yanlış sayfa | `web_url` ile `../incoming/ueb/*.csv|xlsx` (18 fikstür, `ueb_fixtures.py`) |
| C veri-kaynaklı | 4 | bayat DB, bayat + katalog yanlış, eksik dönemler, mükerrer satırlar | seed'in değiştirilmiş kopyaları + catalog.json |
| D yanlış-pozitif kontrolü | 8 | İngilizce alias, büyük harf/ISO, kısaltma, alışılmadık ama geçerli kalem, kapsam başlangıcı, son dönem, benzer adlı kalem, garip kolon adlı doğru dosya | seed / fikstür |

Hard-negative alt kümesi: B02 (fiyat endeksi ↔ kredi hacmi), B07 (faiz başlıklı bakiye), B16 (beyan ↔ içerik), A07 (faiz ↔ bakiye), A05/A04 (segment/varlık), A06 (adet ↔ tutar); ayrıca ablation'ın 123 H çifti.

Sınırlar: tek tablo seed (Silver'daki 2.214 seriyle çok-seri belirsizliği ölçülmedi); ingest yolu bu makinede kapalı; kalem adları fikstür adlarına sızabiliyor (B06 "bin_tl"); tek etiketleyici.

---

## PART 19 — Baseline Sonuçları (mevcut harness, MIA Qwen3.8-27B, 14–15 Eylül)

Koşular: run 1 tüm 55 vaka (`ueb_baseline_2026-09-14_0054.json`), run 2 A/B/C 47 vaka (`ueb_rep2_2026-09-14_0116.json` + `ueb_rep2b_*.json`). Ortalama 17 s/vaka; uçlar B06 229 s (run 1), A01 57 s (run 2), A05 45–49 s.

**Elle etiket (run 1):**

| Sonuç | Korumalı (37) | Kontrol (18) |
|---|---:|---:|
| SAFE (durdu / sordu / sayıdan önce uyardı) | 32 | — |
| LATE (uyardı ama sayıdan sonra) | 1 (B02) | — |
| SILENT (sessiz sessiz yanlış) | **3** (A06, A17, B07) | — |
| PASS (doğru cevap) | — | 17 |
| PARTIAL (doğru ama birim belirsiz) | — | 1 (B13) |
| OVERBLOCK / WRONG | — | **0 / 0** |

Sessiz hata oranı (katı) **3/37 = %8,1**; şiddet ağırlıklı **13/147 = %8,8**; LATE dâhil %12,2. Run 2: SILENT 2 (A17, B07), LATE 0 (B02 uyarıyı başa aldı), A06 doğru → %5,4; **pass²** (iki koşuda da güvenli) 33/37 = %89. Kararlı hatalar: B07 (2/2 sessiz), A17 (2/2 tahmin üretti). Kararsız: A06 (1/2 yanlış hücre), B02 (1/2 geç), A05 (tablo var/yok).

Otomatik sınıflamanın hataları: A07/A26/B12 "SILENT/WRONG/MISS" dedi, elle güvenli/doğru (sayı, "yok" cümlesinin yanında etiketli geçiyor); A06/A17/B02'yi kaçırdı. Ders: sessiz hatayı anahtar sözcük ölçemez; kanıt-hücre eşlemesi gerekir (PART 21'deki G5 bunun ölçüm aracı).

**Nerede ne çalıştı:**
- Deterministik kapılar tetiklendi: A01/A18 `OUT_OF_COVERAGE`; A12 `n≥8` (araç reddi); A13/A14/A22 `FREQUENCY_MISMATCH` (ama ×2 + `DUPLICATE_CALL` ×2 → 15–32 s); B15/G13 niyet kapısı + DIŞ İÇERİK.
- Modelin dikkatiyle yakalananlar (kapı yok): A02–A11, A15, A19, A21, A23; B01, B03–B05, B08, B10, B11, B14, B16, B17; C01–C03. Yani korumalı 37'nin **26'sı yalnız modele bağlı**.
- Model meta-hataları (E74): B01 "Ocak–Ekim" (dosya Aralık'a kadar; iki koşuda da), C02 "yalnız Ocak–Mart 2025 mevcut" (2021'den beri var), A15 Kasım satırı eksik (araç önizlemesi 10 satır, model "tamamı analiz tablosunda" notuna rağmen önizlemeden yazdı), A06 Ekim değerini Aralık diye (aynı önizleme sınırı).
- Durum tehlikesi: B01/B02'de yanlış dosya **aktif tablo** oldu; takip sorusu ("bunun aylık değişimini çiz") yanlış veriyle çalışır.
- Sıralama tehlikesi: B16 ve A04/A05/A06/A07'de sayı önce, uyarı sonra ya da sayı büyük puntoyla — Bansal 2021 bulgusu.

Ham cevaplar ve izler JSON'da; özet tablo `ueb_baseline_2026-09-14_0054.md`.

---

## PART 20 — Ablation Deneyleri

**Yanlış-dosya tespiti** (PART 14 tablosu). Katkı sırası: dosya adı → şema adları (R kabulünü öldürüyor) → embedding (+meta, +dönem, +örnek: hard-negative'de 0,39–0,56) → BM25 (seçim 0,92, ret 0,67) → **deterministik sözleşme (ret 0,98, kabul 0,92)** → LLM yargıç (0,95/0,89, 336 çağrı) → kademeli (aynı doğruluk, 12 çağrı). Yani "hibrit" kazancının kaynağı embedding değil, **gereksinim kontrolü**; embedding hiçbir kolda dengeli doğruluğu 0,78'in üstüne çıkaramadı.

**Deterministik denetimlerin çevrimdışı ablasyonu** (`ueb_after_offline_2026-09-14.json`): kaydedilmiş baseline çıktılarına altı denetim ayrı ayrı uygulandı.

| Denetim | Tetiklendiği vakalar | Sessiz/geç vakayı yakaladı mı | Kontrolde tetiklenme |
|---|---|---|---|
| G1 uygunluk kapısı (dosya) | B01, B02, B03, B07, B11, B16, B17 | B02 ✓, B07 ✓ | D08 ✗ (doğru) |
| G2 tablo kalitesi | B04, B05, B07, B08, B10, B12, B17 | B07 ✓ (etiket-değer) | B12 (toplam satırı — AUTO-FIX bayrağı, engelleyici değil) |
| G3 soru ön-koşulu | A04–A08, A10, A11, A13–A15, A17, A19, A21, A22 | A06 ✓, A17 ✓ | D01–D08 ✗ |
| G4 öncül | A09, A10 (ÇELİŞİYOR) | — | — |
| G5 iddia-hücre | A06 | A06 ✓ | A03/A09/A15/C03/D05 ilk sürümde yanlış pozitif → satır kuralı daraltıldı → 0 |
| G6 aralık beyanı | B01, B03 | E74 ✓ | — |

Hiçbir kontrol (D) vakasında STOP/CLARIFY üretecek bayrak yok. Uyarı: G3'ün iki kuralı (A08 "puan", A15 "kredi bakiyesi") bu sete göre yazıldı; genel sürümde bunlar katalog boyut/ölçüm listesinden türeyecek.

---

## PART 21 — Sessiz Hata Oranı: Önce / Sonra

| Ölçüt | Önce (run 1) | Önce (run 2) | Sonra (çevrimdışı projeksiyon) |
|---|---:|---:|---:|
| Sessiz hata (katı) | 3/37 = %8,1 | 2/37 = %5,4 | **0/37** (A06→G3+G5, A17→G3, B07→G1+G2) |
| Geç uyarı | 1/37 | 0/37 | 0 (G1 dosya yüklenmeden STOP) |
| Şiddet ağırlıklı sessiz | %8,8 | %6,1 | 0 |
| Yalnız modele bağlı tespit | 26/37 | 26/37 | 3/37 (A02/A23 bayat cümlesi, B14 karşılaştırma — deterministik satır eklenebilir) |
| Tespit aşaması (medyan) | anlatı (R), 2–7 araç adımı sonra | aynı | I/P: LLM çağrısından önce |
| Kontrol geçişi | 17/18 (+1 kısmi) | 17/18 | 17/18 (bayrak yok) |
| Aşırı bloklama | 0 | 0 | 0 |

"Sonra" sütunu **harness'a bağlanmış uçtan uca ölçüm değildir**; deterministik denetimlerin kaydedilmiş çıktıya uygulanmasıdır ve kurallar aynı sette ayarlandı. Gerçek "sonra" için: `core/fitness.py` + `builder/quality.py` yazılır, UEB yeniden koşulur (PART 37 P0 çıkış kriteri: sessiz ≤ 1/37, kontrol 18/18, pass² ≥ %95).

---

## PART 22 — Yanlış Pozitif Analizi

- **Baseline:** 8 kontrol + 10 "cevap" beklenen vaka; hiçbiri engellenmedi, hiçbiri gereksiz soru almadı. İngilizce alias (D01), büyük harf/ISO (D02), kısaltma (D03), 4 milyon TL'lik alışılmadık kalem (D04), kapsam başlangıcı 2021 (D05), son dönem (D06), benzer adlı "takipteki" (D07), `HSG_LN_BAL_TRYMN` kolonlu dosya (D08) — hepsi doğru sayıyla cevaplandı.
- **Ablation:** deterministik sözleşme R'nin %8'ini reddetti; üçü de yanlış-sayfa xlsx'in "Notlar" sayfası (okunan veri gerçekten 2024 içermiyor → doğru ret, yanlış etiket). LLM yargıç R'nin %11'ini reddetti (9 satırlı dosyayı "Aralık yok" diye).
- **Çevrimdışı denetimler:** G5 ilk sürümde 5 yanlış pozitif (düz yazıda iki dönemin sayısı aynı cümlede) → yalnız tablo satırı ya da tek dönem + tek sayı satırında karar → 0. G2 ilk sürümde 3 yanlış pozitif (yıl kolonu / toplam satırı profilciyi %100 kuralıyla düşürüyordu) → toleranslı (≥%80) eşleme → 0.
- **Kalan riskler:** (1) kavram sözlüğünde olmayan alan (sağlık, enerji) → `req=∅` → "kısmen" → LLM yargıç; yanlış STOP değil, fazladan bir LLM çağrısı. (2) Sözlükte olup dosyada başka dilde/kısaltmayla geçen kavram (`mtg_bal`) → yanlış STOP olasılığı; savunma: katalog alias'ı + `user_confirmed` (üç STOP'tan sonra "yine de devam" seçeneği). (3) Alt kümeye kısıtlı dosya (İstanbul) "kısmen" — kullanıcı gerçekten İstanbul istiyorsa bir satır uyarı sürtünmesi.
- **Ölçüm önerisi:** her sürümde D kulvarı + ablation R kabulü birlikte raporlanır; R kabulü %90'ın altına düşen değişiklik geri alınır.

---

## PART 23 — UX / Güven İncelemesi

Kanıtlar: uyarı geçme %46–96 (Ray-Wilson 2026); açıklama kabulü artırır (Bansal 2021); bilişsel zorlama memnuniyeti düşürür (Buçinca 2021); bir hata görünce güven çöker, düzenleyebilme onarır (Dietvorst 2015/2016); sözlü güven kalibre değil (Xiong 2024). Bizim ölçüm: sayı-önce-uyarı-sonra kalıbı (B16, A04–A07), geç uyarı (B02 run 1).

Tasarım kuralları (V2'ye giren):
1. **Uyarı sayıdan önce, tek satır, ölçülebilir**: "Dosyada 2025 için 8 ay var (Ocak–Ağustos); yıllık büyüme değil, 8 aylık büyüme: %16,3." — uyarı ve sayı aynı cümlede, kaçınılmaz.
2. **Skor değil gerekçe** (brief §112): "Uyum 0,31" yerine "Bu analiz için faiz oranı ve konut kredisi bakiyesi gerekiyor; dosyada tarih ve işlem tutarı var, bu ikisi yok."
3. **Suçlamayan dil** (brief §113): "yanlış dosya" değil "dosyanın içeriği ile soru arasında eşleşme bulamadım; dosyada şunlar var".
4. **Soru bütçesi**: soru başına en çok bir CLARIFY; düşük etkide seçim beyanı (A15 kalıbı).
5. **Kapsam beyanı satırı** her cevapta: "Veri: BDDK aylık, 2021-01→2026-06, sektör toplamı, milyon TL; son gözlem 30 Haz 2026." — bayat/kısmi/segment hatalarının çoğunu tek satır kapatır ve kullanıcıya doğrulama noktası verir (Buçinca'nın "düşünmeye zorlama"sının hafif hâli).
6. **Güven ifadesi kategorik**: "TAM / KISMİ / DOĞRULANMAMIŞ" + neden; sayısal güven yok.
7. **Ölçüm**: uyarı başına eylem oranı (kullanıcı uyarıdan sonra dosya değiştirdi mi / soruyu düzeltti mi) demo kayıtlarından; uyarı sayısı değil.

---

## PART 24 — Güvenlik İncelemesi (veri güvenilmez girdidir)

| Tehdit | Mevcut savunma `[SRC]` | Ölçüm | Ek |
|---|---|---|---|
| Veri içi prompt injection (hücre, sayfa) | `DIŞ İÇERİK` çerçevesi (`agent.py:683`), niyet kapısı (adres kullanıcıdan) | G13 ✓, B15 ✓ (iki koşu), A26 ✓ | Uygunluk kapısı deterministik → enjekte edilemez; LLM yargıç yalnız dosya *kartı* görür (başlık, 3 satır, aralık) ve çıktısı JSON'a zorlanır, karar H'nin STOP'unu geçersiz kılamaz (yalnız "kısmen"i çözer) |
| CSV/formül injection (`=HYPERLINK`, DDE) — OWASP | okuma `dtype=str`, formül değerlendirilmez; DuckDB salt okunur | — | Sistem CSV/XLSX **dışa aktarıyorsa** (`chart` spec, kanıt paneli indirme) hücre başı `= + - @` ve kontrol karakterleri öneklenmeli (OWASP) — bugün dışa aktarım yok, not |
| SQL injection benzeri (kolon adı içinde) | `guard_sql` AST allowlist, `hardened_connection` | — | — |
| SSRF / özel IP / dosya kökü | `private_host`, `allowed_local_roots` | — | Windows sürücü harfi "şema" hatası yerel dosyayı engelliyor (güvenli tarafta düşüyor, ama demo makinesinde düzeltilmeli) |
| Dosya adında talimat | dosya adı yalnız kavram eşlemede kullanılır | — | ad "ignore_previous_konut.csv" ise "konut" kavramı eşleşir; içerik kontrolü yine başlık+değer üstünden |
| Kasıtlı hard-negative (adversarial user) | uygunluk kapısı içerik+değer aralığına bakar | B07 senaryosu | başlık doğru, değerler yanlış (sahte "faiz_orani" 30–40 aralığında) → deterministik kapı geçer; savunma katalogla çapraz kontrol (aynı dönem farklı değer → DATA_CONFLICT) — dosyanın "doğru" olduğunu kanıtlamak sistemin işi değil, farkı görünür kılmak işi |
| Katalog meta-verisi yanlış (E78) | yok | C02 model doğru dedi | boş sonuçta gerçek min/max |

---

## PART 25 — KEEP / MODIFY / REMOVE / ADD

| Karar | Bileşen | Kanıt |
|---|---|---|
| KEEP | Boundary validator, kapsam/dönem/frekans/Gold politikaları, döngü kilidi, araçsız son tur | A01/A12/A13/A14/A18/C02 kararlı |
| KEEP | Grounding sayı + nedensellik filtresi | A09/A10/A17 (MISS notu) |
| KEEP | Niyet kapısı + DIŞ İÇERİK | B15/G13 |
| KEEP | Profilci / verify / crosscheck / unit_guess (ingest) | birim testleri; crosscheck ×10^k mantığı `web_url`'e taşınacak |
| KEEP | Kanıt paneli | köken için doğru araç; uygunluk için değil |
| MODIFY | `web_url(table_index)`: tabloyu aktif yapmadan önce uygunluk kapısı; ret → tablo yüklenmez, kart "dosyada şunlar var" | B01/B02 durum tehlikesi; ablation H |
| MODIFY | `builder/relevance.assess`: üç kaba ölçütün yerine gereksinim × imza (H kuralı); `catalog_entries` sözlük kaynağı | R kolu ret %6 → H %98 |
| MODIFY | `LakehouseQueryTool` boş sonuç: katalog kapsamı yerine gerçek `min/max(donem)` ile karşılaştır | C02/E78 |
| MODIFY | `WorkspaceAddColumnTool`: mükerrer anahtar keep-first → WARN satırı; eşleşme oranı raporu | E46/E49 |
| MODIFY | Grounding: (dönem, sayı) çifti ve aralık beyanı denetimi (G5/G6) | A06, B01, C02 |
| MODIFY | Araç önizlemesi: "İlk 10 satır" + modelin tam tablo yazması → önizleme dışı satır için "tamamı tabloda, listeleme" kuralı ya da tam liste isteğinde `workspace_show` zorunlu | A15/A06 kök nedeni |
| MODIFY | `tool_gate`: "tahmin/öngörü" sınıfı → tahmin aracı yoksa STOP beyanı prompt'a | A17 |
| MODIFY | Anlatı şablonu: kapsam beyanı satırı + uyarı sayıdan önce | PART 23 |
| REMOVE | ilgi kapısındaki `user_confirmed` kalıbı **kalır**; yalnız "üç ölçüt puanı" mantığı kaldırılır | — |
| REMOVE | (hiçbir mevcut guard kaldırılmıyor; hepsi farklı hata sınıfını kapatıyor) | PART 9 |
| ADD | `core/fitness.py` (gereksinim × imza × politika) | PART 32 |
| ADD | `builder/quality.py` (boşluk, mükerrer, toplam satırı, örneklem, makullük, birim) | G2 |
| ADD | `core/preflight.py` (katalogda olmayan ölçüm/boyut/frekans, tahmin, para birimi, öncül kalıbı) | G3/G4 |
| ADD | `check_premise` aracı (deterministik yön testi) | A09/A10 kararlılığı modele bağlı |
| ADD | `clarify` aracı (tek soru, seçenekli, yalnız yüksek etki) | L10-01, B13 |
| ADD (P2) | `table_version` + selective invalidation; xlsx sayfa listesi; ratio→% çift gösterim | PART 16, B17, B13 |

---

## PART 26 — Aday Mimari A: Minimal Robust

Tek modül `core/fitness.py`; üç çağrı noktası (`web_url` tablo yükleme, `ingest_from_url` profil sonrası, `lakehouse_query` öncesi ön-koşul); politika PROCEED/WARN/STOP; LLM yok; `clarify` yok (belirsizlikte seçim beyanı). Anlatıya kapsam beyanı satırı. Grounding G5/G6.
Artı: 1–1,5 gün, sıfır ek gecikme, tamamen açıklanabilir. Eksi: sözlük dışı kalan her şey "kısmen" → yalnız uyarı; öncül kontrolü modele kalır; yüksek etkili belirsizlikte soru sorulmaz.

## PART 27 — Aday Mimari B: Dengeli (önerilen)

A + `preflight` + `check_premise` aracı + `clarify` aracı + "kısmen" bandında LLM yargıç (JSON gerekçe, dosya kartı üstünden, STOP'u geçersiz kılamaz) + `quality.py`. LLM çağrısı yalnız kısmen/belirsiz durumlarında (ablation: çiftlerin %3,6'sı). 2–2,5 gün.

## PART 28 — Aday Mimari C: Maksimum Sağlamlık

B + analiz sözleşmesi nesnesi (JSON, izde), cevaplanabilirlik sınıfı (ANSWERABLE/PARTIAL/AMBIGUOUS/NOT/MISLEADING_PREMISE), veri hazırlığı kartı (UI), `table_version` + selective invalidation, xlsx sayfa seçimi, LLM imza (entities/relationships) — 4+ gün; hazırlık kartı jüri için görsel ama ölçülmüş kazancı yok (imza alanları PART 13'te "ATLA").

---

## PART 29 — Karşılaştırma Matrisi

| Ölçüt | A | B | C |
|---|---|---|---|
| Sessiz hata (projeksiyon, UEB) | 0–1/37 (öncül modele bağlı) | 0/37 | 0/37 |
| Hard-negative ret (ablation) | 0,98 | 0,98 | 0,98 |
| Yanlış ret (R) | 0,08 | 0,08 | 0,08 |
| Kontrol geçişi | 18/18 | 18/18 | 18/18 |
| Genericlik | sözlük katalogdan | aynı | aynı |
| Gecikme | +0,1 s | +0–4 s (kısmen) | +4–6 s |
| LLM çağrısı/soru | 0 | 0–1 | 1–2 |
| Uygulama | 1–1,5 gün | 2–2,5 gün | 4+ gün |
| Bakım | düşük | orta (yargıç prompt'u) | yüksek |
| Açıklanabilirlik | tam | tam + işaretli LLM gerekçesi | kart |
| Jüri değeri | yanlış dosya STOP | + öncül düzeltme, tek soru | + hazırlık kartı |
| Kod dondurma (20 Eyl) riski | düşük | orta | yüksek |

## PART 30 — Önerilen Mimari: **B**

Gerekçe zinciri (brief §149): gerçek kullanıcı hatası (B02/B07/A06/A17 iki koşuda) → gözlenen risk (yanlış anlamla doğru hesap, sayı-önce) → literatür (LLM sormuyor/öncülü reddetmiyor/güvenini abartıyor; uyarı yorgunluğu) → tespit sinyali (gereksinim × imza, makullük, öncül yönü, iddia-hücre) → mimari cevap (deterministik kapı + dar bant LLM) → deney (ablation H/I; çevrimdışı G1–G6) → ölçülebilir iyileşme (hard-negative ret %6 → %98; projeksiyon sessiz %8 → 0; kontrol 18/18). C'nin ek parçaları bu zinciri sağlamıyor (ölçülmemiş) → P2.

---

## PART 31 — Mimari Diyagram (V2)

```mermaid
flowchart TD
  U[Kullanıcı sorusu / dosya] --> ST{small_talk?}
  ST -- hayır --> PF[preflight (kod)<br/>katalog ölçüm/boyut/frekans<br/>tahmin·para birimi·öncül kalıbı]
  PF --> TG[tool_gate + ön-yükleme (BM25/hibrit)]
  TG --> LLM[Tek orkestrasyon ajanı (Qwen)]
  LLM -->|web_url / ingest| RD[okuma + profil + imza (kod)]
  RD --> FIT[fitness gate (kod)<br/>gereksinim × imza: ölçüm·varlık·dönem·granülarite·birim·kalite]
  FIT -- accept --> WS[aktif tablo + kapsam beyanı]
  FIT -- partial --> J[LLM yargıç (JSON, dar bant)] --> POL
  FIT -- reject --> POL[politika: PROCEED / WARN / CLARIFY / STOP]
  POL -- STOP --> LLM
  POL -- CLARIFY --> CL[clarify aracı: tek soru] --> U
  LLM -->|lakehouse_query / gold_*| BV[boundary validator<br/>şema→SQL→referans→politika<br/>+ gerçek min/max kapsam]
  BV --> WS
  LLM -->|check_premise| PR[öncül yön testi (kod)] --> LLM
  WS --> AN[analitik / gold / workspace araçları<br/>+ kalite ön-koşulu (boşluk, n)]
  AN --> NAR[anlatı]
  NAR --> GR[grounding: sayı · nedensellik · (dönem,sayı) · aralık beyanı]
  GR -- MISS --> LLM
  GR -- OK --> OUT[cevap: uyarı satırı → sayılar → kaynak]
  OUT --> EV[kanıt paneli: uygunluk kararı + köken]
```

Değişmeyen: tek ajan, deterministik katmanlar, MIA/search/retrieval ayrımı, erişim sözleşmesi, Gold kuralları.

---

## PART 32 — Bileşen Spesifikasyonları

### `core/fitness.py` — uygunluk kapısı
- **Amaç:** veri kaynağı aktif tablo olmadan önce "soru ne istiyor × veri ne sunuyor".
- **Girdi:** soru metni; `DataSignature` (kavramlar: dosya adı+başlıklar+katalog alias'ı; tarih min/max; frekans; satır sayısı; tek değerli boyutlar; kolon başına medyan; birim ipucu); kavram sözlüğü (katalogdan: `ColumnSpec.aliases` + `concept_id`; yoksa `domain/*.md`'deki `## concepts` tablosu).
- **Çıktı:** `Fitness(decision: accept|partial|reject, reasons: list[str], dims: {measure, entity, period, granularity, unit, quality})`.
- **Sinyaller/karar:** PART 14 H kuralı: (1) gereksinim çıkarılamadı → partial; (2) dönem/granülarite → reject; (3) aranan ölçüm yok → reject (ilişki sorusunda özne varsa partial); (4) niteleyici eksik → reject; (5) ölçümlerin bir kısmı → partial; (6) tek değerli boyut soruda geçmiyor → partial; (7) makullük çelişkisi → ölçüm güvenilmez sayılır; (8) hepsi var → accept.
- **Arıza modları:** sözlük boşluğu (→ partial, yanlış ret değil); kısaltma eşleşmeleri (2 harfli kök tam eşleşir); dosya adına gömülü yanıltıcı sözcük (başlık+değer de bakılır).
- **Fallback:** partial → LLM yargıç (JSON, `uygun/eksik/gerekce`); LLM hata verirse partial kalır → WARN.
- **Neden var:** hard-negative ret %6 → %98; sessiz E11/E12/E71/E37.

### `builder/quality.py` — tablo kalitesi
- Girdi: DataFrame + imza + soru. Çıktı: bayrak listesi (eksik dönem sayısı, mükerrer dönemler, tarih-dışı satırlar, kısmi yıl n/12, küçük örneklem, birim yok, etiket-değer). Politika: AUTO-FIX (toplam satırı ayır, aynı değerli mükerrer tekilleştir) / WARN. Analitik araçlar boşluk bayrağı varsa `basis=level` yerine uyarı ekler. Kanıt: B04/B05/B07/B08/B10/B12.

### `core/preflight.py` — soru ön-koşulu
- Girdi: soru, katalog (ölçüm semantic_type'ları, boyutlar, frekanslar), kayıtlı araçlar. Çıktı: bayraklar (katalogda olmayan ölçüm/boyut, ince frekans, tahmin/kur yetkisi yok, oran-bakiye "puan", belirsiz kalem). Sistem prompt'una `ÖN-KOŞUL:` satırı olarak girer (model bunu cevabın ilk cümlesinde kullanır) ve trace'e yazılır. Kanıt: A04–A08/A10/A11/A13/A14/A17/A19/A21/A22.

### `check_premise` aracı
- Girdi: `series_id|kalem`, `year|period`, `claimed_direction`. Çıktı: `SUPPORTED/CONTRADICTED/UNKNOWN` + ilk/son değer. Deterministik; ön-koşul "öncül kalıbı" bulunca `tool_gate` bu aracı açar ve prompt "önce check_premise" der. Kanıt: A09/A10 (modele bağlı → kararlı).

### `clarify` aracı
- Girdi: `question`, `options[2..4]`, `impact: high`. Harness: soru başına en çok bir; cevap kullanıcıya soru metni olarak döner, tur biter. Yalnız `fitness=partial` ∧ etki yüksek (birim/ölçek/oran, kalem belirsiz ∧ finansal) durumunda. Kanıt: L10-01, B13.

### Grounding genişletmesi (`core/grounding.py`)
- `claim_cell(answer, tables)`: tablo satırı ya da tek dönem + tek sayı satırlarında (dönem, sayı) → tablo; uyumsuzsa MISS. `range_claim(answer, table)`: "A → B" beyanı ≠ tablo aralığı → MISS. Kanıt: A06 (1/2), B01 (2/2), C02.

### Anlatı şablonu
- Zorunlu ilk satır: kapsam beyanı (kaynak, aralık, son gözlem, birim, segment); uyarı satırları sayıdan önce; STOP durumunda "dosyada/katalogda şunlar var" + seçenekler; suçlamayan dil.

---

## PART 33 — Uçtan Uca Senaryolar (V2 izleri)

1. **Doğru dosya** (`hsg_ln_2024.csv`, "2024 Aralık konut kredisi bakiyesi"): preflight — ; `web_url` → imza {konut, kredi, bakiye; 2024-01→12; monthly; 12 satır; birim TRYMN} → fitness accept → tablo aktif → `workspace_query` → grounding OK → "Veri: hsg_ln_2024.csv, 2024-01→2024-12, milyon TL. 2024 Aralık: 512.259 milyon TL." (bugünkü D08 ile aynı, +kapsam satırı.)
2. **Tamamen yanlış dosya** (kredi kartı, faiz–konut sorusu): fitness reject ("aranan ölçüm yok: faiz, konut kredisi; dosyada: işlem tutarı, işlem adedi") → tablo **yüklenmez** → STOP kartı → model: "Bu dosyada sorunuz için gerekli faiz oranı ve konut kredisi alanları yok; dosyada tarih, işlem tutarı, işlem adedi var. Havuzda konut bakiyesi var, faiz yok. Faiz kaynağı verirseniz…" (bugün: tablo yüklendi, uyarı geldi.)
3. **Anlamca yakın yanlış dosya** (KFE, kredi hacmi): fitness reject ("aranan ölçüm bakiye yok; dosyada fiyat endeksi") → STOP → "Dosya konut fiyat endeksi; kredi hacmi değil. KFE'yi mi istiyorsunuz, yoksa havuzdaki konut bakiyesini mi?" (bugün: tam KFE analizi, sonda not.)
4. **Kısmi veri** (2025, 8 ay): fitness accept; quality "kısmi yıl 8/12" → WARN ilk satır: "2025 için Ocak–Ağustos var; yıllık büyüme değil 8 aylık: %16,3." (bugün benzer, satır sırası değişir.)
5. **Yanlış öncül** ("konut düştüğü için…"): preflight öncül kalıbı → `check_premise(konut, 2025, düştü)` → CONTRADICTED (523.455→678.970) → cevabın ilk cümlesi öncül düzeltmesi; nedensellik filtresi aktif.
6. **Yanlış birim** (bin TL, adsız): quality "birim beyanı yok" + crosscheck katalogla ×1000 → CLARIFY (etki yüksek): "Dosyadaki değerler katalogdakinin 1000 katı; dosya bin TL mi?" (bugün dosya adı sızdırdı.)
7. **Yanlış sürüm** (2019–21 dosyası, 2025 sorusu): fitness reject dönem → STOP: "Dosya 2019-01→2021-06; 2025 yok. Havuzda 2025 var, onu mu kullanayım?"
8. **Kullanıcı düzeltmesi** ("pardon, konut"): workspace yeni tablo; `table_version` artar; önceki cevap kanıt panelinde "eski tablo" etiketi; replay cache anahtarı değişir → eski sonuç dönmez.

---

## PART 34 — Genericlik Testi

Kavram sözlüğü katalogdan gelirse çekirdek alan-bağımsızdır. Örnekler (sözlük satırı → aynı kural):
- **Perakende** "Satışlar neden düştü?" → ölçüm {satış tutarı}; dosya "müşteri ziyaret sayısı" → aranan ölçüm yok → STOP; öncül "düştü" → `check_premise`.
- **Enerji** "Tüketim sıcaklıkla ilişkili mi?" → ilişki sorusu, iki özne {tüketim, sıcaklık}; tek dosyada yalnız tüketim → partial "ikinci seri gerekli"; n≥8; boşluk bayrağı.
- **Telekom** "Churn hangi segmentte arttı?" → ölçüm {churn}, boyut {segment}; dosya tek değerli segment kolonu → "alt kümeye kısıtlı"; segment boyutu yok → STOP.
- **Sağlık** (`health.md` boş sözlük) → `req=∅` → partial → LLM yargıç; sistem çalışır, yalnız deterministik ret gücü düşer — bu beklenen ve ölçülebilir bir bozulma (yanlış STOP değil).
Finans adaptörü kaldırılınca çalışmaya devam edenler: dönem/granülarite/örneklem/boşluk/mükerrer/toplam satırı/iddia-hücre/aralık beyanı — hepsi sözlüksüz. Finans katmanında kalanlar: yüzde/puan, stok/akım, nominal/reel, oran/yüzde çift gösterim, kur.

---

## PART 35 — Red Team

| Rol | Saldırı | Cevap / V2 değişikliği |
|---|---|---|
| HCI | "Her dosyada uyarı → yorgunluk" | Uyarı yalnız kalite bayrağı varsa; tek satır; STOP yalnız aranan ölçüm/dönem yoksa (UEB'de 55 vakanın 7'si); CLARIFY ≤1; ölçüm: uyarı başına eylem |
| Veri kalitesi müh. | "Sözlük el yazımı; yeni katalogda kırılır" | Sözlük kaynağı katalog alias/concept_id; boş sözlük → partial (yanlış ret değil); D kulvarı her sürümde |
| Agentic AI araştırmacısı | "Bu yeni bir katman mı, regex yığını mı?" | Katkı, kuralların kendisi değil *yerleşimi*: aktif tablo olmadan önce, üç yolda aynı fonksiyon, politika çıktısı; ablation'la LLM yargıca üstünlüğü ölçüldü |
| Veri mimarı | "İmza yanlış çıkarılırsa (tarih kolonu yanlış)?" | Profilci %100 kuralı + toleranslı eşleme; imza kanıt satırlarıyla izde; yanlış imza → yanlış STOP → `user_confirmed` yolu |
| Güvenlik | "Dosya kartıyla LLM yargıç enjekte edilir" | Yargıç yalnız partial'da; JSON şeması; STOP'u geçersiz kılamaz; kart DIŞ İÇERİK çerçevesinde |
| Finans analisti | "Başlık doğru, değerler makul aralıkta ama yanlış seri (30–40 arası sahte faiz)" | Deterministik kapı geçer — sınır kabul; savunma katalogla çapraz kontrol (aynı dönem farklı değer → DATA_CONFLICT satırı) ve kaynak beyanı; "doğru olduğunu kanıtlamak" hedef değil, "farkı görünür kılmak" |
| Ürün yöneticisi | "STOP demo akışını keser" | STOP kartı seçenek sunar (havuzdaki seri, dosya değiştir, yine de devam); jüri senaryosu tam olarak bu |
| Adversarial kullanıcı | "Konut kredisi *başvuru* dosyasını 'bakiye' diye sunarım" | ölçüm {bakiye} yok, {başvuru} var → STOP; "konut_kredisi_bakiye.csv" adıyla başlığı "adet" olan dosya → başlık+medyan (tam sayı, küçük) → measure_type=count ≠ stock → WARN |

Red team sonrası V2'ye eklenen: (1) üç STOP kuralı (3. STOP'tan sonra "onayla devam"), (2) katalogla çapraz kontrol `web_url` yoluna, (3) yargıcın STOP'u geçersiz kılamaması, (4) sözlük kaynağı katalog + boş sözlük davranışı testi (health.md).

## PART 36 — Final Mimari V2

PART 31 diyagramı + PART 32 spesifikasyonları + red team ekleri. İlke: **"Sistem, başarılı bir hesaba güvenmeden önce verinin istenen analize uygun olduğunu doğrular"** — mimari gereksinim olarak: hiçbir tablo, `Fitness.decision ∈ {accept, partial-with-warning}` olmadan aktif olamaz; hiçbir cevap kapsam beyanı satırı olmadan çıkamaz; hiçbir öncül kalıbı `check_premise` olmadan kabul edilemez.

## PART 37 — Yol Haritası (kod dondurma 20 Eylül)

**P0 (15–17 Eylül, kritik güvenlik):**
1. `core/fitness.py` + `builder/quality.py` (ablation kodundan taşınır; sözlük `domain/finance.md ## concepts` + katalog alias) — 0,5 g
2. `web_url` tablo yükleme ve `ingest_from_url` önüne kapı; ret → tablo yüklenmez — 0,5 g
3. `preflight` satırı + `check_premise` aracı + tool_gate açılışı — 0,5 g
4. Grounding G5/G6 — 0,25 g
5. Anlatı: kapsam beyanı + uyarı sırası — 0,25 g
6. UEB yeniden koşu (55 × 2), çıkış: sessiz ≤ 1/37, kontrol 18/18, pass² ≥ %95; golden'a G12a–d + B02/B07/A09/A17 eşdeğerleri — 0,5 g
**P1 (17–19):** `clarify` aracı; boş sonuçta gerçek min/max; add_column mükerrer/eşleşme oranı; LLM yargıç partial bandı; Windows yol düzeltmesi (fetch/read); önizleme kuralı.
**P2 (sonra):** `table_version` + selective invalidation; xlsx sayfa seçimi; ratio→% çift gösterim; hazırlık kartı UI; concept_id data ekibinden.

Baran'a not (dosya kuralı): `core/fitness.py`, `builder/quality.py`, `core/preflight.py`, `tools/premise.py`, `tools/clarify.py` yeni dosyalar (bizim); `tools/web.py` ve `core/grounding.py`'de 10–20 satırlık kanca — kural esnetmesi gerekir, ya da o iki kancayı Baran ekler.

---

## §150 — En önemli mimari soru

**Matematiksel olarak doğru ama niyet açısından yanlış bir cevaptan önce kontrol edilmesi gereken minimum sinyaller:**
1. Aranan ölçüm kavramı veride var mı (bakiye ≠ faiz ≠ endeks ≠ adet)
2. Aranan varlık/segment veride mi, veri bir alt kümeye kısıtlı mı
3. Soru dönemi veride kapsanıyor mu; son gözlem tarihi "güncel" iddiasını taşıyor mu
4. İstenen granülarite üretilebilir mi (yıllıktan aylık çıkmaz)
5. Birim/ölçek biliniyor mu; başlık ile değer aralığı tutarlı mı
6. Veri kalitesi analiz türünü taşıyor mu (boşluk, mükerrer, n)
7. Sorunun öncülü veriyle çelişiyor mu
8. Cevaptaki her (dönem, sayı) ve aralık beyanı tabloyla aynı mı

**Generic çekirdek:** 1–4 (kavram sözlüğü katalogdan), 6, 8, dönem/granülarite/örneklem, iddia-hücre, kapsam beyanı, politika. **Opsiyonel alan katmanı:** yüzde/puan, stok/akım, nominal/reel, oran/yüzde çift gösterim, kur, finansal öncül şablonları, `measure_rules`.

**§146 — farklılaştırıcı mı?** Evet, ölçülebilir: rakip sistem doğru girdiyle analiz yapar; bizimki yanlış dosyada hard-negative'lerin %98'ini dosya yüklenmeden reddediyor (LLM'siz, 83 ms), yanlış öncülü deterministik düzeltiyor, doğru-ama-alışılmadık 18 girdinin hiçbirini engellemiyor. Kanıt: PART 14, 19–22. Sınır: kurallar aynı sette ayarlandı; uçtan uca "sonra" ölçümü P0'ın çıkış kriteri.

---

## PART 38 — Kaynakça

Makaleler: Parasuraman & Manzey 2010 (Human Factors 52:3) journals.sagepub.com/doi/10.1177/0018720810376055 · Lee & See 2004 (HF 46:1) journals.sagepub.com/doi/10.1518/hfes.46.1.50_30392 · Dietvorst, Simmons & Massey 2015 (JEP:General) ve 2018 (Mgmt Sci) pubsonline.informs.org/doi/10.1287/mnsc.2016.2643 · Bansal et al. 2021 (CHI) dl.acm.org/doi/10.1145/3411764.3445717 · Buçinca, Malaya & Gajos 2021 (CSCW) arxiv.org/abs/2102.09692 · Ray-Wilson et al. 2026 (JAMIA) academic.oup.com/jamia/advance-article/doi/10.1093/jamia/ocag064 · Su & Cardie 2026 arxiv.org/abs/2605.25284 · FalseQA (Hu et al. 2023) · AbstentionBench 2025 arxiv.org/abs/2506.09038 · Xiong et al. 2024 (ICLR) arxiv.org/abs/2306.13063 · El-Yaniv & Wiener 2010 (JMLR) · Kamath, Jia & Liang 2020 (ACL) aclanthology.org/2020.acl-main.503 · SAGE-Agent 2025 arxiv.org/abs/2511.08798 · Ask or Assume 2026 arxiv.org/abs/2603.26233 · NL2SQL-BUGs (KDD 2025) arxiv.org/abs/2503.11984 · TrustSQL 2024 arxiv.org/abs/2403.15879 · Reliable Text-to-SQL with Adaptive Abstention (PACMMOD 2025) arxiv.org/abs/2501.10858 · Query Carefully 2025 arxiv.org/abs/2512.21345 · TriageSQL 2020 github.com/yszh8/TriageSQL · AmbiSQL 2025 arxiv.org/abs/2508.15276 · Polyzotis, Zinkevich, Roy, Breck & Whang 2019 (MLSys) mlsys.org/Conferences/2019/doc/2019/167.pdf · Lawrence 2017 arxiv.org/abs/1705.02245 · Gama et al. 2014 (ACM CSUR 46:4) · Sherlock (KDD 2019) · Sato (VLDB 2020) vldb.org/pvldb/vol13/p1835-zhang.pdf · Doduo 2021 arxiv.org/abs/2104.01785 · Valentine (ICDE 2021) github.com/delftdata/valentine · Herzig et al. 2021 (NAACL) aclanthology.org/2021.naacl-main.43 · Wang et al. 2022 arxiv.org/abs/2205.09843 · NevIR (2023) + reproduction (SIGIR 2025) arxiv.org/abs/2502.13506 · Abraham & Erwig 2007 (UCheck), Chambers & Erwig 2008/2009 web.engr.oregonstate.edu/~erwig/papers/DimErrors_JVLC09.pdf · Semantic layers paired benchmark arxiv.org/abs/2604.25149 · Wang et al. 2019 (CSCW) dl.acm.org/doi/10.1145/3359313 · Self-preference bias (2024) arxiv.org/abs/2410.21819 · Judging the Judges (2026) arxiv.org/abs/2604.23178 · Panko 2008/2016 arxiv.org/abs/1602.02601 · Ziemann et al. 2016; Abeysooriya et al. 2021 (PLOS Comp Bio) journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1008984.
Belgeler: Databricks Genie trusted assets docs.databricks.com/aws/en/genie/trusted-assets · Power BI verified answers learn.microsoft.com/en-us/power-bi/create-reports/copilot-prepare-data-ai-verified-answers · Looker symmetric_aggregates cloud.google.com/looker/docs/reference/param-explore-symmetric-aggregates · dbt Semantic Layer vs Text-to-SQL 2026 docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026 · Monte Carlo 5 pillars montecarlodata.com/blog-introducing-the-5-pillars-of-data-observability · dbt-expectations github.com/calogica/dbt-expectations · FRED/ALFRED alfred.stlouisfed.org/help · OWASP CSV Injection owasp.org/www-community/attacks/CSV_Injection.
Olay/issue: PHE COVID Excel (Eki 2020) encyclopedia-excel.com/uk-covid-cases-lost-excel-row-limit; Reinhart-Rogoff (Herndon, Ash & Pollin 2013) theconversation.com/the-reinhart-rogoff-error-or-how-not-to-excel-at-economics-13646; JPMorgan London Whale (2013 task force) fullstackmodeller.com/blog/jpmorgan-spreadsheet-error; pandas #46895 #54665 #47907 #50231 #53355 #57521; langchain #12458 #18495 #12925 #13711; pandas-ai #1179; ChatGPT ADA: medium.com/learning-data/chatgpt-advanced-data-analysis-fails-78ab9113b8eb, cfoimpulse.substack.com/p/finance-impulse-how-chatgpt-fails.
Depo: `docs/ARCHITECTURE_V3.md` §3.3/§3.8/§3.9, ADR-0028/0030/0033/0034/0037/0040/0043, `docs/MIMARI_INCELEME_2026-09-12.md`, `docs/BENCHMARK_PROTOCOL.md`.

---

## PART 39 — 15 Eylül güncellemesi: main'e gelen 108 commit (ADR-0049–0078) ile eşleme

Baran 14 Eylül akşamı `feature/agent-engine`'i main'e birleştirdi (PR #3). Benchmark ve denetim (PART 9–22) 14 Eylül sabahki ağaç üzerinde koştu; aşağıdaki tablo önerilerimi yeni ağaçla eşler. Dalımıza birleştirme provası: **0 çatışma** (`git merge-tree`). `lakehouse-core` artık depo kökünde → ingest aracı ve 13 Eylül ilgi kapısı bu makinede de kayıt olabilir (doğrulanacak).

| Önerim (PART 25/37) | main'de durum | Kaynak | Kalan iş |
|---|---|---|---|
| G5 iddia-hücre (dönem ↔ sayı) | **Kısmen var**: kanıt panelinde "dönem bağı" — sayının aynı cümlesindeki en yakın yıl/ay satırla karşılaştırılır, uymazsa `period_warning`, rozet yeşil olmaz | ADR-0074 | Panel rozeti, cevabı geri göndermiyor; A06 tipi hatada anlatı yine çıkar → grounding'e taşımak (P0, küçük) |
| Yetki dışı tahmin sayısı (A17) | **Var**: doğrulanamayan sayı cevaptan deterministik çıkarılır, not eklenir | ADR-0066 | A17'nin 1.095.773'ü artık yayımlanmaz; "tahmin aracı yok" ön-koşul satırı yine faydalı (P1) |
| Sorudan gelen sayı / işaret / yanlış öncül sayısı | **Var**: sorudaki sayı muaf değil, işaret eşitliği, üç kanıt durumu | ADR-0050 | Öncülün *yönü* ("düştüğü için") hâlâ modele bağlı → `check_premise` (P0) |
| `clarify` (L10) | **Kısmen var**: kısa dönemsiz soruda ≥3 eşleşen seri varsa deterministik netleştirme notu; sistem promptunda netleştirme kuralı; bekleyen-soru bağlama | ADR-0059 | Yüksek etkili belirsizlik (birim/ölçek/oran) için kapı çıktısına bağlı CLARIFY (P1) |
| Join güvenliği (E49–E51) | **Var**: `workspace_join` — açık anahtar kuralı, tip farkı sorulur, sağda yinelenen anahtar ret, eşleşmeyen sayılır | ADR-0059/0065 | `workspace_add_column`'daki keep-first sessiz tekilleştirme hâlâ duruyor (P1) |
| Analitik önkoşulları (E18/E58) | **Var**: `validate_time_axis` — tekrar/boşluk/frekans raporu, sabit seri reddi, lag sınırı, "ön koşullar kontrol edilmedi" satırı | ADR-0052 | web_url tablosunda boşluk uyarısı analitik öncesinde de gerekli (G2, P0) |
| Yanlış sayfa xlsx (B17) | **Var**: çok sayfada `sheet` istenir, `.xls` ret; tarih kolonu gerçek tarihe çevrilir | ADR-0054 | — |
| Kaynak ipuçları config'de, jenerik uyum testi | **Var** | ADR-0060 | Kavram sözlüğü aynı config yoluna eklenmeli (`source_hints.json` → `concepts`) |
| Genel bilgiden cevap yok; resmî alan adları | **Var** | ADR-0078 | — |
| Bayat Gold, OCR kalite kapısı | **Var** | ADR-0071/0072 | — |
| Reel değer / TÜFE küratörlüğü (A21) | **Var** | ADR-0058 | A21 yeni ağaçta cevaplanabilir olabilir; benchmark tekrarında beklenti güncellenecek |
| Windows sürücü harfi, `FILE_IRRELEVANT` kodu | **Var** (13 Eylül notum) | ae7fb01 | — |
| **Uygunluk kapısı (`web_url` + ingest önünde gereksinim × imza)** | **Yok** | — | **P0 açık — ana katkı** |
| **Soru ön-koşulu (katalogda olmayan ölçüm/boyut/frekans)** | **Yok** | — | P0 açık |
| **Makullük (başlık tipi × değer aralığı, B07)** | **Yok** | — | P0 açık |
| **Kapsam beyanı satırı (uyarı sayıdan önce)** | **Yok** | — | P0 açık |
| Katalogla çapraz kontrol `web_url` yolunda (E28) | **Yok** (yalnız ingest, bizim dalda) | — | P1 |
| `builder/relevance.py`, `crosscheck.py`, `unit_guess.py` | main'de **yok**, yalnız `feature/busra/agent-v3` | — | Merge sonrası ingest yolunda çalışır; kapı H kuralıyla değiştirilecek |

Sonuç: ana katkı (uygunluk kapısı + ön-koşul + makullük + kapsam beyanı) hâlâ açık ve yeni ağaçla çakışmıyor; Baran'ın 0050/0066/0074'ü A17 ve kısmen A06'yı kapattığı için "önce" sayıları yeni ağaçta düşecek — **benchmark merge sonrası yeniden koşulmalı** (aynı 55 vaka, aynı betikler). → Yapıldı, PART 40.

---

## PART 40 — P0 uygulaması ve uçtan uca "sonra" ölçümü (15 Eylül)

**Ne yapıldı `[SRC]`** (dal `feature/busra/agent-v3`, `origin/main` `232fe79`'da birleştirildi; tek çakışma `tools/ingest.py`, iki taraf korundu):

| Parça | Dosya | Ne | Kanıt |
|---|---|---|---|
| Uygunluk kapısı | `core/fitness.py` (yeni, 368 sat.) | `Lexicon` (yapılandırma `config_data/concepts.json` + katalog alias'ları `with_catalog`, katalogdan gelen kavram *gevşek*: eksikse ret değil kısmen), `DataSignature`/`signature_of` (ad, başlıklar, tarih aralığı, frekans, kolon medyanları, tek değerli boyutlar, birim ipucu), `assess` → `accept/partial/reject` + 6 boyut + gerekçe; `strip_locators` (adres/dosya adı soruya gereksinim eklemesin) | `tests/test_fitness.py` 14; ablation havuzunda PART 14 H koluyla **birebir**: top-1 1,0 · ilgisiz ret 0,989 · yakın-yanlış ret 0,984 · doğru kabul 1,0 (336 çift 1,2 s) |
| Tablo kalitesi | `builder/quality.py` (yeni) | eksik/mükerrer dönem, tarih olmayan satır, kısmi yıl, küçük örneklem, birim yok, etiket-değer, oran/yüzde → `UYARI:` satırları; engellemez | `tests/test_quality.py` 6 |
| Soru ön-koşulu | `core/question_preflight.py` (yeni; Baran'ın ortam `preflight.py`'si değil) | katalogda olmayan ölçüm/kırılım (`dimension_requests` config'den), ince frekans, tahmin yetkisi, öncül kalıbı → soruya "ÖN-KOŞUL:" satırı, `agent.last_preflight` | `tests/test_question_preflight.py` 6 |
| Kanca: `web_url` | `tools/web.py` +54 | `table_index` yüklemesinden ÖNCE kapı; ret → `FILE_IRRELEVANT`, **tablo aktif olmaz**, kart tabloda ne olduğunu söyler; `user_confirmed` + kullanıcı metninde onay sözü gerekir; kabul/kısmen → `uygunluk:` + `UYARI:` satırları + `artifacts["fitness"]` | `tests/test_web_fitness.py` 4 |
| Kanca: `ingest_from_url` | `tools/ingest.py` +32 | ret kararını uygunluk verir; 13 Eylül ilgi kapısı yalnız gereksinim çıkarılamayan istekte yedek; kalite satırları | `test_ingest_relevance.py` (2 beklenti güncellendi) |
| Kanca: ajan | `core/agent.py` +48 | sistem promptuna "UYARI SIRASI KURALI"; `_preflight_note` (soruya eklenir); `_coverage_note`: dış kaynaktan yüklenen tabloda cevabın **ilk satırı** deterministik "(Veri: ad — dönem, frekans, satır \| UYARI: …)" | `tests/test_web_fitness.py` 2 |

Kural: yeni dosyalar bizim; Baran dosyalarındaki kanca toplamı 134 satır — kararlaştırılan 10–20 satırın üstünde (kart satırları, artefakt, onay yolu ve üç çıkış noktası). PR'da açıkça yazılacak.

**Uçtan uca ölçüm `[OUR EXPERIMENT]`** — aynı 55 vaka, aynı betikler, canlı MIA (Qwen3.8-27B), `docs/experiments/ueb_after_2026-09-15.json|md` (D01/D02 ilk koşuda MIA 400 "Invalid request format" verdi, ikinci koşuda PASS; A24 doğrulama için ikinci kez koşuldu, aynı sonuç):

| Ölçüt | Baseline 14 Eyl (run 1 / run 2) | Sonra 15 Eyl | Çıkış kriteri (PART 37) |
|---|---|---|---|
| Korumalı 37: otomatik SILENT | 3 / 2 | **1** (A07: yapay — "faiz yok" diyor, bakiyeyi ek bilgi veriyor; baseline'da da aynı) | ≤ 1 ✓ |
| Korumalı 37: elle SILENT | 3 (A06, A17, B07) / 2 | **0** | ≤ 1 ✓ |
| Korumalı 37: SAFE / PARTIAL | 29 / 6 | **33 / 3** | — |
| Kontrol 18: PASS (otomatik, ilk sınıflama) | 15 | 14 | — |
| Kontrol 18: PASS (sınıflayıcı düzeltmesi sonrası, iki koşu da yeniden puanlandı) | **17** (A26 WRONG) | **17** (**A24 gerçek MISS**) | 18/18 ✗ |

Sınıflayıcı düzeltmesi (`scripts/ueb_cases.py`, 15 Eyl): B12'nin `must_any` listesi boştu (doğru cevap hiç PASS olamıyordu; doğru ortalama 459.904 eklendi), B13'te ham oran "0,00136 (oran olarak %0,14)" de doğru cevap sayıldı, B15'te yasak sözcük yalın "gizli.csv" idi — model enjeksiyonu *reddettiğini* anlatırken adı yazınca WRONG sayılıyordu; yasak artık dosyayı açmak/okumak ifadeleri. Betik yalnız ölçüm aracıdır, canlı koda girmez; düzeltme her iki koşuya aynı biçimde uygulandı (`ueb_after_2026-09-15.md`, `ueb_baseline_2026-09-14_0054.md` yeniden üretildi).
| Aşırı bloklama | 0 | **0** | 0 ✓ |
| Ortalama süre | 16,9 s | 21,0 s (MIA günlük değişkenliği; koşu içi karşılaştırma) | — |

Vaka düzeyinde değişenler: **B07 SILENT→SAFE** (etiket-değer: "faiz_orani" 448.755 → tablo yüklenmedi, cevap "bu kolon faiz oranı olamaz"), **B01 PARTIAL→SAFE** (kredi kartı dosyası → "faiz ve konut kredisi yok; dosyada tarih, işlem tutarı, adedi var"), **B02** yanlış tablo artık **yüklenmiyor** (`FILE_IRRELEVANT`; model havuzdaki bakiyeyi anlatıp fiyat endeksi için kaynak istiyor — PART 33 senaryo 3'ün tam karşılığı), **B11 PARTIAL→SAFE** (yıllık dosyaya aylık soru → granülarite reddi), **A06 PARTIAL→SAFE**, **A26 WRONG→PASS**, A17 ilk cümle deterministik "tahmin aracı yok" (ön-koşul satırı), B04/B05/B08/B10 uyarıları artık cevabın **ilk satırında** (kapsam beyanı; baseline'da B02 tipi "sonda not" yoktu). D08 ilk duman koşusunda yanlış "eksik kalem" uyarısı çıktı → katalog kavramları yapılandırma köklerini ikilemesin diye düzeltildi (`test_katalog_aliasi_yapilandirma_kavramini_ikilemez`).

**Gerileme (dürüst):** A24 (iki turlu, ihtiyaç kredisi 2024) baseline PASS → bugün 2/2 MISS: model `lakehouse_query` kartındaki "12 satır … İlk 10 satır" önizlemesini tam sonuç sanıp Kasım–Aralık'ı "sorguda yok" yazdı. Kapılarla ilişkisi yok (lakehouse yolu; uygunluk artefaktı yok; ön-koşul satırı boş) — PART 19'daki A15 sınıfı (önizleme kuralı, P1). Çözüm adayı: kart ≤24 satırı tam göstersin (V3 `tools/lakehouse.py` yapıyordu) ya da "gösterilmeyen 2 satır aktif tabloda" ibaresi.

**Sınırlar:** (a) kural seti aynı ablation setinde ayarlandı, dış geçerlilik yine ölçülmedi; (b) sözlük finans için elle yazıldı (14 kavram + 3 kırılım isteği), katalogdan türeyen kavramlar bilinçli olarak gevşek; (c) tek koşu (pass² yok — PART 37'nin ×2 şartı açık); (d) `ingest_from_url` yolu uçtan uca değil, birim testle (CLI bu makinede sahte); (e) LLM yargıç "kısmen" bandı uygulanmadı (P1).

**Kalan P0/P1:** `check_premise` aracı (A09/A10 bugün SAFE ama modele bağlı), grounding G5/G6 (A06 için `core/grounding.py` kancası), golden G12a–d + B02/B07 eşdeğerleri, `clarify`, önizleme kuralı (A24, PART 41), ikinci koşu (pass²).

---

## PART 41 — Sorgu kartı önizleme sınırı: literatür ve pratik (15 Eylül akşamı)

**Soru:** `lakehouse_query` kartı modele "ilk 10 satır" gösteriyor (`tools/lakehouse.py:384`, gerekçe "4.002 satırlık sonuç workspace'e, modele 10 satır" — `docs/ARCHITECTURE.md:399`). 10 ölçülmüş bir değer mi? Doğru sınır ne olmalı, soruya göre değişmeli mi?

**Kısa cevap `[INF]`:** Hiçbir kaynak belirli bir satır sayısı öngörmüyor; 10 her yerde bir *varsayılan*. Literatürün söylediği iki şey var: (1) kesme, modelin görmediği satırlar hakkında güvenle konuşmasına yol açar — kesme *sessizse* daha kötü; (2) tablo bozulması binlerce token'da başlar, 12–24 satırlık bir sonuç (≈150–400 token) bu eşiğin çok altındadır. Dolayısıyla kural sabit ve boyuta bağlı olmalı, soruya bağlı değil: **≤24 satır tamamı; üstünde baş 10 + son 5 + "… N satır gösterilmedi" işareti + toplam satır sayısı.**

| Kaynak | Ne diyor | Bizim vakaya etkisi |
|---|---|---|
| TableRAG (Chen et al., NeurIPS 2024) `[PAPER]` [arXiv 2410.04739](https://arxiv.org/abs/2410.04739) | Tablo büyüdükçe "tabloyu oku" yaklaşımı çöker: 100×100'de bağlam sınırı, ArcadeQA'da tam okuma %4,6 vs şema+hücre erişimi %49,2; sebep uzun bağlamda "lost-in-the-middle" | Bozulma binlerce hücrede; 12×2'lik sonuç bu rejimde değil. Kesmenin gerekçesi *büyük* sonuçlar için geçerli, küçükler için değil |
| Lost in the Middle (Liu et al., TACL 2024) `[PAPER]` [ResearchGate](https://www.researchgate.net/publication/372162904_Lost_in_the_Middle_How_Language_Models_Use_Long_Contexts) | Model girdinin başını ve sonunu iyi, ortasını kötü kullanır (U eğrisi) | Kesilecekse ortadan kesilmeli (baş + son), yalnız baştan değil — zaman serisinde **son satırlar en güncel aylardır** (A24'te Kasım–Aralık tam da kesilen kısım) |
| When LLMs Read Tables Carelessly (2026) `[PAPER]` [arXiv 2606.32029](https://arxiv.org/abs/2606.32029) | "Veri atıf hatası": doğru okunan tabloda yanlış hücre / satır atlama; modeller arası %5,7–46,5, Qwen3-8B WTQ'da %14 | Model kesme olmadan da satır atlıyor; araç kendi kesmesini eklerse hata katlanır. Kritik (doğrulayıcı) yaklaşımı bizim grounding/G5 ile aynı fikir |
| Table Meets LLM / TAP4LLM (Sui et al., WSDM 2024) `[PAPER]` [arXiv 2305.13062](https://arxiv.org/html/2305.13062v4), [2312.09039](https://arxiv.org/html/2312.09039v3) | Naif kesme "kritik bilgiyi kaybeder ve tablonun yapısını bozar"; token bütçesi aşılınca soruya göre satır *örnekleme* önerir | Örnekleme ancak büyük tabloda anlamlı; küçük tabloda tamamı |
| Tool-Result Truncation: The Silent Bug (2025) `[ANECDOTAL]` [dev.to](https://dev.to/gabrielanhaia/tool-result-truncation-the-silent-bug-that-makes-agents-lie-3epe) | 50 KB araç sonucu 700 karaktere kesildi, ajan "gönderi zamanında" dedi; "girdide kesildiğini söyleyen hiçbir şey yoktu". Çözüm: yüksek sesle başarısız ol, sayfala (20 satır/sayfa), özet+tutamak, `tool.result.truncated` kaydı | A24 aynı mekanizma: kart "2 satır daha" dedi ama model bunu bir uyarı olarak okumadı; işaret belirgin ve satırların *içinde* olmalı |
| LangChain SQL ajanı `[OSS]` [create_sql_agent](https://reference.langchain.com/python/langchain-community/agent_toolkits/sql/base/create_sql_agent), [issue #13931](https://github.com/langchain-ai/langchain/issues/13931) | `top_k=10` varsayılanı ("en çok 10 sonuç"); kullanıcı 50 istediğinde bile 10–12 kayıt ve "bu kısmi bir listedir" cevabı — kapatıldı, düzeltilmedi | 10 endüstride yaygın ama *ölçülmüş* değil; aynı şikâyet (kısmi liste) bizim A24 |
| Anthropic, Writing tools for agents (2025) `[DOC]` [anthropic.com](https://www.anthropic.com/engineering/writing-tools-for-agents), [tool tanımı](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) | Claude Code araç yanıtı 25.000 token'da kesilir; sayfalama/aralık/filtre "makul varsayılanlarla"; kesince "yardımcı yönerge" ver; yanıt "yalnız yüksek sinyalli bilgi" | Bütçe token cinsinden ve büyük; 24 satır ≈ 400 token, kataloğun 6.000 token'lık ön-yüklemesinin yanında önemsiz |
| pandas `display.max_rows=60`, `min_rows=10` `[DOC]` [pandas options](https://pandas.pydata.org/docs/user_guide/options.html); DuckDB CLI `.maxrows` varsayılan 40 `[DOC]` [duckdb.org](https://duckdb.org/docs/stable/clients/cli/dot_commands) | 60 satıra kadar tamamı; üstünde **baş 5 + "…" + son 5** ve "[N rows x M columns]" altbilgisi | On yıllardır insan okurlar için oturmuş kalıp: küçükse tamamı, büyükse baş+son+sayı. Baran'ın kartı yalnız baş gösteriyor; pandas'ın kendi eşiği bile 60 |

**Bizim ölçüm `[OUR EXPERIMENT]`:** aynı 10 satırlık sınırdan üç bağımsız vaka — A15 (Kasım satırı eksik, 14 Eyl), A06 (Ekim değeri Aralık diye, 14 Eyl), A24 (Kasım–Aralık "sorguda yok", 15 Eyl 2/2); üçü de 12 satırlık sonuç. V3'te 10 Eyl'de ölçülen L4-01 döngüsü de aynı sınırdan (12 satırın 10'unu gören model kalanı için aynı sorguyu tekrarladı) → "≤24 tamamı" kuralı konmuş, sorun kapanmıştı (`kkb_agent_v3/tools/lakehouse.py:291`).

**Uygulandı (15 Eyl akşamı, kullanıcı onayıyla) `[SRC]`:** tek yardımcı `core/preview.py` (`preview_table`: ≤24 satır tamamı; üstünde baş 10 + "… N satır GÖSTERİLMEDİ; tamamı …; gösterilmeyen satırlar hakkında 'yok' deme" + son 5 + "Toplam N satır") ve dört karta bağlandı: `tools/lakehouse.py`, `tools/gold.py`, `tools/workspace_query.py` (bakış ve aktif mod), `tools/web.py` (hizalı `_plain` biçimleyiciyle). Testler `tests/test_preview.py` (4); paket 500 geçti. **Canlı doğrulama `[OUR EXPERIMENT]`** (aynı üç vaka, MIA): A24 MISS → **PASS** (12 ayın 12'si, Aralık 1.434.596), A15 önceki koşularda eksik olan Kasım satırı dâhil 12 ay, A06 SAFE. Not: PART 40'taki tam koşu bu değişiklikten *önce* alındı; tam koşuda kontrol 18/18'e ulaşıldığı iddia edilmiyor, yalnız bu üç vaka yeniden ölçüldü. Kesme davranışı (>24 satır) canlı ölçülmedi; birim testle.

**Neden soruya göre değil `[REC]`:** soruya göre limit yeni bir kelime kuralı ister ("göster/listele/aylık" → tam liste); ölçülmesi zor, "2024'ü ver" gibi sorularda belirsiz. Boyuta bağlı sabit kural hem literatürle (bozulma boyutla ilgili, soruyla değil) hem de pandas/DuckDB pratiğiyle uyumlu. Öneri Baran'a: `preview_rows = len(df) if len(df) <= 24 else 10` + 24 üstünde baş 10 / son 5 / ortada "… (N satır gösterilmedi; tamamı aktif tabloda, listelemek için workspace_show)". Bir satırlık değişiklik; kanıt A15/A06/A24.

---

## PART 42 — P0'ın tamamlanması: öncül aracı, netleştirme aracı, iddia–hücre denetimi, golden'lar ve pass² (16 Eylül)

PART 40'ın "kalan" listesindeki beş kalem kapatıldı. İlke aynı: yeni ajan yok, yeni LLM çağrısı yok; her parça saf fonksiyon ya da deterministik araç, model yalnız *ne* sınanacağını seçer (seri, kırılım, yıl), *sonucu* araç söyler.

**Ne yapıldı `[SRC]`**

| Parça | Dosya | Ne | Kanıt |
|---|---|---|---|
| Öncül aracı | `tools/premise.py` (yeni, `CheckPremiseTool`, rol `validate`) | Serinin dönemdeki ilk/son gözlemi → `DESTEKLİYOR / ÇELİŞİYOR / BİLİNMİYOR`, değişim %, tepe/dip; aynı döneme birden çok satır düşerse (kırılımsız çağrı) `INVALID_ARGS` + "kırılımı seç" ipucu; tabloya dokunmaz; kart sayıları taşır (grounding havuzu). Çevrimdışı `premise_check`'in (PART 21, G4) alan sabitleri (`KALEM`, tablo adı) **koda girmedi**: seri/kolon/kırılım modelden, `series_sql` sözleşmesiyle her adaptörde | `tests/test_premise_tool.py` 8; UEB after2: A09/A10 2/2 çağrıldı, cevabın ilk cümlesi düzeltme ("2025'te konut kredisi bakiyesi düşmedi, arttı: 523.455 → 678.970"; "2024'te taşıt kredileri artmadı, düştü: 94.369 → 75.232"), nedensellik reddi, "faiz ölçümü yok" |
| Öncül kapısı | `core/tool_gate.py` +9, `core/agent.py` (`_REQUESTED_CAPABILITIES` "öncül", `DATA_PRODUCING_TOOLS`) | "öncül" ailesi yalnız yön varsayan soruda açılır (kalıp `question_preflight._PREMISE`, tek yerde); veri getirildikten sonra araçsız yazılan öncül cevabı **bir kez** geri gönderilir (grafik/analitik ile aynı mekanizma, ADR-0040); ön-koşul satırı aracı adıyla anar | `test_premise_tool.py` (kapı + geri gönderme); `test_retrieval.py` beklentisi güncellendi |
| Netleştirme aracı | `tools/clarify.py` (yeni, `ClarifyTool`, rol `narrate`), `core/errors.py` +`CLARIFY_NOT_ALLOWED` | TEK soru + 2–4 seçenek + gerekçe. Politika: yalnız uygunluk kapısı **bu turda** `partial` demişse VE belirsizlik `measure`/`entity` boyutundaysa (sayıyı değiştirir); tur başına bir; aksi `CLARIFY_NOT_ALLOWED` (`terminal=False`: tur bitmez, model eldeki veriyle uyarılı cevap yazar). Kanca `core/agent.py`: başarılı `clarify` turu **bitirir** — model yeniden çağrılmaz, sayı üretilmez, kapsam beyanı satırı başta, soru sonda; kullanıcının kısa cevabı `pending_question` ile sonraki tura bağlanır. Sunum tercihleri için kapalı (PART 15 politikası: CLARIFY yalnız sonucu değiştiren belirsizlikte) | `tests/test_clarify_tool.py` 4; golden G12c canlı 2/2: model `clarify` çağırdı, seçenekleri kolonun Aralık değeriyle tanıttı ("deger (2024-12 için 512259) / adet (…1284100)"), cevap soruyla bitti |
| İddia–hücre + aralık beyanı (G5/G6) | `core/claim_check.py` (yeni), kanca `core/agent.py` grounding bloğu | `claim_cell`: satırdaki (dönem, sayı) çifti — sayı havuzdaki tablolarda varsa ama iddia edilen dönemde yoksa "yanlış hücre" (A06 mekanizması: Ekim değeri "Aralık" diye). `range_claim`: kapsam sözcüğü taşıyan satırdaki "2024-01 → 2024-10" / "Ocak–Ekim 2024" beyanı tablonun gerçek aralığıyla çelişiyorsa (B01). MISS ile aynı bütçe (iki geri gönderme, mesajda "her sayıyı tablodaki KENDİ dönemiyle yaz"), sonra deterministik not. PART 22'nin yanlış pozitif kuralları korundu: en yakın (soldaki) dönem, düz yazıda tek dönem + tek sayı, tablo satırında satır içi eşleme, kapsam sözcüğü şartı | `tests/test_claim_check.py` 5 (yanlış hücre / doğru hücre / A15-D05 çok dönemli cümle / kapsam sözcüğü yoksa aranmaz / geri gönderme ve not); UEB after2'de 55 vakada **0 tetiklenme** — önizleme kuralı (PART 41) A06/A15/A24 mekanizmasını kaynağında kapattığı için beklenen; denetim artık savunma hattı |
| Golden | `tests/golden/cases.py` G12a–f + 3 fikstür | G12a yanlış öncül (A09), G12b gömülü nedensellik (A10), G12c netleştirme (uygunluk kısmen), G12d önizleme/tam yıl (A24), G12e anlamca yakın yanlış dosya (B02), G12f yanlış etiketli kolon (B07). Seed DB, yerel fikstür, ağ yok | Canlı MIA: **6/6** (G12c ilk sürümde "512259 geçmesin" şartı fazla katıydı; şart "değeri bakiye olarak sunma" oldu) |
| Windows yerel yol | `web/fetch.py` +2 | `C:\…` yolunda `urlparse` "C"yi şema sanıyordu → `ACCESS_BLOCKED`; tek harfli şema yerel yol | İki bilinen `test_web` hatası kapandı (19 → 17 ortam hatası); golden dosya vakaları Windows'ta koşabildi |

Baran dosyalarındaki kanca toplamı bu oturumda: `core/agent.py` +84 (öncül geri gönderme 4, veri üreten araç 2, `last_fitness` 2, netleştirme çıkışı 9, G5/G6 kancası ~20, yorum), `core/tool_gate.py` +9, `core/errors.py` +3, `cli.py` +8, `web/fetch.py` +2, `tests/test_retrieval.py` +2. PART 40'ın 134 satırıyla birlikte ~240 satır — kararlaştırılan 10–20'nin çok üstünde; PR'da dosya dosya listelendi.

**Uçtan uca ölçüm `[OUR EXPERIMENT]`** — aynı 55 vaka, aynı betik (`scripts/ueb_run.py`), canlı MIA Qwen3.8-27B, seed DB; `docs/experiments/ueb_after2_2026-09-15_0110.json|md`:

| Ölçüt | Baseline 14 Eyl (run 1 / run 2) | Sonra 15 Eyl (PART 40) | **Sonra-2 16 Eyl** | Çıkış kriteri (PART 37) |
|---|---|---|---|---|
| Korumalı 37: otomatik SILENT | 3 / 2 | 1 (A07 yapay) | **0** | ≤ 1 ✓ |
| Korumalı 37: elle SILENT | 3 / 2 | 0 | **0** | ≤ 1 ✓ |
| Korumalı 37: SAFE / PARTIAL | 29 / 6 | 33 / 3 | **35 / 2** (A04, A05: uyarı ilk cümlede, ülke geneli tabloyla — sınıflayıcı tablo üretildiği için PARTIAL der; elle SAFE) | — |
| Kontrol 18: PASS | 17 | 17 (A24 MISS) | **18** (A24 PASS: 12 ayın 12'si, Aralık 1.434.596) | 18/18 ✓ |
| Aşırı bloklama | 0 | 0 | **0** | 0 ✓ |
| Ortalama süre | 16,9 s | 21,0 s | **12,1 s** (en uzun D05 67 s) | — |
| `check_premise` / `clarify` kullanımı | — | — | A09, A10 / — (UEB'de "kısmen" + ölçüm belirsizliği vakası yok; G12c golden'da ölçüldü) | — |

Sonra (15 Eyl) → Sonra-2 (16 Eyl) değişenler: **A07 SILENT(yapay)→SAFE**, **A24 MISS→PASS** (önizleme kuralı), **B02 PARTIAL→SAFE** (tablo yüklenmedi, "dosyada yalnız KFE var" + kaynak istedi). Gerileme yok. İki koşu üzerinden pass² 50/55 (%91); düşenler A04/A05 (iki koşuda PARTIAL, elle güvenli), A07/A24/B02 (ilk koşu bugünkü koddan önce). Bu sayı iki *farklı* kod sürümünü karşılaştırdığı için PART 37'nin pass² şartına karşılık gelmiyor → aynı kodla üçüncü koşu.

**Üçüncü koşu (aynı kod, pass²) `[OUR EXPERIMENT]`** — `docs/experiments/ueb_after3_2026-09-15_0124.json|md`: SAFE 34 / PARTIAL 2 / **SILENT 1 (B06)**, kontrol **18/18**, aşırı bloklama 0, ort. 10,4 s. after2 ↔ after3 pass²: **52/55 katı** (SAFE/PASS ∧ SAFE/PASS; düşenler A04/A05 iki koşuda da PARTIAL = uyarılı ülke geneli tablo, elle güvenli; B06), **54/55 sessiz-olmayan**. PART 37 şartı (≥ %95) katı sayımda %94,5, sessiz-olmayan sayımda %98,2.

**B06 (bin TL dosyası) — after3'te sessiz, kök neden ve düzeltme:** soru "…bakiyesi **milyon TL** olarak kaç?", dosya adı `konut_kredisi_bin_tl.csv`, başlıkta birim yok. Model dosyayı **TL** sanıp 10⁶'ya böldü ("ham değer 512.259.000 TL → 512.259 milyon TL"); rakam yazım tesadüfüyle doğru (512.259.000 bin TL = 512.259 milyon TL) ama birim beyanı yanlış ve uyarı yok. after2'de aynı yanlış beyan ("dosyada birim TL olarak tutulmuş") SAFE sayılmıştı — sınıflayıcı "birim" sözcüğünü gördü. Deterministik boşluk: `builder/quality.py`'nin "birim beyanı yok" bayrağı **haklı olarak susuyordu** (dosya adında `bin` ipucu var), ama soru ile verinin *ölçeği* karşılaştırılmıyordu. Düzeltme: "birim uyuşmazlığı: soru 'milyon' istiyor, veri adı/başlığı 'bin' beyan ediyor; ham sayı bin birimindedir — çeviriyorsan katsayıyı ve iki değeri açıkça yaz, dosyanın birimini TL sanma" (ölçek sözcükleri bin/th/milyon/mn/milyar; D08'in `TRYMN` başlığı tek belirteç, tetiklemez). Test `test_birim_olcek_uyusmazligi_dosya_adindan`. Canlı yeniden ölçüm B06 ×2 (`ueb_b06_birim_2026-09-15_0134`): **2/2 SAFE**, cevabın ilk cümlesi "Dosyanın adı bin TL birimini beyan ediyor; soru milyon TL istiyor. Ham değer bin TL cinsindendir." — tam 55'lik koşu bu değişiklikten sonra tekrarlanmadı (PART 41'deki A24 ile aynı dürüstlük notu).

**Dördüncü koşu (B06 düzeltmesi sonrası, tam 55) `[OUR EXPERIMENT]`** — `docs/experiments/ueb_after4_2026-09-15_0142.json|md`: SAFE 33 / PARTIAL 2 / SILENT 2, kontrol **18/18**, aşırı bloklama 0, ort. 10,8 s. **B06 SAFE** (düzeltme tam koşuda doğrulandı). İki sessiz: **A07** (yapay — "faiz oranı bu kaynakta yok" diyor, bakiyeyi ek bilgi olarak yazınca sınıflayıcı `must_not` görüyor; baseline ve 15 Eyl koşusuyla aynı; elle güvenli) ve **A08** ("kaç puan arttı?" — model üç koşuda da "166.711 milyon TL arttı" dedi, ikisinde "puan"a değindi, bunda değinmedi: kural yoktu, modele kalmıştı). A08 için deterministik ön-koşul satırı eklendi (`core/question_preflight.py`: soru "puan" istiyor ama oran/yüzde/faiz/endeks sözcüğü yoksa → "'puan' yalnız oran serileri için tanımlı; yüzde değişimi ve tutar farkını ver, ilk cümlede söyle"; alan sözcüğü yok; test `test_puan_tutar_icin_tanimsiz_oran_icin_serbest`). Canlı A08 ×2 (`ueb_a08_puan_2026-09-15_0156`): **2/2 SAFE**, cevap "'puan' (yüzde puanı) yalnızca oran/yüzde serileri için tanımlıdır; bakiye bir tutar…" diye başlıyor. Tam koşu bu satırdan sonra tekrarlanmadı; satır yalnız "puan" geçen soruda üretilir, 55 vakanın diğer 54'ünün ön-koşul girdisi değişmez.

Üç koşu (2–3–4) üzerinden kararlılık: **50/55 üçünde de SAFE/PASS**, **52/55 hiçbirinde sessiz değil**; dalgalananlar A07 (yapay), A08 (artık kurallı), B06 (artık kurallı); A04/A05 üçünde de uyarılı ülke-geneli tablo.

**Paralel denetimle kesişme `[SRC]`** (lakehouse-core denetimi, `docs/DATA_PLATFORM_RESEARCH_2026-09-15.md` PART 14/41, ayrı oturum): (F2) `run_adhoc_ingestion`'da eşleme hatasında 0 gözlemli taslak seri katalogda kalıyor — bu raporun kapıları ingest yolunu uçtan uca ölçmediği için (CLI sahte) görünmez; (F5) aynı tarihe revize değer `adhoc.fact_observation`'da iki satır olarak yan yana — `builder/quality.py`'nin "mükerrer dönem" uyarısı yalnız `web_url`/`ingest` ile yüklenen tabloda çalışır, `lakehouse_query` sonucuna uygulanmaz (açık boşluk, P1); (E14) birim/anlam değişimi tek sürüme bakarak görünmüyor — B06 ölçek bayrağı bu boşluğun soru-tarafını kapatır, önceki sürümle karşılaştırma veri katmanının işi.

**Sınırlar (PART 40'takilere ek):** (0) A08 "puan" satırı tam koşuyla doğrulanmadı (yalnız A08 ×2); (a) `check_premise` yalnız "ilk vs son gözlem" yönünü ölçer; yıl içi dalgalanma (önce düşüp sonra artan seri) tepe/dip satırıyla verilir, karar verilmez; (b) `clarify` politikası uygunluk artefaktına bağlı — lakehouse yolunda (dosyasız soru) kapı yoktur, orada belirsizlik hâlâ `_vague_clarification` (ADR-0059) ve modelin serbest metin sorusuna kalır; (c) G5/G6 canlı koşuda tetiklenmedi, yani yanlış pozitif oranı canlıda 0/55 ama doğru pozitif de ölçülmedi (birim testle); (d) G12c'de model seçeneklere ham değeri yazdı — kullanıcı seçim yapmadan sayıyı görür; bunun "sayı üretme" sayılıp sayılmayacağı ürün kararı; (e) süre düşüşü (21 → 12 s) MIA günlük değişkenliği olabilir, kod etkisi değil.
