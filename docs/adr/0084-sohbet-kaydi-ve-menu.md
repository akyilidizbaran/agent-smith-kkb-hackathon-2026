# ADR-0084: Sohbet kaydı — her sohbet ayrı ve kaldığı yerden; solda sohbet listesi ve yeni sohbet

**Durum:** Kabul edildi · **Tarih:** 2026-09-16 · **İlgili:** ADR-0056/0069 (tam sıfırlama), M10-T12 (oturum dosyaları), ADR-0079 (arayüz akışı)

## Bağlam
Oturum yalnız bellekteydi. Sunucu yeniden başlayınca sohbet, tablolar ve yüklenen dosyalar kayboluyordu. Tek bir sohbet
vardı; "Oturumu sıfırla" hepsini siliyordu.

Kullanıcı istekleri (15–16 Eylül):
- her sohbet kendi konuşmasıyla ayrı dursun;
- "Yeni sohbet" düğmesi olsun;
- uygulama kapatılıp açılınca kaldığı yerden devam etsin;
- sohbetler önce hamburger menü olarak istendi; ilk sürümü görünce kullanıcı sol panelde sürekli görünen, en son kullanılanın
  en üstte olduğu listeye karar verdi (16 Eylül);
- açık sohbetin mesajlarına menüden gidilebilsin.

Kullanıcının verdiği kararlar:
- tam veri sıfırlamasında eski sohbetler kalır, üstünde uyarı çıkar;
- yüklenen dosyalar sohbetle saklanır, sohbet sıfırlanınca ya da silinince silinir.

## Karar
1. **Kayıt yeri:** `ConversationStore` (`kkb_agent/conversations.py`), `DATA_ROOT/conversations/<12 onaltılık>/` altında üç dosya:
   - `meta.json`: başlık, zaman, soru sayısı, profil, veri dönemi, yüklemeler;
   - `answers.json`: arayüzün çizdiği tam cevap yükleri;
   - `state.pkl`: analiz çalışma alanı, konuşma hafızası, web adres izinleri, dışa aktarım tabloları.

   Yazma atomiktir (geçici dosya + yeniden adlandırma) ve `meta.json` en son yazılır; yarım kayıt listelenmez.
2. **Ne zaman yazılır:** her cevaptan sonra, sohbet değiştirilirken, profil geçişinde ve tam sıfırlamadan önce.
   - Hiç soru sorulmamış sohbet kaydedilmez; o sohbette yüklenmiş dosyalar geçişte silinir.
   - Başlık ilk sorudan alınır ("Dosya:" satırları hariç); model çağrısı yapılmaz.
3. **Hız:** kayıt, model turlarının yanında milisaniyelik bir iştir. Modele giden geçmiş zaten son 8 mesajla sınırlı
   (`core/agent.py`); açılan sohbet aynı bağlamla sürer.
4. **Geri yükleme yerinde yapılır:** araçlar çalışma alanının aynı nesnesini tutar (`cli.build_agent`).
   - Sohbet açılırken ya da yeni sohbete geçerken ajan yeniden kurulmaz.
   - Çalışma alanının içi sıfırlanıp kayıttan doldurulur; konuşma hafızası listesi yerinde değişir.
   - Son tur alanları (bağlam, kapı, ön kontrol) temizlenir.
   - Çok turlu takip bağlamı (`_follow_up_context`, PR #7) sohbete aittir: kayda girer, yeni sohbette boşalır, açılan
     sohbette geri gelir. Böylece bir sohbetin ölçü, dönem ya da coğrafya ipucu başka sohbete taşınmaz.
5. **Açılışta** kullanıcının en son açık tuttuğu sohbet açılır (`active.json`; soru sormadan geçilen sohbet de sayılır).
   Bu kayıt yoksa en son kaydedilen sohbet açılır.
6. **Silme ve sıfırlama:**
   - "Oturumu sıfırla" açık sohbeti ve yüklemelerini onay penceresiyle siler, yeni boş sohbet açar.
   - Menüden silme satır içinde onay ister; sohbetin yüklemeleri de silinir.
   - Profil geçişi yeni sohbet açar.
7. **Tam veri sıfırlama:** `conversations/` sıfırlama hedeflerinden biri değildir (`ResetPaths.candidates`).
   - Sıfırlama `epoch.json` sayacını artırır.
   - Önceki dönemin sohbetleri menüde "sıfırlamadan önce" diye işaretlenir; açılınca konuşmanın üstünde uyarı notu çıkar.
   - Yüklemeler ve grafik dosyaları sıfırlamayla silindiği için o sohbetlerde bu bağlantılar çalışmayabilir.
8. **Arayüz:**
   - Sohbet listesi sol panelde, veri havuzu kartlarının altında, sürekli görünür; hamburger menü yok.
   - Sıra son kullanımdır: soru sormak da, sohbete geçmek de o sohbeti en üste taşır (`used_ns`, `saved_ns`).
   - Liste tarihe göre gruplu: Bugün, Dün, Son 7 gün, ay. En üstte "Yeni sohbet" düğmesi var; orta genişlikte (≤1100 px) önce sağdaki kanıt
     paneli gizlenir, liste solda kalır; sol panelin de gizlendiği çok dar ekranda (≤760 px) bu düğme başlığa çıkar.
   - Açık sohbetin soruları sohbetin altında listelenir; soruya basınca cevaba kaydırır. Eski "Bu oturum" listesinin yerini aldı.
   - Cevap sürerken sohbet değiştirilemez.
9. **API:** GET ve POST `/api/conversations`, POST `/api/conversations/{id}/open`, DELETE `/api/conversations/{id}`.
   Kimlik `^[0-9a-f]{12}$` biçimine uymazsa 404 döner. `create_app(conversations=None)` bellek kipidir (testler, betikli koşucular).
10. **Güvenlik notu:** `state.pkl` yalnız bu sunucunun yazdığı, sunucunun ürettiği kimlikli dizinden okunur. Kullanıcı yüklemesi
    hiçbir zaman pickle ile açılmaz. Veri kökü git dışındadır.
11. **Kanıt yolculuğu (ADR-0083 eki):** sayı çipleri kaldırıldı. Yolculuk bütün cevabın zincirini gösterir.

## Sonuçlar
- Tek sunucu, tek açık sohbet (yerel demo). İki tarayıcı penceresinden aynı anda farklı sohbet yürütmek desteklenmez.
- Kod güncellenip çalışma alanı sınıfı değişirse eski `state.pkl` okunamayabilir. Bu durumda sohbet metni ve kanıtlar açılır,
  çalışma alanı boş başlar ve log'a uyarı yazılır.
- Testler: `tests/test_sohbet_kaydi.py`.
