# PDF adresinde HTTP 200 ile dönen HTML erişim engeli

17 Eylül 2026 yerel doğrulaması:

`https://www.borsaistanbul.com/files/aylik-piyasa-raporu-kasim-2023.pdf`

Uygulamanın HTTP istemcisine HTTP 200, Content-Type `text/html` ve 247 baytlık
`Request Rejected` sayfası döndü. Gövdede `The requested URL was rejected` yazıyordu.
Bu yanıt PDF değildir; kaynak PDF'nin bozuk olduğu sonucuna varılamaz.

Önceki davranışta HTTP 200 başarılı erişim sayılıyor, URL'nin `.pdf` uzantısı nedeniyle
HTML gövdesi PDF/OCR okuyucusuna gönderiliyordu. Ayrıştırıcı hatası model tarafından
bozuk dosya olarak anlatılıyor; model farklı sayfa seçerek aynı erişimi tekrar deniyordu.

Düzeltme:

- Erişim sınıflandırıcısı açık ret gövdesini `blocked / bot_challenge` olarak tanır.
- Web okuma ve veri yükleme yolları OCR/ayrıştırma öncesinde `ACCESS_BLOCKED` döndürür.
- HTML içerik türü dosya uzantısından önceliklidir. Web ayrıştırıcısı PDF/HTML gövde
  imzalarını da kontrol eder; gerçek PDF yanlış HTML başlığıyla gelse bile tanınır.
- Erişim reddi kaynağın bozukluğu olarak anlatılmaz; engel farklı PDF sayfalarıyla
  yeniden denenmez. Kaynak verisi alındığı veya veritabanına yazıldığı iddia edilmez.

Bu değişiklik dış sunucunun erişim engelini kaldırmaz. Site PDF'yi bu istemciye
göndermediği sürece URL'den tablo okunamaz. Kullanıcının indirdiği gerçek dosya
ayrı bir yerel kaynak olarak incelenebilir.

Doğrulama: `test_pdf_rejected_response.py`, `test_access_policy.py`, `test_web.py`,
`test_vision.py`, `test_web_ingest.py`: 94 test geçti.
