# ADR-0081 — Ürün kullanım sorusu ve bağlam kayması

**Tarih:** 15 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** kullanıcının arayüz denemesi (15 Eylül akşamüstü)

## Bağlam

Arayüzdeki akış:
1. "naber": selamlaşma, model çağrılmadı.
2. "elimizde hangi veriler var": katalogdan deterministik cevap geldi, sohbet geçmişine eklendi.
3. "architect rolüne nasıl geçebilirim": ajan veri seti tablosunu yeniden yazdı (11,3 s), yani bir önceki soruyu cevapladı.

Oturumun kayıtlı adımları:
- İlk adım: "veri çekilmeden cevap denendi — geri gönderildi".
- Ardından `lakehouse_search` "tüm tablolar veri kaynakları" araması ve iki `lakehouse_query` geldi.
- Sonra "grounding: MISS:681" oldu ve cevap yazıldı.

Neden:
- Aktif tablo yokken araç çağırmayan her cevap "Kullanıcının sorusunu cevaplayan sayıları lakehouse_query ile çek" diye bir kez
  geri gönderiliyordu (G5 önlemi). Kimlik sorusu (ADR-0080) dışında istisna yoktu.
- Ürün kullanım sorusu veri istemez. Sayı çekmeye zorlanan model, geçmişte veriyle cevaplanabilecek tek konuya döndü.
- Bağlam penceresi (son 8 tur) doğru çalıştı; kaymayı zorlama yarattı.
- Modelin istemde rol geçişine dair bilgisi de yoktu.

## Karar

- **Rol, dosya yükleme ve indirme soruları deterministik** (`core/small_talk.py` `usage_reply`, `capability_reply` içinde).
  - Cevap ürünün gerçek durumundan kurulur: kayıtlı araçlara göre Analyst ya da Architect.
  - Arayüz öğeleri anılır: Profil rozeti, operatör anahtarı; Dosya düğmesi, kabul edilen türler ve 25 MB; CSV, XLSX, HTML rapor
    ve PNG indir.
  - Türler ve sınır `web_app.UPLOAD_KINDS` ve `UPLOAD_MAX_BYTES` ile testte eşlenir.
  - Analiz sözcüğü korumasından önce çalışır: "profili nasıl değiştiririm", "tabloyu nasıl indiririm".
- **Kullanım sorusu geri gönderilmez** (`is_usage_question`). Kısa, rakamsız bir soruda "nasıl / nereden / nereye" ile birlikte bir
  ürün terimi geçmelidir: rol, profil, dosya, yükle, indir, rapor, kanıt zinciri, oturum, sıfırla, arayüz. Şu durumlarda kullanım
  sorusu sayılmaz:
  - veri fiili var: göster, hesapla, karşılaştır, getir, çiz, listele, kaç, ne kadar;
  - ekli dosya ya da adres var;
  - soru bir veri değişimini soruyor ("kredi kullanımı nasıl değişti").

  Deterministik konusu olmayan kullanım soruları ("Kanıt zincirini nasıl okurum?") modele gider ama geri gönderilmez.
- **Geri gönderme notu son soruyu yazar.** "Kullanıcının SON sorusu: «…»" ile başlar. Soru veri istiyorsa sayıları çekmesini,
  istemiyorsa araç çağırmadan yalnız bu soruya cevabı yeniden yazmasını söyler: "Önceki sorulara dönme." Kural belirsiz sorularda
  sürer; varsayılan G5 korumasıdır.

- **İkinci kaynak: araçsız işlem iddiası / sayı kapısı** (canlı S3, ilk koşu 44/45).
  - Tablo varken "Kanıt zincirini nasıl okurum?" bir tekrarda "araç çağrılmadan işlem iddiası" diye geri gönderildi. Model,
    önceki "2025 Aralık bakiyesi" sorusunu tablodaki sayıyla yeniden cevapladı; D02 son çıkışı bir ifadeyi daha sildi.
  - Kapının iki notu da ("Bu turda HİÇBİR ARAÇ ÇALIŞMADI…") son soruyu yazmıyordu.
  - Karar:
    - Üç geri gönderme notu (veri çekilmedi, işlem iddiası, tabloda olmayan sayı) ortak `LAST_QUESTION_NOTE` ile başlar:
      "Kullanıcının SON sorusu: «…». Önceki sorulara dönme".
    - Kullanım sorusunda anlatım fiili ("sorgu çalıştırılır, hesaplandı") işlem iddiası sayılmaz.
    - Tabloda olmayan sayı ve okunmamış dosya kapısı kullanım sorusunda da sürer.

- **Üçüncü bulgu: araçsız turda uydurma tutar yayımlandı** (bağlam senaryosu, ikinci koşu 45/45, otomatik denetim zayıftı).
  - Tabloda yalnız "2025 Aralık 678.970" varken "Bir önceki aya göre farkı ne?" iki tekrarda araçsız cevaplandı:
    "Kasım 677.970, fark +1.000". Doğrusu Kasım 658.770, fark 20.200.
  - `unverified_numbers` iki yoldan geçirdi:
    - göreli %0,5 tolerans 677.970'i 678.970'e eşleşmiş saydı;
    - "1.000"ın ondalık okuması (1,0) tablonun satır sayısına (1) eşleşti.
  - Senaryo denetimi yalnız "kasım/fark" sözcüğüne bakıyordu; hata elle okumada bulundu.
  - Karar:
    - Göreli tolerans kalkar; sayı gösterildiği hassasiyetin yarım birimiyle eşleşmeli (tam sayı 0,5; "17,99" 0,005).
    - Tek noktalı üç haneli yazımın ondalık okuması yalnız tam sayıya düşmüyorsa denenir ("18.388" evet, "1.000" hayır).
    - Senaryo denetimi cevaptaki her tutarı veriden bilinen tutarlarla karşılaştırır.
