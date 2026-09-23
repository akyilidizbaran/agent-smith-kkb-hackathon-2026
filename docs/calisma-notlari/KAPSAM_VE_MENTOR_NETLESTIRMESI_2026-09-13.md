# Kapsam ve mentör netleştirmesi — 13 Eylül 2026

## Kaynaklar ve kanıt sınırı

- Kullanıcının repo incelemesindeki 14 soruya bu konuşmada verdiği cevaplar.
- [Kullanıcının paylaştığı mentör soru/cevapları](mentor/2026-09-13-kullanici-paylasimi.txt): ilk dört konuya tam yanıt var. Dosya ikinci soru grubunun “2. soru cevabı” başlığında bitiyor; o yanıt ekli değil.
- [Kick-off transkripti](KKB_Hackathon_2026_Kick_Off_Tam_Transkript.md): otomatik transkripsiyon, konuşmacı ayrımı yok. Kritik ifadeler için dosyanın kendi notu gereği video zaman damgası esas alınabilir; bu tur video incelenmedi.
- Önceki [ADR-0021](../adr/0021-mia-search-retrieval-ayristirma.md) kota/arama/yardımcı modellere ilişkin mentör yanıtının özetini içeriyor. Bu, yeni ekte ikinci yanıtın bulunduğu anlamına gelmez. Transkript 32:19 başlangıç limitlerinden söz eder; güncel sayısal kota bu yeni kaynaklardan kesinleştirilemez.

## Kullanıcının kesinleştirdiği kapsam

- Dondurma 20 Eylül 2026; hedef mümkün olan en erken tarihte tamamlamak.
- Ürün, dış/yeni veri karşısında analiz üreten **jenerik veri analiz agent'ı**. Konut/krediye bağlı bir ürün değil; BDDK/EVDS başlangıç ve zorunlu değerlendirme verisi.
- Jeneriklik lakehouse ve agent için birlikte geçerli. Architect ekip tarafından eklenmiş bir kapsam; özel bir Architect ekranı yarışma şartı olarak ileri sürülmeyecek.
- Motor seçimi henüz kesinleşmedi. Ekip 14 Eylül'de birbirinin çalışmalarını değerlendirecek, güçlü parçaları aktarabilecek ve baseline/iş bölümünü yeniden belirleyecek. Mevcut motoru peşinen üstün ilan etme.
- `feature/lakehouse-catalog-breadth`, bu çalışma hattının veri tabanı olarak korunabilir; takımın son ortak kabulü olarak sunulmayacak.
- Şimdilik ekip bilgisayarında demo varsayımı. Transkript 24:47–24:56 bunu destekliyor; 24:11 başka ortamda tekrar kurulabilme beklentisini de içeriyor.
- BDDK haftalık/aylık/FinTürk ve EVDS; transkript 09:48'de 2021-01 → 2026-06 aralığı. Hangi EVDS gruplarının ne kadar geniş kapsanacağı ayrıca çıkarılmalı; bütün EVDS serileri zorunlu diye varsayılmayacak.
- Kullanıcıya sonuç uyarıyla gösterilebilir. Bu tercih yanlış olduğu saptanan bir sayıya “doğrulandı” demeyi meşrulaştırmaz; yanlış hesap ile eksik kanıt ayrı ele alınmalı.
- Hesabı/sonucu belirleyen eksik bilgiler sorulmalı; diğer varsayımlar açıkça belirtilerek ilerlenebilir. “Kesin rasyonel çıktı” ifadesinin çalışma yorumu budur.
- Tavily mevcut arama sağlayıcısı. İnternet erişimi var; kaynaklara erişilememe nedeni kullanıcıya söylenmeli. Ekip proje e-postasıyla önceden yetkili hesap hazırlayabilir.
- PDF/Excel/dosya yükleme ve tablo/grafik/rapor dışa aktarımı kapsam içinde gerekli; isteğe bağlı süs olarak ertelenmeyecek. Ayrıntılı formatlar henüz seçilmedi.
- Sayısal performans, bütçe ve tekrarlı başarı eşikleri henüz belirlenmedi.

## Mentörün açık yönlendirmeleri

