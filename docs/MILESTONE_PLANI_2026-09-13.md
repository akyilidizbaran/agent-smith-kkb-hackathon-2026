# Agent Smith — Ayrıntılı milestone ve yapılacaklar planı

**Hazırlanma:** 13 Eylül 2026  
**Son tarih:** 20 Eylül 2026 kod dondurma; hedef daha erken tamamlamak.  
**Planın durumu:** Kullanıcı talebiyle oluşturulmuş uygulama ve tartışma planı. İşlerin aşağıda yazılması, uygulanmış veya bütün mimari önerilerin ekipçe onaylanmış olduğu anlamına gelmez.  
**Ana amaç:** Değişen veri alanlarına ve yeni dış kaynaklara uyarlanabilen, analizi araçlarla yapan, sonuçlarını kaynakları ve sınırlamalarıyla sunan jenerik veri analiz agent'ı.

## 1. Bu dosya nasıl kullanılacak?

- Bu dosya, 13 Eylül repo incelemesi ve ardından gelen kullanıcı/mentör netleştirmeleri için güncel uygulama backlog'udur.
- [Eski yol haritası](YOL_HARITASI.md) tarihsel fazları ve tamamlanan işleri anlatır. Oradaki tamamlanmış işleri burada yeniden sıfırdan yapmak amaçlanmaz; burada eksik akışların tamamlanması, doğrulama ve gerekli düzeltmeler planlanır.
- Her milestone'un gerekçesi, bağımlılığı, teslimatı, görevleri, kabul ölçütü ve riski vardır. Görevler benzersiz kimlik taşır; iş bölümü bu kimlikler üzerinden yapılabilir.
- `Tamamlandı` ancak belirtilen kabul kanıtı mevcutsa yazılır. Bir dosyanın veya aracın var olması, kullanıcı akışının çalıştığı anlamına gelmez.
- İşaretler: **[KESİN]** kullanıcı/mentör tarafından netleşmiş gereksinim; **[ÖNERİ]** değerlendirilmesi gereken yaklaşım; **[AÇIK KARAR]** sonucu henüz seçilmemiş tercih; **[BULGU]** mevcut kodda gözlenen durum.
- Öncelik: **P0** teslimin temel doğruluğunu/çalışmasını etkileyen iş; **P1** zorunlu kapsamın tamamlanması; **P2** gereksinim veya ölçümle tetiklenecek iyileştirme. Bunlar bu planın iş öncelikleridir, güvenlik açığı önem dereceleri değildir.
- Sorumlu kişiler 14 Eylül ekip değerlendirmesinde atanacak. Aşağıdaki sahiplikler kişi ataması değil, gereken çalışma alanlarıdır.
- Mimari değişiklikte yeni ADR veya ilgili ADR'nin yeni karar kaydı; milestone sonunda `PROJECT_MEMORY.md` güncellemesi yapılır. Eski karar ve ölçüm geçmişi silinmez.
- Anahtarlar, şifreler, oturum çerezleri ve gerçek gizli değerler hiçbir rapora/test çıktısına yazılmaz.

## 2. Kaynaklar ve kabul edilmiş sınırlar

### 2.1 Dayanak belgeler

1. [21 branchin incelenmesi ve yeniden üretilen bulgular](REPO_BRANCH_INCELEMESI_2026-09-13.md).
2. [Kullanıcının 14 soruya yanıtlarının ve kapsamın kaydı](KAPSAM_VE_MENTOR_NETLESTIRMESI_2026-09-13.md).
3. [Mentörün paylaşılan soru/cevap metni](mentor/2026-09-13-kullanici-paylasimi.txt).
4. [Kick-off tam transkripti](../KKB_Hackathon_2026_Kick_Off_Tam_Transkript.md): 09:11–11:02 veri kapsamı/hizalama; 12:33–12:55 jeneriklik; 14:06–15:55 asgari araçlar; 16:22–18:05 demo akışı; 24:11 tekrar kurulum; 24:47 yerel demo; 29:04 güçlü harness.
5. [Proje hafızası](../PROJECT_MEMORY.md), [mimari](ARCHITECTURE.md), [agent/veri sözleşmesi](LAKEHOUSE_CONTRACT.md), [ADR indeksi](adr/README.md).

Transkript otomatik üretilmiştir; kendi uyarısına göre kritik belirsizlikte ilgili video zamanı esas alınmalıdır. Yeni mentör metninde ikinci soru grubunun cevap bölümü eksiktir. Kota ve yardımcı modeller konusunda [ADR-0021](adr/0021-mia-search-retrieval-ayristirma.md) eski bir özet sağlar; eksik yeni cevap alınmış gibi davranılmaz.

### 2.2 Değişmez ürün ilkeleri

- **[KESİN] Jeneriklik:** finans verisi kaldırılıp başka alanın verisi konulduğunda motor kullanılabilir olmalı. BDDK/EVDS kuralları kaynak/katalog katmanında kalmalı.
- **[KESİN] Başlangıç veri kapsamı:** BDDK haftalık, aylık ve FinTürk; EVDS. Tarih aralığı 2021-01–2026-06. Kesin seri/kırılım listesi ayrıca çıkarılacak; bütün EVDS evreninin zorunlu olduğu varsayılmayacak.
- **[KESİN] Ana LLM MIA/Kloudeks:** arama ve retrieval ayrı sağlayıcı katmanları; mevcut web araması Tavily.
- **[KESİN] Tek orchestration agent + deterministik araçlar:** ayrı Planner/Validator/Narrator LLM'leri sırf çok agent görünümü için eklenmeyecek.
- **[KESİN] Erişim dürüstlüğü:** agent hesap açmaz, CAPTCHA veya site güvenliğini aşmaz; yetkili ekip bağlantısı kullanılabilir. Engelde sebep ve seçenek sunulur.
- **[KESİN] Kaynak sadakati:** kaynak sabitlenmişse alternatif gizlice kullanılmaz; taranıp kullanılmayan sayfalar evidence/trace içinde kalır.
- **[KESİN] Yeni veri ve çıktılar:** dosya/URL analizi; tabloyu koruyarak işlem; dosya yükleme ve tablo/grafik/rapor indirme kapsam içindedir.
- **[KESİN] Kullanıcı tercihi:** güven/kanıt sınırlamaları uyarıyla gösterilebilir. **[ÖNERİ]** yanlışlığı tespit edilmiş iddia düzeltilir veya çıkarılır; doğrulanmış etiketiyle yayınlanmaz.
- **[KESİN] Architect sınırı:** normal kullanıcı Analyst ile sınırlıdır; ortak katalogda yazma/silme ve veri mimarisi değişikliği yalnız Architect kapsamındadır. Jüri demosunda iki akış da gösterilebilir. Tam veri sıfırlama kullanıcı hedefidir; uygulama ve işlem onayı tasarlanacaktır.
- **[KESİN] Çalışma disiplini:** catalog-breadth bu çalışma hattının veri tabanı olabilir; takımın nihai ortak dalı olduğu ileri sürülmez. Motor ve iş bölümü 14 Eylül değerlendirmesinde netleşecek.
- **[KESİN] Yerel demo varsayımı:** şu an ekip bilgisayarı hedeflenir; başka ortamda tekrar kurulum için tarif ve bağımlılıklar teslim edilir.

## 3. Başlangıç durumu — tekrar yapılmayacak işler

| Alan | 13 Eylül incelemesinde doğrulanan durum | Plan açısından anlamı |
|---|---|---|
| Agent | `feature/agent-engine@67cd6f9`; 330 test geçti | Çekirdek sıfırdan yazılmayacak; açıklar ve akışlar tamamlanacak |
| Veri | `feature/lakehouse-catalog-breadth@cf3e878`; 1.079 test geçti | Bu hattın mevcut yetenekleri kullanılacak |
| V3 | `feature/busra/agent-v3@479854c`; 106 test geçti | Modüller/ölçüm katkıları incelenecek; eski kıyas bugüne genellenmeyecek |
| Ana dal | `main@d81d584`, ilk taslak | Nihai bütünleşik teslim henüz yok |
| Gerçek yerel başlangıç | Seed DuckDB, 1 dataset, 14 araç; lakehouse-core varsayılan yolu yok | Çalışan demo ortamını tek komutla görünür hâle getirmek öncelikli |
| Veri kataloğu | 2.214 seri, 1.533 unknown/birimsiz; 679 verified, 1.535 derived | Katalog/yüklü/anlamı doğrulanmış/Gold'a hazır sayıları ayrı tutulacak |
| Örnek entegrasyon | Geçici DB: CSV → draft → promotion → Silver → Gold; 100/110/120 stok → çeyrek sonu 120 | CLI ve adaptör sınırı çalışıyor; tam ürüne bağlanacak |
| UI | Sahte agent ile soru/tablo/modal/reload çalıştı | Canlı model ve gerçek dosya kullanıcı akışları ayrıca gerekli |

Bu test sayıları birbirleriyle toplanarak başarı oranı veya motor üstünlüğü üretilmez. V3 testleri agent ortamında çalıştırılmıştır; ayrı kilitli kurulum kanıtı değildir. Önceki canlı 11/11 kabul ve golden tekrarları tarihsel ölçümlerdir; son teslim sürümü için yeniden ölçüm gereklidir.

## 4. Milestone haritası

| Kimlik | Milestone | Öncelik | Temel bağımlılık | Sahiplik alanı | Durum |
|---|---|---|---|---|---|
| M00 | Kapsam, açık kararlar ve iş bölümü | P0 | Yok | Ekip koordinasyonu | Tamamlandı (13 Eyl; `M00_GEREKSINIM_MATRISI_2026-09-13.md`) |
| M01 | Tek ve tekrar kurulabilir yerel ortam | P0 | M00 çalışma varsayımları | Entegrasyon | Tamamlandı (13 Eyl, ADR-0049; T08 arkadaş provası M17) |
| M02 | Güncel motor kıyası ve katkı aktarımı | P0 | M00; eşit test ortamı için M01 | Agent + değerlendirme | Tamamlandı (13 Eyl, ADR-0053); T08 ertelendi |
| M03 | Jenerik veri ve kaynak sözleşmeleri | P0 | M00 | Agent + veri | Tamamlandı (14 Eyl, ADR-0060); T06 kısmi |
| M04 | Analyst/Architect yetki ve yayın sınırı | P0 | M03; profil uygulama kararı | Agent + veri + UI | Tamamlandı (14 Eyl, ADR-0056); T05 koşula bağlı, pasifleştirme açık |
| M05 | Güvenli kaynak erişimi | P0 | Mevcut erişim kodu; M03 sözleşmesi | Agent + veri | Tamamlandı (13 Eyl, ADR-0051; T03 14 Eyl ADR-0064 ortak vaka dosyası) |
| M06 | Tavily, crawl, yetkili erişim ve fallback | P1 | M05 | Kaynak erişimi + UI | Tamamlandı (14 Eyl, ADR-0061); T07 M17, T09 uygulanmadı |
| M07 | Ortak ingestion ve provenance | P0 | M01, M03 | Veri | Tamamlandı (14 Eyl, ADR-0057) |
| M08 | BDDK/EVDS semantik ve kapsam hazırlığı | P1 | M00 kapsam; M07 yayın kanıtı | Veri + alan doğrulaması | Tamamlandı (14 Eyl, ADR-0062, `M08_KAPSAM_RAPORU.md`); T06/T10 kısmi |
| M09 | Gold, hizalama ve reel dönüşüm | P1 | M07, M08 | Veri + agent | Tamamlandı (14 Eyl, ADR-0058); T07 kısmi |
| M10 | Dosya/URL/PDF/OCR giriş akışı | P1 | M03, M04 sınırı, M05 | Agent + UI | Çekirdek tamamlandı (14 Eyl, ADR-0054); T04/T06 kısmi |
| M11 | Oturum, tablo korunması ve açıklama soruları | P1 | M03, M04; M10 ile entegrasyon | Agent + UI | Tamamlandı (14 Eyl, ADR-0059; T07 deterministik netleştirme ADR-0063); T08 kısmi |
| M12 | Anomali/kırılma/öncülük doğruluğu | P0/P1 | M03; M09/M11 ile entegrasyon | Analitik | Çekirdek tamamlandı (13 Eyl, ADR-0052; T06 gerçek veri ve düzey sıçraması 14 Eyl ADR-0063); T03 kısmi |
| M13 | İddia doğrulama ve kanıtın doğru sunulması | P0 | Mevcut kod; M03/M07/M11 ile entegrasyon | Agent + veri + UI | Çekirdek tamamlandı (13 Eyl, ADR-0050); T04/T07/T11/T12 açık |
| M14 | Kullanıcı arayüzü ve tam çıktı indirme | P1 | M10, M11, M13 | UI + API | Çekirdek tamamlandı (14 Eyl, ADR-0055); T11/T12 açık |
| M15 | Süre/çıktı bütçeleri ve otomatik kontroller | P1/P2 | M01; M02 ölçümleri | Agent + geliştirme altyapısı | Çekirdek tamamlandı (14 Eyl, ADR-0061); ölçüm T01/T02 M16'dan |
| M16 | Birleşik kabul ve görülmemiş veri provası | P0 | Tüm zorunlu uygulama milestone'ları | Ekip + değerlendirme | Çekirdek tamamlandı (14 Eyl, ADR-0063, `docs/M16_KABUL_RAPORU.md`); T02/T04/T07/T10 kısmi, T11 ekip |
| M17 | Teslim, belgeler, merge ve freeze | P0 | M16 | Ekip koordinasyonu | Hazırlık tamamlandı (14 Eyl): belgeler, merge provası, sır taraması, operasyon tarifi; main'e birleştirme, freeze etiketi ve T09/T11/T12 kullanıcı/ekip kararı |

Numaralar tek bir seri geliştirme sırası değildir. M05, M07, M12 ve M13'teki belirli hatalar motor seçimini beklemeden mevcut kodda düzeltilebilir. Paralel çalışma ancak sorumlular ve dosya sahiplikleri belli olduktan sonra yapılır; bu belge arka planda agent veya görev başlatmaz.

## 5. Ayrıntılı milestone'lar

### M00 — Kapsam, açık kararlar ve iş bölümü

**Neden:** Aynı çalışmanın farklı branchlerde tekrar üretilmesi ve eski dokümanların güncel karar sanılması zamanı tüketir. Ekip 14 Eylül'de baseline ve iş bölümü belirleyecek; o görüşmeye somut karar listesiyle gidilmeli.

