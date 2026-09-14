# ADR-0078 — Kullanıcı geri bildirimi: genel bilgiden cevap yok, yetenek soruları, resmi kaynaklar, XML, belge metni, arayüz

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** kullanıcının ürün denemesinden geri bildirim (14 Eylül öğleden sonra)

## Bağlam

Kullanıcı arayüzde ürünü denedi ve dokuz sorun bildirdi:

1. "Elif Sena Önsöz kimdir?" sorusunda model veri havuzunda kayıt olmadığını söyleyip "genel bilgimden" diyerek başka birine ait
   uydurma bir biyografi yazdı (kişi bir ekip üyesi).
2. PDF okuması "metin yalnızca ilk 1500 karakteriyle döndürüldü" diye yarıda kaldı.
3. "2015 dolar kuru", "1 Temmuz 2026 dolar kuru, git araştır bul getir": model internetten kendisi araştırmadı; TCMB kur sayfasının
   adresini açmak için kullanıcıdan adres/onay istedi. Niyet kapısı (ADR-0037) modelin kurduğu her adresi reddediyordu.
4. Kullanıcının verdiği `https://www.tcmb.gov.tr/kurlar/201501/02012015.xml` açıldı ama "tablo yok" denildi: XML metin sayılıyordu.
5. "İnternetten araştırma yapabiliyor musun" sorusuna "Anladım, not aldım. Ama elimde veri sorusu yok" cevabı; sürekli özür ve dolgu.
6. Sağ panelde "Cevaptaki sayılar" listesi istenmiyor; kanıt zinciri yeterli.
7. Mesaj gönderilince mesaj hemen konuşmada görünmeli, altında "düşünüyor" yazmalı.
8. "Hangi veri setlerine sahipsin" sorusunda Gold anlatıldı; beklenen BDDK ve EVDS. Alan tanımı `... ve gold kaynaklı veriler` idi.

## Karar

- **Genel bilgiden cevap yok:** sistem istemine kural (kişiler hakkında hiç, bilinmiyorsa "elimde bilgi yok"). Deterministik
  kapı: cevapta "genel bilgimden / genel bilgime göre / kendi bilgimden" gibi işaret varsa bir kez geri gönderilir; sürerse araç
  çalışmadıysa cevabın tamamı yerine sabit "bu konuda bilgi yok" cümlesi, çalıştıysa yalnız o paragraflar yayımlanmaz.
- **Yetenek ve veri seti soruları deterministik** (ADR-0045 selamlaşmasıyla aynı yol, LLM çağrısı yok): internet yeteneği kayıtlı
  araçlardan (web_search/web_url) söylenir; veri setleri katalogdan birincil kaynağa göre okunur adla, seri sayısı ve kapsamla
  sayılır. Rakam geçen ya da uzun mesaj veri sorusudur, bu yola girmez.
- **Dolgu:** cevabın başındaki "Anladım, not aldım / Özür dilerim / Haklısın" kırpılır; istemde de yasak.
- **Kaynak adları ve türetilmiş katmanlar config'de** (`source_hints.json`: `source_names`, `derived_sources`): alan tanımı
  birincil kaynaklardan kurulur ("BDDK Aylık Bülten, … ve TCMB EVDS kaynaklı veriler"); Gold ve kullanıcı yüklemesi kaynak sayılmaz,
  yalnız türetilmiş katman varsa (boş katalogdan yeni alan) onun kimliği kullanılır. Kod kaynak adı taşımaz.
- **Resmi kamu adresleri:** `official_hosts` (tcmb.gov.tr, bddk.org.tr, tuik.gov.tr …) alan adlarındaki https adreslerini model
  kullanıcı yazmasa da açabilir; okuma yalnız bu alan adlarına gider, sızdırma kanalı açmaz. Diğer adresler için niyet kapısı aynen
  sürer. Bilinen adres kalıpları (`url_patterns`, ör. TCMB günlük kur XML'i) istemde; "internetten araştır" denince model kendisi arar.
- **XML tablo olur:** en sık tekrar eden, çocukları yaprak olan öğe kayıttır; satır = öznitelikler + yaprak metinleri; kök
  öznitelikleri (bülten tarihi) not. Ayrıştırıcı varlık çözümlemez, ağa çıkmaz.
- **Belge metni pencereyle:** kartta 8.000 karakter ve "text_from=N ile devam et" notu; sayfa metni güvenlik sınırı 400.000.
- **Arayüz:** sağ panelde sayı listesi yok (rozetler ve kanıt zinciri kalır); gönderilen mesaj hemen konuşmaya eklenir, altında
  "Düşünüyor…"; cevap gelince yerini tam cevap alır.

## Reddedilen seçenekler

- **Kişi sorularında otomatik web araması:** özel bir kişi hakkında bilgi derlemek istenmiyor; kullanıcı açıkça kaynak verirse okunur.
- **Niyet kapısını tamamen kaldırmak:** sayfaya gömülü adresle veri sızdırma riski geri gelir; resmi alan adı listesi yeterli.
- **Veri seti sorusunu modele bırakmak:** katalog kesin bilgi; model Gold'u ve iç katmanları anlatıyordu.

## Sonuç

`tests/test_geri_bildirim_2026_09_14.py` (XML, resmi adres, metin penceresi, alan tanımı, yetenek/veri seti, dolgu, genel bilgi
kapısı, arayüz, yıl/sıra kimliği); ajan testleri 485 → 495. Canlı deneme (gerçek model ve demo veri, kullanıcının mesajlarıyla): kişi sorusu "elimde bilgi
yok"; yetenek ve veri seti soruları deterministik; TCMB XML'inden 2 Ocak 2015 kuru; "1 Temmuz 2026 kuru, araştır" sorusunda model
TCMB adresini kendisi açtı; 2 sayfalık PDF'in iki bölümü de özetlendi. Canlı denemede "bülten no 2026/120" kimliği sayı sanılıp kanıt rozeti düşüyordu; yıl/sıra kimliği tarih gibi maskelendi. Arayüz provası: `docs/experiments/geri_bildirim_arayuz_2026-09-14/`.

## Ek (14 Eylül, main entegrasyonu hazırlığında K01 bulgusu)

Deterministik yetenek cevabı bir analiz sorusunu yakaladı: K01 T05'teki "web_ziyaret serisinde davranış ne zaman değişti?" sorusunda
"web" (seri adının parçası) ve "serisinde" içindeki "eris" internet yeteneği kalıbına uydu; soru modele gitmeden "Kısmen. Bu ortamda
web araması kapalı…" diye cevaplandı ve kırılma analizi hiç çalışmadı (K01 21/22, `docs/experiments/k01_kabul_2026-09-14_1531.json`,
bd32404). Düzeltme: kalıplarda sözcük sınırı; analiz sözcüğü (kırılma, aykırı, artış, değişim, trend, ortalama, grafik, tablo, davranış …)
taşıyan mesaj hiçbir zaman yetenek sorusu sayılmaz. "Hangi seride kırılma var?" gibi sorular da modele gider. Regresyon testi K01
sorusunu ve benzerlerini içerir; K01 yeniden 22/22.
