# Finans dışı kabul fikstürleri (M03-T08, A08/A09)

Bu dosyalar **sentetiktir** (gerçek sağlık istatistiği değildir); motorun finans kataloğu olmadan çalıştığını
ve iki tarihsiz tablonun anahtarla birleştirildiğini modelden bağımsız beklenen sonuçlarla göstermek içindir.

| Dosya | Şekil | Beklenen |
|---|---|---|
| `acil_basvuru_aylik.csv` | zaman serisi, aylık, 12 satır | Aralık sıçraması aykırı (IQR); tarih kolonu tarih tipine çevrilir |
| `hastane_il.csv` | tarihsiz, il anahtarlı; **Van iki kez**; `yatak_sayisi` tümü tek noktalı (7.120) | sağ tabloda yinelenen anahtar → birleştirme reddedilir; `yatak_sayisi` sayı biçimi belirsiz → metin kalır ve not düşer (7,12 mi 7120 mi veriden çıkmaz) |
| `nufus_il.csv` | tarihsiz, `il_adi` anahtarlı; büyük/küçük harf farkı; Trabzon hastane tablosunda yok | nüfus ⟕ hastane (tekilleştirilmiş): eşleşen 3, yalnız solda 1 (Trabzon), yalnız sağda 1 (Van) |
