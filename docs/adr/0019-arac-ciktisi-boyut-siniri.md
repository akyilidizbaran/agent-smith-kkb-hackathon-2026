# ADR-0019: Araç çıktısı modelin taşıyabileceği boyutta tutulur

**Durum:** Kabul edildi · **Tarih:** 2026-09-09

## Bağlam
`lakehouse_distinct_values`, `contains` filtresi olmadan çağrıldığında 50 kaleme
kadar liste basıyordu. Ölçümde model bu listeyi aldıktan sonra **sorgu yazmadan
cevaba geçti** — yedi vakanın tamamında.

Bu, aracın kendi başına doğru çalıştığı ama çıktısının modeli boğduğu bir durum:
50 satırlık liste + alt toplam uyarıları, 8B'lik bir modelin o turda taşıyabildiğinden
fazlaydı.

## Karar
Filtresiz çağrıda tam liste basılmaz. Bunun yerine:
- kolonda kaç farklı değer olduğu,
- daraltma yönergesi ve somut bir `contains` örneği,
- fikir vermesi için ilk 8 değer

döndürülür. Varsayılan `limit` 50'den 20'ye indirildi.

## Gerekçe
Araç çıktısı, modelin okuyacağı bir arayüzdür (ADR-0010). Doğru veriyi döndürmek
yetmez; **o turda işlenebilir boyutta** döndürmek gerekir. Model bir listeyi
okuyamayacak kadar uzun bulduğunda hata vermiyor — sessizce başka bir şey yapıyor.

Yan fayda: daraltma yönergesi modeli aracın doğru kullanımına yöneltiyor, yani
çıktı sınırı aynı zamanda bir öğretim aracı.

## Not
Daraltma örneği ilk sürümde `contains='(10+11)'` gibi anlamsız bir terim
üretiyordu. `domain.py`'deki `kisa_terim` yardımcısı (profil örnekleri için
yazılmıştı) buraya da bağlandı; iki yer aynı kaynaktan besleniyor ki ayrışmasınlar.
