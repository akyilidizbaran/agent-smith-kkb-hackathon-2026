# Yeni veri yükleme yolunun sertleştirilmesi — `fix/data-intake-hardening`

**Tarih:** 20–21 Eylül 2026 · **Taban:** `main` `64a58cc` · **Kapsam:** Architect dosya/adres kaydı, terfi, arama önbelleği, kanıt paneli.

Bütün maddeler 20 Eylül gecesi Architect profilinde canlı kullanımda (gerçek MIA, 6.304 serilik havuz) gözlendi;
hiçbiri tahmin değildir. Kararlar `ADR-0037` (uydurma yerine sessizlik), `ADR-0043` (kademeli retrieval) ve
`ADR-0033` (kanıt paneli) ile tutarlıdır; yeni ADR açılmadı, gerekçeler kodun içinde ve burada.

## 1. Gözlenen kusurlar ve düzeltmeler

| # | Gözlem (canlı) | Kök neden | Düzeltme | Dosya |
|---|---|---|---|---|
| 1 | Taslak kaydından sonraki ilk soru **674 sn**, 0 adım, 1 model çağrısı; süre bütçesi (300 sn) döngüye girmeden doldu | `EmbeddingCache` anahtarı tüm katalogun kimlik+metin listesi; bir seri eklenince 6.305 vektör baştan (~600 sn, `766b2b18…npy` 21:46) | Artımlı önbellek: yan dosya kayıt izlerini taşır, değişmeyen kayıtlar en yeni sürümden alınır, yalnız yeni/değişen kayıt gömülür. Eski (izsiz) sürüm ilk tam isabette izlenir hâle gelir, yeniden hesap yok. En yeni 3 sürüm tutulur (her biri ~100 MB) | `adapters/mia_embedder.py`, `core/retriever.py` |
| 2 | Aynı turda model "sayfaya eriştim, OCR ile okudum, listede tek rapor var" yazdı; sıfır araç, sıfır kaynak | Süre/adım sınırı kapanışı yalnız sayıları denetliyordu (`_checked_final`); `_ACTION_CLAIM` kapısı kapanışta yoktu | Başarılı araç adımı yoksa ve metin işlem iddiası taşıyor ya da soru adres/dosya içeriyorsa deterministik metin: "hiçbir araç adımı tamamlanamadı …" | `core/agent.py` `_no_tool_claim_exit` |
| 3 | "taslağını onaylıyorum, kataloğa al" → model `promote_draft` çağırmadan "alındı" yazdı; guard metni sildi, kullanıcı "uyumlu değil" gördü | İstenen-yetenek kapısı yalnız grafik/analitik/öncül içindi ve tablo şartı vardı; `promote_draft` "taze veri" listesinde değildi | `terfi` ve `kayıt` yetenekleri (araçsız cevap bir kez geri gönderilir, tablo şartı yok); `promote_draft` `FRESH_DATA_TOOLS`'ta; yazma turunda "önce veriyi çek" uyarısı yerine yetenek uyarısı | `core/agent.py` |
| 4 | Çakışan anahtarla kayıt denemesi reddedildi, ajanın "iki seçenek" açıklaması guard tarafından "uyumlu değil" metniyle ezildi | Bayat tablo guard'ı yalnız *başarılı* taze aracı sayıyordu | Taze/yazma aracı **denendiyse** (başarısız da olsa) cevap denemenin sonucudur, ezilmez | `core/agent.py` |
| 5 | Başarılı kayıttan sonra panel "EKSİK: 0/8 sayı tabloda · dosya zinciri ✗"; dosya ve sha256 `meta.artifact`'ta vardı | Kanıt kurucu yalnız tablo turlarını biliyordu | Kayıt turu: sayılar araç kartıyla, dosya zinciri artifact sha256'sı ve `meta.artifact` kaydıyla denetlenir; özet "kayıt: … · 11 satır yazıldı · artifact sha256 …" | `contracts/evidence.py`, `core/evidence.py`, `core/agent.py` (`kind: record`) |
| 6 | `.xlsm` yüklemede kabul, veri ekibinin CLI'ında ilke gereği ret; kayıt son adımda düşüyordu | İki katman farklı liste | `.xlsm`/`.xlsb` yüklemede açıklamalı ret; kullanım cevabı ve arayüz seçici aynı listede | `web_app.py`, `core/small_talk.py`, `static/index.html` |
| 7 | "kg, aylık, dönemlik akım" beyanıyla kaydedilen taslakta `default_agg` NULL | Toplama yöntemi sorulmuyor, türetilmiyordu | Ölçüm tipinden deterministik türetme (stok→last, dönemlik akım→sum, oran/endeks→avg …), kanıt satırı ve kartta görünür; `unknown` için türetilmez, beyan ezilmez | `tools/ingest.py` |
| 8 | Katalog adı `bist_altin_csv_test — 3bcc4cc9_bist_altin_2023.xlsx (taslak)` | Yükleme kopyasının rastgele ön eki ada sızıyordu | Ön ek kataloğa girmez | `tools/ingest.py` |
| 9 | Dosya eklenmeden adı yazılınca "izinli klasörde yok" | Doğru ret, yanlış yönlendirme | Çıplak ad → "dosyayı 📎 ile ekleyin, isteği aynı mesajda yazın" | `tools/ingest.py` |
| 10 | Tarihsiz tablo (il × değer) için "tarih ve değer kolonu bulunamadı" | Doğru ret, sebebi belirsiz | "tarih kolonu hiç yok: kalıcı seri olamaz; oturumda `web_url` ile okunabilir" | `tools/ingest.py` |
| 11 | Terfiden sonra `first_obs/last_obs` boş; ajan "kapsam bilinmiyor" diyordu | Kapsam yalnız tam Silver kurulumunda yenileniyordu | `promote_draft_series` aynı işlemde `refresh_series_coverage` çağırır | `lakehouse-core/catalog/promotion.py` |
| 12 | Aynı CSV yeni seri anahtarıyla kaydedilemedi: "artifact … is not registered under the run-artifact link's source/dataset"; üç deneme üç **yetim taslak** ve üç **"success" run** (rows_out 11, gözlem 0) bıraktı | PR #11 artifact kimliğini baytlara bağladı (`meta.artifact` ilk çekimin dataset'ini saklar) ama ad-hoc yayın kontrolü hâlâ eşitlik istiyordu; kayıt sırası run→seri→yayın, yayın düşünce geri alınmıyordu | Yayın, run'ın kendi `meta.run_artifact` bağını esas alır (artifact var olmalı, ilk dataset'e eşit olmak zorunda değil); yayın reddedilirse bu çağrının eklediği taslak silinir ve run `failed` + gerekçe olur | `lakehouse-core/adhoc/publication.py`, `application.py` |

