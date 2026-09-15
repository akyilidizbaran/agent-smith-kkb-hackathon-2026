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
