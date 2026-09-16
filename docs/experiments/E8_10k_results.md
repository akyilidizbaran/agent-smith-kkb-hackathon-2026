# E8-10k — geçiş modu EVDS ölçeğinde (katalog modeli v2: kavram başına ≤48 varyant + ilgisiz filler)

model: `kkbhackathon2026/Qwen3.8-27B` · max_model_len: bilinmiyor · sorgu: 50 standart + 20 hard_variant · K=30, grouped G=8×V=4 · non-thinking, T=0

| N seri | kol | R@K (retrieval tavanı) | uçtan uca doğruluk | prompt token | p50 s | p95 s | kırılım |
|---|---|---|---|---|---|---|---|
| 3000 | bm25 | 96% | 90% | 1172 | 0.18 | 0.25 | exact 5/5, abbrev 5/6, synonym 6/9, english 5/6, typo 4/4, misleading 10/10, natural 8/10, hard_variant 20/20 |

<details><summary>N=3000 bm25 hatalar (7)</summary>

- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da var)
- 'mortgage bakiyesi' → syn:var:000008 (beklenen syn:bddk:konut_kredi_bakiye; top-K'da YOK)
- 'enflasyon' → syn:evds:enflasyon_beklentisi (beklenen syn:evds:tufe; top-K'da var)
- 'batık krediler' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da var)
- 'housing loans' → syn:bddk:konut_kredi_haftalik (beklenen syn:bddk:konut_kredi_bakiye; top-K'da var)
- 'bankaların özkaynağı ne kadar' → NONE (beklenen syn:bddk:ozkaynak; top-K'da YOK)
- 'işletmelere verilen krediler' → syn:fill:00000 (beklenen syn:bddk:ticari_kredi_bakiye; top-K'da YOK)

</details>

| 3000 | grouped | 96% | 93% | 934 | 0.18 | 0.23 | exact 5/5, abbrev 5/6, synonym 8/9, english 6/6, typo 4/4, misleading 10/10, natural 8/10, hard_variant 19/20 |

<details><summary>N=3000 grouped hatalar (5)</summary>

- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da var)
- 'batık krediler' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da var)
- 'bankaların özkaynağı ne kadar' → NONE (beklenen syn:bddk:ozkaynak; top-K'da YOK)
- 'işletmelere verilen krediler' → NONE (beklenen syn:bddk:ticari_kredi_bakiye; top-K'da YOK)
- 'katılım bankaları mevduat' → NONE (beklenen syn:var:000278; top-K'da YOK)

</details>

| 10000 | bm25 | 96% | 90% | 1139 | 0.18 | 0.27 | exact 5/5, abbrev 5/6, synonym 6/9, english 5/6, typo 4/4, misleading 10/10, natural 8/10, hard_variant 20/20 |

<details><summary>N=10000 bm25 hatalar (7)</summary>

- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da var)
- 'mortgage bakiyesi' → syn:var:000008 (beklenen syn:bddk:konut_kredi_bakiye; top-K'da YOK)
- 'enflasyon' → syn:evds:enflasyon_beklentisi (beklenen syn:evds:tufe; top-K'da var)
- 'batık krediler' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da var)
- 'housing loans' → syn:bddk:konut_kredi_haftalik (beklenen syn:bddk:konut_kredi_bakiye; top-K'da var)
- 'bankaların özkaynağı ne kadar' → NONE (beklenen syn:bddk:ozkaynak; top-K'da YOK)
- 'işletmelere verilen krediler' → NONE (beklenen syn:bddk:ticari_kredi_bakiye; top-K'da YOK)

</details>

| 10000 | grouped | 96% | 91% | 936 | 0.18 | 0.20 | exact 5/5, abbrev 5/6, synonym 8/9, english 5/6, typo 4/4, misleading 10/10, natural 8/10, hard_variant 19/20 |

<details><summary>N=10000 grouped hatalar (6)</summary>

- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da var)
- 'batık krediler' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da var)
- 'housing loans' → syn:bddk:konut_kredi_haftalik (beklenen syn:bddk:konut_kredi_bakiye; top-K'da var)
- 'bankaların özkaynağı ne kadar' → NONE (beklenen syn:bddk:ozkaynak; top-K'da YOK)
- 'işletmelere verilen krediler' → NONE (beklenen syn:bddk:ticari_kredi_bakiye; top-K'da YOK)
- 'TP döviz mevduatı' → syn:bddk:yp_mevduat (beklenen syn:var:000343; top-K'da YOK)

</details>

| 30000 | bm25 | 96% | 90% | 1152 | 0.18 | 0.19 | exact 5/5, abbrev 5/6, synonym 7/9, english 5/6, typo 4/4, misleading 10/10, natural 8/10, hard_variant 19/20 |

<details><summary>N=30000 bm25 hatalar (7)</summary>

- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da var)
- 'mortgage bakiyesi' → syn:var:000008 (beklenen syn:bddk:konut_kredi_bakiye; top-K'da YOK)
- 'enflasyon' → syn:evds:enflasyon_beklentisi (beklenen syn:evds:tufe; top-K'da var)
- 'housing loans' → syn:bddk:konut_kredi_haftalik (beklenen syn:bddk:konut_kredi_bakiye; top-K'da var)
- 'bankaların özkaynağı ne kadar' → NONE (beklenen syn:bddk:ozkaynak; top-K'da YOK)
- 'işletmelere verilen krediler' → NONE (beklenen syn:bddk:ticari_kredi_bakiye; top-K'da YOK)
- 'weekly NPL' → syn:var:000263 (beklenen syn:var:000261; top-K'da var)

</details>

| 30000 | grouped | 97% | 91% | 954 | 0.19 | 0.26 | exact 5/5, abbrev 5/6, synonym 7/9, english 6/6, typo 4/4, misleading 10/10, natural 8/10, hard_variant 19/20 |

<details><summary>N=30000 grouped hatalar (6)</summary>

- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da var)
- 'enflasyon' → syn:evds:enflasyon_beklentisi (beklenen syn:evds:tufe; top-K'da var)
- 'batık krediler' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da var)
- 'bankaların özkaynağı ne kadar' → NONE (beklenen syn:bddk:ozkaynak; top-K'da YOK)
- 'işletmelere verilen krediler' → NONE (beklenen syn:bddk:ticari_kredi_bakiye; top-K'da YOK)
- 'weekly NPL' → syn:var:000263 (beklenen syn:var:000261; top-K'da var)

</details>

