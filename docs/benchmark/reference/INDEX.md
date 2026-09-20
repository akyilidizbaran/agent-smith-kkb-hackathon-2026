# Bağımsız V2.1 oracle çıktıları — yerel veri

Bu klasör LLM anlatısı değil, `data/lakehouse.duckdb` üzerinden salt-okunur DuckDB sorgularıyla üretilen veya prompt içi fixture’dan hesaplanan oracle artifactlerini içerir. Güncel hash/satır/kolon kaydı `answers_v2_local.jsonl` içindedir; doğrulama için `agent-core/scripts/m02_benchmark/validate_contract_v2_1.py` çalıştırılır.

## Üretilen dosyalar

- **P01** `bddk_monthly:1539_Toplam` 2024-01-31 → 2024-12-31: 12 satır — 12 aylık ay sonu stok; birim TRY_mn. [P01 artifact](./P01_bireysel_kredi_karti_2024.csv)
- **P02** `bddk_monthly:334_NakdiKrediToplam` 2023-01-31 → 2024-12-31: 24 satır — 24 satır; stok + mutlak LAG değişimi. [P02 artifact](./P02_kobi_2023_2024.csv)
- **P06** `bddk_monthly:1904_Toplam` 2025-01-31 → 2026-06-30: 18 satır — Son mevcut gözlem 2026-06-30; 18 aylık pencere. [P06 artifact](./P06_ihracat_kredileri_last18.csv)
- **T01** `bddk_monthly:1357_Toplam` 2022-01-31 → 2024-12-31: 36 satır — Stok; toplam alınmaz; mutlak/yüzde değişim. [T01 artifact](./T01_total_deposit_2022_2024_changes.csv)
- **T03** `bddk_monthly:544_Rasyo` 2023-01–2024-12 endpoint comparison: 1 summary row — start/end ratio, percentage-point change and relative percent change are separate. [T03 artifact](./T03_npl_ratio_2023_2024.csv)
- **T05** `bddk_monthly:1357_Toplam + evds:TP.FG.J0` 2022-01-31 → 2025-12-31: 48 satır — TÜFE baz ayı 2022-01; nominal ve reel birlikte. [T05 artifact](./T05_real_total_deposit_2022_2025.csv)
- **P03** `bddk_monthly:1534_Toplam`: 2023 yazının üç ayını içeren 36 aylık geçerli pencereler; listelenen CSV kanonik örnektir, tek doğru değildir. [P03 artifact](./P03_konut_36ay_earliest_containing_2023_summer.csv)
- **R01** `bddk_monthly:1539_Toplam` parent ve `1541/1542` child 2024: 12 satır — child toplamı parent ile yuvarlama toleransında karşılaştırılır. [R01 artifact](./R01_kredi_karti_parent_child_2024.csv)
- **T06** `bddk_monthly:1534_Toplam` + `evds:TP.KTF12` monthly-average gold + `evds:TP.TUKFIY2025.GENEL`: 2021-01–2025-12, 60 rows. [T06 artifact](./T06_multiseries_alignment_2021_2025.csv)
- **R02** `meta.series` katalog adayları: 87 aktif “toplam kredi” eşleşmesi — kaynak/frekans/birim/ölçüm ve kapsam bilgisiyle. [R02 artifact](./R02_toplam_kredi_catalog_candidates.csv)
- **R04** FinTürk Ankara/Bursa/İzmir toplam mevduatları 2022–2024: 9 il-yıl satırı — quarterly stock değerlerinin yıllık aritmetik ortalaması; İstanbul dışarıda. [R04 artifact](./R04_finturk_ankara_bursa_izmir_annual_mean_2022_2024.csv)
- **R05** “Mortgage” alias çözümü: `bddk_monthly:1534_Toplam`, 2023 aylık: 12 satır. [R05 artifact](./R05_mortgage_alias_konut_2023.csv)
- **R06** BDDK toplam mevduat + EVDS TÜFE endeksi, 2022–2024: 36 satır ortak ay ekseni. [R06 artifact](./R06_deposit_plus_cpi_2022_2024.csv)
- **F02** Konut kredisi 2021–2024: stok, aylık fark ve yıllık yüzde değişim; pencere öncesi LAG tabanı korunur. [F02 artifact](./F02_konut_2021_2024_with_changes.csv)
- **F04** Üç kredi serisi 2021–2025 temiz kullanıcı projection’ı: 60 satır, 9 analiz kolonu. [F04 artifact](./F04_three_credit_series_clean_projection_2021_2025.csv)
- **F07** Konut kredisi 2020–2025: 2019-12 LAG tabanı ile 72 satır. [F07 artifact](./F07_konut_2020_2025_lag_base_retained.csv)
- **L01** Toplam krediler 2016–2025: 120 aylık satır. [L01 artifact](./L01_total_credit_120_months_2016_2025.csv)
- **L02** Beş kredi serisi 2020–2025: 15 analiz kolonu, 72 satır. [L02 artifact](./L02_five_credit_series_15col_2020_2025.csv)
- **L05** İhtiyaç + kredi kartı 60 aylık tablo ve özet. [L05 full artifact](./L05_two_stock_60m_full.csv), [L05 summary](./L05_two_stock_60m_summary.csv)
- **D05** Toplam mevduat change-point referansı (`basis=change`, `min_size=4`, `max_breaks=3`): 2021-11, 2022-03, 2024-01 kırılmaları. [D05 artifact](./D05_total_deposit_change_points_2021_2025.csv)
- **S03** Ay sonu konut kredisi + günlük politika faizi backward as-of join, 2024: 12 satır. [S03 artifact](./S03_asof_konut_credit_policy_rate_2024.csv)

