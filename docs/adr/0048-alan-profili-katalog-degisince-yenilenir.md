# ADR-0048: Alan profili katalog değişince yenilenir; arayüzde her tıklanan yer bir uca gider

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Sıradaki:** E kapanış

## Bağlam
Kullanıcı sordu: Architect ile lakehouse boşaltılıp başka veri çekilince alan profili
kendiliğinden şekilleniyor mu? Ölçülen durum: katalog tarafı dinamikti (adaptör ingest/terfi
sonrası `reload()` ile `meta.series`'i yeniden okuyor, araçlar yeni seriyi hemen görüyor) ama
profil (sistem promptundaki `{domain}`, araç açıklamalarındaki örnek kolonlar) ajan kurulurken
bir kez türetiliyor, oturum içinde değişmiyordu; ancak sunucu yeniden açılınca ya da "Oturumu
sıfırla" ile yenileniyordu. Ayrıca arayüzde oturum listesi, veri havuzu kartları, üst rozetler
ve grafik tıklanınca hiçbir şey olmuyordu; kanıt yolculuğu penceresi X ile kapanmıyordu.

## Karar
1. **Profil fabrikası.** `AnalyticsAgent(profile_factory=…)`; CLI fabrikayı
   `DomainProfile.from_catalog(lakehouse.list_datasets(), DOMAIN_DESCRIPTION, DOMAIN_AUDIENCE)`
   olarak verir. Katalog değiştiren bir araç (`ingest_from_url`, `promote_draft`) başarıyla
   çalışınca `refresh_profile()`: profil yeniden türetilir, sistem promptu ve kayıt defterinin
   profili (araç şemaları çağrı anında render edilir) güncellenir; o turun sistem mesajının ilk
   satırı da değişir. Profil yine LLM'den değil katalogdan gelir (ADR-0012); fabrika yoksa
   davranış eskisi gibi. Sonuç: lakehouse boşaltılıp hastane verisi yüklenirse bir sonraki
   soruda "Sen kimsin?" ve örnekler yeni veriye göre.
2. **Arayüz: tıklanan her yer bir uca gider.** Oturum listesi → o cevaba kaydırır, izi ve
   kanıtı ona çevirir; veri havuzu kartları ve üst rozetler → "Sistem durumu" penceresi
   (`GET /api/status`: model, araçlar, kademe, kapı, bütçe, uç noktalar); grafik → büyük
   görünüm; cevap yüklerinin tamamı sunucuda tutulur (`GET /api/answers`, `/api/answers/{i}`),
   sayfa yenilenince sohbet geri gelir. Pencereler X, arka plan ve Esc ile kapanır
   (`.modal[hidden]{display:none}`: `display:flex` `hidden`'ı eziyordu).
3. **Kanıt yolculuğu sonraya.** Düğme kalır, öncelik genel mimari (ADR-0047 "deneme").

## Sonuçlar
- Uç nokta denetimi (curl): `/`, `/api/status`, `/api/answers`, `/api/answers/{i}`, `/static/…`
  200; boş soru 422; olmayan cevap 404; `/api/reset` sonrası liste boş.
- Sınır: profil yenilemesi araç şemasının ortasında değil, bir sonraki turda devreye girer.
