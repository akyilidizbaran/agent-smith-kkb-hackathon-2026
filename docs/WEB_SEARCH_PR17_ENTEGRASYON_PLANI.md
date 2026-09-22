# PR #17 Web Araştırma Katmanının Entegrasyon Planı

**Amaç:** PR #17'deki web araştırma katkılarını mevcut Analyst harness'ına, mevcut yerel benchmark değişikliklerini ve proje erişim kurallarını koruyarak taşımak. Bu plan tek bir demoya veya soru metnine göre özel davranış eklemeyi değil, kaynak keşfi → güvenli okuma → veri/kanıt doğrulama → kısa cevap hattını genel olarak güçlendirmeyi hedefler.

**Kaynak:** [bushushow/AgentSmithler_WorkSpace PR #17](https://github.com/bushushow/AgentSmithler_WorkSpace/pull/17), incelenen head `dbc1a1efea34f282bf4e58f9378d557ccccb39fc`.

## Kapsam ve değişmezler

- Uygulama, PR'ı topluca merge etmek yerine mevcut agent koduna mantıksal parçalar halinde port edilir.
- Mevcut `.env`, benchmark oracle/manifesti ve kullanıcıya ait yerel değişiklikler korunur.
- Arama parçacıkları veri kanıtı değildir; sayı veya tablo cevabı ancak okunmuş kaynak/araç çıktısıyla desteklenir.
- Kamu kaynağı fallback'i yalnız yapılandırmayla güvenilir sayılan kaynaklarda ve veri yokluğu yetkili biçimde doğrulandıktan sonra açılır.
- Kullanıcının kaynak/domain kısıtı korunur; erişim engeli, CAPTCHA veya bot denetimi aşılmaz.
- PDF metin katmanının okunması, OCR ile çıkarılmış tablo hücrelerini kendiliğinden doğrulanmış yapmaz. Doğrulama yoksa OCR belirsizliği kanıtta görünür kalır.
- URL içeriği ve geçici fetch cache'i sohbet/istek sınırlarını aşarak sessizce yeniden kullanılmaz.
- `TP.KFE.TR` demo-serisi commit'i web motoru entegrasyonundan ayrı tutulur.

## Milestone'lar

### M0 — Envanter, koruma sınırları ve PR incelemesi

**Durum:** Tamamlandı.

**Yapılacaklar:** PR head/base/CI bilgilerini doğrula; değişen modülleri, mevcut kodla örtüşmeleri ve politika çatışmalarını belirle; yerel çalışma ağacındaki çakışan kullanıcı değişikliklerini kayda al.

**Gerekçe:** PR'ı tek hamlede almak, `core/agent.py` ve `tools/web.py` üzerindeki yerel değişiklikleri ezebilir veya çakıştırabilir. Başarılı CI tek başına kaynak/kanıt sözleşmesine uyumu kanıtlamaz.

**Kabul ölçütü:** Port edilecek işlevler, dışarıda bırakılacak davranışlar ve mevcut dosya çakışmaları açıkça listelenmiş olmalı.

### M1 — Kaynak yapılandırması ve saf web yönlendirme/fallback planı

**Durum:** Tamamlandı.

**Yapılacaklar:** `source_hints.json` içine kurum→domain ve katalog kaynağı→kamu domain'i eşlemelerini ekle; `core/web_routing.py` içinde URL/domain normalizasyonu, kaynak sabitleme, web niyeti/yasağı ve katalog metadata'sından güvenli arama planı kuran saf fonksiyonları oluştur; `SOURCE_HINTS_FILE` ile boş/özel konfigürasyon davranışını sınayan çevrimdışı testler yaz.

**Gerekçe:** Kaynak adları ve domain'ler harness koduna gömülmeden değiştirilebilir olmalı. Fallback arama sorgusu ham kullanıcı metnini, SQL'i veya veri satırlarını dışarı taşımamalı.

**Kabul ölçütü:** Açık URL ve kurum sabitlemesi doğru domain kümesini üretmeli; domain son-ek kontrolü `bddk.gov.tr.evil.example` gibi hostları reddetmeli; yalnız allowlist'teki katalog kaynakları fallback planı oluşturmalı; özel/kullanıcıya ait sorgular, yasaklanmış web ve eksik metadata plan üretmemeli; plan yalnız katalog adları ve sınırlı dönem işaretlerini içermeli.

**Sonuç:** Kurum ve katalog kaynağı domain eşlemeleri `source_hints.json` içine taşındı; `source_hints.py` bunları normalize ederek yüklüyor. `core/web_routing.py` yönlendirme niyetini, web yasağını, host sınırlarını, kaynak allowlist'ini ve katalog metadata'sından kurulan sınırlı fallback planını LLM'den bağımsız saf fonksiyonlarla hesaplıyor. Ham kullanıcı prompt'u, SQL ve satır değerleri dış arama sorgusuna kopyalanmıyor. Bu milestone yalnız plan üretir; henüz agent/tool akışını çalıştırmaz.

**Doğrulama:** `tests/test_web_routing.py` ve erişim/web regresyon testleri dahil tam agent-core suite **855 geçti**; 1 mevcut Starlette/AnyIO deprecation uyarısı. İlgili Ruff kontrolleri, JSON parse ve `git diff --check` başarılı.

### M2 — Doğrulanmış yoklukta agent ve araç kapısı entegrasyonu

**Durum:** Tamamlandı.

**Yapılacaklar:** Fallback'i yalnız `CONFIRMED_ABSENT`/`OUT_OF_COVERAGE` veya aday bulunmayan, yüklenmemiş seri olmadığı kanıtlanan katalog yokluğu halinde tetikle; bu durumda web araçlarını aynı turda dinamik aç; lakehouse SQL hatası, erişim hatası, indekslenmemiş/pending aday veya kaynak uyuşmazlığında web'e otomatik geçme.

**Gerekçe:** “Havuzda bulamadım” ile “veri yayımlanmamış” farklıdır. Her hata web aramasına çevrilirse erişim/politika sorunları sessiz veri kaynağı değişimine dönüşür.

**Kabul ölçütü:** Pozitif/negatif testlerle çağrı sırası ve fallback nedeni doğrulanmalı; arama yalnız güvenilir domain filtresiyle açılmalı; ham SQL/kullanıcı prompt'u dış aramaya gitmemeli.

**Sonuç:** Agent yalnız `lakehouse_search` için aday/yüklenmemiş seri içermeyen `DATASET_NOT_FOUND` veya `lakehouse_query` için yetkili `OUT_OF_COVERAGE` / `CONFIRMED_ABSENT` sonucunda fallback planı kuruyor. SQL/fetch/erişim/kaynak uyuşmazlığı, pending aday, özel veri veya web yasağı fallback'i engelliyor. Sorgudaki seri kimlikleri yalnız katalog metadata'sıyla eşleştirilerek provenance'a dönüştürülüyor. Kaynak eşleşmesi yok katalog aramasında kullanıcıya açıkça sabitlenmiş kamu domain'i ve güvenli kısa arama terimleri şart. Plan varsa web araç şeması aynı turda dinamik açılıyor; Tavily sorgusu/domain'i harness planına sabitleniyor ve bir kez kullanılabiliyor. Boş sonuçlu sorgu artık `FOUND` olarak işaretlenmiyor.

**Doğrulama:** Agent-core suite **860 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı. M2 yönlendirme/web/recovery/agent testleri 103/103 geçti; değişen modüllerde Ruff `F`, yapılandırma JSON ve `git diff --check` başarılı. Harici Tavily ağına çıkılmadı; arama davranışı sahte sağlayıcıyla doğrulandı.

### M3 — Domain filtreli arama ve kaynak keşfi

**Durum:** Tamamlandı.

**Yapılacaklar:** `web_search.include_domains` argümanını sağlayıcıya kadar taşı; sonuç URL hostlarını tekrar doğrula; okunan sayfalardaki aynı-domain linkleri güvenli locator olarak sun; doğrudan CSV/XLSX/PDF adaylarını işaretle ve arama parçacıklarını sayısal kanıt havuzunun dışında tut.

**Gerekçe:** Kullanıcının URL'si bazen landing page olur; doğru belge aynı kurumun alt sayfasında veya doğrudan dosya URL'sindedir. Domain filtresi ve host doğrulaması kapsam dışına taşmayı önler.

**Kabul ölçütü:** Kullanıcı domain'i, kurum pin'i, alt-domain sınırları, yanlış-domain arama sonucu, same-domain link ve doğrudan dosya vakaları test edilmeli; yalnız arama sonucu varken cevap sayı yayımlayamamalı.

**Sonuç:** Açık URL/kurum pini Tavily `include_domains` filtresine taşınıyor ve sağlayıcıya rağmen dönen her URL yeniden denetleniyor; HTTP(S) dışı, kimlik bilgili, portlu, malformed veya özel/loopback host reddediliyor. Host eşleşmesi `host == domain || host.endswith("." + domain)` kuralıyla lookalike suffix'leri kabul etmiyor. Yalnız doğrulanmış aday URL'leri aynı turdaki `web_url` niyet kapısına ekleniyor. CSV/TSV/XLS/XLSX/PDF/JSON dosyaları arama sonucunda ve same-domain crawl kuyruğunda öne alınıyor. `max_depth=1` ile tarama mevcut crawler'ın aynı-domain kontrolünden geçiyor; dış linkler açılmıyor. Arama sonuç artefact'i `direct_data`, reddedilen sonuç adedi ve snippet'lerin doğrulanmamış bağlam olduğunu tutuyor. Agent `web_search` çıktısını sayısal grounding havuzuna almıyor; bu turda kaynak sayfası açılmadan model nihai cevap vermeye kalkarsa yalnız aday bulundu/ bulunmadı durumunu veren deterministik, sayısız kapanış kullanılıyor.

**Doğrulama:** Agent-core tam suite **864 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı. Domain pin'i, lookalike host, malformed/credential URL, doğrudan dosya sırası, PDF same-domain link önceliği ve arama snippet'inden sayı yayımlamama regresyonları eklendi. Değişen Python modüllerinde Ruff `F` ve `git diff --check` başarılı. Gerçek Tavily ağı kullanılmadı.

### M4 — Fetch sınırları, hata sınıfları, aynı-tur cache ve bounded recovery

**Durum:** Tamamlandı.

**Yapılacaklar:** `CONTENT_TOO_LARGE` ile erişim/yokluk ayrımını yap; sınırlı arama/çıkarım tekrarlarını tanımla; aynı URL'nin keşif→tablo yükleme adımında aynı turda ikinci fetch/OCR'ı önle; yeni tur ve açık refresh'te fetch'i yenile. PR cache yaklaşımı mevcut `_last_turn` sınırıyla birleştirilir.

**Gerekçe:** Tekrarlanan indirme/OCR gecikmeyi büyütür; kalıcı cache ise bayat kaynağı güncelmiş gibi sunabilir.

**Kabul ölçütü:** Aynı turda aynı locator tek kez indirilip ayrıştırılmalı; sonraki tur/refresh tekrar indirmeli; başarısız keşif cache'e alınmamalı; büyük dosya erişim engeli veya yokluk olarak raporlanmamalı; tekrar sayısı üst sınırda durmalı.

**Sonuç:** `ContentTooLarge` ayrı bir fetch istisnası olarak tanımlandı; crawler bunu `limit_exceeded` kanıtına alıyor. `web_url` bu durumda `CONTENT_TOO_LARGE` döndürüyor ve web artefact'inde URL/sınır sebebini saklıyor; aynı URL ve aynı bütçeyle tekrar deneme retryable değil. `refresh=true` cache'i açıkça atlıyor. Aynı turda aynı URL, sayfalar, tarama bütçesi ve amaçla başarılı keşiften tablo yüklenirken crawl/OCR sonucu kullanılıyor; yeni tur, farklı anahtar veya refresh yeniden çekiyor. Başarısız keşif cache'e girmiyor.

**Doğrulama:** Başarılı 8MiB sınır üstü fetch, crawler ayrımı, artefact, same-turn reuse, amaç değişince invalidation, başarısız keşif, yeni tur ve refresh regresyonları eklendi. `uv run --frozen --extra dev pytest -q`: agent-core **870 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; hedefli Ruff `F` ve `git diff --check` başarılı. Canlı web/Tavily isteği yapılmadı.

**20 Eylül güncellemesi (ADR-0088):** Doğrudan sayfa okumasında `purpose` değişikliği yeniden fetch sebebi olmaktan çıkarıldı; derin taramada amaç link sıralamasını etkilediği için anahtarda tutuluyor. Cache URL kimliği normalize edilir, 8 kayıt/16 MiB ile sınırlanır; aynı metin penceresi tekrarında uzun excerpt yerine kısa tekrar notu döner. Timeout sonrası arama/okuma artefact'lerinin korunması ve `web_reads` API aktarımı ADR-0095'te ele alındı. Tam suite bu güncelleme sonrasında **899 geçti**.

### M5 — HTML/CSV/XLSX/PDF çıkarımı ve kanıt doğruluğu

**Durum:** Tamamlandı.

**Yapılacaklar:** PDF text-layer okumasını mevcut OCR sözleşmesiyle uyumlu hale getir; tablonun text-layer'dan mı, OCR'dan mı çıktığını ve hangi sayfaların okunduğunu provenance'a yaz; OCR hücreleri doğrulanmadıysa kalite kapısını ve kullanıcı uyarısını koru; bozuk/çıkarılamayan içerik için ayrı hata sınıfı üret.

**Gerekçe:** PDF'in metin katmanı metin kanıtı sağlar, fakat OCR'dan çıkarılmış hücre değerlerini otomatik doğrulamaz. Yanlış “doğrulandı” etiketi finansal sayı hatasına yol açabilir.

**Kabul ölçütü:** Metin katmanlı PDF metni, taranmış PDF, OCR tablosu, OCR düşük kalite, çıkarım hatası ve büyük dosya için offline fixture testleri; hiçbir doğrulanmamış OCR tablosu doğrulanmış olarak gösterilmemeli.

**Sonuç:** `vision/pdf.py` pypdfium2'nin Unicode uyumlu metin katmanı çıkarımını seçili sayfa ve karakter bütçesiyle sunuyor; PDF text-layer içeriği düz metindir, tablo yapısı çıkarılmış gibi gösterilmiyor. OCR açıksa yapılandırılmış tablolar OCR yolunda kalıyor; text-layer metni ek bağlam/provenance taşıyor fakat OCR hücrelerini doğrulamıyor. OCR veya text-layer başarısızlığı, metin katmanı olmayan tarama, OCR kalite reddi ve boyut aşımı veri yokluğundan ayrıldı. `DOCUMENT_EXTRACTION_FAILED` ve PDF text/OCR sayfa/yöntem metadata'sı eklendi; kullanılan web tablosunun `QueryProvenance` uyarılarında da çıkarım yöntemi ve sayfa kapsamı yazıyor.

**Doğrulama:** Gerçek PDFium text-layer fixture'ı, text-layer-only prose, scanned PDF/OCR yok, OCR + native text, OCR hata sonrası text-layer fallback, tablo yapısı çıkarılamama ve M4 boyut sınırı offline sınandı. Agent-core tam suite **876 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; ilgili Ruff `F` ve `git diff --check` başarılı. MIA OCR veya dış web servisi çağrılmadı.

### M6 — Kanıt paneli, kaynak notu ve kullanıcıya hata sunumu

**Durum:** Tamamlandı.

**Yapılacaklar:** Web araması, okunan URL, kullanılan tablo, dosya hash'i, fetch zamanı ve çıkarım kalitesini kanıt zincirinde ayrıştır; kullanılmayan arama adaylarını veri kaynağı gibi göstermeme; başarısız anlatım olsa bile doğrulanmış tabloyu ve erişim durumunu koru.

**Gerekçe:** Kullanıcı, cevap verisinin nereden geldiğini ve neyin doğrulanmadığını anlayabilmeli. Arama bağlamı ile sayı kaynağı görsel olarak da ayrılmalı.

**Kabul ölçütü:** Arama-only, okunan metin, yüklenen tablo, redirect/domain reddi, OCR uyarısı ve fetch hatası kanıt panelinde ayrı ve doğru durumlarla görünmeli.

**Sonuç:** Kanıt sözleşmesinde `context_sources` arama adaylarını, `web_reads` başarıyla okunan fakat tabloya seçilmeyen URL'leri, `web_sources` çalışma tablosuna alınan sayfaları taşır. Seçili tablo indeksi/etiketi/ölçüsü; URL, HTTP, hash, çekim, cache ve PDF çıkarım metadatası API ve UI kanıtlarında korunur. Boyut/erişim/çıkarım reddi artefact'leri başarısız araç sonucunda da kaybolmaz. Kanıt paneli ve kanıt yolculuğu PDF text-layer/OCR durumunu ve “URL okundu, tablo seçilmedi” halini ayırır. Anlatım timeout'u sonrası web tablosu ve erişim kanıtının `FOUND` cevapta kaldığı gerçek agent/tool fixture'ıyla doğrulandı.

**Doğrulama:** Web, web-app, kanıt yolculuğu ve adım yolculuğu hedefli testleri **56 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı. M6'ya özel arama/okuma/tablo ayrımı, takip turunda kaynak hatırlama, boyut sınırı, erişim hatası, PDF çıkarım metadata'sı, anlatım timeout'u ve Node tabanlı kanıt yolculuğu testleri eklendi. `docs/adr/0090-web-kanit-panelinde-arama-okuma-ve-tablo-secimi.md` kararı kaydeder.

### M7 — Tam regresyon, manuel web smoke testleri ve ikinci benchmark'a hazırlık

**Durum:** Tamamlandı.

**Yapılacaklar:** Agent-core tam testleri ve mevcut v2.1 contract doğrulayıcısını çalıştır; yerel ve kaydedilmiş fixture testlerini tamamla; izinli birkaç web kaynağında sınırlı smoke test yap; süreleri ve hata türlerini kaydet; ancak bundan sonra benchmark koşusunu başlat.

**Gerekçe:** Mimari değişikliklerin önce deterministik ve düşük maliyetli testlerde güvenilirliği doğrulanmalı; pahalı benchmark ancak kod ve oracle hazırken anlamlıdır.

**Kabul ölçütü:** Mevcut testlerin regresyonsuz geçmesi; yeni güvenlik/kanıt testlerinin geçmesi; benchmark prompt'larına özel kod bulunmaması; web smoke testlerinin kaynak ve fetch provenance'ı üretmesi; ikinci benchmark için başlama kararı ölçüm kayıtlarıyla verilmesi.

**Sonuç:** Agent-core tam suite **879 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; benchmark sözleşme doğrulayıcısı 120 vakayı (76 oracle, 31 doğrulanmış artifact) eşleştirdi ve 71 yerel agent-CLI vakasının `--dry-run` listesi model çağrısı yapmadan tamamlandı. Mevcut crawler aynı bir sayfa/sıfır derinlik bütçesiyle üç resmi kamu ana sayfasını okudu: TCMB, BDDK ve EVDS. Üçünde HTTP 200, başlık, SHA-256 ve fetch zamanı kaydedildi. Bunlar web erişim/provenance smoke testleridir; finansal tablo çekme veya Tavily arama doğrulaması değildir. İkinci benchmark'ın prompt seti/runner ve yerel sözleşmesi hazır; canlı 71 vaka MIA çağrısı bu entegrasyon milestone'unda başlatılmadı.

**Doğrulama:** `uv run --frozen --extra dev pytest -q` → 879 geçti; benchmark contract validator ve 71-vaka `run_v2.py --dry-run` başarılı; M6 web + kanıt UI hedefli tekrar 47 geçti; Ruff `F` ve `git diff --check` başarılı. Resmi sayfa smoke sonuçları:

| URL | HTTP | SHA-256 | Çekim zamanı (UTC) |
|---|---:|---|---|
| `https://www.tcmb.gov.tr/` | 200 | `3a50d3f7e559898bf8d68bf962a0b5a74ce11446869fc2a820c2bab53d08e1ef` | 2026-09-19 20:19:22 |
| `https://www.bddk.gov.tr/` | 200 | `9fa4ff94aeac948249797dd196a18157a2797c435d096c94b7ae7f6b73efd2a9` | 2026-09-19 20:19:39 |
| `https://evds2.tcmb.gov.tr/` | 200 | `cf7aea887bd6353b1b8da0445fa60b4594e8722a69edd3eba61da6c0687ef9b6` | 2026-09-19 20:19:40 |

## Açık entegrasyon engelleri

- PR #17'deki Chrome-benzeri sahte User-Agent değişikliği alınmayacak; proje kuralı bot denetimini aşmayı yasaklıyor.
- PDF text-layer + OCR tablo yolunda OCR hücreleri ile metin katmanı karşılaştırılmadan tablo “doğrulanmış” sayılamaz.
- PR'daki URL cache'inin tur/refresh sınırı yok; mevcut yerel aynı-tur cache davranışı korunacak ve sonraki tur yenilemesi test edilecek.
- KFE demo verisi web motoru kapsamı dışında, ayrı değişiklik olarak değerlendirilecek.

## İlerleme kaydı

- 2026-09-19 — M0 tamamlandı; PR #17 head ve CI doğrulandı, yerel çalışma ağacı korundu.
- 2026-09-19 — M1 tamamlandı; yapılandırılmış kaynak domain'leri ve saf web yönlendirme/fallback planı eklendi, 855 agent-core testi geçti. Agent entegrasyonu M2'de başlayacak.
- 2026-09-19 — M2 tamamlandı; yalnız doğrulanmış kamu veri yokluğunda tool gate aynı turda açılıyor, sorgu/domain harness planına sabit ve tek kullanımlık. Agent-core suite 860 test geçti.
- 2026-09-19 — M6 tamamlandı; arama adayı, okunan URL ve tabloya seçilen kaynak panel/API/UI'da ayrıldı; PDF çıkarım, tablo ve fetch metadata'sı ile narration-timeout kurtarması kanıtlandı. Hedefli suite 56 geçti; M7 regresyon/doğrulaması sürüyor.
- 2026-09-19 — M7 tamamlandı; 879 tam test, v2.1 sözleşmesi, 71 vaka dry-run, üç resmi kaynak crawler smoke ve son lint/diff kontrolleri geçti. Entegrasyon M0–M7 kapandı; pahalı canlı MIA benchmark bu milestone'un dışında bırakıldı.
