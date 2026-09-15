# ADR-0085: Adım yolculuğu — araç izi figürlerle ve sırayla; alt çubuk tek satır

**Durum:** Kabul edildi · **Tarih:** 2026-09-16 · **İlgili:** ADR-0079 (canlı adım akışı), ADR-0083 (kanıt yolculuğu)

## Bağlam
Konuşmanın altındaki "Araç izi" çubuğu her araç çağrısını ayrı bir çip olarak diziyordu. 14 adımlık bir cevapta çubuk altı
satıra yayılıyor, yaklaşık 330 piksel yer kaplıyor ve konuşma alanını 900 piksellik ekranda 520 piksele düşürüyordu.

Kullanıcı (16 Eylül) izlerin korunmasını, ama kanıt yolculuğu gibi "Yolculuğu izle"nin yanındaki bir düğmeyle, figürlerle ve
sıralı gösterilmesini istedi.

## Karar
1. **Ortak gösterici:** kanıt yolculuğunun sahnesi, hareketi, ayrıntı kartı ve dar ekran düzeni `chainViewer(cfg)` fabrikasına
   taşındı. İki pencere de bunu kullanır:
   - kanıt yolculuğu ilk kopuk halkada durur (`halts: true`);
   - adım yolculuğu durmaz, çünkü ajan hatadan sonra devam eder.
2. **Durak kurucusu `stepStops(cevap)`:** her araç çağrısı ve doğrulamanın geri gönderdiği taslak cevaptaki sırasıyla durak olur.
   - Arka arkaya aynı araç tek durakta birleşir: "×5 · 10,0 s".
   - Son durak "Cevap"tır; araç sayısı, hata sayısı, geri gönderme, model çağrısı, token ve süreyi toplar.
3. **Durumlar:**
   - bütün çağrıları hatalı durak: kırmızı rozet, içine giden bağlantı kırmızı;
   - kısmen hatalı durak ve geri gönderilen taslak: amber rozet;
   - diğerleri teal.
4. **Figürler:** her araç türünün kendi figürü var:
   - katalog araması, web araması, tablo yapısı, kolon değerleri;
   - veri sorgusu (veri havuzu), tablo sorgusu (çalışma tablosu), tablo birleştirme, kolon hesabı, hesaplanmış tablo;
   - analiz, grafik, sayfa okuma, veri alma, öncül denetimi, netleştirme;
   - doğrulama, cevap.

   Bilinmeyen araç genel figürle ve kendi adıyla görünür. On ya da daha fazla duraklı zincirde figürler küçülür.
5. **Ayrıntı kartı:** duraktaki her çağrı ayrı bir karttır. Kartta şunlar yer alır: amaç (modelin `purpose` alanı), sonuç ya da
   hata kodu, süre ve varsa SQL. Geri gönderilen taslakta gerekçe yazar.
6. **Arayüz:**
   - Sağ panelde "Yolculuğu izle"nin yanında "Adımları izle" düğmesi var; araç çalışmamış cevapta kapalıdır.
   - Alttaki "Araç izi" çubuğu tek satır özet olur: "13 adım · 2 araç hatası · 1 geri gönderme · 235.958 token · 31,2 s". Araç kapısı
     pencerenin "Cevap" durağında gösterilir.
   - Sağ panelin gizlendiği ekranlar için özetin sonunda da "Adımları izle" düğmesi var.
   - Cevabın üstündeki kapalı "nasıl bulundu" listesi değişmedi.

## Sonuçlar
- İzden bilgi eksilmedi: çağrı sırası, amaç, sonuç, hata kodu, süre ve SQL pencerede; toplamlar hem pencerede hem alt satırda.
- Kanıt yolculuğu davranışı aynı kaldı; motor paylaşıldığı için iki pencere birlikte düzelir ya da bozulur. Testler ikisini de
  node üzerinde koşturur.
- Testler: `tests/test_adim_yolculugu.py`.