### 1a. Codex'in adres kaydı işi bu dala alındı (cherry-pick, 21 Eylül)

`feature/architect-url-ingest` dalının üç commit'i (`5acc34a`, `298cb26`, `7b29e9f`) yazarlıkları korunarak
alındı; dal ucundaki merge commit'in test dosyasına eklediği `active_question` atamaları ayrı commit'le tamamlandı.
Kazanımlar: rapor **sayfasındaki** indirilebilir ekler listelenip `resource_index` ile seçilir (sunumdaki
Borsa İstanbul "piyasa verileri" ve `endeks/xtumy` adresleri sayfa, dosya değil); metin katmanlı PDF tabloları
`pdfplumber` ile OCR'suz okunur, `table_index`/`value_row` ile ölçüm seçilir; PDF adresine HTTP 200 ile dönen
"Request Rejected" HTML'i erişim engeli sayılır, sayfa değiştirerek tekrar denenmez; lakehouse CLI yürütülebilir
dosyası yapılandırılmış PATH'ten çözülür. Yeni bağımlılık `pdfplumber` (`uv.lock` değişti; Elif'in PR #17'si aynı
işi `pypdfium2` ile yapıyor, ikisi birlikte de zararsız). Canlı: Risk Merkezi Temmuz 2026 bülteni sayfa → ek 1 →
sayfa 4 → "Nakdi Krediler" satırı → 5 kurum taslak (Bankalar 27.790, Toplam 28.963 milyar TL), ikinci koşu
idempotent; Borsa PDF adresi bugün 404 → `SOURCE_NOT_FOUND`, uydurma yok. Belgeler: `docs/ARCHITECT_URL_KAYIT.md`,
`docs/PDF_ERISIM_TESHISI.md`.

### 1b. Şekil düzeltmeleri: kolon seçimi ve beyan edilen dönem (21 Eylül)

Kullanıcının verdiği on adresin yoklaması (`docs/…` yerine sohbet kaydı): erişilebilen tablolu kaynakların çoğu
biçim değil **şekil** yüzünden kaydedilemiyordu. İki eksik kapatıldı:

- **Kolon seçimi** (`value_column`, `date_column`, `entity_column`): profilci çok kolonlu dosyada "en dolu sayısal
  kolonu" sessizce alıyordu (TLREF'te kapanış yerine en düşük değer olabilirdi). Şimdi birden çok sayısal kolon varsa
  ve kullanıcı seçmediyse yazılmaz, kolonlar listelenip sorulur. Seçim beyandır: model, aracın listelediği kolonu
  kullanıcı anmadan seçemez (`_mentioned`); dosyada olmayan ya da role uymayan kolon açıkça reddedilir.
