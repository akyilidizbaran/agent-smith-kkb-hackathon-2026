# ADR-0072 — Düşük kaliteli OCR tablosu aktif tablo olmaz; OCR sayısı doğrulanmış sayılmaz

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** düzeltme planı K02-T06 (A12) · **Değiştirdiği:** ADR-0041'deki
"OCR kalitesi yalnız notla işaretlenir" davranışı

## Bağlam

OCR sayfası kalite ölçüyordu (`belirsiz`: tablo yapısı çözülemedi; `düşük`: satır toplamları tutmuyor) ve "DİKKAT … bu
tablodan sayı verme" notu yazıyordu. Ama `web_url(table_index=…)` tabloyu kaliteye bakmadan aktif tablo yapıyor, provenance'a
yalnız ilk notu taşıyordu. Kanıt paneli de OCR tablosundan eşleşen sayıları doğrulanmış sayıyordu.

## Karar

- **Kalite kapısı:** kalite `düşük` ya da `belirsiz` ise tablo yüklenmez; `LOW_QUALITY_SOURCE` (tekrar denemeyle çözülmez)
  döner ve DİKKAT notları mesajdadır. Kullanıcı açıkça "doğrulanmamış olsa da kullan" derse yüklenir; bu durumda bütün
  DİKKAT notları kolon provenance uyarılarına girer.
- **Doğrulanmamış sayı:** web kaynağı OCR ile okunmuşsa panel `ocr_unverified` olur; hücreler eşleşse de "sayılar" rozeti
  yeşil olmaz ve boşluk "sayılar OCR ile görüntüden okundu; hücreler doğrulanmadı, kesin sonuç sayılmaz" der. Zincir rozeti
  (URL + sha256 + zaman) bundan etkilenmez.

## Sonuç

`tests/test_k02_ocr.py` (bozuk OCR tablosu yüklenmez; açık kabulle uyarılı yüklenir) ve güncellenen kanıt testi
(`test_sorudaki_yil_ve_metin_kalmis_hucre_sayi_sayilir`: OCR tablosu artık `complete` değil).
