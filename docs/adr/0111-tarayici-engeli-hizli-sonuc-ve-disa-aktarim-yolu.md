# ADR-0111: Tarayıcıda bot engeli hızlı ve açık sonuçtur; kanıt panelinde bronze araması tek tarama

**Durum:** Kabul edildi · **Tarih:** 2026-09-23 · **İlgili:** ADR-0028, ADR-0034, ADR-0110, PR #23

## Bağlam
Canlı arayüzde iki gecikme görüldü.

1. **Adresle istenen dinamik rapor.** Statik okuyucu JavaScript kabuğunu aldı. PR #23'ün gerçek tarayıcı katmanı sayfayı başsız Chrome ile açtı, kaynak ise "Request Rejected" (bot koruması) döndürdü.
   - Adaptör form öğelerini her çağrıda 30 sn bekledi, hatayı sessizce yuttu ve boş sonuca düştü.
   - Model aynı adresi üç kez denedi (~100 sn).
   - Cevap genel "takip isteği tamamlanamadı" şablonuyla kapandı; nedeni ve seçenekleri söylemedi.
2. **Kanıt paneli.** Günlük kur serisini taşıyan bir tabloda panel ~1300 gözlemin her biri için bronze klasörünü baştan taradı (`rglob`, 16.991 dosya, tek arama 0,065 sn). Cevap hazırken ~100 sn beklendi.

Mentörün 12 Eylül kararı ve ADR-0028/0034 açık: ajan CAPTCHA ve bot denetimini aşmaz. Erişilemeyen kaynakta durumu söyler ve seçenek sunar; kontrollü biçimde geri çekilir. JavaScript ile işleme meşrudur; engeli atlatmak değildir.

## Karar
1. **Tarayıcı engeli tanır.** Sayfa açılır açılmaz içerik erişim sınıflandırıcısından (`classify_access`, aynı bot/CAPTCHA işaretleri) geçer. Engel görülürse adaptör beklemeden durur (`BrowserBlocked`). Engel gizlenmez ve aşılmaya çalışılmaz.
2. **Engel yapısal sonuçtur.** `browser_crawl_result` engeli `CrawlResult.blocked` olarak döner. `web_url` bunu boş sonuç değil `ACCESS_BLOCKED` erişim kararı yapar: terminaldir, seçenekleri taşır. Diğer tarayıcı hataları sessizce yutulmaz, günlüğe yazılır.
3. **Engelli host yeniden açılmaz.** Aynı host 10 dakika boyunca tarayıcıyla yeniden denenmez; sonuç anında döner.
4. **Dışa aktarım yolu yapılandırmadadır.** Otomatik erişimi engelleyen kaynak için kullanıcının dosyayı nasıl indireceği `source_hints.json → financial_sources[].manual_export` alanında durur ve engel mesajına eklenir. Çekirdek koda kurum adı ya da menü yolu gömülmez.
5. **Erişim engelinin cevabı deterministiktir.** Terminal hata erişim katmanındaysa cevap aracın kartından kurulur: neden, seçenekler (dosya yükle, alternatif kaynak) ve dışa aktarım yolu. Model yeniden yazmaz; takip turu şablonu bu durumda devreye girmez; aktif tablo değişmez.
6. **Bronze yolları tek taramada.** Kanıt panelinde bronze yolu, klasör bir kez taranarak kurulan kimlik → yol tablosundan okunur. Bulunamayan kimlikte tablo en sık 5 sn'de bir yeniden kurulur, böylece yeni kayıtlar görünür.

## Sonuçlar
- **Adresle istenen rapor:** 1–3. turlardan sonra dördüncü tur 105 sn yerine 2,9 sn sürdü. Cevap engeli, seçenekleri ve kaynağın dışa aktarım yolunu söylüyor; önceki tablo korunuyor.
- **Dosya yüklenince:** Aynı tur her tekrarda kaynak değerleriyle tutuyor (ADR-0110).
- **Kanıt paneli:** 1300 bronze araması 84 sn'den 0,12 sn'ye indi; sonuçlar eski yöntemle aynı.
- **Kalıcı otomatik erişim:** Engelleyen kaynak için meşru yol yetkili erişimdir (kurumdan API ya da izin). Geldiğinde yalnız yeni bir kaynak adaptörü eklenir; orkestrasyon ve doğrulama değişmez.
