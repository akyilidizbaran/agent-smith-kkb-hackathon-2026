# Branch özeti — `feature/lakehouse-finturk-evds-housing`

**Sahip:** Zümra Yılmaz (Claude Code ile)

**Amaç:** BDDK FinTürk (İllere Göre) kaynağını sisteme eklemek, ingestion'ı
kataloğa-dayalı generic bir çalıştırıcıya taşımak, ve EVDS'ten konut/mortgage
temasıyla ilgili seri kapsamını genişletmek — hepsi mevcut mimariye (Connector/
Parser ayrımı, insan-onaylı+kaynak-türetilmiş katalog, RAW→Bronze immutability)
sadık kalarak.

## Neden yapıldı?

Lakehouse'un pipeline'ı (`IngestionPipeline`, connector/parser çiftleri, katalog
yükleyici) daha önce hiç gerçek veriyle uçtan uca çalıştırılmamıştı — yalnızca
fixture'larla test edilmişti. Bu dal önce bunu tek bir seriyle kanıtladı, sonra
brief'in "İllere Göre" ve "tüm seriler" isteklerini karşılayacak şekilde
genişletti — ama "tüm seriler" kelimenin tam anlamıyla değil (EVDS'te 678 veri
grubu, 53.792 gerçek seri var; bunun tamamını çekmek konu dışı ve saatler sürer),
mentörlere bu netleştirme için ayrı bir mesaj hazırlandı.

## İlk kez: gerçek kaynak → DB bağlantısı bu dalda kuruldu

Bu dala kadar `BddkWeeklyConnector`, `BddkMonthlyConnector`, `EvdsConnector` gibi
sınıfların hepsi yazılmış ve test edilmişti, ama **hiçbiri gerçek kaynağa karşı
çalıştırılıp sonucu DB'ye kaydedilmemişti** — `meta.artifact` 0 satırdı,
`bronze`/`silver`/`gold` şemaları boştu. Bu dal, "kaynak → connector → RAW →
parser → Bronze → DuckDB" zincirini **ilk kez gerçek HTTP istekleriyle uçtan uca
çalıştırıp** kanıtladı: önce tek bir seriyle (BDDK Haftalık), sonra
`scripts/run_catalog_ingestion.py` ile kataloğun tamamı (1619 seri, temizlikten
sonra) için. Bu zincirin kendisi (connector/parser/pipeline sınıfları) önceki
dallarda yazılmıştı; burada yapılan, onu **ilk kez gerçekten çalıştırıp
doğrulamak** ve tek bir seriden 1619 seriye ölçeklenebilir hale getirmekti.

## Neler yapıldı?

**Yeni kaynak — BDDK FinTürk:**
- `src/lakehouse/connectors/bddk_finturk.py`, `src/lakehouse/parsers/bddk_finturk.py`
- Canlı doğrulama: `POST /BultenFinturk/tr/Home/VeriGetir`, `tabloNo=3`
  (Bireysel Bankacılık) tek tablo ile Konut Kredisi taşıyor; `tabloNo=1` ve `4`
  denenip **taşımadığı** doğrulandı (`docs/sources/bddk_finturk.md`)
- **Önemli kaynak bulgusu:** FinTürk verisi aylık değil **çeyreklik** yayınlanıyor
  — ay-bazlı `donem` alanı sadece Mart/Haziran/Eylül/Aralık'ta HTTP 200 dönüyor,
  diğer aylarda kaynağın kendi sunucusu HTTP 500 veriyor. Connector sadece çeyrek
  sonlarını istiyor
- 81 il × 22 çeyrek (2021-2026), tamamı canlı doğrulandı
- `tests/connectors/test_bddk_finturk_connector.py` (22 test),
  `tests/parsers/test_bddk_finturk_parser.py` (22 test) — ekibin diğer
  kaynaklar için kurduğu fixture-tabanlı, ağ erişimsiz test deseniyle aynı
  şekilde; fixture gerçek bir canlı yanıttan alındı (Yalova, 2025-9)

**Generic ingestion çalıştırıcısı:**
- `scripts/ingestion_registry.py` — `source_id → (Connector, Parser, FetchSpec
  üretici)` eşlemesi; yeni kaynak eklemek tek bir kayıt demek
- `scripts/run_catalog_ingestion.py` — `meta.series`'i okuyup ne varsa onu
  çalıştırır, hiçbir seri kodu script içinde yazılı değil. `IngestionPipeline.run()`
  yerine her asset'i ayrı ayrı işler (bir asset'in çakışması/hatası diğerlerini
  etkilemesin diye) — paylaşılan `pipeline.py`'a dokunulmadı

**EVDS genişletmesi:**
- `scripts/evds_catalog_generator.py` — EVDS'in kendi `/datagroups` ve
  `/serieList` metadata uçlarından katalog üretir (`semantic_source:
  source_service`, `semantic_confidence: derived`)
- 17 konut/mortgage temalı veri grubundan (Konut Fiyat Endeksi, Konut Satış
  İstatistikleri, Konut/Tüketici Kredisi Faiz Oranları, TÜFE) **1606 seri**
  kataloğa eklendi
- Önceden var olan `TP.KTF12`/`TP.KFE.TR` girişleri, insan tarafından yazılmış
  zengin açıklama/alias'ları korunarak yeniden eklendi
- İlk gerçek çalıştırmadan (bkz. aşağıdaki "Doğrulama durumu" tablosu) sonra,
  kaynağın kendisi hiçbir zaman veri döndürmeyen **70 seri kataloğdan silindi**
  (58'i `EMPTY_DATASET` — çoğu "(Arşiv)" etiketli, artık üretilmeyen seriler;
  12'si `HTTP_ERROR: HTTP 400` — `TP.BIRIMFIYAT.<il>` serisinin bazı illerde
  hiç yayımlanmadığı, ör. Ardahan/Artvin/Bayburt/Gümüşhane/Hakkari/Tunceli).
  Katalog artık **1536 seri**; bu, kod hatası değil, kaynağın kendi kapsam
  sınırlarına göre kataloğun daraltılması