- Agent kendi kendine hesap açmaz, CAPTCHA veya güvenlik engeli aşmaz.
- Kullanım hakkı olan önceden hazırlanmış hesap/API anahtarı kullanılabilir; gizli değerler secret/env/vault katmanında kalır.
- Erişim yoksa sebep + yetkili bağlantı/dosya yükleme/alternatif kaynak seçenekleri. Hesap hazırlığına rağmen erişilemeyen kaynak senaryosu çalışmalı.
- Kullanıcı kaynak sabitlememişse açıkça belirtilen alternatif kullanılabilir; kaynak sabitlenmişse değişiklik kullanıcıya sunulur. Kullanılmayan sayfalar sade cevapta değil trace/evidence panelinde.
- Crawl: ilgi ve bütçeye göre, aynı alan adı, robots uyumu, sayfa/süre/derinlik üst sınırları. Her linke gitmek yerine ilgili veri/API/belge bağlantılarına öncelik.
- Tek orchestration agent + deterministik seçim/erişim/parse/normalize/doğrulama/provenance/politika katmanları uygundur. Roller ayrı LLM agent gerektirmez.
- Yeni REST API/DB/stream/auth türünde source adapter/capability eklenebilmeli; ana orchestration/validation yeniden yazılmamalı. Bu, tüm kaynak türlerinin bugün uygulanmış olduğu iddiası değildir.

## Öneri — Analyst/Architect sınırı, henüz uygulanmadı ve kesin karar değil

Kullanıcı Architect'e erişmemeyi önerdi ve görüş istedi. Önerilen tasarım:

| İşlem | Son kullanıcı / Analyst | Ekip / Architect |
|---|---|---|
| Veriyi sorgula, birleştir, analiz et, görselleştir | Evet | Evet |
| Dosya/URL ver, sohbet için geçici veri hazırla | Evet | Evet |
| Tablo, grafik, rapor indir | Evet | Evet |
| Ortak kataloğa seri yayınla, semantik metadata değiştir | Hayır; talep oluşturabilir | İnceleyerek yayınlar |
| Ortak Silver/Gold yeniden kur, kalıcı kaynak/credential tanımla | Hayır | Evet |

- Geçici dosya saklamak ile ortak analitik veri havuzuna yayınlamak ayrılmalı. Session verisi kullanıcının analizi için izole tutulabilir; kalıcı katalog değişikliği gerektirmez.
- Aynı kod/harness ve farklı registry/yazıcı erişimi yeterli. Son kullanıcı registry'sine kalıcı yazma/terfi araçları eklenmez; model “onaylıyorum” metniyle yönetici yetkisi kazanmaz.
- Mevcut `tool_gate` yalnız sunulan şemayı daraltır, yetkilendirme değildir. Sadece Architect düğmesini gizlemek bu sınırı sağlamaz.
- Yerel demo için ayrı operator CLI veya ayrı başlatma profili yeterli olabilir; kimlik sistemi şart diye varsayılmamalı. Paylaşılan sunucuya geçişte sunucu tarafında kimlik/oturum/yetki sınırı gerekir.
- Mevcut sohbetten `promote_draft` davranışı bu öneri kabul edilirse değişecek; ADR-0039/0044 ve yol haritasındaki eski ifadeler o uygulama sırasında güncellenmeli.

## Öncelik önerisi — takım kararı değil

1. Agent + catalog-breadth sabit commitleriyle tek tekrar kurulabilir yerel çalışma; başlangıç doğrulaması.
2. İncelemede bulunan yanlış iddia/işaret/redirect/gecikme/provenance açıkları; eksik kanıt ile yanlış sonuç için ayrı uyarı.
3. Jeneriklik kabulü: finans kataloğunu çıkartıp temiz bir ortamda finans dışı veriyle aynı motoru çalıştır; eski alias/prompt/SQL varsayımlarının sızmadığını ölç. Katalogsuz dosya analizi ve belirsiz semantik vakaları da dahil.
4. Aynı oturumda harici dosya + mevcut tabloyu bozmadan ek kolon/join; yerel dosya yükleme ve tam çıktı indirme.
5. Transkriptteki gerçek çok turlu senaryo: 60 aylık konut → faiz → reel değer → KFE → dış bağlam → karşılaştırmalı grafik. Jenerik motorun zorunlu finans örneği olarak test et; finans davranışını motor koduna gömme.
6. 14 Eylül motor kıyası: aynı MIA, aynı veritabanı, aynı görülmemiş sorular/tekrarlar; doğruluk, uyarı ve provenance, jeneriklik, süre, token ölç. Test adetlerini motor kalitesi sıralaması olarak kullanma.

## Hâlâ açık noktalar

- Analyst/Architect önerisinin kabulü ve operator akışı.
- Genel veri modelinin kapsamı: mevcut seri/tarih/değer odaklı Silver'ın yanında işlem tablosu, çok varlıklı ilişkisel veri veya belge analizinin hangi sınırlarla destekleneceği.
- Zorunlu BDDK/EVDS seri/kırılım listesi; KFE ve reel dönüşüm için endeks bazlarının doğrulanması.
- Takımın motor/iş bölümü kararı; performans eşikleri; çıktı formatlarının ayrıntıları.
- Mentör paylaşımındaki ikinci soru grubunun eksik yanıtı (özellikle kota ve yerel yardımcı model koşulları); önceki ADR özetinden ayrı tutulmalı.
