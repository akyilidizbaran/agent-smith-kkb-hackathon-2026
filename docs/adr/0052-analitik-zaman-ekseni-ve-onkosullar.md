# ADR-0052: Analitik araçlar zaman eksenini doğrular; gecikme sınırı; NaN/sonsuz/sabit; ön koşul dürüstlüğü

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Milestone:** M12

## Bağlam
Ölçüldü: 8 gözlem + `max_lag=24` → NumPy broadcast hatası; sırasız, tekrarlı ve düzensiz tarihli 8
satır doğrulamadan geçiyor; yöntem satır sırasını dönem sayıyor; sonsuz değer ve sabit seri için
davranış tanımsız; Granger kartı ön koşulları kontrol ediyormuş gibi okunabiliyor.

## Karar
1. **`validate_time_axis`** (üç araç ortak): tarih kolonu bulunur, satırlar zamana göre sıralanır
   (indeks etiketleri korunur; eklenen kolonlar aktif tabloya hizalanır, tablonun sırası bozulmaz),
   tekrar tarih / okunamayan tarih / boşluk / frekans (günlük … yıllık, düzensiz) raporlanır.
   Tarih yoksa "satır sırası dönem varsayıldı (doğrulanmadı)" kartta yazar.
2. **Tekrar tarihte hesap yok:** aynı dönemde birden çok satır (varlık kırılımı) → `INVALID_ARGS`,
   ipucu "önce tek seriye indir".
3. **Gecikme sınırı** `lag_cap`: her gecikmede en az 5 çift ve n/3; istenen aşıyorsa indirilir ve
   kartta "max_lag 24 → 2" yazar; hata yok.
4. **NaN/±sonsuz/sabit:** sonsuz boş sayılır ve kartta söylenir; sabit seri üç araçta reddedilir.
5. **Kart bilgisi:** frekans, "k ay/hafta" dönem sözcüğü, n, yön, boşluk/düzensizlik notları; kırılma
   kartında min segment / en çok kırılma / ceza; Granger satırında "ön koşullar (durağanlık, gecikme
   seçimi, çoklu deneme) KONTROL EDİLMEDİ, sonuç betimseldir".

## Sonuçlar
- Testler A15, A16, A29 (`tests/test_m12_zaman_ekseni.py`); 344 → 348.
- Açık: M12-T03 çok varlıklı seride otomatik kırılım seçimi (şimdi ret + ipucu), T06 gerçek veriyle
  bilinen aykırılık kabulü (A32/A33 fikstürleri M16'da), T09 durağanlık dönüşümü (uygulanmadı, söyleniyor).
