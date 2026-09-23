# M03 — Jenerik veri modeli ve kaynak sözleşmeleri

**Tarih:** 14 Eylül 2026 · **ADR:** 0060 · **Kanıt:** `agent-core/tests/test_m03_jenerik.py`, `test_m03_kaynak_ipuclari.py`, `tests/fixtures/generic/`

## 1. Desteklenen veri şekilleri (T01, T02)

| Şekil | Nerede yaşar | Ne yapılabilir | Sınır |
|---|---|---|---|
| Zaman serisi (tek ölçüm, tarih + değer, isteğe bağlı varlık/il) | **Silver** (`silver.fact_observation`, `meta.series`) | Katalog araması, SQL, Gold hizalama/ayrıştırma/join, analitik, reel dönüşüm, kanıt zinciri RAW'a kadar | Seri anlamı (birim, ölçüm tipi, frekans) katalogda olmalı; belirsizse yayınlanmaz |
| Tarihsiz tablo (anahtar + ölçümler: il, kurum, ürün…) | **Oturum workspace'i** (`k1`, `k2`…) | workspace_query (SQL), workspace_join (anahtar denetimli), grafik, dışa aktarım | Ortak kataloğa otomatik yayınlanmaz; tarih uydurulmaz |
| İşlem/olay tablosu (satır başına olay) | Oturum workspace'i | GROUP BY ile döneme/anahtara indirgeme, sonra analiz | Silver'a ancak Architect bir zaman serisine indirip yayınlarsa girer |
| Çok varlıklı seri (aynı tarihte birden çok satır) | Silver (entity_id) ya da oturum | Varlık filtresiyle tek seriye inme, sonra analitik | Analitik araçlar tekrar tarihte hesap yapmaz, "tek seriye indir" der (M12) |
| Belge içinden tablo (PDF/görsel) | Oturum workspace'i (OCR) | Aynı tablo işlemleri; sayfa/tablo etiketi ve sha256 kanıtı | "OCR ile okundu, doğrulanmadı"; kalite bayrağı |

**Birleştirme kuralı (A09):** iki tablo `workspace_join` ile, açık anahtarla birleşir. Anahtar belirsizse araç sorar;
sağda yinelenen anahtar reddedilir; eşleşmeyen satırlar her iki yönde sayılır; kolon adı çakışması soneklenir;
her kolon kendi kaynağının provenance'ını taşır. Fikstür beklentileri: `tests/fixtures/generic/README.md`.

## 2. Sözleşmeler (T03)

| Katman | Taşınan bilgi |
|---|---|
| `meta.series` (veri) | series_id, source_id, dataset_id, ad/açıklama/takma ad, frekans, hafta çapası, birim, ölçüm tipi, varsayılan toplama, kümülatif sıfırlama, semantik güven (verified/derived/unknown), durum |
| `silver.fact_observation` | series_id, entity_id, tarih, değer, quality_flag, artifact_sha256, vintage_id, run_id |
| `meta.artifact`, `meta.run`, `meta.run_artifact`, `meta.ingest_warning` | kaynak adresi, HTTP durumu, çekim zamanı, RAW yolu; run durumu, satır sayısı, uyarılar (M07) |
| `DatasetSpec` (ajan) | ad, açıklama, kaynak, frekans, zaman kolonu, kolonlar (rol, dtype, semantik tip, birim, çarpan), kapsam, notlar |
| `QueryProvenance` (ajan) | SQL, dataset_ids, kaynaklar, URL'ler, satır sayısı, uyarılar — her kolona bağlanır |

## 3. Kaynağa özel bilgi nerede (T04)

- **Veri tarafı:** bağlayıcı + parser + `ingestion_registry` kaynak başına; alan bilgisi katalog YAML'larında.
- **Ajan tarafı:** çekirdek kod (`core/`) kaynak adı taşımaz. Kaynak yüzü sözcükleri, anahtar-host eşlemesi ve kurum
  sabitleme adları `kkb_agent/config_data/source_hints.json`'da; `SOURCE_HINTS_FILE` ile değiştirilir; boş dosyada
  motor çalışır (test). Modele giden metinlerde alan terimi yok (iki test: `test_domain_profile`, `test_m03_jenerik`).
- **Kalan yerel bilgi:** `core/facets.py`'deki 81 il listesi Türkiye coğrafyasıdır (alan değil yerel ayar); başka
  ülke verisinde yüz boş kalır, motor çalışır.

## 4. Yeni kaynak türü eklemek (T05, T06)

| Yetenek | Nerede tanımlanır | Bugün uygulanmış |
|---|---|---|
| Erişim yöntemi (HTTP GET/POST, dosya) | veri: `connectors/*`; ajan: `web/fetch.py` (`guarded_get`) | HTTP(S), yerel dosya, EVDS API anahtarı, FinTürk form POST |
| Kimlik doğrulama | `source_hints.json` host→env adı; değer yalnız ortamdan | API anahtarı başlıkta (EVDS, Tavily); OAuth/oturum çerezi yok |
| Format | `builder/read.py`, `web/html.py`, `vision/ocr.py` | CSV/TSV, XLSX, JSON kayıt, HTML tablo, PDF/görsel (OCR) |
| Sayfalama / pencereleme | veri: `ingestion/windowing.py` (EVDS pencere), FinTürk çeyrek döngüsü | Tarih penceresi; imleçli sayfalama yok |
| Bütçe | web: tarama sayfa/süre/derinlik; arama: `WEB_SEARCH_BUDGET`; OCR: sayfa/süre | Var |
| Hata zarfı | ajan `ToolError` (kod, katman, aday, ipucu); veri `LakehouseError(ErrorPayload)` | Var |
| Kanıt zarfı | veri: artifact sha256 + run; ajan: `QueryProvenance`, web sha256+zaman | Var |

**REST API / DB / stream / farklı kimlik doğrulama:** ajan yeni bir kaynağı `LakehouseClient` sözleşmesini (list/get/search
datasets, execute_sql, preview, series_sql, health, close) sağlayan bir adaptörle görür. `test_m03_jenerik.py`
bellek-içi bir adaptörü (finans dışı katalog) ajan koduna dokunmadan araçlara takar: arama, tanım, kolon ekleme ve
analitik çalışır, alan profili yeni katalogdan türetilir. REST/DB/stream adaptörleri **uygulanmadı**; ekleneceği yer
ve uyması gereken sözleşme bu testtir. Orkestrasyon ve doğrulama katmanı değişmez (mentör yönlendirmesi).

## 5. Boş katalog ve alan değişimi (T07)

- Boş katalog: `DomainProfile.from_catalog([])` jenerik profil; ön kontrol "veri yok" der (M01).
- Katalog değişince (ingest/terfi/sıfırlama): `refresh_profile()` sistem promptunu ve araç açıklamalarını yeniden
  türetir (ADR-0048); tam sıfırlama oturumu ve ajanı yeniden kurar (ADR-0056).

## 6. Desteklenmeyen şekil (T09)

Sessiz veri kaybı yok: belirsiz sayı biçimi metin kalır ve not düşer (fikstür: `yatak_sayisi`), belirsiz gün/ay tarih
metin kalır, çok sayfalı Excel sorulur, `.xls`/Word reddedilir, tekrar tarihli seride analitik reddedilir, anahtarı
belirsiz birleştirme sorulur. Her ret sebep ve sonraki seçenekle döner.
