# Yol haritası — 12 → 20 Eylül 2026

**Durum:** 12 Eylül. Teslim 20 Eylül (8 gün). Finalist duyurusu 5 Ekim, final 17 Ekim.
**Kaynak belgeler:** `ARCHITECTURE.md`, `adr/` (27), `VERI_DALLARI_INCELEMESI_R3.md`, `MOTOR_KARSILASTIRMA_YANIT.md`, mimari haritası (artifact).

---

## Değişmeyen ilkeler

1. **Harness güçlü, LLM'e en az iş.** Model hesap yapmaz, ham veri görmez, kategori icat etmez, hatayı yutmaz.
2. **Tek harness, iki rol.** Analist (okur) ve Architect (yazar) aynı `AnalyticsAgent` sınıfı, ayrık araç setleri, ayrık bağlantılar. Analist'in üstüne orkestratör yok; analiz alt-agent'a itilmez.
3. **Yetki yetenekle, kimlikle değil.** Analist'in bağlantısında yazma yeteneği yok. Architect draft'a yazar, curated'a asla. Terfi insanın git commit'i.
4. **Her değişiklik ölçülür.** Golden + benchmark, iki şema, tekrarlı. "İyileştirdim" iddiasının tek kanıtı bu.
5. **Her karar ADR.** Gerekçesi ve ölçümüyle.
6. **Mentör 12 Eylül:** erişim politikası + fallback sözleşmesi, bütçe-tabanlı crawl, kaynak sadakati bayrağı, roller mantıksal — ayrı LLM değil.

---

## Faz A — Omurga (13–14 Eylül)

Architect ve yeni araçların üstüne oturacağı ortak katman. Önce bu, çünkü sonraki her şey buradan geçecek.

| # | iş | çıktı | ölçüm |
|---|---|---|---|
| A1 | **Erişim politikası + fallback sözleşmesi** (ADR-0028) | `AccessOutcome{ok / needs_credential / blocked / not_found}` + seçenekler (`candidates`); soru düzeyinde `source_pinned` bayrağı; credential yalnız env | birim test: her sonuç sınıfı, sabitlenmiş kaynakta sormak ↔ serbest kaynakta geçmek |
| A2 | **Validator tek modülde** — `core/validator.py`: şema → SQL guard → referans → politika | 5 dosyadaki `ToolResult.fail` çağrıları tek boru hattına; mesaj metinleri korunur (ADR-0010/16/17/19) | golden 7/7 ve benchmark değişmeden; hata sınıfı dağılımı aynı |
| A3 | **Rol etiketi** — `AgentStep.role ∈ {plan, retrieve, validate, narrate}` | trace rollerle okunur; golden/benchmark rol başına adım sayar | — |
| A4 | **Motor birleşme kararı (Büşra ile)** | V3 modülleri ortak katmana: validator (A2), sınırlı ön-yükleme (D1), paralel yürütme; koşucunun `sys.path` düzeltmesi; tek harness | benchmark her iki şemada, `--repeat ≥ 5` |

## Faz B — Architect (14–16 Eylül) · demo 2. soru

"Yeni veri getirilir, agent ingest eder ve belgeler."

| # | iş | çıktı | ölçüm |
|---|---|---|---|
| B1 | **Profilci + doğrulayıcı, LLM'siz** | `profile_tabular()` (tip, null, kardinalite, monotonluk, tarih/ayraç adayları); `verify_mapping()` (kolon var mı, tarih %100 ayrışıyor mu, değer sayısal mı, satır sayısı korunuyor mu, series_id çakışması) | birim testler, gerçek CSV/XLSX fixture'larıyla |
| B2 | **Architect rolü** | ayrı registry (`fetch · profile · propose · verify · register_draft · build_silver · build_gold`), yazar bağlantı, `kapat → yaz → yeniden aç` (`LakehouseClient.reload()`); `SubAgentTool`; Analist'te tek araç `ingest_from_url(url\|dosya, bütçe)` → yapısal sonuç (draft seri + provenance + reddedilenler) | golden'a **G8 ingest vakası**: jüri CSV'si → `adhoc.fact_observation` draft; curated'a sızma yok; belge kartı üretildi |
| B3 ✅ | **Gold hayata dönsün** (ADR-0031, 12 Eyl) | `python -m lakehouse gold` (adlandırılmış metrik tabloları, provenance sütunlarıyla); adaptörde `gold.*` tabloları dataset olarak görünür; `gold_align / gold_decompose / gold_join` araçları | golden **G9**: "çeyreklik göster" → Gold'dan; stok seride `decompose` reddi görünür |

## Faz C — Görünür güven (16–18 Eylül) · demo 3. soru + dış kaynak

