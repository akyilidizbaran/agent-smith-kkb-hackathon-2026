# PROJECT_MEMORY — KKB Hackathon 2026, "Lakehouse Agent Builder and Data Analytics"

> Adım adım ne yaptığımızın kaydı. Her adım tamamlanınca buraya bir bölüm eklenir: ne
> yapıldı, neden, ne ölçüldü, hangi ADR ve commit. Gerekçelerin tamamı `docs/adr/` altında;
> burası harita, oradaki kayıtlar bölge.
>
> Son güncelleme: 21 Eylül 2026 · Dal: `feature/agent-engine` · Veri bacağı:
> `feature/lakehouse-integration-r3` (`4802ba4`)

---

## 0. Değişmeyen kurallar

| Kural | Nereden |
|---|---|
| Her mimari karar `docs/adr/` altına, gerekçe ve ölçümle. 2026-09-20 itibarıyla 98 ADR kaydı. | Takım kararı |
| Tüm commit'ler `Baran Akyıldız <147875893+akyilidizbaran@users.noreply.github.com>` kimliğiyle. | Takım kararı |
| API anahtarları asla commit edilmez; yalnız repo kökündeki `.env`'de (`MIA_API_KEY`, `EVDS_API_KEY`, ileride `TAVILY_API_KEY`). | KKB kuralı |
| Dış LLM API'si yok; yalnız KKB'nin MIA/Kloudeks'i (`kkbhackathon2026/Qwen3.8-27B`). Bulut ambarı yok. | Şartname |
| "Harness güçlü, LLM'e en az iş." Hedef demo yeterliliği değil, büyük sisteme kapasite. | Mentör |
| Agent hesap açmaz, CAPTCHA ve bot denetimi aşmaz; kimlik bilgisi yalnız gizli katmanda. | Mentör, 12 Eyl |
| Erişilemeyen kaynak açıkça söylenir ve seçenek sunulur; kaynak sabitse sessizce değiştirilmez. | Mentör, 12 Eyl |
| Tarama bütçe ve ilgi tabanlı. Tek orkestrasyon agent'ı + deterministik katmanlar; roller mantıksal. | Mentör, 12 Eyl |
| Takvim: teslim 20 Eyl, finalistler 5 Eki, final 17 Eki. | Yarışma |

## 1. Ekip ve dallar

