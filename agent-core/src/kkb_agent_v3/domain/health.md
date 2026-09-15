# Sağlık alanı — boş şablon

Motor bu dosya boşken de çalışır; genericliğin kanıtı budur. Yeni bir alan için
aşağıdaki bölümler doldurulur, motor kodu değişmez.

## measure_rules

| semantic_type | allowed | forbidden | hint |
|---|---|---|---|
| count | last, sum, diff | - | Hasta/yatak sayısı gibi adet serileri. |
| ratio | recompute, pp_change | avg, sum | Doluluk oranı pay/payda ile yeniden hesaplanır. |
| flow | sum, avg, pct_change | last | Dönem içi başvuru/yatış sayıları toplanır. |

## evidence_domains

| domain | priority | note |
|---|---|---|
| saglik.gov.tr | 1 | Sağlık istatistikleri yıllığı |
| tuik.gov.tr | 1 | Nüfus ve sağlık verileri |

## note: örnek

(Buraya alanın tarihli notları yazılır. Boş bırakılabilir.)
