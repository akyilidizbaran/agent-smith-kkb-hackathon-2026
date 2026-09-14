# ADR-0077 — İşaretsiz büyüklük, yön sözcüğü ve yuvarlama: her geçiş kendi bağlamında

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** düzeltme planı K03-T03 canlı tekrar bulgusu (M13-T03, M13-T05, A06, A14)

## Bağlam

Canlı M16 kabulü 51c066d'de üç kez koşuldu (14/14, 13/14, 12/14). A06 turu ("faiz düşerken kredi artmayan dönemler")
iki koşuda düştü: cevabın 24 sayısının hepsi tabloda bulundu, ama bir ya da iki sayı "işaret uyarısı" aldığı için
sayılar rozeti ✗ oldu. Cevap aynı büyüklüğü tabloda işaretli ("−0,51 puan"), yorumda işaretsiz ve yön sözcüğüyle
("faiz düşüşü küçük (0,06–0,51 puan)") yazıyordu. İki kusur vardı:

- Yön sözcüğü penceresi sayının metindeki ilk geçişine bakıyordu; ilk geçiş işaretli tablo hücresiydi ve çevresinde yön
  sözcüğü yoktu.
- İşaret çevirmeli eşleşmede yalnız göreli tolerans vardı; işaretli eşleşmedeki gösterilen ondalığın yarım birimi
  (M13-T05) yoktu. "0,06" ↔ −0,062 ve "0,4" ↔ −0,403 eşleşmiyordu.

## Karar

- Yön sözcüğü, sayının işaretsiz yazıldığı geçişlerin her birinin ±40 karakter çevresinde aranır; biri yeterlidir.
  İşaretli geçişler ("−0,51") ve başka bir sayının parçası olan geçişler ("10,51") sayılmaz.
- İşaret çevirmeli eşleşme işaretli eşleşmeyle aynı toleransı kullanır (göreli %0,5 ya da gösterilen ondalığın yarım
  birimi, büyük olan).
- A14 kuralı değişmez: açık ters işaret ("+0,54" ↔ −0,54) eşleşmez; yön sözcüksüz işaretsiz büyüklük eşleşir ama
  uyarı alır ve rozet yeşil olmaz.

## Reddedilen seçenekler

- **Pencereyi büyütmek:** ilk geçiş sorununu çözmez; ilgisiz cümlelerdeki yön sözcüklerini de sayar.
- **İşaretsiz büyüklüğü koşulsuz kabul etmek:** M13-T03'ün kaldırdığı koşulsuz ters işaret eşleşmesini geri getirir.

## Sonuç

`tests/test_k03_isaret_yonu.py` canlı cevabın metniyle (uyarı yok, rozet yeşil), yönsüz sayıyla (uyarı var), yuvarlama
sınırıyla (0,06 eşleşir, 0,07 eşleşmez) ve geçiş seçimiyle; mevcut A14 testleri geçiyor. Ajan testleri 473 → 477.
Canlı koşu kayıtları değiştirilmedi; düzeltmeden sonra hedefli tekrarlar ayrı raporlanır.

## Ek (14 Eylül, hedefli canlı tekrarlar 6f12bbe)

Düzeltmeden sonraki hedefli tekrarlarda iki farklı kusur daha görüldü; aynı ilkeyle kapatıldı (sayı ya da eşleşme bilgisi
araçtan ya da tablodan türetilebildiği ölçüde kabul edilir, tahmin kabul edilmez):

- **Kalan satır sayısı (21b594e):** finans 1. turda model 60 satırın 10'unu listeleyip "Kalan 50 ay aktif analiz
  tablosunda" dedi; 50 hücrede olmadığı için rozet ✗ oldu (aynı imza gece koşuları 0133/0154'te de vardı). Tamsayı, tablo satırı
  eksi cevapta gösterilen farklı satır sayısına eşitse ve işaretsiz geçişinin yanında "kalan/diğer/gösterilmeyen" gibi bir sözcük
  varsa "(kalan satır sayısı)" olarak doğrulanır. Tutarsız sayı ve sözcüksüz aynı sayı doğrulanmaz
  (`tests/test_k03_kalan_satir.py`). Kayıtlı canlı cevap yeniden değerlendirildiğinde 14/14, sayılar ✓.
- **Birleştirme kapısı (04655c7):** dosya senaryosunun birleştirme turunda model `workspace_join`'i çağırmadan "birebir
  eşleşme yalnız Adana'da tutar, İzmir vs Izmir" yazdı; fikstürde tam eşleşen yalnız İzmir'dir, iki iddia da yanlıştı. Soru
  birleştirme istiyor, oturumda en az iki tablo var, turda `workspace_join` yok ve cevap eşleşmeyi anlatıyorsa cevap bir kez geri
  gönderilir; eşleşme bilgisi aracın kartından gelir (D01, ADR-0065). Tek tabloda ve birleştirme istenmeyen turda kapı açılmaz
  (`tests/test_k03_birlestirme_kapisi.py`).

Ajan testleri 477 → 482. Canlı koşu kayıtları değiştirilmedi.

Aynı gün ekran provası ve kapı tekrarlarında üç kusur daha bulundu (`tests/test_k03_ekran_bulgulari.py`, ajan testleri 485):

- **Kart tablosu hizası:** `web_url` kartı pandas ile sağa hizalıyordu; kısa metin değerlerin önünde dolgu boşluğu görünüyordu ve model "adların başında boşluk var" diye yanlış yazdı. Metin sola, sayı sağa hizalanır; satır başında dolgu yok.
- **Yıl-ay yazımı:** "kapsam 2026-06'ya kadar" cümlesindeki 2026 sayı sanılıp "tabloda yok" deniyordu. Yıl-ay (ay 01–12) tarih olarak maskelenir; "2021-25 arası" gibi yıl aralığı maskelenmez.
- **Bakış sonucu:** `lakehouse_query` bakış modunda (aktif tablo değişmez) dönen sonuç kanıt havuzuna girmiyordu; model faizleri o sonuçtan doğru yazdığı halde panel "tabloda yok" dedi. `workspace_query` gibi bakış kaydı tutulur.