- **Agent katmanı** (Baran): `feature/agent-engine`, kod `agent-core/`.
- **Lakehouse** (Sena / elifsenaonsoz, Elif Güngen, Zümral Yılmaz): üç dal, `feature/lakehouse-integration-r3` üzerinde birleştirildi (76 commit, 5 yazar, Zümral'ın yazarlığı iki ebeveynli merge ile korundu).
- **V3 motoru** (Büşra Özlem Koç): paralel harness; grounding modülü ortak katmana alındı, motor yakınsaması (A4) takım kararı olarak açık.
- Sözleşme sınırı: agent `lakehouse-core`'u **import etmez** (ADR-0024). Yazma ve Gold çağrısı veri ekibinin CLI'ı üzerinden ayrı süreçte.

## 2. Adım adım kayıt

### 2.1 Temel harness (8–10 Eylül) — commit'ler `457a3e8` … `e63d063`
- Kendi harness (ADR-0001), sözleşme öncelikli tasarım (ADR-0002), semantik katalog (ADR-0003), LLM sağlayıcı soyutlaması ve reasoning kapatma (ADR-0004/0005), analiz workspace'i (ADR-0006).
- Golden set: metni değil **tabloyu** denetler (ADR-0007), kararlılık tekrarla ölçülür (ADR-0008).
- Guard'lar ölçülerek eklendi: değer keşfi zorunlu (ADR-0009), kapsam kontrolü ve cevap guard'ı (ADR-0010), prompt kuralı eklemenin sınırı (ADR-0011), DomainProfile ile jeneriklik (ADR-0012), bağlam ön-yükleme kararı (ADR-0013), aday budama (ADR-0014), embedding/reranker erteleme (ADR-0015), add_column yapısal parametreler (ADR-0016), dönem filtresi zorunluluğu (ADR-0017), dönem anahtarı uyumu (ADR-0018), araç çıktısı boyut sınırı (ADR-0019), adaptör sertleştirme ve TLS (ADR-0020).
- MIA bağlantısı: golden 7/7 kararlı, 4–12 s (`e63d063`). Mentör kararları: MIA / Search / Retrieval üç ayrı sağlayıcı katmanı (ADR-0021); OCR ve Tavily kararı (ADR-0022/0023).

### 2.2 Silver adaptörü ve veri dallarının incelenmesi (11 Eylül) — `97d594c` … `7d785a9`
- Agent, veri ekibinin `meta.series` + `silver.fact_observation` şemasında çalışır (ADR-0024); golden iki şemada da 7/7.
- Yapılandırılmış hata zarfı `ToolError` ve döngü kilidi (ADR-0025): hata sayılabilir ve "düzelt-dene" ile "bu yoldan sonuç çıkmaz" ayrılabilir.
- Kataloglu seri ≠ sorgulanabilir seri (ADR-0026): 1.620 serinin yalnız gözlemi olanı modele gösterilir; olmayanı "var ama yüklenmemiş" diye ayrı sebeple reddedilir.
- Veri ekibine iki tur istek listesi (`docs/DATA_TEAM_REQUESTS*.md`), üçüncü tur inceleme (`docs/VERI_DALLARI_INCELEMESI_R3.md`).

### 2.3 Motor karşılaştırması, Büşra'nın V3'ü (11 Eylül) — `5ec2549` … `9de54cd`
- Protokol: 18 vaka × 2 şema × 3 tekrar, durum tabanlı kontrol. `--repeat 3` karar düzeyinde değil (aynı kod 0/3 ↔ 3/3 verebiliyor).
- Üç kök neden kapatıldı: Silver'da erişim kalıbı (`'{id}' bir tablo adı DEĞİL, SQL'de şöyle eriş: …`), döngü kırılması (`DUPLICATE_LIMIT=2`), DuckDB bağlantısında sorgu başına `cursor()` (800 paralel sorguda 2 istisna ölçülmüştü).
- Anlatı doğrulama (grounding) ortak katmana taşındı ve döngüye takıldı (ADR-0027): cevaptaki her sayı araç çıktısında olmalı; bir kez yeniden üretim, sonra tablo + uyarı.
- Sonuç: Silver 17/18 (takım) vs 16/18 (V3), seed 17/18 vs 17/18, SQL_FAILED 18 → 0, grounding 48/48. V3'ün tur avantajı ön-yüklemeden (gerçek katalogda 44.157 token; ADR-0026 ile 522). Öneri: modüller ortak katmana, tek harness (`docs/MOTOR_KARSILASTIRMA_YANIT.md`).

### 2.4 Veri bacağı r3 (11–12 Eylül, `feature/lakehouse-integration-r3`)
- `95187d8` Sena'nın devir teslimi (`ca86f16`) + Zümral'ın dalı (`6e90bd1`) iki ebeveynli merge.
- `e147f46` Bronze ile Silver arasındaki üretim adımı: `python -m lakehouse silver`; katalog güdümlü Silver adaptörü (seri başına izin listeleri gitti), deterministik `ORDER BY`.
- `c333fec` BDDK FinTürk birimi kanıtlandı: **Bin TL** (81 il toplamı ulusal stokla %0,0008 içinde); 81 il Silver'a girebiliyor.
- `32914d2` EVDS resmî ucu ilk kez canlı: tarih alanı fixture'ların tersiydi, sessizce yanlış hafta üretiyordu → UNIXTIME'a bağlandı. BDDK aylık `1534?Toplam?Toplam` adres hatası düzeltildi.
- `e8ee31c` TÜFE için canlı anahtarlı yakalama.
- `4802ba4` Gold materyalizasyonu (B3, aşağıda).
- Uçtan uca kanıt: RAW → Bronze → Silver → agent cevap verdi. Testler 1015 → 1050 → 1083.
- Veri ekibine raporlanan açık işler: toplu ingest provenance (`meta.run`=0), 1.534 `unknown` seri kararı, EVDS çeyreklik biçimi, 95 artifact çatışması, TP.FG.J0 terfi kapısı 4. adım.

### 2.5 Yol haritası (12 Eylül) — `4eafd23`
`docs/YOL_HARITASI.md`: A (sınır ve kural) → B (Architect ve Gold) → C (görünür güven) → D (kapasite ve kararlılık) → E (kapanış). Karar: "harness güçlü", tek agent iki rol, Gold tabloları B3'te tek paket.

### 2.6 Faz A — sınır ve kural (12 Eylül)
- **A1** `699a4a6` Erişim politikası ve geri çekilme sözleşmesi (ADR-0028): `classify_access` (robots → ulaşılamaz → 404 → 429 → 401 → giriş yönlendirmesi → 403 bot/hesap → 2xx captcha/bot/paywall → ok), kimlik bilgisi yalnız ortam değişkeninden aranır ve **değeri hiç okunmaz**, kaynak sabitleme tespiti, `decide` (devam / kullanıcıya sor / alternatif dene, açıkça), `render_for_model`. Üç yeni hata kodu, tekrar denenmez. 32 test.
- **A2+A3** `c950813` Sınır doğrulayıcı tek modülde (ADR-0029): şema → SQL guard → referans (`validate_refs`) → politika (`check_policy`) → çalıştır. Roller `retrieve | execute | validate | narrate` araçta ve izde; Planner LLM'in kendisi, ayrı agent yok.
- **A4** takım kararı, açık.

### 2.7 Faz B — Architect ve Gold (12 Eylül)
- **B1** `e4afdca` LLM'siz profilci + doğrulayıcı (ADR-0030): tarih/değer/entity kolonu, ayraçlar, frekans, ölçüm tipi kanıt ve güvenle önerilir; belirsiz tarih biçiminde tahmin yok. Doğrulayıcı yayınlama dilbilgisinin birebir kopyasıyla 7 kontrol. 13 test.
- **B2** `0606ba2`, `bdbb755` `ingest_from_url`: erişim → danışma okuması → profil → öneri → doğrulama → belirsizse sor, yazma → okuyucuyu kapat → veri ekibinin CLI'ı taslak yazar → yeniden aç → belge kartı. DuckDB tek yazar: süreç çapında okuyucu kaydı `register_reader/release_connections`. Katalog kaydı deterministik (model adı ikinci koşuda değişince veri ekibinin sözleşmesi doğru olarak reddetmişti). Taslak seri Analist'e `adhoc` ilişkisinden görünür, notu TASLAK. Golden **G8** 3/3.
- **B3** `4802ba4` (veri) + `e9661fe` (agent), ADR-0031: `catalog/gold/*.yml` metrik kataloğu; `python -m lakehouse gold` kataloglanmış fonksiyon çağrılarını `gold.<metric>` tabloları olarak kurar, red `meta.gold_build` defterine yazılır ve bayat tablo düşer, her satırda kurulum kimliği ve Silver parmak izi; `gold-run` tek çağrı salt okunur JSON. Agent'ta `GoldCapable`, `gold_align / gold_decompose / gold_join`, `GOLD_REFUSED` tekrar denenmez, `gold.*` tabloları defterden dataset. Golden **G9** 3/3 (hazır tabloyu SQL ile sorgulamak da Gold'dur; `tool_path_checks` eklendi). Demo DB'de 3 metrik: 22 çeyrek, 66 ay birleşim, 67 ay faiz; Q4 2025 = 678.970 milyon TL.

### 2.8 Faz C — görünür güven (12 Eylül)
- **C1** `6617a18` Grafik (ADR-0032): model ne çizileceğini söyler, inşacı kuralı uygular (stok için y=0, birim ve dönem başlıkta, uyarılı gözlem halkalı, çift eksen ve log yalnız istenirse, ay sonu tarihleri ay kutusuna, noktalı alan adları güvenli), bağımsız denetçi 9 kural, geçmezse dosya yok; PNG `vl-convert` ile tarayıcısız 0,36 s. Harita aracı hazır, `assets/geo/tr_provinces.geojson` bekliyor. Golden **G10** 3/3 (iğne "grafi": Türkçe ek k→ğ). G3: 12 ya da 13 satır (LAG için Aralık tabanı meşru).
- **C2** `fe24c49` Kanıt paneli (ADR-0033): sayı → hücre → SQL → Silver/adhoc satırı → artifact → Bronze → RAW → URL + fetched_at + HTTP. "Tam" ölçülebilir; eksikse halka adı. Gold tabloları katkıda bulunan gözlemlere çözülür. CLI `[kanıt]` özeti ve `--evidence`. Golden koşucusu `KANIT ZİNCİRİ n/m tam` basar; gerçek DB'de G1/G8/G9/G10 4/4 tam.
- **C3** `e1b433f` Web (ADR-0034): `web_url` bütçeli (sayfa/derinlik/süre), robots'a saygılı, özel adres yok, sha256 + zaman; liste ve yükleme modu; "soruda geçen yıl sayfada GEÇMİYOR" denetimi; erişilemezse sözleşme zarfı. Tablolar metin olarak çıkarılır, sayıya profilci dilbilgisiyle çevrilir (pandas tahmini TCMB'nin 31.51'ini 3151 yapıyordu). `web_search` yalnız `TAVILY_API_KEY` varsa. Golden **G11a/b/c** (var / yok / erişilemez, yerel fikstür) 3/3, 3/3, 3/3. Gerçek: TCMB 260×3 tablo doğru; BDDK eski adres 404; TÜİK JS kabuğu.
- `e95118b` golden fikstür kökü ayarla aynı, `incoming/` gitignore'da.

### 2.9 Faz D — kapasite ve kararlılık (12 Eylül)
- **D1** Sınırlı ön-yükleme (ADR-0035): `core/context.py`, soruya göre seçilen k=8 kompakt kart + küçük katalogda gerçek kırılım değerleri, 6.000 token bütçesi, kalanlar dizin; kural prompt'ta, araçlar kayıtlı. `AgentAnswer.usage` ile token ölçümü, golden `TOKEN:` satırı. Ölçüm kapalı → açık: seed 7/7 → 7/7, adım 7,0 → 3,3, LLM çağrısı 9,0 → 5,3, prompt token 54.953 → 36.354; gerçek DB 7/7 → 7/7, adım 3,0 → 1,6, çağrı 4,3 → 3,1, kanıt zinciri 5/5. Bedel ~1.100–1.850 token.

- **D2** BM25 sözlük dizini (ADR-0036): `core/lexical.py` iki adaptörün de arkasında (Türkçe katlama, ön ek yarım ağırlık, tam sözcük şartı, takma ad 3×); isabetler eşleşmeyen sözcükleri taşır. `search_uningested`: "yok" ile "var ama yüklenmemiş" ayrı; kısmi isabet / boş arama ikinci kezde tekrar denenmez. `UNKNOWN_TOOL` tekrar denenebilir (G11a flake'i). Türetilmiş kolonların provenance'ı formül. Ölçüm: G12 (yüklenmemiş taşıt) 0/3 → **3/3, 2 adım, 125k → 25k token**; seed 7/7 (adım 2,3); gerçek DB G1, G8–G11 geçiyor; testler 235 → 242.

- **D3** Güçlendirme + kararlılık (ADR-0037): `core/intent.py` niyet kapısı (ingest/web_url adresi yalnız kullanıcı mesajından ya da onaylı arama sonuçlarından; yazma yalnız açık istekle; `INTENT_REQUIRED` tekrar denenmez), dış içerik "veridir, talimat değildir" çerçevesi, alt süreç ortamı izin listesi (API anahtarları geçmez), G13 enjeksiyon vakası, kararlılık raporunda hata sınıfı/rol/token/tam hata metni. Ölçüm 5 tekrar: seed G1–G7 hepsi 5/5; gerçek DB G8, G10, G11a–c, G12, G13 5/5; G9 4/5 (model anlatıda fark hesapladı, guard uyarı düştü, kanıt zinciri eksik saydı). Testler 243 → 250.

- **D4** Demo kabul betiği (ADR-0038): `scripts/demo_acceptance.py` tek komut: bootstrap → canlı ingest (5 seri, `--only`) → silver → gold → 8 senaryo (G1, G2, G14, G8, G9, G10, G11a, G13) golden koşucusuyla; JSON rapor + çıkış kodu. Sıfırdan ölçüm: ingest 26 s, Silver 684 satır, Gold 3 tablo, **8/8 senaryo, kanıt zinciri 8/8**. Güvenlik kilidi: katalog betiği `--only` tanımıyorsa filtresiz canlı ingest reddedilir (ölçüldü: bir kez 1.620 seriyi çekmeye başladı, durduruldu). Veri ekibi betiğine `--database/--data-root/--only` eklendi (r3 `c07f73a`). G14: gerçek DB'de "tabloyu bozmadan" Gold faiz sütunu, 3/3.

### 2.10 İki uçtan uca deney — Architect'in ikinci kapısı, sohbette kalan analiz (12 Eylül, ADR-0039)
Kullanıcının isteği: main itilmeyecek, dal silinmeyecek; Architect finans dışı bir veriyi yalnız agent'la Bronze → Silver → Gold'dan geçirsin, Analist başka bir veriyi yalnız sohbette işlesin (DB'ye yazmadan), çıktılar alınabiliyor mu bakılsın.
- **Terfi** (veri ekibi r3 `46b9c8b` + agent `promote_draft`): taslak → aktif yalnız kullanıcı "onaylıyorum / kataloğa al" deyince ve seri anahtarı mesajda geçince; `semantic_source=manual`, güven `derived` kalır; satırlar adhoc → Silver, provenance korunur; Silver yeniden kurulumu terfi edilmişleri her yolda ekler.
- **Beyan edilen anlam**: `ingest_from_url` `unit/measure_type/default_agg/frequency`; kullanıcı metninde geçmeyen beyan yok sayılır ve sorulur (ölçüldü: model `°C`/`stock` uydurdu).
- **Gold rızası + `GOLD_REQUIRED`**: `gold_*` `allow_unverified` ancak "doğrulanmamış olsa da kullan" ile; `lakehouse_query` dönem toplayan/ortalayan SQL'i `gold_*` kayıtlıyken reddeder (ölçüldü: model AVG … GROUP BY ay yazdı).
- **`workspace_query`**: aktif tablo `t`, sertleştirilmiş bellek-içi DuckDB; varsayılan bakış modu (tablo değişmez, sonuç kanıt için not edilir), `as_active_table=true` kırpma (ölçüldü: her sorgu tabloyu ezince 24 satır → 5 → 1, yanlış dönem, grafik düştü).
- **Kanıt zinciri**: sayı önceki tablo sürümünde / bakış sorgusunda olabilir; kırpılmış web tablosu ve türetilmiş kolon web zincirini bozmaz ("web — başlık" ön eki); sayfa önceki turdan hatırlanır (`workspace.web_pages`).
- **Harness**: grafik istendi ama `chart` çağrılmadıysa bir kez geri; grafik kartı çizilen satırları taşır; "önce veriyi çek" uyarısı terfi/grafik/ingest sonrası ya da tablo hazırken verilmez; nedensellik filtresi "etkisiyle / nedeniyle" (ölçüldü: sığınmacı cümlesi geçmişti); grafik başlığında 2000.0 → 2000.
- **Ölçüm** — Deney 1 (Melbourne günlük min. sıcaklık, 3.650 gün): 5 tur, taslak → onay → aktif → Gold aylık (rıza) → grafik; ayrı süreçte `meta.series active/derived/manual/°C/index/avg/daily`, adhoc 3.650 = silver 3.650, artifact HTTP 200 + RAW 67.921 bayt, Bronze parquet, `gold-run` 1985'te 12 ay (Ocak 14,22, Temmuz 6,14; 31'er gözlem); kanıt zinciri tam 13/13 · 365 gözlem → 1 artifact; 20–56 bin prompt token/tur. Deney 2 (OWID Türkiye nüfusu): 3 tur, 24 satır tablo, %33,39 (65.425.957 → 87.270.502), en hızlı 2015 (+1.978.068), çizgi grafiği 6/6; kanıt zinciri üç turda tam; DB parmak izi (sayımlar + dosya listeleri + sha256) ayrı süreçte önce/sonra **fark yok**; 44–60 bin token/tur. Testler 252 → 270. Kabul senaryoları mevcut DB'de 7/8 (G9 anlatı aritmetiği kalıntısı).

### 2.11 Analitik ailesi — aykırılık, kırılma, öncül-ardıl (12 Eylül, ADR-0040)
Kullanıcı: "anomali ve nedensellik araçlarının bulunmaması çok kötü görüntü"; yarışmanın asgari araç listesinde üçü adıyla var. Görünürlük katmanı en sona, veri ekibinin işleri gerekirse bize.
- `analytics/methods.py` (numpy + scipy, LLM yok): `detect_anomalies` (IQR / z-skoru; Spearman rho ≥ 0.8 ise dönemlik yüzde değişim tabanı), `detect_change_points` (ikili bölütleme, ceza 2·log(n)·σ², σ birinci farkların MAD'ı), `lead_lag` (gecikmeli Pearson −k..+k, iki yönlü Granger F-testi). Sentetik testler: sıçrama, trend uçları aykırı değil, adım 50'de, saf gürültüde kırılma yok, gecikme 2 ve Granger yönü.
- `tools/analytics.py`: `anomaly_detect` (`<sütun>_anomali`, `_skor`, `_degisim_yuzde`), `change_points` (`<sütun>_rejim`), `lead_lag` (tablo değişmez, kart). Sütunlar "türetilmiş:" provenance; kart tabloları kanıt paneli için not edilir; grafik `_anomali` sütununu halka ile işaretler; kart "NEDENSELLİK DEĞİLDİR" der.
- Harness: grafik kuralı genelleştirildi (`_REQUESTED_CAPABILITIES`): aykırılık/kırılma/öncülük soruldu, araç çağrılmadan cevap yazıldıysa bir kez geri. Analitik kartları veri üreten araç sayılır.
- Golden ilk koşu 0/6 ve üç kaçak: kanıt paneli kart sayılarını (k, n, r, p) tanımıyordu → kart parametreleri not edilir, satır sayısı ve işareti düşmüş sayı eşleşir, tanımlayıcı rakamı (`5690_3`) ve "0.263" doğru ayrışır; dönem ipucu "2021'den bu yana"yı "= 2021" diyordu → `>=`/`<=`/`BETWEEN`; model "aylık" soruya çeyreklik Gold tablosunu okudu → `FREQUENCY_MISMATCH` (kabadan ince üretilemez; inceden kaba serbest).
- Ölçüm (demo DB, aylık konut 66 ay): aykırı 2023-03 (+6,49 %) ve 2023-05 (+5,42 %); rejimler 2021-02→2023-02 %1,15/ay, 2023-03→08 %3,34, 2023-09→2024-09 %0,31, 2024-10→ %2,62; haftalık faiz → konut bakiyesi: gecikme +8 hafta r=−0,28, Granger p=0,003 (ters yön p=0,19). İlk ceza kalibrasyonu (3·log(n), serinin MAD'ı) gerçek seride hiç rejim bulamadı → ölçülüp değiştirildi. Testler 270 → 287. README'deki boş vaatler (anomali, nedensellik) kapandı; ARCHITECTURE "planlı" → "yazıldı". Golden G15–G17 üç koşu 0/6 → 1/6 → **9/9 kararlı** (2 / 4 / 3 adım, 47–60k token); G16'da model önce çeyreklik Gold tablosunu deniyor, guard aylık seriye çeviriyor. Kabul senaryoları 8 → 10 (G15, G17); mevcut DB'de **10/10** (G9 dâhil, kanıt zinciri 10/10 tam, 1–4 adım, 23–72k token).

### 2.12 Tavily anahtarı ve arama bütçesi (13 Eylül)
- Kullanıcı Tavily dev anahtarını verdi → yalnız kök `.env` (`TAVILY_API_KEY`, gitignore'da); `.env.example`'a boş alan. Sohbette paylaşıldığı için yarışma sonrası döndürülmeli.
- `web/search.py`: anahtar `Authorization: Bearer` başlığında (gövdede değil), `topic` ve `time_range` modele açık, **süreç başına bütçe** `WEB_SEARCH_BUDGET` (varsayılan 20; ücretsiz katman ayda 1.000 kredi, golden döngüsü bitirmesin). Kart "kalan arama bütçesi: n" yazar; bütçe dolunca erişim sözleşmesi zarfıyla "kullanıcıdan adres iste".
- Canlı doğrulama: "BDDK haftalık bülten konut kredileri toplam" → 3 sonuç, ilki bddk.org.tr/bultenhaftalik (0,87). `web_search` artık kayıtlı: gerçek DB'de 19 araç.
- Tavily `SKILL.md` okundu; CLI kurulumu (`curl | bash`), `tvly login`, Claude Code'a global skill ekleme **uygulanmadı** (REST + httpx yeterli; dış betik çalıştırma yok). Alternatif ücretsiz sağlayıcılar (Google Programmable Search 100/gün, Brave 2.000/ay) `SearchClient` sözleşmesine ikinci adaptör olarak eklenebilir; demo için Tavily yeter.

### 2.13 Görüntü ve PDF girişi (13 Eylül, ADR-0041)
Demo slaytı "Altın İşlemleri PDF'inden değer çıkarma" istiyor; ADR-0022 OCR'ı ölçmüştü, kod yoktu.
- `vision/ocr.py`: `OcrClient` (MIA Unlimited-OCR, rehber istemi + `vllm_xargs`, Bearer), `pdf_pages_to_png` (pypdfium2, 2×, en çok 5 sayfa), `ocr_document` (sayfa sayfa, ilk `<|det|>` öncesi atılır), `is_document`. `web_url` ve `ingest_from_url` PDF/PNG/JPG'yi bu yoldan alır; araç sayısı değişmedi (19).
- HTML tablo hattı genelleşti: colspan/rowspan ızgarası (`_grid_rows`), `<td>` başlık satırlarının kolon adı olması (`promote_header_rows`, çok satırlı "TL | Hacim"), "-"/"n.a." yer tutucular boş, kart tablosu bilimsel gösterim yazmaz.
- Kanıt: sayfa notu + provenance uyarısı "görüntüden OCR ile okundu, doğrulanmadı"; zincir URL + belge sha256 + zaman + OCR bilgisi; ingest'te OCR tablosu CSV olarak izinli köke, belge kopyası yanına, sha256/sayfa/model katalog açıklamasında. `VISION_MODEL` yoksa "okunamaz", uydurma yok.
- Ölçüm: `ith_au.pdf` 5,8 s, 32×14 tablo 14/14 sayısal, 2025 Ocak 9.654,00 kg; `kmp_au.pdf` 1,9 s, 13×11, "TL | Hacim/Volume (TL)" 2026 Ocak 93.824.682.381. İlk denemede tek "-" hücresi altı kolonu metin bırakmış, colspan başlıkları kaydırmıştı; ikisi de ölçülüp düzeltildi. Testler 287 → 297. Golden G18a **2/2** (26 s, 2 adım), G18b ilk 0/2 → kanıt paneli düzeltmesi (sorudaki sayı yankı, metin hücre sayı) → **2/2** (21 s). Kabul senaryoları 10 → 11 (G18a); mevcut DB'de **11/11**, kanıt zinciri 11/11. `.env.example`'a `VISION_MODEL`.

### 2.14 Veri genişliği (13 Eylül, ADR-0042) — veri ekibinin işi devralındı, `feature/lakehouse-catalog-breadth`
Demo DB'de 5 seri vardı; BDDK aylık/haftalık kataloglarında birer seri, FinTürk'te yalnız konut kolonu. Oturum yeniden başlayınca scratchpad ve /tmp silinmişti: lakehouse worktree r3'ün itilmiş ucundan yeni dalda kuruldu, demo DB sıfırdan yeniden.
- **Keşif canlı ve kanıtlı:** BDDK aylık kalem ağacı Gelişmiş sayfanın `<option>` listesinden (ilk kimlik kararlı); 19 kalem 2025-12 için tek tek çağrıldı, birim yanıtın kolon başlığından; rasyoların sütunu `KalemSutunGetir` ile `?Rasyo`. EVDS 678 veri grubu listelendi, 8 seri seçildi (kur, politika faizi, AOFM, mevduat faizi, kart harcaması, M2/M3), TÜFE küratörlü.
- **Katalog:** BDDK aylık 1 → 20, FinTürk 81 → 648 (7 sütun × 81 il, ek istek yok: aynı yanıtın kolonları), EVDS 1.537 → 1.545; toplam 2.214 seri yükleniyor (bootstrap doğrulandı, katalog testleri 54/54). Gold 3 → 6 metrik (tüketici kırılımı, takipteki kırılımı, kur+faiz).
- **Ingest betiği:** aynı FetchSpec'i paylaşan seriler bir kez çekilir (bir ilin 8 sütunu = 1 istek/dönem).
- **Demo seti** 5 → 127 seri (~43 çekim grubu). G12 "yüklenmemiş seri" vakası taşıttan Van iline taşındı (taşıt artık yüklü).
- Alınmayan: haftalık ek kalemler (konumsal kimlik), KOBİ (sütun belirsiz), üretilmiş EVDS `unknown` serileri.
- **Ölçüm (sıfırdan):** bootstrap 2 s, canlı ingest **197 s** (127/127; FinTürk 264 artifact = 12 il × 22 çeyrek), Silver 2 s **8.290 satır**, Gold 1 s **6 tablo** red 0. İki kaçak: rasyo "(%)" birimi Silver'ın incelenmiş birim tablosunda yoktu (`% → pct`); FinTürk'te bir çekimin 8 serisi Bronze'da çekimin `dataset_id`'sini taşıyor → yeni sütunlar ilin konut `dataset_id`'sini aldı. Senaryolar 10/11 → G17 düzeltmeleri (Unicode eksi, olumsuz nedensellik, p eşiği, ikinci geri gönderme) → G17 3/3, G9 3/3, G12 (Van) 2/2. Adım sayıları arttı (G1 1 → 3, G14 4 → 8): büyük katalogda model daha çok arıyor; araç kapısı sıradaki iş. Lakehouse: `% → pct` birim eşlemesi; üç test yeni katalog durumuna uyarlandı (kataloglanmayan sütun sentetik, Gold refused sayısı katalogdan türetilir); paket 1.079 test. Dal `feature/lakehouse-catalog-breadth` itildi (r3 üstüne, main değil).

### 2.15 Kademeli retrieval, yüzler, araç kapısı (13 Eylül, ADR-0043)
Kullanıcı: proje çok kataloglu sistemlere göre kurulmalı; küçükte basit, büyükte güçlü çözüm, eşikler ölçülerek. Önerilen ve onaylanan: modele giden kart sayısı sabit, aday havuzu ölçekle büyür.
- `core/retriever.py` `CatalogRetriever` + `RetrievalPolicy`: `preload_all` (≤ 60 seri), `bm25` (yüzlü), `hybrid` (≥ 5.000 ve embedder varsa; BM25 ∪ embedding → RRF → yüzler). Adaptörler ve ölçüm koşucusu aynı sınıfı kullanır. `RETRIEVAL_MODE`, `RETRIEVAL_SMALL_MAX`, `RETRIEVAL_HYBRID_MIN`, `EMBEDDING_CACHE_DIR`, `TOOL_GATE` ayarları.
- `core/facets.py`: il (81 il, ekleriyle), frekans, kaynak yüzleri; il sorulduysa başka il elenir, sorulmadıysa il serileri ulusalın arkasına; frekans aynı → ince → kaba.
- `adapters/mia_embedder.py`: MIA Qwen3-Embedding-8B (4096), 64'lük dilim, disk önbelleği (2.214 seri 36 MB). Kosinüs numpy ile (saf Python döngüsü ölçüm koşusunu bitiremedi).
- `scripts/retrieval_golden.py`: üretilmiş + 34 elle sorgu, recall@1/@8 mod başına; EVDS'nin 53.792 serisi büyük ölçek ölçümü için canlı listelendi (yüklenmedi).
- `core/tool_gate.py`: her tur soruya göre araç alt kümesi (lakehouse/workspace/gold her zaman; chart, analitik, web, Architect sinyalle); şemayı daraltır, yetkiyi değil.
- **Ölçüm:** 2.214 seride BM25 yüzsüz recall@1 0,649 / recall@8 0,864 → yüzlü **0,888 / 0,996**. Kabul 11/11; adımlar 36 → 27, prompt token ≈ 690k → ≈ 416k (G14 8 → 4 adım, G10 6 → 2, G17 4 → 2). Hibrit: 2.214 seride recall@1 0,888 → **0,940**, recall@8 0,996 → 1,000 (bedel: soru başına bir embedding çağrısı, ağ bağımlılığı → orta kademede BM25 kaldı); EVDS 3.000 örneklem (yalnız adlar): BM25 0,792/0,973 → hibrit **0,821/0,993**; eşik 5.000'de bırakıldı, 3.000–5.000 gri bölge. "3 aylık" gibi sayılı vade frekans yüzü sayılmaz (ölçülüp düzeltildi); embedding ucu düşerse BM25'e düşer. Testler 298 → 307.

### 2.16 Canlı PDF provası (13 Eylül, ADR-0041 ek)
Demo günü PDF canlı verilecek. Borsa İstanbul'un 20 PDF'i indirilip OCR hattından geçirildi (tek sayfa yatay metal tabloları, 2 sayfalık cevher, 4 sayfalık elmas, 24 sayfalık aylık rapor, düşük kaliteli JPEG tarama).
- Kapatılan kaçaklar: OCR'ın virgülü nokta okuması ("133.119.720.04" → ondalık düzeltmesi); tek noktalı sayıların belirsiz kalması (tablo düzeyinde ayraç kuralı + karışık kolon kuralı); üç satırlı başlık ve birim satırı ("2025 | TL | USD | …" → başlığa; elmas 0/10 → 9/10 sayısal); düşük kaliteli taramada sessiz yanlış sayı (satır toplamı denetimi + yapı/karışık hücre izi → "DİKKAT, sayı verme" notu; küçük görsel 2× büyütme).
- Yeni: `pages` parametresi (web_url ve ingest), belge başına 90 s zaman bütçesi, kart kalan sayfalar için `pages` ister; prompt kuralı.
- Golden G18c (2 sayfalık yatay cevher belgesi, altın/gümüş ayrımı, 2025 altın 28.088,44 kg) eklendi; ilk 0/2: model gümüş tablosunu altın diye verdi → her OCR tablosu "sayfa n: <başlık>" etiketi taşır (kart + provenance). G18a/b 2/2; G18c etiketten sonra 3/3 doğru değer (bir koşuda kanıt paneli "27.07.2026" tarihini sayı sandı → tarih yazımları maskelenir). Testler 307 → 315.

### 2.17 Arayüz D9 (13 Eylül, ADR-0044)
Claude Design kanvasında üç yön çizildi (`docs/design/`: Main, Architect, PdfView + B/C düşük çözünürlüklü alternatifler; yayın: https://claude.ai/code/artifact/c00c1637-39d0-4d9b-a960-03c9f80fd897). Yön A (editoryal, veri-önce, üç sütun) ana ekran olarak uygulandı.
- `kkb_agent/web_app.py` FastAPI: `POST /api/ask` ajan cevabını olduğu gibi JSON'a çevirir (metin, adımlar rol/araç/hata/süre, aktif tablo ilk 200 satır, grafik PNG base64 + denetçi sonucu, kanıt paneli, token, araç kapısı, kalan arama bütçesi); `GET /api/status` katalog/yüklü/Silver/Gold sayılarını canlı DB'den; `POST /api/reset`. Tek ajan, sorular kilitle sıralı. `create_app(agent_factory)` testte sahte ajan alır. Başlatma `python -m kkb_agent.serve` (`kkb_agent.web` paketi web araçlarına ait olduğu için `web.py` olmadı).
- `static/index.html`: çerçeve yok, CDN yok (yalnız Google Fonts, yoksa sistem yazı tipi). Sol veri havuzu + oturum; orta soru → cevap (kaçırılmış mini-Markdown) → tablo ve grafik yan yana → araç izi çipleri (validate kehribar, hata kırmızı) → soru kutusu; sağ kanıt zinciri: "tam/EKSİK" rozeti, cevaptaki sayılar (eşleşen yeşil), kolon → SQL, Silver gözlemi → artifact/Bronze/RAW → kaynak, belge (OCR) kehribar, kopuk halkalar ve danışılıp kullanılmayanlar.
- Ölçüldü (demo DB, 2025 konut kredisi tablo+grafik sorusu): 5 adım, 63.485 token, 31,9 s; kanıt 24/24 tam; tablo ile grafik yan yana; grounding MISS uyarısı (bir yuvarlama) izde göründü — gizlenmedi. `/api/status` 2.214 · 127 · 8.290 · 6, tasarımdaki sayılarla birebir.
- Tasarım gözden geçirmesi (arka plan ajanı) sonrası düzeltmeler: "çekim" → "çekim" (çekim = piyango), aynı run id iki ayrı ingest'te, çelişen çekim zamanları, iz sayacı 2 → 4 adım, Haz etiketi veri noktasına, PdfView "13/13 sayı kolonu"; model adı `Qwen3.8-27B` gerçek ad, değiştirilmedi.
- Sınır: tek oturum, kimlik yok, akış (SSE) yok — ajan bitince tek cevap. Testler 315 → 317.

### 2.18 Yalnız sorulana cevap (13 Eylül, ADR-0045)
Arayüzde "selam" → emoji + öneri menüsü + eski tablo. Sebep: promptta "istenmemişi yazma" kuralı yoktu ve her turda modele aktif tablo/tarihçe/katalog gidiyor, veri sorusu olmayınca model bunu "devam menüsü" yapıyor; arayüz de her cevapta workspace tablosunu çiziyordu.
- `core/small_talk.py`: dar sözlükle selam/teşekkür/onay tanınır, LLM çağrılmaz, tek cümle, tablo/kanıt yok (iz: "selamlaşma — LLM çağrılmadı"). Prompt kuralı: yalnız sorulana cevap, öneri/emoji yok. Cevap sonundaki öneri kuyruğu ("Başka bir soru istersen… Örneğin:… Ne yapmak istersin?") deterministik kırpılır; ortadaki "Örneğin…" cümleleri kalır; tümüyle öneri olan cevap boş bırakılmaz.
- Arayüz: tablo yalnız bu cevap ürettiyse/ele aldıysa gösterilir.
- Testler 317 → 325.

### 2.19 Anlatı sıcaklığı ayrıldı (13 Eylül, ADR-0046)
Aynı soruya birebir aynı cevap (her çağrı temperature 0). Araç turları 0 kaldı; cevaplayan veri geldikten sonraki turlar (anlatı, hesap kolonu) `LLM_NARRATE_TEMPERATURE` = 0,5. Golden ve kabul betiği 0'a zorlar. Kod varsayılanı 0 → birim testler deterministik. Grounding denetimi sayıları korur.
- Ölçüm (demo DB, aynı soru): temiz ajan ×3 → değerler 3/3 aynı, anlatı 3/3 farklı (T=0'da da farklı: uç nokta T=0'da bile birebir deterministik değil). Aynı oturumda tekrar → T=0,5'te bile birebir aynı (model tarihçedeki cevabını kopyalıyor) → harness tekrar sorusuna "kopyalama" notu ekler → benzerlik 1,00 → 0,49, değerler aynı. Ders: şikâyetin kaynağı sıcaklık değil tarihçeden kopyalamaydı.
- Testler 325 → 327.

### 2.20 Kanıt yolculuğu — iki gösterim denemesi (13 Eylül, ADR-0047)
Kanıt panelinde "Yolculuğu izle": aynı zincir (Cevap → Tablo·SQL → Silver → Bronze → RAW; web/OCR'da Belge halkası) iki görünümle. 2,5B: izometrik SVG + rAF, karakter "Smith" yürür, halkalar yanar, balon gerçek kanıtı yazar. 3B: three.js v0.170.0 (MIT) `static/vendor/` yerel, CDN yok; kamera döner/sürüklenir, aktif halka ışır. Sayı çipi tıklanınca yolculuk o sayıdan; kopuk halkada karakter durur (kırmızı). FastAPI `/static` mount. Karar kullanıcıda; seçilmeyen görünüm kaldırılacak.
- "Sen kimsin" sorusu: sistem promptu "Sen {domain} üzerinde çalışan bir veri analisti ajansın" ile başlar; {domain} `DomainProfile.from_catalog(lakehouse.list_datasets())` ile ajan kurulurken kataloğun kaynak adlarından deterministik türetilir ("bddk_monthly ve evds … kaynaklı veriler"), `DOMAIN_DESCRIPTION`/`DOMAIN_AUDIENCE` .env ile ezilir; lakehouse değişince bir sonraki kurulumda kendiliğinden güncellenir (ADR-0012).
- Testler 327 → 328.

### 2.21 Arayüz uçları ve dinamik alan profili (13 Eylül, ADR-0048)
Kullanıcı: tıklanan yerler bir yere gitmiyor, yolculuk penceresi X ile kapanmıyor; profil lakehouse değişince dinamik mi?
- Hata: `.modal{display:flex}` `hidden`'ı eziyordu → `.modal[hidden]{display:none}`; Esc de kapatır.
- Oturum listesi → cevaba kaydırır, iz+kanıt o cevaba döner; kartlar/rozetler → Sistem durumu penceresi; grafik → büyük görünüm. Cevap yükleri sunucuda (`/api/answers`), sayfa yenilenince sohbet geri gelir. Uç nokta denetimi curl ile: hepsi beklenen kod.
- Profil: katalog zaten dinamikti (adaptör reload), profil kurulumda bir kezdi → `profile_factory` + `refresh_profile()`; ingest/terfi başarılı olunca sistem promptu ve araç açıklamaları yeni kataloğa göre. Test: iki terfi → iki farklı alan.
- Kanıt yolculuğu sonraya (ADR-0047 deneme). Testler 328 → 330.

### 2.22 Ad: Agent Smith (13 Eylül)
Proje görünen adı "AgentSmithler" → "Agent Smith" (arayüz başlığı, FastAPI başlığı, README, tasarım dosyaları, kanvas başlığı). Repo ve dizin adları değişmedi. Sol üstte özgün SVG amblem (`static/agent-smith.svg`: ajan silueti, koyu gözlük, kulaklık; film karesi değil, telif/likeness riski yok) ve aynı dosya favicon (`/favicon.ico` 404'ü kapandı).

### 2.23 Milestone planı ve M00 kararları (13 Eylül)
`docs/MILESTONE_PLANI_2026-09-13.md` (18 milestone, 192 görev) çalışma planı oldu; milestone milestone gidilecek. M00 kararları kullanıcıdan: baseline `feature/agent-engine`; 81 il; yüklü kapsam 2016-01'den itibaren (odak 2021–2026), istenen başka bir dönem sorulursa kaynaktan çekilip cevaplanabilmeli (tarih aralığı koda gömülmez); çıktı CSV+XLSX/PNG/HTML; jüri iki profilde (Analyst/Architect) dosya yükler, Architect tam sıfırlama ve başka alan verisiyle jeneriklik sınar; tüm milestone'lar bu hatta; kota/arama/yardımcı model kısıtı yok; paylaşılan sunucu yok, 10 kullanıcı örneklemi (oturum başına workspace), demo kullanıcının bilgisayarında, internet var, PDF canlı; JS siteleri opsiyonel; harita istenirse (lisans kullanıcıdan). Mentöre M04 sorusu taslağı `docs/mentor/2026-09-13-m04-yetki-sinir-sorusu.md`.

### 2.24 M00 kapandı (13 Eylül)
Transkriptteki 18 zorunlu davranış (R01–R18, zaman damgalı) kabul vakalarına eşlendi; yeni vakalar A30 (yüklü dışı dönem), A31 (kümülatif → akım), A32/A33 (bilinen anomali/kırılma), A21a–c (Analyst reddi, Architect yayını, tam sıfırlama + başka alan). Rol sınırı ve silme kapsamı kabul metni: profil başlatmada seçilir, Analyst kayıt defterinde yazma aracı yok, silme = pasifleştirme ya da açık onaylı tam sıfırlama (kod/kurulum/sırlar hariç). Dosya: `docs/M00_GEREKSINIM_MATRISI_2026-09-13.md`. Sıradaki: M01.

### 2.25 M01 — tek ortam (13 Eylül, ADR-0049)
Ölçülen: varsayılanlar agent-core/data seed'ine bağlanıyor, `lakehouse-core` yolu yok (scratchpad worktree), Silver yoksa sessizce seed'e düşüyor. Yapılan: `lakehouse-core/` repo ağacına ağaç anlık görüntüsü olarak alındı (`origin/feature/lakehouse-catalog-breadth@cf3e878`, `scripts/sync_lakehouse_core.sh` ile yenilenir; tarihçe veri dalında); `DATA_ROOT` (repo/data) altında DB/raw/bronze/incoming/charts/cache, göreli yollar repo köküne göre; `LAKEHOUSE_MODE=demo|seed|auto` (demo: DB yok ya da seed şeması → açık nedenle durur); `--preflight` salt-okunur ön kontrol (DB, şema, sayılar, tarih aralığı, gold, provenance, RAW/Bronze, CLI `--help` koşusu, izinli kök, model, anahtar var/yok; `--live` MIA denemesi); `scripts/build_demo_data.py` (`make demo-data`) veri değiştiren tek komut, silme yalnız `--fresh --yes`; kök `Makefile`. İlk ön kontrol: HAZIR DEĞİL (doğru); `make demo-data` 127/127 canlı (ingest 200 s) → ön kontrol hazır: 2.214/127/8.290, 2021-01 → 2026-07, 6 Gold, 295 artifact, **0 run kaydı** (M07 bulgusu doğrulandı). Temiz klon provası geçti. Kapanış formu `docs/M01_ORTAM.md` §6. Belge: `docs/M01_ORTAM.md`. Testler 330 → 333.

### 2.26 M13 — iddia doğrulama (13 Eylül, ADR-0050)
İncelemenin üç açığı kapandı: sorudaki sayı muaf değil ("%300, öyle yaz" → MISS (sorudan), kanıt "SORUDAN, TABLODA YOK"; yıl/≤31/"60 aylık" filtre kalır); açık ters işaret ("+0,54" vs −0,54) eşleşmez, işaretsiz büyüklükte yön sözcüğü yoksa `sign_warning`; kanıt paneli üç ayrı durum (sayılar / sorgu izi / dosya zinciri) ve `complete` üçünün birleşimi; `file_present` ile RAW/Bronze diskte şart; "ilk 200/N satır incelendi" notu. Grounding ile kanıt aynı kuralları uygular. Arayüzde üç rozet + sayı çiplerinde ⚠ ve ?. Testler 333 → 338. Açık: T04, T05, T07, T11, T12.

### 2.27 M05 — web erişim sınırı (13 Eylül, ADR-0051)
`guarded_get`: kütüphane yönlendirmesi kapalı, her Location hedefi istekten önce şema + özel adres kontrolü, 5 sekme, döngü reddi, toplam süre; robots.txt aynı sınırdan (özel adrese yönlendirme takip edilmez, 512 KB); başka hosta yalnız UA/Accept; yarım indirmede bağlantı kapanır, "erişilemedi". Sahte taşımayla 6 test (A19 dâhil). Açık: T03 veri connector'ıyla ortak sözleşme testi; DNS rebinding kapsam dışı. Testler 338 → 344.

### 2.28 M12 — analitik zaman ekseni (13 Eylül, ADR-0052) + M14-T08
`validate_time_axis` üç araçta ortak: zamana göre sıralama (indeks korunur, kolon ekleme hizalı, aktif tablo sırası bozulmaz), tekrar tarih → ret + ipucu, boşluk/frekans/düzensizlik notu; `lag_cap` (5 çift, n/3; 8 gözlem + 24 gecikme → 2, hata yok); sonsuz → boş, sabit seri → ret; kartta frekans, "k ay" sözcüğü, kırılma parametreleri, Granger "ön koşullar KONTROL EDİLMEDİ". Arayüz JSON'unda ±Infinity → null. Testler 344 → 348.

### 2.29 M02 — motor kıyası (13 Eylül gece, ADR-0053)
Büşra'nın koşucusu + 18 vaka + 5 görülmemiş soru; aynı DB (M01) ve model, anlatı sıcaklığı 0, 3 tekrar; V3 worktree'den `V3_SRC` ile, ortak paket bu repodan. Ham pass^3 ekip 16/23, V3 17/23; üç vakada kontrol bayat (SQL'de "konut" sözcüğü arıyor, motor seri kimliğiyle sorguluyor) + U1 pivot → düzeltilince ekip 20/23, V3 18/23. Süre 8,6/10,5 s, tur 3,4/4,9, araç hatası 23/82, grounding 54/57 vs 51/57. Ekipte gerçek açık: L3-02 alt kalem toplamı; ortak açık L10-01 netleştirme. K01 değişmedi. Aktarım: ön-yükleme ve grounding alınmıştı; koşucu alındı; max_tokens=700 M15'te; alan notları aday; paralellik ertelendi.

### 2.30 M10 — dosya girişi (14 Eylül, ADR-0054)
`POST /api/upload` (tür kabul listesi, .xls/.doc/.html açık ret, 25 MB, boş dosya), oturuma özel `uploads/<oturum>/<8hex>_<güvenli-ad>`, sıfırlamada silinir; arayüzde 📎 + sürükle-bırak, soruya `Dosya: <yol>` eklenir (niyet kuralı korunur), balonda yalnız ad. openpyxl kuruldu (XLSX daha önce okunamıyordu!), çok sayfada `sheet` sorulur, `.xls` reddedilir; ingest okuyucusu HTTP'de `guarded_get`. Format matrisi `docs/M10_DOSYA_GIRISI.md`. **Canlı prova hatası:** tarih metin kalınca ORDER BY sözlük sırası → LAG yanlış (kanıt paneli yakalayamadı, sayılar tablodaydı) → `convert_dates` (yüklemede tarih tipine çevir, belirsizse sor) + compute_column metin ORDER BY reddi; ikinci prova doğru, kanıt 12/12. Testler 348 → 353.

### 2.31 M14 — dışa aktarım (14 Eylül, ADR-0055)
Her cevabın tam tablosu sunucuda (`tables[index]`); `/api/answers/{i}/table.csv` (BOM, `;`, `,`), `table.xlsx` (gerçek hücreler + notlar sayfası), `chart/{k}.png`, `report.html` (soru, cevap, uyarılar, tam tablo, gömülü grafik, üç kanıt rozeti, kaynaklar, model+commit). Arayüzde bağlantılar ve "oturum verisi / ortak veri havuzu" rozeti. Testler 353 → 356. Açık: demo bilgisayarı provası, yolculuk görünümü kararı (K10).

### 2.32 M04 — profiller ve tam sıfırlama (14 Eylül, ADR-0056)
`AGENT_PROFILE=analyst|architect`: Analyst kayıt defterinde ingest/terfi yok (yokluk, kapı değil); `POST /api/profile` yalnız `ARCHITECT_TOKEN` ile (boşsa geçiş kapalı), geçiş oturumu temizler; `POST /api/architect/reset` iki adım (hedef listesi + onay kodu → silme + `lakehouse bootstrap`), hedefler yalnız DATA_ROOT altında, kod/.env hariç. Arayüzde profil rozeti, anahtar penceresi, "Tam veri sıfırlama…" düğmesi. Canlı: anahtarsız 403; Analyst 17 araç, Architect'te ingest+terfi ile 19. Pasifleştirme veri CLI'ında yok (açık). Testler 356 → 360.

### 2.33 Gece koşusu — M07, M08, M09, M03, M11, M06, M15 (14 Eylül, ADR-0057…0061)
Kullanıcı uyurken tüm milestone'ları sırayla kapatma görevi. Kod dalı yalnız `feature/agent-engine`, main'e dokunulmadı.
- **M07 (ADR-0057):** toplu ingest artık run/artifact bağı/uyarı kaydı tutuyor (öncesi: 295 artifact, 0 run); bayat run kapatma, `--start/--end`, `--only-file`, eksik seri çıkış 1, JSON kapsam raporu. 6 test; lakehouse 1.079 → 1.085.
- **M08:** zorunlu set katalogdan 681 seri (20 aylık, 1 haftalık, 648 FinTürk = 81 il × 8, 12 anlamı tanımlı EVDS). 2016-01'den ayrı köke (`data_build_2016/`) canlı kurulum: 681/681 (104 uyarılı), ingest 1.659 s (FinTürk 3.402 istek), 36.424 gözlem, 114 run, 3.435 artifact (hepsi run'a bağlı), Gold 6 tablo 126 satır. Boşluklu seri 0; 81 il toplamı ↔ ulusal aylık konut 42 çeyrekte medyan |fark| %0,013, en çok %0,19. **Bulgu:** EVDS 1.000 gözlem sınırı günlük serileri sessizce kırptı (USD/EUR 2023-10'dan, APIFON4 2022-08'den) → toplu betikte ≤365 günlük pencere + limit-dolu yanıt kırpılma sayılıyor. **Bulgu:** BDDK aylık 1676/1688/1717 kaynakta 2018-01'den, 1746_Rasyo 2018-08'den yayınlanıyor (istek 2016'dan). **Bulgu:** run kaydı sayesinde BDDK "grid defaultValue 0" uyarısı artık Silver'a `source_warning` olarak taşınıyor (36.424 gözlemin 31.964'ü) — doğru ama gürültülü. Ayrı hazır oluş sayaçları (katalog / doğrulanmış / tanımlı / yüklü / Gold'a hazır) ön kontrol, API ve arayüzde. L3-02 alt kalem kuralı (alandan bağımsız).
- **M09 (ADR-0058):** `workspace_real_value` (endeks tipi, baz kapsamı, aylık hizalama, endeks kolonu görünür, lineage). Canlı prova hatası: yüklü TÜFE 2025=100 serisi "Genel Endeks" adıyla aranamıyordu → katalog küratörlüğü (ad, açıklama, takma ad, etiket; TP.FG.J0 2003=100 ile splice yok) + aday listesi anlamdan (yüklü INDEX serileri).
- **M03 (ADR-0060):** kaynak ipuçları (`source_words`, host→anahtar adı, kurum adları) çekirdekten `config_data/source_hints.json`'a; boş yapılandırmada motor çalışıyor. Bellek-içi finans dışı adaptörle uyum testi iki alan sızıntısı yakaladı ("bakiye" araç açıklamasında, "kredi|bakiye" selam dedektöründe) → düzeltildi. Sözleşme belgesi `docs/M03_VERI_SOZLESMESI.md`, fikstürler `agent-core/tests/fixtures/generic/`.
- **M11 (ADR-0059):** oturum tabloları `k1…k8`, `workspace_join` (anahtar belirsizse sorar, sağda yineleme reddi, eşleşmeyenler iki yönde sayılır, ad çakışması sonek, provenance kolon başına), `workspace_query` kN okur, netleştirme kuralı, bekleyen soruya kısa yanıt notu.
- **M06/M15 (ADR-0061):** `js_required` sebebi; "ekip hesabı" seçeneği yalnız anahtarı kullanan bağlayıcıda (ajan hiçbir web isteğinde anahtar göndermiyordu → eski seçenek sahte vaatti); erişim seçenekleri arayüz düğmesi. OpenAI SDK tekrarı kapalı (bizim döngüyle çarpılıyordu), yalnız geçici hatada tekrar, `LLM_TIMEOUT`/`LLM_MAX_TOKENS`/`AGENT_TIME_BUDGET_S`, model kesintisi 500 yerine açıklamalı cevap, uzunluk kesintisi notu. GitHub Actions (`tests.yml`), `make ci`, lakehouse Makefile hedefleri gerçek adlarıyla.
- **Bulgu:** M14 arayüz dışa aktarım bağlantıları önceki commit'te yazılmamıştı (API uçları vardı) → eklendi ve doğrulandı.
- Testler: ajan 360 → 377; lakehouse 1.085 (+EVDS pencere testi).

### 2.34 — Dönem kapsamı ve cevap tablosu regresyonu (18 Eylül 2026)
- **Kök neden 1:** 60 aylık `lakehouse_query` tam 60 satır üretmesine rağmen model anlatıyı doğrulamak için `workspace_query(as_active_table=false)` ile dört örnek tarih seçiyordu. `web_app.project_result_table` bu salt-okunur bakışı son sorgu sanıp UI/CSV/XLSX tablosuna geçiriyordu.
- **Düzeltme:** salt-okunur peek, soru açıkça baz/orijinal değerleri istemiyorsa aktif çalışma tablosunu değiştiremez; dışa aktarım ve ekrandaki tablo kanonik aktif tabloyu korur. Baz değer isteği için eski dar projeksiyon davranışı tutuldu.
- **Kök neden 2:** `202201–202312` kompakt ay aralığı takip çözümleyicisinde ve dönem niyetinde tanınmıyordu. Tarih kısıtı devralınan `2022-2023` aralığının arkasında kalıyor, verified-workspace fast path eski 60 satırı aynen kullanıyordu.
- **Düzeltme:** `YYYYMM–YYYYMM` aralıkları açık mevcut-tur `date_range` olarak çözümleniyor; hızlı yol güvenli biçimde devreden çıkıyor, model yeni kapsamı sorguluyor. Dönem guard'ı açık aylık aralığın dışına taşan/eksik ayları `PERIOD_GRAIN_MISMATCH` ile reddediyor. `PeriodIntent.effective_window_months` açık aralığın gerçek ay sayısını taşıyor.
- **Doğrulama:** 820 agent-core testi geçti (1 Starlette deprecation uyarısı). Canlı demo akışı yeniden başlatıldı: ilk sorgu 60 satır, ikinci `202201–202312` sorgusu 24 satır döndürdü. İlk canlı yanıt 162,7 s; ikinci 359,1 s (LLM fallback/retry nedeniyle) — kapsam doğruluğu korunuyor.

### 2.34 M16 ilk kabul koşusu bulguları ve düzeltmeler (14 Eylül gece)
İlk canlı `scripts/acceptance_m16.py` koşusu 10/14 tur (rapor `docs/experiments/acceptance_m16_2026-09-14_0118.json`, başarısızlar rapordan çıkarılmadı). Dört kusur, dördü de harness'te kapatıldı:
- **Kanıt zinciri ✗:** veri kökü `data_build_2016/` → `data/` taşınınca artifact'teki mutlak RAW yolları bayatladı. Adaptör RAW yolunu bulamazsa aynı `raw/…` kuyruğunu güncel DB kökünde arıyor (`_resolve_raw`).
- **Karşılaştırmalı grafik yok:** iki farklı birimli seri L9'a takıldı, model grafiksiz özür yazdı. Çift eksen kendiliğinden açılmaz (ADR-0034 kuralı korunur); zaman ekseninde çizgi grafikte tek kusur birim farkıysa araç her seriyi ilk döneminde 100'e çevirir, kartta ve artifact'te `rebased_to_100` yazar.
- **Uydurulmuş işlem:** finans dışı birleştirme turunda model hiç araç çağırmadan "yüklendi ve birleştirildi, 24 il" yazdı; önceki turdan tablo olduğu için veri zorunluluğu susmuştu. Yeni guard: bu turda başarılı araç yokken işlem fiili ("yüklendi, birleştirdim, hesaplandı…") ya da soruda `Dosya:`/URL varsa cevap bir kez geri gönderilir.
- **Belirsiz kısa soru netleştirilmedi (L10):** ≤2 içerik sözcüğü, dönem/sayı yok, aktif tablo yok ve katalogda ≥3 farklı adlı eşleşme varsa kullanıcı mesajına aday adlarıyla "tahmin etme, tek soruda sor" notu eklenir (alan bilgisi yok, ad sayar).
- CI agent-core işi `PIL`/`lxml` eksikliğiyle düşüyordu → `pillow`, `lxml` bağımlılığa ve kilide eklendi. Eski demo verisi `data_prev_2021demo/` olarak saklandı, `.gitignore`'da.
- **A23 RAW özeti:** gerçek veride RAW dosyasının sha256'sı artifact kimliğiyle aynı (6/6 örnek). Adaptör artık dosya baytlarını kayıtla karşılaştırıyor; değişmiş dosya zinciri yeşil göstermiyor.
- Kabul matrisi A01–A33 test eşlemesi çıkarıldı (14 tam, 19 kısmi, 0 yok); kısmi kalanlardan A23 (özet), A26 (eski cevap tablosu), A07 (PNG indirme), A27 (model kesintisi) testle kapatıldı.
- Arayüz uçtan uca betiği `scripts/ui_e2e_m16.py` (Playwright, önbellekteki Chromium, sunucu açıkken). İlk koşu 6/7: tek başarısızlık betiğin yanlış beklentisiydi (fikstürde İstanbul yok, ajan doğru "Ankara" dedi) → beklenen değer fikstürden hesaplanıyor.
- CI: agent-core işi bağımlılık düzeltmesiyle yeşil; art arda push'ta eski koşu iptal (`concurrency`). README, AGENT.md, ARCHITECTURE durum/doğrulama/sınırlar bölümleri 14 Eylül gerçeğine göre güncellendi (M17-T04).
- **İkinci kabul koşusu 11/14** (`acceptance_m16_2026-09-14_0133.json`): grafik ve birleştirme turları düzeldi. Kalan üç: (1) finans ilk turunda tek eşleşmeyen sayı "dosya zinciri"ni de ✗ yapıyordu → rozetler bağımsız; (2) ziyaret fikstüründe kırılma 2024-10 çıktı, beklenen 2025-01 → yüzde tabanında düzey sıçraması ayrı kırılma; (3) L10 not eklenmesine rağmen sormadı → netleştirme deterministik, LLM çağrılmıyor.
- **Büşra'nın dalı (14 Eyl 00:15):** bizim dalı merge etmiş; ilgi kapısı, çapraz kontrol, birim tahmini eklemiş; bize not bırakmış. İki isteği yapıldı (`FILE_IRRELEVANT`, Windows sürücü harfi); kodunu bu dala alma kararı ekipte. Merge provası: onun dalı → bizim dal çatışmasız (84 dosya, V3 motoru kökte); main ← bizim dal çatışmasız (main ata commit).
- Sır taraması (ca2bfe3): `.env` gizli değerleri ağaçta/tarihçede yok; tek eşleşmeler `.env.example`'daki değişken referansı ve test fikstüründeki sahte AKIA dizisi. Lakehouse testleri yerelde 1.086 geçti (12 dk).
- **CI lakehouse işi GitHub'da düşüyordu:** 1.086 testin 1'i (`test_an_ipv4_mapped_loopback_is_refused`): `::ffff:127.0.0.1` yerelde (Python 3.12.13) "loopback", koşucudaki 3.12'de "private" sınıflanıyor. Adres sınıflamadan önce IPv4'e açılıyor; sebep yorumlayıcıya bağlı değil. Aynı iş GitHub'da 34 dk sürdü, 40 dk sınırı bir koşuyu iptal ettirdi → 60 dk.
- **M05-T03 (ADR-0064):** ajan ile lakehouse bağlayıcısı karşılaştırıldı; ajan multicast, site-local ve `.internal`/`.localhost` adlarını geçiriyordu. Tek adres modülü (`web/addresses.py`) ve iki paketin okuduğu ortak vaka dosyası `docs/sozlesmeler/url_erisim_vakalari.json` (17 adres, 5 ad). Lakehouse tarafı 22 test, ajan tarafı 23 test.
- **Üçüncü kabul koşusu 11/14, senaryo 5/6** (`acceptance_m16_2026-09-14_0154.json`, ae7fb01): L10 (0,2 s, LLM yok), ziyaret kırılması (2025-01) ve birleştirme düzeldi. Kalan: finans 1. turda "50" eşleşmedi (bağlam kırpılmış), 3. turda faiz "17.985" binlik okundu → iki okuma; grafik turunda model chart'ı çağırmadan reddetti → tablo varken de grafik zorunluluğu. Arayüz uçtan uca ae7fb01'de 7/7.
- **Dördüncü kabul koşusu 12/14** (`acceptance_m16_2026-09-14_0205.json`, b33c03f): grafik turu chart'ı çağırdı ve geçti. Kalan iki: finans 3. turda yuvarlanmış değişim "−0,40" (−0,403) göreli %0,5'e takıldı → tolerans gösterilen hassasiyetin yarım birimi (M13-T05); birleştirme turu kontrol hatası (ajan fikstürün beklediği gibi Van yinelemesinde reddedip sordu) → kontrol düzeltildi, kayıt değiştirilmedi. Arayüz uçtan uca b33c03f'de 7/7.
- Sabah raporu: kararlar (Büşra dalı, main/freeze, ARCHITECT_TOKEN, K10, boş katalog provası, ekip eşikleri/mentör/arkadaş provası) ve açıklar `docs/M16_KABUL_RAPORU.md` ile artifact sayfasında.
- **Beşinci kabul koşusu 12/14** (`acceptance_m16_2026-09-14_0214.json`, b05cea3) — ciddi bulgu: iki uydurma sayı cevaba girdi. (1) "Ara 2025: 1.048.900 milyon TL", gerçek 678.970; tek geri göndermeden sonra notla gitti → MISS iki hak. (2) Faiz sorusunda araç çağrılmadan kafadan farklar ve tekrarlanan uydurma satırlar → araçsız turda tabloda olmayan ≥2 sayı geri gönderilir. Kanıt paneli ikisini de kırmızı gösterdi.
- **Altıncı kabul koşusu 14/14, senaryo 6/6** (`acceptance_m16_2026-09-14_0219.json`, cc793be): uydurma sayı guard'ları sonrası ilk tam koşu; arayüz uçtan uca aynı commit'te 7/7. Tek koşu kararlılık kanıtı değildir.
- **CI yeşil:** son kod commit'i cc793be'nin tam GitHub koşusu (agent-core + lakehouse-core) başarılı, 43 dk (koşu 34789368571).
- Testler ajan 377 → 418.

## 3. Bugünkü sayılar

| Ölçüm | Değer |
|---|---|
| Agent birim testi | 418 (14 Eyl gece) |
| Lakehouse testi | 1.086 + 22 ortak URL vakası (yerel 12 dk; GitHub 34 dk) |
| ADR | 64 |
| Golden vakası | 21: seed G1–G7 5/5; gerçek DB G8, G10, G11a–c, G12, G13 5/5, G14 3/3, G15–G17 3/3, G18a/b 2/2; G9 4/5. Demo kabul sıfırdan 8/8; 13 Eyl 11 senaryo 11/11 |
| M16 kabul (14 tur) | koşu 1–6: 10 → 11 → 11 → 12 → 12 → 14 (b44cc1f → cc793be); arayüz uçtan uca son kodda 7/7 |
| Araç sayısı (gerçek DB'de) | 19: lakehouse ×4, workspace ×4 (query dâhil), analitik ×3 (anomaly_detect, change_points, lead_lag), ingest, promote_draft, gold ×3, chart, web_url, web_search (Tavily anahtarı .env'de) |
| Harness guard'ları | cevap guard'ı, veri üreten araç zorunluluğu (iş yapan araç/tablo varken susar), istenen yetenek zorunluluğu (grafik, analitik), frekans uyuşmazlığı (kabadan ince yok), grounding, nedensellik filtresi, tekrar kilidi + döngü kırma, araçsız son tur, dönem filtresi, ay çözünürlüklü kapsam, GOLD_REQUIRED, niyet kapısı, beyan kapısı, adım sınırı, reasoning temizliği |

## 4. Mimari, tek bakışta

```
Kullanıcı → AnalyticsAgent (tek harness; roller: retrieve/execute/validate/narrate)
   ├─ BoundaryValidator: şema → SQL guard → referans → politika → çalıştır
   ├─ Araçlar (registry; alan profili katalogdan)
   │    lakehouse_search/describe/distinct_values/query   ← LakehouseClient sözleşmesi
   │    workspace_add_column/compute_column/show/query     ← AnalysisWorkspace (query: bakış/kırpma, DB'ye dokunmaz)
   │    anomaly_detect/change_points/lead_lag             ← analytics/methods.py (LLM yok, ADR-0040)
   │    ingest_from_url  (Architect yazma yolu, ayrı süreç CLI, yalnız adhoc+draft; beyan kapısı)
   │    promote_draft    (Architect ikinci kapı: kullanıcı onayıyla taslak → aktif + Silver)
   │    gold_align/decompose/join  (GoldCapable, gold-run salt okunur ayrı süreç)
   │    chart  (spec → lint → render), web_url / web_search (erişim sözleşmesi; PDF/görsel → vision/ocr.py)
   ├─ Guard'lar (bkz. §3) + grounding + kanıt paneli (EvidenceBuilder, cevaptan sonra)
   └─ Adaptörler: SilverLakehouse (veri ekibinin şeması, sertleştirilmiş salt okunur DuckDB),
                  DuckDBLakehouse (seed)
Veri ekibi: RAW (içerik adresli) → Bronze (parquet) → Silver (fact_observation + meta.series)
            → Gold (fonksiyonlar + kataloglanmış metrik tabloları), CLI: bootstrap/ingest/
            ingest-file/promote-draft/silver/gold/gold-run
```

## 5. Açık işler ve sıradaki adımlar

**Yol haritası (sırayla):** D5–D9 ✅ (ADR-0035–0044); arayüz `python -m kkb_agent.serve`.
1. ~~D1 sınırlı ön-yükleme~~ ✅ (ADR-0035).
2. ~~D2 BM25 dizini ve yüklenmemiş seri cevabı~~ ✅ (ADR-0036).
3. ~~D3 kararlılık + güçlendirme~~ ✅ (ADR-0037).
4. ~~D4 demo kabul betiği~~ ✅ (ADR-0038).
5. **E** main'e birleştirme. Prova yapıldı (yerel, itilmedi): agent-engine main'in üstüne merge commit; r3 **bağımsız tarihçe** (ortak ata yok) → `--allow-unrelated-histories`, yalnız README.md ve .gitignore çakışıyor (birleştirildi: README agent metni + depo haritası). Gizli bilgi taraması iki dalda temiz; `.env/.duckdb/.parquet` izlenmiyor. Silinebilir dallar: r3'e tamamen dâhil 13 lakehouse dalı; dâhil olmayan 4 dal (busra/agent-v3 → A4 kararı; lakehouse-main-ready, lakehouse-source-access, source-access-bddk-weekly → yalnız eski docs commit'leri). **Push ve dal silme kullanıcı onayı bekliyor.**

**ADR-0039 sonrası açık:** G9 anlatı aritmetiği (fark isteyen sorularda hazır fark kolonu / decompose); `web_url` liste + yükleme iki çağrı; web tablolarında birim yok ("birim belirtilmemiş" başlığı).

**Karar ve dış bağımlılık:** A4 motor yakınsaması (Büşra ile); 81 il sınır dosyası (kaynak + lisans, kullanıcı onayı); Tavily anahtarı; isteğe bağlı `build_gold` aracı (jüri dosyasını Gold'a taşıyan akış, bugün "insan onayı gerek" diye kesiliyor, doğru davranış).

**Veri ekibi paralel hattı:** toplu ingest provenance, `unknown` seriler, EVDS çeyreklik, artifact çatışmaları, TP.FG.J0 terfi, katalog güdümlü Silver adaptörünün incelenmesi.

## 6. Ölçüm komutları

```bash
# agent birim testleri
cd agent-core && uv run pytest -q

# golden, seed (varsayılan .env)
cd agent-core && uv run python scripts/run_golden.py G1_ G2_ G3_ G4_ G5_ G6_ G7_

# golden, gerçek demo DB (ingest, gold, grafik, web dâhil)
cd agent-core && LAKEHOUSE_PATH=/tmp/kkb_demo/data/lakehouse.duckdb \
  LAKEHOUSE_CORE_DIR=<lakehouse-core dizini> INGEST_ALLOWED_ROOT=/tmp/kkb_incoming \
  uv run python scripts/run_golden.py G8 G9 G10 G11 --repeat 3

# lakehouse
cd lakehouse-core && uv run pytest -q
uv run python -m lakehouse silver --database data/lakehouse.duckdb --data-root data
uv run python -m lakehouse gold   --database data/lakehouse.duckdb --data-root data
```

## 7. Ölçülerek öğrenilenler (tekrar yapmamak için)

- Küçük model prompt kuralını okuyup yine de geçiyor; işe yarayan kalıp **seçenek bırakmamak** (araç reddi, doğrulayıcı), kural eklemek değil (ADR-0010/0011).
- Golden iğneleri Türkçe çekime dikkat: "grafik" ≠ "grafiği", "grafi" kullan.
- Bir vaka için tek doğru yol dayatma: hazır Gold tablosunu sorgulamak da Gold'dur (`tool_path_checks`); LAG için Aralık taban satırı 13. satır olarak meşru.
- Vega alan adında `.` iç içe erişimdir; DuckDB tek yazar kabul eder ve dosya kilidi son okuyucu kapanana kadar kalır; pandas `thousands="."` tahmini yüz kat hata üretir; sahte oturumla geçen test canlı yolu açmaz (`requests` yoktu).
- Model dosya yolunu ve taranan sayfaları cevaba gömüyor; bunlar kanıt paneline ve CLI satırına, cevaba değil.
- Kullanıcı yanlış öncül verirse (stok seriyi "birikimli" sanmak) araç reddi cevaba yansımalı; model düzeltti.
- Model beyan edilmemiş semantiği (birim, ölçüm tipi) uydurur; beyan **kullanıcı metninde** aranır, araç parametresine güvenilmez (ADR-0039).
- Sohbet-içi SQL aracı sonucu tabloyu ezerse model bir sonraki turda küçülmüş tabloyla yanlış dönem için cevap verir; varsayılan bakış modu olmalı.
- Kanıt panelinde `sources` listesi "web — başlık" biçiminde; `"web" in sources` liste üyeliği sessizce yanlış. DuckDB aynı dosyaya aynı süreçte farklı yapılandırmayla ikinci bağlantı açtırmaz; doğrulama ayrı süreçte.
- Retrieval'da il/frekans sözcükleri puan değil eleme olmalı (BM25 tek başına "konut kredisi"de 81 ili öne alıyordu); sayıyla gelen "3 aylık" vade, frekans değil. Kosinüs benzerliğini saf Python döngüsüyle yazma (2.214×4096 sorgu başına saniyeler), numpy matrisle.
- Model grafik sonrası tabloyu "doğrulamak" için sorgu üstüne sorgu atar; kart çizilen satırları taşıyıp "araç çağırmayı bırak" demeli; grafik istenip çizilmediyse harness geri göndermeli.
- Trendli seride aykırılık düzeyde değil değişimde aranır (uçlar sahte aykırı); kırılma cezası serinin kendi MAD'ıyla değil birinci farkların MAD'ıyla ölçeklenmeli (gerçek seride hiç rejim bulunamıyordu). Yöntemi gerçek seride ölçmeden kabul etme.

## 8. Bağımsız repo ve branch incelemesi — 13 Eylül 2026

- Kullanıcı isteği: yerel repo + arkadaşların bütün uzak branchlerini dikkatle incele, soruları hazırla; geliştirmeler daha sonra birlikte tartışılacak. Bu tur uygulama değişikliği, merge, push veya dal silme yapılmadı.
- Ayrıntılı, commit bağlantılı envanter ve bulgular: `docs/REPO_BRANCH_INCELEMESI_2026-09-13.md`. Eski ölçümler tarihsel kayıttır; aşağıdaki bilgiler güncel incelemedir.
- Origin verilen GitHub reposuyla aynı; fetch sonrası 21 uzak branch. Agent `67cd6f9`, güncel veri `feature/lakehouse-catalog-breadth@cf3e878`, V3 `479854c`, main `d81d584`. Main yalnız ilk taslak. Agent/veri tarihçeleri ayrı; birleştirme kararı alınmadı.
- **Yerel gerçek durum:** mevcut ayarlarla `build_agent()` seed `DuckDBLakehouse` açıyor, 1 dataset ve 14 araç. Varsayılan `/Users/baran/Desktop/KKB/lakehouse-core` mevcut değil; Architect/Gold araçları açılmıyor. Önceki 127 serilik demo bu varsayılan çalıştırma değildir. Kanonik DB, CLI yolu ve başlatma komutu kullanıcıyla netleştirilecek.
- **Güncel katalog sayımı:** 2.214 seri; 1.533 `unknown`/birimsiz; 679 verified, 1.535 derived. EVDS kataloğunda 152 quarterly seri. Önceki açık listelerdeki 1.534 unknown / 233 quarterly değerleri güncel sayım değildir. Semantiği tanımlı 681 seri, yüklü veya tamamı Gold'a uygun demek değildir.
- **Bağımsız doğrulama:** agent 330 test geçti; V3 snapshot 106 test geçti (agent ortamında). Lakehouse kendi kilitli ortamında 1.079 test geçti (763,29 s). Temiz geçici DB'de gerçek CLI ile CSV → draft → promotion → Silver → Gold çalıştı; 100/110/120 aylık stok Q1 için 120 üretti. Agent adaptörü üç satırı ve mevcut RAW/Bronze kanıtını okudu. GoldCLI derived veri için rıza yokken `UNVERIFIED_SEMANTICS`, rıza varken başarı döndürdü. Canlı MIA/OCR golden yeniden koşulmadı.
- **Yeniden üretilen açıklar, henüz düzeltilmedi:** sorudaki yanlış `%300` grounding/evidence kontrolünden geçebiliyor; `-0.54` tablo değeri `+0,54` anlatıyla evidence'da eşleşiyor (grounding ayrı olarak reddediyor); RAW/Bronze yolu olmayan observation `complete=True`; public URL'den private hedefe redirect sonrası host yeniden denetlenmiyor (sahte taşıma ile); 8 gözlem + max_lag=24 broadcasting hatası; sırasız/tekrarlı tarihler analitik kontrolünden geçiyor; sonsuzluk JSON serileştirmesini bozuyor.
- **Koddan doğrulanan eski açık:** toplu `run_catalog_ingestion.py` hâlâ ortak run/warning kayıt hattını atlıyor. Observability modülünün varlığı bu yolun provenance'ını garanti etmiyor.
- **Arayüz:** Playwright ile sahte agent üzerinde soru/tablo/modal kapatma/reload akışı geçti. Tek RAM oturumu, upload/export/SSE yok; çok kullanıcı gereksinimi henüz kararlaştırılmadı.
- **Sonraki adım:** rapordaki 14 kapsam/ekip/veri/kanıt/teslim sorusunu kullanıcıyla netleştir; ardından açıkları önceliklendir. V3'ün eski karşılaştırmasını bugünkü motor için güncel üstünlük kanıtı sayma; araştırma/benchmark katkılarını harness kararından ayrı koru.


## 9. Kullanıcı yanıtları ve mentör kapsamı — 13 Eylül 2026

- Kaynaklı netleştirme: `docs/KAPSAM_VE_MENTOR_NETLESTIRMESI_2026-09-13.md`; mentör metni kalıcı olarak `docs/mentor/2026-09-13-kullanici-paylasimi.txt` içinde korundu. Kullanıcının eklediği kick-off transkripti okundu; değiştirilmedi.
- **Kesin kapsam:** jenerik dış/veri analiz agent'ı; finans/krediye bağlı ürün değil. BDDK/EVDS zorunlu başlangıç veri alanı, 2021-01 → 2026-06. Architect ekipçe eklenmiş yetenek; yarışmanın zorunlu kullanıcı rolü/ekranı olarak sunulmayacak.
- **Takvim:** 20 Eylül freeze geçerli, daha erken bitirme hedefi. Ekip 14 Eylül'de motorları/branchleri inceleyip baseline ve iş bölümünü yeniden belirleyecek; güçlü parçalar taşınabilir. Motor kararı açık.
- **Çalışma tabanı:** catalog-breadth bu çalışma hattında korunabilir; takımca son kabul edilmiş dal diye ilan edilmez. Şimdilik kendi bilgisayarında demo; transkript 24:47 bunu destekler, 24:11 tekrar kurulabilirliği ister.
- **Kullanıcı tercihleri:** eksik güven/kanıt uyarıyla gösterilebilir; sayısal sonucu belirleyen eksik bilgi sorulur, diğer varsayımlar açık söylenebilir. Performans eşikleri daha sonra belirlenecek. Dosya yükleme, tablo/grafik/rapor indirme kapsam içi gereklilik.
- **Erişim:** Tavily arama sağlayıcısı. Yetkili ekip hesabı/API key önceden hazırlanabilir; agent hesap açmaz/CAPTCHA aşmaz. Credential gizli katmanda. Kaynak engeli ve nedeni görünür; dosya/alternatif önerilir, kaynak sabitlenmişse değişiklik kullanıcıya sunulur. Crawl ilgi/sayfa/süre/derinlik bütçeli; tek orchestration agent ve deterministik katmanlar mentörce destekleniyor.
- **Architect konusunda henüz KARAR DEĞİL:** kullanıcı son kullanıcının yalnız Analyst'e erişmesini önerdi ve görüş istedi. Önerimiz kullanıcı dosya/URL ile oturumda analiz yapabilsin; ortak kataloğa yayın, promotion, kalıcı Silver/Gold değişiklikleri ve credential yönetimi ekip/operator'de kalsın. Registry ve yazıcı erişimi ayrılmalı; tool_gate veya gizli düğme yetki sınırı değildir. Bu kabul edilirse mevcut sohbet promotion akışı ve ilgili ADR'ler uygulama sırasında güncellenmeli.
- **Güven önerisi:** kanıtı eksik sonuç uyarıyla sunulabilir; yanlış olduğu saptanan sayıyı yalnız uyarı ekleyerek doğrulanmış gibi sunma. Hesap, semantik güven ve kaynak zinciri ayrı gösterilmeli.
- **Jeneriklik kabul önerisi:** temiz boş katalog + finans dışı veri + aynı motor; önceki finans alias/prompt/SQL varsayımları sızmamalı. Mevcut seri/tarih/değer Silver modelinin genel işlem/ilişkisel veri için sınırları ayrıca değerlendirilmeli. Zorunlu finans çok-turlu senaryosu ve dış veri senaryosu birlikte ölçülmeli.
- **Kaynak eksiği:** yeni mentör dosyası “2. soru cevabı” başlığında bitiyor; kota/arama/yardımcı model yanıtı yok. ADR-0021'de eski özet var; güncel sayısal kota bu ekten doğrulanmış sayılmaz.
- Bu tur yalnız doküman/hafıza güncellendi; uygulama veya takım baseline kararı değiştirilmedi.

## 10. Ayrıntılı milestone planı — 13 Eylül 2026

- Kullanıcının bütün konuşulan işleri nedenleriyle milestone'lara kaydetme isteği tamamlandı: güncel operasyonel backlog `docs/MILESTONE_PLANI_2026-09-13.md`.
- Plan 18 milestone (M00–M17), benzersiz kimlikli 192 görev ve 29 birleşik kabul senaryosu içerir. Her milestone için gerekçe, teslimat, görevler, kabul ölçütleri ve riskler; ayrıca bağımlılık haritası, açık karar defteri ve kapatma kanıtı formatı vardır.
- Kesin gereksinimler, kod bulguları, öneriler ve açık kararlar ayrıldı. Analyst/Architect yetki önerisi, ortak motor seçimi ve performans eşikleri onaylanmış sayılmadı. 20 Eylül freeze korunuyor; ara tarihler öneridir, ekip taahhüdü değildir.
- Eski `docs/YOL_HARITASI.md`, ADR'ler ve test ölçümleri tarihsel kayıt olarak korunur; bu plan tamamlanmış işleri sıfırlamaz. Yeni uygulama görevleri kabul kanıtı oluşmadan tamamlandı işaretlenmeyecek.
- Sonraki adım: M00 kapsam/iş bölümü kararlarını ekipçe netleştirmek; M01 tekrar kurulabilir ortamı hazırlamak ve bağımsız doğruluk açıklarını plan doğrultusunda ele almak. Bu kayıt uygulama geliştirmesi, merge veya push yapıldığı anlamına gelmez.
- Doküman doğrulaması: milestone/görev/senaryo sayımları, görev kimliği benzersizliği ve yerel belge bağlantıları kontrol edildi. Bu tur uygulama kodu değiştirilmedi.


## 11. Milestone geri bildirimi ve kullanıcı kararları — 13 Eylül 2026

- Değerlendirme: `docs/MILESTONE_FEEDBACK_DEGERLENDIRMESI_2026-09-13.md`. Arkadaşın dört önerisi kodla karşılaştırıldı; ana planın ilgili maddeleri güncellendi.
- M04 düzeltmesi: geçici workspace ve kalıcı CLI yolları zaten ayrıdır; eksik olan kullanıcı/Architect işletim profili sınırıdır. ADR-0039 korunmalı, yeni rol kapsamıyla tamamlanmalı; kimlik sistemi otomatik gereksinim değil.
- **Kullanıcı kesinleştirdi:** normal kullanıcı ortak kataloğa yazamaz/silemez; Architect veri mimarisini değiştirir. Jüri demosunda iki akış da gösterilebilir. Salt Analyst jüri profili tek başına demo kapsamını karşılamaz.
- **Kullanıcı kesinleştirdi:** iki yeni tabloyu anahtarla birleştirme zorunlu. Mevcut workspace_query yalnız aktif `t` tablosunu kaydeder; çok kaynaklı tablo kimlikleri, join anahtarı/kardinalite ve provenance M03/M11/A09 kapsamında tamamlanmalı. Silver'ı genel ilişki deposuna dönüştürmek önerilmiyor.
- **Kullanıcı hedefi:** her türlü silme ve boş ortamdan yeniden kurulum. Öneri: pasifleştirme + ayrı Architect fiziksel veri reseti; katalog/RAW/Bronze/Silver/Gold/oturum/cache kapsanır, kod ve kurulum korunur. Kesin hedef ve işlem onayı gerekir; bu tur veri silinmedi. Kabul ayrı geçici veri kökünde yapılmalı.
- Mentörden yeni Architect onay cevabı yok; 45 görev için somut liste veya yeni kod yok. 192 alt görevi körlemesine azaltma yerine yaklaşık 35–45 sonuç paketi önerildi; zorunlu kabul vakaları korunur. Henüz paket eşlemesi veya 45 sayısı kararı yok.
- M02 revize önerisi: üç dengeli ilk tekrar, kritik/dalgalı vakalara bütçeli ek tekrar. Yakın skor eşitlik kanıtı değildir. Kesin model bütçesi ve eşikler hâlâ açık.
- Bu tur 15 ilgili offline test geçti (0,41 s); tarihsiz grup toplamı A=30/B=7 doğrulandı. Promotion check_policy eski onay + güncel “yayınlama” metninde ret üretmedi; yalnız politika çağrısı yapıldı, CLI/DB yazımı yapılmadı. Onay işlem kapsamına bağlanmalı.
- Uygulama kodu, dal ve veri değiştirilmedi; yalnız değerlendirme/plan/hafıza yazıldı.

## 12. Milestone uygulamalarının bağımsız kontrolü — 14 Eylül 2026

- Kullanıcı uyguladığı milestone'ların doğru ve eksiksiz olup olmadığını sordu. İncelenen HEAD `196dcfe`, son uygulama commit'i `cc793be`. Rapor: `docs/MILESTONE_DOGRULAMA_2026-09-14.md`. Bu tur düzeltme/merge/push yapılmadı; izlenmeyen `.claude/` dizinine dokunulmadı.
- Agent testleri 418/418 (4,07 s); hedefli lakehouse Gold/toplu ingestion/ad-hoc provenance/observability 176/176 (213,20 s). Tam lakehouse suite, canlı MIA/OCR ve Playwright bu tur yeniden koşulmadı; önceki M16 kayıtları bağımsız yeni ölçüm sayılmadı.
- Salt okunur preflight başarılı: 2.214 katalog, 681 yüklü seri, 43.830 gözlem, 6 Gold, 3.468 artifact, 117 run. Eski varsayılan seed/eksik CLI yolu problemi mevcut ortamda giderilmiş.
- Asıl 192 görevde 152 `[x]`, 27 `[~]`, 13 `[ ]`; ek EK görevleri hariç. M16 kendi kaydı 14 tam/19 kısmi kabul gösteriyor; bütün milestone'lar kapanmış sayılamaz.
- Yeniden üretilen açıklar: join float64 dönüşümü 9007199254740992/9007199254740993 kimliklerini eşleştiriyor; `001`/`1` ve boş kimlikler de örtük eşleşiyor. Join yardımcı `__k` kolonu kullanıcıda varsa sessiz siliniyor.
- Harness kontrollü modelde gerçek Aralık=110 iken 999 iddiasını iki geri gönderme sonrası yalnız uyarıyla nihai yanıta taşıyor. Onaylı/eksik kanıtı uyarıyla sunma ile bilinen yanlış sayıyı düzeltme ayrılmalı.
- Promotion politika kontrolünde geçmiş onay + güncel “yayınlama” hâlâ ret üretmiyor; bu tur gerçek CLI/promotion çağrılmadı. M04-T09 tam kabul değil.
- Reset callback'inin kullandığı bootstrap yeni geçici DB'yi 2.214 finans katalog kaydıyla kurdu; boş katalog kabulü yok. Şema-only seçenek alt katmanda mevcut ama reset/sonraki yazma yollarına taşınmalı. Reset sonrası geçici kökte eski charts/old.png kaldı; silme hataları ignore_errors ile başarı diye listelenebilir.
- Kanıt zinciri: RAW yok + Bronze var iken chain_ok=True; Bronze da sonradan silinince mevcut nesne yine True. Fiziksel halka doğrulaması ve kısmi zincir sunumu tamamlanmalı.
- Sonraki adım: rapordaki R01–R07'yi düzelt, A09/A21c gerçek uçtan uca geçici veri kökünde kapanmalı; sonra kısmi kabul senaryoları ve başka kişi kurulum provası. Asıl demo verisine bu kontrolde dokunulmadı.

## 13. İnceleme sonrası düzeltme ve kapanış planı — 14 Eylül 2026

- Kullanıcı incelemede yapılması gereken kapsamları ayrıntılı Markdown dosyası olarak istedi. `docs/MILESTONE_DUZELTME_VE_KAPANIS_PLANI_2026-09-14.md` oluşturuldu; ana milestone planının yerini almaz, kontrol raporunun uygulama ekidir.
- Yedi düzeltme paketi D01–D07, rapordaki R01–R07 ile eşleşir: kayıpsız join, yanlış sayı için güvenilir nihai çıkış, işlem kapsamlı onay, boş katalog bootstrap, eksiksiz reset, fiziksel kanıt doğrulama, yardımcı kolon çakışmalarını önleme.
- K01–K04: gerçek CLI/UI ile A09/A21c kabulü, kısmi A01–A33 senaryoları, son sürüm/başka ekip üyesi provası ve ana plan/ADR/kanıt durumlarının tutarlı kapanışı. Her pakette neden, görev, bağımlılık ve beklenen kabul sonucu kayıtlı.
- Bu tur yalnız yeni plan ve hafıza yazıldı; ana planın tamamlanma işaretleri değiştirilmedi, uygulama kodu/veri üzerinde işlem yapılmadı. Görevler kabul kanıtı oluşana kadar açık kalacak.

## 14. Düzeltme planının uygulanması — 14 Eylül 2026

- **D01/D07 (ADR-0065):** join anahtarı açık kural; `tam` varsayılan (tamsayı kayıpsız, metin olduğu gibi, zaman damgası saatiyle), tip farkı ya da gevşek kuralın sonucu değiştirmesi sorulur, boş anahtar eşleşmez, ≥2^53 float kimlik reddedilir. Yardımcı kolon kaldırıldı; `__k=preserve-me` korunur, sonek çakışması sayı sonekiyle çözülür, kural kart ve provenance'ta. M11 ve A09 testleri artık `metin_normal`'ı açık seçiyor (ankara ↔ Ankara sorulur).
- **D02 (ADR-0066):** doğrulanamayan sayı taşıyan cümle/madde/tablo satırı son çıkışta çıkarılır; anlam kalmazsa deterministik tablo özeti. Döngü kilidi, adım/süre sınırı ve araçsız turda da; araçsız eşik 1 sayı, havuza önceki tablolar ve bakışlar girdi. Her tur 999 diyen model testinde nihai metin, sohbet ve anlatı adımı 999 taşımıyor.
- Ajan testleri 418 → 432.
- **D03 (ADR-0068):** terfi onayı bekleyen işleme ve bu turun mesajına bağlandı (`core/approvals.py`); geçmiş onay + güncel 'yayınlama' artık ret; kısa 'evet' yalnız tek bekleyen işlemde; onay denemede tüketilir; Gold rızası ile yayın onayı sözcükleri ayrıldı. Ajan testleri 432 → 440.
- **D04/D05 (ADR-0069):** `meta.lakehouse_setting.series_catalog` (default|none); `bootstrap --catalog none` sonrası silver/gold/promote/ingest/yeniden açılış finans kataloğunu geri getirmiyor; toplu finans ingest betiği boş kipte duruyor. Arayüz sıfırlaması: hedefler yapılandırmadan (grafik ve önbellek dahil), kök dışı ayarda ret, onay kodu kapsam + katalog seçimine bağlı, okuyucular kapanıyor, hedef başına sonuç ve silme sonrası yokluk, bootstrap `--catalog none` ve seri 0 + kip none doğrulaması; aksi `kısmi`. Pencere kapsamı ve sonucu gösteriyor.
- **D06 (ADR-0070):** gözlem kanıtında yol metni ile canlı dosya durumu ayrı; altı halka durumu; yalnız Bronze kalması 'ham kaynak eksik'; panel kurulduktan sonra silinen dosya yeşil kalmıyor; kanıt fikstürü gerçek sha256'lı RAW'a geçti.
- Testler: ajan 440 → 448; lakehouse tam suite 1.086 → 1.111 (12 dk 08 s).
- **K01 (22/22, `docs/experiments/k01_kabul_2026-09-14_1227.json`):** gerçek web uygulaması, harness, araçlar ve lakehouse CLI geçici kökte, model yerine betik. İlk koşularda bulunan: yalnız bootstrap edilmiş DB'de Silver tablosu yoktu, ajan açılamıyordu → `run_bootstrap` boş Silver ilişkisi kurar; Gold `count` tipini güvenli toplamadığı için reddeder (tasarım), aylık başvuru `flow_periodic`. Aynı süreçte DuckDB farklı ayarlı ikinci bağlantıyı reddettiği için betik DB okumalarını ayrı süreçte yapar.
- **K02-T08/T09/T13:** uyarılı artifactin iki ingest koşusu testi (tek artifact, koşu başına uyarı, Bronze değişmez); bayat Gold tablosuna sorgu `GOLD_STALE` ile red (ADR-0071); analitik kartlar yöntem/eşik/ceza değeri/min segment ve SINIRLAMA satırı taşıyor, testle denetleniyor. Ajan testleri 450.
- **K02-T06/T10/T12:** düşük kaliteli OCR tablosu yüklenmez, OCR sayıları doğrulanmış sayılmaz (ADR-0072); Tavily HTTP hatası testleri ve süre bütçesi için deterministik sınır notu; Architect `ingest_source` ile yüklü aralık dışını kayıtlı kaynağından çeker (ADR-0073). Ajan testleri 450 → 458.
- **A30 canlı (5/5):** `scripts/k02_a30_canli.py` geçici kökte Architect oturumunda `ingest_source` ile bddk_monthly:1534_Toplam 2015-12'yi gerçek kaynaktan çekti (5,6 s; Silver'da 2015-12-31 = 143.248, run kaydı, 1 kaynak uyarısı); asıl demo DB sha256 aynı.
- **K02-T07/T11/T14 (ADR-0074):** serbest kaynakta erişim hatası artık turu bitirmiyor (önce model aynı turda alternatif kaynak deneyemiyordu), kullanılan alternatif cevapta deterministik not; kanıtta sayı yanında yazılan döneme bağlanıyor, önceki tablo eşleşmesi kaynak kimliğiyle; A28 K01 kanıtıyla kapandı. Ajan testleri 461.
- **K02-T02…T05 (ADR-0075, 22/22, `docs/experiments/k02_finans_kabul_2026-09-14_1310.json`, commit 15f8593):** M16 canlı finans araç yolu gerçek demo DB'de betikli modelle yeniden oynatıldı, beklenenler Silver'dan ayrı süreçte. Betiğin bulduğu dört ürün kusuru kapatıldı: baz yılı doğrulanmamış KFE reel dönüşümde rızasız kullanılabiliyordu; grounding araç çıktısındaki "18.388"i binlik okuyup Gold faizini MISS sayıyordu; arayüz ve rapor grafik başlığında birim ve dönem yoktu; web araması sonucu kanıtta hiç görünmüyordu (artık 'bağlam, veri değil'). İlk koşuda betik önizlemede görünmeyen sayıyı cevaba yazdı; grounding'in reddi doğruydu, betik canlı akıştaki gibi son ayı `workspace_query` ile gösterdi. Ajan testleri 461 → 471.
- **K01-T07 (15/15, `docs/experiments/k01_ui_kabul_2026-09-14_1319/`, commit 9eaf60e):** A09 ve A21 arayüzden gerçek Chromium ile; sunucu süreç içinde, `cli.OpenAICompatClient` betikli yönlendiriciye bağlandığı için profil geçişi ve sıfırlamadan sonra kurulan ajan da aynı betiği kullandı. Bulgu: boş katalogdan yeni alan kurulup seri onaylanınca durum sayacı 0 gösteriyordu (adhoc seriler topluca dışarıda sayılıyordu) → yalnız taslaklar dışarıda (ADR-0076).
- **K02-T01 kurulum provası bulgusu (ADR-0076):** temiz klonda ön kontrol 'hazır' dedi, `make serve` ham `OpenAIError: Missing credentials` ile çöktü. Sebep provada `.env` kabukta `source` edildi: `MIA_API_KEY` satırındaki boşluk ve `LLM_API_KEY=${MIA_API_KEY}` referansı kabukta kayboluyor (python-dotenv ikisini de okur). Ürün düzeltmesi: uzak modelde anahtar boşsa ön kontrol model satırı ✗, ajan kurulumu açık mesajla durur. Operasyon tarifine 'source .env yapma' notu.
- **K03-T02/T03 (14 Eyl öğleden sonra):** veri manifesti `k03_veri_manifesti_2026-09-14_1327.json`; lakehouse tam suite 1.112 geçti (12 dk 15 s). Canlı M16 kabulü 51c066d'de üç kez: 14/14, 13/14, 12/14 (tur medyanı 7,5 s, p90 13,0 s, en çok 20,5 s). A06 turu 1/3: cevabın 24 sayısının hepsi tabloda olduğu halde işaret uyarısı; kanıt paneli yön sözcüğünü sayının ilk (işaretli) geçişinde arıyordu ve işaret çevirmede yuvarlama toleransı yoktu → düzeltildi (ADR-0077, 6f12bbe, canlı cevap metniyle regresyon testi). Dosya senaryosunun birleştirme turu 2/3: model Van yinelemesi yüzünden birleştirmeyi reddedip onay istedi ama '?' yazmadı; betiğin koşulu karşılanmadı, davranış doğru. Betik koşulu sonuç lehine değiştirilmedi.
- **K03-T03…T05 tamam (14 Eyl öğleden sonra):** hedefli canlı tekrarlar 6f12bbe (finans 6/6, 5/6, 6/6; dosya 3/4, 4/4) ve 04655c7 (dosya 4/4, 3/4, 4/4). Tekrarlar ve demo bilgisayarı ekran provası beş ürün kusuru daha buldu, hepsi kapatıldı (ADR-0077 ve eki): tabloyla tutarlı 'kalan 50 ay' doğrulanmıyordu; birleştirme turunda model araç çağırmadan yanlış eşleşme iddiası yazabiliyordu (kapı); web kartındaki sağa hizalama dolgusu 'adların başında boşluk var' yanlışına yol açtı; '2026-06' yıl-ay yazımı sayı sanıldı; lakehouse_query bakış sonucu kanıt havuzuna girmiyordu. Ekran kontrolü 1512×982 ve 1280×800'de 6/6, canlı arayüz provası 7/7. Kalan canlı dalgalanma: birleştirme turunda doğru davranışta '?' eksikliği betik koşulunu düşürüyor; koşul değiştirilmedi. Kullanıcının 8765'te açık sunucusuna dokunulmadı; provalar 8766'da.
- **Kullanıcı geri bildirimi (14 Eyl akşam, ADR-0078):** arayüz denemesinde dokuz sorun bildirildi, hepsi kapatıldı. Kişi sorusunda (ekip üyesi) model 'genel bilgimden' diyerek başka birine ait uydurma biyografi yazdı → istem kuralı + deterministik kapı (bir kez geri gönderme, sürerse yayımlanmaz). Yetenek ve veri seti soruları katalog ve kayıtlı araçlardan deterministik (Gold anlatılmıyor; alan tanımı birincil kaynak adlarıyla, adlar `source_hints.json`'da). Resmi kamu alan adları (tcmb.gov.tr …) model tarafından açılabilir; TCMB kur XML'i tablo olur; belge metni 8.000 karakterlik pencereyle ve devam notuyla (önce 1.500'de kesiliyordu). Arayüz: sağda sayı listesi yok, mesaj hemen görünür ve altında 'Düşünüyor…'. Canlı denemede kullanıcının mesajları: kişi sorusu 'elimde bilgi yok'; 2 Ocak 2015 ve 1 Temmuz 2026 dolar kuru TCMB'den (model adresi kendisi açtı); 2 sayfalık PDF'in iki bölümü de özetlendi. Canlı denemede bulunan ek yanlış negatif: 'bülten no 2026/120' kimliği sayı sanılıyordu → yıl/sıra kimliği maskelendi.
- **main entegrasyonu hazırlığı (14 Eyl akşam):** arkadaşlar main'e PR #1 (Elif Güngen) ve #2 (Zümral) ile lakehouse işini birleştirdi. Bizim dal 107 commit'le tam geçmişiyle birleştirilecek (kullanıcı kararı; commit sıkıştırma yok). main ile deneme birleştirmesinde lakehouse-core/ 16 dosya add/add çatışması verdi; sebep git'in ortak atasının ilk taslak commit'i olması. Bizim lakehouse-core kopyası main geçmişindeki cf3e878 ile birebir aynı çıktı; bu tabanla üç yönlü birleştirmede 15 dosya otomatik birleşti, tek gerçek çakışma docs/sources/evds.md paragrafı (main'in güncel metni + bizim TÜFE bölümü). main iki doğrulanmış BDDK serisi ekledi (158_Toplam, 194_Toplam; katalog 2.214 → 2.216); K01 artık sayıyı katalog dosyalarından okuyor. Birleşik ağaçta K01 koşusu bugünkü yetenek cevabının bir analiz sorusunu yakaladığını gösterdi (merge kaynaklı değil, bd32404'te de) → sözcük sınırı ve analiz sözcüğü koruması (ADR-0078 eki). Büşra'nın dalına dokunulmadı; o gerekirse bizim üzerimize push atacak.
- **main entegrasyon dalı hazır (14 Eyl akşam):** `integration/agent-engine-main` = feature/agent-engine (8bf4f28) + origin/main (582ee98) birleştirmesi 51ccc17 ve bu kanıt commit'i; main'e gidecek 109 commit'imiz tam geçmişiyle. 16 lakehouse-core çatışması ortak taban cf3e878 ile çözüldü (15 otomatik, 1 doküman paragrafı elle). Birleşik ağaçta: ajan 495 geçti + 1 atlandı (yerel seed DB yok), lakehouse 1.126 geçti, K01 22/22, K01-T07 arayüz 15/15, K02 finans 22/22, ön kontrol hazır. Entegrasyon K01 koşusu bir ürün hatası buldu (yetenek cevabı analiz sorusunu yakalıyordu) ve iki sabit sayı güncellendi (katalog 2.216, etkin 1.907: main 309 EVDS serisini deprecated işaretledi). main'e birleştirme PR ile, kullanıcı onayıyla; Büşra'nın dalına dokunulmadı.
- **Architect kayıt süresi ve onay hatası (15 Eyl):** gerçek araç ve CLI ile: dosya → taslak 1,1 s, taslak → katalog + Silver 1,05 s, kaynaktan dönem çekme (canlı BDDK) 5,6–7,7 s, tam sıfırlama 0,3 s. Canlı modelle arayüzde onay iki denemede de reddediliyordu: yükleme ön eki (8 onaltılık) seri kimliğine giriyor, kullanıcı ön eksiz ad yazıyor → onay eşleşmesi ön eksiz adı da kabul ediyor (ADR-0068 eki). Düzeltmeden sonra canlı 3/3 kataloğa alındı; ekleme turu ortalama 5,7 s, onay turu 4,6 s. Ön ekin ingest anahtarına hiç girmemesi tools/ingest.py'de, PR #4 birleşince.
- **Arayüz: canlı adımlar, yazım animasyonu, kanıt akışı (15 Eyl, ADR-0079):**
  - Kullanıcı üç şey istedi: kanıt akışı düzgün görünsün, "Düşünüyor…" sırasında ne yapıldığı görünsün, cevap bir anda düşmesin.
  - Cevap token token akıtılmadı. Doğrulama kapısı taslağı geri gönderebildiği için yayımlanmamış sayı ekrana düşerdi.
  - `POST /api/ask/stream` (NDJSON) adım olaylarını, sonunda da `/api/ask` ile aynı yükü gönderir. Kanca `kkb_agent/live_steps.py`'de,
    soru süresince örnek düzeyinde kurulur; `core/agent.py`'ye dokunulmadı (PR #4).
  - Doğrulanmış metin istemcide harf harf açılır; tam metin DOM'da kalır, kabul betiklerinin `.busy` beklemesi değişmedi.
  - Sağ panel halka halka: cevap → tablo → sorgu → Silver → Bronze → RAW. Aynı SQL tek sorgu; SQL ve notlar kapalı kutuda.
  - Canlı denemede (qwen3.8-27B, iki serili soru, 24,5 s) model turları 3,1–3,6 s, katalog ve sorgu araçları ≤0,3 s sürdü:
    bekleme süresi modelde geçiyor.
  - İlk sürümde kanıt halkaları yolculuk penceresinin `.stage` stiliyle çakışıyordu (440 px beyaz kutu), `hop` adına geçti.
  - Ajan testleri 504. K01-T07 arayüz kabulü yeni akış ucu ve yazım animasyonuyla 15/15 (`docs/experiments/k01_ui_kabul_2026-09-15_1533/`).
  - Canlı sunucuda başsız Chromium: yazım ortasında 358 harfin 295'i saydam kuyruktaydı, tamamı DOM'daydı; yazım 1,8 s sürdü.
  - Görünmeyen sekmede kare çizilmediği için animasyon atlanır, metin hemen tam gelir.
- **Kimlik deneyi: yalnız DB değişince "Sen kimsin?" (15 Eyl):**
  - Betik: `scripts/kimlik_alan_deneyi.py`. Rapor: `docs/experiments/kimlik_alan_deneyi_2026-09-15_1546.json`.
  - Aynı kod, istem ve gerçek model; beş DB: finans kopyası, boş, sağlık serisi, web ziyareti serisi, finans + sağlık. Asıl demo DB değişmedi.
  - Alan tanımı DB'ye göre değişiyor ama ürün cevabı sorunlu çıktı.
  - **Sebep 1:** aktif tablo yokken ajan "veri çekilmeden cevap denendi" diye kimlik cevabını geri gönderiyor.
    - İlk taslak doğruydu ("BDDK ve TCMB verileri üzerinde çalışan…").
    - Yeniden yazılan cevap "önceki mesajın 'Sen kimsin?' idi" diye bozuluyor.
    - Sağlık ve web DB'lerinde model tablo döküyor.
    - Kullanıcının arayüzde gördüğü iyi cevap aktif tablo olduğu içindi (kural susuyor); canlı tekrarla doğrulandı.
    - Kural `core/agent.py`'de, PR #4'ün değiştirdiği dosya.
  - **Sebep 2:** yalnız kullanıcı serisi olan katalogda alan tanımı "adhoc kaynaklı veriler" (iç kimlik).
  - **Sebep 3:** "Hangi veri setlerine sahipsin?" cevabı eksik cümle ("Kullanıcının eklediği 1 seri de var.") ve seri adını söylemiyor.
  - Boş katalogda model örnek olarak enflasyon/döviz/BDDK yazdı (istemdeki finans örnekleri).
- **PR #4 entegrasyonu (15 Eyl, ADR-0080):**
  - **Karar.** Kullanıcı önce "Büşra'yı bekleyelim" dedi, sonra PR #4'ü birleştirip eksiklerini bizim düzeltmemize onay verdi.
  - **Dal.** `integration/user-error-gates-main` = feature/agent-engine + PR #4 merge commit (baa0df4).
    - Büşra'nın 30 commit'i aynı kimliklerle içeride; bu dalda olmayan PR #4 commit'i 0.
    - Büşra'nın dalına push yok.
  - **Durum.** Deneme birleştirmesi PR #4 → main ve bizim dal → (main + PR #4) çatışmasızdı. Birleşik ağaçta 611 test geçti,
    3 test kırıktı, K02 A06 kırmızıydı.
  - **Kök nedenler:**
    - Geniş ay kolonlu OCR tablosu (Yıl | Ocak | Şubat) yıllık sayılıp "2025 Ocak" reddediliyordu.
    - İlgi kapısı pytest yolunun dizin parçalarını ve kullanıcının beyan cümlesini konu terimi sayıyordu.
    - V3 adaptörü `validate_refs`'i atlıyordu. Kırılma PR #4'ten değil, 14 Eyl'de bizim workspace araçlarındaki boş tablo
      denetimini `validate_refs`'e taşımamızdan.
    - "düştüğü halde … dönemler olmuş mu?" öncül sayılıyordu.
    - Kimlik sorusu "veri çekilmedi" diye geri gönderiliyordu.
    - Kullanıcı serisi iç kimlikle anılıyordu ("adhoc kaynaklı veriler"); kapsamı 1900 görünüyordu. lakehouse-core onayda
      `meta.series` first_obs/last_obs'u güncellemiyor.
    - Yükleme ön eki seri anahtarına giriyordu.
  - **Düzeltme sırasında kendi hatalarım:**
    - Beyan sözcüklerini ortak durak listesine ekledim; katalog alias'ı "kalem türü" bozuldu.
    - Adresi tümden sildim; kullanıcının dosyayı adıyla anması ilgi işareti olmaktan çıktı.
    - Beyan sözcüğünü kökle düşürdüm; `birimsiz.csv` adı "birim" kökü yüzünden atıldı.
    - Üçü de testte yakalandı: soru tarafında tam sözcük, adres yerine dosya adı.
  - **Ölçüm:**
    - Ajan testleri 621.
    - K02 22/22, K01 22/22 (ilk koşu 21/22: T06 betiği "adhoc" arıyordu, beklenti seri adına sıkılaştırıldı), K01-T07 arayüz 15/15.
    - Kimlik deneyi yeniden: "Sen kimsin?" 15/15 kimlik anlatıyor (önce 2/15; biri de "adhoc kaynaklı veriler" diyordu).
  - **Sıra.** Kullanıcı onayıyla önce PR #4 GitHub'da merge commit, hemen ardından entegrasyon PR'ı.
- **main birleştirmeleri (15 Eyl, kullanıcı onayıyla):**
  - PR #4 → main, merge commit 83d73f9. Ebeveynleri bacab9d ve 1cfb85d.
  - PR #5 (entegrasyon) → main, merge commit 5a85254. Ebeveynleri 83d73f9 ve 70a0893. CI: agent-core 37 s, lakehouse-core
    46 dk 58 s, ikisi de yeşil.
  - PR #3'ten bu yana main'e 30 commit Büşra'dan (30 tekil kimlik, GitHub hesabı bushushow), 7 commit Baran'dan girdi.
  - İkisi de `gh pr merge --merge` ile birleştirildi: repoda squash ve rebase de açık, düğme seçimi hataya açık.
  - main'e push'ta CI iş akışı çalışmıyor; iş akışı yalnız PR'da koşuyor.
  - feature/agent-engine main'e ileri sarıldı; 8765 sunucusu bu kodla çalışıyor.
- **Bağlam kayması ve kullanım soruları (15 Eyl akşam, ADR-0081; kullanıcı kararı: önce çoklu senaryo testi, PR yok):**
  - **Bulgu (arayüz).** "naber" → "elimizde hangi veriler var" → "architect rolüne nasıl geçebilirim" akışında üçüncü soru veri
    seti tablosuyla cevaplandı.
    - Kayıtlı adımlar: "veri çekilmeden cevap denendi — geri gönderildi" → katalog araması → iki sorgu.
    - Bağlam penceresi değil, geri gönderme notunun "sayıları çek" zorlaması modeli geçmişteki son veri sorusuna döndürdü.
  - **Düzeltmeler:**
    - Rol, dosya yükleme, indirme ve oturum sıfırlama soruları arayüzün ve profilin gerçek durumundan deterministik cevaplanıyor.
    - Kullanım soruları "veri çekilmedi" diye geri gönderilmiyor.
    - Üç geri gönderme notu (veri çekilmedi, işlem iddiası, tabloda olmayan sayı) "Kullanıcının SON sorusu: «…». Önceki sorulara
      dönme" ile başlıyor.
  - **Canlı senaryolar ek iki gerçek hata buldu:**
    - Araçsız turda uydurma fark ("Kasım 677.970, +1.000") yayımlandı. `unverified_numbers`'ın göreli %0,5 toleransı ve "1.000"ın
      ondalık okumasının satır sayısına eşleşmesi sebepti. Tolerans gösterim hassasiyetinin yarım birimine indirildi.
    - "Oturumu nasıl sıfırlarım?" sorusuna model "yazmanız yeterli" diye uydurdu; artık düğmeleri anıyor.
  - **Kendi hatam.** İlk koşuda senaryo denetimi yalnız "kasım/fark" sözcüğüne bakıyordu ve uydurma cevabı geçirdi; elle okumada
    bulundu, denetim tutar karşılaştırmasına çevrildi. Aynı dakikada biten iki koşu aynı rapor dosyasına yazdı; S3 ×5 konsol
    çıktısı saklandı, betik adı düzeltildi.
  - **Ölçüm:**
    - Ajan testleri 632; K01 22/22, K02 22/22.
    - Son tüm senaryolar koşusu sıkı denetimle 45/45, son S3 ×5 13/15.
    - Fark cevaplarında uydurma tutar: düzeltmeden önce 11 cevapta 2, sonra 8 cevapta 0.
  - **Açık:**
    - Tek satırlık tablodan sonra "önceki aya göre fark" planlaması: bir tekrarda `workspace_add_column` önceki ayı aynı tarihe
      ekledi, cevap "0 değişim" oldu.
    - Araçlı turların `grounding_check`'i de göreli %0,5 tolerans kullanıyor.
- **Kullanıcı metninde iç ad yok (15 Eyl akşam, ADR-0082; kullanıcı kararı, PR yok):**
  - **Bulgu.** Arayüzde "Elinde nasıl veriler var" deterministik yola düşmedi (kalıp yalnız hangi/ne/neler), modele gitti.
    - Model "Hazır Gold tabloları" başlığı ve doğrulanmamış "687+ seri" yazdı (doğrusu 681).
    - Grafik altyazısı ve rapor kaynakları "bddk_monthly — / gold —" diye yazılıyordu.
  - **Kullanıcı kararı:**
    - Cevap metninde iç kimlik ve mimari adı olmayacak.
    - Kanıt zinciri katman adlarını taşımaya devam edecek.
    - Sol panel sayaçları kullanıcı diliyle yazılacak.
  - **Düzeltmeler:**
    - "nasıl / ne tür / ne çeşit veriler" deterministik.
    - Sistem istemi ve Gold istemi iç adı yasaklıyor; kural alan bağımsız, finans terimi yok.
    - Arama kartı tablonun kaynağını yazıyor ("hesaplanmış tablo (TCMB EVDS ve BDDK Aylık Bülten verisinden)").
    - `labels.readable_source` grafik altyazısı ve rapor için okunur ad veriyor.
    - `labels.humanize_internal` son güvence: kimlik → katalog adı, "Gold tablosunda" → "hesaplanmış tabloda".
    - Tablosuz ve veri çekilmemiş turda sayılar araç çıktısıyla doğrulanıyor.
    - Sol panel "gözlem / hesaplanmış tablo".
  - **Ölçüm:**
    - Ajan testleri 638; K01 22/22, K02 22/22, arayüz 15/15.
    - Canlı 7 senaryo × 3 kayıtlı 57/60. Üç kırmızı da denetim kalıbımın hatası: okunur "TCMB EVDS:" ifadesini `evds:` kimliği
      saydı. Kalıp düzeltildi, 60 cevabın hiçbirinde iç ad yok.
  - **Açık soru (kullanıcıya soruldu).** Veri seti cevabı içeriği canlı katalogdan okuyor, ama yalnız kaynak, sayı ve dönem veriyor.
    Konu başlıkları eklenmesi ya da cevabı modelin katalog bilgisiyle yazması seçenekleri kullanıcıda. Okunur adı olmayan yeni
    kaynak ham kimlikle görünür.
- **Veri seti cevabı konu başlıklı; tablosuz sayı denetimi düzeltildi (15 Eyl akşam, ADR-0082 ek 1-2):**
  - **Kullanıcı kararı.** Deterministik veri seti cevabına konu başlıkları eklendi. İçerik her soruda canlı katalogdan okunuyor;
    Architect ekleme ve onayı `reload()` ile kataloğu hemen yeniliyor.
  - **Konu.** Ölçüm kolonunun ilk takma adından çıkarılıyor; il bazlı kaynakta il adı atılıyor ("81 il × 8 konu"), kısaltmalar
    adındaki yazımla ("TÜFE"), en çok 6 konu.
  - **Yeni kaynağın adı ayar dosyası olmadan:** source_names → adres/kimlikten kurum adı ("tuik" → "TÜİK") → alan adı → kimlik.
    `meta.source` DB'de boş, kullanılmadı.
  - **Kendi gerilemem.** Tablosuz sayı denetimi havuzu yalnız bu turun araç çıktısıydı. S8'de önceki deterministik cevaptan
    tekrarlanan doğru "81 il" maddeleri 3/3 silindi, başlık boş kaldı; not da tablo yokken "tabloda" diyordu.
  - **Düzeltme:**
    - Havuz = araç çıktıları + ön-yükleme kartları + önceki cevaplar.
    - Not metni düzeltildi.
    - Denetim araçsız tura da uygulanıyor; model araçsız "166 seri" yazmıştı.
  - **Kontrol dersi.** "Geri gönderilmez" denetimi yanlış şeyi ölçüyordu; S8 artık "boş başlık yok" arıyor. Kusurlar iki kez
    otomatik denetimde değil elle okumada bulundu.
  - **Ölçüm:**
    - Ajan testleri 644; K01 22/22, K02 22/22, arayüz 15/15.
    - 8 senaryo × 3 canlı 66/66: iç ad 0, boş başlık 0, silinen ifade 0, fark 3/3 doğru.
    - Kimlik deneyinde silinen ifade 0.
  - **Açık:** model cevabında iç kolon adı (`entity_id`) ve olmayan banka/kurum kırılımı iddiası görüldü.
- **PR #6 main'e birleşti (15 Eyl akşam, kullanıcı onayıyla):**
  - Birleştirme: merge commit 7e47213, ebeveynler 5a85254 ve fbeee45; `gh pr merge --merge`.
  - Kapsam: ADR-0081 (bağlam kayması, kullanım soruları, uydurma tutar toleransı, sıfırlama cevabı), ADR-0082 ve ekleri (iç ad yok,
    konu başlıklı veri seti cevabı, yeni kaynağın okunur adı, tablosuz sayı denetimi), sol panel etiketleri.
  - CI yeni PR koşusunda yeşil: agent-core 38 s, lakehouse-core 44 dk 41 s. PR sayfası ilk anda aynı commit'in eski koşusunu yeşil
    gösterdi; birleştirme yeni koşunun sonucu beklenerek yapıldı.
  - feature/agent-engine main'e ileri sarıldı.

### 2.36 MIA yanıt gecikmesi teşhisi (17 Eylül)
- Canlı sohbet `ca17151aa4e3`: ilk veri sorusu 199,5 s; `lakehouse_query` 23,2 s, son anlatım LLM çağrısı 174,8 s; toplam iki LLM çağrısı ve prompt kullanımı 24.261 token.
- Aynı sohbette alakasız `Machine learning nedir` sorusu 49,2 s ve 10.448 prompt token kullandı. Aktif tablo, son sekiz mesaj ve finans takip bağlamı modele taşındı.
- `core/agent.py` her turda izinli araç şemalarını (~15.934 karakter, yaklaşık 5.000 token) gönderiyor; son anlatım turunda araç çağrısı gerekmese de şemalar tekrar gönderiliyor. Sistem + ön-yükleme bağlamı da yaklaşık 6.000 token.
- `core/follow_up.py` kısa ve yeni alan belirtmeyen soruları önceki bağlama takip sorusu sayabiliyor; bu, bağımsız kullanım/genel bilgi sorularında gereksiz tablo ve finans bağlamı taşıyor.
- `LLM_DISABLE_THINKING=true` kısa kontrollü çağrıda çalışıyor (reasoning token 0); bu vakadaki ana neden düşünme modu değil, büyük prompt + uzun anlatım üretimi ve MIA değişken gecikmesi.
- Öncelikli optimizasyon adayları: alakasız yeni soruda takip bağlamını temizlemek; nihai yeniden yazım çağrılarında tool schema göndermemek; basit/genel soruları LLM'e gitmeden ayırmak; LLM çağrısı başına prompt/completion/HTTP retry sürelerini ayrı ölçmek.

### 2.37 origin/main ile karşılaştırma (17 Eylül)
- `origin/main` güncellendi: `573f4a6`; `feature/agent-engine` (`69a0aaa`) ile ortak ata `4f65310`; feature dalı 1 commit önde (PROJECT_MEMORY), main 10 commit ileride.
- Üst seviye dizinler aynı (`agent-core`, `lakehouse-core`, `docs`, `scripts`, `tests`); main'in eklediği yapısal dosyalar bounded execution recovery modülü, iki recovery/numeric-grounding test dosyası, iki workflow ve iki inceleme dokümanı.
- Main çalışma zamanı ilerlemeleri: araç hatalarında en fazla 3 yeniden planlama ve `availability_status` kanıtı; sayısal grounding/evidence toleransının gösterilen hassasiyete göre sıkılaştırılması; libyaml ile katalog yükleme hızlandırması.
- Bu main değişiklikleri mevcut başarılı akışın LLM prompt boyutunu küçültmüyor. Recovery, yalnız hatalı araç çağrılarında ek LLM turları açtığı için o senaryolarda gecikmeyi artırabilir; mevcut MIA gecikmesi için tek başına çözüm değildir.
- Çalışma ağacında commit edilmemiş `PROJECT_MEMORY.md`, `.claude/launch.json` ve üç UI kabul deney dizini ile bir JSON var; doğrudan `git pull` yapılmayacak, önce temiz bir benchmark/inceleme dalında main değişiklikleri doğrulanacak.

### 2.38 origin/main birleşimi (17 Eylül)
- `origin/main` (`573f4a6`) `feature/agent-engine` dalına `957176c` merge commit'iyle alındı; mevcut yerel bellek ve kabul çıktıları stash ile korunup geri yüklendi.
- Birleşen kapsam: bounded execution recovery, sayısal grounding/evidence toleransı, libyaml katalog yükleme hızlandırması, yeni agent/lakehouse CI workflow'ları ve ilgili test/dokümanlar.
- Doğrulama: agent-core tam test paketi 759 geçti (1 deprecation warning); lakehouse-core katalog testleri 57 geçti; diff check temiz.
- `.env` değiştirilmedi; birleşim öncesi ve sonrası SHA-256 `326ac678ad0242b1a62a79aaf0d08775a6243c42241847c847ec1fb986e46075` aynı.
- Dal, `origin/feature/agent-engine` karşısında 11 commit önde; paylaşmak için ayrıca push gerektirir.
- Merge sonrası çalışan demo süreci yeni kodla yeniden başlatıldı; `127.0.0.1:8765` dinliyor.

### 2.39 Lakehouse kurulum doğrulaması (17 Eylül)
- `lakehouse-core` kilitli ortamı `uv sync --frozen` ile senkron; `.venv` Python 3.12.13 ve lakehouse importu çalışıyor.
- CLI komut grubu (`bootstrap`, `ingest`, `silver`, `gold`, `promote-draft`, `gold-run`, `ingest-file`) yardım çıktısında doğrulandı.
- Lakehouse-core tam test paketi: 1126 geçti (380,03 s); agent-core testleri: 759 geçti.
- Kök veri tabanı `data/lakehouse.duckdb` salt-okunur açıldı: `meta.series` 2214, `silver.fact_observation` 43830, `gold.konut_faizi_aylik` 127 ve `gold.kur_ve_faiz_aylik` 127 satır.

### 2.40 Kick-off kapsamı ile veri envanteri karşılaştırması (17 Eylül)
- Kick-off transkripti belirli dosya adları vermiyor; zorunlu açık kaynak başlıkları BDDK haftalık bülten, BDDK aylık bülten, BDDK FinTürk il verileri ve TCMB EVDS (5 yıllık derinlik ve frekans hizalama).
- Katalogda bunlara karşılık `bddk_finturk` 648 (81 il × 8 seri), `bddk_monthly` 22, `bddk_weekly` 1 ve EVDS 1545 seri var. Kök DB bootstrap'ında 2 aylık seri (`194_Toplam`, `158_Toplam`) henüz meta.series'e alınmamış; katalog ve DB sayıları bu yüzden 2216/2214.
- `data/incoming` altında konut_test, TÜFE HTML'leri, M16 sağlık/web CSV'leri, PDF'ler ve kullanıcı yüklemeleri bulunuyor; bunlar transkriptte adı geçen zorunlu dosyalar değil, jenerik ingest/demo/test girdileri.
- `data/charts`, `data/conversations`, rapor JSON'ları ve `agent-core/data` altındaki fixture/alternatif DB çalışma çıktıları kaynak veri değil; mevcut demo `LAKEHOUSE_PATH=data/lakehouse.duckdb` ile kök DB'yi kullanıyor.

### 2.41 FinTürk kapsam karşılaştırması (17 Eylül)
- Mevcut FinTürk kataloğu 81 il × 8 doğrulanmış ölçüm = 648 seri; kök Silver'da 27.216 satır, seri başına 42 gözlem (2016-03–2026-06) bulunuyor.
- Arkadaşın ekranındaki 56 kolon × 81 il = 4.536 hesabı aynı kaynağın daha fazla tablo/kolon kapsamını ölçüyor; bizim 648 seriyle doğrudan kıyaslanabilir bir dosya boyutu değil, katalog genişliği ölçüsüdür.
- Mevcut connector yalnız `tabloNo=3` Bireysel Bankacılık sözleşmesini canlı doğruluyor. Diğer FinTürk tabloları/parti grupları eklenmeden 56 kolona çıkmak semantik, birim, frekans ve erişim doğrulaması yapılmamış kapsam olur.

### 2.35 Kanıt yolculuğu tek gösterim, sohbet kaydı ve PR #7 birleştirmesi (15–16 Eylül)
- **Kanıt yolculuğu (ADR-0083):**
  - 3B three.js ve yürüyen karakter kaldırıldı; tıklanabilir tasarım prototipi gerçek kayıtla (Adana konut kredisi) hazırlanıp onaylandı.
  - Duraklar yalnız kanıtta olan halkalardan kurulur; sıra verinin akışıdır: kaynak → RAW → Bronze → Silver → (hesaplanmış tablo) →
    SQL → Tablo → Cevap. İlk uygulamada sıra tersti, kullanıcı ekranda görünce çevrildi.
  - Animasyon ilk kopuk halkada durur, sonrası "doğrulanamadı". Sayı çipleri kullanıcı isteğiyle kaldırıldı; sağ panelde küçük zincir var.
- **Sohbet kaydı (ADR-0084):**
  - Her sohbet `DATA_ROOT/conversations/<kimlik>` altında, cevaptan sonra yazılır; uygulama yeniden açılınca son açık sohbet gelir.
  - Sohbet listesi sol panelde, en son kullanılan en üstte. Önce hamburger menü denendi; kullanıcı sürekli görünen listeyi seçti.
  - Yeni sohbet düğmesi, onaylı silme; "Oturumu sıfırla" açık sohbeti ve yüklemelerini siler.
  - Tam veri sıfırlama sohbetleri korur ve "sıfırlamadan önce" diye işaretler.
  - Orta genişlikte (≤1100 px) önce sağdaki kanıt paneli gizlenir, sohbet listesi solda kalır.
- **origin/main birleştirmesi (PR #7, çok turlu bağlam):** feature/agent-engine'e yerel merge commit 05b06a3 ile alındı, çakışma
  çıkmadı. Takip bağlamı (`_follow_up_context`) sohbete bağlandı: yeni sohbette boşalır, açılan sohbette geri gelir.
- **Ölçüm:** agent testleri 675/675; arayüz kabulü (k01_ui) 15/15 (Playwright 1.62.0, önbellekteki tarayıcıyla).
- **Adım yolculuğu (ADR-0085):** alttaki araç izi çubuğu 14 adımda altı satıra yayılıp konuşma alanını daraltıyordu (900 px ekranda
  520 px). İzler "Yolculuğu izle"nin yanındaki "Adımları izle" penceresine taşındı:
  - figürlerle ve sırayla; arka arkaya aynı araç tek durak (×N);
  - hatalı çağrı kırmızı, geri gönderilen taslak amber; son durak cevap toplamları;
  - kanıt yolculuğuyla ortak `chainViewer` motoru kullanılıyor;
  - alt çubuk tek satır özet oldu (konuşma alanı 729 px). Testler 679/679.
- **Durum:** commit edilmedi; kullanıcı kontrol ettikten sonra PR ile main'e gidecek.
- **Son doğrulama ve PR (16 Eyl gece):** son kodla arayüz kabulü 15/15 (`docs/experiments/k01_ui_kabul_2026-09-16_0121`); kullanıcı
  onayıyla commit edildi, feature/agent-engine'den main'e PR açıldı. main'e birleştirme CI yeşil gelince ayrıca onayla yapılacak.
- **PR #8 main'e birleşti (16 Eyl, kullanıcı onayıyla):** merge commit 4f65310, ebeveynler d187502 ve f135d4a; `gh pr merge --merge`.
  - Kapsam: ADR-0083 (kanıt yolculuğu tek gösterim), ADR-0084 (sohbet kaydı, solda sohbet listesi), ADR-0085 (adım yolculuğu, tek
    satır araç izi) ve son arayüz kabul raporu.
  - CI bu commit'in kendi koşularında yeşil: agent-core 37-39 s, lakehouse-core 28 ve 47 dk.
  - feature/agent-engine main'e ileri sarıldı.

### 2.42 FinTürk 56×81 demo veri kapsamı (18 Eylül)
- Kullanıcı kararı: Demo, FinTürk'te 56 ölçüm kolonu × 81 il = **4.536 aktif seri** üzerinden ilerleyecek. `tabloNo=5` (Oranlar) ve `7` (Altın) kapsam dışı; tüm istekler Sektör (`tarafKodu=10001`).
- Canlı kaynak doğrulaması: tablo 1/2/3/4/6 ölçü sayıları sırasıyla 4/7/8/31/6; `sehirList[0]=HEPSİ` tek yanıtta illeri döndürüyor. Tablo 1–4'teki ek `YURT DIŞI` satırı parser tarafından atılıyor.
- `BddkFinTurkParser` artık tek şehir ve `HEPSİ` çoklu şehir yanıtlarını destekliyor; tek şehirdeki birden fazla satır için eski fail-closed denetimi korunuyor.
- `scripts/ingestion_registry.py` FinTürk seri kayıtlarını tablo bazlı bulk FetchSpec'lere eşliyor. Tablo 3'ün mevcut seri kimlikleri korunarak dataset kimliği `bddk_finturk_table3` altında ortaklaştırıldı; yeni tablo 1/2/4/6 kayıtları da tablo bazlı dataset kullanıyor.
- `lakehouse-core/catalog/series/bddk_finturk.yml` 3.888 kayıt eklenerek 4.536'ya çıkarıldı. Bootstrap sonrası DB'de `meta.series` FinTürk sayısı 4.536.
- Canlı backfill: 2016-03–2026-06, 5 tablo × 42 çeyrek = 210 RAW/Bronze artifact; 0 fetch failure. Silver yeniden kuruldu: 190.512 satır, 4.536 distinct seri, 0 boundary duplicate.
- Kök demo veri kökünde önceki il-başı tablo-3 Bronze temsilleri (3.402 dosya) silinmedi; kimlik çakışmasını önlemek için `data/bronze_legacy_finturk_20260918` altına taşındı. Kök `data/lakehouse.duckdb` ve `data/bronze` artık çalışan baseline'dır.
- Doğrulama: FinTürk parser/connector/catalog/ingestion testleri 106 geçti. `.env` dosyasına dokunulmadı.
- Semantik sınır: yeni tablo 1/2/4/6 kayıtları kaynak tablo etiketlerinden türetilen unit/measure_type ile `semantic_confidence: derived`; tablo 3'ün önceki bağımsız birim doğrulaması korunuyor. Tablo bazlı ek çapraz doğrulama demo öncesi backlog'da.

### 2.43 BDDK/EVDS veri kullanılabilirliği kontrolü (18 Eylül)
- Kök demo DB kaynak özeti: `bddk_finturk` 4.536 seri / 190.512 gözlem; `bddk_weekly` 1 seri / 547 gözlem; `bddk_monthly` 20 seri / 2.417 gözlem; EVDS 12 seri / 13.650 gözlem.
- BDDK aylık kataloğunda 22 aktif seri bulunuyor; `bddk_monthly:194_Toplam` ve `bddk_monthly:158_Toplam` henüz Silver'da yok.
- EVDS kataloğu 1.545 kayıt (1.236 active, 309 deprecated) içeriyor; bunun yalnız 12 aktif/curated serisi mevcut Silver'a alınmış. Katalog genişliği ile fiziksel veri yüklemesi aynı şey değil; tüm EVDS kataloğu şu an tam backfill edilmiş sayılmayacak.
- BDDK haftalık ve FinTürk kapsamı demo için dolu; aylık iki seri ve EVDS'in katalogda olup henüz indirilmeyen serileri demo öncesi açık backlog olarak tutuluyor.

### 2.44 BDDK aylık eksik serilerin tamamlanması (18 Eylül)
- Toplantı kapsamındaki dönem (2021-01–2026-06) kullanılarak `bddk_monthly:158_Toplam` ve `bddk_monthly:194_Toplam` yeniden indirildi; her biri 66 gözlem ve Bronze'a birer artifact olarak yazıldı.
- Silver yeniden kuruldu: BDDK aylık **22 seri / 2.549 gözlem**, tüm seriler için üst dönem Haziran 2026. Kümülatif seriler kaynak semantiği korunarak kaydedildi; sıfır görünen boş hücre uyarıları provenance'a işlendi.
- Kök demo DB preflight: katalog 6.104 seri, yüklü 4.571 seri, 207.258 gözlem; Gold 6 tablo; servis `127.0.0.1:8765` üzerinde HTTP 200 ile çalışıyor.
- `.env` değiştirilmedi. EVDS'in 1.545 kayıtlık kataloğundan yalnızca 12 küratörlü seri fiziksel olarak yüklü olma durumu devam ediyor ve ayrı kapsam kararı gerektiriyor.

### 2.45 Zorunlu dönem kapsamı doğrulaması (18 Eylül)
- 2021-01–2026-06 aralığında seçilmiş demo kapsamı seri başına eksiksiz: FinTürk 4.536/4.536 seri × 22 çeyrek; BDDK aylık 22/22 seri × 66 ay; BDDK haftalık katalogdaki 1/1 seri × 286 hafta.
- EVDS tarafında aynı aralıkta 12 küratörlü seri yüklü (7.141 gözlem); katalogdaki 1.236 aktif serinin tamamı fiziksel olarak backfill edilmiş değil. Bu nedenle “zorunlu seçilmiş demo kapsamı tamam”, “tüm katalog tamam” sonucu birlikte korunur.

### 2.46 origin/main senkronizasyonu (18 Eylül)
- `origin/main` `84d9355` commit'ine ilerledi; `feature/agent-engine` üzerine `ae87333` merge commit'iyle alındı. Yeni kapsam: sonuç tablosu projection, workspace uyumsuzluk kontrolü, eksik timestamp normalizasyonu, hücre hizalama düzeltmesi ve web/UI regresyon testleri.
- Doğrulama: agent-core ilgili yeni testler 23/23, tam test paketi 773/773 geçti. Servis birleşmiş kodla `127.0.0.1:8765` üzerinde HTTP 200 ve preflight “hazır” durumunda.
- Yerel FinTürk/lakehouse değişiklikleri ve kabul çıktıları stash ile korunup geri yüklendi; merge sırasında conflict oluşmadı. `.env` SHA-256 `3d9edab0b35a33c3c0b99c4e1dec457f54d8cc8abe03ba160ddcced59d74e516` olarak değişmeden kaldı.

### 2.47 Reasoning ayarı denetimi (18 Eylül)
- Çalışan demo `.env` içindeki `LLM_DISABLE_THINKING=false` ile başladı; üretim istemcisinde açık bir `reasoning_effort` seviyesi gönderilmiyor, sağlayıcının varsayılanı kullanılıyor.
- `LLM_DISABLE_THINKING=true` olduğunda istemci `reasoning_effort=none` ve `enable_thinking=false` göndererek düşünmeyi kapatıyor. Ana agent yolunda `low` gibi ara seviye ayarı yok; değişiklik sonrası servis yeniden başlatılmalı.

### 2.48 Çoklu BDDK aylık sorusunda timeout teşhisi (18 Eylül)
- Canlı sunucu çıktısında istek için LLM çağrısı 1/3 ve 2/3 `Request timed out` uyarıları görüldü; herhangi bir `adım ... lakehouse_*` kaydı oluşmadan timeout'a girdi. Bu vaka ilk planlama LLM çağrısında kesiliyor, DuckDB sorgusunun yavaşlığından kaynaklandığına dair kanıt yok.
- İstek metnindeki “2022–2023” ile “60 aylık” birbiriyle uyumsuz: 2022-01–2023-12 **24 ay**. Aynı soru deterministik bir tarih netleştirmesi olmadan modele gönderiliyor.
- Mevcut facet çıkarımı `60 aylık` ifadesini frekans değil pencere sayıyor; bare `BDDK` ve `Türkiye’deki` kaynak/ulusal facet'i açmıyor. 4.577 sorgulanabilir seri üzerinde `bm25` aramasının `limit=8` sonucu doğru aylık seriler yerine bayat `gold.tuketici_kredisi_kirilimi_aylik` ve yedi il bazlı FinTürk “Diğer Tüketici Kredileri” kartı döndürüyor. `limit=30` çağrısında doğru `bddk_monthly:1536_Toplam` ve `bddk_monthly:1539_Toplam` sonuçları mevcut.
- Veri mevcut ve hızlı: kök Silver'da 1536 ve 1539 serilerinin her biri 2022-01–2023-12 arasında 24 gözleme sahip. Yeni Silver backfill'inden sonra altı Gold tablosu bayat; doğru hesaplanmış tablo yeniden oluşturulmadı.
- İlk çağrı için yaklaşık yük: sistem 11.031 karakter, izinli 14 araç şeması 15.934 karakter, ön-yükleme 6.375 karakter (~1.993 token); reasoning açıkken bu yanlış kartlar ve belirsiz tarih isteğiyle birlikte Kloudeks'in 90 saniyelik çağrı sınırını aşabiliyor. Aynı timeout isteğinin 3 kez değiştirilmeden tekrarlanması toplam beklemeyi uzatıyor.
- Öncelikli düzeltme sırası: (1) tarih çelişkisini LLM'den önce netleştirme, (2) kaynak/frekans/ulusal facet'lerini generic katalog ipuçlarıyla düzeltip il-serisi çoğalmasını engelleme, (3) Silver değişiminden sonra Gold'u yenileme, (4) son anlatım çağrısında araç şemalarını göndermeme, (5) timeout'ta aynı isteği körlemesine üç kez tekrarlamak yerine kısaltılmış bağlamla tek yeniden deneme, (6) planlama reasoning'ini açık bırakıp final anlatım için ayrı düşük/kapalı thinking seçeneğini ölçme.

### 2.49 İç içe dönem niyeti, retrieval düzeltmesi ve Gold yenilemesi (18 Eylül)
- Kullanıcı kararı: “60 ay çek ama 2022–2023 arasındaki 24 ayı içersin” ifadesi çelişki olarak reddedilmeyecek; 24 aylık aralık, 60 aylık sonuç penceresi için **dahil edilmesi gereken anchor** olarak yorumlanacak.
- `agent-core/src/kkb_agent/core/period_intent.py` eklendi. Yıl/ay aralıklarını, ay penceresini ve `kapsayan/içersin/içeren` gibi containment ifadelerini deterministik çıkarıyor. Dış başlangıç/bitiş verilmemişse birden fazla 60 aylık pencere mümkün olduğundan LLM çağrılmadan tek netleştirme sorusu dönüyor; sistem tarih uydurmuyor. `2021-01–2025-12` gibi dış sınır açık olduğunda kapı çalışmıyor.
- Retrieval facet'leri generic hale getirildi: bare `BDDK` kaynak ailesi, `Türkiye’deki/Türkiye geneli/ülke geneli` ulusal kapsamı, `60 aylık dönem` aylık pencere frekansı olarak işleniyor. Ulusal isteklerde il serileri eleniyor; kaynak ailesi (`bddk_*`) eşleşiyor. BM25 facet öncesi aday havuzu `k×10` yerine `k×50`/en az 500'e çıkarıldı; doğru aylık seriler il tekrarları arasında kaybolmuyor.
- Gerçek katalog doğrulaması: yeni aramada `bddk_monthly:1536_Toplam` 1. sırada, `bddk_monthly:1539_Toplam` ilk 8 içinde; FinTürk il serileri ulusal istekte elendi. Gold stale listesi boş.
- Yeni Silver'dan Gold yeniden üretildi: build id `c87a15b9-e3ef-4d73-aef1-3de904f5fd15`, 207.258 Silver gözlemi, 7/7 metrik tablo, 0 refused. Servis yeniden başlatıldı; `/api/status` HTTP 200, `gold_tables=7`, `silver_rows=207258`.
- Testler: period/facet/retrieval/agent odaklı 48 geçti; canlı belirsiz soru 0 LLM çağrısıyla dış pencereyi istedi. `.env` değiştirilmedi.

### 2.50 İç içe dönem kapısının kenar durumları (18 Eylül)
- Netleştirme cevabı soru işaretiyle bitiyor; kısa kullanıcı yanıtı (`2021-01–2025-12`) mevcut pending-question akışıyla asıl isteğe bağlanabiliyor.
- 24 aylık anchor'dan kısa bir pencere (ör. 12 ay) artık ayrı bir uyumsuzluk olarak yakalanıyor; sistem sayı üretmeden en az anchor kadar pencere istiyor.
- Ay düzeyinde açık dış aralık (`2021-01–2025-12`) ile aynı uzunluktaki `60 aylık` ifadesi exact window kabul ediliyor; 24 aylık aralık + 60 ay ise anchor olarak korunuyor.

### 2.51 Dönem guard'ında anchor yılları (18 Eylül)
- Canlı dış pencere denemesinde model `2021–2025` filtresini kurduğu halde guard, soruda geçen anchor `2022–2023` yıllarını da SQL'de aradı ve `MISSING_PERIOD_FILTER` üretti; bu gereksiz LLM retry'larına ve 120 saniyelik beklemeye yol açtı.
- `_atlanmis_donem_filtresi` artık `period_intent` ile aynı sözleşmeyi kullanıyor: dış pencere açıkken yalnız dış sınır yıllarını zorunlu kılıyor, anchor yıllarını ikinci filtre olarak istemiyor. Regresyon testi eklendi; agent-core tam paket **778** geçti.

### 2.52 Açık dış pencere canlı kontrolü (18 Eylül)
- `2021-01–2025-12` dış penceresi + `2022–2023` anchor'ı ile canlı akışta `MISSING_PERIOD_FILTER` tekrarı ortadan kalktı; modelin ilk dönem sorgusu başarıyla çalıştı.
- Kloudeks'in reasoning açık ilk planlama çağrısı bu koşuda yaklaşık 74 saniye sürdü; bu kalan sağlayıcı gecikmesidir, dönem guard'ının yeni retry döngüsü değildir. Bu kayıt, dönem düzeltmesinin doğruluğu ile LLM latency problemini ayrı izlemek için tutuldu.

### 2.53 Temiz demo oturumu (18 Eylül)
- Güncel kod ve yeniden oluşturulmuş Gold ile servis yeniden başlatıldı; önceki yarım canlı istek temizlendi.
- `/api/reset` ile yalnız aktif sohbet/agent çalışma durumu sıfırlandı; veri kökü, Silver, Gold ve `.env` korunuyor.
- Temiz durum: sohbet geçmişi 0, Gold tablo 7, Silver gözlemi 207.258, katalog 5.795, servis `127.0.0.1:8765`.

### 2.54 Demo sorusu korunuyor (18 Eylül)
- Kullanıcının verdiği demo sorgusu değiştirilmedi ve sistem yeni bir “net soru örneği” önermiyor; dönem belirsizliğinde yalnız gerekli başlangıç/bitiş aylarını istiyor.

### 2.55 Demo bağlantı süreci (18 Eylül)
- `Failed to fetch` kontrolünde 8765 portunda servis süreci yoktu; veri/API hatası değildi. Güncel servis yeniden başlatıldı.
- UI, static dosya ve `/api/status` uçları HTTP 200 dönüyor; demo yeniden erişilebilir.

### 2.56 İç içe dönem için otomatik pencere seçimi (18 Eylül)
- Kullanıcı kararı önceki netleştirme politikasını değiştirdi: anchor aralığını içeren daha büyük pencere için kullanıcıdan dış tarih istenmeyecek.
- `period_intent` artık seçili katalog kapsamının ortak aralığındaki tüm geçerli pencereleri çıkarıp `SystemRandom` ile birini seçiyor. Anchor'dan kısa isteklerde minimum pencere anchor uzunluğuna genişletiliyor.
- Seçilen pencere modelin aktif sorusuna ve sistem notuna ekleniyor; SQL guard yalnız seçilen dış sınır yıllarını zorunlu tutuyor. Cevap başına `(Otomatik seçilen dönem: …)` kanıt satırı ekleniyor.
- Eski “dış pencereyi kullanıcıdan iste” akışı kaldırıldı; demo sorusu değiştirilmeden otomatik seçim yapılıyor.

### 2.57 Localhost yeniden başlatma (18 Eylül)
- Servis kapalı olduğu için `127.0.0.1:8765` güncel kodla yeniden başlatıldı.
- `/api/status` HTTP 200: Analyst profili, BM25 retrieval, 207.258 Silver gözlemi ve 7 Gold tablo doğrulandı.

### 2.58 60 aylık sonuçta aylık grain koruması ve model bağlamı düzeltmesi (18 Eylül)
- Ekran denemesinde otomatik seçilen `2021-04–2026-03` penceresine rağmen sonuç yalnızca `2022-12-31` ve `2023-12-31` olmak üzere iki satıra indi. Kök neden, seçilen pencerenin yalnızca sistem notunda kalması ve modelin anchor yıllarını dış pencerenin yerine koyabilmesiydi; DuckDB sorgu süresine dair kanıt yoktu.
- `_ask` artık `_period_resolved_question` değerini hem sistem notuna hem de gerçek kullanıcı mesajına gönderiyor. Böylece seçilen başlangıç/bitiş ayları SQL planında görünür.
- Dönem seçim notu aylık isteklerde beklenen farklı ay sayısını ve “anchor yıllarını gruplayıp iki satıra indirme” yasağını açıkça söylüyor.
- `LakehouseQueryTool` sorgu sonrası date/period kolonundan farklı `YYYY-MM` sayısını deterministik kontrol ediyor. Sayı beklenen pencere ayından azsa sonuç aktif tabloya yazılmadan `PERIOD_GRAIN_MISMATCH` (retryable) döndürülüyor; modelden aylık period satırlarını onarması isteniyor. Böylece yanlış iki satır başarılı tablo gibi gösterilmiyor.
- Yeni hata kodu agent recovery kümesine eklendi; iki satırlı regresyon ve tam 60 aylık başarılı sonuç testleri yazıldı.
- Doğrulama: `agent-core/tests` **782 geçti**, `compileall` ve `git diff --check` başarılı. `.env` değiştirilmedi.
- Performans kararı: 300 saniyelik bütçeyi artırmak yerine yanlış sonucu erken ve deterministik reddetmek seçildi. Sağlayıcı reasoning açıkken tek LLM çağrısının 90 saniyeye yaklaşması ayrı bir latency riski olarak izleniyor; aynı timeout'u körlemesine uzatmak bu tür isteklerde toplam beklemeyi artırabilir.
- Test tekrarı için eski başarısız sohbet silinmeden yeni boş sohbet (`87d4d6842ad2`) aktif edildi; API status'ta history boş.
- `PERIOD_GRAIN_MISMATCH`, bounded execution recovery kümesine de eklendi; ilk redden sonra en fazla üç sınırlı planlama/onarım denemesi yapılabiliyor. Aynı yanlış sonuç aktif tabloya alınmıyor.

### 2.59 LLM dışı harness gecikme denetimi ve genel ölçekleme planı (18 Eylül)
- Aynı sorunun canlı logunda araç adımı oluşmadan LLM istemcisi üç kez timeout oldu; mevcut istemci aynı tam payload'ı 90 saniyelik timeout ile 3 kez deniyor ve aralarda 2/4 saniye bekliyor. Bu, DuckDB sorgusunun yavaşladığına dair kanıt değil; ilk planlama çağrısı provider/context aşamasında kesiliyor.
- Güncel basit BDDK sorusu için model çağrısı ölçümü: araç kapısı 14 şema sunuyor (yaklaşık 15.934 karakter / 4.980 tahmini token); sistem + ön-yükleme yaklaşık 17.465 karakter / 5.458 token; ilk istek yaklaşık 10,4 bin tokenlık bağlamla başlıyor.
- Genel çözüm planı: (1) faz bazlı tool şeması (`retrieve → query → transform → narrate`), (2) katalog ve dönemden typed `PlanSpec` üreten deterministik soru derleyici, (3) SQL yerine katalog doğrulamalı query builder, (4) sonuç sözleşmesiyle kaynak/frekans/coğrafya/dönem/anahtar/birim doğrulaması, (5) aynı payload'ı tekrarlamayan deadline-aware retry merdiveni, (6) soru/katalog sürümü/SQL sonuç önbellekleri, (7) doğrudan veri getir sorularında deterministik anlatım, (8) p50/p95 latency, token, tool-round ve recovery metrikleri.
- Mimari kırmızı çizgi: domain davranışı finans koduna gömülmeyecek; derleyici katalog metadata'sı ve tool capability sözleşmeleriyle jenerik kalacak. Daha fazla aracı tek LLM çağrısına eklemek yerine faza göre sunulan seçenekler daraltılacak.

### 2.60 Fazlı şema, deadline ve doğrulama paketinin uygulanması (18 Eylül)
- İlk LLM planlama turunda yeni veri sorularına yalnız retrieval yüzü sunuluyor; veri/işlem sonucu alındığında gate tam tool ailesine geçiyor. Grafik/web/analitik/Architect sinyali varsa ilgili aile ilk turda korunuyor. `initial_phase` sözleşmesi yeni plugin araçlarının isim listesine dokunmadan ilk faza katılmasını sağlıyor.
- Güncel demo registry ölçümü: plain BDDK veri sorusunda ilk tur **5/14 tool**, şema karakteri **3.837/15.906**; ilk çağrı için yaklaşık %76 daha küçük native tool yüzü. İkinci fazda tam 14 araç gerektiğinde açılıyor.
- Katalog araması/şema incelemesi başarıyla bittiğinde faz geçişi artık veri sorgusunu beklemiyor; ikinci LLM turunda Gold, workspace ve analiz araçları açılıyor. `GOLD_REQUIRED` hatası da aynı geçişi tetikliyor; dönem toplaması isteyen bir soru Gold şemasını gizli tutup kilitlenemiyor.
- `ToolRegistry.schemas()` profil + seçili araç kümesi anahtarıyla şema önbellekliyor; kayıt veya profil değişince önbellek geçersizleşiyor. Aynı turdaki dönüşlerde Pydantic şeması yeniden üretilmiyor.
- Her cevapta `usage` içine `initial_tool_schemas`, `max_tool_schemas`, `phase_switches` metrikleri eklendi; UI/acceptance koşucusu log ayrıştırmadan faz etkisini ölçebilir.
- OpenAI uyumlu istemcide varsayılan provider denemesi 3 (22 Eyl: 2'ye indirilmişti, paralel MIA koşusunda 3 vaka tek zaman aşımında düştüğü için 3'e geri alındı; `LLM_MAX_RETRIES` ile ayarlanabilir). Agent soru bütçesini istemciye deadline olarak geçiriyor; her retry kalan süreye kırpılıyor, backoff deadline'ı aşmıyor. Sarmalanmış timeout RuntimeError'ları da LLM kesintisi olarak güvenli biçimde raporlanıyor.
- Aylık iç içe dönem sonuçları için tam ay kümesi denetimi güçlendirildi: açık dış pencerede eksik veya pencere dışı aylar `PERIOD_GRAIN_MISMATCH` ile aktif tabloya yazılmadan reddediliyor.
- Doğrulama: `agent-core` **789/789**, `lakehouse-core` **1126/1126** test geçti; `compileall` ve `git diff --check` başarılı. Bir Starlette deprecation uyarısı dışında hata yok. `.env` SHA-256 `3d9edab0b35a33c3c0b99c4e1dec457f54d8cc8abe03ba160ddcced59d74e516` olarak aynı kaldı.
- Sonraki ölçüm noktası: canlı sağlayıcıda aynı demo sorusunu tekrar tekrar bekletmek yerine `usage` faz sayaçları, p50/p95 süre ve gerçek provider timeout oranı ayrı raporlanacak; typed PlanSpec/SQL builder deterministikleştirmesi bir sonraki kapasite paketi.

### 2.61 MIA health-check ve embedding doğrulaması (18 Eylül)
- UI’daki “Model servisine ulaşılamıyor” metni agent’ın LLM çağrısında `Request timed out` ile oluşuyor; embedding çağrısından kaynaklanmıyor. MIA endpoint’i ve anahtar erişilebilir.
- Eski `--preflight --live` kontrolü reasoning açık modelde yalnız 5 token istediği için görünür cevap üretmeden `finish=length` alıyor ve yanlış negatif veriyordu. Health ping reasoning’i yalnız kontrol çağrısında kapatıp 32 token kullanacak şekilde düzeltildi; uygulamanın `LLM_DISABLE_THINKING=false` ayarı değişmedi.
- Düzeltme sonrası canlı preflight: `MIA canlı ✓ cevap: 'hazır' · finish=stop`.
- Aynı MIA anahtarıyla `Qwen3-Embedding-8B` endpoint’i doğrulandı: 4096 boyut, tek istek 0,49 s. `RETRIEVAL_MODE=auto` ve 4.571 sorgulanabilir seri (`hybrid_min=5000` altında) nedeniyle üretimde BM25 seçiliyor. Embedding’i timeout çözümü olarak zorlamak yerine cache’li A/B ölçümüyle devreye almak öneriliyor; ilk katalog vektörleme 4.571 seri için çoklu embedding çağrısı gerektirir.

### 2.62 Compact planner ve faz şeması daraltması (18 Eylül)
- Yeni veri sorusunun ilk LLM turunda tam sistem promptu + ön-yükleme kataloğu gönderilmiyor; 1.575 karakterlik compact planner sözleşmesi ve 5 retrieval şeması kullanılıyor. Aynı soru provider’a doğrudan testte reasoning geçici kapalıyken 7,28 saniyede doğru `lakehouse_search` çağrısı verdi; önceki yaklaşık 18 bin karakterlik yük 30 saniyelik testte timeout olmuştu.
- İlk tool planlama ve recovery çağrılarında reasoning geçici olarak kapatılıyor; doğrulanmış veri geldikten sonraki SQL/Gold/anlatım turlarında `.env` içindeki reasoning ayarı korunuyor.
- Retrieval/describe/distinct turlarında şema yüzü 5 araçta kalıyor. Yalnız `GOLD_REQUIRED` hatası Gold şemalarını açıyor; birleştirme/sütun/tablo istekleri workspace ailesini, grafik/analitik/web/Architect ise kendi sinyalini açıyor.
- Canlı uçtan uca denemede MIA’nın değişken provider gecikmesi ikinci geniş promptta yeniden timeout verdi; bu nedenle compact planner ölçümü güvenilir, provider’ın her anda cevap vereceği garanti değil. Bir sonraki sağlamlaştırma adımı, katalogdan deterministik retrieval + query planı çıkarıp ilk tool seçim LLM çağrısını tamamen opsiyonel hale getirmek.
- Doğrulama: `agent-core` **791/791**, `lakehouse-core` **1126/1126** (önceki tam koşu) geçti; `.env` değişmedi.

### 2.63 Exact demo sorusu canlı yeniden denemesi (18 Eylül)
- Güncel compact planner, fazlı tool gate ve planlama/recovery reasoning kapatma değişiklikleriyle exact demo sorusu temiz sohbette tekrar denendi. İstemci 180 saniyeye kadar bekledi; yanıt dosyası oluşmadan timeout oldu.
- Bu sonuç, testlerin ve doğrudan compact provider çağrısının başarılı olmasına rağmen sağlayıcı gecikmesinin canlı uçtan uca koşuda hâlâ değişken olduğunu gösteriyor. Sunucu ayakta kaldı; `/api/status` HTTP 200 ve `retrieval_mode=bm25`, `silver_rows=207258`, `gold_tables=7` değerleri korundu.
- Sonraki güvenilirlik paketi: soru metninden katalog facet'leri ve typed `PlanSpec` üretip retrieval/query tool çağrısını deterministik başlatmak; LLM'yi yalnız plan doğrulama ve anlatım için opsiyonel kullanmak. Böylece ilk model timeout'u veri getirme akışını bloke etmeyecek.

### 2.64 Demo soru bütçesi 600 saniye (18 Eylül)
- Kullanıcının canlı denemeyi tamamlayabilmesi için `AGENT_TIME_BUDGET_S` varsayılanı 300 saniyeden 600 saniyeye çıkarıldı (`agent-core/src/kkb_agent/config.py`). Ortam değişkeni verilirse açık değer önceliklidir.
- Tek MIA çağrısının timeout'u 90 saniye ve provider retry sayısı 2 olarak bırakıldı; yalnız toplam soru bütçesi genişletildi. `.env` değiştirilmedi.
- Servis yeni ayarla yeniden başlatıldı ve `127.0.0.1:8765` üzerinde çalışıyor. `agent-core` harness/web odak testleri **62/62** geçti; `git diff --check` başarılı.

### 2.65 Demo oturumunda reasoning kapatma (18 Eylül)
- Kullanıcının canlı ekranında 60 satırlık tablo kurulmasına rağmen son anlatım/doğrulama LLM turu `RuntimeError` ile kesildi. Demo denemesi için servis `LLM_DISABLE_THINKING=true AGENT_TIME_BUDGET_S=600` ortamıyla yeniden başlatıldı.
- Reasoning yalnız bu çalışan süreçte kapalıdır; `.env` değiştirilmedi ve SHA-256 aynı kaldı. Planlama, veri sorgusu ve son anlatım turları aynı hızlı provider ayarını kullanır.
- `/api/reset` sonrası temiz Analyst oturumu doğrulandı: retrieval `bm25`, Silver 207.258 gözlem, Gold 7 tablo.

### 2.66 Takip sorusu ve tablo önizleme düzeltmeleri (18 Eylül)
- Takip çözümleyicide zaman kolonu takma adları (`dönem`, `tarih`, `ay`) ve tek başına frekans etiketleri (`aylık`) seri adayı sayılmıyor. Ayrıca `min`/`max` eşleşmeleri kelime sınırına alındı; `döneminde` artık yanlışlıkla minimum agregasyon üretmiyor.
- Terminal tool hatasında modelin yanlış kaynağı açıklayan son paragrafı yayınlaması engellendi; doğrulanmış aktif tablo varsa takip isteği başarısızlığı deterministik ve tabloyu koruyan metinle sonuçlanıyor.
- API/UI katmanları, doğrulanmış `table` artifact'i varken modelin kısaltılmış markdown tablosunu metin bölümünde ikinci kez göstermiyor. Böylece üst metindeki eksik hücreler ile CSV/XLSX arasındaki görünür çelişki ortadan kalkıyor; canonical tablo kartı ve rapor tablosu tek gösterim oluyor.
- Gerçek exact soru yeni kodla **206,2 s**, 60 satır ve JSON tablosunda **0 boş hücre** ile tamamlandı. Resolver regresyonu ve ilgili workspace testleri geçti; agent tam paket **792/792**, statik JS `node --check`, `git diff --check` başarılı.
- Hatalı eski sohbet silindi; servis temiz Analyst oturumunda çalışıyor. `.env` SHA-256 değişmedi.
- Son doğrulama: agent-core **792/792**, web/follow-up odak testleri **19/19**, statik JavaScript syntax kontrolü ve `git diff --check` başarılı.

### 2.67 Aktif tablo dönüşümlerinin stale guard tarafından bastırılmaması (18 Eylül)
- Takip isteği aylık değişim ve ortak tarih ekseni dönüşümü için aktif 24 aylık tablo doğru olsa da son cevap, yalnız dış kaynaktan veri getiren `FRESH_DATA_TOOLS` kümesi aranarak yanlışlıkla “mevcut analiz tablosuyla uyumlu değil” metnine eziliyordu.
- `workspace_compute_column`, `workspace_query`, `workspace_join`, `workspace_add_column` ve analitik/Gold dönüşüm araçları ayrı `ACTIVE_TABLE_ACTION_TOOLS`/`TRANSFORMATION_TOOLS` sözleşmeleriyle tanımlandı. Stale guard artık geçerli aktif tablo işlemini yeni retrieval yok diye reddetmiyor; ulusal/il/frekans uyumsuzluğunda eski tabloyu kullanmama koruması sürüyor.
- “aylık değişim”, “aynı tarih ekseni”, “hizala”, “normalleştir”, “dönüşüm” gibi istekler araçsız anlatıya kaçarsa deterministik dönüşüm capability geri gönderimiyle `workspace_compute_column`/`workspace_query`/Gold aracı çağrısı isteniyor.
- Doğrulama: yeni aktif tablo regresyonu dahil agent-core **793/793** geçti; sunucu güncel kodla yeniden başlatıldı, `/api/status` ve UI HTTP 200, geçmiş temiz; `.env` SHA-256 değişmedi.

### 2.68 PR9 veri tabanının kanonik köke alınması (18 Eylül)
- Kullanıcı kararıyla veri baseline'ı `bushushow/AgentSmithler_WorkSpace` PR #9 kapsamı olarak kabul edildi. PR9 ağacında `.duckdb`, Parquet ve Bronze/RAW dosyaları Git'e alınmadığı için binary doğrudan pull edilmedi; PR9 katalogları ve kabul kapsamı kullanılarak veritabanı yeniden oluşturuldu.
- Kök `data/lakehouse.duckdb` artık PR9 kapsamıyla çalışıyor. Aktif katalog: `bddk_finturk` 4.536, `bddk_monthly` 498, `bddk_weekly` 34, `evds` 1.236; toplam **6.304 aktif seri**. Deprecated kayıtlar: BDDK aylık 76, BDDK haftalık 3, EVDS 309.
- Silver gözlemleri: FinTürk **99.792** (56 ölçüm × 81 il × 22 çeyrek), BDDK aylık **32.817**, BDDK haftalık **9.807**, EVDS **89.579**; toplam **231.995** gözlem. FinTürk zorunlu aralığı 2021-03–2026-06 arasındaki 22 çeyrek uç noktasıyla dolu; diğer kaynaklarda 2021-01–2026-06 dönemi kapsanıyor. Mevcut eski serilerin daha uzun geçmişi varsa kaynak kanıtı korunarak silinmedi.
- Yedi Gold tablosu yeniden üretildi; güncel Silver parmak iziyle eşleşiyor ve reddedilmiş metrik yok. BDDK `1536?Toplam` doğrulaması: 2022-12 **674.803**, 2023-12 **983.284** milyon TL; demo sorusundaki değerlerle uyumlu.
- PR9 anlatısındaki 232.217 gözlem sayısı yerine canlı kaynaklardan yeniden kurulan kökte 231.995 gözlem var. Fark, kaynak dönem/tekrar sınırı ve mevcut dosyalardaki gerçek gözlem bulunabilirliğinden kaynaklanıyor; eksik değer uydurulmadı. Tüm 6.304 aktif seri yüklü olduğu için bu fark veri kapsamının eksik olduğu anlamına gelmiyor.
- Eski kök verisi geri dönüş için `data/lakehouse_pre_pr9_20260918.duckdb` ve `data/bronze_pre_pr9_20260918/` altında saklandı. `.env` SHA-256 değişmeden `3d9edab0b35a33c3c0b99c4e1dec457f54d8cc8abe03ba160ddcced59d74e516` kaldı.
- Hedefli doğrulama testleri: `tests/catalog tests/parsers tests/silver tests/gold` **393 geçti**; tam yeniden oluşturma sırasında Bronze 16.812 dosya olarak köke alındı. Servis güncel kök DB ile `127.0.0.1:8765` üzerinde yeniden başlatıldı; `/api/status` HTTP 200, Silver 231.995 ve Gold 7 görünüyor.

### 2.69 Büyük katalogda soğuk embedding ve parent–child retrieval düzeltmesi (18 Eylül)
- 6.311 seriyle aynı demo sorusunun ölçümü: toplam **345,7 s**; ilk `lakehouse_search` adımı **218,2 s** sürdü. Sebep DuckDB değil, katalog önbelleği eşleşmediği için 64'lük yaklaşık 99 uzak embedding isteğinin interaktif soruda senkron çalışmasıydı. Aynı Silver SQL'i doğrudan **0,15 s** sürdü.
- Retriever artık 1.000'den büyük soğuk katalogda embedding migration'ı başlatmıyor; tam embedding önbelleği yoksa açık durum iziyle BM25'e düşüyor. Küçük kataloglar ve açık warm-up yolu mevcut hibrit davranışı koruyor.
- Çok kavramlı sorular artık özgün cümleye ek olarak `ve/ile/veya` ve noktalama ile ayrılan kavram parçalarıyla aranıyor. Sert kaynak/frekans/coğrafya yüzleri clause havuzundan önce uygulanıyor; böylece tekrar eden il-alt seri ailesi ulusal parent seriyi aday havuzundan silemiyor.
- Dönem çözümleyici, yalnızca anchor aralığını ve istenen dış pencereyi tek başına taşıyabilen serilerin kapsamını ortaklaştırıyor. İlgisiz, geç başlayan bir aylık seri 60 aylık pencereyi artık yok edemiyor.
- Güncel kodla aynı soru temiz oturumda **62,6 s**, 60 satır/5 kolon ve 0 başarısız araç çağrısıyla tamamlandı. Adımlar: arama 10,1 s, üç describe toplam 12,0 s, sorgu turu 22,9 s, anlatım 14,3 s; kalan süre model turlarının sağlayıcı gecikmesi.
- Bu gözlem parent–child semantiğinin yalnız isimlerden modele bırakılmaması gerektiğini doğruladı. Kalıcı çözüm için sonraki veri sözleşmesi: `concept_id`, `parent_series_id`, `relation_type`, `dimension_path`, `additivity`, `semantic_confidence` ve kanıt artifact'iyle `meta.series_relation`; geniş kavramda parent varsayılan, alt kalem isteğinde child, toplama yalnız `additivity=additive` kanıtlıysa yapılacak.
- BDDK örneği: `1539` bireysel kredi kartları toplamı; `1541` taksitli ve `1542` taksitsiz alt kalemler. Kullanıcı geniş kavramı sorduğunda parent seçilmeli; alt kırılım istenirse üçü birlikte gösterilmeli ve parent = child toplamı deterministik uzlaştırılmalıdır.
- Doğrulama: retrieval/period/agent odak testleri **53 geçti**; `LLM_DISABLE_THINKING=true AGENT_TIME_BUDGET_S=600` ile servis yeniden başlatıldı ve `/api/reset` sonrası temiz Analyst oturumu hazır.

### 2.70 `meta.series_relation` ortak ilişki katmanı (18 Eylül)
- Kaynak parserlarının ürettiği `series_id` kimliği korunarak, BDDK aylık/haftalık, FinTürk ve EVDS serilerini tek bir source-independent ilişki modeline bağlayan `meta.series_relation` tablosu eklendi. Parser gözlemlerinin fiziksel sözleşmesi değişmedi; ilişki, katalog yükleme/migration aşamasında aynı kimlikler üzerinde üretiliyor.
- Ortak kayıt alanları: `concept_id`, `parent_series_id`, `relation_type`, `dimension_path`, `additivity`, `relation_confidence`, `relation_source`, `relation_content_sha256`. Bilinmeyen ilişki tahmin edilmiyor ve `standalone` olarak kalıyor.
- BDDK item-tree eşlemeleri parent/child olarak; FinTürk il boyutu `dimension_member`; EVDS bölge boyutu `dimension_path` olarak kaydediliyor. Üretim kökünde **6.304** aktif seri için relation satırı oluşturuldu: `dimension_member=5.587`, `child_breakdown=192`, `parent_total=16`, `standalone=509`.
- Silver adaptörü relation satırlarını `DatasetSpec` ve retriever `CatalogRecord` içine taşıyor. Geniş kavram sorgusu doğrulanmış parent'ı öne alıyor; açık child/breakdown sorgusu doğrudan child'ları genişletiyor. Açıkça adlandırılmış bir child boyutunda ilgisiz sibling yeniden eklenmiyor.
- Migration komutu: `cd lakehouse-core && uv run python scripts/sync_series_relations.py ../data/lakehouse.duckdb`. Bootstrap yolu `005_series_relation.sql` ile aynı tabloyu otomatik oluşturuyor; eski relation'sız DuckDB'ler adaptör tarafında geriye dönük varsayılanlarla okunabiliyor.
- Doğrulama: relation/catalog/integration/infrastructure odak paketi **79 geçti** (EVDS ortak dataset bölge regresyonu dahil); agent-core tam paket **795 geçti**; lakehouse-core tam suite yeniden üretim ağırlıklı olduğu için 14:28'de **148 test geçtikten sonra** manuel demo hazırlığını bloklamaması için durduruldu. `.env` değişmedi.

### 2.71 Relation katmanı sonrası demo hazır (18 Eylül)
- `data/lakehouse.duckdb` relation migration'ı son kodla tekrar çalıştırıldı ve 6.304 relation satırı doğrulandı.
- Güncel servis `LLM_DISABLE_THINKING=true AGENT_TIME_BUDGET_S=600` ile `127.0.0.1:8765` üzerinde çalışıyor. `/` ve `/api/status` HTTP 200; status'ta katalog 6.304, yüklenmiş seri 6.304, Silver 231.995 gözlem ve Gold 7 görünüyor.
- `.env` SHA-256: `3d9edab0b35a33c3c0b99c4e1dec457f54d8cc8abe03ba160ddcced59d74e516`.

### 2.72 Gold dönem filtresinde anchor daralması düzeltmesi (18 Eylül)
- Canlı ekran incelemesinde otomatik dış pencere metni 60 ayı gösterirken aktif Gold tablosu modelin `period_from=2022-01`, `period_to=2023-12` argümanlarıyla 24 satıra daralıyordu. `lakehouse_query` grain guard'ı bunu kapsamadı çünkü sonuç `gold_align/gold_join` üzerinden kurulmuştu.
- `_GoldTool` artık aktif resolved question içindeki canonical dış aylık pencereyi (`outer_bounds_explicit`) okuyor ve modelin yalnız anchor yıllarını verdiği Gold filtrelerini bu pencereyle tutarlı biçimde uyguluyor. Böylece seçilen 60 ay aktif tabloya 60 satır olarak geçiyor; kullanıcı sorusuna özel fixture eklenmedi.
- Yeni regresyon: `test_gold_ambiguous_anchor_donemini_ust_pencereye_tasiyor`; Gold/lakehouse/retrieval/agent odak paketi **89 geçti**. Exact kullanıcı sorusu test kaynağına eklenmedi ve önceki kalıcı sohbet `/api/reset` ile temizlendi.
- Servis güncel kodla `127.0.0.1:8765` üzerinde çalışıyor; katalog 6.304, Silver 231.995, Gold 7, sohbet geçmişi boş.

### 2.73 PR9 artifact provenance backfill ve kanıt zinciri onarımı (18 Eylül)
- UI kanıt yolculuğunda BDDK aylık sonuçları `Kaynak URL / adres kaydı yok` ile kırılıyordu. İncelemede sayısal veri, RAW JSON ve Bronze Parquet dosyaları mevcutken PR9 kök veritabanında BDDK aylık **498**, BDDK haftalık **34**, FinTürk **110** ve EVDS **35** `meta.artifact` satırının eksik olduğu bulundu. Bu bir localhost çökmesi değildi: aynı sırada `/`, `/api/status`, `/api/answers` ve `/api/ask/stream` uçları HTTP 200 dönüyordu.
- `lakehouse-core/scripts/repair_artifact_metadata.py` eklendi. Script yalnız Silver'daki gerçek artifact SHA/fetched_at, mevcut content-addressed RAW dosyasının boyutu/yolu ve `meta.series.metadata_url` üzerinden eksik kayıtları tamamlar; indirme yapmaz ve timestamp uydurmaz. `meta.artifact_request` satırları da aynı kaynak açıklamasıyla yazılır. Aynı SHA için FinTürk'teki 81 il serisi tek source-level artifact olarak deterministik temsil edilir; Silver gözlem eşlemesi değişmez.
- Canlı backfill sonucu: **677** `meta.artifact` ve **677** request-provenance satırı eklendi; eksik RAW **0**, eksik locator **0**. Silver → `meta.artifact` eşleşmesi BDDK aylık 498/498, haftalık 34/34, FinTürk 110/110, EVDS 7.354/7.354 oldu. Önceki DB `data/lakehouse_pre_artifact_repair_20260918.duckdb` olarak saklandı.
- Adaptör doğrulaması: BDDK ihtiyaç kredisi gözlemi `locator=https://www.bddk.org.tr/BultenAylik`, `raw_present=true`, `bronze_present=true`, `raw_digest_ok=true`, `complete=true`, `chain_state='tam'` döndü. Böylece kanıt panelindeki URL halkası gerçek kaynak URL'siyle yeşile dönebilecek.
- Servis `LLM_DISABLE_THINKING=true AGENT_TIME_BUDGET_S=600` ile yeniden başlatıldı; `/api/status` HTTP 200, katalog 6.304, Silver 231.995, Gold 7. `/api/reset` sonrası manuel test geçmişi boş temiz Analyst oturumu hazır. `.env` SHA-256 değişmedi.

### 2.74 Uzun çıktı ve dönüşüm dışa aktarımı düzeltmesi (18 Eylül)
- Son manuel takip cevabında model 24×7 dönüşüm tablosunu araçla üretmiş ve son `workspace_show` ile doğrulamıştı; ancak dışa aktarım seçicisi önceki 24×3 `workspace_query` snapshot'ını seçtiği için CSV/XLSX yalnız bakiyeleri içeriyordu. `project_result_table` artık sorguyu dönüşümden önceki ara girdi olarak ayırıyor; dönüşümden sonra gelen sorguyu son projeksiyon, son `workspace_show` snapshot'ını ise tam cevap artifact'i olarak seçiyor.
- Markdown tablo ayırıcısı `---:`, `:---` ve `:---:` hizalama biçimlerini tanıyacak şekilde düzeltildi. Yapılandırılmış tablo artifact'i varken modelin uzun Markdown tablosu anlatıda tekrar edilmiyor; böylece önizleme ile indirme arasında kolon çelişkisi oluşmuyor.
- Varsayılan `LLM_MAX_TOKENS` **1500 → 4000** yapıldı; `.env` değeri varsa önceliği sürüyor. Sistem promptu tam tablonun UI/CSV/XLSX artifact'inde bulunduğunu, nihai anlatının uzun satır satır Markdown tabloyu kopyalamaması gerektiğini söylüyor. Bu hem 24/60 aylık çıktılarda `finish_reason=length` riskini azaltıyor hem de doğrulanmış tabloyu koruyor.
- Yeni dönüşüm→`workspace_show`→dışa aktarım regresyon testi eklendi. Projection/web/follow-up odak paketi **26 geçti**; `py_compile`, `git diff --check` başarılı. Servis `LLM_DISABLE_THINKING=true AGENT_TIME_BUDGET_S=600 LLM_MAX_TOKENS=4000` ile yeniden başlatıldı; `/api/reset` sonrası geçmiş boş, `/api/status` HTTP 200. `.env` SHA-256 değişmedi.

### 2.75 Çağrı türüne göre dinamik token bütçesi (18 Eylül)
- Global `LLM_MAX_TOKENS=4000` artık her çağrının hedefi değil, geriye dönük uyumluluk üst sınırı olarak kullanılıyor. `TokenBudgetPolicy` katalog/ilk araç seçimi (`planning=1000`), dönüşüm veya özel araç argümanı (`tool=1800`), normal anlatı (`narration=2800`), 48+ satır veya 6+ kolonlu uzun anlatı (`long_narration=3400`) ve kurtarma/adım sınırı (`recovery=1400`) fazlarını seçiyor. Her değer global tavanla kırpılıyor.
- `AnalyticsAgent` eski doğrudan kullanımını koruyor: `token_budget_policy` verilmezse testlerdeki ve gömülü kullanımlardaki sabit `max_tokens` davranışı değişmiyor. CLI sunucusu politikayı ayarlardan kuruyor. Çağrıların seçilen fazı ve uygulanan tavanı `usage.token_budget_calls` izinde yayınlanıyor; `finish_reason=length` yalnız kullanıcıya görünen anlatı/kurtarma fazlarında kesinti sayılıyor.
- Ayarlanabilir ortam değişkenleri: `LLM_PLAN_MAX_TOKENS`, `LLM_TOOL_MAX_TOKENS`, `LLM_NARRATE_MAX_TOKENS`, `LLM_LONG_NARRATE_MAX_TOKENS`, `LLM_RECOVERY_MAX_TOKENS`. `.env` değiştirilmedi; canlı süreç `LLM_DISABLE_THINKING=true AGENT_TIME_BUDGET_S=600 LLM_MAX_TOKENS=4000` ile yeni koddan yeniden başlatıldı, `/api/reset` sonrası geçmiş temiz.
- Doğrulama: dinamik politika dahil `agent-core` **800 geçti**, `py_compile` ve önceki statik kontroller başarılı. Canlı `/api/status`: katalog **6.304**, Silver **231.995**, Gold **7**, `retrieval_mode=hybrid`, Analyst profili; servis `127.0.0.1:8765` üzerinde HTTP 200.

### 2.76 PR CI ve çalışma ağacı temizliği (18 Eylül)
- GitHub Actions kotası yeniden kullanılabilir olduğu için `.github/workflows/tests-agent.yml` ve `tests-lakehouse.yml` içindeki `pull_request` tetikleri yeniden açıldı; `workflow_dispatch` da korunuyor. `docs/PR_ONCESI_TEST.md` artık eski “Actions yok” prosedürü yerine CI komutlarını ve yerel doğrulama durumunu belgeliyor.
- PR kapsamından `.claude/` ve `docs/experiments/` altındaki yerel UI/benchmark artefaktları dışarıda tutulacak; çalışma ağacında bırakıldılar, silinmediler. PR9 kapsamındaki 4.536 aktif FinTürk serisini taşıyan katalog değişikliği kaynak katalog olarak dahil edilecek.
- Exact demo sorusu fixture'dan çıkarıldı; Gold anchor testi sentetik bir soru ifadesi kullanıyor. `test_gold_tools.py` **16 geçti**.
- CI ile aynı agent komutu `uv run --frozen --extra dev pytest -q -p no:cacheprovider`: **801 geçti**, 1 uyarı, 6,71 s. Lakehouse hızlı hedefli kapsam **55 geçti**, 142,58 s. 6.304 serilik tam lakehouse paketi yerelde katalog bootstrap maliyeti nedeniyle yaklaşık 14 dakika sonra %6 ilerlemede durduruldu; assertion hatası görülmedi ve tam sonuç PR Actions job'ına bırakıldı.

### 2.77 PR #18 main conflict çözümü (18 Eylül)
- `origin/main` PR #9 sonrası `14740e6` seviyesine ilerlediği için `feature/agent-engine` ile merge sırasında beş dosya conflict verdi: iki Actions workflow'u, `docs/PR_ONCESI_TEST.md`, `bddk_finturk.yml` ve `scripts/ingestion_registry.py`.
- Çözümde PR #9'un 4.536 serilik FinTürk kataloğu, BDDK aylık/haftalık geniş katalogları ve üç paralel lakehouse Actions shard'ı kanonik kabul edildi. `ingestion_registry.py`, PR9'un tablo eşleme/haftalık pozisyon JSON'larını korurken gelecekteki `<tabloNo>|<SEHIR>` bulk adreslerini de destekliyor.
- PR9 katalog dataset kimlikleriyle uyum için `tests/silver/test_build.py` FinTürk fixture'ı `bddk_finturk_yalova_housing_loans` dataset kimliğine güncellendi; veri veya fixture kimliği uydurulmadı.
- Conflict sonrası doğrulama: `agent-core` tam paket **802 geçti**, 1 deprecation uyarısı, **6,77 s**; lakehouse hedefli kapsam **131 geçti**, **261,69 s**; `git diff --check` başarılı. Tam lakehouse paketi üç paralel Actions shard'ında merge kapısı olarak çalışacak.
- Merge commit'i henüz oluşturulup push edilmedi; çalışma ağacında yalnız `.claude/` ve `docs/experiments/` kapsam dışı yerel artefaktlar untracked tutuluyor. `.env` değişmedi.

### 2.78 PR #19'dan seçili performans ve güvenilirlik katmanlarının alınması (18 Eylül)
- Elif Sena'nın main'e merge edilen PR #19'undan yalnız üç genel katkı `feature/agent-engine` dalına uyarlandı: doğrulanmış aktif workspace için LLM'siz `period_change`/`percent_change` fast path, katalog/workspace kolonlarında karmaşık SQL identifier'larını güvenli tırnaklayan normalizer ve çoklu türetilmiş kolonların cevap/CSV/XLSX projeksiyonu.
- Fast path yalnız mevcut tablo, provenance, tarih ekseni, grup anahtarı, frekans ve takip sorusu kapsamı çakışmadığında devreye girer; hesap pandas ile deterministik yapılır, ilk LAG boşluğu/sıfır taban korunur, satır-sıra-hesap doğrulanır ve atomik `add_columns` geçmişi yazılır. Yeni kaynak, tarih aralığı, metrik veya coğrafya seçimi normal LLM/araç akışına bırakılır.
- `validator` artık isteğe bağlı `normalize_args` kancası çalıştırıyor; `lakehouse_query` ve `workspace_query` kolon adlarını SQL literal/yorumlarına dokunmadan normalleştiriyor. Böylece `bddk_monthly:...@...::value` gibi serbest katalog kimlikleri modelden doğru quoting beklemeden sorgulanabiliyor.
- PR19'un eski 14740e6 tabanından kör cherry-pick yapılmadı; mevcut PR18 katalog/Gold/token/period değişiklikleri korunarak üç commit (`9526377`, `cfad86f`, `cadf2e6`) ve test uyarlaması (`a6aa7e8`) oluşturuldu. Ortak dosya çakışmaları (`agent.py`, `follow_up.py`, `lakehouse.py`, `web_app.py`) çözüldü; `.env`, `.claude/` ve `docs/experiments/` değiştirilmedi.
- Doğrulama: yeni fast path/identifier/projection/follow-up hedef paketi **36 geçti**; agent-core tam paket **817 geçti**, 1 Starlette deprecation uyarısı; `compileall` ve `git diff --check` başarılı. Lakehouse kodu değiştirilmedi. PR19'un güncel main commit'i `b84c160` ayrıca branch'e merge edilerek PR18 yeniden `MERGEABLE` duruma getirildi (`2aa4ec2`); GitHub Actions yeniden kuyruğa alındı.

### 2.79 60 aylık soru ve takip dönüşümü gözlemi (18 Eylül)
- Kullanıcı dışa aktarımı `/Users/baran/Downloads/agent-smith-cevap-1.csv` incelendi: takip tablosu **24 satır × 19 sütun** ve istenen 1536 İhtiyaç + 1539 Bireysel Kredi Kartı yerine 1534 Konut + 1536 İhtiyaç serilerini içeriyor.
- Ek sütunların kaynağı veri hatası değil: `gold_join` kanıt/provenance alanlarını (`quality_flag`, `observations`, `missing_observations`, kaynak tarihleri, artifact SHA listeleri, contributing/absent series, completeness) aktif workspace'e taşıyor; dışa aktarım bunları şu anda tam tabloyla birlikte yayınlıyor. İki `workspace_compute_column` çağrısı da `konut_aylik_degisim` ve `ihtiyac_aylik_degisim` ekledi.
- Takipte `202201–202312` çözümlemesi doğru şekilde **24 ay** olarak tanındı; güvenli fast path explicit tarih override'ını bilerek reddettiği için model yeni retrieval yaptı. Belirsiz “tüm serileri” ifadesi aramada 1534+1536 seçimine yol açtı; ilk aktif tablonun 1536+1539 serilerini koruyan dönem filtreli deterministik yol henüz yok.
- Son oturumun ilk cevabı **444,7 s** sürdü. Lakehouse sorgusu yalnız **37,1 s**; kalan süre grounding başarısızlığı (121,1 s), 60 satırlık `workspace_show` (96,3 s) ve tekrar anlatım (165,4 s) kaynaklı. Önceki koşuda aynı sorgu 162,7 s idi; bu fark veritabanı değil model doğrulama/yanıt yolu ve `LLM_DISABLE_THINKING=false` ile anlatı çağrılarında reasoning açık olmasından kaynaklanıyor.
- Kalıcı çözüm adayı: yalnız explicit aylık tarih aralığı aktif tablonun kapsadığı aylar içindeyse, aktif serileri ve provenance'ı koruyarak yerel satır filtresi + LAG dönüşümünü fast path'e almak; kullanıcıya dönük CSV/XLSX için kanıt kolonlarını ayrı metadata sayfasına ayırmak. Bu değişiklik uygulanmadı; mevcut gözlem teşhis amaçlıdır.

### 2.80 Takip aralığı fast path ve temiz kullanıcı projection'ı (18 Eylül)
- Explicit aylık `YYYYMM–YYYYMM` takip aralığı artık önceki aktif tablonun seri kimliklerini koruyarak doğrulanmış workspace fast path'e girebilir. Yeni kaynak/seri/metrik/coğrafya değişikliği hâlâ normal retrieval yoluna düşer.
- Somut ay aralığı takip bağlamında otomatik `comparison_target` oluşturmaz; yıl düzeyindeki kısa karşılaştırma davranışı korunur. Böylece “202201–202312” isteği model tarafından iki aralık karşılaştırması sanılmaz.
- Dönemsel değişim önce aktif tam tablo üzerinde LAG ile hesaplanır; ardından istenen aylık aralığa filtrelenir. Önceki ay aktif tabloda varsa ilk çıktı ayının farkı da hesaplanır; yoksa yalnız ilk değer boş kalır. Eksik istenen aylar varsa fast path güvenli biçimde devreye girmez.
- Provenance kolonları grup veya ölçü olarak kullanılmaz. Dışa aktarım projection'ı `series_id`, `quality_flag`, birim/ölçüm metadata'sı, artifact listeleri, Gold build alanları, `contributing_series`, `is_complete_period` gibi kanıt yardımcılarını kullanıcı tablosundan ayırır; `tüm sütunları göster` isteği bu korumayı bilinçli olarak kaldırır. `period_end` varken teknik `period_start` tek tarih ekseninden çıkarılır. Boolean completeness kolonları da ölçü sayılmaz.
- Structured table anlatı kuralı güçlendirildi: model satır satır Markdown tablo/provenance tekrarlamaz, en fazla üç kısa paragraf veya altı madde yazar; tam içerik UI/CSV/XLSX artifact'inde kalır.
- Yeni regresyonlar: 60 aylık aktif tabloda explicit aralık + LAG tabanı, LLM'siz seri koruması, Gold provenance projection'ı. Gerçek `gold.tuketici_kredisi_kirilimi_aylik` tablosuyla smoke testte 60 → 24 satır ve Ocak 2022 değişimi Aralık 2021 tabanıyla doğrulandı. Agent-core tam suite **825 geçti**, 1 Starlette deprecation uyarısı; `compileall` ve `git diff --check` başarılı.

### 2.81 Demo soru metinlerinin testlerden ayrıştırılması (18 Eylül)
- İki demo sorusunun tam metni tracked kod, test ve dokümantasyon içinde tutulmuyor. Regresyon testleri aynı period/follow-up davranışını nötr sentetik ifadelerle doğruluyor; böylece test kapsamı korunurken demo promptu fixture'a sızmıyor.
- `data/conversations/` altındaki eski çalışma zamanı cevapları tarihsel oturum kaydıdır ve kod/fixture olarak yüklenmez; bu arşivde geçmiş kullanıcı promptlarının bulunması uygulama davranışını etkilemez.
- Doğrulama: `git grep` ile iki tam metin için sonuç yok; workspace fast-path ve follow-up hedef paketi **27 geçti**.

### 2.82 LLM anlatı kesintisi sonrası takip bağlamı kaybı (19 Eylül)
- Canlı oturumda ilk 60 aylık sorgunun veri tablosu kurulmuş, ancak son anlatı LLM zaman aşımıyla kesilmiş. `ask()` kesinti yakalayıcısı tabloyu koruyor fakat başarısız turdaki başarılı araç adımlarını `AgentAnswer.steps` içine taşımadığı için `_complete_follow_up()` semantik bağlamı commit etmiyor.
- Sonraki aylık takip bu nedenle aktif tabloyu görmesine rağmen `FollowUpContext` boş kaldı; resolver `series` alanını belirsiz işaretledi, fast path güvenlik gereği kapandı ve model yeni, ilgisiz BDDK bilanço/rasyoları aradı. Gold doğrulaması `UNVERIFIED_SEMANTICS` ile reddedildi. Bu veri bozulması değil, kısmi başarı sonrası bağlam commit eksikliğidir.
- Düzeltme uygulandı: `_ask` içindeki in-flight araç adımları anlatı kesintisi yakalayıcısına taşınıyor. Başarılı veri adımı korunuyorsa `_complete_follow_up()` semantik bağlamı commit ediyor; yalnız anlatı adımı başarısız olarak ekleniyor. Böylece tablo orphan kalmıyor ve yanlış katalog araması yapılmıyor.
- Yeni regresyon: “query başarılı + narration timeout → aynı seri üzerinde aylık takip” senaryosu 24 satır, LAG tabanı ve **0** yeni LLM/sorgu çağrısıyla doğrulandı. İlgili takip/agent/workspace/projection paketi **75**, agent-core tam suite **826** geçti; `compileall` ve `git diff --check` başarılı.

### 2.83 Demo sorularından bağımsız benchmark prompt seti (19 Eylül)
- Takım paylaşımı için `docs/benchmark/TEST_PROMPTLARI_V1.md` oluşturuldu. Dosyada önceki iki demo sorusunun tam metni yok; 10 aile altında **72** yeni vaka bulunuyor: dönem/niyet, katalog-parent-child, dönüşüm, çoklu join, takip konuşmaları, harici CSV/XLSX/URL, kalite/geri çekilme, görülmemiş şema, büyük çıktı/performance ve adversarial istekler.
- Her vaka için ölçüm amacı veriliyor; beklenen serbest metin cevabı verilmedi. Başarı kriteri tablo/artifact/provenance/araç izi ve gecikme metrikleri olarak tanımlandı. Harici kaynaklarda URL, erişim zamanı, response SHA-256 ve data-drift ayrımı zorunlu tutuldu.
- İlk paylaşım turunda takım arkadaşları aynı promptları bağımsız çalıştıracak. Sonuçlar daha sonra yapılandırılmış vaka manifesti ve koşucuya dönüştürülecek; eski iki demo sorusu yalnız ayrı regresyon kontrolü olarak kalacak.

### 2.84 Yeni GPT sohbeti için proje brifingi (19 Eylül)
- `docs/PROJECT_BRIEF_FOR_NEW_GPT.md` eklendi. Sıfır bir sohbeti projeye hazırlamak için amaç, RAW/Bronze/Silver/Gold/Meta akışı, aktif veri kapsamı, Analyst/Architect sınırı, token politikası, kanıt zinciri, jeneriklik kuralları ve 72 vakalı benchmark dosyasına bağlantı tek bir kopyala-yapıştır metninde toplandı.
- Brifing, projeyi yalnız BDDK kredi sorularından ibaret göstermiyor; finans dışı şema, harici URL/CSV/XLSX ve provenance/data-drift davranışlarını da benchmark bağlamına dahil ediyor.

### 2.85 V2 benchmark'ın sabitlenmesi (19 Eylül)
- Kullanıcı tarafından oluşturulan kök `TEST_PROMPTLARI_v2.md` incelendi ve paylaşılabilir/izlenebilir konuma `docs/benchmark/TEST_PROMPTLARI_V2.md` olarak taşındı. V1'in 72 vakası korunuyor; D (anomali/change detection), C (correlation/causality), W (web), I (ingestion yaşam döngüsü), O (output/grafik parity) ve S (bileşik stress) aileleriyle toplam **120 benzersiz vaka** var.
- İki eski demo sorusunun tam metni V2'de yok; `python3` ile başlık kimliklerinde tekrar ve tam prompt sızıntısı kontrol edildi, `git diff --check` başarılı.
- V2, prompt protokolü olarak benchmark'ın sabit kanonik sürümü kabul edildi. İnceleme sırasında implicit “ekli dosya” ve canlı web bağımlılıkları da açık placeholder/`external_mode` alanına alındı: **36** fixture/snapshot vakası, **6** canlı web vakası. Bunlar sağlanmadan bütün vakalar çalıştırılabilir değildir; cevap üretimi yerel referanslar ve harici snapshot'lar olarak ayrılacak.
- Markdown vakaları koşucuya bağlamak için `tests/benchmark/prompts_v2.jsonl` oluşturuldu: 120 vaka, F ailesinde `turns`, harici vakalarda `placeholders`, ölçüm notları ve difficulty alanları korunuyor.
- Cevapların serbest model metni olarak değil kaynak-doğrulanmış tablo/artifact + provenance + kısa grounded özet olarak üretilmesi kararı `docs/benchmark/ANSWER_KEY_V2_STATUS.md` ile belgelendi. Fixture/snapshot manifesti olmadan 36 fixture vakasında ve 6 canlı web vakasında sayı uydurulmayacak; 78 vaka mevcut lakehouse veya güvenlik/politika akışıyla çalıştırılabilir.

### 2.86 V2 bağımsız yerel referansların ilk üretimi (19 Eylül)
- `data/lakehouse.duckdb` doğrudan DuckDB ile sorgulanarak `docs/benchmark/reference/` altında P01, P02, P03, P06, R01, T01, T03, T05 ve T06 için CSV referans artifact'leri oluşturuldu. P03 için politika: 2023 yazını içeren en erken geçerli 36 aylık pencere (2021-07–2024-06); R01 parent/child residual toleransı ±1 milyon TL; T06'da haftalık konut faizi aylık ortalamaya indirilip bakiye/TÜFE dönüşümleri ayrı tutuldu.
- Referans indeksinde mevcut veriyle sayı üretmemesi gereken durumlar kaydedildi: R03'te reel efektif kur eşleşmesi yok; P05 haftalık doğrulanmış oran yerine tutar/stok serileri içeriyor; T02/T07 ölçüm semantiği uyuşmazlığında netleştirme gerekir.
- Tüm 120 vakanın üretim durumları `tests/benchmark/reference_status_v2.jsonl` dosyasına yazıldı. 9 doğrudan CSV referansı hazır; 78 yerel/politika vaka beklentisi `docs/benchmark/reference/LOCAL_CASE_EXPECTATIONS.md` içinde; harici/fixture vakalarında sayı uydurulmayacak, URL snapshot ve dosya hash'leri geldiğinde kalan referanslar tamamlanacak.
- Yeni GPT brifingi V1 bağlantısından V2'ye güncellendi. V1 dosyası tarihsel karşılaştırma için korunuyor.

### 2.87 V2 yerel cevap paketinin genişletilmesi (19 Eylül)
- V2 manifestinde implicit “ekli CSV/dosya” bağımlılığı olan J03 ve J04 açık placeholder'lara çevrildi. Güncel sayım: **120 vaka; 38 fixture/snapshot, 6 canlı web, 76 yerel/politika**. Bu nedenle önceki 27/36 sayımları tarihsel ara durum olarak kaldı; karşılaştırmada güncel manifest esas alınacak.
- `docs/benchmark/answers_v2_local.jsonl` ve okunabilir `docs/benchmark/ANSWER_KEY_V2_LOCAL.md` oluşturuldu. Bunlar 76 yerel/politika vaka için agenttan bağımsız cevap katmanıdır: doğrudan DuckDB’den üretilen sayısal artifact veya ölçüm/kapsam belirsizliğinde beklenen netleştirme/güvenli geri çekilme cevabı.
- Sayısal referanslar 24 artifact'e genişletildi: R02 katalog adayları, R04 FinTürk il ortalamaları, R05 Mortgage aliası, R06 BDDK+TÜFE, F02/F04/F07 takip tabloları, L01/L02/L05 büyük çıktılar, D05 change-point ve S03 backward as-of join dahil. Artifactler [`docs/benchmark/reference/INDEX.md`](docs/benchmark/reference/INDEX.md) ve makine manifesti [`tests/benchmark/reference_status_v2.jsonl`](tests/benchmark/reference_status_v2.jsonl) ile izlenebilir.
- Harici fixture veya canlı URL gelmeden bu vakalarda sayı üretilmeyecek; kullanıcı CSV/URL girdilerini verdiğinde aynı JSONL/artifact/provenance formatıyla ayrı snapshot cevapları eklenecek. `git diff --check` başarılı.
- Harici ID ve placeholder envanteri [`docs/benchmark/EXTERNAL_INPUTS_PENDING_V2.md`](docs/benchmark/EXTERNAL_INPUTS_PENDING_V2.md) içine çıkarıldı; ekip 27'lik eski ara sayıyı değil güncel manifestteki 38 fixture + 6 canlı web kapsamını kullanacak.

### 2.88 Yanıt sürerken sohbet geçişinin sessizce engellenmesi (19 Eylül)
- Frontend `switchConversation()` geçişi, `btn-ask` disabled durumdaysa reddediyor. Yanıt devam ederken bu düğme disabled ediliyor; fakat sol sohbet satırları disabled görünmediğinden tıklama çalışmıyor gibi algılanıyor. Akış tamamlanınca düğme `finally` içinde yeniden etkinleşiyor.
- Backend'de `Session.ask()` ve `open_conversation()` aynı session kilidini kullanıyor; başka sekmede süren yanıt, sohbet açma isteğini de bekletebilir.
- Bu turda kod değiştirilmedi. Sorun tekrar ederse önce yanıtın tamamlanıp `Sor` düğmesinin etkinleştiği doğrulanmalı. Kalıcı UX iyileştirmesi: geçişin neden engellendiğini görünür kılmak veya oturum/iptal yönetimini konuşma bazında ayırmak.

### 2.89 Aynı soru için 28 sn / 120,8 sn gecikme karşılaştırması (19 Eylül)
- 2024 bireysel kredi kartı bakiyesi sorusunun iki gerçek konuşma izi karşılaştırıldı. İki çalıştırmada da `lakehouse_query` SQL'i ve 12 satırlık tablo aynı; profil Analyst, narration token üst sınırı 2.800.
- 120,8 sn koşu: `lakehouse_search` 7,0 sn + `lakehouse_describe` 6,5 sn + SQL 20,1 sn + narration 85,4 sn; toplam 4 LLM çağrısı, 781 completion token. 28,0 sn koşu: aynı SQL 7,8 sn + narration 17,7 sn; toplam 2 LLM çağrısı, 405 completion token. Hızlı iz önceden yüklenmiş katalog bağlamında doğrudan sorguya geçmiş.
- Gecikme farkı yalnız token tavanından kaynaklanmıyor: faz bütçeleri aynı, ama LLM servis/narration ve SQL süreleri değişken; yavaş koşuda ayrıca arama/tanımlama yapılmış. Ölçüm, kullanıcı metriklerinin yanında faz/araç bazlı p50-p95 gecikme ile provider bekleme ve üretim süresinin ayrı kaydedilmesi gerektiğini gösteriyor.

### 2.90 Başarılı tablodan sonra anlatım zaman aşımı için dayanıklı kapanış (19 Eylül)
- Gerçek KOBİ kredisi vakasının 209,8 sn izinde SQL başarılı olmuş ve 24 satırlık aktif tablo oluşmuş; yalnız son anlatım LLM çağrısı `LLM_UNAVAILABLE` ile bitmiş. Eski hata metni, hazır tabloya rağmen tüm soruyu başarısız gösteriyordu.
- Harness artık yalnız bu turda başarılı araçtan gelen ve aktif tabloyla birebir aynı olan veri çerçevesini doğrulanmış sayıyor. Böyle bir durumda kullanıcıya tablo/CSV/XLSX'in hazır olduğunu söyleyen kısa deterministik kapanış veriliyor; uydurma analiz veya sayı eklenmiyor. Veri yoksa eski erişilememe hatası korunuyor.
- Başarısız LLM çağrısının fazı/süresi `usage.failed_llm_calls` ve `usage.failed_llm_call_ms` ile izleniyor; narrator trace adımına gerçek süre yazılıyor.
- Regresyon testinde 60 satırlık doğrulanmış tablo API payload'ında kaldı, takip bağlamı commit edildi ve narrator hatası kullanıcıya bütün yanıtın başarısız olduğu şeklinde sunulmadı. Agent-core suite: **826 geçti**, 1 Starlette deprecation uyarısı; `git diff --check` başarılı.

### 2.91 Salt tablo yanıtını anlatım çağrısından ayırma (19 Eylül)
- 12:10 ekranındaki 332,2 sn koşuda veri tablosu hazırdı; yine de model sonrasında ek `workspace_query` örneklemesi ve uzun anlatım üretimine gitti. Bu iki adım doğrudan veri-getirme isteği için gereksizdi; narration sağlayıcısı hata verince eski yanıt tüm turu başarısız gösteriyordu. Çalışan `uv run python -m kkb_agent.serve` süreci bu düzeltmelerden önce başlatıldığı için dosya değişikliklerini hot-reload etmiyordu.
- Harness artık yalnız açık analiz/yorum/metaveri isteği bulunmayan doğrudan göster/getir/listele taleplerinde, bu turda veri üreten araçtan gelen çerçeve aktif tabloyla birebir doğrulanmışsa modeli tekrar çağırmadan tabloyu başarıyla yayımlar. Başarısız adım veya aynı turda kısmi/reddedilmiş fitness kararı varsa kısa yol kapalıdır; dönüşüm/analiz, `clarify`, URL/dosya uygunluk kapıları normal akışını korur.
- Açık anlatım gereken `narration`, `long_narration` ve `recovery` çağrıları `LLM_NARRATION_TIMEOUT_S` ile (varsayılan 30 sn, `.env.example` üzerinden ayarlanabilir) soru bütçesinden bağımsız olarak tüm retry'lar için sınırlandırılır. Zaman aşımında daha önce eklenen doğrulanmış tablo fallback'i çalışır. Gerçek `.env` dosyasına dokunulmadı.
- Yeni testler salt tablo isteğinin ikinci LLM çağrısı olmadan API tablosu üretmesini, açık yorum isteğinde tablo/follow-up bağlamının korunmasını ve narrator deadline'ının 600 sn soru bütçesinden kısa kalmasını doğruluyor. Agent-core suite **828 geçti**, 1 Starlette deprecation uyarısı; `git diff --check` başarılı. Eski localhost süreci yenilendi ve `/api/status` HTTP 200 ile **6.304 katalog serisi** bildirdi. Manuel MIA sorgusu bu turda gönderilmedi.

### 2.92 Bileşik dönüşüm + grafik takip sorusunda tool-phase timeout (19 Eylül)
- Gerçek oturum izinde yanıt **231 sn** sürdü. Önce iki doğrulama geri göndermesi toplam **36,3 sn** harcadı; grafik aracı başarılı tamamlandı (**10,7 sn**); sonra modelin `tool` fazındaki iki denemesi **182,3 sn** sonunda `Request timed out` oldu. `LLM_NARRATION_TIMEOUT_S=30` yalnız `narration`/`long_narration`/`recovery` fazlarına uygulandığı için bu kesintiyi sınırlamadı. Hata anlatı üretiminde değil, dönüşüm yeteneğini araçla yerine getirme aşamasındaydı.
- Takip sorusunda aktif workspace tablosu zaten aylık değişim kolonlarını içeriyordu. Ancak yetenek kapısı dönüşüm aracının **bu turda** çağrılmış olmasını şart koştu; önceki doğrulanmış tablonun dönüşümü karşılamasını kabul etmedi. Grafik aracı 24 satırlık iki değişim serisini çizdiği halde, sonraki model turu dönüşüm çağrısını seçemedi ve iki kez bekledi. İz ayrıca takip bağlamının tek seri kimliği taşıdığını, başarılı grafiğin ise iki seriyi kullandığını gösteriyor; çok serili takip bağlamı ayrıca doğrulanmalı.
- Kesinti yakalayıcısı yalnız mevcut turdaki veri üreten araç çıktısıyla tabloyu doğruluyor ve `_ask` içindeki yerel `artifacts` listesini hata cevabına aktarmıyor. Bu nedenle 24 satırlık mevcut tabloya dair kullanıcı metni yazılmış olsa da kaydedilen yanıt payload'ında `table`, `charts` ve `evidence` boş/null; grafiğin başarılı araç adımı kanıt olarak kalıyor fakat yeniden yüklenebilir yanıt artifact'ine bağlanmıyor.
- Bu teşhis turunda uygulama kodu değiştirilmedi ve test çalıştırılmadı. Kalıcı iyileştirme için sıradaki işler: (1) follow-up'ta mevcut doğrulanmış tablonun istenen dönüşümü zaten karşılayıp karşılamadığını şema/kapsam/provenance ile kontrol etmek, (2) composite işlemi deterministik `reuse/transform → validate → chart → concise response` planına çevirmek ve aynı kabiliyeti tekrar tekrar LLM'den istememek, (3) in-flight turn state içinde tablo, grafik, kanıt ve follow-up lineage'ını birlikte saklayıp timeout cevabına güvenli biçimde taşımak, (4) çok serili aktif tablo kimliklerinin follow-up context'te korunmasına regresyon testi eklemek, (5) provider timeout/retry gecikmesini faz bazında sınırlandırıp kullanıcıya tamamlanmış artifact'leri açıklama kesintisinden ayırarak göstermek.

### 2.93 Doğrulanmış dönüşüm/grafik fast path ve timeout dayanıklılığı (19 Eylül)
- Takip sorusunda mevcut aktif tablonun istenen aylık dönüşümü yeterli kanıtla taşıyıp taşımadığı artık suffix'e bakılarak değil; workspace işlem geçmişi, `türetilmiş:` LAG provenance'ı, kaynak seri kimlikleri, frekans ve açık tarih aralığının eksiksizliği birlikte denetlenerek belirleniyor. Doğrulanmışsa dönüşüm bu turun yetenek kapısını karşılıyor; çoklu seri kimlikleri takip çözümlemesine ekleniyor.
- Uygun ve yalnız yapılandırılmış çıktı/grafik isteyen dönüşümlerde deterministik akış `aktif tablo → dönüşümü uygula/gerekirse doğrula → chart aracı → kısa kapanış` biçiminde tamamlanıyor. Bu yol kullanıcı açıkça yorum/analiz istediğinde kullanılmıyor. Başarısız grafik denemesinde yeni dönüşüm geri alınıyor.
- LLM anlatısı kesilirse in-flight başarılı grafik artifact'i korunuyor; mevcut tablo yalnız provenanced dönüşüm ve aynı kapsam doğrulanmışsa API/CSV/XLSX projection'a ekleniyor. `web_app` artık bu doğrulanmış yeniden kullanımı tablo dokunulmuş sayıyor ve kullanıcı görünümünde tarih + istenen türetilmiş kolonları seçiyor.
- Araç/planlama fazı `LLM_TOOL_TIMEOUT_S` ile, sağlayıcının tekrar denemeleri dahil toplam **90 sn** varsayılan deadline'a bağlandı. Narration sınırı devam ediyor. OpenAI-uyumlu istemci hata mesajında ayarlanan retry sayısını değil gerçekten başlayan istek sayısını gösteriyor; başarısız faz `usage.failed_llm_phase` içinde.
- Yeni sentetik regresyonlar iki farklı seri kimliğinde deterministik dönüşüm+grafik yolunun sıfır LLM çağrısı ile çalıştığını, çok serili kimliklerin korunduğunu, narrator timeout'ta tablo ve grafik artifact'inin API payload'ında kaldığını, kaydedilmiş Session tablosunun CSV/XLSX çıktılarında 60 satır ve türetilmiş kolonları koruduğunu ve tool deadline'ının soru bütçesini aşmadığını doğruluyor. Eski iki demo promptunun tam metni kod/testlere eklenmedi; gerçek `.env` değiştirilmedi.
- Doğrulama: agent-core **831 test geçti**, bir Starlette bağımlılık deprecation uyarısı; değişen modüllerde Ruff `F` kontrolleri geçti; `git diff --check` geçti. Tam `ruff check` depo genelindeki mevcut stil/import ihlalleri nedeniyle temiz değil ve düzeltilmedi.
- Manuel deneme için hot-reload kullanmayan eski localhost süreci kontrollü durdurulup güncel kodla yeniden başlatıldı; `http://127.0.0.1:8765/` sunucusu `/api/status` üzerinden HTTP 200 ve Analyst profilinde 21 kayıtlı araçla doğrulandı. Gerçek model sorgusu gönderilmedi.

### 2.94 Tek kullanıcıyla manuel test için Cloudflare Tunnel yayını (19 Eylül)
- Kullanıcının açık onayıyla Cloudflare Zero Trust'ta `agent-smith-demo` tüneli `agent-smith-demo.bardaka.site` public hostname'ine bağlandı; tüm path'ler `http://localhost:8765` origin'ine yönleniyor. Mevcut `social-ihbar` tüneline dokunulmadı.
- `cloudflared` 2026.9.1 connector'ı bu Mac'te `cloudflared tunnel run --token-file /Users/baran/.cloudflared/agent-smith-demo-token` komutuyla başlatıldı. Token repo dışındaki kullanıcıya özel dosyada `0600` izinle saklanıyor; gerçek `.env` değişmedi.
- Doğrulama: Cloudflare tunnel durumu **Healthy**, connector **Connected**; `https://agent-smith-demo.bardaka.site/` ve `/api/status` Cloudflare edge'e HTTPS isteğinde HTTP 200 verdi. Bu Mac'in sistem resolver'ı ilk denemelerde hostname'i çözemedi, fakat `dig` DNS kayıtlarını gösterdi ve edge IP'si sabitlenmiş HTTPS kontrolleri başarılı oldu.
- Erişim sınırı: uygulamada giriş/kimlik doğrulama yok; hostname bilen herkes UI ve API'ye erişebilir. Linki yalnız hedef arkadaşla paylaşmak operasyonel tercihtir, teknik erişim kontrolü değildir. Uygulama ve connector bu bilgisayarda çalıştığı sürece tünel erişilebilir; bilgisayar, yerel sunucu veya `cloudflared` durursa public erişim kesilir. Kalıcı/çok kullanıcılı paylaşım için Access politikası ve oturum izolasyonu ayrıca ele alınmalı.

### 2.95 Yüklenen CSV'de anlatım timeout teşhisi (19 Eylül)
- Kaydedilmiş `weather.csv` denemesinde 1,37 MB / 28.576×8 tablo okuma ve workspace'e yükleme başarılı. Aynı yerel dosya önce tablo listesi için 15,7 s, sonra `table_index=0` ile tekrar okunup yüklenirken 19,1 s harcandı; bu iki çağrı arasında parse sonucu yeniden kullanılmadı.
- Son model çağrısının fazı `narration`; `LLM_UNAVAILABLE: Request timed out` kaydı 30.004 s. Bu, anlatım servisi yapılandırılmamış demek değil: turdaki önceki model çağrıları yanıt verdi; son anlatım çağrısı 30 s sınırını aşınca kontrollü tablo-fallback'i döndü. Tur toplamı 66,6 s.
- Başarılı model çağrıları için raporlanan giriş toplamı 27.322 token; timeout olan çağrının token kullanımı bilinmiyor. 8 kolon nedeniyle anlatım bütçesi 3.400 token seçildi; token tavanı ve 30 s süre sınırı ayrı ayarlardır.
- İzleyen genel iyileştirme adayları: dosya/tablo keşif-sonrası seçimde parse edilmiş sonucu hash/locator ile yeniden kullanmak; anlatı bağlamını satır dökümü yerine sınırlı istatistik ve tablo özetleriyle kurmak; timeout'ta güvenli, deterministik kısa özet sağlamak. Bu teşhis turunda prompt veya runtime kodu değiştirilmedi.

### 2.96 Anlatım timeout fallback'i ve aynı-tur dosya önbelleği (19 Eylül)
- `LLM_NARRATION_TIMEOUT_S` varsayılanı 30 → 60 s yapıldı; `.env.example` güncellendi. Gerçek `.env`'de bu anahtar tanımlı değildi ve `.env` değiştirilmedi. Ortam değişkeni tanımlanırsa override etmeye devam eder.
- `web_url`, başarılı keşif sonucundaki parse edilmiş sayfayı yalnız aynı agent turunda ve aynı locator için `table_index` yüklemesinde yeniden kullanıyor. Yeni turda kaynak yeniden çekilir; başarısız keşif önbelleğe alınmaz.
- Yeni `core/table_summary.py`, anlatım timeout'u sonrasında doğrulanmış aktif tablo için model çağrısı yapmadan kısa yerel özet üretir: tablo boyutu/şema, algılanan tarih aralığı, eksik kolonlar ve sayısal min–max aralıkları. Özet tahmin/nedensellik üretmez ve tabloda değişiklik yapmaz; anlatı prompt'u bu çalışmada değiştirilmedi.
- Doğrulama: agent-core **839 test geçti** (tek Starlette deprecation uyarısı); değişen modüllerde Ruff `F` ve `git diff --check` temiz. Genel Ruff mevcut diğer stil/import ihlallerini raporlamaya devam ediyor. `weather.csv` yerel smoke testi (28.576×8): pandas okuma 0,043 s, özet 0,004 s. Güncel demo `127.0.0.1:8765/api/status` HTTP 200, Analyst profili, 21 araç.
- Gerçek MIA anlatım timeout'u bu uygulama değişikliğiyle yeniden tetiklenmedi; manuel test bekleniyor. Bu sayede 60 s sınırının sağlayıcı davranışını çözüp çözmediği gerçek çağrıda ölçülecek.

### 2.97 60 s anlatım timeout'u sonrası gerçek MIA tekrar denemesi (19 Eylül)
- Önceki `weather.csv` dosya analiz isteği aynı metinle tekrar gönderildi. Sunucu mevcut konuşmayı/aktif tabloyu kullandı; dosya yeniden yüklenmedi ve başlangıç adımı `workspace_show` oldu.
- İstek 86,7 s sürdü; 4 başarılı MIA çağrısı (1 planning, 3 narration bütçeli çağrı), 5 kısa `workspace_query`, kanıt adımı ve 20 satırlı aylık özet tablosu üretti. `failed_llm_calls=0`; son yanıt anlatısı geldi, önceki timeout tekrarlanmadı.
- 60 s sınırı her anlatım çağrısına uygulanır; toplam isteğin 60 s'den uzun sürmesi normaldir. Bu koşudaki model adımları 60 s'ye ulaşmadı; genel 86,7 s gecikmenin başlıca nedeni birden fazla anlatım/özetleme turudur. Manuel demo denemesi için servis erişilebilir kaldı.

### 2.98 Harici girdisiz V2 benchmark tam koşusu (19 Eylül)
- Terminal kapanmasının ardından Cloudflare `cloudflared` tüneli kapalı bırakıldı; yerel demo `uv run python -m kkb_agent.serve` ile `127.0.0.1:8765` üzerinde açıldı. `/api/status` HTTP 200 verdi; Analyst, 6.304 katalog serisi, 21 araç. Bu benchmark için `.env` ve uygulama kodu değiştirilmedi.
- `agent-core/scripts/m02_benchmark/run_v2.py` ile `external_mode=none` olan 76 vakanın tamamı birer kez çalıştırıldı. 76 benzersiz ID kaydedildi; fixture/URL isteyen 44 vaka kapsam dışı kaldı. Ham kayıtlar `docs/experiments/v2_local_full_20260919.jsonl`, CSV tabloları yanındaki `_tables/` dizininde.
- Tekrarlanabilirlik iddiası olmaksızın ilk manuel puan: 71 puanlanabilir vakada ortalama 41,6/100; 5 vaka başlangıç state’i, concurrency veya UI export kabiliyeti runner’da olmadığı için N/T. Puanlar, vaka başına gerekçeler ve benchmark oracle kusurları `docs/experiments/v2_local_full_20260919_score.md` içinde.
- 47/76 vakada MIA/LLM çağrısı timeout/fallback kaydı bıraktı (%61,8); süre medyanı 124,0 sn, p95 272,6 sn, maksimum 490,0 sn. `executed_needs_review` başarı sayılmamalı; tablo varlığı içerik doğruluğuna eşit değil.
- Benchmark sözleşmesinde düzeltilecek örnekler: R06 mevcut tablo seed’i olmadan başlıyor; L07 paralellik, L08 timeout recovery, O03 UI filtre/export ve O06 CSV/XLSX parity runner tarafından ölçülemiyor; F07/L01 seri seçimi promptta belirtilmemiş; P03/T03/T06/F08 prompt–referans kapsam/formül uyumsuzlukları var. Değişiklik öncesi bu set benchmark oracle ve runner açısından düzeltilmeli.
- Sonraki adım: narration servis kesintilerinin ham trace’lerini incelemek; runner’a workspace setup, timeout enjeksiyonu, export parity ve eşzamanlı oturum testlerini eklemek; prompt/referans sözleşmesini düzeltip 76 vakayı üç tekrar ile yeniden çalıştırmak.


### 2.99 Benchmark sözleşmesi v2.1 donduruldu (19 Eylül)
- Yerel benchmark prompt/oracle/setup değerlendirmesi tamamlandı. `docs/benchmark/CONTRACT_V2_1.md` normatif sözleşme; insan okunur prompt, oracle ve yerel beklenti belgeleri JSONL manifestlerin aynasıdır. `contract_v2_1` ve `evaluation_contract` her vakada test yüzeyi, workspace başlangıcı, kabul koşulu ve kritik hata ölçütlerini taşır.
- Kapsam 120 prompt: 76 yerel, 38 fixture/snapshot ve 6 canlı web. Agent-CLI koşucusu 71 vakayı seçer; L06/L07/L08/O03/O06 sırasıyla performans tekrarı, concurrency, fault injection, UI filtre ve CSV/XLSX export parity olarak ayrı yüzeylere ayrılmıştır. 44 harici vaka fixture/snapshot pinlenmeden çalıştırılmaz.
- Oracle kusurları giderildi: P03 için yaz 2023'ün tüm aylarını kapsayan herhangi bir geçerli kesintisiz 36 aylık pencere kabul edilir; R01 parent-child prompt/referans eşleşir; R06 gerçek ilk tur tablosunu kurup takipte TÜFE ekler; T03 uç nokta pp/göreli yüzde farkını ölçer; T06 doğru serilerle 60 ay ve 2020-12 LAG tabanı kullanır; F01/F08 takip projection'ları kendi dönem/satır sayılarına göre referanslanır; P04/F01/L03/L04 artık bağımsız sayısal artifact sahibidir; Q03–Q05/I08 implicit fixture yerine prompt-içi örneklerle sınanır.
- Yerel oracle: 31 CSV artifact doğrulanır (28 DuckDB snapshot çıktısı + 3 prompt-içi fixture). L03 81 toplam-mevduat il serisi × 20 doğal çeyrek = 1.620 satırdır; kişi başı seriler dışlanır. T06 60 satır, L04 20 çeyrek, F01 24 ay, F08 36 ay.
- `agent-core/scripts/m02_benchmark/validate_contract_v2_1.py` tüm 120 prompt/76 oracle ID eşleşmesini, Markdown aynalarının vaka kapsamını, yüzey sayımlarını, kritik row-count'ları, 31 artifact hash/kolon/satır sayılarını ve L03 il/çeyrek kapsamını doğrular. `run_v2.py` CLI dışı vakaları varsayılan koşudan ayırır ve doğrudan ID ile seçilmelerini açık hata yapar.
- Sözleşme öncesi tek koşuluk 41,6/100 raporu v2.0 keşif koşusu olarak işaretlendi; v2.1 baseline değildir ve yeniden puanlanmadı. Tüm 76 vakaya MIA çağrısı gönderilmedi.
- Doğrulama: `uv run pytest -q` **841 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; benchmark dosyalarında Ruff temiz; contract validator ve 71-vaka `--dry-run` başarılı; `git diff --check` başarılı. Uygulama/harness runtime’ına ve `.env`'e bu benchmark düzeltmesi için dokunulmadı.
- Snapshot SHA-256: DuckDB `5ab35f4cd1b014b15361566ab28cbe70570a9c118459e7243a6442bd63794df6`; prompt manifest `b306c92ebce75980a99144d784c49203cf87ebd2da2f678819eba5a912aa7ced`; local oracle `94796cfc996b7e54af4ed23f7453fd55b1ce1185ade49061fdda9014006ac239`.
- Sonraki adım: v2.1 sözleşmesine göre 71 CLI vakasını kontrollü tekrarlarda yeniden çalıştırmak; L06/L07/L08/O03/O06'yı kendi test yüzeylerinde manuel/entegrasyon doğrulamak. Harici URL/CSV vakaları arkadaşın web search tool'u ve fixture'lar hazır olduktan sonra eklenir.

### 2.100 PR #17 web araştırma entegrasyonunda M1 (19 Eylül)
- PR #17 topluca alınmadı. Entegrasyon `docs/WEB_SEARCH_PR17_ENTEGRASYON_PLANI.md` altında M0–M7 olarak ayrıldı; mevcut kullanıcı değişiklikleri ve `.env` korunuyor. Sahte Chrome User-Agent, doğrulanmamış OCR tablo hücreleri ve tur sınırı olmayan URL cache'i kapsam dışı.
- M1'de kurum/host ve katalog kaynağı/kamu domain eşlemeleri `agent-core/src/kkb_agent/config_data/source_hints.json` içine alındı; `source_hints.py` yükleme/normalizasyonu yapıyor. Yeni `core/web_routing.py`, host ve URL doğrulaması, web intent/forbid, allowlist kesişimi ve katalog metadata'sından sınırlı arama planı üreten saf fonksiyonlar içeriyor. Ham prompt/SQL/satırlar arama planına kopyalanmıyor.
- M1 henüz web çağrısını agent'a bağlamıyor. Güvenli otomatik fallback için araçtan doğrulanmış `CONFIRMED_ABSENT` / `OUT_OF_COVERAGE` ayrımı M2'de kurulacak; SQL/fetch hatası veya pending indeks sonucu internet araması başlatmamalı.
- Mimari gerekçe `docs/adr/0086-web-kaynak-yonlendirme-plani.md` içinde. Doğrulama: agent-core tam suite **855 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; ilgili Ruff, JSON parse ve `git diff --check` başarılı.
- Gerçek `.env` değiştirilmedi; demo/tünel durumu değiştirilmedi; commit veya PR oluşturulmadı. Sonraki adım M2: katalog yokluğu durum sözleşmesini ve yalnız yetkili durumda dinamik web tool gate'i agent'a bağlamak.

### 2.101 PR #17 web araştırma entegrasyonunda M2 (19 Eylül)
- `AnalyticsAgent` M1 yönlendirme planını sadece authoritative absence (`lakehouse_search`/`lakehouse_query`) sonrasında değerlendiriyor. `OUT_OF_COVERAGE` öncesi query provenance yoksa SQL'den yalnız katalogda birebir bulunan dataset ID'leri metadata lookup için çıkarılıyor; SQL dış sorguya gönderilmiyor.
- Uygun kamu source planı oluşursa aynı turda `web_search` + `web_url` tool şeması açılıyor; LLM'e query/domain planı bildirilirken `WebSearchTool` argümanları turn-scoped plan ile clamp ediyor ve otomatik aramayı bir çağrıyla sınırlıyor. Yeni turda plan/harcama bayrağı temizleniyor.
- Pending/unloaded aday, `SQL_FAILED`, erişim/kaynak hatası, özel veri kalıbı, web yasağı, bilinmeyen/özel source veya `web_search`/`web_url` eksikliği otomatik fallback'i kapatır. Açık kaynak pin'i olmadan ve katalog provenance'ı yokken arama planı oluşturulmaz.
- Boş fakat başarılı sorgu `FOUND` sayılmıyor; `CONFIRMED_ABSENT`/`RETRIEVAL_FAILED` availability sonucu korunuyor.
- Doğrulama: agent-core **860 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı. İlgili hedefli testler 103 geçti; değişen modüllerde Ruff `F`, source JSON parse ve `git diff --check` başarılı. Harici Tavily ağına çıkılmadı.
- Gerçek `.env` ve demo/tünel durumu değiştirilmedi; commit/PR yok. Sonraki adım M3: Tavily sonucunu host bazında tekrar doğrulama, aynı-domain kaynak keşfi ve arama parçacıklarının kanıt dışı kalmasını tamamlamak.

### 2.102 PR #17 web araştırma entegrasyonunda M3 (19 Eylül)
- Açık URL/kurum pin'i Tavily `include_domains` filtresine taşınıyor; sağlayıcı sonuçları ayrıca denetleniyor. HTTP(S) dışı, malformed, userinfo/port taşıyan, private/loopback veya pinned host sınırını aşan aday `sanctioned_locators` içine girmiyor. Domain karşılaştırması tam host/alt-domain sınırıyla yapılıyor.
- CSV/TSV/XLS/XLSX/PDF/JSON sonuçları ve same-domain crawl'daki PDF/doğrudan veri linkleri öne alınıyor. Landing-page keşfi `max_depth=1` ile sınırlandırılmış mevcut crawler'ın same-domain ve robots politikalarını kullanıyor.
- `web_search` snippet'leri artık agent'ın numeric grounding havuzuna eklenmiyor. Aynı turda `web_url` kaynağı okunmadan ve başka veri aracı çalışmadan model final vermeye kalkarsa deterministik, sayısız aday/okunma durumu döndürülüyor; arama URL/title ve aday tipi evidence artefact'inde kalıyor.
- ADR-0087 arama-result trust boundary, snippet kanıt kuralı ve doğrudan dosya önceliğini kaydediyor. M3 planı tamamlandı; M4 fetch sınırları, hata sınıfları ve same-turn cache testleri üzerinde çalışılacak.
- Doğrulama: agent-core **864 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; ilgili Ruff `F` ve `git diff --check` başarılı. Canlı Tavily çağrısı yapılmadı. Gerçek `.env`, demo ve tünel değiştirilmedi; commit/PR yok.

### 2.103 PR #17 web araştırma entegrasyonunda M4 (19 Eylül)
- `ContentTooLarge` fetch türü, crawler `limit_exceeded` sonucu ve `CONTENT_TOO_LARGE` tool hatası eklendi. Erişilmiş ama boyut bütçesini aşan içerik, erişim engeli veya veri yokluğu gibi raporlanmıyor; aynı URL/bütçe tekrarına terminal recovery uygulanıyor.
- `web_url` başarılı keşfi yalnız aynı agent turu ve aynı URL/sayfalar/bütçe/amaç parametreleri için tekrar kullanıyor. Yeni tur, farklı amaç ve `refresh=true` yeni fetch/OCR başlatıyor; başarısız keşif cache'e alınmıyor. `cache_reused` kanıt artefact'inde görünür.
- Mimari karar `docs/adr/0088-web-fetch-buyuk-icerik-ve-tur-cache.md`; M4 entegrasyon planında tamamlandı, M5 PDF text-layer/OCR kanıt entegrasyonu başladı.
- Doğrulama: agent-core **870 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı. `CONTENT_TOO_LARGE`, bounded recovery, same-turn cache, yeni tur/refresh, değişen amaç ve başarısız keşif testleri geçti. Gerçek `.env`, demo/tünel ve canlı web isteği değiştirilmedi; commit/PR yok.

### 2.104 PR #17 web araştırma entegrasyonunda M5 (19 Eylül)
- Yeni `vision/pdf.py` text-layer'ı pypdfium2 `get_text_bounded()` ile sayfa/karakter bütçesinde okuyor. Bu içerik düz metin olarak taşınır; tablo yerleşimi uydurulmaz. Text-layer yoksa tarama “veri yok” sayılmaz.
- PDF'e OCR uygulanınca metadata text-layer ve OCR sayfalarını/yöntemlerini ayrı taşır. Text-layer OCR tablo hücrelerini doğrulamıyorsa OCR quality gate ve `ocr_unverified` korunur. OCR başarısızsa native text fallback varsa kullanılır; tablo çıkarımı imkânsızsa `DOCUMENT_EXTRACTION_FAILED` döner.
- PDF extraction method/page scope hem web artefact'inde hem aktif tablo `QueryProvenance` uyarılarında bulunur. Karar `docs/adr/0089-pdf-text-layer-ve-ocr-kanit-siniri.md` içinde.
- Doğrulama: gerçek PDFium text fixture, OCR+text-layer, scanned/no-OCR, OCR failure fallback, tablo çıkarım hatası ve mevcut OCR kalite testleri; agent-core **876 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı. Ruff `F`, `git diff --check` başarılı; harici servis çağrısı yok. M6 kanıt paneli/UI metadatasına geçildi.

### 2.105 PR #17 web araştırma entegrasyonunda M6 (19 Eylül)
- Kanıt sözleşmesi arama adayını (`context_sources`), okunan URL'yi (`web_reads`) ve çalışma tablosuna seçilen sayfayı (`web_sources`) ayırıyor. Seçili tablonun indeks/etiket/ölçüsü ve fetch/cache/PDF extraction metadata'sı API, kanıt paneli ve kanıt yolculuğunda gösteriliyor; PDF text-layer veya OCR tablo hücrelerini kendiliğinden doğrulanmış yapmıyor.
- Erişim/boyut/çıkarım/uygunluk retlerinde web artefact'i korunuyor. Çalışma alanı seçilmiş tablo metadata'sını takip sorusuna taşıyor. Narration timeout sonrası gerçek `AnalyticsAgent` testi tabloyu, hash'i, `table_used` durumunu ve `FOUND` cevabı korudu.
- Karar `docs/adr/0090-web-kanit-panelinde-arama-okuma-ve-tablo-secimi.md`; entegrasyon planında M6 tamamlandı, M7 tam regresyon/benchmark doğrulaması sürüyor.
- Doğrulama: web, web-app, kanıt yolculuğu ve adım yolculuğu hedefli testleri **56 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı. Harici arama/LLM API'si kullanılmadı; `.env`, demo/tünel, commit ve PR değiştirilmedi.

### 2.106 PR #17 web araştırma entegrasyonunda M7 ve M0–M7 kapanışı (19 Eylül)
- Tam agent-core suite **879 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı. Benchmark v2.1 contract validator 120 vaka/76 oracle/31 artifact kapsamını doğruladı; `run_v2.py --dry-run` 71 agent-CLI vakasını MIA çağrısı olmadan listeledi.
- Mevcut crawler TCMB (`https://www.tcmb.gov.tr/`), BDDK (`https://www.bddk.gov.tr/`) ve EVDS (`https://evds2.tcmb.gov.tr/`) resmi ana sayfalarını 1 sayfa/derinlik 0 bütçesiyle okudu; HTTP 200, içerik hash'i ve UTC fetch zamanı `docs/WEB_SEARCH_PR17_ENTEGRASYON_PLANI.md` içine kaydedildi. Smoke test veri tablolarını veya Tavily arama sağlayıcısını doğrulamaz.
- Ruff `F` ve `git diff --check` başarılı; gerçek `.env`, demo/tünel ve kullanıcıya ait diğer değişiklikler korunmuş; commit/PR oluşturulmamış. Entegrasyon planı M0–M7 tamamlandı.
- İkinci tam 71-vaka canlı MIA benchmark'ı bu entegrasyon milestone'unun parçası olarak çalıştırılmadı; runner/sözleşme hazır ve ayrı benchmark işi olarak yapılabilir.


### 2.107 71-vaka canlı MIA benchmark (20 Eylül)
- `v2.1` benchmark sözleşmesindeki 71 `agent_cli` vakası `--repeat 1` ile aynı `feature/agent-engine` HEAD'inde çalıştırıldı; 71/71 koşu kaydı oluştu. Bu, yürütme kapsamıdır; otomatik doğruluk geçişi değildir. Benchmark sırasında kod, ayar, gerçek `.env` ve lakehouse veritabanı değiştirilmedi; `.env` hash'i `3d9edab0b35a33c3c0b99c4e1dec457f54d8cc8abe03ba160ddcced59d74e516` kaldı.
- 59/71 vaka en az bir LLM çağrı hatasıyla tamamlandı; toplam 381 çağrının 63'ü başarısız oldu (planning 4, tool 25, narration 24, recovery 10). 50 vakada dolu tablo/CSV korundu; toplam tablo satırı 2.175. Latency p50 168,38 sn, p95 296,45 sn, maksimum 430,68 sn; süre tek tekrarın seri toplamında 199,3 dk. Tekrarlı benchmark kararlılığı veya başarı oranı iddiası çıkarılmamalı.
- 50 CSV artifact'in SHA-256 değerleri koşu kaydıyla eşleşti. İlk oracle incelemesi P01 ve R01 sayısal değerlerini doğru buldu; P03 pencere anchor'ı, T06 projection, F01 takip dönüşümü, F06 BDDK→EVDS kaynak değişimi ve L05 güvenli `UNION ALL` davranışında kusurlar gördü. P02'nin promptu ile referans oracle'ı çeliştiğinden bu vaka önce düzeltilmeli.
- Ham koşu: `docs/experiments/v2_mia_71_full_20260919.jsonl`; artifact'ler: `docs/experiments/v2_mia_71_full_20260919_tables/`; ilk analiz: `docs/experiments/v2_mia_71_full_20260919_analysis.md`. Analiz belgesi tam 71-vaka doğruluk skorlaması değildir; her vaka bağımsız oracle'a göre incelenmeli.
- Doğrulama: benchmark validator 120 vaka/76 oracle/31 artifact sözleşmesini geçti; ön kontroller ve kısa canlı MIA ping başarılıydı. Buna rağmen canlı akıştaki LLM hata oranı yüksek ve değişken çıktı; yalnızca bu tek koşu üretim/demoya hazır olma ölçütünü karşılamaz. Commit/PR oluşturulmadı.
- Sonraki adım: P02 sözleşme/oracle çelişkisini düzelt, tüm vakaları oracle'a göre puanla; ardından projection, follow-up state, source-switch ve SQL güvenlik/hata toparlama sorunlarını prompta özel kurallar eklemeden harness'ta ele al. Değişikliklerden sonra canary ve sözleşmedeki tekrarlı doğruluk/performance koşularını çalıştır.

### 2.108 MIA benchmark oracle düzeltmeleri ve 71-vaka puan kartı (20 Eylül)
- 71 canlı `agent_cli` koşusu, P02/L05/S03 bağımsız oracle’ları düzeltilerek tek tek puanlandı. Ham JSONL ve promptlar değiştirilmedi; `.env` hash’i korunuyor. Rapor: `docs/experiments/v2_mia_71_full_20260919_score.md`; latency/yürütme kaydı: `docs/experiments/v2_mia_71_full_20260919_analysis.md`.
- P02: Ocak 2023 LAG tabanı Aralık 2022 olduğu için doğru fark 70.366. L05: referans aralığı prompttan sapıyordu; canonical CSV 2021-01–2025-12 olarak yeniden üretildi ve Ocak farkı 2020-12 tabanını kullanıyor. S03: 2024-08-30 `missing_value`, doğru son geçerli as-of 2024-08-29 / 52,79.
- Sonuç: ortalama 44,0/100; 6 geçti, 26 kısmi, 39 başarısız. 59/71 vakada LLM çağrı hatası, 63/381 çağrıda hata; 18 vakada hiç tablo yok. Tekrar sayısı 1 olduğundan baseline keşif niteliğinde.
- Önemli mimari işaretler: 1357 verified ulusal toplam mevduat ile 543 derived vade tablosu yakın eşleşmesi; takip turu dönüşüm/projection state kaybı; timeout sonrası eksik anlatı; güvenli `UNION ALL` reddi; C/T/O analiz vakalarında ham join’in analize dönüşmemesi. Bunlar prompta özel kural değil, retrieval, session state, SQL guard, analitik tool ve narration fallback katmanlarına ait.
- Benchmark validator **120 vaka / 76 yerel / 71 agent_cli / 5 integration-performance / 76 oracle / 31 artifact** için geçti. Uygulama kodu değiştirilmedi; commit/PR yok.

### 2.109 MIA benchmark sayaç notu (20 Eylül)
- Puan kartındaki tablo/artifact olmayan vaka sayısı **21/71** olarak netleştirildi: bunların 18'i LLM çağrı hatası nedeniyle, 3'ü (A01 netleştirme, A06 güvenlik reddi, A08 kapsam/gizlilik yanıtı) doğru biçimde tablo üretmedi. Önceki 2.108 kaydındaki “18 vakada hiç tablo yok” ifadesi, yalnız LLM hatası alıp tablo üretmeyen alt kümeyi toplamla karıştırıyordu.
- 59/71, en az bir LLM çağrı hatası alan vaka sayısıdır; ham JSONL SHA-256 `e2074d034cb8e6652c7b3b2f54f70b8ca99528d7e7a835d2809ff895f0a8f1dd`.

### 2.110 MIA benchmark mimari düzeltmeleri (20 Eylül)
- Benchmark bulguları sorgu/prompt özel kuralına dönüştürülmedi. ADR-0091 retrieval sıralamasını yalnız yakın aday kümesinde açık ölçüm türü, aday adı/alias kapsamı ve eşdeğer doğrulanmış semantik üzerinden düzenler. Gerçek Silver smoke testinde `bddk_monthly:1357_Toplam` genel mevduat/stok isteğinde ilk; vade kırılımı açık sorguda `bddk_monthly:543_Toplam` ilk sırada kaldı.
- ADR-0092 takip sorusunda aktif çalışma tablosu/provenance kimliklerini yeni kaynak birleşimi için çapaya taşır; yeni kaynak/seri katalogdan tekrar keşfedilip doğrulanır. Eski tablo tek başına yeni isteğin cevabı sayılamaz.
- ADR-0093 `seasonal_mad` aylık analitiğini (takvim ayı için en az 4 gözlem) ekler ve SQL parse hatasını `SQL_SYNTAX_ERROR`/retryable olarak güvenlik reddinden ayırır. Politika ihlali ve çoklu statement guard'ları korunur.
- ADR-0094 adım telemetrisine `llm_duration_ms`, `tool_duration_ms` ve aggregate `llm_call_ms` ekler; toplam `duration_ms` geriye uyumlu kalır. Anlatım sağlayıcısı kesildiğinde doğrulanmış tablo korunur ve eksik analiz açıkça belirtilir. Narration promptu değiştirilmedi.
- Doğrulama: agent-core tam suite **891 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; benchmark sözleşme doğrulayıcısı **120 vaka / 76 oracle / 31 artifact** geçti; retrieval gerçek katalog smoke testi; değiştirilmiş `retriever.py` Ruff temiz; `git diff --check` başarılı. Gerçek `.env`, demo/tünel, commit ve PR değiştirilmedi.

### 2.111 Web araştırma timeout'unda kanıtı koruma ve same-turn tekrar maliyetini düşürme (20 Eylül, ADR-0088/0095)
- `web_url` tur cache'i doğrudan sayfa okumalarında amaç metninden bağımsızlaştı; derin taramada amaç link seçimini etkilediğinden anahtarda kalır. URL şema/host/default port/fragment normalizasyonu, 8 kayıt/16 MiB üst sınırı, başarısız/aşırı büyük yanıtı cache'lememe, explicit refresh ve yeni tur temizliği korunur.
- Aynı URL ve aynı metin aralığı tekrar istendiğinde uzun excerpt model bağlamına ikinci kez eklenmez; başka `text_from` aralığı cache'den verilir. Bu ağ/OCR maliyeti kadar tekrarlanan prompt girdisini de azaltır.
- Web sayfaları okunmuşsa anlatım çağrısı kesintisinde deterministik, sayı üretmeyen source-only yanıt ve kanıt paneli döner. Yalnız arama adayı varsa adayın veri kanıtı olmadığı belirtilir. `availability_status=UNKNOWN`; önceki workspace tablosu temiz bir kanıt workspace'iyle dışarıda bırakılır.
- `evidence_to_dict` API serializer'ına `web_reads` eklendi; UI'ın beklediği “okundu, tablo seçilmedi” listesi artık taşınır. Genel model kesintisi metni eski tablonun bu soruya ait olmadığını açık söyler.
- Doğrulama: son web/follow-up/web-app hedefli koşu **48 geçti**; tam agent-core suite **899 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; benchmark sözleşmesi 120 vaka/76 oracle/31 artifact geçti; değişen Python modüllerinde Ruff `F`, `git diff --check` temiz. Gerçek MIA/Tavily isteği yapılmadı; manuel demo doğrulaması sonraki adımdır.
- `.env`, lakehouse DB, Cloudflare tüneli, commit ve PR değiştirilmedi. Yerel demo yeni kodla `127.0.0.1:8765` üzerinde yeniden başlatıldı; `/api/status` HTTP 200 ve 6.304 katalog / Analyst / 21 araç bildirdi. Sonraki mimari iş: aynı turdaki *farklı* kaynaklar için bütçeli kaynak seçimi ve model bağlamına giden toplam kanıt miktarını ölçüp sınırlamak; konuya/URL'ye özel kural yazmamak.

### 2.112 Web araştırma sentezi timeout incelemesi (20 Eylül)
- Manuel “Tera holdingin sahibi kimdir, git ve webden araştır” turu **116,2 sn** sürdü: ilk arama 6,0 sn (LLM 4,0 + araç 2,0), sayfa okuma 8,4 sn (LLM 7,0 + fetch 1,3), ikinci arama 41,2 sn (LLM 37,0 + araç 4,3), son narration 60,0 sn'de `LLM_UNAVAILABLE`. İzde toplam model süresi 108,0 sn; 3 başarılı ve 1 başarısız LLM çağrısı, başarılı çağrılarda 11.980 prompt / 624 completion token raporlandı. İkinci arama seçimi `narration` fazında ve 2.800 token tavanıyla çalışmış; bu, mevcut faz seçiminin araştırma aracı kararlarıyla anlatımı ayırmadığını gösteriyor. Fetch başarılı; asıl süre sağlayıcı LLM çağrılarında.
- Kaynak adaylarında “Tera” adı farklı şirketlerle eşleşebildi; ikinci arama yeni adaylar ekledi ama kapsamı netleştirmedi. Arama snippet'leri kanıt değil, okunmuş sayfa da otomatik olarak doğru tüzel kişiyi kanıtlamıyor; kaynak kimliği/iddia kapsamı korunmalı.
- Mimari sonraki adım olarak konuya özel prompt kuralı değil, bütçeli ve durum bilgili bir araştırma orkestratörü değerlendirilecek: sınırlı arama/fetch fan-out, kanıt yeterlilik ve çelişki ölçütüyle durma, kompakt kanıt paketi, kaynak destekli kısa sentez, aşama bazlı deadline ve narration arızasında kanıtı kaybetmeyen yanıt durumu. Henüz bu akış için yeni kod veya karar uygulanmadı.

### 2.113 Tur bütçeli web araştırma orkestrasyonu (20 Eylül, ADR-0096)
- Araştırma denetimi `WebResearchState` ile tur kapsamına taşındı: en çok 3 arama, 5 benzersiz sayfa ve 48.000 karakter dış model bağlamı. Arama sonuçları en çok 5 × 500 karakter snippet; artifact/kanıt izi tam kalır.
- Aynı Unicode/Türkçe normalize edilmiş sorgu tekrar engellenir. Yeni arama için önce önceki adaylardan en az biri okunmalı; ardından model hangi kanıt boşluğunu kapatacağını `research_gap` ile belirtmeli. `web_url.max_pages` kalan tur sayfa bütçesine göre kırpılır.
- Web arama/açma kararları `tool` token fazında kalır; anlatım fazının 60 saniye sınırı web `tool` çağrılarına uygulanmaz, `LLM_TOOL_TIMEOUT_S` ayrı kalır. Böylece gerçek izde ikinci aramanın yanlışlıkla narration sayılması önlenir.
- Dış kanıt metni bütçesi aşılırsa yalnız model bağlamı kırpılır ve güven uyarısı eklenir; kaynak artifact'i korunur. Mevcut source-only narration fallback'i değişmeden devrededir.
- Doğrulama: agent-core tam suite **903 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; web araştırma/hata zarfı hedefli testleri; benchmark v2.1 sözleşme doğrulayıcısı; yeni modül/test Ruff ve `git diff --check`. Canlı MIA/Tavily isteği yapılmadı.
- `.env` değiştirilmedi; `.env.example` daha önceki yapılandırma değişiklikleriyle dirty durumdadır ve bu işte düzenlenmedi. Eski localhost süreci kontrollü durdurulup `uv run python -m kkb_agent.serve` ile yeni kodla yeniden başlatıldı; `/api/status` HTTP 200, 6.304 seri ve 21 Analyst aracı bildirdi. Tünel, lakehouse, commit ve PR değiştirilmedi.

### 2.114 Narration prompt yönlendirmesi incelemesi (20 Eylül)
- Ayrı bir `NARRATION_PROMPT` yok. Faz sınıflandırması `_chat` için token bütçesi/deadline/temperature/reasoning ayarlarını seçiyor; aynı `messages` listesi araç döngüsü boyunca kullanılıyor.
- Yeni tabloyla başlayan turda `_build_messages(..., compact_planning=True)` tek system mesajı olarak `COMPACT_PLANNING_PROMPT` kuruyor ve araçlardan sonra final sentezde de aynı prompt kalıyor. Bu kısa metin ayrıntılı nihai cevap/grounding/sunum sözleşmesini içermiyor. Aktif tabloyla başlayan turda tam `SYSTEM_PROMPT` kullanılıyor.
- `long_narration` ayrı bir çağrı fazı değil; `narration` fazında satır/kolon eşiklerine göre yalnızca token tavanı 3.400'e yükseliyor. Recovery için de ayrı system prompt yok; aynı sistem mesajına user-role `RECOVERY_NOTE`/son tur yönergesi ekleniyor.
- Henüz prompt veya runtime kodu değiştirilmedi. Narration özelleştirmesi istenirse tek system mesajı kısıtını koruyan faz-duyarlı prompt composer tasarlanmalı; yalnız narration sözleşmesi değişmeli, kanıt/uydurmama gibi değişmezler ortak tabanda kalmalı. Benchmark öncesi/sonrası latency, fallback oranı, sayı grounding'i ve çıktı kısalığı ölçülmeli.

### 2.115 İlk faz-duyarlı narration promptu (20 Eylül, ADR-0097)
- `NARRATION_PROMPT` eklendi: alan profiline göre render edilen, yalnız doğrulanmış araç/aktif tablo çıktısıyla anlatım yapan kısa son-yanıt sözleşmesi. Kaynak, dönem, kapsam, birim, eksik kanıt, nedensellik ve UI artifact'ini tekrar etmeme kuralları içerir; benchmark soru metni veya seri kimliği içermez.
- `AnalyticsAgent` normal `narration` çağrısında system mesajının operasyonel prompt bölümünü narration sözleşmesiyle değiştirir. Web kaynağı okunduktan sonraki model çağrısı `tool` süre/token fazında kalır ama kısa anlatım yönergesini kullanır; arama/okuma kararları, deadline ve araç şemaları değişmez. Çalışma/aktif tablo notları, JSON protokolü ve birinci/tek system mesajı korunur; recovery prompt yönlendirmesi sonraki adımdır.
- Prompt geçişi, web sentezine giden yol, aktif bağlamın korunması ve custom system prompt davranışı için sahte LLM testleri eklendi.
- Doğrulama: hedefli agent-loop/web/token testleri **47 geçti**; tam agent-core suite **906 geçti**, bir mevcut Starlette/AnyIO deprecation uyarısı. Tam Ruff kontrolü dirty çalışma ağacındaki önceki biçim kurallarını da raporladı; bu değişen dosyalarda `ruff check --select F` temiz. `git diff --check` ve `compileall` başarılı. Prompt metni `SYSTEM_PROMPT` çekirdeğinden karakter sayısında **%83,4 kısa**; gerçek sağlayıcı token/latency kazanımı henüz ölçülmedi. Canlı MIA/Tavily çağrısı yapılmadı.
- `.env`, lakehouse verisi ve Cloudflare tüneli değiştirilmedi; commit/PR oluşturulmadı. Demo, yeni kodla `127.0.0.1:8765` üzerinde yeniden başlatıldı; `/api/status` HTTP 200, 6.304 seri ve Analyst profilinde 21 araç bildirdi. Sonraki adım manuel narration testi; ardından cevap kalitesi, MIA süresi ve fallback oranını benchmark çıktılarıyla ölçmek. Planning/tool/recovery promptları bu adımdan ayrı ele alınacak.

### 2.116 Takip dönüşümünde dönem etiketi ve hatalı LAG onarımı (20 Eylül, ADR-0098)
- Ekran kanıtındaki sorun takip sınıflandırması değildi: iki takip de API'de `is_follow_up=true`, `operation=period_change` olarak işaretlenmişti. İlk dönüşümde `ay` metin alanı tarih ekseniyle aynı ayları satır satır taşıdığı halde `PARTITION BY ay` olarak seçilmiş; her grup tek satır olunca iki değişim kolonu da boş kalmıştı. Eski doğrulama, değerleri hesapla karşılaştırmadığı için hatalı çıktıyı başarı gibi göstermişti; tekrar isteği de LLM yoluna düşüp narration timeout almıştı.
- Genel çözüm redundant aylık dönem etiketlerini panel gruplamasından çıkarır; persisted türetilmiş değerleri LAG aritmetiğiyle doğrular; yalnızca uygulama provenance'ı ve kaynak snapshot kesin olduğunda geçersiz son dönüşümü önceki doğrulanmış tablodan yeniden hesaplar. Aynı istek artık doğrulanmış sonucu yeniden kullanır; son dönüşümün dönem/kapsam başlığı güncellenir.
- Regresyon testi: yanlış tek-satırlı partition/null üretimini reddetme, 60 satırlı kaynak snapshot'ından 24 satırlı analitik görünümü onarma, ilk görünen aya önceki ay tabanını uygulama ve tekrar isteğinde sıfır LLM çağrısı. Tam agent-core test paketi **907 geçti** (tek mevcut Starlette/AnyIO deprecation uyarısı). İlgili core modüllerinde Ruff `F` ve `git diff --check` temiz.
- Canlı MIA A/B: aynı 24 satırlı doğrulanmış değişim çıktısı, 21 araç şeması, model/ayar ve 2.800 token tavanıyla successful SYSTEM_PROMPT örneği 52,70 sn / 14.461 prompt token; successful NARRATION_PROMPT örneği 77,61 sn / 10.995 prompt token verdi (**%24 daha az giriş tokenı**). 60 saniyelik narration deadline içinde SYSTEM_PROMPT 1/2, NARRATION_PROMPT 0/2 başarılı oldu; ek 120 saniye tanı çağrısı NARRATION_PROMPT'u 77,61 saniyede tamamladı. Bu tek koşuda token tasarrufu doğrulandı, hız artışı doğrulanmadı; 60 saniye SLO başarımı ve tekrarlı latency ölçümü açık.
- Kod/test/ADR güncellendi; demo eski PID kontrollü durdurulup `make serve` ile yeni kodda yeniden başlatıldı. `/` ve `/api/status` HTTP 200; model `kkbhackathon2026/Qwen3.8-27B`, Analyst profilinde 6.304 katalog serisi ve 21 araç; kalıcı sohbet aynı kimlikle yüklendi. `.env`, kaynak veritabanı, tünel, commit ve PR değiştirilmedi.

### 2.117 Anlatım gecikmesi için ölçüm, kompakt olgu paketi ve araçsız son çağrı (20 Eylül, ADR-0099)
- Her LLM çağrısında faz, elapsed süre, ilk görünür token (akış açıksa), prompt/completion tokenı, retry/bekleme, request ID, mesaj ve araç şema boyutu/status kaydediliyor. Araç yürütme, context hazırlığı, narration facts hazırlığı ve tur duvar saati ayrıdır; ham istem ve cevap kaydedilmez. Stream uyumu MIA'da canlı doğrulanmadı ve `LLM_STREAM_NARRATION=false` varsayılan.
- Tamamlanan ve doğrulanan veri işi için model girdisi ham araç konuşması yerine sınırlı `NarrationFacts` paketine düşürülüyor. Tablo ve indirmeler aynen kalıyor; bu paket hesap/analiz yapmıyor. Bekleyen bilinen yetenek, çözülmemiş onarım, başarısızlık veya web araştırmasında tool-free yol açılmıyor.
- Narration timeout doğrulanmış tablo teslimini düşürmüyor; deterministik özet yalnız mevcut tablodan üretiliyor. Artifact boyutu tek başına token bütçesini büyütmüyor; explicit analiz/çoklu kaynak daha geniş metin bütçesi seçiyor.
- Genel `SYSTEM_PROMPT` kritik kaynak/kanıt/hesap/uyarı/aktif tablo/yanıt kuralları korunarak 5.373 → 2.679 karaktere (**%50,1 daha kısa**) indirildi. Bu karakter farkıdır; provider token ve latency kazanımı canlı ölçülmedi. İlk sorular benchmark/test içeriğine taşınmadı.
- Doğrulama: agent-core **915 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; ilgili kodlarda Ruff `F` temiz ve `git diff --check` temiz. Tüm repo Ruff taraması dirty ağacın bu değişiklik dışındaki 25 önceden var olan uyarısını raporladı. Canlı MIA testi henüz yapılmadı.
- Gerçek `.env`, lakehouse veritabanı, Cloudflare tüneli, commit ve PR değiştirilmedi. Eski localhost süreci kontrollü durdurulup `make serve` ile yeni kodda yeniden başlatıldı (PID 75979); `/api/status` HTTP 200, 6.304 katalog serisi ve Analyst profilinde 21 araç bildirdi. `LLM_STREAM_NARRATION` varsayılanı kapalı olduğundan manuel MIA testi mevcut non-stream davranışla yapılabilir; streaming canary ayrı doğrulanmalı.

### 2.118 V2 ilk 10 vaka izole MIA benchmark koşusu (20 Eylül)
- P01–P06 ve R01–R04, V2.1 `agent_cli` sözleşmesine göre vaka başına yeni agent/workspace ile bir kez çalıştırıldı. Yerel lakehouse ve retrieval indeksi ortak/sıcak kaldı; önceki sohbet/aktif tablo durumu vakalar arasında taşınmadı. Ham iz `docs/experiments/v2_mia_first10_isolated_20260920.jsonl`, CSV'ler aynı adlı `_tables/` dizininde, skor `v2_mia_first10_isolated_20260920_score.md`.
- 10 vaka toplam 795,26 sn; p50 85,10 sn, p95 129,74 sn. 59 LLM çağrısı, 384.662 prompt/5.499 completion tokenı; 7 başarısız çağrı (4 narration, 3 recovery; her biri ≈60 sn). Başarısız çağrılarda sağlayıcı request ID/token kullanımı yok.
- Sayısal oracle/source değerleri P01, P03, P04, P06 ve R01'de eşleşti. P04 temiz workspace'te doğru 16 çeyrek ve iki ulusal seri üretti; önceki UI koşularındaki state sızıntısı bu vakada desteklendi. P02'de Ocak 2023 LAG değeri boş kaldı (Aralık 2022 tabanı yok). P05/R02/R03'te arama/recovery döngüleri ve 2'şer yinelenen çağrı; R04'te `GOLD_REQUIRED` + `UNVERIFIED_SEMANTICS` güvenli duruşu görüldü.
- Temel sonuç: narration hatası veri artifact'ini koruyor fakat istenen açıklamayı tamamlamıyor; tablosuz P05/R02/R03 recovery timeout'u genel servis hatasına düşüyor. P05/R02/R03 uzun arama döngüleri 48k–129k prompt tokenına çıktı; deterministik katalog aday listesi ve duplicate/arama bütçesi bitince kısa geri çekilme mimari önceliktir. P02 görünür aralığın öncesindeki LAG tabanını filtre öncesi dahil etmiyor. R04 güvenli refusal olarak sayısal completion değildir; semantik güven/oracle sözleşmesi ayrıca netleştirilmeli.
- Benchmark koşusu kod, `.env`, lakehouse ve tünel değiştirmedi. Bu on vaka, tam 71'lik MIA benchmark skoru değildir.

### 2.119 Sınırlı katalog orkestrasyonu ve kompakt recovery (20 Eylül, ADR-0100)
- Genel harness iyileştirmesi olarak `lakehouse_search` tur bütçesi varsayılan 5 gerçek çağrıya ayarlandı ve kurucudan değiştirilebilir hale getirildi. Bütçe aşımı `CATALOG_SEARCH_BUDGET` terminal hatasıdır; arama sınırına ulaşmak veri yokluğunu kanıtlamaz. Recovery artifact'ine arama sayısı/sınırı/doygunluk bilgisi eklendi.
- Recovery ve adım/süre kapanışı tüm model/araç konuşmasını yeniden göndermek yerine son kullanıcı isteğini, availability durumunu, son dört hata özetini, yalnız doğrulanmış tablodan `NarrationFacts`'i ve en çok üç yerel katalog/şema çıktısını taşır. Ham web içeriği ve diğer araç geçmişi dışarıda kalır.
- Recovery LLM çağrısı kesilirse harness yetkili yokluk, erişim engeli ve retrieval failure durumlarını ayrı deterministik mesajlarla korur. Retrieval hatası “veri yok” diye sunulmaz; `UNKNOWN` durumda mevcut genel kesinti davranışı sürer.
- Regresyonlar: arama bütçesi/kompakt bağlam, recovery timeout'unda yanlış yokluk iddiası üretmeme ve doğrulanmış yokluk durumunu koruma. İlk 10 vaka içindeki sorulara özel prompt/kural eklenmedi.
- Doğrulama: `agent-core` tam suite **918 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; ilgili Python dosyalarında Ruff `--select F` temiz; `git diff --check` temiz; benchmark sözleşme doğrulayıcısı **120 vaka / 76 oracle / 31 artifact** geçti. Gerçek MIA tekrar koşusu yapılmadı; bu sonuç latency kazanımı kanıtı sayılmaz.
- Henüz demo süreci yeni kodla yeniden başlatılmadı. Sonraki adım: yerel endpoint'i kontrol et, gerekiyorsa yeniden başlat; sonra aynı izole ilk-10 MIA alt kümesinde arama sayısı, recovery context boyutu, retrieval/narration fallback, doğruluk ve gecikmeyi baseline ile karşılaştır. Beş arama sınırının geçerli karmaşık işlere etkisini birlikte incele.

### 2.120 Sınırlı katalog orkestrasyonu — MIA A/B sonucu ve sınır etkisi (20 Eylül)
- İlk izole P01–P06/R01–R04 tekrarında 10 vaka toplamı **795,26 → 640,53 sn** (−19,5%), prompt tokenı **384.662 → 245.440** (−36,2%), LLM çağrı izi 59 → 49 ve başarısız çağrı 7 → 6 oldu. Tek sağlayıcı koşusu olduğu için hız farkı kararlılık/causality kanıtı değildir; ayrıntılı puan [`docs/experiments/v2_mia_first10_recovery_arch_20260920_score.md`](docs/experiments/v2_mia_first10_recovery_arch_20260920_score.md).
- P05 prompt tokenı 128.566 → 49.922; R03 48.200 → 24.824. R03 yanlış nominal seri seçmeden güvenli, kısmi kapanış verdi. R02 aynı 64.121 token ve recovery timeout'unda kaldı. P01/P02/P04/P06 narration timeout'ları sürdü. R04 arama bütçesi nedeniyle Gold semantik doğrulamasına ulaşmadı; tablosuz ve güvenli kaldı. P02'nin Ocak LAG tabanı kusuru devam etti.
- Ek kısmi tanı koşusunda P05 284,50 sn, 12 model çağrısı, 137.144 prompt tokenı ve 4 katalog araması sonunda boş anlatımla/sıfır tablo satırıyla tamamlandı. Beş arama bütçesine erişmedi; bu nedenle bütçe kapısı bu vakayı durdurmadı. R02 başında sağlayıcı HTTPS/TLS handshake beklemesi görüldü; koşu skorlanmadan durduruldu. Bu ham iz, tam benchmark kabul edilmemeli.
- Sonraki mimari adım: aynı içerik/adayları döndüren keşiflerin ve boş metadata sorgularının gerçek ilerleme üretip üretmediğini ölçen, yalnız çağrı sayısına dayanmayan genel progress/yield kapısı. Arama sınırı körlemesine yükseltilmemeli; R04 gibi çok varlıklı isteklerde ilgili yeni aday verimi ve güvenli semantik doğrulama birlikte değerlendirilmelidir.

### 2.121 Terminal recovery ve boş final yanıtı koruması (20 Eylül, ADR-0101)
- `DUPLICATE_CALL` ve `CATALOG_SEARCH_BUDGET` sonrası, bu turda doğrulanmış tablo yoksa yeni MIA recovery anlatımı yapılmadan deterministik ve availability durumunu koruyan yanıt üretilir. Bu “veri yok” demek değildir; aday çıktısı varsa araç adımlarına işaret edilir.
- Model reasoning temizlendikten sonra final metni boşsa yanıt artık boş kalmaz. Doğrulanmış aktif tablo varsa tablo/indirme korunur ve yalnız tabloya bağlı kısa facts/özet gösterilir; yoksa yokluk, erişim, retrieval failure ve bilinmeyen durumlar ayrı ifade edilir.
- Yeni testlerle terminal arama bütçesi, duplicate döngüsü, boş final yanıtı ve tablo koruması doğrulandı. Tam `agent-core` suite **922 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; benchmark sözleşme validator'ı **120 vaka / 76 oracle / 31 artifact** geçti; Ruff `--select F` ve `git diff --check` temiz.
- Kısmi canlı MIA tanı koşusu son boş-final korumasından önce tamamlandı; bu korumanın sağlayıcı latency etkisi canlı koşuda doğrulanmadı. Ardından demo yeni kodla `make serve` üzerinden yeniden başlatıldı; `/api/status` HTTP 200, Analyst, 6.304 katalog serisi ve 21 araç gösterdi. Commit/PR yok.

### 2.122 Güncel mimariyle ilk 10 MIA vakasının yeniden koşulması (20 Eylül)
- P01–P06 ve R01–R04, V2.1 `agent_cli` benchmark'ında vaka başına yeni agent/workspace, tek tekrar ve en çok 12 adımla çalıştırıldı. Ham iz `docs/experiments/v2_mia_first10_current_20260920.jsonl`, CSV'ler aynı adlı `_tables/` dizininde, doğruluk ve hız değerlendirmesi `docs/experiments/v2_mia_first10_current_20260920_score.md`.
- Güncel koşu 541,14 sn toplam / 46,15 sn p50 / 129,26 sn en uzun vaka; 276.374 prompt, 11.895 completion tokenı, 47 LLM çağrısı ve 2 başarısız çağrı verdi. Önceki recovery koşusuna göre toplam −15,5%, p50 −41,1%, başarısız çağrı −66,7%; en uzun vaka +52,7%, prompt tokenı +12,6%, completion tokenı +115,2% oldu. Tek sağlayıcı tekrarıdır, cache/yük kontrol edilmedi. P05 ve R04 arama bütçesinde işi tamamlamadan erken kapandığı için medyan kazanımı başarı sayılmamalı; bu iki tamamlanmamış vakayı çıkarınca kalan sekiz vakanın p50’si önceki recovery koşusundaki 78,52 sn’den 59,51 sn’ye (−24,2%) düştü.
- Oracle doğrulamasında P01, P06 ve R01 tam eşleşti; P03 geçerli 36 aylık başka bir pencere seçti ve ortak 18 ay oracle ile eşleşti, fakat seçim gerekçesi zayıf. P04 tüm tablo değerlerini eşleştirdi ancak anlatımda mevduat artışının her çeyrek kredi artışını aştığına dair iki çeyrekte yanlış iddia var. P02 Ocak LAG farkını hâlâ boş bıraktı. P05 aday/kapsam yanıtını, R02 beklenen 87 katalog adayını/metadatayı, R04 FinTürk il-yıl ortalamalarını üretmedi. R03 doğru biçimde nominal USD/EUR ikamesi yapmadı ama 10 LLM çağrısı ve 129,26 sn ile gereğinden pahalı kaldı. Genel değerlendirme: 4 geçti, 2 kısmi, 4 başarısız.
- Mimari çıkarım: arama bütçesi yalnız çağrı sayısıyla kapanmamalı; eldeki adaylardan ilerleme/iş tamamlanabilirliği değerlendirilmeden deterministik ret vermek P05/R04’ü kesiyor. Trend narrasyonu doğrulanmış hesaplanmış facts ile denetlenmeli; negatif bulgu araştırması da kapsama göre deterministikleştirilmeli. Kod değiştirilmedi; bu kayıt benchmark sonucudur.

### 2.123 Güncel mimariyle 71-vaka MIA benchmark denemesi (20–21 Eylül)
- V2.1 `agent_cli` seçkisi 71/71 vaka için çalıştırıldı ve ham iz `docs/experiments/v2_mia_71_full_current_20260920.jsonl` dosyasına, 25 tablo artifact’i yanındaki `_tables/` dizinine yazıldı. Runner sözleşmesi ayrıca 120 prompt / 76 oracle / 31 artifact ve 71 CLI vakası olarak doğrulandı.
- L05’te MIA `401 AuthenticationError: API key expired or inactive` verdi; A01 dışında kalan 32 sonraki vaka da aynı hatayla LLM’e ulaşmadı. Böylece toplam 33 servis-auth hatası oluştu. Erişebilen 38 vakada 16 `recovered_with_llm_failure`, 22 `executed_needs_review`; 25 artifact’te 872 satır var. Runner durumu doğruluk puanı değildir; auth nedeniyle bu koşuya tam 71 vaka pass/partial/fail puanı verilmedi. Hata raporu `docs/experiments/v2_mia_71_full_current_20260920_status.md`.
- Önceki koşudaki aynı 38 erişilebilir vaka ile tek tekrarlı karşılaştırmada medyan 149,68 → 92,71 sn (−38,1%), ortalama 159,42 → 120,77 sn (−24,2%), fakat p95 296,45 → 358,13 sn (+20,8%) oldu. Başarısız LLM çağrısı 34 → 16, prompt tokenı 1.785.632 → 1.644.161 (−7,9%), completion tokenı 26.905 → 62.547 (+132,5%). Servis yükü/cache kontrollü tekrar yok; bu ölçüm hız/kalite kanıtı değildir.
- `.env`, kod, lakehouse, demo ve tünel değiştirilmedi. Sonraki koşudan önce yetkili ortamda MIA erişimi düzeltilmeli; benchmark runner’a sistemik 401’i ilk oluştuğunda tanıyıp kalan vakaları çağırmayan preflight/circuit breaker eklenmeli. Mevcut kısmi koşu yeni tam benchmark baseline’ı değildir.

### 2.124 Kloudeks/MIA ayarlarının geri yüklenmesi (21 Eylül)
- Geçici harici sağlayıcı denemesi kaldırıldı. Kök `.env` tekrar `.env.example` içindeki MIA/Kloudeks ayarlarına döndürüldü: `https://mia.csp.kloudeks.com/v1`, `kkbhackathon2026/Qwen3.8-27B`, MIA embedding ve Unlimited-OCR; `LLM_API_KEY` `MIA_API_KEY` değişkenini kullanıyor, reasoning kapalı.
- `config.py` sağlayıcı etiketi yerel Ollama/Kloudeks davranışına geri döndü. Geçici sağlayıcıya ait endpoint, model ve API anahtarı yerel `.env`'de bırakılmadı. Demo yeniden başlatıldı; `/api/status` HTTP 200 ile 6.304 seri ve 21 aracı doğruladı. Canlı preflight MIA'dan `401 API key expired or inactive` döndürdü; Kloudeks ayarları geri yüklendi fakat MIA anahtarının yenilenmesi gerekiyor. Tünel kapalı, kod commit edilmedi.

### 2.125 Lakehouse CI A/C zaman aşımı ve bootstrap maliyeti (21 Eylül)
- Actions `35538510918` (`7d0009e`) içinde A ve C test job'ları 60 dakikada `cancelled` oldu; son pytest ilerlemesi A %29, C %62 idi. B tamamlandı. Assertion sonucu/stack trace yok; gerçek neden 6.304 aktif seri kapsamına göre eski A/B/C parçalarının artık fazla büyük olması. `tests-lakehouse.yml` A–H sekiz parçaya dağıtıldı; 15 test dizininin tam ve çakışmasız kapsandığı YAML/coverage kontrolü geçti. Test komutuna `--durations=20` eklendi. Yeni Actions süresi henüz ölçülmedi; dosya değişiklikleri push/PR edilmedi.
- `load_series_catalog` her bootstrap'ta ilişki grafiğinin tamamını ayrı ayrı yeniden yazıyordu. Relation hash'i değişmeyen satırlar artık atlanıyor, değişenler tek `executemany` batch'iyle yazılıyor. Geçici DuckDB benchmark'ında tekrar bootstrap **5,766 s → 0,717 s** (−%87,6); ilk bootstrap 6,884 s / 7,502 s olduğundan ilk kurulumda hız kazanımı ölçülmedi.
- Regresyon doğrulaması: ilişki idempotency/update + catalog bootstrap testleri **22 geçti**; acceptance **37 geçti**; tam test keşfi **1.133** vaka. Tam lakehouse suite yerelde başlatıldı ancak büyük katalog maliyeti nedeniyle tamamlanmadan durduruldu; tam suite sonucu iddia edilmiyor. Workflow değişiklikleri ve relation batch yolu için CI'ın yeni A–H koşusu gerekir.

### 2.126 MIA erişiminin geri gelmesi (21 Eylül)
- Yerel demo `127.0.0.1:8765` üzerinde çalışıyordu ve `/api/status` HTTP 200 verdi. Salt-okunur `uv run python -m kkb_agent.cli --preflight --live` kontrolü tam hazır sonucu verdi; canlı MIA ping'i `kkbhackathon2026/Qwen3.8-27B` üzerinden `hazır` yanıtı aldı.
- Önceki 401/API key expired hatası şu an tekrarlanmadı. Model/sağlayıcı, prompt, token veya ortam ayarı değiştirilmedi; bu yalnızca servis erişiminin geri geldiğini doğrulayan kısa sağlık çağrısıdır.
- Ardından eski demo PID'si kontrollü durdurulup `make serve` ile `0b76fad` commitindeki kod yeniden başlatıldı. `/` ve `/api/status` HTTP 200; katalog 6.304 seri ve araç sayısı 21; başlatma logu Kloudeks/Qwen3.8-27B'yi, canlı preflight da başarılı `hazır` yanıtını doğruladı.

### 2.127 Cloudflare demosu tekrar açıldı (21 Eylül)
- Aynı `agent-smith-demo` Cloudflare tunnel connector'ı mevcut token-file ile tekrar çalıştırıldı; Cloudflare uzaktan hostname ingress yapılandırmasını `agent-smith-demo.bardaka.site` → `http://localhost:8765` olarak yükledi ve connector kaydoldu.
- Public `/` ve `/api/status` HTTPS kontrolleri HTTP 200 verdi. Public status aynı `kkbhackathon2026/Qwen3.8-27B` modelini, 6.304 katalog serisini ve 21 aracı gösterdi. Token/secret proje dosyasına yazılmadı; uygulama kodu ve `.env` değiştirilmedi.

### 2.128 Aynı sorguda 22,8 sn / 51,9 sn gecikme farkı (21 Eylül)
- İki ayrı yeni sohbette aynı soru tam metin eşleşti. Önceki yanıt **22,834 sn**, yenisi **51,868 sn**; ikisi de Qwen3.8-27B ile 3 LLM çağrısı, 5 başlangıç / 14 maksimum araç şeması, 0 başarısız çağrı ve 0 retry kullandı. Prompt/completion tokenları sırasıyla 10.177/478 ve 10.082/421; boyut farkı ihmal edilebilir.
- LLM çağrı süreleri toplamı **13,63 → 42,23 sn** (+28,60 sn); araç yürütmesi **1,05 → 1,72 sn**, context hazırlığı her ikisinde de yaklaşık 0,05 sn. Üç planlama çağrısının süreleri 0,96/2,39/10,27 sn'den 6,75/9,42/26,07 sn'ye çıktı. Ek 29,03 saniyenin neredeyse tamamı provider çağrılarında; harness/tool yolu belirgin değişmedi.
- En kuvvetli açıklama Kloudeks/MIA serving latency değişkenliği (muhtemel kuyruk/iş yükü/cold-start); ancak stream kapalı olduğundan TTFT yok ve provider kuyruğu ile model üretim süresi ayrılamıyor. Bu gözlem kod, token ayarı veya Cloudflare kaynaklı bir değişiklik kanıtı değil; tekrarlı eşzamanlı canary ve streaming TTFT metriğiyle izlenmeli.

### 2.129 Narration timeout'unun 100 saniyeye çıkarılması (21 Eylül)
- Kullanıcı isteğiyle `LLM_NARRATION_TIMEOUT_S` varsayılanı 60 → 100 saniyeye çıkarıldı. Sağlayıcı istemcisinin tek çağrı üst sınırı 90 sn'de narration'ı keseceği için `LLM_TIMEOUT` da 100 sn oldu; tool fazı kendi 90 sn deadline'ıyla sınırlı, soru bütçesi 600 sn. Bu nedenle planlama gibi araçsız LLM çağrılarının genel tek-çağrı tavanı da 90 → 100 sn yükseldi.
- `.env.example` ve yerel `.env` aynı iki değere ayarlandı; ortam değişkeniyle farklı değer verme desteği korunuyor.
- Doğrulama: settings/default+override, agent doğrudan-varsayılanı, narration deadline ve web research testleri **8 geçti**; etkin ayarlar `LLM_TIMEOUT=100`, `LLM_NARRATION_TIMEOUT_S=100`, `LLM_TOOL_TIMEOUT_S=90`. Değişen modüllerde Ruff `F` ve `git diff --check` temiz; geniş Ruff kural seti `agent.py` içindeki bu değişiklikten bağımsız mevcut biçim uyarılarını raporluyor. Demo PID 8873 ile yeniden başladı; yerel ve Cloudflare `/api/status` HTTP 200 verdi, tünel prosesi korundu.

### 2.130 Kloudeks DeepSeek alternatif model erişimi (22 Eylül)
- Mevcut `.env` içindeki MIA/Kloudeks anahtarıyla salt sağlayıcı kontrolleri yapıldı; `/v1/models` exact model kimliği `deepseek-ai/DeepSeek-V4.1-Flash` olarak listeliyor.
- Aynı modelle doğrudan chat canary’si HTTP 200/`stop` verdi; native function-tool canary’si HTTP 200/`tool_calls` ile `echo` çağrısı ve argüman üretti. Bu, modelin agent’in OpenAI-uyumlu araç protokolüne erişilebilir olduğunu gösterir; tam 71-vaka kalite benchmarkı değildir.
- Demo’nun mevcut modeli değiştirilmedi: `LLM_MODEL=kkbhackathon2026/Qwen3.8-27B`. DeepSeek’i denemek isteyen ekip yalnızca kendi yerel `.env` dosyasında `LLM_MODEL=deepseek-ai/DeepSeek-V4.1-Flash` seçebilir; API anahtarı veya değeri repoya yazılmadı.

### 2.131 Seri seçimi için dönem ve semantik uyum kapısı (22 Eylül)
- 60 satırlı BDDK sorgusunda kredi kartı kolonu boş kalıyordu çünkü model `bddk_monthly:1897_Toplam` adlı türetilmiş “Kredi Kartları (Krediler)” serisini seçmişti. Bu seri 2022-01'de başlıyor ve “Bireysel Kredi Kartları, Toplam (Sektör)” doğrulanmış `bddk_monthly:1539_Toplam` serisinin yerine geçemiyor; ihtiyaç kredisi serisi doğruydu. 60 aylık dış pencerenin otomatik olarak 2021-01→2025-12 çözülmesi beklenen davranış olarak kaldı.
- Genel mimariye iki savunma eklendi: retriever, bağlaçsız çoklu kavram sorgularında kısa kavram ifadelerini de aday havuzuna katar; `lakehouse_query` SQL çalıştırmadan önce kullanılan aylık serilerin çözülmüş dış pencereyi tamamen kapsadığını ve daha güçlü doğrulanmış alternatif varken türetilmiş seriye düşülmediğini kontrol eder. Uyuşmazlıklar `SERIES_COVERAGE_MISMATCH` / `SERIES_SEMANTIC_MISMATCH` olarak yapılandırılmış ve recovery semantic guard'a bağlanmıştır.
- Regresyonlar: seçilen kısa seri SQL çalışmadan reddediliyor ve tam kapsamlı doğrulanmış aday öneriliyor; bağlaçsız ihtiyaç + bireysel kart sorgusu iki kavramı aynı aday havuzunda koruyor. Hedefli lakehouse/retrieval/recovery testleri **80**, tam `agent-core` suite **947** geçti; yalnız mevcut Starlette/AnyIO deprecation uyarısı var. `compileall`, değişen dosyalarda Ruff F ve `git diff --check` temiz.
- Demo kontrollü biçimde bu kodla yeniden başlatıldı; `/api/status` HTTP 200, DeepSeek modeli, 6.304 seri, 21 araç ve 7 Gold tabloyu bildirdi. Aynı kullanıcı sorusu API üzerinden başarıyla tamamlandı: 60 satır, iki dolu seri (`1536` + doğrulanmış `1539`), 5 LLM çağrısı, 15,7 sn; yanlış `1897` serisi seçilmedi. `.env`, veritabanı ve Cloudflare tüneli değiştirilmedi. Kod/test/memory değişikliği yerel bir committe; henüz push/PR yok.

### 2.132 Dönüşüm çıktısında kullanıcı penceresi ile aktif çalışma tablosunu ayırma (22 Eylül)
- Ekrandaki 24 dönemlik takip dönüşümü anlatımda doğru görünürken UI/CSV/XLSX kartı aktif 60 satırlı workspace'i dışa aktarıyordu. LAG tabanının korunması için workspace'in tam pencere olması doğrudur; hata, `project_result_table`'ın deterministic fast path `result_data` görünümünü ve reuse proof'un dönem sınırlarını yok sayıp tekrar tam workspace'e dönmesiydi.
- Genel projeksiyon katmanı düzeltildi: deterministic fast path'ın zaten kapsamlandırılmış `result_data`'sı kullanıcı artefaktına taşınıyor; verified workspace reuse'ta yalnız `period_start`–`period_end` aralığı filtreleniyor. Aktif workspace 60 satır olarak korunuyor, kullanıcı tablosu ve indirilebilir dosyalar istenen 24 satırı taşıyor. Ortak `_compute_result_projection` helper'ı kolon seçim mantığını iki yoldan da aynı tutuyor.
- Regresyonlar: takip dönüşümü API payload'ı 24 satır ve 2023-01–2024-12 sınırlarıyla; deterministic fast path üzerinde 60 satırlı workspace'e karşı UI/CSV/XLSX 24 satırla doğrulanıyor. İlgili projection/follow-up testleri **50 geçti**, tam `agent-core` suite **947 geçti**; tek mevcut Starlette/AnyIO deprecation uyarısı. `ruff --select F` ve `git diff --check` temiz.
- `.env`, lakehouse, provider, model ve Cloudflare tüneli değiştirilmedi. Değişiklikler henüz commit edilmedi; demo süreci mevcut eski kodla çalışıyor ve commit sonrası kontrollü yeniden başlatılıp canlı takip akışı doğrulanmalı.

### 2.133 Fast path'in kanıt metadatasını analitik seri saymaması (22 Eylül)
- Canlı takip akışında 24 satır kapsamı düzeldikten sonra BDDK Gold kanıt kolonları (`::observations`, `::missing_observations`) da numeric oldukları için `*_change` kolonlarına dönüştürülüyordu. Bunlar ölçüm serisi değil lineage metadata'sıdır ve kullanıcı projeksiyonuna girmemelidir.
- `plan_verified_workspace_transform` artık ortak provenance kolon filtresini kullanıyor; gerçek ölçü kolonları üzerinde dönüşüm yapılırken kanıt kolonları hesaplanmıyor. Bu generic kural BDDK dışındaki Gold/workspace tablolarında aynı suffix sözleşmesine sahip metadata için de geçerlidir.
- Yeni regresyon testi numeric provenance kolonlarının plan dışı kaldığını doğruluyor. Önceki 947 teste ek hedefli test çalıştırılacak; commit ve demo yeniden başlatması bu ek değişiklikten sonra yapılmalı.

### 2.134 24 satırlı takip çıktısının canlı doğrulaması (22 Eylül)
- UI/export kapsamı düzeltmesi `92dae5f` ve kanıt filtresi `6cb35f3` commitleriyle yerel dala alındı; untracked benchmark/deney dosyaları commit kapsamına alınmadı.
- Tam `agent-core` suite **949 geçti** (tek mevcut Starlette/AnyIO deprecation uyarısı); hedefli projection/follow-up/workspace suite **64 geçti**. `ruff --select F` ve `git diff --check` temiz.
- Yeni demo kontrollü biçimde PID 11233 ile `127.0.0.1:8765` üzerinde çalışıyor; DeepSeek `deepseek-ai/DeepSeek-V4.1-Flash`, 6.304 seri ve 21 araç aktif. Aynı iki sorunun canlı akışında ilk tablo 60 satır; takip dönüşümü 2022-01-31–2023-12-31 arasında 24 satır, yalnız iki gerçek `value_change` kolonu, 0 başarısız LLM çağrısı verdi. `table.csv` 24 veri satırı, `table.xlsx` 24 veri satırı olarak ayrıca doğrulandı.
- Aktif workspace tam 60 aylık pencere olarak korunuyor; bu, sonraki takiplerde Aralık 2021 tabanıyla LAG hesaplamasını ve kapsam değişikliğini bozmuyor. Cloudflare, `.env`, lakehouse ve provider ayarları değiştirilmedi; PR/push yapılmadı.

### 2.135 Teknik kolon adlarını kullanıcı etiketlerine ayırma (22 Eylül)
- Gold birleşiminden gelen `<seri>@<varlık>::value` ve `...::value_change` isimleri UI/export başlıklarında ham haliyle görünüyordu. Yeni `display_column_labels` katmanı katalogdaki seri adı, ölçüm alias'ı ve birimden okunur etiket üretir; `Dönem`, `ihtiyaç kredisi (milyon TL)` ve `ihtiyaç kredisi — değişim (milyon TL)` gibi başlıklar gösterilir.
- Bu yalnızca sunum projeksiyonudur: DataFrame kolon kimlikleri, provenance, SQL ve kanıt paneli değişmez. JSON payload başlıklarıyla CSV/XLSX başlıkları aynı etiketlerden üretilir; katalog eşleşmesi yoksa teknik isim korunur, anlam uydurulmaz. Kullanıcı dosyaları ve zaten okunur kolonlar etkilenmez.
- `test_labels.py` ile katalog semantiği, birim ve türetilmiş kolon adlandırması; web/export testleriyle geriye dönük davranış doğrulandı. Tam `agent-core` suite **950 geçti**, tek mevcut Starlette/AnyIO deprecation uyarısı; `ruff --select F` ve `git diff --check` temiz. Demo, commit sonrası yeniden başlatılıp Gold başlıkları canlı kontrol edilmeli.