**Altyapı düzeltmeleri (yol boyunca bulundu):**
- `truststore` bağımlılığı — BDDK'nın eksik ara sertifikası (`GlobalSign RSA OV
  SSL CA 2018`) için Windows'un kendi sertifika deposunu kullanıyor
- Windows `LongPathsEnabled` registry ayarı — içerik-adresli Bronze yollarının
  260 karakter sınırını aşması için gerekliydi
- `load_series_catalog()`'un (`src/lakehouse/catalog/series.py`) kasıtlı olarak
  yalnızca upsert yaptığı, YAML'dan silinen satırları `meta.series`'ten hiç
  silmediği bulundu (docstring: "Rows in meta.series that this catalog does
  not define are never deleted"). Bu yüzden 70 seri `evds.yml`'den silindikten
  sonra bile `bootstrap_database()` tek başına `meta.series`'i senkronlamadı —
  paylaşılan loader'a dokunmak yerine, bu 70 satır tek seferlik bir SQL
  `DELETE` ile elle temizlendi (script-local bir bakım işlemi, kalıcı bir kod
  değişikliği değil)
- 3 paylaşılan regresyon testi (`tests/catalog/test_series_catalog.py`,
  `tests/integration/test_series_catalog_bootstrap.py`), kataloğun eskiden
  yalnızca 4 seriden ibaret olduğunu varsayan tam-eşitlik kontrolleri
  kullanıyordu; katalog büyüdükçe kırılmasınlar diye subset-kontrolüne
  çevrildi (orijinal 4 serinin hâlâ var olduğu doğrulanmaya devam ediyor,
  sadece "yalnızca bunlar" varsayımı kaldırıldı)

## Doğrulama durumu (özet)

| Kaynak | Seri sayısı | Durum |
|---|---|---|
| `bddk_weekly` | 1 | ✅ Canlı doğrulandı, tam aralık Bronze'da |
| `bddk_monthly` | 1 | ✅ Canlı doğrulandı, tam aralık Bronze'da |
| `bddk_finturk` | 81 | ✅ Canlı doğrulandı (Yalova spot-check + 81 il gerçek çekim), tam aralık Bronze'da |
| `evds` | 1536 | ✅ İlk kez gerçek çekimle uçtan uca çalıştırıldı (1606 seri üzerinden): 1441 seri başarıyla Bronze'a yazıldı, 70 seri kaynağın kendisinde hiç veri olmadığı için (`EMPTY_DATASET`/`HTTP_ERROR`) kataloğdan çıkarıldı, 95 seri "(Arşiv)" etiketli serilerin sha256 çakışmasıyla hâlâ başarısız (bkz. "Bilinen eksikler"); metadata `derived`, tek tek doğrulanmadı; 2 orijinal seri hariç |

**Test durumu:** yeni connector/parser için 44 test eklendi (ekibin fixture
deseniyle aynı), tam takım 400+ test geçiyor. Tek istisna:
`test_raw_path_is_deterministic_and_uses_the_contract` — bu dalın
değişikliklerinden bağımsız, ekibin önceden var olan bir Windows
path-separator sorunu (`git stash` ile doğrulandı, dokunulmadı).

**Gerçek veri üzerinde mantık kontrolü:** Bronze'a yazılan gerçek değerler
sorgulanıp makul olup olmadığı doğrulandı — örn. `TP.KTF12` konut kredisi
faizi son gözlemde %41.45 (03.07.2026), BDDK FinTürk'te 2026 Q2 konut kredisi
sıralamasında İstanbul (228,4 milyar TL) beklenen şekilde en yüksek il,
BDDK Haftalık sistem geneli konut kredisi hafta hafta düzenli artıyor
(26.06.2026: 800,5 milyar TL). Bunlar formel bir kabul testi değil, gerçek
verinin anlamlı ve tutarlı olduğuna dair bir sağlamlık kontrolü.

## Silver ve agent nasıl kullanacak?

Değişen bir şey yok — bu dal sadece **kapsamı büyütüyor**, sözleşmeyi değil.
Silver hâlâ `series_id` üzerinden `meta.series`'e bakıp `unit`/`frequency`/
`measure_type`'ı okuyacak; agent hâlâ `name_tr`/`aliases`'tan doğru seriyi
bulacak. `bddk_finturk` ve genişletilmiş `evds` serileri aynı arayüzden, aynı
şekilde görünür.

## Bilinen eksikler / sonraki adımlar

- EVDS'in kalan ~52.000 serisi (52 kategori) kasıtlı olarak dışarıda bırakıldı —
  mentör onayı bekleniyor
- FinTürk'ün session/antiforgery cookie zorunluluğu hâlâ kanıtlanmadı (connector
  ihtiyatlı davranıp önce sayfayı GET ediyor)
- 95 EVDS serisi (çoğu `TP.TICK*`/`TP.VK*` gibi "(Arşiv)" etiketli, artık
  üretilmeyen seriler) hâlâ "artifact identity conflict" ile başarısız oluyor —
  kaynağın bu serilerde döndürdüğü içerik, başka bir seriye ait içerikle
  bayt-bayt aynı (aynı sha256) olduğu için `ArtifactRepository`'nin
  değişmezlik sözleşmesine takılıyor; kataloğdan çıkarılıp çıkarılmayacağı
  henüz karara bağlanmadı

Bu çalışma henüz `feature/lakehouse-integration` dalına alınmadı — commit/push
kararı ayrı verilecek.
