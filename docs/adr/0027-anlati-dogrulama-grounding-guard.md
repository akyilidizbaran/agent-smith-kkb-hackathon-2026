# ADR-0027: Anlatı doğrulama — cevaptaki her sayı bir araç çıktısında olmalı

**Durum:** Kabul edildi · **Tarih:** 2026-09-11 · **Modülün yazarı:** Büşra (V3 §3.1)

## Bağlam
Harness'ın kuralı baştan beri "model hesap yapmaz, SQL yapar"dı. Bu kural **araç
çağrısında** tutuyor: hesap `lakehouse_query` ya da `workspace_compute_column` ile
yapılıyor, model aritmetik yapmıyor. Tutmadığı yer **anlatı**: model tabloyu doğru
üretip, sonra tablonun altına tabloda olmayan bir sayı yazıyor.

Büşra'nın V3 ölçümünde gölge modda yakalanan örnek: tablo doğru, anlatıda
"155.515 milyon TL arttı" — o fark hiçbir araç çıktısında yok, model kendi çıkarmış.
Bu bizim ölçtüğümüz hiçbir kontrole takılmıyordu; golden vakaları **üretilen tabloyu**
kontrol ediyor (ADR-0007), serbest metni değil. Yani kör noktamız tam da jürinin
okuyacağı yerdeydi.

11 Eylül motor karşılaştırmasında V3 iki şemada 43/45 ve 45/45 temiz ölçtü; bizde
eşdeğer bir kontrol yoktu ve "söyleneni doğrula" saldırısını (L11-02) Silver'da
2/3 geçiyorduk.

## Karar
`grounding_check(question, answer, tool_texts)` ortak katmana (`core/grounding.py`)
alındı ve döngüye takıldı. Modül Büşra'nın; tek kopya olsun diye `kkb_agent_v3`
yerine `kkb_agent`'a taşındı — saf fonksiyon, yalnız `re` kullanıyor, ne harness'ı
ne adaptörü tanıyor, iki motor da import edebilir.

Cevap yazılmadan önce cevaptaki her sayı, o soruda başarılı olmuş araç çıktılarının
havuzunda aranır:

- **Temiz** → cevap gider.
- **Eksik sayı ya da nedensellik ifadesi** → cevap bir kez geri gönderilir, gerekçesi
  söylenerek ("şu sayılar hiçbir araç çıktısında yok: …").
- **İkinci denemede de eksik** → cevap yine gider, ama doğrulanamayan değerler
  cevabın sonunda açıkça işaretlenir.

İkinci durumda cevabı tümden bastırmıyoruz: tablo zaten kullanıcıda ve doğru;
anlatıyı silmek bilgi kaybı olur, işaretlemek olmaz.

## Neden sayı karşılaştırması bu kadar dikkat istiyor
Aynı metin havuzunda iki sayı biçimi var: araç çıktıları pandas'tan İngiliz ondalığı
ile geliyor (`1.357539`), model Türkçe yazıyor (`1,36`, `678.970`). Binlik ayracı
alternatifi yalnız üçerli gruplar rakamla devam etmiyorsa eşleşiyor — aksi hâlde
`1.357539` → `1.357` (=1357) okunuyor ve `%1,36` havuzda bulunamıyordu. Büşra'nın
gölge kayıtlarındaki yanlış pozitiflerin kaynağı buydu; modül bunu çözmüş hâlde geldi.

Kontrol dışı bırakılanlar: yıllar (1900–2100), ≤31 küçük tam sayılar (ay/gün/sıra),
soruda zaten geçen sayılar. Tolerans %0,5 — yuvarlama geçer, uydurma geçmez.

## Nedensellik ayrı bir filtre
"yol açtı", "neden oldu", "sayesinde" gibi ifadeler veriden çıkarılamaz. Sayı uydurmak
kadar risklidir ve jüri tam olarak bunu arar. Aynı geri gönderme yoluna bağlandı.

## Ölçüm
Sahte LLM ile dört test (`tests/test_agent_loop.py`): uydurma sayı bir kez geri
gönderiliyor, ikinci denemede işaretleniyor, nedensellik geri gönderiliyor, veri
çekilmemişse ölçüm hiç yapılmıyor (havuz boşken her sayı "eksik" görünür, ölçüm
anlamsız olur). Golden koşucusu artık `ANLATI DOĞRULAMA: n/m temiz` basıyor.

## Maliyet
Temiz cevapta sıfır ek tur. Kirli cevapta bir ek tur. Büşra'nın ölçümünde enforce
modunun bedeli +2 turdu; bizde tek yeniden üretim olduğu için +1.

## İlgili
ADR-0007 (kontrol edilen şey üretilen tablodur), ADR-0010 (boş sonuç ve halüsinasyon),
ADR-0025 (yapılandırılmış hata zarfı), ADR-0026 (kataloglu/sorgulanabilir ayrımı).