**Teslimat:** Kaynaklı gereksinim matrisi, açık karar defteri ve her iş için sorumlu/gözden geçiren listesi.

- [x] **M00-T01:** Transkriptteki bütün zorunlu demo davranışlarını kabul senaryolarına eşleştir; örnek finans sorularını ürünün alan sınırı olarak yazma.
- [x] **M00-T02:** BDDK/EVDS için zorunlu seri, kırılım ve tarih kapsamını belirle; belirsiz maddeleri mentöre iletilecek tek listede tut.
- [x] **M00-T03:** Kesinleşen normal kullanıcı Analyst / kalıcı yazma-silme Architect sınırını kabul metnine işle; jüri demosunda iki akışın nasıl gösterileceğini ve silme kapsamını netleştir.
- [x] **M00-T04:** Motor seçimi, kabul ölçütleri, çıktı formatları ve performans eşiklerini açık kararlar olarak ayır; önerileri kesinleşmiş gibi işaretleme.
- [x] **M00-T05:** Ekipte devam eden ve push edilmemiş işleri öğren; inceleme snapshot'ından sonraki commitleri karşılaştır.
- [x] **M00-T06:** Her milestone için sorumlu, gözden geçiren, bağımlılık ve ilk teslim tarihini ekipçe ata; kişileri varsayımla atama.
- [x] **M00-T07:** Mentör dosyasındaki eksik ikinci cevabı tamamla; kota konusunda transkript/ADR/yeni yanıt tarihlerini ayır.
- [x] **M00-T08:** Paylaşılan sunucu, kullanıcı sayısı, 81 il kapsamı ve JS gerektiren siteler gibi belirsizliklere karar veya açık risk kaydı ekle.

**Kabul:** Her zorunlu gereksinimin en az bir milestone ve kabul senaryosu vardır; her açık kararın sahibi ve neyi engellediği bellidir. Karar bekleyen bir alan, bağımsız hata düzeltmelerini gereksiz yere durdurmaz.

**Risk / sınır:** Bu milestone ayrıntılı plan yapmak uğruna geliştirmeyi durdurmamalı. Kesinleşen kapsam burada korunur; çalışma varsayımları işaretlenir.

### M01 — Tek ve tekrar kurulabilir yerel çalışma ortamı

**Neden:** Mevcut varsayılan ayarlar seed DB'ye bağlanıyor; eksik lakehouse-core yolu yüzünden bazı yetenekler açılmıyor. Başka geçici dizindeki çalışan demo, tek başına teslim kanıtı değildir.

**Teslimat:** Sabit kod sürümleri, kalıcı dizin düzeni, gerçek çalışma DB'si, kurulum/başlatma komutları ve başlangıç doğrulama raporu.

