# UEB sonucu — after_rerun

## Özet

| ölçüt | değer |
|---|---:|
| n | 3 |
| guarded | 0 |
| safe | 0 |
| partial | 0 |
| silent | 0 |
| silent_rate | 0.0 |
| severity_weighted_silent_rate | 0.0 |
| controls | 3 |
| control_pass | 2 |
| overblock | 0 |
| control_wrong | 1 |
| mean_duration_s | 7.7 |

## Vakalar

| id | beklenen | karar | tablo | tespit | yanlış | süre | araçlar | cevap (ilk 220) |
|---|---|---|---|---|---|---:|---|---|
| A24_cok_tur_niyet | answer | **MISS** | evet | yer alm, değil |  | 15.2 | lakehouse_query | 2024 yılı aylık ihtiyaç kredisi bakiyeleri (BDDK Aylık Bülten, sektör toplamı, ay sonu stok, milyon TL):  / Dönem / Bakiye (milyon TL) / /---/---/ / Ocak 2024 / 1.006.160 / / Şubat 2024 / 1.049.444 / / Mart 2024 / 1.090. |
| D01_ingilizce_alias | answer | **PASS** | evet | değil |  | 4.2 | lakehouse_query | Aralık 2025 sonu itibarıyla konut (mortgage) kredi bakiyesi **678.970 milyon TL** (BDDK Aylık Bülten, "Tüketici Kredileri - Konut" kalemi, sektör toplamı).  Bunu para cinsi kırılımıyla: - Türk parası (TL): 678.912 milyon |
| D02_iso_buyuk_harf | answer | **PASS** | evet | değil |  | 3.6 | lakehouse_query | **Konut Kredisi Bakiyesi — Aralık 2025** (BDDK Aylık Bülten, sektör toplamı):  / Gösterge / Tutar / /---/---/ / Türk Parası (TP) / 678.912 milyon TL / / Yabancı Para (YP) / 58 milyon TL / / **Toplam** / **678.970 milyon  |