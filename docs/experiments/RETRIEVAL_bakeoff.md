# Retrieval bake-off (küçük, sentetik katalog)

N=300 seri (REAL 60 + filler) · 50 el yazımı sorgu · BM25 stemmer'sız (Türkçe karakter normalize) · dense = Qwen3-Embedding-8B instruct'lı, cosine

| Sistem | R@1 | R@3 | R@5 | MRR | ms/sorgu |
|---|---|---|---|---|---|
| alias_exact | 0.60 | 0.64 | 0.64 | 0.61 | 7 |
| bm25 | 0.86 | 0.96 | 0.96 | 0.91 | 2 |
| dense_qwen3 | 0.88 | 0.96 | 0.98 | 0.92 | 28 |
| hybrid_rrf | 0.88 | 0.98 | 0.98 | 0.93 | 30 |
| hybrid_rrf+alias | 0.90 | 0.98 | 0.98 | 0.94 | 30 |

## Kategori kırılımı (R@3)

| Sistem | abbrev | english | exact | misleading | natural | synonym | typo |
|---|---|---|---|---|---|---|---|
| alias_exact | 6/6 | 6/6 | 4/5 | 6/10 | 0/10 | 8/9 | 2/4 |
| bm25 | 6/6 | 6/6 | 5/5 | 10/10 | 8/10 | 9/9 | 4/4 |
| dense_qwen3 | 6/6 | 5/6 | 5/5 | 10/10 | 9/10 | 9/9 | 4/4 |
| hybrid_rrf | 6/6 | 6/6 | 5/5 | 10/10 | 9/10 | 9/9 | 4/4 |
| hybrid_rrf+alias | 6/6 | 6/6 | 5/5 | 10/10 | 9/10 | 9/9 | 4/4 |

## Hatalar (R@3 dışı)

<details><summary>alias_exact: 18 hata</summary>

- 'konut kredisi bakiyesi' → [] (beklenen syn:bddk:konut_kredi_bakiye)
- 'batık krediler' → [] (beklenen syn:bddk:takipteki_alacak)
- 'konut kredsi bakiyesi' → [] (beklenen syn:bddk:konut_kredi_bakiye)
- 'politka faizi' → [] (beklenen syn:evds:politika_faizi)
- 'konut kredisi faizi' → [] (beklenen syn:evds:konut_kredi_faiz)
- 'katılım bankaları konut finansmanı' → [] (beklenen syn:bddk:katilim_konut)
- 'kamu bankaları konut kredisi' → [] (beklenen syn:bddk:kamu_konut)
- "İstanbul'daki konut kredileri" → [] (beklenen syn:bddk:finturk_istanbul_konut)
- 'bankaların özkaynağı ne kadar' → [] (beklenen syn:bddk:ozkaynak)
- 'kaç banka şubesi var' → [] (beklenen syn:bddk:sube_sayisi)
- "TCMB'nin döviz rezervi" → [] (beklenen syn:evds:rezerv)
- 'cari açık ne durumda' → [] (beklenen syn:evds:cari_denge)
- 'inşaat sektörüne verilen krediler' → [] (beklenen syn:bddk:sektorel_insaat)
- 'borsa endeksi kapanış' → [] (beklenen syn:bist:xu100)
- 'işletmelere verilen krediler' → [] (beklenen syn:bddk:ticari_kredi_bakiye)
- 'kredi kartı borçları' → [] (beklenen syn:bddk:kredi_karti_bakiye)
- 'kiralar ne kadar arttı' → [] (beklenen syn:evds:kira_endeksi)
- 'piyasanın enflasyon beklentisi' → [] (beklenen syn:evds:enflasyon_beklentisi)

</details>

<details><summary>bm25: 2 hata</summary>

- 'bankaların özkaynağı ne kadar' → ['syn:evds:mevduat_faizi', 'syn:bddk:personel_sayisi', 'syn:fill:00198'] (beklenen syn:bddk:ozkaynak)
- 'işletmelere verilen krediler' → ['syn:fill:00026', 'syn:fill:00023', 'syn:fill:00014'] (beklenen syn:bddk:ticari_kredi_bakiye)

</details>

<details><summary>dense_qwen3: 2 hata</summary>

- 'housing loans' → ['syn:evds:ipotekli_konut_satis', 'syn:bddk:konut_kredi_haftalik', 'syn:bddk:katilim_konut'] (beklenen syn:bddk:konut_kredi_bakiye)
- 'işletmelere verilen krediler' → ['syn:fill:00019', 'syn:fill:00022', 'syn:fill:00006'] (beklenen syn:bddk:ticari_kredi_bakiye)

</details>

<details><summary>hybrid_rrf: 1 hata</summary>

- 'işletmelere verilen krediler' → ['syn:fill:00026', 'syn:fill:00019', 'syn:fill:00023'] (beklenen syn:bddk:ticari_kredi_bakiye)

</details>

<details><summary>hybrid_rrf+alias: 1 hata</summary>

- 'işletmelere verilen krediler' → ['syn:fill:00026', 'syn:fill:00019', 'syn:fill:00023'] (beklenen syn:bddk:ticari_kredi_bakiye)

</details>

