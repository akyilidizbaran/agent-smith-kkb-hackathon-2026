# ADR-0040: Analitik ailesi — aykırılık, kırılma, öncül-ardıl; tespit araçta, anlatı modelde

**Durum:** Kabul edildi · **Tarih:** 2026-09-12 · **Sıradaki:** D7 görüntü/PDF girişi, D8 veri genişliği

## Bağlam
Yarışmanın asgari araç listesi altı ad sayıyor: Lakehouse, Web Search, Web URL, **Anomali,
Causality, Change Detection**. README bunları vadediyordu, `ARCHITECTURE.md` "planlı" diyordu,
kod yoktu. Kod inceleyen jüri için kötü sinyal; kullanıcı da "çok kötü görüntü" dedi.

İkinci sebep ölçülmüş: model sayısal girdi üzerinde kendi aritmetiğini yapınca uyduruyor
(ADR-0027; G9'da hâlâ 4/5). "Aykırı ay hangisi", "büyüme ne zaman değişti", "faiz krediyi
önden mi izliyor" sorularını modele bırakmak, tabloda olmayan sayı ve veride olmayan sebep
üretir. Mentörün çizgisi de aynı: tek orkestrasyon ajanı + deterministik katmanlar.

## Karar
`analytics/methods.py` (numpy + scipy, LLM yok) ve `tools/analytics.py` (üç araç, aktif tablo
üzerinde, veri türünden bağımsız):

| Araç | Yöntem | Tabloya |
|---|---|---|
| `anomaly_detect` | Tukey çiti (IQR, k=1.5) ya da z-skoru (|z|>3) | `<sütun>_anomali` ('ok'/'aykırı'), `<sütun>_skor`, gerekirse `_degisim_yuzde` |
| `change_points` | ikili bölütleme, parçalı sabit ortalama, ceza 2·log(n)·σ² | `<sütun>_rejim` (1..k) |
| `lead_lag` | gecikmeli Pearson (−k..+k) + iki yönlü Granger F-testi | tablo değişmez; kart |

**Taban kararı deterministik.** Spearman |rho|(sıra, değer) ≥ 0.8 ise seri trendli sayılır ve
yöntem dönemlik yüzde değişim üzerinde çalışır; aksi hâlde düzey. Ölçüldü: yükselen stok seride
düzey IQR'ı iki ucu "aykırı" sayıyor, değişim tabanı gerçek sıçramayı buluyor. Kullanıcı
`basis=level|change` ile zorlayabilir; kart hangi tabanın neden seçildiğini yazar.

**Ceza kalibrasyonu ölçüldü.** İlk sürüm σ'yı serinin kendi MAD'ından alıp 3·log(n) ile
çarpıyordu; 66 aylık konut serisinde gözle görülen rejimlerin hiçbirini bulmadı (gerçek
kaymalar gürültü sayılıp cezayı şişirdi). σ birinci farkların MAD'ından (kaymalardan
etkilenmez), ceza BIC ölçeğinde 2·log(n)·σ²: aynı seride dört rejim çıktı (aşağıda), saf
gürültüde kırılma yok, sentetik adımda tam yerinde.

**Sayı modelden değil karttan.** Sonuç sütunları "türetilmiş: anomali(…)" provenance'ı taşır,
kanıt zinciri kopmaz; kart tabloları (`aykırı dönemler`, `rejimler`, `gecikme`, `granger`)
workspace'e not edilir, kanıt paneli cevaptaki sayıyı orada bulur. Grafik `_anomali` sütununu
`quality_flag` gibi kırmızı halka ile işaretler.

**"Causality" dürüst.** `lead_lag` öncülük ölçer; kart "NEDENSELLİK DEĞİLDİR" der, "öncülük
ediyor / birlikte hareket ediyor" dedirtir; anlatı guard'ı (`causal_language`) "neden oldu"
yazılırsa yine geri çevirir. README'deki "nedensellik" kutusu "öncül-ardıl (Granger)" oldu.

**Harness.** Grafik kuralıyla aynı mekanizma genelleştirildi: soru aykırılık/kırılma/öncülük
içeriyor ve ilgili araç çağrılmadan cevap yazıldıysa bir kez geri gönderilir. Analitik kartları
veri üreten araç sayılır ("önce veriyi çek" uyarısı tetiklenmez).

