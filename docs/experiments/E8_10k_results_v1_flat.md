# E8-10k — geçiş modu (BM25 top-30 → model) EVDS ölçeğinde

model: `kkbhackathon2026/Qwen3.8-27B` · max_model_len: bilinmiyor · sorgu: 50 standart + 20 hard_variant · non-thinking, T=0

| N seri | kol | R@K (retrieval tavanı) | uçtan uca doğruluk | prompt token | p50 s | p95 s | kırılım |
|---|---|---|---|---|---|---|---|
| 3000 | bm25 | 83% | 63% | 1228 | 0.21 | 0.23 | exact 4/5, abbrev 5/6, synonym 3/9, english 5/6, typo 4/4, misleading 9/10, natural 7/10, hard_variant 7/20 |

<details><summary>N=3000 bm25 hatalar (26)</summary>

- 'takipteki alacaklar oranı' → syn:var:000733 (beklenen syn:bddk:npl_orani; top-K'da YOK)
- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da YOK)
- 'mortgage bakiyesi' → syn:var:000720 (beklenen syn:bddk:konut_kredi_bakiye; top-K'da YOK)
- 'ev kredisi faizi' → syn:var:000181 (beklenen syn:evds:konut_kredi_faiz; top-K'da YOK)
- 'enflasyon' → syn:evds:enflasyon_beklentisi (beklenen syn:evds:tufe; top-K'da YOK)
- 'batık krediler' → syn:var:000732 (beklenen syn:bddk:takipteki_alacak; top-K'da YOK)
- 'döviz mevduatı' → syn:var:002536 (beklenen syn:bddk:yp_mevduat; top-K'da YOK)
- 'banka kârı' → syn:var:000757 (beklenen syn:bddk:net_kar; top-K'da YOK)
- 'housing loans' → syn:bddk:konut_kredi_haftalik (beklenen syn:bddk:konut_kredi_bakiye; top-K'da YOK)
- "İstanbul'daki konut kredileri" → syn:var:000118 (beklenen syn:bddk:finturk_istanbul_konut; top-K'da var)
- 'bankaların özkaynağı ne kadar' → NONE (beklenen syn:bddk:ozkaynak; top-K'da YOK)
- "TCMB'nin döviz rezervi" → syn:var:002544 (beklenen syn:evds:rezerv; top-K'da YOK)
- 'kiralar ne kadar arttı' → syn:var:000234 (beklenen syn:evds:kira_endeksi; top-K'da YOK)
- 'Adana SYR' → NONE (beklenen syn:var:001598; top-K'da var)
- 'YP ticari faiz' → syn:var:000438 (beklenen syn:var:001338; top-K'da var)
- 'Ankara konut kredisi' → syn:var:000419 (beklenen syn:var:000899; top-K'da var)
- 'YP yabancı banka konut kredisi' → syn:bddk:yabanci_konut (beklenen syn:var:001364; top-K'da var)
- 'mevduat bankaları kredi kartı borcu' → syn:var:001811 (beklenen syn:var:000011; top-K'da var)
- 'Bursa KKDF' → NONE (beklenen syn:var:001012; top-K'da var)
- 'monthly kredili konut satışı' → syn:evds:ipotekli_konut_satis (beklenen syn:var:000214; top-K'da var)
- 'YP enflasyon beklentisi' → syn:var:001377 (beklenen syn:var:002277; top-K'da var)
- 'monthly ihtiyaç faizi' → syn:var:000199 (beklenen syn:var:001399; top-K'da var)
- 'quarterly Türk lirası mevduat' → syn:var:000795 (beklenen syn:var:001995; top-K'da var)
- 'monthly kamu bankası konut kredisi' → syn:bddk:kamu_konut (beklenen syn:var:002623; top-K'da var)
- 'YP özkaynak' → syn:var:002256 (beklenen syn:var:001356; top-K'da var)
- 'bireysel krediler' → syn:bddk:tuketici_kredi_bakiye (beklenen syn:var:001746; top-K'da var)

</details>

| 10000 | bm25 | 77% | 56% | 1239 | 0.22 | 1.05 | exact 4/5, abbrev 5/6, synonym 2/9, english 5/6, typo 4/4, misleading 9/10, natural 7/10, hard_variant 3/20 |

<details><summary>N=10000 bm25 hatalar (31)</summary>

- 'takipteki alacaklar oranı' → syn:var:000253 (beklenen syn:bddk:npl_orani; top-K'da YOK)
- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da YOK)
- 'mortgage bakiyesi' → syn:var:000240 (beklenen syn:bddk:konut_kredi_bakiye; top-K'da YOK)
- 'ev kredisi faizi' → syn:var:001081 (beklenen syn:evds:konut_kredi_faiz; top-K'da YOK)
- 'enflasyon' → syn:evds:enflasyon_beklentisi (beklenen syn:evds:tufe; top-K'da YOK)
- 'batık krediler' → syn:var:002532 (beklenen syn:bddk:takipteki_alacak; top-K'da YOK)
- 'araba kredisi' → syn:var:004987 (beklenen syn:bddk:tasit_kredi_bakiye; top-K'da YOK)
- 'döviz mevduatı' → syn:var:000856 (beklenen syn:bddk:yp_mevduat; top-K'da YOK)
- 'banka kârı' → syn:var:005257 (beklenen syn:bddk:net_kar; top-K'da YOK)
- 'housing loans' → syn:var:001725 (beklenen syn:bddk:konut_kredi_bakiye; top-K'da YOK)
- 'kamu bankaları konut kredisi' → syn:var:000643 (beklenen syn:bddk:kamu_konut; top-K'da YOK)
- 'bankaların özkaynağı ne kadar' → NONE (beklenen syn:bddk:ozkaynak; top-K'da YOK)
- "TCMB'nin döviz rezervi" → syn:var:000744 (beklenen syn:evds:rezerv; top-K'da YOK)
- 'kiralar ne kadar arttı' → syn:var:006174 (beklenen syn:evds:kira_endeksi; top-K'da YOK)
- 'toplam kamu bankası konut kredisi' → syn:bddk:kamu_konut (beklenen syn:var:007063; top-K'da var)
- 'TP inşaat kredileri' → syn:bddk:sektorel_insaat (beklenen syn:var:003766; top-K'da var)
- 'monthly kredili konut satışı' → syn:var:000274 (beklenen syn:var:003814; top-K'da YOK)
- 'mevduat bankaları M2' → syn:evds:m2 (beklenen syn:var:000025; top-K'da var)
- 'kamu bankaları mortgage bakiyesi' → syn:bddk:kamu_konut (beklenen syn:var:004200; top-K'da var)
- 'Gaziantep ithalat' → syn:var:008188 (beklenen syn:var:002188; top-K'da var)
- 'SYR' → syn:bddk:syr (beklenen syn:var:005978; top-K'da var)
- 'araba kredisi' → syn:var:004987 (beklenen syn:var:000247; top-K'da YOK)
- 'Kocaeli KKDF' → syn:var:002512 (beklenen syn:var:008512; top-K'da var)
- 'TP brüt rezerv' → syn:evds:rezerv (beklenen syn:var:006444; top-K'da var)
- 'YP ticari faiz' → syn:var:004038 (beklenen syn:var:004938; top-K'da var)
- 'TP Türk lirası mevduat' → syn:bddk:tl_mevduat (beklenen syn:var:001935; top-K'da var)
- 'kredi kartı borcu' → syn:bddk:kredi_karti_bakiye (beklenen syn:var:004151; top-K'da var)
- 'yerli özel bankalar ticari kredi' → syn:var:009910 (beklenen syn:var:002710; top-K'da var)
- 'daily haftalık konut kredisi' → syn:var:001125 (beklenen syn:var:008325; top-K'da var)
- 'Kayseri ihtiyaç kredisi' → syn:var:009068 (beklenen syn:var:003068; top-K'da var)
- 'monthly cari açık' → syn:evds:cari_denge (beklenen syn:var:002606; top-K'da var)

</details>

| 30000 | bm25 | 69% | 49% | 1222 | 0.22 | 0.67 | exact 4/5, abbrev 4/6, synonym 2/9, english 5/6, typo 4/4, misleading 8/10, natural 7/10, hard_variant 0/20 |

<details><summary>N=30000 bm25 hatalar (36)</summary>

- 'takipteki alacaklar oranı' → syn:var:000853 (beklenen syn:bddk:npl_orani; top-K'da YOK)
- 'KFE' → syn:var:000242 (beklenen syn:evds:kfe; top-K'da YOK)
- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak; top-K'da YOK)
- 'mortgage bakiyesi' → syn:var:000240 (beklenen syn:bddk:konut_kredi_bakiye; top-K'da YOK)
- 'ev kredisi faizi' → syn:var:001621 (beklenen syn:evds:konut_kredi_faiz; top-K'da YOK)
- 'enflasyon' → syn:evds:enflasyon_beklentisi (beklenen syn:evds:tufe; top-K'da YOK)
- 'batık krediler' → syn:var:021432 (beklenen syn:bddk:takipteki_alacak; top-K'da YOK)
- 'araba kredisi' → syn:var:004327 (beklenen syn:bddk:tasit_kredi_bakiye; top-K'da YOK)
- 'döviz mevduatı' → syn:var:000256 (beklenen syn:bddk:yp_mevduat; top-K'da YOK)
- 'banka kârı' → syn:var:000217 (beklenen syn:bddk:net_kar; top-K'da YOK)
- 'housing loans' → syn:var:000525 (beklenen syn:bddk:konut_kredi_bakiye; top-K'da YOK)
- 'katılım bankaları konut finansmanı' → syn:var:000342 (beklenen syn:bddk:katilim_konut; top-K'da YOK)
- 'kamu bankaları konut kredisi' → syn:var:000643 (beklenen syn:bddk:kamu_konut; top-K'da YOK)
- 'bankaların özkaynağı ne kadar' → NONE (beklenen syn:bddk:ozkaynak; top-K'da YOK)
- "TCMB'nin döviz rezervi" → syn:var:000744 (beklenen syn:evds:rezerv; top-K'da YOK)
- 'kiralar ne kadar arttı' → syn:var:008634 (beklenen syn:evds:kira_endeksi; top-K'da YOK)
- 'monthly işsizlik' → syn:evds:issizlik (beklenen syn:var:014609; top-K'da YOK)
- 'kamu bankaları şube adedi' → syn:var:016840 (beklenen syn:var:011440; top-K'da var)
- 'quarterly TÜFE' → syn:var:016383 (beklenen syn:var:018783; top-K'da var)
- 'katılım konut' → syn:bddk:katilim_konut (beklenen syn:var:024582; top-K'da YOK)
- 'dolar kuru' → syn:evds:usd_try (beklenen syn:var:021861; top-K'da var)
- 'yerli özel bankalar REK' → syn:var:011756 (beklenen syn:var:029756; top-K'da var)
- 'KKO' → syn:var:000271 (beklenen syn:var:020971; top-K'da YOK)
- 'Denizli kredi mevduat oranı' → syn:var:003699 (beklenen syn:var:021699; top-K'da var)
- 'Adana politika faizi' → syn:var:013565 (beklenen syn:var:019565; top-K'da var)
- 'kamu bankaları ev satışları' → syn:var:000633 (beklenen syn:var:015033; top-K'da var)
- 'mevduat faizi' → syn:evds:mevduat_faizi (beklenen syn:var:009857; top-K'da YOK)
- 'quarterly ihtiyaç faizi' → syn:var:029599 (beklenen syn:var:005599; top-K'da var)
- 'Manisa mortgage faizi' → syn:var:023761 (beklenen syn:var:005761; top-K'da var)
- 'katılım bankaları enerji kredileri' → syn:var:027348 (beklenen syn:var:023748; top-K'da var)
- 'YP NPL' → syn:var:009433 (beklenen syn:var:022032; top-K'da var)
- 'mevduat' → syn:bddk:toplam_mevduat (beklenen syn:var:006554; top-K'da YOK)
- 'Adana euro kuru' → syn:var:013582 (beklenen syn:var:001582; top-K'da var)
- 'monthly bireysel krediler' → syn:bddk:tuketici_kredi_bakiye (beklenen syn:var:016986; top-K'da YOK)
- 'Ankara ÜFE' → syn:evds:ufe (beklenen syn:var:024364; top-K'da var)
- 'weekly haftalık konut kredisi' → syn:bddk:konut_kredi_haftalik (beklenen syn:var:002925; top-K'da var)

</details>

