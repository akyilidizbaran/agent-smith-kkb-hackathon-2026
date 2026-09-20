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