- **Beyan edilen dönem** (`period`): tarih kolonu olmayan kesit tablolarında (il × değer, kurum × tutar) kullanıcı
  dönemi söyler ('Ağustos 2026', '2026-08', '2026-06-30', '2026Q2', '2025'); tüm satırlar dönem sonuna bağlanır,
  frekans dönemden türer, türetilen tablo izinli köke `derived_<ad>_<sha>.csv` olarak yazılır ve dönüşüm notu
  kartta/katalogda taşınır. Dönemin yılı kullanıcı metninde geçmiyorsa beyan sayılmaz. Belirsiz yazım ('06/08/2026')
  kabul edilmez. Codex'in satır-ölçüm matrisi (`value_row`) artık başlıkta ay yoksa beyan edilen dönemle de çalışır
  ve yerel dosyalar (yükleme, OCR) için de uygulanır.

Canlı (modelsiz araç, 21 Eyl): TCMB `KFE.pdf` sayfa 2, `value_row="Konut Fiyat Endeksi"`, `period="Ağustos 2026"` →
4 il taslak olarak yazıldı (Türkiye 236,8; İstanbul 226,6; Ankara 265,0; İzmir 229,6), kaynak zinciri PDF sha256 +
türetilen CSV + manifest. Sınır: PDF metin katmanı harf aralıklı başlıkları bozuk verebiliyor ("T Ü R K İY E",
"İS T A N L"); il adları sorguda eşleşmeyebilir, aynı veri EVDS `TP.KFE.*` serilerinde temiz duruyor.

### 1c. Canlı model testi ve son düzeltmeler (21 Eylül öğleden sonra)

Gerçek MIA, yalıtılmış veritabanı kopyası, Architect profili, üç senaryo:

| Senaryo | Sonuç |
|---|---|
| TCMB KFE.pdf adresi, "il bazında, dönem Ağustos 2026" | Model `pages=2`, `value_row`, `period`, `entity_column="il"` verdi; 4 il yazıldı, birim başlıktan ("endeks"), kanıt tam, 71 sn |
| TLREF CSV (4 sayısal kolon), kolon söylenmeden | Yazmadı; dört kolonu listeleyip sordu (öneri: Kapanış). "Kapanış Değeri kolonunu kaydet" deyince `value_column` ile geçti; model ölçüm tipini kendi değiştirince beyan kapısı bir kez daha sordu (doğru) |
| Borsa altın PDF'i (OCR), "TL hacim kolonu" | "Tarihsiz" sayıldı: tablo tarih değil ay adı taşıyor ("Ocak / January"), yıl başlıkta; oturumda tablo olarak yüklendi, uydurma yok |

Üçüncü bulgudan iki düzeltme: ay adı sütunu + beyan edilen yıl → ay sonu tarihleri (TOPLAM satırı düşürülür,
notta sayılır); birim ipucu önce seçilen değer kolonunun kendi başlığından okunur (öbür kolonun "KG"si sızmaz).
Ayrıca eski `.xls` xlrd ile okunur ve türetilmiş CSV olarak sahnelenir (veri havuzu politikası değişmedi);
TBB'nin `.xls`'i okunuyor ama sayfası rapor düzeninde (birleşik başlık, dönem başına TP/YP/Toplam üç satır),
otomatik eşlemeye uygun değil, sınır olarak kalıyor. "EKLENMEDİ — sorulmalı" turunda kanıt paneline kayıt satırı
kurulmuyor.

Altın PDF'i yeni kodla tekrar sürüldü (aynı sunucu düzeni), iki kusur daha çıktı ve kapatıldı:

| Kusur | Düzeltme |
|---|---|
| Model `value_column="TL Hacim"` yazdı, dosyada "TL \| Hacim/Volume (TL)"; birebir ad şartı turu boşa harcadı | Kolon adı önce birebir, sonra büyük/küçük ve Türkçe harf farkı, sonra sözcük kapsamasıyla eşlenir; iki kolona uyarsa seçilmez, adaylar sayılır |
| Başlıkta "\|" olunca veri ekibinin ayraç koklayıcısı virgülü de dikeyi de geçerli buldu, kayıt reddedildi | Kendi yazdığımız CSV'lerde (OCR, türetilmiş, web tablosu) `--delimiter ,` açıkça gider; kullanıcının kendi dosyasında koklayıcı kalır |
| Kayıt cevabı "(Veri: … UYARI: uygunluk kısmen …)" ön ekiyle açılıyordu | Kayıt turunda kapsam satırı yok; kart zaten dönem/satır/birimi söylüyor. Uygunluk gerekçesindeki yinelenen etiketler de tekilleşti |
| Sonraki soruda cevap "1.513497e+11 TL" | Modele giden tablolarda bilimsel gösterim kapatıldı (pandas float biçimi); cevap "151.349.741.325 TL" |

Son ölçüm: kayıt 41 sn, 2 LLM çağrısı, 12 ay yazıldı (Ocak–Aralık 2026, TOPLAM düşürüldü), birim TL başlıktan, kanıt
zinciri tam; aynı oturumda "en yüksek ay hangisi" 18 sn, doğru (Mart 2026), kanıt tam.

