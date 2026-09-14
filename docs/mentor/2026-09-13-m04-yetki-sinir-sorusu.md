# Mentöre soru taslağı — Analyst/Architect yetki sınırı (M04)

**Durum:** taslak, gönderilmedi. Kullanıcı gönderir. Cevap `docs/mentor/` altına kaynaklı kaydedilir.

---

Merhabalar Mehmet Bey,

Bir önceki cevabınızdaki "source abstraction + access policy + provenance + fallback sözleşmesini temiz tutun" yönlendirmesini uyguluyoruz. Şimdi bunun yanına giren bir yetki sınırı kararında görüşünüzü almak istiyoruz.

**Bugünkü yapı.** Tek orchestration agent'ın iki mantıksal rolü var:
- **Analyst:** ortak veri havuzunu (lakehouse) yalnız okur; sorgular, tablo kurar, kolon ekler, grafik çizer, dosya/URL'den gelen veriyi analiz eder. Bağlantısı salt-okunur.
- **Architect:** yeni bir dosya/URL'i ortak kataloğa alma yolu. Yazma agent sürecinde değil, ayrı bir süreçte çalışan veri ekibinin komut satırı aracıyla yapılıyor; o da yalnız `adhoc` şemasına ve "taslak" durumuna yazabiliyor. Taslak, kullanıcı sohbette açıkça "kataloğa al" derse ve birim/ölçüm türü gibi belirsizlikler kullanıcı beyanıyla kapanmışsa Silver'a alınıyor. Onay, modelin ürettiği metne değil kullanıcının kendi metnindeki niyete bağlı; insan onayı veriyi "doğrulanmış" değil "türetilmiş" bırakıyor. Kimlik sistemi yok; demo tek bilgisayarda.

**Değerlendirdiğimiz model.** Son kullanıcının ortak kataloğu ve veri havuzunu istemeden değiştirmemesi için:

| İşlem | Son kullanıcı (Analyst) | Ekip (Architect/operator) |
|---|---|---|
| Sorgula, birleştir, analiz et, görselleştir | Evet | Evet |
| Dosya/URL ver, sohbet için geçici veri hazırla | Evet (oturuma özel alan) | Evet |
| Tablo, grafik, rapor indir | Evet | Evet |
| Ortak kataloğa seri yayınla, semantik metadata değiştir | Hayır; yayın talebi oluşturur | İnceleyip yayınlar |
| Ortak Silver/Gold'u yeniden kur, kalıcı kaynak/credential tanımla | Hayır | Evet |

Bunun gerektirdikleri: son kullanıcı kayıt defterinde kalıcı yazma araçlarının hiç bulunmaması (arayüzde gizlemek değil), oturuma özel geçici veri alanı, "yayın talebi → ekip incelemesi → aktif yayın → geri alma" akışı ve paylaşılan sunucuya geçilirse sunucu tarafında kimlik/oturum/yetki sınırı.

**Sorularımız:**

1. **Sınırın yeri.** Son kullanıcının ortak kataloğa yayın yapamaması, yalnız talep açabilmesi sizce doğru varsayılan mı? Yoksa demoda jürinin verdiği dosyanın aynı sohbette kataloğa girip sorgulanabilir olması mı bekleniyor?
2. **Yayın talebi akışı.** Taslak → inceleme → aktif → geri alma akışı bir hackathon teslimi için değer mi katar, yoksa "insan onaylı taslak" bugünkü hâliyle yeterli mi? Değer katıyorsa asgari hâli nedir?
3. **Kimlik ve yetki sistemi.** Tek bilgisayar demosunda ayrı bir operator başlatma profili (yazma araçları kayıt defterine hiç girmez) yeterli sayılır mı? Yoksa kullanıcı/rol/oturum bazlı gerçek bir yetkilendirme (kimlik doğrulama, oturum izolasyonu, çok kullanıcı) bekleniyor mu? Bunun değerlendirmede bir karşılığı var mı?
4. **Onayın anlamı.** İnsan onayı veriyi "doğrulanmış" yapmalı mı? Biz onaylı veriyi "türetilmiş" tutuyoruz; Gold hesaplarında kullanımı ayrıca kullanıcı rızası istiyor. Bu ayrım sizce doğru mu, fazla mı?
5. **Enjeksiyon ve metin yetkisi.** Dosya veya web içeriğindeki talimatları veri sayıyoruz; yazma niyeti yalnız kullanıcının kendi mesajından çıkarılıyor. Bunun ötesinde beklediğiniz bir kontrol var mı?
6. **Demo günü.** Jüri dosyayı canlı verecekse hangi rolde olacak: veriyi analiz eden son kullanıcı mı, kataloğu genişleten ekip üyesi mi? Cevap, arayüzde hangi düğmelerin görüneceğini belirliyor.

Bu kararı 14 Eylül'de ekipçe kapatmayı planlıyoruz; görüşünüz ona yön verecek. Uygun olursanız mimariyi kısa bir toplantıda göstermek isteriz.

Teşekkürler.
