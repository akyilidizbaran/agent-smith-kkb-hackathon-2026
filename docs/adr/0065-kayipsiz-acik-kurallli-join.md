# ADR-0065 — Kayıpsız ve açık kurallı anahtar eşleme; yardımcı kolonsuz birleştirme

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** bağımsız kontrol R01/R07 → düzeltme D01/D07 (M03, M11, A09)

## Bağlam

`workspace_join` anahtarları `float64`'e çeviriyordu: `9007199254740992` ile `9007199254740993` eşleşti ve sağdaki değer
yanlış satıra yazıldı. Metin `001` ↔ `1`, boş ↔ boş anahtar ve saatli zaman damgaları da örtük olarak aynı sayıldı.
Ayrıca geçici `__k` ve `_merge` kolonları kullanıcının aynı adlı kolonlarını ezip sonuçtan düşürüyordu.

## Karar

- **Anahtar eşdeğerliği açık kuraldır (`key_policy`).** Varsayılan `tam`: tamsayı Python tamsayısı (float yok), metin
  olduğu gibi, zaman damgası saat/saat dilimiyle. Diğer kurallar yalnız açık seçimle: `metin` (iki taraf metin olarak),
  `metin_normal` (boşluk ve Türkçe büyük/küçük harf farkı yok sayılır), `sayi` (baştaki sıfırlar yok sayılır),
  `tarih_gun` (saat atılır).
- **Tip farkı ya da sonucu değiştiren kural sorulur.** `tam` kuralında iki tarafın tipi farklıysa ya da gevşek bir kural
  daha çok satır eşleştiriyorsa araç birleştirmez; seçenekleri eşleşme sayıları ve bir örnekle döner. Model kullanıcıya
  sorar, kabul edilen kuralla yeniden çağırır.
- **Hassasiyet kaynakta kaybolmuşsa doğruluk iddia edilmez.** Ondalık okunmuş ve 2^53'ü aşan kimlik reddedilir.
- **Boş anahtar hiçbir satırla eşleşmez**; sayısı karta yazılır.
- **Yineleme kural uygulandıktan sonra da denetlenir.** Birebir eşitlikte yinelenen anahtar önce raporlanır (her gevşek
  kuralda da yinelenir); yalnız kural yüzünden oluşan yineleme ayrıca söylenir.
- **Yardımcı kolon yok.** Eşleme anahtar sözlüğüyle yapılır; sonuç sol tablo + seçilen sağ kolonlardan kurulur. Ad
  çakışması `<kolon>_<kN>`, o da doluysa sayı sonekiyle çözülür. Kaynak tablolar değişmez, ham anahtar değerleri korunur.
- **Kural görünür.** Kart "Anahtar kuralı" satırını taşır; sağdan eklenen her kolonun provenance SQL'ine
  `-- workspace_join kN.anahtar = kM.anahtar · kural: …` eklenir.

## Reddedilenler

- **Sessiz normalizasyonu koruyup yalnız float'ı düzeltmek:** `001`/`1` ve harf farkı her veri alanında aynı kimlik
  değildir; sonucu değiştiren eşdeğerlik kullanıcının kararıdır.
- **Rezerv adı başka sabit adla değiştirmek:** yine çakışabilir; yardımcı kolon hiç kullanılmaz.

## Sonuç

`tests/test_d01_d07_join.py` (9 vaka: büyük ardışık tamsayı, float okunmuş kimlik, `001`/`1`, boş anahtar, aynı gün iki
saat, bildirilmiş metin/tamsayı, kural kaynaklı yineleme, `__k=preserve-me`/`_merge`/hazır `value_k2`/açık `columns`,
outer/inner). M11 ve finans dışı A09 testleri artık kuralı açık seçerek geçer.
