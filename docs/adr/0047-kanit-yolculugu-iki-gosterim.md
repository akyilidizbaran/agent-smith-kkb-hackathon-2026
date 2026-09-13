# ADR-0047: Kanıt yolculuğu — aynı zincir, iki gösterim (2,5B SVG+CSS ve 3B three.js)

**Durum:** Deneme (karar bekliyor) · **Tarih:** 2026-09-13 · **Sıradaki:** kullanıcı iki görünümü inceleyip birini seçer; seçilmeyen kaldırılır

## Bağlam
Kanıt zinciri (cevaptaki sayı → tablo/SQL → Silver gözlemi → Bronze artifact → RAW kaynak)
harness'in en güçlü iddiası; panelde metin olarak duruyor. Kullanıcı bunu üç boyutlu ve
animatik bir karakterle göstermek istedi; iki tekniği görüp karar verecek.

## Karar (deneme)
1. **Tek veri modeli, iki görünüm.** `buildJourney(evidence, sayı)` kanıt panelinden düğüm
   listesi kurar (Cevap, Tablo·SQL, Silver, Bronze, RAW; web/OCR kaynağında tek "Belge/Sayfa"
   halkası). Her düğümün `ok` bayrağı var; ilk kopuk halkada karakter durur, halka kırmızı.
   Sayı çipine tıklamak yolculuğu o sayıdan başlatır. Zaman tek döngüden (`t`), iki görünüm
   aynı durumu çizer: bir görünüm kaldırılırsa veri kodu değişmez.
2. **2,5B: SVG + CSS.** İzometrik kutular, karakter "Smith" (ajanın maskotu) yol boyunca
   `requestAnimationFrame` ile yürür, bağlantılar sırayla yanar, altta konuşma balonu gerçek
   kanıtı yazar (SQL, gözlem, sha256, run id, HTTP). Kütüphane yok.
3. **3B: three.js (v0.170.0, MIT, yerel dosya `static/vendor/`).** Aynı düğümler kutu+kaide,
   karakter kapsül+küre, kamera kendiliğinden döner ve sürüklenir, aktif halka ışır; etiketler
   3B→2B izdüşümle HTML. CDN yok: demo çevrimdışı da çalışır (691 KB).
4. **Arayüz:** kanıt panelinde "Yolculuğu izle" düğmesi → pencere; sekmeler "2,5B · SVG + CSS"
   ve "3B · three.js"; Duraklat / Sonraki halka.

## Karar için ölçütler
Jüri projektöründe okunabilirlik (etiketler, balon), 10 saniyede anlaşılırlık, performans
(3B WebGL ister), dosya boyutu, freeze'e kalan süre. Öneri: 2,5B ana, 3B "orbit" seçenek;
kullanıcı karar verecek.
