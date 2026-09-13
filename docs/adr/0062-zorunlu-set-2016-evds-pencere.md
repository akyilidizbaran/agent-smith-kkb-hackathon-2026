# ADR-0062: Zorunlu 681 seri 2016'dan; EVDS pencereleme; demo veri kökü değişimi

**Durum:** Kabul edildi · **Tarih:** 2026-09-14 · **Milestone:** M08 · **Karar (K04):** 81 il, yüklü kapsam 2016-01'den

## Bağlam
Demo DB 127 seri, 12 il, 2021'den başlıyordu. Kullanıcı kararı: 81 il, 2016+, ağır seri setlerine verimli çözüm.

## Karar
1. Zorunlu set katalogdan türetilir: BDDK aylık/haftalık + FinTürk'ün tamamı + birimi ve ölçüm tipi tanımlı EVDS (681).
   `make demo-data` varsayılanı bu set (`--set demo` hızlı 127'lik set).
2. Kurulum ayrı köke yapıldı, ön kontrol "hazır" dedikten sonra `data/` ile yer değiştirildi: eski DB `data_prev_2021demo/`
   adıyla korunuyor (silme yok, geri almak için klasör adları geri çevrilir).
3. EVDS 1.000 gözlem sınırı: toplu betik EVDS isteklerini ≤365 günlük pencerelere böler; limit dolu yanıt kırpılma sayılır,
   indirilmez. Pencere sınırlarındaki aynı gözlemler Silver'da tekilleşir; farklı değer revizyon olarak kurulumu durdurur.
4. Kapsam, mutabakat ve kalite ölçümleri `docs/M08_KAPSAM_RAPORU.md`.

## Sonuçlar
681 seri, 43.830 gözlem, 117 run, 3.468 artifact, Gold 6. Kurulum süresi FinTürk'te 81 il × 42 çeyrek istek nedeniyle ~26 dk;
yeniden kurulum idempotent (aynı içerik yeniden indirilmez, yalnız yeni çeyrekler).
