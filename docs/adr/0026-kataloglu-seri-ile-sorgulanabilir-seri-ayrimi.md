# ADR-0026: Kataloglu seri ile sorgulanabilir seri ayrı şeylerdir

**Durum:** Kabul edildi · **Tarih:** 2026-09-11

## Bağlam
Veri ekibinin iki dalı birleştirilip gerçek kaynaklardan veri çekildiğinde adaptörümüzü
ilk kez gerçek bir veritabanına bağladık. Sağlık çıktısı şuydu:

```
series               1620
observations          987
unverified_series    evds:TP.AKONUTSAT1.KMA, evds:TP.AKONUTSAT1.KTR100, ... (1605 kimlik)
```

1620 seri kataloğa girdi, 15'inde gözlem vardı. `meta.series` "hangi serinin **anlamı**
kayıtlı" sorusunu yanıtlar; "hangi serinin **verisi** var" sorusunu değil. Biz ikisini tek
şey sanmıştık — çünkü kendi seed'imizde ikisi aynı şeydi.

Üç ayrı arıza aynı kökten çıkıyordu:

1. **Model sorgulayamayacağı seriyi görüyor.** 1605 seri için `DatasetSpec` üretiliyor,
   araç açıklamalarına ve alan profiline giriyordu. Model bunlardan birini seçtiğinde
   boş sonuç alır; ADR-0010'da ölçtüğümüz üzere boş sonuç, sayı uydurmanın en verimli
   zeminidir.
2. **Hata mesajı hataya dönüşüyor.** `get_dataset` bulunamayan kimlik için *tüm kataloğu*
   listeliyordu. Dört tabloda faydalı, 1620 seride modele gönderilen tek bir mesajın
   pencereyi doldurması demek.
3. **Arama eşleşme yoksa alakasız tablo döndürüyor.** Skor sıfır olduğunda kataloğun ilk
   N serisi dönüyordu. Seed'de zararsız bir kolaylık; 1620 seride modele "bunu kullan"
   demenin kibar hâli.

## Karar
Adaptör kataloğu ikiye ayırıyor:

- `_catalog` — `silver.fact_observation`'da **en az bir gözlemi olan** seriler. Modele
  giden, aranan, tarif edilen küme budur.
- `_uningested` — katalogda tanımlı, gözlemi olmayan seriler. Yalnızca kimlik ve ad.

`get_dataset` üç farklı cevap veriyor ve bunlar birbirinin yerine geçmiyor:

| durum | cevap |
|---|---|
| gözlemi var | `DatasetSpec` |
| katalogda var, gözlemi yok | "katalogda tanımlı fakat henüz hiç gözlem yüklenmemiş" |
| katalogda yok | "bulunamadı" + en fazla 8 benzer kimlik + `lakehouse_search` yönlendirmesi |

Arama eşleşme bulamazsa **boş dönüyor**. `health()` üç sayıyı ayrı ayrı basıyor:
`queryable_series`, `catalogued_series`, `uningested_series`.

## Neden ikinci satır ayrı bir cevap
Jüri kataloğun içinde olup henüz çekilmemiş bir seriyi sorabilir — 1620'ye 15 oranıyla
bu ihtimal yüksek. "Bilmiyorum" yanlış cevaptır: seri tanımlıdır, anlamı kayıtlıdır,
nereden geleceği bellidir. Doğru cevap "bu seri tanımlı fakat verisi bu ortama henüz
yüklenmemiş"tir ve bunu söyleyebilmek için iki durumu tek hataya indirgememek gerekir.

## Sonuç
Gerçek veritabanında (1620 katalog / 15 yüklü) sağlık çıktısı:

```
queryable_series      15
catalogued_series   1620
uningested_series   1605
unverified_series      2 seri (ör. evds:TP.FG.J0, evds:TP.KFE.TR)
```

Golden: **7/7, 3/3 kararlı**, bütün vakalar %100 — ayrım hiçbir mevcut davranışı bozmadı.
Gerçek veritabanında canlı soru: "2026 ikinci çeyrek itibarıyla hangi ilde konut kredisi
bakiyesi en yüksek?" → İstanbul 228.383.471 bin TL, Ankara 108.927.596, İzmir 59.970.021;
kaynak ve birim belirtilerek.

## Kapanmayan taraf
Bu ayrım "yüklenmemiş" durumu **görünür** kılar, çözmez. 1605 serinin yüklenmesi veri
ekibinin işi. Bizim tarafta açık kalan asıl mesele, sorgulanabilir seri sayısı üç haneye
çıktığında kataloğun tamamının sistem promptuna sığmayacak olmasıdır — ADR-0013'te
ölçtüğümüz eşik (≈1000 seri = 28k token, %98 doğruluk; 3000 seri = %92) hâlâ geçerli ve
ön-yükleme + retrieval kararı hâlâ sıradaki iş.

## İlgili
ADR-0010 (boş sonuç ve halüsinasyon), ADR-0013 (katalog token eşiği),
ADR-0024 (Silver adaptörü ve fiziksel SQL), ADR-0025 (yapılandırılmış hata zarfı).
