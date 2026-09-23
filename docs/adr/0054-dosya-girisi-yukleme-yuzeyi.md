# ADR-0054: Dosya girişi — oturuma özel yükleme yüzeyi, format matrisi, Excel sayfa seçimi

**Durum:** Kabul edildi · **Tarih:** 2026-09-14 · **Milestone:** M10

## Bağlam
Jüri demoda dosyayı canlı verecek (K02: iki profilde de). Bugüne kadar kullanıcı sunucudaki dosya
yolunu yazmak zorundaydı; XLSX okuma kütüphanesi (openpyxl) kurulu değildi; çok sayfalı Excel'de
sessizce ilk sayfa alınıyordu; ingest okuyucusu yönlendirmeleri kütüphaneye bırakıyordu.

## Karar
1. **`POST /api/upload`**: tür (kabul listesi; .xls/.doc/.html açık ret ve öneri), boyut (25 MB),
   boş dosya denetimi; oturuma özel dizin `INGEST_ALLOWED_ROOT/uploads/<oturum>/<8hex>_<güvenli-ad>`;
   kullanıcının yerel yolu hiç görülmez; sıfırlama dizini siler.
2. **Mesaj kompozisyonu:** arayüz soruya `Dosya: <sunucu yolu>` ekler; araçların "adres kullanıcı
   metninde geçmeli" kuralı korunur, yeni yetki yolu açılmaz. Balonda yalnız dosya adı.
3. **Excel:** openpyxl eklendi; çok sayfada `sheet` istenir (ad ya da indeks), `.xls` reddedilir.
4. **İngest okuyucusu** HTTP'de `guarded_get` kullanır (M05 ile aynı sınır); `FetchRefused` →
   `ReadRefused` olarak yüzeye çıkar.
5. Format matrisi ve sınırlar `docs/calisma-notlari/M10_DOSYA_GIRISI.md`'de; "her belgeyi doğru okuma" vaadi yok,
   ret ve soru da başarılı davranıştır.

6. **Tarih kolonu gerçek tarihe çevrilir** (`convert_dates`, tablo yüklemede): canlı provada "31.01.2025"
   metin kalınca `LAG … OVER (ORDER BY "Tarih")` sözlük sırasına gitti ve aylık değişimler yanlış çıktı;
   sayılar tabloda olduğundan kanıt paneli yakalayamadı. Profilcinin %100 ayrıştırdığı biçim çevrilir;
   gün/ay belirsizse metin kalır ve söylenir. `workspace_compute_column` metin kolonuna göre ORDER BY'ı
   reddeder (zaman sırası değil, sözlük sırası).

## Sonuçlar
- Canlı prova: jüri CSV yüklendi → tablo → aylık değişim 65,5 / 102,75 / … doğru, kanıt 12/12 tam.
- Testler 348 → 353 (yükleme güvenliği, XLSX çoklu sayfa, .xls, okuyucu yönlendirme).
- Açık: sayfa/tablo seçimi için arayüz düğmesi (bugün sohbette parametreyle); profilci güven puanı (T04).
- Bağımlılık: `openpyxl`, `python-multipart` kilit dosyasında.