**Golden'ın ortaya çıkardığı üç kaçak (ilk koşu 0/6):**
- *Kanıt paneli kart sayılarını tanımıyordu.* Model k=1,5, n=66, r=0,26, p=0,003 gibi kart
  değerlerini yazdı; panel "tabloda yok" dedi. Kart parametreleri artık workspace'e not edilir,
  satır sayısı ("124 hafta") ve işareti düşmüş sayı ("−2,31" Unicode eksi) eşleşir; r iki, p üç
  ondalıkla yazılır ki model kopyalasın. Sayı ayrıştırıcı tanımlayıcı içindeki rakamı
  (`bddk_weekly:5690_3`) ve "0.263" gibi sıfırlı ondalığı artık sayı/binlik sanmıyor.
- *Dönem ipucu "= 2021" diyordu.* "2021'den bu yana" aralıktır; ipucu artık ifadeye göre
  `>=`, `<=` ya da `BETWEEN` verir.
- *Model "aylık" soruya çeyreklik Gold tablosunu okudu* (22 satır, tutarlı ama soruya değil).
  Yeni politika `FREQUENCY_MISMATCH`: soru tek frekans söylüyor ve okunan her kaynak ondan
  kabaysa sorgu çalışmaz, adaylar istenen frekansta (BM25 sırasıyla) listelenir. İnceden kabaya
  (haftalıktan aylık) serbest, o Gold'un işi.

## Ölçüm (12 Eylül, demo DB, aylık konut kredisi bakiyesi 2021-01 → 2026-06, 66 ay)

- `anomaly_detect`: taban değişim (rho=0.99), normal aralık [−2,31 %, +5,37 %]; aykırı **2023-03
  (+6,49 %, skor 2,09)** ve **2023-05 (+5,42 %, 1,53)**.
- `change_points`: dört rejim — 2021-02→2023-02 ortalama %1,15/ay (25 ay), 2023-03→2023-08 %3,34
  (6), 2023-09→2024-09 %0,31 (13), 2024-10→2026-06 %2,62 (21); kırılmalar 2023-03, 2023-09, 2024-10.
- `lead_lag` (haftalık faiz → haftalık konut bakiyesi, 2024-01→2026-06, 124 ortak hafta, değişim
  tabanı): en güçlü gecikme +8 hafta, r = −0,28 (zayıf, ters yönlü); Granger faiz→bakiye F=3,22
  **p=0,003**, bakiye→faiz p=0,19. Kart bunu "faiz, bakiye artışını 8 hafta önden ve ters yönde
  izliyor; öncülük, nedensellik değil" diye verir.
- Birim testleri 270 → 287 (sentetik: sıçrama, trend, adım, gürültü, gecikme 2, Granger yönü;
  kanıt eşleşmeleri; frekans guard'ı).
- Golden G15–G17: §Golden (9/9). Demo kabul senaryoları 8 → 10 (G15, G17 eklendi).

## Golden (MIA Qwen3.8-27B, demo DB, 13 Eylül)

| Vaka | Soru | Sonuç | Adım | Prompt token |
|---|---|---|---|---|
| G15 aykırı ay | 2021–2026/06 aylık konut bakiyesinde olağandışı artış ayları | **3/3** | 2 | 47,5k |
| G16 kırılma | büyüme hızı ne zaman rejim değiştirdi | **3/3** | 4 (çeyreklik Gold denemesi → `FREQUENCY_MISMATCH` → aylık seri → `change_points`) | 59,5k |
| G17 öncülük | haftalık faiz haftalık bakiyeye öncülük ediyor mu (2024–2026/06) | **3/3** | 3 (sorgu → `workspace_add_column` → `lead_lag`) | 56,6k |

Üç koşu: 0/6 → 1/6 → **9/9**. Kanıt zinciri üçünde de tam. Demo kabul (10 senaryo, mevcut DB):
**10/10**, kanıt zinciri 10/10, G9 bu koşuda geçti. G16'da model her koşuda önce hazır
çeyreklik tabloya gidiyor; guard geri çeviriyor, iki adım onarım. Ön-yükleme kartlarında Gold
tablolarının önde gelmesi sebep olabilir; ölçülmedi, açık.

## Açık kalan
- `lead_lag` en güçlük gecikmeyi |r| maksimumuyla seçiyor; sınırdaki gecikme (±max_lag) kenar
  etkisi olabilir. Kart tüm gecikme tablosunu veriyor, kullanıcı görüyor.
- Mevsimsellik yok: aylık seride Ocak etkisi "aykırı" çıkabilir. STL/ay kuklası sonraki adım.
- Katkı ayrıştırması (il bazında waterfall) ve Gold `decompose` ile birleşik "fark" aracı
  stretch listesinde.
