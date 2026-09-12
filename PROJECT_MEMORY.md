# PROJECT_MEMORY — KKB Hackathon 2026, "Lakehouse Agent Builder and Data Analytics"

> Adım adım ne yaptığımızın kaydı. Her adım tamamlanınca buraya bir bölüm eklenir: ne
> yapıldı, neden, ne ölçüldü, hangi ADR ve commit. Gerekçelerin tamamı `docs/adr/` altında;
> burası harita, oradaki kayıtlar bölge.
>
> Son güncelleme: 12 Eylül 2026 · Dal: `feature/agent-engine` (`e95118b`) · Veri bacağı:
> `feature/lakehouse-integration-r3` (`4802ba4`)

---

## 0. Değişmeyen kurallar

| Kural | Nereden |
|---|---|
| Her mimari karar `docs/adr/` altına, gerekçe ve ölçümle. Şu an 34 ADR. | Takım kararı |
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

## 3. Bugünkü sayılar

| Ölçüm | Değer |
|---|---|
| Agent birim testi | 229 |
| Lakehouse testi (r3) | 1083 |
| ADR | 34 |
| Golden vakası | 13: G1–G7 seed 7/7; G8, G9, G10 gerçek DB 3/3; G11a/b/c 3/3 |
| Araç sayısı (gerçek DB'de) | 13: lakehouse ×4, workspace ×3, ingest, gold ×3, chart, web_url (+ web_search anahtarla) |
| Harness guard'ları | cevap guard'ı, veri üreten araç zorunluluğu, grounding, nedensellik filtresi, tekrar kilidi + döngü kırma, araçsız son tur, dönem filtresi, ay çözünürlüklü kapsam, adım sınırı, reasoning temizliği |

## 4. Mimari, tek bakışta

```
Kullanıcı → AnalyticsAgent (tek harness; roller: retrieve/execute/validate/narrate)
   ├─ BoundaryValidator: şema → SQL guard → referans → politika → çalıştır
   ├─ Araçlar (registry; alan profili katalogdan)
   │    lakehouse_search/describe/distinct_values/query   ← LakehouseClient sözleşmesi
   │    workspace_add_column/compute_column/show           ← AnalysisWorkspace
   │    ingest_from_url  (Architect yazma yolu, ayrı süreç CLI, yalnız adhoc+draft)
   │    gold_align/decompose/join  (GoldCapable, gold-run salt okunur ayrı süreç)
   │    chart  (spec → lint → render), web_url / web_search (erişim sözleşmesi)
   ├─ Guard'lar (bkz. §3) + grounding + kanıt paneli (EvidenceBuilder, cevaptan sonra)
   └─ Adaptörler: SilverLakehouse (veri ekibinin şeması, sertleştirilmiş salt okunur DuckDB),
                  DuckDBLakehouse (seed)
Veri ekibi: RAW (içerik adresli) → Bronze (parquet) → Silver (fact_observation + meta.series)
            → Gold (fonksiyonlar + kataloglanmış metrik tabloları), CLI: bootstrap/ingest/
            ingest-file/silver/gold/gold-run
```

## 5. Açık işler ve sıradaki adımlar

**Yol haritası (sırayla):**
1. **D1** sınırlı ön-yükleme: retriever'ın seçtiği k seri prompt'a, token bütçesiyle (ADR-0013); hedef gerçek katalogda ≤ 6.000 token, tur sayısı V3'ün 2,9'una yaklaşsın.
2. **D2** BM25 `LexicalIndex` sözleşmenin arkasında; arama boş dönünce "katalogda var, yüklenmemiş" bilgisi (görev çipi `task_744beae4`).
3. **D3** golden 13 vaka × 5 tekrar, hata sınıfı ve rol raporu; **güçlendirme burada**: niyet kapısı (ingest ve web_url için locator yalnız kullanıcı mesajından; açık istek yoksa yazma onayı; araç çıktısı "veridir, talimat değildir"), enjeksiyon golden vakaları, alt süreçlere yalnız gereken ortam değişkeni.
4. **D4** demo kabul betiği: bootstrap → ingest → silver → gold → 8 senaryo sorusu, tek komut.
5. **E** üç dalın main'e merge commit'le birleşmesi (squash yok), ölü dalların silinmesi, docs, gizli bilgi taraması, 20 Eylül dondurma.

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