- **Q04** Inline parent/child reconciliation: parent=100, children sum=100, residual=0. [Q04 artifact](./Q04_parent_child_reconciliation_inline.csv)
- **Q05** Inline null/zero adjacent-month changes: 4 rows; zero is a value, null breaks adjacent comparisons. [Q05 artifact](./Q05_null_zero_adjacent_month_changes.csv)
- **I08** Inline piecewise unit conversion: 500,000 thousand TRY=500 million TRY; next observation 600 million TRY; delta=100. [I08 artifact](./I08_temporal_unit_conversion_inline.csv)

- **F08** Three BDDK balance series, clean 2022–2024 projection: 36 rows. [F08 artifact](./F08_three_credit_series_clean_projection_2022_2024.csv)

- **L04** BDDK housing + Ankara FinTürk deposits + EVDS CPI: 20 exact quarter-end rows, 2021Q1–2025Q4. [L04 artifact](./L04_monthly_quarterly_common_period_2021_2025.csv)

- **P04** 16 quarter-end rows, BDDK deposits and total credit. [P04 artifact](./P04_bddk_quarter_end_deposit_credit_2021Q3_2025Q2.csv)

- **F01** 24-row preserved-series follow-up crop for 2022–2023. [F01 artifact](./F01_followup_crop_2022_2023.csv)

- **L03** 1,620 native-quarter rows for 81 provinces; per-capita series excluded. [L03 artifact](./L03_finturk_81_province_total_deposit_2021_2025_quarterly.csv)

## Veri kapsamı kontrolleri

- `bddk_monthly:1534_Toplam`: 2016-01-31 → 2026-06-30, 126 gözlem
- `bddk_monthly:1539_Toplam`: 2016-01-31 → 2026-06-30, 126 gözlem
- `bddk_monthly:334_NakdiKrediToplam`: 2021-01-31 → 2026-06-30, 66 gözlem
- `bddk_monthly:1357_Toplam`: 2016-01-31 → 2026-06-30, 126 gözlem
- `evds:TP.FG.J0`: 2016-01-31 → 2026-01-31, 121 gözlem
- `bddk_monthly:544_Rasyo`: 2016-01-31 → 2026-06-30, 126 gözlem

## Semantik sonuçlar

- `bddk_monthly:1357_Toplam` ve `1539_Toplam` stoktur; dönemleri toplamak yanlış olur.
- `bddk_monthly:334_NakdiKrediToplam` aylık stoktur; P02 değişimi önceki ay LAG ile hesaplanır.
- `evds:TP.FG.J0` endekstir; reel dönüşümde 2022-01 baz kabul edilmiştir.
- FinTürk il serileri quarterly ve TRY_th'tir; aylık 81 il × 60 dönem paneli doğal frekansta yoktur.
- Haftalık “takipteki alacak oranı” isteminde mevcut katalogdaki haftalık serilerin çoğu tutar/stoktur; oran serisi yoksa sistem netleştirmeli veya kapsam sınırını söylemelidir.
- R01 parent/child uzlaştırmasında kaynak değerleri yuvarlandığı için residual sıfıra yakın olmalıdır; bu veri setinde maksimum mutlak residual 1 milyon TL'dir ve yeniden toplama yapılmaz.

## Doğrudan sayı üretmemesi gereken yerel vakalar

- **P05:** Mevcut BDDK haftalık katalogda takipteki alacak tutarları/stokları vardır; aynı adla doğrulanmış haftalık oran serisi yoktur. Oran uydurulmamalı, kapsam açıklanmalıdır.
- **R03:** Mevcut aktif EVDS kataloğunda reel efektif döviz kuru eşleşmesi bulunamadı; benzer döviz kuru serisi sessizce seçilmemelidir.
- **T02/T07:** İstek, mevcut katalogdaki ölçüm türüyle çelişirse (ör. stok seriyi kümülatif akış sanmak veya kullandırım akışı yokken gecikmeli korelasyon istemek) sistem netleştirmeli ya da güvenli biçimde reddetmelidir.
