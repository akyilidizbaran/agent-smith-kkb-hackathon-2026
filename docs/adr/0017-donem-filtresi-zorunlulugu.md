# ADR-0017: Soruda geçen dönem sorguda yoksa sorgu reddedilir

**Durum:** Kabul edildi · **Tarih:** 2026-09-09

## Bağlam
Golden set 6/7'den 2/7'ye düştüğünde teşhis, üç ayrı başarısızlığın **tek kök
nedene** dayandığını gösterdi: model dönem filtresini atlıyordu.

```
Soru : "2025 yılında konut kredisi bakiyesini aylık olarak göster"
SQL  : SELECT donem, tp, yp, toplam FROM bddk_aylik_krediler WHERE kalem = '...'
Sonuç: 66 satır — tüm kapsam (2021-01 → 2026-06), 12 değil
```

Etkilenen vakalar ve neden:
- **G2** (aylık seri): 12 yerine 66 satır.
- **G3** (aylık değişim): aynı.
- **G4** (kapsam dışı): sorguda "2015" hiç geçmediği için ADR-0010'daki kapsam
  kontrolü **tetiklenmedi**; agent 2015 verisi yokken bir tablo üretti.

Sonuncusu özellikle önemli: iki koruma birbirine bağlıymış. Dönem filtresi
atlanınca halüsinasyon koruması da devre dışı kalıyordu.

## Karar
`lakehouse_query`, sorguyu çalıştırmadan önce kontrol eder: kullanıcının
sorusunda geçen bir yıl SQL'de hiç geçmiyorsa sorgu **reddedilir** ve modele
dönem kısıtını eklemesi söylenir.

## Neden uyarı değil, ret
Önce sonuca uyarı metni eklendi ("tablonun tamamı döndü, daraltmak isteyebilirsin").
Ölçüldü: **0/2.** Model uyarıyı okuyup yine de cevaba geçti — çünkü tablo zaten
kurulmuştu ve uyarıyı dikkate almak zorunda değildi.

Ret ise seçenek bırakmıyor. Bu, ADR-0010'daki kapsam kontrolünde işe yarayan
kalıbın aynısı ve genel bir ilkeye işaret ediyor: **modelin uyabileceği bir
tavsiye ile uymak zorunda olduğu bir kısıt arasındaki fark, kararlılığın büyük
kısmını açıklıyor.**

## Ölçüm

| | Uyarı olarak | Ret olarak |
|---|---|---|
| G2 | 0/2 | **2/2 KARARLI** |
| G3 | 0/2 | **2/2 KARARLI** |
| G4 | 0/2 | **2/2 KARARLI** |

Tam golden set: **7/7** (önceki en iyi 6/7).

## Bedeli ve açık kalan
Her vakada bir ek tur oluşuyor: model önce filtresiz sorgu yazıyor, ret alıyor,
düzeltiyor. Vaka başına ortalama süre 82 sn'den 115 sn'ye çıktı. Yani doğruluk
için hız ödendi.

Bir sonraki iyileştirme, modelin ilk denemede doğru yazmasını sağlamak olmalı —
ret bir güvenlik ağı olarak kalsın ama olağan yolda tetiklenmesin.

## Yanlış pozitif riski
"2021'den beri nasıl değişti" gibi bir soruda kullanıcı gerçekten tüm seriyi
ister; ancak o durumda sorgu da `WHERE donem >= '2021-01-01'` içereceği için
kontrol tetiklenmez. Risk düşük, ama katalog çeşitlendikçe yeniden ölçülmeli.
