# PROJECT_MEMORY — KKB Hackathon 2026, "Lakehouse Agent Builder and Data Analytics"

> Adım adım ne yaptığımızın kaydı. Her adım tamamlanınca buraya bir bölüm eklenir: ne
> yapıldı, neden, ne ölçüldü, hangi ADR ve commit. Gerekçelerin tamamı `docs/adr/` altında;
> burası harita, oradaki kayıtlar bölge.
>
> Son güncelleme: 12 Eylül 2026 (D1 sonrası) · Dal: `feature/agent-engine` · Veri bacağı:
> `feature/lakehouse-integration-r3` (`4802ba4`)

---

## 0. Değişmeyen kurallar

| Kural | Nereden |
|---|---|
| Her mimari karar `docs/adr/` altına, gerekçe ve ölçümle. Şu an 38 ADR. | Takım kararı |
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
- **Demo seti** 5 → 127 seri (~43 çekiliş grubu). G12 "yüklenmemiş seri" vakası taşıttan Van iline taşındı (taşıt artık yüklü).
- Alınmayan: haftalık ek kalemler (konumsal kimlik), KOBİ (sütun belirsiz), üretilmiş EVDS `unknown` serileri.
- **Ölçüm (sıfırdan):** bootstrap 2 s, canlı ingest **197 s** (127/127; FinTürk 264 artifact = 12 il × 22 çeyrek), Silver 2 s **8.290 satır**, Gold 1 s **6 tablo** red 0. İki kaçak: rasyo "(%)" birimi Silver'ın incelenmiş birim tablosunda yoktu (`% → pct`); FinTürk'te bir çekilişin 8 serisi Bronze'da çekilişin `dataset_id`'sini taşıyor → yeni sütunlar ilin konut `dataset_id`'sini aldı. Senaryolar 10/11 → G17 düzeltmeleri (Unicode eksi, olumsuz nedensellik, p eşiği, ikinci geri gönderme) → G17 3/3, G9 3/3, G12 (Van) 2/2. Adım sayıları arttı (G1 1 → 3, G14 4 → 8): büyük katalogda model daha çok arıyor; araç kapısı sıradaki iş. Lakehouse: `% → pct` birim eşlemesi; üç test yeni katalog durumuna uyarlandı (kataloglanmayan sütun sentetik, Gold refused sayısı katalogdan türetilir); paket 1.079 test. Dal `feature/lakehouse-catalog-breadth` itildi (r3 üstüne, main değil).

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

## 3. Bugünkü sayılar

| Ölçüm | Değer |
|---|---|
| Agent birim testi | 315 |
| Lakehouse testi (r3 + genişlik dalı) | 1.079 |
| ADR | 43 |
| Golden vakası | 21: seed G1–G7 5/5; gerçek DB G8, G10, G11a–c, G12, G13 5/5, G14 3/3, G15–G17 3/3, G18a/b 2/2; G9 4/5. Demo kabul sıfırdan 8/8; 13 Eyl 11 senaryo 11/11 |
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

**Yol haritası (sırayla):**
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
