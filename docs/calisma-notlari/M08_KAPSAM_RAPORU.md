# M08 — BDDK/EVDS kapsamı ve semantik hazır oluş: ölçüm raporu

**Tarih:** 14 Eylül 2026 · **ADR:** 0062 · **Veri:** `data/lakehouse.duckdb` (önceki 2021 demo DB `data_prev_2021demo/` adıyla korunuyor, silinmedi)

## 1. Zorunlu seri seti (T01, T02)

Katalogdan türetilir (kod listesi değil, `agent-core/scripts/build_demo_data.py required_series`): BDDK aylık + haftalık + FinTürk'ün tamamı ve birimi + ölçüm tipi tanımlı EVDS serileri.

| Kaynak | Seri | Frekans | Anlam |
|---|---|---|---|
| BDDK aylık bülten | 20 (bakiye + oran kalemleri) | aylık | birim, ölçüm tipi, toplama kuralı katalogda; 20'si `verified` |
| BDDK haftalık | 1 (konut) | haftalık | `verified` |
| BDDK FinTürk | 648 = 81 il × 8 ölçüm (konut, taşıt, diğer tüketici, KMH, kredi kartı, üç takipteki) | çeyreklik | Bin TL, stok, `verified` |
| EVDS | 12 (konut faizi, KFE, TÜFE 2025=100, TÜFE 2003=100, USD/EUR kur, politika faizi, AOFM, mevduat faizi, kart harcaması, M2, M3) | günlük…aylık | 10 `verified`, 2 `derived` (KFE ve eski TÜFE bazı doğrulanmamış) |
| **Toplam** | **681** | | Gold'a hazır 679 |

Keşif kataloğundaki 1.533 birimsiz EVDS serisi silinmedi; aranabilir, "tanımlı ama yüklü değil" diye cevaplanır (T03).

## 2. Kurulum (canlı, 14 Eylül gece)

| Adım | Sonuç |
|---|---|
| ingest | 681/681 (ok 10, uyarılı 104, aynı çekimi paylaşan 567, başarısız 0), 1.659 s; FinTürk 3.402 çeyrek isteği |
| EVDS günlük düzeltme | 3 seri × 11 pencere, 0 başarısız |
| silver | 46.830 satır aşamalandı, 3.000 sınır tekrarı tekilleşti, **43.830** yayımlandı, 681 seri |
| gold | 6 metrik, 126 aylık satır, 0 ret |
| provenance | 3.468 artifact, **117 run**, hepsi run'a bağlı; her Silver gözlemi run_id taşıyor |

## 3. Kapsam (T04): beklenen ↔ mevcut

| Kaynak | Seri | Gözlem | Başlangıç | Bitiş | Boşluklu seri |
|---|---|---|---|---|---|
| FinTürk | 648 | 27.216 (42 çeyrek × 648) | 2016-03-31 | 2026-06-30 | 0 |
| BDDK aylık | 20 | 2.417 | 2016-01 (4 kalem geç, aşağıda) | 2026-06 | 0 |
| BDDK haftalık | 1 | 547 | 2016-01-08 | 2026-06-26 | 0 |
| EVDS | 12 | 13.650 | 2016-01 | 2026-07-03 | 0 |

**Veri yokluğu (kaynak yayınlamıyor):** BDDK aylık `1676_Toplam`, `1688_Toplam`, `1717_Toplam` 2018-01'den, `1746_Rasyo` 2018-08'den başlıyor; istek 2016-01'den yapıldı ve kaynak daha eskisini döndürmedi.

**Erişim kırpılması (düzeltildi):** EVDS tek istekte en çok 1.000 gözlem döndürür ve fazlasını sessizce kırpar. Toplu betik günlük serileri tek pencereyle istediği için `TP.DK.USD.A.YTL` ve `TP.DK.EUR.A.YTL` 2023-10'dan, `TP.APIFON4` 2022-08'den başlamış göründü (tam 1.000 gözlem). Betik artık EVDS isteklerini ≤365 günlük pencerelere böler ve limit dolu yanıtı kırpılma sayıp indirmez (test). Yeniden çekimden sonra üçü de 2016-01'den.

**Anlamı belirsiz:** yok (zorunlu set anlamı tanımlı serilerden oluşuyor).

## 4. Mutabakat (T09)

81 ilin FinTürk konut kredisi toplamı (Bin TL → milyon TL) ile BDDK aylık bülten ulusal konut kredisi, çeyrek sonlarında:

| Ölçü | Değer |
|---|---|
| Karşılaştırılan çeyrek | 42 (2016-Q1 → 2026-Q2) |
| \|fark\| medyan | %0,013 |
| \|fark\| en çok | %0,19 (2016-Q1) |
| Son çeyrek | 801.440,8 ↔ 801.438 milyon TL (%0,000) |

İki farklı yayın (il tablosu ve ulusal bülten) aynı büyüklüğü tutarlı veriyor; fark kaynak yuvarlaması düzeyinde.

## 5. TÜFE ve KFE (T07, T08)

- `TP.TUKFIY2025.GENEL`: TÜFE 2025=100; kaynak 2016'dan itibaren aynı bazda veriyor. Katalog adı "Genel Endeks"ten "Tüketici Fiyat Endeksi (TÜFE, genel, 2025=100)"a küratörlendi (canlı prova bulgusu, ADR-0058); reel dönüşümün varsayılan endeksi.
- `TP.FG.J0`: TÜFE 2003=100 (`derived`: canlı kanıt var, Silver kapısı açık). 2025=100 ile birleştirilmez.
- `TP.KFE.TR`: KFE; baz yılı repoda doğrulanmadığı için `derived`. Tabloya eklenebilir, Gold'da yalnız açık rızayla.

## 6. Kalite bayrakları (gözlem)

Run kaydı sayesinde parser uyarıları artık Silver'a taşınıyor: BDDK kaynaklarının her kolonu "grid defaultValue 0 (yayınlanmamış değer sıfır görünebilir)" uyarısı taşıdığından 36.424 gözlemin 31.964'ü `source_warning`. Doğru (bayrak sessizce iyileştirilmiyor) ama gürültülü; ajan tablo sorgusunda `quality_flag` kolonu seçilmedikçe uyarı notu göstermiyor, kanıt panelinde görünüyor.

## 7. Açık

- T05: 12 ilden 81 ile geçildi (tamamı yüklü); harita için sınır dosyası lisansı kullanıcıdan (K09).
- T06: EVDS çeyreklik seriler zorunlu sette yok; bağlayıcı pencereleme ve frekans parametresiyle destekliyor, canlı çeyreklik yanıt bu turda ölçülmedi.
- T10: kaynak şema değişimi ve birim reddi mevcut testlerle (`tests/parsers/*` şema hataları, `silver/test_catalog_driven_adapter` birim reddi); "eksik ay" için yayın reddi testi yok — kapsam boşlukları bu raporda ölçüldü (0).