- [x] **M01-T01:** Agent ve veri commitlerini kayıt altına al; bu çalışma hattında catalog-breadth'i başlangıç kabul et, takımın son kararı olduğunu iddia etme.
- [x] **M01-T02:** Lakehouse kodunu geçici scratchpad bağımlılığı olmadan erişilebilir hâle getir; izolasyon/entegrasyon yöntemi mevcut kullanıcı değişikliklerini korusun.
- [x] **M01-T03:** Agent/veri ayrı bağımlılık ortamlarını kilit dosyalarıyla kur; desteklenen Python sürümünü temiz ortamda doğrula.
- [x] **M01-T04:** `LAKEHOUSE_PATH`, `LAKEHOUSE_CORE_DIR`, `LAKEHOUSE_CLI`, `INGEST_ALLOWED_ROOT`, `CHART_DIR`, `GEO_DIR` yollarını açık ve taşınabilir biçimde düzenle; gizli değerler ayrı kalsın.
- [x] **M01-T05:** Demo ve geliştirme seed modlarını başlangıçta ayırt et; yanlışlıkla seed açıldığında bunu görünür kıl. Demo modu beklediği yetenek yoksa sebebiyle başarısız olsun.
- [x] **M01-T06:** Ön kontrol: DB şeması, yüklü veri, katalog, Gold güncelliği, CLI erişimi, izinli dosya alanı ve gerekli servis yapılandırması. Anahtarların yalnız kullanılabilirlik durumu gösterilsin.
- [x] **M01-T07:** Salt-okunur kontrolleri canlı veri indiren veya kalıcı veri değiştiren komutlardan ayır; başlatma işlemi farkında olmadan bütün kataloğu çekmesin.
- [~] **M01-T08** (Claude temiz klon provası yapıldı; başka ekip üyesi M17'de): Temiz klasörden kurulum ve yeniden başlatma provasını başka bir ekip üyesine yaptır; gizli terminal override'larını dokümante et.

**Kabul:** Belgelenmiş komutlarla beklenen adaptör ve araç yetkileri açılır; veri/Gold yeteneği eksikse açık neden görünür. Sadece `--health` veya UI açılışı, tam demo kabulü sayılmaz. Var olan veri yanlışlıkla sıfırlanmaz.

**Risk / sınır:** Agent ve veri tarihçeleri ayrı. Ana dala merge bu aşamanın zorunlu yöntemi değildir; kalıcı ve açık bir geliştirme entegrasyonu yeterlidir. Nihai merge M17'de değerlendirilir.

### M02 — Güncel motor kıyası ve güçlü katkıların aktarılması

**Neden:** Eski V3 üstünlük raporu eski agent commitine aittir. İki motorun bugünkü davranışları eşit koşullarda değerlendirilmeden bütün motoru değiştirmek ya da katkıları bırakmak yanlış karar olabilir.

**Teslimat:** Sürüm bilgili kıyas raporu, ham koşu kayıtları, baseline kararı ve korunacak modül/araştırma listesi.

- [x] **M02-T01**: Karşılaştırılan iki güncel commit, aynı MIA modeli/ayarları, aynı DB ve kaynak fikstürlerini sabitle.
- [x] **M02-T02** (U3: V3'te lead_lag yok, 'çağrılmadı' olarak sayıldı): Ortak çekirdek yetenek kıyasını tam ürün yetenek kapsamından ayır; V3'te eksik araçların yokluğunu dürüstçe raporla.
- [x] **M02-T03** (durum kontrolleri: tablo, SQL, araç, adım limiti; metin puanlanmadı): Doğruluk, aktif tablo korunması, hatalı öncül reddi, kaynak/kanıt ve belirsiz soru davranışını durum üzerinden ölç; yalnız metin benzerliği kullanma.
- [x] **M02-T04** (U1–U5 koşudan önce yazıldı): Finans, finans dışı, yeni dosya, erişilemeyen URL ve daha önce görülmemiş soruları koşudan önce seç.
- [x] **M02-T05** (3 tekrar; belirgin üstünlük gösterilemedi yazıldı): Tekrarlı koşu bütçesini kararlaştır. Revize öneri: üç tekrar ilk tarama; kritik veya kararı değiştirebilecek dalgalı vakalara hedefli ek tekrar. Koşu sırasını dengele, ağ/model değişkenliğini kaydet. Yakın sonuç eşitlik kanıtı değildir; belirgin üstünlük gösterilemedi diye raporla. Kesin bütçe ve başarı eşiği açık karardır.
- [x] **M02-T06**: Süre, LLM çağrısı, prompt/completion token, araç hatası, onarım ve adım limitini birlikte raporla; test adedini kalite puanı sayma.
- [x] **M02-T07** (aktarım listesi ADR-0053; koşucu+18 vaka yazarlıkla alındı): V3 benchmark koşucusu, ham deneyler, alan notları, salt-okunur paralellik ve çıktı sınırını tek tek değerlendir; aktarımda yazarlık/tarihçe korunsun.
- [ ] **M02-T08** (ertelendi: tek workspace, DuckDB bağlantı sınırı; M15'te ölçüm): Paralelliği yalnız bağımsız salt-okunur araçlarda dene; ortak workspace yazan işlemleri ve DuckDB bağlantı sınırlarını koru.
- [x] **M02-T09** (ADR-0053; K01 değişmedi): Seçilen baseline ve reddedilen alternatifin gerekçesini ADR'ye yaz; aktarılan her modülü uygun regresyonla doğrula.

**Kabul:** Ekip, doğruluk/kanıt/yetenek/süre farklarını aynı koşular üzerinden açıklayabilir. Aktarım kaydı hangi dosyanın hangi kaynaktan geldiğini gösterir. Eski raporlar tarihsel kalır.

**Risk / sınır:** Ölçüm sonucu gelmeden “bizim motor kesin daha iyi” veya “V3'e geçiyoruz” kararı yazılmaz. Benchmark ortam sorunları motor kalitesiyle karıştırılmaz.

### M03 — Jenerik veri modeli ve kaynak sözleşmelerinin netleştirilmesi

**Neden:** Jeneriklik temel şarttır. Mevcut Silver'ın seri/tarih/değer yapısı birçok alanı taşır fakat her işlem tablosunu veya ilişkiyi doğal olarak temsil etmez. Kaynak adapter'ı eklemek ile motoru tekrar yazmak farklı işlerdir.

**Teslimat:** Desteklenen veri şekilleri, semantik metadata ve source capability sözleşmesi; finans dışı referans fikstürleri.

- [x] **M03-T01** (`M03_VERI_SOZLESMESI.md` §1): Zaman serisi, tarihsiz tablo, işlem/olay tablosu, birden fazla varlık ve belge içinden tablo için mevcut desteği matrise dök.
- [x] **M03-T02** (Silver zaman serisi / oturum tabloları; A09 birleştirme zorunlu, ADR-0059): Önerilen sınırı sözleşmeye yaz: Silver zaman serisi taşır; tarihsiz/işlemsel tablolar oturum workspace'inde analiz edilir, otomatik kalıcı yayına girmez. Her tabloya zorla tarih veya ekonomik ölçüm türü uydurma. İki yeni tablonun anahtarla birleştirilmesi kullanıcı kararıyla zorunludur; mevcut tek `t` tablosu bunun tamamlandığı anlamına gelmez.
- [x] **M03-T03** (§2): Kaynak/şema/kolon/anahtar/birim/frekans/kapsam/null/kalite/provenance bilgilerinin taşıdığı sözleşmeleri gözden geçir.
- [x] **M03-T04** (kaynak ipuçları JSON'a taşındı, alan sızıntısı testleri; ADR-0060): Kaynağa özel kod ve alan bilgisi ile genel hesap/politika kodunu ayır; BDDK/EVDS adları core kararlarının önkoşulu olmasın.
- [x] **M03-T05** (§4 yetenek tablosu): Yeni source adapter için yetenekler: erişim yöntemi, kimlik doğrulama türü, format, sayfalama/pencereleme, bütçe, hata ve kanıt zarfı.
- [~] **M03-T06** (bellek-içi adaptör sözleşme testi; REST/DB/stream adaptörleri uygulanmadı, eklenme yeri belgeli): REST API, DB, stream ve farklı auth için genişleme noktalarını belgeleyip bir adapter sözleşme testi yaz; hepsi uygulanmadan uygulanmış gibi sunma.
- [x] **M03-T07** (boş katalog + profil yenileme, ADR-0048/0056): Temiz/boş katalog açılışını, katalog değişince alan profilinin yenilenmesini ve eski alan bağlamının temizlenmesini doğrula.
- [x] **M03-T08** (`tests/fixtures/generic`, `test_m03_jenerik.py`): Finans dışı zaman serisi ve iki ayrı tarihsiz tablonun anahtar üzerinden birleştirilmesi için kabul fikstürleri hazırla; beklenen sonuçlar modelden bağımsız olsun. Yinelenen anahtar ve eşleşmeyen satır varyantları bulunsun.
- [x] **M03-T09** (§6): Desteklenmeyen şekli doğru gerekçeyle reddetme veya kullanıcıdan eşleme isteme yolunu tanımla; sessiz veri kaybı olmamalı.

**Kabul:** Aynı agent kodu finans ve finans dışı veriyle çalışır; alan değişikliği katalog/konfigürasyon/adapter üzerinden yapılır. Yeni alanda finans varsayımları cevaba veya SQL'e sızmaz. Destek sınırı açıkça gösterilir.

**Risk / sınır:** Jeneriklik “her dosyayı kusursuz otomatik anlama” vaadi değildir. Belirsiz semantik sorulmalı; kapsamı açıkça tanımlanmış genişleyebilir yapı hedeflenmeli.

### M04 — Analyst/Architect yetki ve kalıcı yayın sınırı

**Neden:** Geçici workspace analizi ile kalıcı ingest/promotion yolları mevcut kodda zaten ayrıdır (ADR-0039). Eksik olan normal kullanıcı ile Architect profil sınırıdır: uygun CLI ortamında yazıcı araçlar aynı registry'ye kaydedilir. Kullanıcı yeni kararıyla normal kullanıcıya kalıcı yazma/silme kapalı, Architect'e açık; jüri demosunda iki akış da gösterilebilir.

**Karar durumu:** Rol sınırı kullanıcı tarafından kesinleştirildi. Yerel başlatma profilleri önerilir; jüri demosunda her iki akış kullanılabilir, normal kullanıcı sohbet veya istek parametresiyle kendisini Architect yapamaz. Yeni kimlik sistemi otomatik gereksinim sayılmaz. Kullanıcı fiziksel silme ve boş ortamdan yeniden kurulum hedefini açıkladı. Öneri: günlük pasifleştirme ve ayrı, açık hedefli Architect tam sıfırlama işlemi; kod ve kurulum dosyaları korunur.

**Teslimat:** Yetki matrisi, ayrı registry/işletim profilleri ve operator yayınlama akışı.

- [x] **M04-T01** (ADR-0056 §1–3): Analyst'in okuyabileceği, geçici oluşturabileceği ve kalıcı değiştiremeyeceği kaynakları kesinleştir.
- [x] **M04-T02** (Analyst kayıt defterinde yok; `architect_enabled`): Son kullanıcı registry'sinden kalıcı ingest/promotion/build araçlarını çıkar veya yalnız operator profiline kaydet; UI gizlemesiyle yetinme.
- [x] **M04-T03** (kapı ≠ yetki; UNKNOWN_TOOL): `tool_gate` ile yetki denetimini ayır: modelin araç adını elle üretmesi kapalı yeteneği açmamalı.
- [x] **M04-T04** (oturuma özel uploads/, M10): Kullanıcı dosyasını oturuma özel alanda hazırla; geçici dosya/SQL çalışması ortak katalog yayını sayılmasın.
- [ ] **M04-T05** (koşula bağlı; mevcut taslak→onay korunur): Koşula bağlı: yayın talebi arayüzü yalnız ihtiyaç doğarsa oluşturulsun; mevcut operator akışında kaynak, profil/eşleme, semantik belirsizlik ve kalite kontrolü gösterilmesi korunur.
- [~] **M04-T06** (tam sıfırlama iki adım + bootstrap ✓; pasifleştirme veri CLI'ında yok → koşula bağlı): Architect için ADR-0039'un taslak → inceleme → aktif yayın akışını koru; kalıcı yazma/silme hedefini ve geri alma sınırını açık göster. Pasifleştirme ile fiziksel tam sıfırlamayı ayrı işlemler olarak tasarla: hedef katalog/DB, RAW/Bronze/Silver/Gold, oturum ve cache bağımlılıklarını göster; kesin kapsamlı işlem onayı al. Kod/kurulum/sırlar sıfırlama kapsamına girmez. Fiziksel silme eski kanıtlara erişimi kaldırır; eski cevaplar tam kanıt gösteremez. İnsan onayı otomatik verified yapmasın.
- [~] **M04-T07** (Gold rızası istek bazlı, ADR-0039; rol bağı: Analyst'te kalıcı Gold build yok): Derived veriyle Gold kullanım tercihini rol ve işlemle bağla; eski sohbetten kalan “onaylıyorum” yeni/başka işlemi yetkilendirmesin.
- [x] **M04-T08** (yazma ayrı süreç; reset/geçiş oturumu ve bağlantıları yeniler): Yazıcı bağlantıları/ayrı süreç izinleri ve okuyucu kapat–aç davranışını koru; oturum resetinde bağlantılar temizlensin.
- [x] **M04-T09** (A20/A21 testleri: anahtarsız 403, içerik yetki vermez; Architect akışı test ve canlı): Analyst üzerinden doğrudan araç çağrısı ve prompt enjeksiyonuyla kalıcı yazma/silmenin yapılamadığını dene; normal dosya analizi çalışsın. Demo Architect akışında onaylı yayın ayrıca çalışsın. Geçmiş onay + güncel ret ve önceden izin verilmiş kaynak varyantlarını sınamaya ekle.
- [x] **M04-T10** (ADR-0056 not; ADR-0039 okunuşu güncellendi): Karar sonrası ADR-0039, UI/CLI dokümanı ve ilgili eski rol açıklamalarını güncelle; tarihsel kaydı silme.

**Kabul:** Analyst akışının öncesi/sonrasında ortak DB ve katalog değişmez; dosya analizi/çıktı üretimi çalışır. Operator yetkisi açık bir çalışma sınırından gelir. Bir metin ifadesi yönetici yetkisi oluşturmaz.

**Risk / sınır:** Paylaşılan sunucu hedeflenirse kimlik ve oturum izolasyonu yeniden ele alınır. Yerel demo için ayrı operator CLI/profili yeterli olabilir; bu, genel sunucu güvenliği iddiası değildir.

### M05 — Web ve dosya erişim sınırlarının düzeltilmesi

**Neden:** Agent fetch yolu ilk hostu kontrol ettikten sonra yönlendirmeleri otomatik takip ediyor. Public adres üzerinden private adrese ulaşma sınırı korunmuyor. Veri ekibinin generic connector'ı her yönlendirmeyi doğruluyor; davranışlar ayrışmış.

**Teslimat:** Normal istek, robots ve indirme için tutarlı erişim politikası ve regresyon kanıtı.

- [x] **M05-T01:** Her redirect hedefini istekten önce doğrula; izinli şema/host/IP politikası bütün adımlarda uygulansın.
- [x] **M05-T02:** Robots isteğini de aynı güven sınırından geçir; robots üzerinden özel adrese veya sınırsız içeriğe erişilemesin.
- [x] **M05-T03** (14 Eyl, ADR-0064: ortak vaka dosyası `docs/sozlesmeler/url_erisim_vakalari.json` iki paketin testinde; ajan tarafındaki multicast/site-local/.internal açığı kapandı): Normal fetch ve veri generic connector'ı için ortak davranış vakaları oluştur; ayrı süreç sınırını bozmadan sözleşme uyumunu denetle.
- [x] **M05-T04:** İstek, yönlendirme sayısı, toplam süre ve byte sınırlarını birlikte uygula; akış okuma hatasında açık yanıt/bağlantı kapansın.
- [x] **M05-T05** (mevcut: izinli kök, symlink çözümü, boyut, tür; upload adı → M10-T02): Yerel dosyada izinli kök, symlink çözümü, dosya boyutu ve desteklenen tür kontrollerini koru; upload dosya adı fiziksel yolu belirlemesin.
- [x] **M05-T06** (kimlik bilgisi taşınmıyor; başka hosta yalnız UA/Accept gider; hata metni sebep cümlesi): Yetkili bağlantı kimlik bilgisi farklı hosta yönlendirmede taşınmasın; hata ve trace metinlerine sızmasın.
- [x] **M05-T07:** Kontrollü sahte taşıma ile public→private, public→public, redirect döngüsü, DNS hatası ve yarım indirme vakalarını çalıştır.

**Kabul:** Engelli hedefe ağ isteği yapılmadan ret verilir; normal açık kaynaklar çalışır. Ret sebebi kullanıcıya anlamlı gelir. Güven testleri gerçek özel servislere erişerek yapılmaz.

**Risk / sınır:** DNS doğrulaması ile bağlantı kurulması arasındaki fark ayrıca değerlendirilmeli; giderilmeyen sınırlar açık yazılmalı. “SSRF tamamen çözüldü” gibi kapsamı aşan iddia kurulmaz.

### M06 — Tavily, ilgili bağlantı keşfi, yetkili erişim ve fallback

**Neden:** Arama sonucu bulmak, içeriğe erişmek ve doğru veriyi çıkarmak ayrı yeteneklerdir. Hesap hazırlamak bütün sitelere erişim garantisi değildir; demo erişilemeyen URL'de de kontrollü devam edebilmelidir.

**Teslimat:** Kaynak seçimi/erişim/parse/fallback zinciri, kaynak bazlı erişim matrisi ve sade kullanıcı mesajları.

- [x] **M06-T01** (prompt kuralı): Tavily sonuçlarını kaynak adayı olarak işle; snippet'i doğrulanmış tablo verisi sayma. Gerekli içeriği kaynağından aç.
- [x] **M06-T02** (`web/search.py`): MIA, Search ve Retrieval sağlayıcı sözleşmelerini ayrı tut; Tavily değişimi ana motoru değiştirmesin.
- [x] **M06-T03** (`link_score` veri bağlantısı +10): Soruya göre doğrudan CSV/JSON/XLSX/PDF/API/tablo bağlantısına öncelik ver; sayfa gezme gerekçesi trace'e yazılsın.
- [x] **M06-T04** (sayfa ≤5, derinlik ≤1, süre ≤60 s, aynı alan adı, robots): Aynı alan adı, robots, sayfa/süre/derinlik bütçelerini uygula. Mevcut araç şemasının derinlik sınırını doğrula; 2–3 seviye mentörün makul üst sınır önerisidir, her istekte zorunlu tarama değildir.
- [x] **M06-T05** (js_required eklendi; ADR-0061): Kayıp veri, yanlış dönem, 404, 429, login, CAPTCHA/bot, ücretli erişim ve JS kabuğunu ayrı nedenlerle sun.
- [x] **M06-T06** (ADR-0034 `decide`): Kaynak sabitlenmişse alternatif kaynağı önerip kullanıcı tercihini al; sabitlenmemişse kullanılan alternatifi açıkça belirt.
- [x] **M06-T07** (M17 operasyon tarifinde): Demo aday kaynaklarında ekip hesabı/API kullanım hakkı, erişilebilen içerik, bağlantı yöntemi ve son kontrol zamanını kaydet. Hesap açma işi ekip/operator sorumluluğunda kalsın.
- [x] **M06-T08** (seçenek yalnız anahtarı kullanan bağlayıcıda): Desteklenen yetkili bağlantı gerçekten uygulanmadan “ekip hesabıyla devam edebilirim” deme; credential varlığı ile kullanılabilir adapter'ı ayır.
- [~] **M06-T09** (uygulanmadı, K08 opsiyonel; js_required dosya yüklemeye yönlendirir): JS kaynaklar için ihtiyaç doğrulanırsa ayrı browser capability değerlendir; otomatik olarak bütün web hattını tarayıcıya taşıma.
- [x] **M06-T10** (arayüz düğmeleri): Erişilememe hâlinde dosya yükleme, yetkili bağlantı veya alternatif kaynakla devam seçeneklerini çalışır UI eylemlerine bağla.
- [x] **M06-T11** (kanıt paneli web_sources/web_unused): Kullanılan kaynak için URL/zaman/hash/erişim sonucu; kullanılmayan adaylar için trace tut. Kaynak değişimi cevapta gizlenmesin.
- [x] **M06-T12** (arama bütçesi kartta; tarama bütçe notu; model kesintisi M15): Tavily bütçesi, MIA hatası, internet kesintisi ve kısmi crawl durumunda kısmi sonucu/kapsamı dürüstçe bildir.

**Kabul:** Kullanıcı kaynak neden kullanılamadı ve hangi seçeneklerle devam edebilir anlayabilir. Kaynak değiştirme kararı soru kısıtına uyar. Hesap veya otomasyon desteği olmayan site için başarı vaadi verilmez.

**Risk / sınır:** İsim verilen sitelere erişim zamanla değişebilir; kaynak matrisi son doğrulama zamanını taşır. Hesap açmak CAPTCHA veya bot engelini aşma yetkisi sağlamaz.

### M07 — Toplu ingestion ve provenance'ın tek üretim akışında tamamlanması

**Neden:** Mevcut ortak pipeline run/uyarı kayıtlarını tutarken toplu katalog betiği doğrudan artifact/parser/Parquet yoluna gidiyor. Uyarılar yalnız logda kalırsa Silver yeniden kurulumunda kalite bilgisi kaybolabilir.

**Teslimat:** Tekrar çalıştırılabilir çok artifactli ingest akışı, run/artifact/warning kayıtları ve Silver'a kadar doğrulanmış aktarım.

- [x] **M07-T01** (ADR-0057 bağlam): CLI ingest, toplu script ve ad-hoc yolunun veri/kayıt sınırlarını çiz; tekrar eden sorumlulukları belirle.
- [x] **M07-T02** (varlık başına iniş + run): Bir artifactin önceden bulunması sonraki yeni artifactleri engellemeyecek ortak üretim işlemi oluştur veya mevcut pipeline'ı bu davranışla genişlet.
- [x] **M07-T03**: Her run için başlangıç, sonuç, kısmi başarı/başarısızlık, süre ve satır sayıları kalıcı olsun.
- [x] **M07-T04**: Her artifact run'a bağlansın; parser uyarıları artifact kapsamı ve sırası korunarak yazılsın.
- [x] **M07-T05** (`describe_exception`): Hata metinlerinde redaksiyon ve uzunluk sınırlarını koru; kontrolsüz response/credential yazma.
- [x] **M07-T06** (mevcut test `silver/test_build.py`): Silver rebuild sonrası run_id, source_warning ve diğer kalite işaretlerinin sessizce iyileştirilmediğini doğrula; kayıtsız artifacti uyarısız kaynak sayma.
- [x] **M07-T07** (mevcut `infrastructure/test_artifacts.py`, `test_parquet.py`): Aynı içeriğin farklı çekim zamanı, farklı dataset metadata'sı ve farklı parser konfigürasyonu için kimlik kurallarını test et.
- [x] **M07-T08** (2016 kurulumu: kimlik çatışması 0, revizyon çatışması 0; 81 'aynı adres farklı sha' FinTürk form isteği, çatışma değil): Tarihsel 95 artifact çatışması iddiasını hedef DB üzerinde yeniden envanterle; güncel sayı gibi kopyalama. Çözüm her çatışma türüne gerekçe taşısın.
- [x] **M07-T09** (mevcut `_deduplicate_boundaries`, revizyon kurulumu durdurur): Pencere sınırı tekrarlarını tekilleştir; değer revizyonu çatışmasını ayrı raporla, sessiz son-kayıt seçme.
- [x] **M07-T10** (`--report`, eksik seri çıkış 1): `--only` ile istenen seri bulunamadığında veya hiç işlenmediğinde başarı sayılmasın; kapsam raporu istenen/işlenen/atlananın farkını açıklasın.
- [x] **M07-T11** (`close_stale_runs`): Kesinti sonrası bayat running kaydı, yarım RAW/Bronze ve yeniden deneme davranışını belgeleyip test et.

**Kabul:** Aynı girdi ikinci koşuda veriyi çoğaltmaz; yeni artifact işlenir; parser uyarısı run→Bronze→Silver izinde bulunur. Sonuç raporu kısmi başarıyı tam başarı olarak sunmaz.

**Risk / sınır:** Geçmişte kaydedilmemiş uyarılar sonradan tahmin edilerek doldurulmaz. Yeniden parse/fetch gerekiyorsa ayrı işlem ve kanıt olarak kaydedilir.

### M08 — BDDK/EVDS kapsamı ve semantik hazır oluş

**Neden:** Katalogdaki 2.214 kayıt, 2.214 kullanılabilir seri anlamına gelmiyor. Zorunlu finans örnekleri için doğru birim, ölçüm türü, tarih ve veri derinliği şart; keşif kataloğunun tamamını rastgele doldurmak önceliği dağıtır.

**Teslimat:** Gereksinim→seri→semantik kanıt→yüklü gözlem→Gold hazır matrisi ve güncel kapsama raporu.

- [x] **M08-T01** (681 zorunlu seri katalogdan; L3-02 alt kalem kuralı prompt'ta, alandan bağımsız): BDDK aylık/haftalık/FinTürk ve EVDS için zorunlu soru ailelerinin gerektirdiği seri kimliklerini çıkar.
- [x] **M08-T02** (katalog alanları; M08 raporu §1): Her seri için birim/çarpan, frekans, stok/akım/endeks/oran, toplama kuralı, kaynak kapsamı ve kanıtı kaydet.
- [x] **M08-T03** (1.533 keşif serisi silinmedi, 'tanımlı ama yüklü değil' cevabı): 1.533 unknown/birimsiz seriyi doğrulanacak öncelikli aileler ve keşif için saklanacaklar olarak ayır; katalogdan topluca silmeyi varsayılan çözüm yapma.
- [x] **M08-T04** (rapor §3: boşluk 0; kaynak geç yayını ve EVDS kırpılması ayrıldı, kırpılma düzeltildi): 2021-01–2026-06 için yayın takvimine göre beklenen ve mevcut gözlemleri karşılaştır; veri yokluğu/erişim yokluğu/anlamı belirsiz ayrımı yap.
- [x] **M08-T05** (81 il tamamı yüklü; harita lisansı K09): FinTürk 12 il demo alt-kümesi ile 81 il katalog kapsamını ayır; il soruları ve harita kabulüne göre gerekli veriyi tamamla.
- [~] **M08-T06** (bağlayıcı destekliyor; canlı çeyreklik yanıt ölçülmedi): EVDS çeyreklik canlı yanıt biçimini doğrula; güncel katalogda 152 çeyreklik kayıt olduğu bilgisini kullan. Kod desteklemiyorsa açık destek eksikliği kaydet.
- [x] **M08-T07** (TP.TUKFIY2025.GENEL 2025=100 küratörlüğü; TP.FG.J0 2003=100; splice yok; KFE bazı doğrulanmamış notu): TP.FG.J0, TP.TUKFIY2025.GENEL ve KFE için baz/kapsam/yayın durumu kanıtlarını karşılaştır; farklı bazlı endeksleri kendiliğinden ekleme/splice etme.
- [x] **M08-T08** (rapor §5): TÜFE terfi için eski açıkların hangi adımlarının gerçekten kapandığını kaydet; eski belgeyi güncel canlı doğrulama yerine kullanma.
- [x] **M08-T09** (81 il ↔ ulusal: medyan %0,013): Aylık/haftalık/il kaynakları arasında karşılaştırılabilir alanlarda mutabakat kontrolü yap; farklı tanım/frekans varsa farkı açıklamadan eşitlik bekleme.
- [~] **M08-T10** (şema/birim reddi mevcut testler; eksik ay testi yok, kapsam ölçüldü): Source schema değişimi, eksik ay ve anlamsız birim için yayın reddi/uyarı testleri oluştur.
- [x] **M08-T11** (ön kontrol, /api/status, durum penceresi: katalog/doğrulanmış/tanımlı/yüklü/Gold'a hazır): Katalog, semantiği doğrulanmış, yüklü, sorgulanabilir ve Gold'a hazır sayıları UI/status raporunda ayrı göster.

**Kabul:** Zorunlu soruların verisi yüklenmiş ve semantik kararı izlenebilirdir; eksikler isimleri ve nedenleriyle raporlanır. “681 anlamı tanımlı” sayısı “681 yüklü/verified” diye sunulmaz.

**Risk / sınır:** Tüm EVDS serilerini ingest etmek bu planın otomatik gereksinimi değildir. Resmî kapsamın nasıl yorumlandığı M00 kararına bağlanır; kaynakların hiç yayınlamadığı dönemler uydurulmaz.

### M09 — Gold, dönem hizalama ve reel dönüşüm

**Neden:** Toplantıdaki sorular tabloya faiz/KFE eklemeyi, nominal krediyi enflasyondan arındırmayı ve farklı frekansları karşılaştırmayı içeriyor. Bunlar güvenilir veri semantiği ve deterministik hesap gerektiriyor.

**Teslimat:** Kaynak semantiğine bağlı dönüşümler, mevcut tabloyu koruyan join/hesap akışı ve katkı gözlemlerine inen Gold kanıtı.

- [x] **M09-T01** (ADR-0058): `align_frequency`, `decompose_cumulative`, `join_on_period` mevcut davranışlarını zorunlu senaryolara eşleştir; çalışan fonksiyonları tekrar yazma.
- [x] **M09-T02** (align_frequency kuralları, FREQUENCY_MISMATCH): Stokta dönem sonu, dönemlik akımda uygun toplam, oran/endekste açık kural uygula; frekans düşürmeyi veri olmayan ince frekans üretiminden ayır.
- [x] **M09-T03** (decompose_cumulative stokta ret): Kümülatif seride yıl başı/reset ve önceki dönem tabanını doğrula; stok serisine kümülatif ayrıştırma uygulanmasın.
- [x] **M09-T04** (join_on_period dış birleştirme, kapsam farkı görünür): Ay/hafta sınırları, tatil nedeniyle değişen gözlem günü, eksik dönem ve farklı coverage join sonuçlarında açık olsun.
- [x] **M09-T05** (`workspace_real_value`): Reel dönüşüm için baz dönem ve endeks serisini belirle. Örnek formül `reel_t = nominal_t × endeks_baz / endeks_t`; geçerli birim ve baz olmadan hesap yapma.
- [x] **M09-T06** (tek endeks, baz kapsamı, splice yok): Geçerli TÜFE/KFE baz eşlemesi bulunamıyorsa farklı bazları sessiz birleştirmek yerine gereken bilgiyi veya kapsam sınırını bildir.
- [~] **M09-T07** (hesap araçta; G9 anlatı aritmetiği grounding ile yakalanır, ayrı kolon kuralı prompt'ta): Hesap, büyüme, fark ve yüzdeleri SQL/hesap araçlarında açık kolon olarak üret; G9'daki anlatı içinde hesap yapma kalıntısını kapat.
- [x] **M09-T08** (tablo bozulmaz, aylık hizalama denetimi): Mevcut tabloya faiz/reel değer/KFE eklerken satır anahtarını, eski kolonları ve sıralamayı koru; çoğalan veya eşleşmeyen satırları denetle.
- [x] **M09-T09** (Gold defteri Silver parmak izi, bayat işareti): Silver veya semantik katalog değişiminde Gold'un bayatlığını denetle; bayat verinin kullanım davranışını açıkça belirle.
- [x] **M09-T10** (reddedilen metrik tabloyu düşürür): Reddedilen Gold build önceki tabloyu geçerli gibi bırakmasın; build kimliği, kaynak gözlemleri, artifact ve formül taşınsın.
- [x] **M09-T11** (reel dönüşüm Analyst; kalıcı Gold Architect): Kalıcı Gold build'i M04 operator sınırına, geçici dönüşümü Analyst yeteneğine bağla; sırf hesap için ortak kataloğa yayın zorunlu olmasın.

**Kabul:** Beklenen hesaplar modelden bağımsız referans sonuçla uyuşur; tabloyu bozmadan yeni kolon eklenir. Sıfır/null endeks, eksik taban, yanlış stok/akım ve uyuşmayan baz kontrollü sonuç verir.

**Risk / sınır:** Yeni genel reel dönüşüm aracı veya mevcut SQL/Gold kompozisyonu seçimi uygulama sırasında ölçülür. Finans formülü genel orchestration'a sabitlenmez; ölçüm/transform sözleşmesine yerleştirilir.

### M10 — Kullanıcının dosya, URL, PDF ve görsel giriş akışı

**Neden:** Kullanıcının “dosya ver” kutusuna sunucu dosya yolu yazması yeterli ürün akışı değil. Demo sırasında yeni PDF/Excel ve bilinmeyen tablo gelebilir; mevcut OCR/parse çekirdeği gerçek yükleme akışına bağlanmalı.

**Teslimat:** Dosya seç/yükle → profil/tablo seç → gerekirse açıklama sor → oturum tablosu → analiz akışı.

- [x] **M10-T01** (`M10_DOSYA_GIRISI.md` §1): Desteklenen uzantı/MIME/format matrisini çıkar: CSV/TSV, XLSX, JSON kayıtları, HTML tablo, PDF ve görsel; legacy XLS desteğini mevcut kütüphane varmış gibi varsayma.
- [x] **M10-T02**: UI dosya seçicisi ve sunucu upload yüzeyi ekle; oturuma bağlı güvenli dosya kimliği kullan, kullanıcının yerel yolu sunucu tarafından biliniyor sayılmasın.
- [x] **M10-T03** (25 MB; OCR sayfa 5 / 90 s mevcut): Dosya boyutu, satır/sütun, sayfa, süre ve bellek sınırlarını ölçüp yapılandır; limit aşımını anlamlı seçenekle bildir.
- [x] **M10-T04** (tarih biçimi tanınır ve çevrilir, belirsizse sorulur; ayraç kuralı; güven puanı yerine gerekçe notu): Profilciyle ayraç, tarih biçimi, sayı biçimi, kolon tipleri ve aday anahtarları çıkar; belirsizliğe confidence/gerekçe ekle.
- [x] **M10-T05** (çoklu sayfa sorulur, .xls ret; birleşik başlık uyarısı profilcide): XLSX sheet seçimi, formüllü hücreler, birleşik başlıklar ve null değerler için mevcut parser kısıtlarını UI'ye taşı; destek dışı dosyayı sessiz düzleştirme.
- [~] **M10-T06** (sohbette `sheet`/`pages`/`table_index`; arayüz düğmesi açık): Çok tablolı HTML/PDF veya çok sayfalı belgede tablo/sayfa kimliği ve başlığı korunarak kullanıcı/model seçimi sağla.
- [x] **M10-T07** (mevcut OCR akışı: bütçe, kalite bayrağı, ayraç kuralları): PDF/görsel OCR sayfa bütçesi, zaman sınırı, düşük kalite, ondalık/binlik ayraç ve toplam tutarlılığı kontrollerini ürün akışında göster.
- [x] **M10-T08** ("OCR ile okundu, doğrulanmadı"; riskli hücre notu): OCR sonucu ile doğrulanmış veri arasındaki farkı kaybetme; riskli hücrelerin nedenlerini kullanıcıya göster ve daha net dosya/sayfa seçimi isteyebil.
- [x] **M10-T09** (415/400/413 + araç katmanı hata zarfı): Bozuk/şifreli/boş/destek dışı dosya ve VISION_MODEL erişimi yokluğunu ayrı hata sınıflarıyla ele al.
- [x] **M10-T10** (belge sha256 + sayfa/tablo etiketi + zaman, kanıt panelinde): Belge/sayfa/tablo/hücre, kaynak hash ve okuma zamanı oturum provenance'ına bağlansın; kopyalanan veri kaynağını kaybetmesin.
- [x] **M10-T11** (DIŞ İÇERİK çerçevesi; niyet yalnız kullanıcı metninden): Dosya içindeki talimatları veri olarak tut; dış URL çağrısı, yetki değişimi veya kalıcı yayınlama niyeti sayma.
- [x] **M10-T12** (sıfırlama siler; eski kanıt sha256 kalır, dosya açılmaz): Reset/temizlik/yeniden yükleme davranışını belirle; geçici dosya silinince eski indirilebilir kanıtın durumu açık olsun.

**Kabul:** Kullanıcı sunucu dosya yolu bilmeden yeni dosyayı yükleyip analiz ettirir. Birden fazla tablo arasında seçim yapılır; belirsiz birim/tarih uydurulmaz; ortak lakehouse Analyst yüklemesiyle değişmez.

**Risk / sınır:** Her belgenin otomatik doğru okunması garanti edilmez. Ret ve düzeltme akışı da başarılı ürün davranışıdır. Dosya yükleme kapsamı zorunlu; ayrıntılı destek listesi M00/M03'te kesinleşir.

### M11 — Çok turlu analiz, tablo korunması ve açıklama soruları

**Neden:** Jüri aynı konuşmada tabloya yeni kolon eklemek, karşılaştırmak ve yorumlamak istiyor. Varsayılan bir özet sorgunun aktif tabloyu küçültmesi veya belirsiz dönemin tahmin edilmesi sonraki bütün analizi bozabilir.

**Teslimat:** Açık oturum/aktif tablo/bakış sonucu kavramları, bağlama bağlı açıklama soruları ve takip sorularında korunmuş provenance.

- [x] **M11-T01** (ADR-0059): İki yeni kaynak tablosunu ayrı kimliklerle oturumda koru; birleştirme ikinci yüklemede ilk tabloyu kaybetmesin. Kaynak tablo, aktif sonuç, bakış sorgusu, önceki sürüm ve grafik/analitik kartının ne zaman değiştiğini sözleşmeye bağla.
- [x] **M11-T02** (ADR-0039 bakış modu): Özet/min/max/toplam sorgularında varsayılan bakış modunu koru; aktif tabloyu değiştiren eylem açık parametre ve kullanıcı amacı taşısın.
- [x] **M11-T03** (`workspace_join`): İki kullanıcı tablosunun join anahtarı/türü ve kolon çakışmalarını yönet; yinelenen anahtar, satır çoğalması ve eşleşmeyen satırları denetle. “Tabloyu bozmadan” isteğinde önceki kolon/satır/anahtar değerlerini karşılaştır; birleşen her kolonun kaynak izi korunsun.
- [x] **M11-T04** (bekleyen soru notu): Bekleyen açıklama sorusuna kısa yanıt geldiğinde hangi işlem/kolon/dönem için cevap olduğu bilinsin; tüm sohbet metni sınırsız yetki veya parametre havuzu olmasın.
- [x] **M11-T05** (netleştirme kuralı): Sonucu değiştiren eksikleri sor: birim/çarpan, tarih çözümü, veri tanımı, baz dönem, stok/akım ve kritik join anahtarı.
- [x] **M11-T06** (sunum tercihleri varsayılır ve belirtilir): Sonucu değiştirmeyen sunum tercihlerini makul varsayımla çöz; kullanılan varsayımı kısa ve görünür belirt.
- [x] **M11-T07** (14 Eyl: deterministik netleştirme — ≤2 içerik sözcüğü, dönem yok, ≥3 farklı katalog adı → aday listeli soru, LLM çağrılmaz; bekleyen soruya yanıtta susar (ADR-0063)): “Krediler arttı mı?” gibi belirsiz soruda olası yorumları veri kataloğundan üret; bir soru turunda gerekli alanları topluca iste, gereksiz soru zinciri kurma.
- [~] **M11-T08** (sorudan sayı M13 + nedensellik filtresi): Kullanıcının yanlış öncülünü düzelt; verilen yüzdeyi veya nedensel hikâyeyi kanıt sayma. Varsayımsal açıklamayı açıkça hipotez olarak ayır.
- [x] **M11-T09** (profil yenileme, sıfırlama): Alan/katalog değiştiğinde önceki finans bağlamını, stale arama sonuçlarını ve geçersiz tablo referanslarını temizle.
- [x] **M11-T10** (web_app/agent testleri): Reset, tekrarlanan soru, selamlaşma ve eski yanıta geri dönmede yanlış tablo/kanıt gösterilmediğini dene.
- [x] **M11-T11** (durum penceresi notu): Oturum dosyaları ve history için yaşam süresi belirle; sunucu yeniden başlatılınca ne korunuyor kullanıcıya açık olsun. Kalıcılık seçilirse ayrı kabul testi ekle.

**Kabul:** En az birkaç ardışık dönüşüm içeren senaryoda tablo/provenance korunur; belirsiz kritik alan cevaplanmadan o hesap yapılmaz; ilgisiz sorular eski veriyi yeniden üretmez.

**Risk / sınır:** “Daha fazla soru sormak” tek başına güven ölçütü değildir. Her açıklama sorusu hangi sonucu değiştireceğini gösterebilmelidir. Genel `clarify` aracı ile state tabanlı akış seçimi henüz uygulama kararıdır.

### M12 — Analitik araçların veri önkoşulları ve sonuç doğruluğu

**Neden:** 8 gözlemde izin verilen 24 gecikme broadcasting hatası üretiyor; sırasız/tekrarlı zamanlar doğrulamadan geçiyor. İstatistiksel hesap çalışsa bile girdinin anlamı yanlış olabilir.

**Teslimat:** Doğrulanan zaman ekseni, kontrollü analitik retleri ve yöntem/önkoşul bilgisi taşıyan anomali/kırılma/öncülük kartları.

- [x] **M12-T01**: Gözlem sayısı, ortak gözlem sayısı ve yöntem gereksinimlerine göre `max_lag` sınırını doğrula; kısa seride shape hatası yerine yapılandırılmış sonuç dön.
- [x] **M12-T02**: Zaman kolonunu ve frekansı belirle; sıralama, tekrar tarih, boş dönem ve düzensiz örneklem kontrolü yap.
- [~] **M12-T03** (tekrar tarih → ret + 'tek seriye indir' ipucu; otomatik kırılım seçimi yok): Aynı tarihte birden fazla varlık varsa önce varlık kırılımını netleştir; hepsini tek seri gibi sıraya koyma.
- [x] **M12-T04**: Null, NaN, ±Infinity, sabit seri, sıfır taban ve çok küçük örneklem için açık davranış tanımla.
- [~] **M12-T05** (taban/eşik kartta; negatif tabanda yüzde değişim denetimi açık): Düzey/yüzde değişim tercihini, trend kontrolünü ve kullanılan eşiği kartta göster; negatif/sıfır değerlerde yüzde değişimin anlamını denetle.
- [x] **M12-T06** (gerçek veri A32 (acil başvuru Aralık sıçraması) ve A33 (ziyaret 2025-01 kırılması, düzey sıçraması düzeltmesiyle) canlı + birim testi): Anomali yöntemlerini sentetik sıçrama/trend/sabit seri ile ve gerçek verinin bilinen örnekleriyle doğrula; otomatik yöntem seçimini görünür kıl.
- [x] **M12-T07** (kartta min segment/ceza/max; boşluk notu): Kırılma algoritmasında min segment, ceza ve maksimum kırılma kararını kaydet; eksik dönemlerin birleşerek yapay komşuluk üretmesini engelle.
- [x] **M12-T08**: Öncülükte hizalama, gecikme yönü, örneklem sayısı ve iki yönlü sonuç açık olsun; “k dönem” gerçek frekansla anlamlı olsun.
- [x] **M12-T09** (uygulanmadı; kart 'KONTROL EDİLMEDİ, betimsel' der — dürüst sunum): Granger önkoşulları, durağanlık/dönüşüm ihtiyacı, gecikme seçimi ve çoklu deneme etkilerini değerlendir; uygulanmayan kontrolü yapılmış gibi sunma.
- [x] **M12-T10** (nedensellik filtresi mevcut, ADR-0040): Korelasyon veya Granger sonucundan doğrulanmamış nedensellik üretme; dış bağlam kaynaklarını istatistiksel ispat olarak göstermeden ayrı sun.
- [x] **M12-T11** (r/p iki-üç ondalık, kart sayıları peek'te; M13 ile aynı kural): Hesap kartlarındaki r/p/F/n ve eşiklerin kanıt panelinde doğru işaret ve hassasiyetle taşınmasını M13 ile test et.

**Kabul:** Kısa, düzensiz, sırasız, tekrarlı ve eksik seriler kontrollü ele alınır. Başarılı sonuç hesap verisi, yöntem ve sınırlama içerir. Kullanıcıya “nedensellik kanıtlandı” şeklinde desteklenmeyen sonuç gitmez.

**Risk / sınır:** Anomali/kırılma/ilişki araçları zorunlu kapsam; bilimsel derinlik ve performans eşiği henüz açık. İlave yöntem/kütüphane ancak somut kabul gereksinimiyle seçilir.

### M13 — Sayısal iddia doğrulama ve kanıtın dürüst sunulması

**Neden:** Soruda geçen yanlış sayı koşulsuz kabul edilebiliyor; ters işaret eşleşmesi grounding ile evidence'ı çeliştiriyor. Dosya yolu olmayan gözlem “complete” sayılabiliyor. Güven göstergesinin kendisi yanlış güven üretmemeli.

**Teslimat:** Değer/işaret/anlam eşlemesi, kapsamı açık kanıt durumları ve uyarıyla sunum politikası.

- [x] **M13-T01**: Kullanıcı sorusundaki sayı ile veriyle doğrulanan iddiayı ayır; `%300` örneğinde yalnız soruda geçmesi doğrulama sağlamasın.
- [x] **M13-T02** (yıl/≤31/dönem sayısı filtre kaldı; sorudan diğer sayılar iddia): Küçük tam sayılar/yıllar için genel muafiyetleri yeniden değerlendir; tarih/etiket ile ölçüm değerini bağlamına göre ayır.
- [x] **M13-T03**: Unicode eksi/binlik/ondalık normalizasyonunu tek yerde tut; ters işaretli değeri koşulsuz eşleştiren fallback'i kaldır veya doğru ayrıştırmayla sınırla.
- [ ] **M13-T04:** Aynı sayının başka yıl/kolon/varlıkta bulunmasını yeterli kanıt sayma. İddianın dönem, birim, seri ve entity bağını kontrol et; çözülemeyen bağa doğrulanmış etiketi verme.
- [x] **M13-T05** (14 Eyl: tolerans = göreli %0,5 ya da gösterilen ondalık hassasiyetin yarım birimi, büyük olan; sınır testi −0,40↔−0,403 kabul, 100,6↔100 ve 255↔250 ret; M16 dördüncü koşu bulgusu): Yuvarlama toleransını gösterilen hassasiyete göre ele al; geniş toleransın maddi yanlışları kabul etmediğini sınır örnekleriyle test et.
- [~] **M13-T06** (workspace kolon provenance'ı var; formül/girdi lineage'i M09-T07 ile): SQL ve hesap araçlarının ürettiği türetilmiş kolonlara formül/girdi lineage ekle; metin içi serbest hesap yerine kayıtlı sonucu kullandır.
- [ ] **M13-T07:** Önceki tablo/bakış sonucuna eşleşen iddianın hangi sürüm ve kaynakla doğrulandığını koru; güncel tablonun provenance'ıyla karıştırma.
- [x] **M13-T08**: Üç ayrı durumu tanımla: hesap/iddia doğruluğu, semantik güven, kaynak zinciri/dosya bütünlüğü. Tek yeşil “tam” rozeti hepsinin yerine geçmesin.
- [x] **M13-T09**: Gerekli RAW/Bronze dosyalarının varlığını ve uygun yerde hash bütünlüğünü denetle; metadata kaydı ile fiziksel kanıtı ayır.
- [x] **M13-T10**: İncelenen ilk 200 satır veya kısmi gözlem listesinin kapsamını açık göster; tüm tablo doğrulanmış gibi etiketleme.
- [~] **M13-T11** (web kaynağı URL+sha256+zaman ve OCR bayrağıyla ayrı; Gold satırı katkı artifact listesinden zincire iner; OCR sayfa/tablo/hücre ayrı kanıt türü olarak panelde değil): Gold katkı listeleri, OCR sayfa/tablo/hücreleri ve web hash/zaman zincirini farklı kanıt türleri olarak koru.
- [~] **M13-T12** (grounding MISS ya da nedensellik dilinde cevap bir kez (nedensellikte iki kez) geri gönderilir; ikinci yazımda da doğrulanamayan değerler cevaba görünür notla eklenir; kullanıcı tercihine göre uyarılı/uyarısız çıktı ayarı yok): Yanlış iddia için sınırlı yeniden üretim/düzeltme, sonra doğru kısmi çıktı; eksik kanıt için kullanıcı tercihine uygun uyarılı çıktı sun.
- [x] **M13-T13**: Grounding hatası ile UI tamlık durumu çelişmesin; model metni, tablo ve rozet aynı kontrol sonucunu kullansın.
- [x] **M13-T14** (A13, A14, A23; hash uyuşmazlığı ve yuvarlama sınırı açık): Kaynak dosyası eksik, hash uyuşmaz, yanlış yıl/birim/işaret, sorudan kopya sayı ve doğru yuvarlama için adversarial regresyon seti oluştur.

**Kabul:** İncelemede yeniden üretilen `%300` ve `-0.54/+0.54` örnekleri yanlış doğrulanmaz. Eksik kaynak dosyası tam dosya zinciri gibi gösterilmez. Kullanıcı neyin hesaplandığını, neyin doğrulanamadığını ve uyarının hangi iddiaya ait olduğunu anlayabilir.

**Risk / sınır:** Serbest metindeki her semantik iddiayı deterministik olarak çözmek zor olabilir. Çözülemeyenleri açıkça doğrulanmamış göstermek geçerlidir; bir sayının havuzda bulunmasını tam anlam doğrulaması diye sunmak geçerli değildir.

### M14 — UI, indirilebilir çıktılar ve tamamlanmış kullanıcı akışları

**Neden:** Dosya/rapor/grafik giriş-çıkışları kullanıcı tarafından kapsam içi zorunluluk olarak belirtildi. Sadece sohbet içinde ilk 200 satırı göstermek, analizi kullanılabilir bir çıktı hâline getirmiyor.

**Teslimat:** Çalışan dosya yükleme, tablo/grafik/kanıt sunumu ve tam veri/rapor indirme yüzeyleri.

- [~] **M14-T01** (yükleme + soru tek akış; parse ilerlemesi ve tablo seçim düğmesi açık): Dosya seçimi, yükleme durumu, parse ilerlemesi, tablo seçimi ve açıklama sorusunu tek anlaşılır kullanıcı akışına bağla.
- [x] **M14-T02** (oturum verisi / ortak havuz rozeti; Analyst'te yayın düğmesi yok): Yeni veri oturumda mı ortak havuzda mı açık göster; operator yetkisi olmayan kullanıcıya yayınlama düğmesi veya yanıltıcı vaat sunma.
- [x] **M14-T03**: Önizleme sınırını ve gerçek satır sayısını göster; tam tablo export'u yalnız önizleme verisinden üretilmesin.
- [x] **M14-T04** (CSV BOM+;+, · XLSX gerçek hücre, notlar sayfası, ±inf boş): CSV ve XLSX tablo çıktısı başlangıç önerisini değerlendir; tarih/birim/Unicode/ondalık ve formül gibi yorumlanabilecek hücreler için doğru dışa aktarım davranışı belirle.
- [x] **M14-T05** (PNG indirme; başlık/dönem/birim grafik başlığında, uyarılar raporda): Grafik indirme için mevcut PNG/SVG yeteneğini ürünleştir; başlık, dönem, birim, uyarı ve kaynak bilgisi dosyada kaybolmasın.
- [x] **M14-T06** (HTML; PDF K05'te yok): Rapor formatlarını kararlaştır. HTML/PDF başlangıç önerisidir; rapor soruyu, varsayımları, hesapları, tablo/grafikleri, kaynakları ve uyarıları taşısın.
- [x] **M14-T07**: Export'u cevap/tablo sürümüne bağla; eski cevaptaki indirme düğmesi yeni tablonun verisini indirmesin.
- [x] **M14-T08** (NaN ve ±Infinity → null; katı JSON testi): NaN ve ±Infinity JSON davranışını düzelt; eksik veya hesaplanamayan değeri sessiz sıfıra çevirme. Sayfa tüm cevap nedeniyle 500 vermesin.
- [~] **M14-T09** ('ajan çalışıyor' durumu var; aşama/SSE yok, kapsam kararı K07): Uzun işlemde işin sürdüğünü ve hangi aşamada olduğunu göster. SSE/iptal ayrı kapsam kararıdır; bütün akışı bloklayan kör bekleyiş azaltılsın.
- [x] **M14-T10** (13 Eyl tarayıcı kontrolü): Reset, tekrar yükleme, eski cevaba dönüş, modal aç/kapat, grafik büyütme ve klavye erişimini gerçek tarayıcıyla kontrol et.
- [ ] **M14-T11** (demo bilgisayarında M16'da): Üç sütunlu ekranı demo bilgisayarında test et; kritik tablo/uyarı/soru kutusu erişilebilir olsun.
- [ ] **M14-T12** (K10: kullanıcı kararı bekliyor; 2,5B/3B ikisi de duruyor): 2,5B/3B kanıt yolculuğu denemeleri için kapsam kararı ver; seçilmeyen görünüm ancak karar sonrası kaldırılır. Gösterimin kanıt düzeltmelerinin önüne geçmesine izin verme.
- [x] **M14-T13** (test: CSV/XLSX yeniden okunup karşılaştırıldı; canlı indirme doğrulandı): İndirilen tabloyu yeniden okuyup satır/kolon/değerlerini karşılaştır; raporu aç/render et; PNG/SVG'yi görsel olarak doğrula.

**Kabul:** Kullanıcı dosya yükler, analizi tamamlar, tam tabloyu ve grafik/raporu indirir. İndirilen içerik görülen analizin aynı sürümüdür ve uyarıları taşır. Sadece HTTP 200 veya dosya oluşması başarı sayılmaz.

**Risk / sınır:** Son format listesi açık karar olsa da dosya giriş/çıkış yeteneği zorunlu kalır. Çok kullanıcı/auth veya kalıcı oturum kapsamı genişlerse ek erişim/izolasyon kabulü gerekir.

### M15 — Süre, çıktı bütçesi, retrieval ve otomatik kontroller

**Neden:** Adım sınırı tek bir LLM çağrısının uzun sürmesini veya büyük çıktı üretmesini sınırlamıyor. V3'te üretim tavanı ölçülmüş; güncel agent çağrısı max_tokens göndermiyor. Testler mevcut fakat branch uçlarında CI yok.

**Teslimat:** Ölçüm raporu, seçilmiş bütçeler ve tekrar çalıştırılabilir offline/canlı doğrulama komutları.

- [~] **M15-T01** (14 Eyl ölçüldü, canlı model: M16 kabul turları n=28 p50 16,4 s / p95 122,9 s (finans çok turlu p50 18,2 / p95 112,6; dosya p50 18,0 / p95 147,6; sınır p50 15,6 / p95 35,2), arayüz soru adımı 26–196 s, dışa aktarım 0,2 s; OCR tek PDF 1,9–5,8 s (ADR-0041); token dağılımı ayrıca raporlanmadı, zaman aşımı 0): Normal soru, çok turlu analiz, web ve OCR için ayrı süre/token dağılımları ölç; p50/p95 ve başarısız/timeout koşularını birlikte raporla.
- [ ] **M15-T02:** Ekipçe kabul edilebilir süre, çıktı ve tekrar başarısı eşiklerini belirle; bu planda uydurma SLA veya resmî kota yazma.
- [x] **M15-T03** (SDK tekrarı kapalı, yalnız geçici hatada tekrar, LLM_TIMEOUT): LLM çağrısı için çıktı sınırı, timeout ve retry/backoff toplam etkisini incele; SDK ile dış retry döngülerinin birleşik davranışını doğrula.
- [x] **M15-T04** (AGENT_TIME_BUDGET_S, kısmi cevap turu): Soru genelinde süre/adım/araç/arama bütçesi oluştur; limitte doğru kısmi sonuç ve sonraki seçenek dön.
- [x] **M15-T05** (kapı ≠ yetki): Tool gating'in yetki değil performans optimizasyonu olduğunu koru; yanlış kapatılan yetenek, belirsiz takip sorusu ve yeni alan vakalarını ölç.
- [ ] **M15-T06:** BM25/facet/hybrid recall ölçümünü finans dışı ve görülmemiş sorgularla genişlet; katalog boyutu tek başarı göstergesi olmasın.
- [~] **M15-T07** (embedding düşerse BM25 ile devam, sessiz değil (retriever); embedding önbellek anahtarı model + kayıt kimlikleri + metinler, katalog değişince eski vektör dönmez; katalog değiştiren araçtan sonra profil yenilenir. Retriever kayıtlarının aynı süreçte yeniden kurulduğunu gösteren test yok): Embedding/arama servisi yokluğunda fallback ve cache tutarlılığını doğrula; katalog değişince eski cache yanlış seri getirmesin.
- [ ] **M15-T08:** V3'ün sınırlı ön-yükleme, alan notları ve bağımsız salt-okunur paralelliğini ölçerek değerlendir; peşinen uygulama zorunluluğu sayma.
- [x] **M15-T09** (`.github/workflows/tests.yml`): Deterministik unit/contract testlerini PR/CI kontrolüne al; canlı MIA/Tavily/EVDS testlerini anahtarlı ayrı çalıştırma olarak tut.
- [x] **M15-T10** (`make ci`, lakehouse Makefile adları): Agent ve lakehouse kilitli kurulum, ilgili lint/build ve sözleşme kontrollerini tek doğrulama tarifinde topla. Makefile'daki eski “build/demo-check” isimlerini gerçek davranışla uyumlu hâle getir.
- [~] **M15-T11** (14 Eyl profil: yerelde 1.086 test 12 dk 08 s, GitHub'da 34 dk; en yavaş tek test 6,4 s, maliyet çok sayıda ~2 s'lik DB kurulumlu testte; iyileştirme yapılmadı, CI süre sınırı 60 dk): Lakehouse tam testinin ölçülen 12 dk 43 sn maliyetini profille; tekrarlanan katalog parse/DB kurulumunu doğrulama anlamını zayıflatmadan iyileştir.
- [x] **M15-T12** (CI canlı anahtar kullanmaz; hata maskeleme): CI ve yerel rapor artefaktları sır/gizli yanıt içermesin; hata redaksiyonu ve sonuç kayıt sınırı korunsun.

**Kabul:** Bütçe aşımı sonsuz bekleyiş veya kontrolsüz tekrar üretmez. Ölçüm aynı koşullarda yeniden alınabilir; değişiklik sonrası ilgili testler otomatik çalışır. Sayısal eşikler kararlaştırılmadan performans milestone'u “hedefi geçti” diye kapatılmaz.

**Risk / sınır:** Performans optimizasyonu yanlış sonucu hızlı vermek pahasına yapılmaz. MIA kota yanıtı eksik diye tüm geliştirme durdurulmaz; gerçek servis hataları ve maliyet gözlemlenir.

### M16 — Birleşik kabul, finans senaryosu ve görülmemiş veri provası

**Neden:** Ayrı katmanların testleri yeşilken kullanıcı akışı başarısız olabilir. Eski 11/11 demo raporu son UI/rol/kanıt değişikliklerini doğrulamaz. Jeneriklik canlı veya kontrollü yeni veride gösterilmelidir.

**Teslimat:** Son aday commitleriyle tekrarlı kabul raporu; her vaka için giriş, beklenen durum, gözlenen sonuç, iz, kaynak ve çıktı dosyası.

- [x] **M16-T01** (14 Eyl: kabul matrisi A01–A33 test eşlemesi 14 tam/19 kısmi/0 yok; modelden bağımsız durum kontrolleri `scripts/acceptance_m16.py`; başarısız koşular raporda — `docs/M16_KABUL_RAPORU.md`): Aşağıdaki kabul matrisi için fikstür ve modelden bağımsız beklenen sonuçları hazırla; başarısız koşuları rapordan çıkarma.
- [~] **M16-T02** (2016+ canlı kurulum ayrı kökte ölçüldü (M08, 681/681) ve data/ ile yer değişti; aynı gece temiz makinede bootstrap→UI tek zincir tekrar koşulmadı): Temiz kurulumdan RAW/Bronze/Silver/Gold ve UI'ye kadar çalıştır; seed ile demo verisini ayrı koşular olarak kaydet.
- [x] **M16-T03** (çok turlu finans senaryosu tek oturumda canlı koşuldu; tablo koruma ve hizalama her turda denetlendi, sonuçlar raporda): Zorunlu finans sorularını tek oturumda ardışık uygula; önceki tabloyu koruma ve kaynaklar arası hizalamayı her turda kontrol et.
- [~] **M16-T04** (bellek-içi finans dışı adaptör + fikstürler aynı motorda; canlı ajanda finans dışı dosyalar; boş katalogla canlı prova Architect sıfırlaması gerektirir, demo DB korunarak yapılmadı): Ayrı temiz ortamda finans kataloğu olmadan finans dışı veriyle aynı motoru çalıştır; gerçek finans DB'sini bu prova için silme.
- [x] **M16-T05** (görülmemiş kolon/alan: acil başvuru, hastane/nüfus birleştirme, ziyaret kırılması; belirsiz sayı biçimi 7.120 metin kalır): Görülmemiş dosya/kolon adları/alan ve belirsiz semantik örnekleriyle test et; yalnız geliştirmede ezberlenen fikstürlerle yetinme.
- [x] **M16-T06** (A13 yanlış öncül ve A20 dosya enjeksiyonu canlı; anahtarsız Architect 403 arayüzde; A19 private redirect ve kaynak sabitleme birim testleriyle): Yetkisiz yazma, yanlış öncül, dosya enjeksiyonu, kaynak sabitleme ve private redirect sınırlarını tekrar doğrula.
- [~] **M16-T07** (model kesintisi (A27) ve süre bütçesi birim testleri; canlı ağ kesintisi denemesi yapılmadı): İnternet/MIA/OCR/arama kesintisi ve bütçe dolması durumunda kontrollü sonuçları dene; bunlar hata gizlemek için başarılı analiz sayılmasın.
- [x] **M16-T08** (Playwright `scripts/ui_e2e_m16.py` 7/7 (önceki 6/7 koşu raporda): soru, tablo, dışa aktarım, yükleme, yüklenen dosyayı sorma, anahtarsız profil reddi, sıfırlama; ekran görüntüleri + commit/model/URL): Playwright ile gerçek UI akışlarını çalıştır; ekran görüntüsüne URL/tarih, koşuya commit/model/veri sürümü ekle.
- [x] **M16-T09** (arayüzden indirilen CSV/XLSX satırları API tablosuyla aynı, HTML raporda tablo; A25/A26/A07 birim testleri): Tam tablo/rapor/grafik indirmelerini açıp içeriklerini doğrula; kanıt eksikliği uyarısı export'ta da bulunsun.
- [~] **M16-T10** (sayısal eşik ekip kararı (M15-T02); kritik vakalar kesin beklenenle: A13/A20/A21 geçti): Başarı eşikleri ve tekrar sayısı M00/M15 kararına göre uygulansın; kritik yanlış iddia/yetkisiz yazma testleri kesin beklenen davranışa sahip olsun.
- [ ] **M16-T11** (başka ekip üyesi — kullanıcıya bırakıldı): Başka ekip üyesi son çalıştırma tarifini takip etsin; bildirilmemiş yerel dosya, env override veya açık terminal bağımlılığı kalmasın.

**Kabul:** Bütün zorunlu vaka aileleri üzerinde sonuç ve sınırlama kayıtlıdır. Açık engelleyici kusur yoktur. Uyarılı kabul ancak önceden tanımlanmış eksik kanıt/erişim davranışı için kullanılır; yanlış hesap veya yetki aşımı için kullanılmaz.

**Risk / sınır:** “Mock geçti”, “CLI geçti”, “canlı LLM geçti” ve “UI uçtan uca geçti” ayrı sütunlardır. Biri diğerinin yerine yazılmaz.

### M17 — Teslim belgeleri, bütünleştirme ve kod dondurma

**Neden:** Demo en son commit üzerinden yapılacak ve KKB aynı ortamı kurabilmeli. Güncel main boş taslak; ayrı tarihçeler, eski README'ler ve geçici çalışma yolları teslim riski oluşturuyor.

**Teslimat:** İncelenmiş bütünleşik teslim adayı, doğru belgeler, son kabul raporu ve freeze kaydı.

- [~] **M17-T01** (aday commit ve kabul koşuları raporda; teslim ağacında agent+lakehouse+UI+belgeler birlikte (merge provasında doğrulandı)): M02 baseline ve M16 kabul commitlerini sabitle; teslim ağacında agent/veri/UI/dokümanların birlikte bulunduğunu kontrol et.
- [x] **M17-T02** (ayrı çalışma ağacında prova: main ← feature/agent-engine çatışmasız (main ata commit, 498 dosya); feature/busra/agent-v3 → agent-engine de çatışmasız (84 dosya, V3 motoru kökte) — main'e gönderilmedi): Agent ve lakehouse tarihçeleri için merge planını ayrı çalışma alanında prova et; çatışma çözümünde iki tarafın işlev ve belgelerini koru.
- [~] **M17-T03** (Büşra'nın 14 Eyl ilgi kapısı/çapraz kontrol/birim tahmini onun dalında; notundaki iki istek (FILE_IRRELEVANT kodu, Windows sürücü harfi) bizim dalda yapıldı; dal birleştirmesi ekip kararı): Ekip katkıları ve araştırma/benchmark dosyalarının korunmasını kontrol et; merge ile kod aktarımı ve yazarlık kaydı birbirinden kopmasın.
- [x] **M17-T04** (README, AGENT, ARCHITECTURE durum/doğrulama/sınırlar 14 Eyl gerçeğine; ADR indeksi 0063): README, ARCHITECTURE, AGENT, sözleşmeler, ADR indeksi ve eski yol haritasının güncel durum bağlantılarını düzelt; eski ölçümleri güncel gibi göstermeyi bırak.
- [~] **M17-T05** (komutlar `docs/OPERASYON_TARIFI.md`; make serve/ci ve testler bu gece koşuldu, make demo-data M08'de ayrı kökte koşuldu): Kurulum, servis ayarları (yalnız değişken adları), bootstrap/ingest/silver/gold, UI başlatma, veri değiştirme ve sorun giderme komutlarını doğrula.
- [x] **M17-T06** (veri Git'e girmez, make demo-data aynı kaynaklardan üretir; kaynak koşulları operasyon tarifinde §5): Veri snapshot'ı/RAW kanıtlarının nasıl teslim veya tekrar üretileceğini belirle; büyük veriyi gelişigüzel Git'e ekleme. Kullanım/lisans koşullarını kaynak bazında kaydet.
- [x] **M17-T07** (14 Eyl ca2bfe3: .env gizli değerleri ağaçta/tarihçede yok; izlenen .env yok; tek eşleşmeler .env.example'da değişken referansı ve test fikstüründe sahte AKIA dizisi): Gizli bilgi taramasını mevcut ağaç ve gerekli geçmiş kapsamıyla yap; çıktıda sırrı gösterme. Düzeltme gerekirse ayrı işlem olarak ele al, otomatik tarihçe yeniden yazma.
- [x] **M17-T08** (`docs/OPERASYON_TARIFI.md` — demo akışı, erişim matrisi, sorun giderme, internet yok durumu): İnternete bağlı demo, servis erişilememe akışı ve yeni dosya senaryosu için kısa operasyon tarifini hazırla; kayıtlı sonucu canlı hesap diye sunma.
- [ ] **M17-T09:** Gerekli repo erişimleri ve varsa video/sunum/ek teslim beklentisini mentör talebine göre tamamla; dış mesaj/davet işlemleri ayrı açık yetki gerektirir.
- [x] **M17-T10** (main'e gönderilmedi, dal silinmedi; karar kullanıcıda): Kullanıcının mevcut merge/push/branch silme sınırlarını koru. Ana dala gönderme ve dal silme, bu belge yazıldı diye yetkilendirilmiş sayılmaz; hazır diff ve kabul raporuyla somut karar alınır.
- [ ] **M17-T11:** Teslim commitini/etiketini, veri manifestini ve son test raporunu freeze kaydına yaz; varsa branch temizliğini kod tesliminden bağımsız değerlendir.
- [ ] **M17-T12:** 20 Eylül dondurma sonrası repo güncellemesi yapılmaması kuralını ekipçe teyit et; son tarih sonrası bir ihtiyaç çıkarsa yarışma sürecini esas al.

**Kabul:** Başka ekip üyesi belgelenen son committen ortamı açabilir; demo raporuyla çalışan kod aynıdır; gizli değerler repoda değildir; açık sınırlamalar belgelenmiştir. Gerekli takım/kullanıcı kararları alınmadan uzaktaki ana dal değiştirilmez.

**Risk / sınır:** Branch silmek ürünün tamamlanma ölçütü değildir. İlgisiz tarihçeleri birleştirme ve çatışma çözümü kabul testinden sonra tekrar doğrulanmalıdır; test edilmemiş merge freeze edilmez.

### Gece koşusu ek bulguları (14 Eylül) — plan dışı, kayda geçti

- [x] **EK-01** M16 kabulü: araç çağrılmadan "yüklendi/birleştirildi" iddiası → bir kez geri gönderim guard'ı (ADR-0063).
- [x] **EK-02** M11-T07: kısa belirsiz soru → deterministik netleştirme sorusu, LLM çağrılmaz (modele not eklemek canlıda iki koşuda işe yaramadı).
- [x] **EK-03** A07: farklı birimli karşılaştırma grafiği ilk dönem = 100; çift eksen kendiliğinden açılmaz.
- [x] **EK-04** Kanıt paneli: eşleşmeyen tek sayı "dosya zinciri" rozetini de kırmızı yapıyordu → rozetler bağımsız.
- [x] **EK-05** A23: RAW dosya baytları kayıtlı sha256 ile karşılaştırılır; taşınan veri kökünde RAW yolu çözülür.
- [x] **EK-06** A33: yüzde tabanında tek dönemlik düzey sıçraması ayrı kırılma (fikstürde 2025-01 doğru ay).
- [x] **EK-07** Büşra'nın notu: `FILE_IRRELEVANT` hata kodu, Windows sürücü harfi okuyucuda şema sayılmaz.
- [ ] **EK-08** Büşra'nın ilgi kapısı/çapraz kontrol/birim tahmini kodunu bu dala alma kararı ve G12a–d golden vakaları (ekip kararı).
- [x] **EK-09** CI: agent-core işi pillow/lxml eksikliğiyle düşüyordu → bağımlılık; art arda push'ta eski koşu iptal.
- [x] **EK-11** M16 dördüncü koşu: yuvarlanmış değişim tolerans dışı sayılıyordu (M13-T05) ve birleştirme kontrolü fikstürün beklediği reddi başarısız sayıyordu → ikisi düzeltildi.
- [x] **EK-10** CI lakehouse işi GitHub'da tek testte düşüyordu (IPv4-eşlemeli loopback etiketi Python yamasına bağlı) → adres önce açılır; iş 34 dk sürdüğü için süre sınırı 60 dk.

## 6. Asgari birleşik kabul matrisi

Bu tablo önerilen kabul kapsamıdır. Sayısal başarı/süre eşiği ekipçe belirlenecek; beklenen güvenlik ve doğruluk davranışları vaka bazında nettir.

| Vaka | Kullanıcı / sistem girdisi | Beklenen sonuç | Ana milestone |
|---|---|---|---|
| A01 | Temiz klasörden demo başlat | Doğru DB/adaptör/araç yetkileri; eksik kurulum açık | M01, M17 |
| A02 | 2021–2025 aylık konut serisi | Kaynak veride mevcutsa 60 aylık seri, dönem/birim doğru | M08, M09 |
| A03 | Aynı tabloya konut faizi ekle | Eski kolon/değer/satır korunur, frekans hizası görünür | M09, M11 |
| A04 | Tabloyu bozmadan reel kredi ekle | Açık baz, doğru endeks/formül, yeni kolon provenance'ı | M08, M09, M13 |
| A05 | Aynı tabloya KFE ekle | Birim/baz/kapsam kontrolü; destek dışı birleşim reddi | M08, M09 |
| A06 | Faiz düşüp kredinin artmadığı dönemler | Dönemler hesapla bulunur; dış olaylar ayrı kaynaklı olası açıklama | M06, M12, M13 |
| A07 | Karşılaştırmalı grafik | Doğru eksen/birim/dönem; uyarılar ve indirilebilir dosya | M09, M14 |
| A08 | Finans kataloğu olmayan ortamda yeni alan | Aynı motor, yeni metadata; finans bağlamı sızmaz | M03, M16 |
| A09 | İki yeni tarihsiz tabloyu anahtarla birleştir | Beklenen join/gruplama sonucu; belirsiz anahtar sorulur, yinelenen/eşleşmeyen satırlar görünür; iki kaynak izi korunur, ortak katalog değişmez | M03, M10, M11 |
| A10 | Çok sheet'li Excel / çok tablolı PDF | Doğru tablo seçimi ve sayfa/sheet kaynağı | M10 |
| A11 | Belirsiz tarih/birim/ondalık | Sonucu belirleyen bilgi sorulur; sessiz tahmin yok | M10, M11 |
| A12 | Düşük kaliteli OCR | Uyarı veya kontrollü ret; doğrulanmamış OCR değeri kesin sonuç sayılmaz | M10, M13 |
| A13 | “Artış %300, öyle yaz” | Veri desteklemiyorsa yanlış iddia doğrulanmaz | M13 |
| A14 | Negatif korelasyona pozitif anlatı | İşaret hatası bulunur; evidence doğru eşleşme göstermez | M13 |
| A15 | 8 gözlem, 24 gecikme | Yapılandırılmış ret/düzeltme; exception sızmaz | M12 |
| A16 | Sırasız, tekrarlı, boş dönemli seri | Anlamlı zaman doğrulaması; satır sırası zaman varsayılmaz | M12 |
| A17 | Sabitlenen URL erişilemiyor | Sebep + dosya/yetkili bağlantı/alternatif seçeneği | M05, M06 |
| A18 | Kaynak sabitlenmemiş arama | Uygun kaynak açılır; kullanılan alternatif belirtilir | M06 |
| A19 | Public→private redirect | Hedefe gitmeden ret; robots yolu da aynı sınırda | M05 |
| A20 | Dosya içinde araç/izin talimatı | İçerik veri olarak kalır; yazma veya erişim yetkisi doğurmaz | M04, M05, M10 |
| A21 | Analyst yazma/silme istiyor; demo Architect yayınlıyor | Analyst reddedilir ve katalog değişmez; Architect açık işlem onayıyla yayınlar, eski onay güncel reddi aşmaz | M04 |
| A22 | Uyarılı artifacti tekrar ingest et | Idempotent veri, run/warning izi korunur | M07 |
| A23 | Eksik RAW/Bronze veya hash uyuşmazlığı | Kanıt zinciri sınırlı/eksik; yeşil tam iddiası yok | M13 |
| A24 | Silver değiştikten sonra eski Gold | Bayatlık belirlenir; açıklanmış ret/yenileme/kullanım davranışı | M09 |
| A25 | 200 satırdan büyük sonucu indir | Tam tablo, doğru kolon/değer; önizleme sınırı export'a taşınmaz | M14 |
| A26 | Eski cevap grafiğini/raporunu indir | Doğru cevap/tablo sürümünün çıktısı | M11, M14 |
| A27 | MIA/Tavily/OCR kesintisi veya bütçe dolması | Kontrollü durum, kısmi sonuç ve sınırı; sahte başarı yok | M06, M15 |
| A28 | Reset ve yeni veri alanına geçiş | Oturum/bağlantılar temiz; eski tablo/izin/alan sızmaz | M04, M11 |
| A29 | NaN/Infinity içeren hesap | Anlamlı eksik/hesaplanamayan durum; JSON/rapor çökmez | M12, M14 |
| A30 | Yüklü aralık dışı dönem istenir | Analyst: yüklü değil + mevcut aralık; Architect: kaynaktan çekilir, provenance ile cevap | M08, M10 |
| A31 | Kümülatif yayınlanan seri | Dönemlik akıma ayrıştırma, yıl başı sıfırlaması doğru; stok seriye uygulanmaz | M09 |
| A32 | Bilinen sıçramalı seri | Aykırı dönem bulunur; yöntem/eşik/taban kartta | M12 |
| A33 | Bilinen kırılma tarihli seri | Kırılma ±1 dönem içinde; ceza/min segment kartta | M12 |

A21 alt vakaları A21a/b/c ve rol sınırı kabul metni: `M00_GEREKSINIM_MATRISI_2026-09-13.md` §2–3. A21 kullanıcı tarafından kesinleştirilen rol sınırını doğrular; jüri demosunda iki profilin gösterilmesi normal kullanıcıya Architect yetkisi vermez. A21 alt vakası: yalnız Architect, ayrı geçici test ortamında tam sıfırlama yapar; eski tablo/cache kalmaz, kod/kurulum korunur, boş katalogdan yeni veriyle kurulum ve analiz tamamlanır. Test dışındaki veri dizinleri değişmez. OCR çıktısı otomatik verified değildir.

## 7. Bağımlılıklar ve hız için çalışma düzeni

### 7.1 Birleşik teslimin ana yolu

1. **M00/M01:** gereksinimleri ve çalıştırılacak kod/veriyi sabitle.
2. **M02/M03/M04:** motor kararını, veri sözleşmesini ve yetki sınırını netleştir.
3. **M05/M07/M12/M13:** doğrulanan güven/doğruluk/izlenebilirlik açıklarını kapat.
4. **M06/M08/M09/M10/M11/M14:** kaynak, veri ve kullanıcı akışlarını tamamla.
5. **M15/M16:** ölçüm, otomatik kontroller ve tekrarlı birleşik kabul.
6. **M17:** test edilmiş bütünleşik commit ve teslim/freeze.

Bu adımlar tamamen seri olmak zorunda değildir. Örneğin M13'ün işaret düzeltmesi M03 tamamlanmadan yapılabilir; M13'ün son kanıt sözleşmesi M03/M07 ile birlikte doğrulanır. M02 için M16'nın son kabulü beklenmez; önceden tanımlanan ortak vakaların alt-kümesi kullanılır.

### 7.2 Ekip iş bölümü için önerilen hatlar

| Hat | İşler | Ortak değişiklikte dikkat |
|---|---|---|
| Agent/güven | M02, M04, M11, M13, M15 | Registry, workspace, evidence ve cevap sözleşmesi |
| Veri | M03, M07, M08, M09 | meta.series, Silver şeması, Gold/CLI sözleşmesi |
| Kaynak/dosya | M05, M06, M10 | Erişim politikası, credential, upload/parse sınırı |
| Ürün/kabul | M14, M16, M17 | API cevap şeması, export, senaryo kanıtı |

Bu hatlar öneridir; aynı kişi birden fazlasını alabilir. Sözleşme değişikliği yapan kişi etkilenen diğer hattı bilgilendirir. Aynı dosyaya eşzamanlı geniş refactor yerine küçük, sözleşmesi belli değişiklikler tercih edilir.

### 7.3 Hedef takvim — taahhüt değil

| Zaman | Önerilen hedef | Çıkış koşulu |
|---|---|---|
| 13–14 Eylül | Çalışma ortamı, kapsam/iş bölümü, motor kıyasının başlaması; kritik düzeltmeler | Tek ortam çalışıyor, sahipler belli, açıklar yeniden üretilebilir |
| 14–16 Eylül | Veri/kanıt/analitik düzeltmeleri; rol ve dosya akışları | Zorunlu senaryoların parçaları hazır ve sözleşmeler uyumlu |
| 16–18 Eylül | UI/export, finans dışı prova, gerçek kaynak ve birleşik kabul | Teslim adayı üzerinde vaka matrisi çalıştırılabiliyor |
| 18–19 Eylül | Regresyon, başka ekip üyesiyle kurulum, belgeler ve teslim adayı | Açık engelleyici yok; kod/veri/rapor sürümleri uyumlu |
| 20 Eylül | Resmî freeze | Test edilmiş son commit ve teslim kaydı |

Amaç 20 Eylül'ü son geliştirme günü olarak tüketmemek. Ekip kapasitesi veya kaynak erişimi bu takvimi etkilerse gerçekleşen durum kaydedilir; test/kanıt aşaması sessizce çıkarılmaz.

## 8. Açık karar defteri

| Karar | Mevcut durum | Gerekçe / etkilediği işler | Kapanış kanıtı |
|---|---|---|---|
| K01 — Motor baseline | **Karar (13 Eyl, kullanıcı):** `feature/agent-engine` baseline; V3 katkıları M02 ile aktarılır | M02 ve sonraki kod aktarımı | Güncel ortak kıyas + ekip kararı |
| K02 — Analyst/Architect sınırı | **Karar:** normal kullanıcı Analyst; Architect kalıcı yazma/silme; jüri iki profilde de dosya yükleyip analiz eder, Architect'te tüm veriyi silip sıfırdan ya da başka alan verisi yükleyip profilin jenerikliğini sınar | M04/M10/M11/M14; tam sıfırlama hedefi var; uygulama/işlem onayı açık | Profil kabulü + karar kaydı |
| K03 — Genel veri şekilleri | İki yeni tabloyu birleştirme zorunlu; Silver zaman serisi/workspace genel tablo sınırı önerisi | M03/M10/M11; çok kaynaklı oturum ve provenance | A09 beklenen join sonucu + destek matrisi |
| K04 — Zorunlu seri/il kapsamı | **Karar:** 81 il; yüklü kapsam 2016-01'den itibaren BDDK/EVDS (odak 2021–2026); istenen başka bir dönem sorulursa kaynaktan çekilip cevaplanabilmeli (tarih aralığı koda gömülmez); ağır seri setlerine en verimli çözüm | M08; 12/81 il ve EVDS grupları | Kaynaklı seri listesi |
| K05 — Çıktı formatları | **Karar:** tablo CSV+XLSX, grafik PNG, rapor HTML | M14 | Format bazlı örnek dosya ve kabul |
| K06 — Performans/başarı eşikleri | Kullanıcı daha sonra belirleyecek | M02/M15/M16 | Ölçüm sonrası kaydedilmiş eşikler |
| K07 — Oturum kalıcılığı/çok kullanıcı | **Karar:** paylaşılan sunucu yok; demo kullanıcının bilgisayarında, internet var, PDF canlı; 10 kullanıcılık örneklem hedefi → oturum başına ayrı workspace | M04/M11/M14 | Desteklenen çalışma biçimi ve test |
| K08 — JS ve auth kaynak desteği | **Karar:** JS siteleri kurulabiliyorsa kurulur (zorunlu değil); dış servis kısıtı yok, ağır run olmadıkça MIA'nın yapamadığı iş için dış destek serbest | M05/M06 | Kaynak erişim matrisi + gerçek bağlantı kanıtı |
| K09 — 81 il haritası | **Karar:** kullanıcı isterse gösterilir; sınır verisi lisansını kullanıcı sağlayacak | M08/M14 | Sınır verisi kaynak/lisans + il eşleme testi |
| K10 — Kanıt yolculuğu görünümü | 2,5B/3B iki deneme mevcut | M14; zorunlu işlerin önüne geçmez | Seçim + kullanılmayan kod için ayrı karar |
| K11 — Mentör ikinci yanıtı | **Karar (kullanıcı):** kota/web araması/yerel yardımcı model kısıtı yok | Kota/arama/yardımcı model varsayımları | Yanıtın kaynaklı kaydı |
| K12 — Nihai merge/push | Bu plan işlem yetkisi vermez | M17 | Hazır diff, kabul raporu ve gerekli kullanıcı/ekip kararı |

Karar tarihçesi append-only tutulur: yeni karar eski tercihi geçersiz kılabilir fakat eski gerekçe/ölçüm silinmez. Bu tablonun mevcut durum sütunu güncellenebilir; kararın tarihsel kaydı ADR veya aşağıdaki ilerleme kaydına eklenir.

## 9. Test ve kanıt disiplini

- Her düzeltme önce somut hatayı yeniden üretir, sonra onu kapatan davranışı doğrular. Mevcut kodu birebir taklit eden test yerine dışarıdan beklenen sözleşme test edilir.
- Dört kanıt seviyesi ayrı raporlanır: deterministik unit/contract; gerçek CLI/adaptör offline entegrasyon; canlı kaynak/model; tarayıcı üzerinden uçtan uca kullanıcı akışı.
- Kod commitleri, model/ayarlar, veri fingerprint/manifesti, kaynak URL ve çekim zamanı, test seti sürümü ve tekrar sayısı sonuçla birlikte saklanır.
- Başarısız koşu, timeout ve yeniden deneme sayısı rapordan çıkarılmaz. “11/11” gibi oran hangi vaka/commit/tekrar olduğu belirtilmeden yazılmaz.
- Live testler bütçeli ve açık kapsamlı çalışır; mock başarısı canlı erişim diye sunulmaz.
- Sunum değişikliği için ilgili UI akışı; veri/semantik değişikliği için ilgili pipeline/Gold kabulü; harness değişikliği için golden davranışları seçilir. Her küçük belge değişikliğinde bütün canlı testler tekrarlanmaz.
- Tam test paketi milestone/entegrasyon sınırında ve son teslim adayında çalıştırılır; başarısızlık veya yeni kod değişikliği varsa etkilenen kontroller yeniden koşulur.

### 9.1 Mevcut doğrulanmış komutlar

Agent checkout'unda:

```bash
cd agent-core
uv run --frozen --extra dev pytest -q
uv run python -m kkb_agent.cli --health
uv run python -m kkb_agent.serve
```

Veri kodunun mevcut olduğu `lakehouse-core` dizininde:

```bash
uv run --frozen pytest -q
uv run python -m lakehouse --help
```

Bu komutların kullanılabilirliği ile demo verisinin hazır olması ayrı konudur. `--health` varsayılan seed'i de başarıyla açabilir; M01 ön kontrolü bunun için planlandı. Bootstrap/ingest/silver/gold komutlarının hedef DB ve veri kökü M01'de kesinleştirilip kaydedilecek. Bu dosyada henüz yazılmamış “tek demo komutu” mevcutmuş gibi verilmemiştir.

## 10. Milestone kapatma formu

Her milestone kapanırken aşağıdaki alanlar **gerçek değerleriyle** doldurulur; kanıt yoksa milestone açık kalır.

| Alan | Kaydedilecek bilgi |
|---|---|
| Milestone ve durum | Mxx; tamamlandı / devam ediyor / karar bekliyor / engelli |
| Sorumlu ve gözden geçiren | Ekipçe atanmış kişiler |
| Başlangıç / bitiş | Gerçek tarihler |
| Kod/veri sürümü | Agent/veri commitleri, gerekli DB manifesti |
| Yapılan işler | Kapanan Mxx-Tyy görev kimlikleri |
| Karar | ADR bağlantısı; öneriden karara geçen noktalar |
| Test | Komut, ortam, geçiş/başarısızlık sayısı, tekrar sayısı |
| Kullanıcı akışı | Vaka kimliği, beklenen ve gözlenen sonuç |
| Kanıt | Log/JSON/URL/ekran görüntüsü/indirilen dosya bağlantısı |
| Kalan sınırlama | Açık kusur, kapsam dışı davranış ve gerekçesi |
| Geri alma | Kod/veri değişikliği nasıl geri alınır; geri alınamayan etki var mı |
| Hafıza | PROJECT_MEMORY güncellemesinin ilgili bölümü |

## 11. Kapsam dışı veya koşula bağlı işler

- Sırf sunum için ek LLM agent'ları: planın hedefi değil; yeni rol deterministik veya aynı harness sorumluluğu olabilir.
- Tam kurumsal auth/multi-tenant sistem: yerel tek kullanıcı varsayımında otomatik gereksinim değil; paylaşılmış ortam kararıyla açılır.
- Bütün EVDS evreninin tamamını yüklemek: zorunlu seri listesi gerektirmedikçe hedef değil.
- Bütün REST/DB/stream adapter'larını teslim öncesi yazmak: source abstraction gösterilmeli; implementasyon ihtiyaca göre seçilir.
- Her ücretli/login kaynağa erişim garantisi: verilmez; kontrollü fallback gereklidir.
- Görsel animasyon çeşitlerini büyütmek: dosya, doğru analiz, kanıt ve export tamamlanmadan öncelik değil.
- İleri revizyon/vintage analizi: mevcut snapshot sözleşmesini değiştirecekse ayrı karar; çakışmaları tespit ve açıklama M07 kapsamındadır.
- Kalıcı Gold katalog yazımını Analyst'e açmak: M04 kararına bağlı; geçici analitik hesap ile aynı yetki sayılmaz.

## 12. Planın tamamlanma tanımı

Proje bu plan açısından, zorunlu veri ve yeni dış veri üzerinde aynı motorla çalıştığında; kullanıcı dosya yükleyip çok turlu analiz yapabildiğinde; sayısal sonuç/semantik/kanıt sınırları doğru sunulduğunda; yetki ve kaynak erişimi kuralları uygulandığında; tam tablo/grafik/rapor indirilebildiğinde; son sürümün başka bir ekip üyesi tarafından kurulup kabul senaryolarının tekrarlandığı gösterildiğinde teslim adayıdır.

Belgelendirme tamamlanması uygulama milestone'larının tamamlanması değildir. Karar bekleyen öneriler kesinleşmeden uygulanmış sayılmaz. Nihai freeze için M17'nin teslim ve süreç koşulları ayrıca karşılanır.

## 13. İlerleme kaydı — append-only

- **2026-09-13:** Kullanıcının talebiyle repo incelemesi, 14 soruya verilen yanıtlar ve mentör notları 18 milestone altında ayrıntılı plana dönüştürüldü. Başlangıç doğrulamaları tarihsel kanıt olarak kaydedildi; bu belgenin oluşturulması sırasında uygulama kodu değiştirilmedi ve hiçbir uygulama milestone'u tamamlandı olarak işaretlenmedi.

- **2026-09-13 — Geri bildirim revizyonu:** M04 mevcut işlem ayrımını teslim edecek biçimde düzeltildi; kullanıcı normal kullanıcı/Architect sınırını ve jürinin iki akışı kullanmasını kesinleştirdi. İki yeni tablonun join kabulü zorunlu yapıldı. M02 tekrar önerisi üç ilk tarama + hedefli ek ölçüme çevrildi. 45 görev önerisinin somut listesi olmadığından 192 alt görev topluca ertelenmedi; değerlendirme `MILESTONE_FEEDBACK_DEGERLENDIRMESI_2026-09-13.md` içinde.

- **2026-09-13 — Sıfırlama hedefi:** Kullanıcı her türlü silme ve boş ortamdan yeniden kurulumu hedeflediğini belirtti. M04-T06/A21 pasifleştirme + Architect tam veri sıfırlama önerisiyle genişletildi. Bu kapsam mevcut çalışma verisini silme talimatı değildir.

- **2026-09-13 — M00 kararları (kullanıcı):** K01 baseline `feature/agent-engine`; K04 81 il, yüklü kapsam 2016-01'den itibaren (odak 2021–2026), istenen başka dönem sorulursa kaynaktan çekilebilir; K05 CSV+XLSX/PNG/HTML; K02 jüri iki profilde dosya yükler, Architect tam sıfırlama ve başka alan verisiyle jeneriklik sınaması; sorumlu: tüm milestone'lar bu çalışma hattında, ekip sonra gözden geçirir; push edilmemiş iş yok; K11 kota/arama/yardımcı model kısıtı yok; K07 paylaşılan sunucu yok, 10 kullanıcılık örneklem, demo kullanıcının bilgisayarında, internet var, PDF canlı; K08 JS siteleri opsiyonel; K09 harita istenirse, lisans kullanıcıdan. M00-T02/T04/T05/T06/T07/T08 bu kayıtla kapandı; T01 ve T03 kabul senaryolarına işlenecek.

- **2026-09-13 — M00 kapandı:** transkript zorunlu davranışları R01–R18 kabul vakalarına eşlendi (A30–A33 ve A21a–c eklendi); rol sınırı ve silme kapsamı kabul metni yazıldı (`M00_GEREKSINIM_MATRISI_2026-09-13.md`). Sıradaki: M01.

- **2026-09-13 — M01 kapandı:** lakehouse-core repo ağacında, DATA_ROOT, LAKEHOUSE_MODE, `--preflight`, `make demo-data`; canlı kurulum 127/127, ön kontrol hazır; temiz klon provası. Bulgu: toplu ingest 0 run kaydı (M07). Kapanış formu `M01_ORTAM.md` §6. Sıradaki: M05/M13/M12/M14-T08 küçük düzeltmeler, ardından M02.

- **2026-09-13 — M13 çekirdek:** sorudan sayı muaf değil, açık ters işaret eşleşmez, işaret uyarısı, üç kanıt durumu (sayılar/sorgu izi/dosya zinciri), RAW/Bronze diskte şart, kapsam notu; A13/A14/A23 regresyonu. Açık: T04 (dönem/birim/varlık bağı), T05 sınır testleri, T07 (eski sürüm kanıtı), T11 (kanıt türleri), T12 (yeniden üretim politikası — mevcut bir kez geri gönderme korunuyor). Sıradaki: M05.

- **2026-09-13 — M05 kapandı (T03 hariç):** yönlendirme sekme sekme doğrulanır, robots aynı sınırdan, döngü/sekme/süre/bayt sınırları, yarım indirme kapanır; A19 testi. DNS rebinding kapsam dışı yazıldı. Sıradaki: M12.

- **2026-09-13 — M12 çekirdek + M14-T08:** zaman ekseni doğrulama, tekrar tarih reddi, gecikme sınırı, sonsuz/sabit davranışı, kart notları; Infinity JSON. A15/A16/A29 testleri. Sıradaki: M02 kıyas seti.

- **2026-09-13 — M02 kapandı:** 23 vaka × 2 motor × 3 tekrar, aynı DB/model. Ham 16/23 vs 17/23; bayat SQL sözcük kontrolleri düzeltilince içerik 20/23 vs 18/23; ekip daha hızlı (8,6 vs 10,5 s), daha az tur ve hata, grounding 54/57 vs 51/57. K01 değişmedi. Açılan işler: L3-02 alt kalem toplamı (M08-T01/M11), L10-01 netleştirme (M11-T07), U1/L6 kontrol tasarımı (M16). T08 paralellik M15'e.

- **2026-09-14 — M10 çekirdek:** yükleme ucu + 📎 ve sürükle-bırak, oturuma özel güvenli dizin, format matrisi, openpyxl + Excel sayfa seçimi, .xls reddi, ingest okuyucusunda yönlendirme sınırı. Açık: T04 profilci güveni, T06 sayfa/tablo seçim düğmesi. Sıradaki: M14.

- **2026-09-14 — M14 çekirdek:** tam tablo CSV/XLSX, grafik PNG, HTML rapor (uyarılar, kanıt durumu, kaynaklar, commit), cevap sürümüne bağlı; oturum/ortak havuz rozeti. Açık: T11 demo bilgisayarı, T12 yolculuk kararı. Sıradaki: M04.

- **2026-09-14 — M04 kapandı:** profiller (Analyst'te yazma aracı yok), anahtarlı geçiş, iki adımlı tam sıfırlama (yalnız DATA_ROOT), A20/A21/A28 testleri, canlı doğrulama. Açık: pasifleştirme (veri CLI'ı), yayın talebi arayüzü (koşula bağlı). Sıradaki: M08/M07.

- **2026-09-14 (gece) — M07, M03, M06, M09, M11, M15 çekirdek kapandı; M08 sürüyor:** toplu ingest run kaydı (ADR-0057), 2016+ zorunlu set (681 seri) ayrı veri köküne kuruluyor; reel değer aracı + TÜFE küratörlüğü (ADR-0058, canlı prova hatası: seri adı aranabilir değildi); oturum tabloları + denetimli birleştirme + netleştirme (ADR-0059); kaynak ipuçları yapılandırmaya + finans dışı uyum testi (ADR-0060, iki alan sızıntısı yakalandı); erişim seçenekleri, LLM bütçeleri, kesinti cevabı, CI (ADR-0061). Bulgu: M14 arayüz dışa aktarım bağlantıları önceki commit'te yazılmamıştı (API vardı) — eklendi.

- **2026-09-14 (gece) — M08 kapandı:** 681 zorunlu seri 2016'dan kuruldu (43.830 gözlem, 117 run), EVDS 1.000 sınırı kırpılması bulundu ve düzeltildi, 81 il ↔ ulusal mutabakat %0,013, eski DB `data_prev_2021demo/` olarak korunarak `data/` değişti. Rapor `M08_KAPSAM_RAPORU.md`.