| # | iş | çıktı | ölçüm |
|---|---|---|---|
| C1 ✅ | **Grafik + denetçi** (ADR-0032, 12 Eyl; 81 il haritası aracı hazır, sınır dosyası ve 81 seri bekliyor) | `chart` (Vega-Lite → PNG); deterministik lint: stok için y=0, çift eksen yalnız istenirse, log etiketli, birim+dönem başlıkta, `quality_flag≠ok` işaretli; ilk grafik **81 il haritası** | golden **G10** grafik vakası; lint testleri |
| C2 | **Kanıt paneli** | cevaptaki sayı → SQL → `silver` satırı → `artifact_sha256` → Bronze → RAW → kaynak URL + `fetched_at`; taranıp kullanılmayan sayfalar burada, cevapta değil | her golden vakasında zincir eksiksiz mi |
| C3 | **Web** | `web_search` (Tavily) + `web_url`: aynı alan adı, robots.txt, max derinlik + max sayfa + süre bütçesi, doğrudan veri linkleri önce; A1 sözleşmesinden geçer; kaynak sabitse ve yoksa **sorar** | golden **G11**: "şu URL'den 2025 enflasyonu" (var / yok / erişilemez üç hâli) |

## Faz D — Kapasite ve kararlılık (18–19 Eylül)

| # | iş | çıktı | ölçüm |
|---|---|---|---|
| D1 | **Sınırlı ön-yükleme** | kataloğun tamamı değil, Retriever'ın seçtiği k seri prompt'a; bütçe token'la sınırlı (ADR-0013) | tur sayısı: hedef V3'ün 2,9'una yaklaşmak; gerçek katalogda ≤ 6.000 token |
| D2 | **BM25 `LexicalIndex`** (sözleşmenin arkasına) | sorgulanabilir seri eşiği aşınca devreye girer; mentör: serbest | retrieval isabet ölçümü |
| D3 | **Golden genişletme + kararlılık** | G8–G11 eklendi; `--repeat 5`; hata sınıfı ve rol başına adım raporu | tüm vakalar %100 kararlı |
| D4 | **Demo kabul testi (commit'li)** | `scripts/demo_acceptance.py`: bootstrap → ingest → silver → gold → 8 senaryo sorusu; tek komut | yeşil |

Stretch (zaman kalırsa): `clarify` (EVPI, L10-01), katkı ayrıştırması (il bazında waterfall), çapraz kaynak mutabakat fonksiyonu.

## Faz E — Kapanış (19–20 Eylül)

| # | iş |
|---|---|
| E1 | **main'e birleştirme:** üç uç (`lakehouse-integration-r3`, `agent-engine`, `busra/agent-v3` → birleşmiş hâli), **merge commit** (squash yok — 76 commit, 5 yazar korunur); 3 ölü dal silinir |
| E2 | **Belgeler:** `ARCHITECTURE.md` roller ve Architect'le güncel; ADR indeksi; README'de demo komutları; gizli anahtar taraması (geçmiş dahil) |
| E3 | **Freeze.** Sonrası commit yok. |

---

## Veri ekibi — paralel hat

1. Toplu ingest script'i provenance yazsın (`meta.run`, `run_artifact`, `ingest_warning`) — Silver `run_id` ve `quality_flag` bunsuz eksik.
2. 1.534 `unknown` seri: hangi aileler elle doğrulanacak, hangileri kataloğdan çıkacak.
3. EVDS çeyreklik yanıt biçimi (233 seri) — canlı yakalama.
4. 95 artifact kimlik çakışması — karar.
5. TP.FG.J0 terfi kapısı 4. adım.
6. Kataloğa dayalı Silver adaptörü + `silver` komutu — onların çekirdeği, gözden geçirme.

## Yapmayacaklarımız

- Analist'in üstüne orkestratör agent; ikinci harness; multi-agent "görünsün diye".
- Kimlik/rol/auth sistemi — yetenek ayrımı zaten daha güçlü.
- Model ayarı, prompt cilası; ölçüm farkın harness'ta olduğunu söylüyor.
- Vintage/revizyon analizi — Silver'ın anlık-görüntü sözleşmesini değiştirir; freeze sonrası fikir.

## Demo tamamlanma ölçütü

| beklenen | kapanış |
|---|---|
| canlı soru | ✅ |
| kapsam dışı → uydurma yok | ✅ |
| tabloyu bozmadan sütun | ✅ |
| yeni veri ingest + belge | B2 |
| gelişkin grafik | C1 |
| dış kaynak canlı | C3 |
| "yeni kaynak türü gelirse?" | ✅ (SourceMapping + Architect registry) |
| kanıt/provenance | C2 |

## Yapım sırası (şimdi başlıyoruz)

**A1 → A2 → A3 → B1 → B2 → B3 → C1 → C2 → C3 → D3 → D4 → E** — A4 ve D1/D2 Büşra ile paralel.
Her adım: golden yeşil → ADR (karar varsa) → commit (akyilidizbaran) → push.
