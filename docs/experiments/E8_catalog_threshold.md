# E8 — katalog-prompt'ta eşiği

model: `kkbhackathon2026/Qwen3.8-27B` · sorgu sayısı: 50 · non-thinking, T=0

| N seri | prompt token | doğruluk | p50 s | p95 s | kategori kırılımı |
|---|---|---|---|---|---|
| 60 | 1989 | 98% | 0.27 | 0.29 | exact 5/5, abbrev 5/6, synonym 9/9, english 6/6, typo 4/4, misleading 10/10, natural 10/10 |

<details><summary>N=60 hatalar (1)</summary>

- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak)

</details>
| 200 | 6027 | 98% | 0.57 | 0.71 | exact 5/5, abbrev 5/6, synonym 9/9, english 6/6, typo 4/4, misleading 10/10, natural 10/10 |

<details><summary>N=200 hatalar (1)</summary>

- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak)

</details>
| 1000 | 27857 | 98% | 2.41 | 4.31 | exact 5/5, abbrev 5/6, synonym 9/9, english 6/6, typo 4/4, misleading 10/10, natural 10/10 |

<details><summary>N=1000 hatalar (1)</summary>

- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak)

</details>
| 3000 | 90854 | 92% | 10.88 | 12.86 | exact 5/5, abbrev 5/6, synonym 9/9, english 6/6, typo 4/4, misleading 8/10, natural 9/10 |

<details><summary>N=3000 hatalar (4)</summary>

- 'NPL' → syn:bddk:npl_orani (beklenen syn:bddk:takipteki_alacak)
- 'katılım bankaları konut finansmanı' → NONE (beklenen syn:bddk:katilim_konut)
- "İstanbul'daki konut kredileri" → syn:bddk:konut_kredi_bakiye (beklenen syn:bddk:finturk_istanbul_konut)
- 'kredi kartı borçları' → syn:fill:00000 (beklenen syn:bddk:kredi_karti_bakiye)

</details>