- **Dördüncü bulgu: oturum sıfırlama.** "Oturumu nasıl sıfırlarım?" modele gitti; üç tekrarda da "'oturumu sıfırla' yazmanız
  yeterli" dedi. Doğrusu sol paneldeki düğme. Karar: sıfırlama da deterministik kullanım cevabıdır. Cevap Oturumu sıfırla düğmesini
  ve Architect'te Tam veri sıfırlama düğmesini anar; etiketler testte `index.html` ile eşlenir.
- **Açık (bu kararda değiştirilmedi):** araçlı turların `grounding_check`'i de göreli %0,5 tolerans kullanıyor (araç çıktısındaki
  sayılar havuzuyla). Örneğin araç 20.200 dediyse, kafadan yazılmış 20.150 geçer. Aynı düzeltme orada K02'deki iki okumalı
  eşleşmeleri ("18,388 ⇄ 18.388") etkileyebilir; ayrı ölçümle ele alınmalı.

## Sonuçlar

- Kullanıcının akışı modele hiç gitmeden cevaplanır. Rol cevabı o anki profili ve geçişi söyler.
- Ajan testleri 627 geçti (`tests/test_baglam_kullanim_sorusu.py`). Testler şunları kapsar:
  - kullanıcının akışı;
  - yanlış pozitifler: veri değişimi, veri fiili, ekli dosya;
  - profile göre rol cevabı;
  - arayüzle tutarlı türler ve sınır;
  - modele giden kullanım sorusu;
  - belirsiz soruda notun son soruyu yazması.
- Ajan testleri 632 geçti. K01 22/22, K02 22/22 (`docs/experiments/k01_kabul_2026-09-15_1754.json`,
  `k02_finans_kabul_2026-09-15_1754.json`). K02'deki üç ondalıklı iki okumalı eşleşmeler yeni toleransla da geçti.
- Canlı ölçüm: `scripts/baglam_senaryolari.py`. Gerçek model, demo DB kopyası, web araması kapalı; beş çok turlu senaryo.

  | Koşu (rapor) | Kod durumu | Sonuç |
  |---|---|---|
  | 1 (`…_1743.json`), ×3 | kullanım cevabı + geri gönderme notu | 44/45; S3'te kanıt zinciri sorusu işlem iddiası notuyla önceki soruya kaydı |
  | 2 (`…_1749.json`), ×3 | + `LAST_QUESTION_NOTE` | 45/45 ama denetim zayıftı; elle okumada 2 uydurma fark, 3 yanlış sıfırlama cevabı |
  | S3 (`…_1748.json`), ×5 | aynı | 15/15; sıkı tutar denetimiyle de 5/5 doğru |
  | 3 (`…_1756.json`), ×3 | + tolerans + sıfırlama cevabı, sıkı denetim | 45/45 |
  | S3 (`…_1756_S3_x5_konsol.txt`), ×5 | aynı | 13/15 |

  - S3 ×5'in son koşusu: 3 doğru. Biri dürüst red: `lakehouse_query` doğrulamada reddedildi, model "hesaplayamıyorum" dedi.
    Biri yanlış: "0 değişim"; aşağıda açık konu.
  - Bu koşunun JSON'u aynı dakikada biten koşu 3 tarafından ezildi; konsol çıktısı saklandı. Betik artık saniye ve senaryo
    etiketini dosya adına yazıyor ve adımların hata kodunu kaydediyor.
- "Bir önceki aya göre farkı ne?" cevapları, cevaptaki her tutar veriyle karşılaştırılarak:
  - tolerans düzeltmesinden önce 11 cevapta 9 doğru, 2 uydurma tutarlı ("677.970", "+1.000");
  - sonra 8 cevapta 6 doğru, 0 uydurma, 1 dürüst red, 1 yanlış.
  - Düzeltmeden sonra araçsız uydurma taslak iki kez yakalandı; geri gönderilen model gerçek veriyi çekip 20.200'ü buldu.
- **Açık:** tek satırlık tablodan sonra "önceki aya göre fark" planlaması.
  - Bir tekrarda model önceki ayı `workspace_add_column` ile aynı tarihe kolon olarak ekledi; araç Aralık değerini getirdi ve cevap
    "0 milyon TL değişim, 678.970 → 678.970" oldu.
  - Sayılar araç çıktısından geldiği için doğrulama kapıları geçirir.
  - Olası önlem: eklenen kolon mevcut ölçüm kolonuyla birebir aynıysa kart uyarsın. Ölçülüp ayrıca karar verilecek.
- Bilinen sınır: kullanım sorusu tanıma sözcük tabanlıdır. Listede olmayan bir ürün sorusu hâlâ geri gönderilebilir; o durumda not
  son soruyu yazdığı için kayma beklenmez, canlı senaryo S4 bunu ölçer.