### 1d. Eski sorunlar: faiz alias çakışması, Gold bayatlığı, KFE (21 Eylül akşamı)

Jürinin 1. adım sorusu ("2021–2025 aylık konut kredisi faiz oranı") üç ayrı sebeple yanlış ya da boş dönüyordu:

| Sebep | Ölçüm | Düzeltme |
|---|---|---|
| Alias çakışması (PR #9 alias üreticisi): stok serisi `TP.BKR.TRY.18` de "konut kredisi faiz oranı" alias'ını taşıyordu; 19 faiz alias'ı birden çok seride | BM25: stok 33,84 · akım `TP.KTF12` 33,31 · Gold `konut_faizi_aylik` 33,14; "aylık" yüzü stoku öne aldı | Stok grubunun her alias'ı "stok" taşır; `(KMH Dahil)`, `(… Hariç)`, döviz nitelikleri alias'ta kalır (aynı alias iki seride değil); üreticiye `--rewrite` seçeneği |
| Puanlar alias sayısına bağlı, anlama değil | Aynı ölçüm | Retriever'da eşitlik bandı (%5): bantta doğrulanmış seri ya da Gold metriği otomatik girişin önüne geçer; bant dışında sıra değişmez. Gold faiz tablosuna iki alias |
| Gold bayat: gerçek DB'de Gold 15 Eylül'de 116.413 Silver satırıyla kurulmuş, 18 Eylül genişletmesi Silver'ı 232.217'ye çıkarmış | Sorgu `GOLD_STALE` ile reddedildi (kopya DB'de aynı) | Kaynaktan çekme ve terfi araçları Silver'dan sonra `lakehouse gold` çalıştırır (`LakehouseCLI.refresh_gold`); gerçek DB'de bir kez elle `gold` gerekiyor |
| KFE `TP.KFE.TR` "baz yılı doğrulanmadı" diye `derived` | 2023'ün 12 ayının ortalaması tam 100,00 | Açıklama 2023=100 ile, `verified` |

Sonuç (canlı, kopya DB, Gold yeniden kurulmuş): jüri sorusu → `gold.konut_faizi_aylik`, 60 ay, 2021-01 18,39 … 2022-11 21,58 …, kanıt sayılar ✓, 81 sn; "KFE 2024 ortalaması ve baz yılı" → 141,54 ve 2023, 33 sn.

### 1e. Kümülatif seriler: canlı doğrulama (21 Eylül gece)

Transkript 10:15–10:25 kümülatif yayınlanan serilerin aylık akıma çevrilmesini ister. 53 `flow_ytd` serisi Silver'da
kaynağın yayınladığı gibi (yıl başından birikimli) durur; ayrıştırma iki yoldan çalışır ve ikisi de canlıda ölçüldü
(gerçek MIA, kopya DB, Gold yeniden kurulmuş):

| Soru | Yol | Sonuç |
|---|---|---|
| "Haziran 2026 aylık net kârı, kümülatif değil" | Hazır Gold `net_kar_aylik` (decompose_cumulative) | 106.642 mn TL (Haziran kümülatifi 528.431 − Mayıs), cevap ayrımı açıkça söylüyor, 57 sn |
| "2025 aylık toplam faiz gelirleri, ay ay" (hazır Gold yok) | Ajan `gold_decompose` aracını `bddk_monthly:158_Toplam` için anında çalıştırdı | 12 ay, Ocak 621.187 … Aralık 804.880 mn TL, kanıt 13/13 sayı tabloda, 56 sn |

Yani 52 seri için ayrı Gold tablosu gerekmiyor; ayrıştırma sorulduğunda hesaplanıyor ve kartta "kaynakta kümülatif,
aylık akıma çözüldü" notu düşüyor. Silver'a türetilmiş seri yazılmaması bilinçli: ham gözlem kaynağın yayınladığı
gibi kalır, türetim Gold'un işi (ADR-0031).

### 1f. BDDK aylık: 70 serinin 2021 boşluğu — eski şema kimlikleri (21 Eylül gece)

Yarışma 2021-01'den itibaren derinlik ister; 498 aylık serinin 70'i daha geç başlıyordu (2021-11: 9, 2022-01: 32,
2022-06: 6, 2022-09: 8, 2023-01: 11, 2024-02: 4). Kaynağa soruldu: BDDK Gelişmiş sayfasındaki `<option value="1842,1626,…">`
bir kalemin şema sürümlerinin kimliklerini (yeniden eskiye) taşıyor; eski aylar eski kimlikte duruyor. 70 serinin
tamamı için her kimliğe canlı sorgu (≈400 istek): **63 seride eski kimlik 2021 başını veriyor**, 7 seride hiçbir
kimlikte yok (kaynak sonradan yayınlamış: 1840, 1891, 1892, 1893, 1913, 1914, 1936), 1 seri (1937) yalnız 2021-11'den.
Kimlikler zincir olabiliyor (1940: 1933 → 1934 → 1935 → 1940) ve geçiş ayında örtüşüyor.

Uygulama (lakehouse-core, veri sözleşmesi değişmedi):
- `catalog/bddk_monthly_history.yml`: seri → eski kimlik → pencere (73 pencere, 63 seri); pencereler örtüşmez, geçiş
  ayı yeni kimlikte kalır (Silver aynı gözlem için iki farklı değeri revizyon çatışması sayar). `catalog/series/`
  altına konmadı: o klasörün her dosyası seri kataloğu sayılıyor.
- `run_catalog_ingestion.py`: seri çekildikten sonra eski kimlikler istenen pencereye kırpılarak aynı seri için ayrı
  run olarak çekilir (`history_code` raporda); `--only`/`--only-file` ana seriyi seçer, tarihçe otomatik gelir.
- `SeriesRow.series_key` → FetchSpec `series_key` (tel alanı değil) → connector metadata `requested_series_key` →
  parser tek ölçüm kolonunu katalogdaki anahtar altında yayınlar; birden çok kolonda uyarıyla yok sayılır.
- Testler: registry, connector, parser, betik (pencere kırpma + örtüşme reddi).

Canlı doğrulama (kopya DB + RAW/Bronze kopyası, 4 seri, ardından `lakehouse silver`): 1842, 1940 ve 1953 artık
2021-01 → 2026-06 kesintisiz 66 ay (2, 4 ve 3 artifact'tan), geçiş aylarında değerler süreklilik gösteriyor
(1842: 2021-10 525.011 → 2021-11 557.655); 1937 kaynak sınırı gereği 2021-11'den. Silver satırı 232.217 → 232.310.

Gerçek DB için (sunucu kapalı): `run_catalog_ingestion.py --only-file catalog/bddk_monthly_history.series.txt
--start 2021-01-01 --end 2026-06-30`, sonra `silver` ve `gold`.

### 1g. Benchmark alt kümesi (Baran'ın `TEST_PROMPTLARI_V2.md`, 22 Eylül gece)

Gerçek DB'nin güncel kopyası, gerçek MIA, Architect; 13 vaka + jürinin 2. adımı. Sonuçlar:

| Vaka | Sonuç |
|---|---|
| P05 haftalık takipteki alacak oranı | Doğru ret: haftalıkta oran yok, adaylar ve kapsam sınırı verildi (90 sn, 11 adım — yavaş) |
| R02 "toplam kredi" adayları | Adaylar tablo hâlinde, ulusal seri seçildi, FinTürk ayrı tutuldu (150 sn) |
| R05 mortgage alias | `bddk_monthly:1534_Toplam`, 2023 12 ay, kanıt tam |
| T02 kümülatif ihracat akışı | Doğru ret: stok farkı akış diye sunulmadı |
| T04 politika faizi yıllık ortalama | 2022 12,63 · 2023 20,67 · 2024 48,96 · 2025 42,83; kredi akışı yok denildi |
| T05 reel mevduat | 48 satır, `workspace_real_value`, kanıt tam |
| Q01 kapsam dışı tarih | Sayı üretilmedi, son gözlem 30 Haziran 2026 |
| Q02 bilinmeyen seri | Benzer seri seçilmedi, adaylar açıklandı |
| Jüri 1. adım (aylık faiz) | Gold aylık ortalama, 60 ay, kanıt tam (159 sn) |
| Jüri 2. adım "faiz sütunu ekle" | Önce haftalık seriyle 9 satır eşleşti, sonra Gold aylık sütunu eklendi; 60/60 dolu (148 sn) |
| İhracat kredileri 2021-01 → 2022-06 | Eski kimlikten gelen aylar dahil 18 satır, 2 artifact, kanıt tam |
| R06 tur 2 "mevcut tabloya TÜFE ekle" | **Kusur:** `workspace_add_column` 72 gözlemi eklemişken cevap bayat-tablo guard'ıyla silindi → `workspace_add_column` ve `workspace_join` taze kaynak sayıldı; tekrarında 36/36 satır, cevap korundu |
| BIST 100 2025 aylık | **Kusur:** katalog kaydı `derived` olduğu için Gold indirgeme reddedildi → değerler Borsa İstanbul kapanışlarıyla doğrulanıp `verified` yapıldı; tekrarında tablo geldi |

Tekrarda kalan sınır: BIST'te **Mart 2025 boş**. Kaynak (EVDS) tatil günlerini (31 Mart, 1 Nisan 2025 bayram) NULL satır olarak
yayınlıyor; Gold `last` kuralı dönemin son gözlemini alıyor ve o NULL (`boundary_missing`). `gold/align.py` bunu bilinçli
yapıyor: "sınır okuması eksikse geriye uzanmak enterpolasyondur" (stok mantığı). Borsa endeksi için ay sonu kapanışı = son
işlem günü kapanışıdır; tatil satırı eksik okuma değil takvim boşluğudur. Öneri (veri ekibinin kararı, sözleşme değişikliği):
`index`/`rate` ölçüm tipinde sınır kuralı NULL'u atlayıp son mevcut okumayı alsın ve bunu bayrakla söylesin; ya da
iş günü takvimli serilerde tatil NULL'ları Silver'a gözlem olarak girmesin.

Ayrıca bir MIA kesintisi (3 deneme zaman aşımı) `/api/ask`'ten 500 döndürdü; veriyle ilgisi yok, arayüzde hata metni
olarak görünür.

**Karar (Zümra, 22 Eylül 02:30): uygulandı.** `gold/align.py`: `index` ve `rate` ölçüm tipinde sınır kuralı (`last`/`first`)
NULL sınır okumasını atlayıp dönemin son (ilk) yayımlanmış okumasını alır, yeni bayrak `boundary_shifted` ile söyler
(`source_observation_dates` günü verir). Stok serilerinde davranış değişmedi (`boundary_missing` kalır). Mevcut Gold
tabloları etkilenmiyor (kur ve faiz `avg`). Kopya DB'de BIST 100 2025: Mart 9.659,48 `boundary_shifted`, öbür aylar aynı.
Testler: endeks tatil sınırı, oran `first`, stok `first` (eski sözleşme korunuyor).

### 1h. Tamamlanma sözleşmesi ve arama defteri (22 Eylül)

İki istek (Baran'ın benchmark bulguları): (1) işin tamamlandığını doğrulayan genel bir sözleşme — istekten beklenen
seri kimlikleri, dönem/frekans, işlem, kolonlar ve çıktı kapsamı çıkarılsın; teslimden önce satır/dönem kapsamı, seri
kimliklerinin korunması, türetilmiş değerlerin girdiyle tutarlılığı denetlensin; eksikse araç akışı sürsün ya da
eksiklik açıkça yazılsın. (2) Katalog araması çağrı sayısıyla durdurulmasın; yeni ve tekil aday üretimi ile istenen
yüzler izlensin; büyük sonuçta tam aday listesi indirilebilir tabloda kalsın.

Hiçbir sürümde yoktu: main ve bu dal yalnız anlatıdaki sayıyı denetliyordu; Baran'ın `feature/agent-engine` dalı
aramayı sabit `max_catalog_search_calls` ile kesiyor ("N arama yapıldı, durduruldu").

Uygulama (soruya özel kural yok):
- `core/completion.py`: beklenti sorudan türetilir (ay/YYYYMM/çeyrek/ay adı/yıl/takvim yılı/yarıyıl pencereleri, frekans
  sözcüğü ya da pencerenin tanesi, "önceki aya göre fark" ve "yüzde değişim" türetimleri, katalog kimlikleri, liste
  isteği). Denetim: dönem kapsamı (eksik dönemler adlandırılır), fark/yüzde kolonunun girdisiyle tutarlılığı, seri
  kimliklerinin kaynak/SQL'de bulunması. Frekans bilinmiyorsa dönem sayısı zorlanmaz (yalnız pencerede hiç gözlem yoksa).
- Ajan: nihai cevaptan önce kontrol; eksikse bir kez "TAMAMLANMA KONTROLÜ" notuyla modele geri gider (araçlarla
  tamamlasın), ikinci kez de eksikse cevabın sonuna deterministik "(Kapsam kontrolü: …)" notu; adım/süre limiti ve
  terminal hata kapanışlarında da. Dürüst ret ("yok", "…amıyorum") geri gönderilmez, not tekrar edilmez.
  `AgentAnswer.completion` ve API'de `completion` alanı.
- `core/search_ledger.py`: tur içi defter — tekil adaylar, arama başına yeni aday, istenen yüzler (frekans/il/kaynak)
  adaylarda var mı. Doygunluk: ≥3 aramadan sonra son iki arama yeni aday üretmediyse (`SEARCH_SATURATED`, tam liste
  ile); ısrar edilirse ikinci kez araçlar geri alınır. `lakehouse_search` `limit` aldı (liste isteğinde ajan 40 verir).
  Aday listesi istendiğinde ya da arama doyunca adaylar tablo olarak kurulur ("(Aday listesi: N seri; tam liste
  tabloda, indirilebilir.)"), API/indirme bu tabloyu verir.
- Yan bulgular: Gold doğrulanmamış seriyi reddedince aynı adın doğrulanmış serisi aday olarak döner ve tur bitmez
  (P04: 1888 → 1160 ile tamamlandı); konu belirten "hangi seriler var" sorusu envanter cevabına kaçmaz (konu sözcükleri
  katalogdan); `claim_check` Gold satırında `period_end`'i etiket sayar (P04 yanlış çelişki notu).

Canlı (gerçek MIA, güncel DB kopyası, dört tur): P02 ve üç yazımı 24/24 + fark/yüzde kolonu doğrulandı; P04 ve iki
yazımı 16/16 (ilk denemede Gold reddi → doğrulanmış eşdeğerle tamamlandı); P05 dürüst ret + 25/48 adaylık tablo;
R02 50 adaylık tablo teslim edildi; R02b (konu belirten liste) 68 aday; R04 boşluksuz; Q01 ve "2026-03–2026-09"
kısmi pencere: eksik dönemler adlandırıldı. Birim: `test_completion_contract.py` (24 vaka), gold ve small_talk testleri;
tam paket 855.

### 1i. Ekip bulgularından alınanlar (22 Eylül öğle)

Bir ekip arkadaşının PR #18 taramasından bize düşen üç küçük düzeltme:
- **Uygunluk kapısı çökmesi** (`fitness.py`): yinelenen/float kolon etiketli tabloda (TCMB today.xml) `frame[c]` DataFrame
  dönüyor, tarih/yıl taraması patlıyor, kapı sessizce atlanıyordu. Arkadaşın `" ".join` yaması alındı; ek olarak imza
  başında etiketler tekil dizeye çevriliyor (her yol için). Test: yinelenen float etiket.
- **Sözlük** (`config_data/concepts.json`, kod değil): `doviz` kavramı (döviz/dolar/usd/euro/forex…) ve `alis` ölçümü
  (alış ↔ ForexBuying/BanknoteBuying), `satis`'e sell/forexsell/banknotesell kökleri. "Dolar alış ve satış kuru" sorusu
  İngilizce başlıklı TCMB tablosuyla artık eşleşiyor; konut satışları ve kredi soruları değişmedi (ölçüldü).
- **PDF bayt sınırı** (`web/fetch.py`): medya türü PDF ise 8 MiB yerine 32 MiB (BDDK faaliyet raporu); HTML sınırı aynı.

Bize düşmeyenler: web araştırma bütçesi yaması ve arama sonucundaki gerçek linki önceliklendirme (`web_research.py`,
yalnız #18 dalında); change-point çıktısının anlatı özetinde kırpılması (#18'in özet katmanı, bizde tam tablo yazılır).
Ayrı eksik: XML dosyası okuma/kaydetme yolu bizde yok.

### 1j. Boş katalog + finans dışı veri provası (22 Eylül öğleden sonra)

Jürinin "içini boşaltıp sağlık verisiyle çalışsın" kriteri (12:33) şimdiye kadar canlıda denenmemişti (M16-T04 kısmi).
Ayrı veri kökü, `bootstrap --catalog none` (0 seri), `DOMAIN_DESCRIPTION` demografi, Architect, gerçek MIA, gerçek veri:
Dünya Bankası ülke × yıl nüfus CSV'si (17.195 satır, 265 varlık, 1960–2024) — GitHub'daki `datasets/population` deposu.

| Adım | İlk koşu | Bulunan | Düzeltme | Son koşu |
|---|---|---|---|---|
| Sızıntı: boş katalogda "konut kredisi faizi" | Dürüst "havuzda yok" | — | — | ✓ (9 sn) |
| URL'den kayıt (ülke bazında, yıllık) | **Red: "Year" tarih değil** | Profilci çıplak yıl sütununu tanımıyor | `%Y` yalnız 1900–2100 dört haneli tam sayılarda; kayıt yolu yılı yıl sonu tarihine çevirip sahneler; HTML tablosunda yıl sayı kalır | ✓ 17.195 satır, yıllık |
| Terfi | — | — | — | ✓ 17.195 gözlem Silver'a |
| Türkiye 1990–2020 | **"Türkiye kaydı yok"** | `lakehouse_distinct_values` seri kimliğini tablo adı sanıyor (her Silver serisinde patlıyordu) | Adaptör `series_scope` (ilişki + series_id filtresi) | ✓ 31/31 |
| Takip: yüzde değişim + grafik | ✓ | — | — | ✓ |
| Almanya ile Türkiye 2000–2020 | **GOLD_REQUIRED** (pivot frekans dönüşümü sanıldı); sonra "Türkiye bulunamadı" | Dönem ifadesi WHERE'de sayılıyordu; varlık araması aksana duyarlı ("Türkiye" ≠ "Turkiye") | Yalnız GROUP BY/SELECT'teki dönem ifadesi sayılır; `strip_accents(lower())` ile arama | ✓ 21 satır yan yana |
| "Hangi ülkeler var, 'stan' geçenleri listele" | ✓ ama sahte "aday listesi" boşluğu | Sözleşme "listele"yi katalog adayı sandı | Teslim edilen herhangi bir tablo listeyi karşılar | ✓ 9 varlık |

Beş jenerik kusur finans verisiyle görünmüyordu (tarihler tam, varlıklar il adı, pivot nadir). Hepsi soruya/alana özel
kural olmadan düzeltildi; toplam 4 yeni test. Prova reçetesi README "Başka alanla çalıştırma" bölümünde.

Değişmeyenler, bilinçli: beyan kapısı (birim/ölçüm tipi kullanıcıdan gelir, doğrulanmaz), aynı anahtar farklı içerik reddi
(veri ekibinin sözleşmesi), tarihsiz tablonun kalıcı kaydedilmemesi, `unknown` ölçüm tipinde toplama türetilmemesi.

## 2. Doğrulama

**Birim/sözleşme testleri** (`agent-core/tests/test_intake_hardening.py`, 12 test; `lakehouse-core/tests/adhoc/test_promotion_coverage.py`):
artımlı önbellek (yalnız yeni kayıt gömülür, eski sürüm izlenir hâle gelir, budama başka modele dokunmaz, bozuk dosya tam hesaba düşer),
kapanış iddia kapısı (iddiasız kısmi metin korunur), terfi/kayıt geri gönderme, `.xlsm` reddi, toplama türetme, ad temizliği,
kayıt turu paneli (sayı kartla, zincir artifact'la; yalnız sayı uyuşmazlığı zinciri düşürmez), terfi kapsamı.

**Canlı sürüş** (yalıtılmış DB kopyası, gerçek MIA, `scripts` yerine `scratchpad/live/drive*.py`): sayılar §3.

## 3. Ölçüm (canlı, 20–21 Eylül)

Düzenek: `main` veritabanının kopyası (6.304 seri, 232.217 gözlem; RAW/Bronze dosyaları kopyalanmadı, o yüzden
tablo turlarında "Bronze eksik" halkası bu düzeneğe aittir), önbellek kopyası (`766b2b18…`, eski biçim), gerçek MIA,
Architect profili, ayrı sunucu (8766). Sorular API'den, `scratchpad/live/drive*.py`.

| Adım | main (20 Eyl, kullanıcı) | Bu dal (sürüş 4) |
|---|---|---|
| Kayıttan sonraki ilk soru | **674 sn**, 0 adım, uydurma "sayfaya eriştim" | 38 sn; yeni yan dosya `cae350c0` (6.313 kayıt) yazıldı, yalnız 1 seri gömüldü |
| Aynı CSV yeni anahtarla | 3 deneme × "not registered under … source/dataset"; 4 yetim taslak, 4 sahte "success" run | `ingest_from_url` ok, 11 gözlem, run success, kanıt "11 satır yazıldı · artifact sha256 4e88e730… · dosya zinciri ✓" |
| Terfi | model araçsız "alındı" yazdı, guard metni sildi | `promote_draft` ok, anlatı korundu, `first_obs/last_obs` = 2023-01-31 / 2023-11-30, Silver 11 satır |
| Terfiden sonraki soru | — | 31,6 sn, "Ocak–Kasım 2023, 11 gözlem", kanıt zinciri tam |
| Çakışan anahtar (aynı anahtar, farklı dosya) | açıklama "uyumlu değil" ile ezildi | ret gerekçesi ve iki seçenek kullanıcıya ulaştı (sürüş 1, adım 4) |
| Tarihsiz tablo | "tarih ve değer kolonu bulunamadı" | "tarihsiz, kalıcı seri olamaz; oturumda yüklendi" + 5 satırlık tablo, kanıt tam |
| Dosya eklenmeden ad | "izinli klasörde yok" | "📎 ile ekleyin, isteği aynı mesajda yazın" |
| `.xlsm` | yükleme kabul, CLI ret | 415 "dosyayı .xlsx olarak kaydedin" |

Eski önbellek biçiminden geçiş: ilk tam isabette yan dosyaya izler yazıldı (`records: true`), yeniden hesap olmadı.

Kalan gözlemler (bu dalın kapsamı dışında, kayda geçsin): kayıttan hemen sonraki soruda model bazen araç çağırmadan
kartı özetliyor ve bayat tablo guard'ı bunu siliyor (sürüş 4 B adımı; PR #18'in `_active_table_reuse_allowed`
düzeltmesi bu durumu hedefliyor); `.env`'de `LAKEHOUSE_CORE_DIR` mutlak yol olarak durduğu için başka bir çalışma
kopyasında ajan yine ana kopyanın CLI'ını çalıştırıyor (yalnız geliştirici tuzağı). Eski veritabanlarında kalan yetim
taslaklar tek SQL ile temizlenir: `DELETE FROM meta.series WHERE source_id='adhoc' AND status='draft' AND series_id
NOT IN (SELECT DISTINCT series_id FROM adhoc.fact_observation)`.

Testler: agent-core tam paket 789 geçti (yalnız bilinen Windows yol testi kaldı); lakehouse `tests/adhoc` yeni iki
testle birlikte geçti (§2).
