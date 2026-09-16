# Blok C — harness konfigürasyon deneyleri (golden set)

repeat=2 · vaka=7 · model=kkbhackathon2026/Qwen3.8-27B

| Konfig | pass^k | ort. s/vaka | ort. araç adımı | ort. LLM turu | ort. token | grounding (gölge) |
|---|---|---|---|---|---|---|
| baseline | 7/7 vaka (koşu 14/14) | 6.9 | 5.6 | 6.9 | 29887 | 6/14 temiz |
| preload | 7/7 vaka (koşu 14/14) | 5.3 | 2.6 | 3.9 | 22389 | 10/14 temiz |
| parallel | 6/7 vaka (koşu 12/14) | 8.5 | 5.7 | 7.0 | 30674 | 12/14 temiz |
| preload+parallel | 7/7 vaka (koşu 14/14) | 6.9 | 2.3 | 3.6 | 20612 | 5/14 temiz |
| preload+parallel+short | 7/7 vaka (koşu 14/14) | 3.3 | 1.4 | 2.9 | 15761 | 6/14 temiz |
| preload+parallel+ground | 7/7 vaka (koşu 14/14) | 8.2 | 3.4 | 5.4 | 34021 | 14/14 temiz |
| preload+parallel+escalate | 7/7 vaka (koşu 14/14) | 4.7 | 2.3 | 3.6 | 20604 | 6/14 temiz |

<details><summary>baseline ayrıntı</summary>

```json
{
 "G1_tek_deger": {
  "passed": 2,
  "runs": 2,
  "secs": [
   4.8,
   4.1
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   5,
   5
  ],
  "tokens": [
   20001,
   19988
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G2_aylik_seri": {
  "passed": 2,
  "runs": 2,
  "secs": [
   5.5,
   5.3
  ],
  "steps": [
   5,
   5
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   25810,
   25759
  ],
  "fails": [],
  "ground": [
   "MISS:155.515",
   "OK"
  ]
 },
 "G3_turetilmis_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   7.0,
   5.8
  ],
  "steps": [
   5,
   5
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   26323,
   26311
  ],
  "fails": [],
  "ground": [
   "MISS:155.515",
   "MISS:155.515"
  ]
 },
 "G4_kapsam_disi": {
  "passed": 2,
  "runs": 2,
  "secs": [
   4.4,
   4.5
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   24517,
   24517
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G5_karsilastirma": {
  "passed": 2,
  "runs": 2,
  "secs": [
   6.5,
   6.5
  ],
  "steps": [
   5,
   5
  ],
  "turns": [
   5,
   5
  ],
  "tokens": [
   21596,
   21596
  ],
  "fails": [],
  "ground": [
   "MISS:682.410, 2.149.876, 2,8, 3,1, 2,80, 3,15",
   "MISS:682.410, 2.149.876, 2,8, 3,1, 2,80, 3,15"
  ]
 },
 "G7_tablo_uzerinde_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   9.3,
   9.0
  ],
  "steps": [
   7,
   7
  ],
  "turns": [
   9,
   9
  ],
  "tokens": [
   38215,
   38135
  ],
  "fails": [],
  "ground": [
   "OK | MISS:2,21, 2,50, 2,44, 2,43, 1,36, 1,94, 2,37, 2,48, 2,95, 2,59, 3,07",
   "MISS:155.515 | MISS:2,21, 2,50, 2,44, 2,43, 1,36, 1,94, 2,37, 2,48, 2,95, 2,59, 3,07"
  ]
 },
 "G6_tabloyu_bozmadan": {
  "passed": 2,
  "runs": 2,
  "secs": [
   11.5,
   11.9
  ],
  "steps": [
   9,
   10
  ],
  "turns": [
   11,
   12
  ],
  "tokens": [
   49783,
   55871
  ],
  "fails": [],
  "ground": [
   "MISS:155.515 | MISS:57.882, 56.315, 54.902, 53.640, 52.518, 51.480",
   "MISS:155.515 | OK"
  ]
 }
}
```
</details>

<details><summary>preload ayrıntı</summary>

```json
{
 "G1_tek_deger": {
  "passed": 2,
  "runs": 2,
  "secs": [
   2.0,
   1.9
  ],
  "steps": [
   1,
   1
  ],
  "turns": [
   2,
   2
  ],
  "tokens": [
   10399,
   10408
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G2_aylik_seri": {
  "passed": 2,
  "runs": 2,
  "secs": [
   3.8,
   3.7
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   3,
   3
  ],
  "tokens": [
   16722,
   16722
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G3_turetilmis_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   4.3,
   4.3
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   3,
   3
  ],
  "tokens": [
   17221,
   17221
  ],
  "fails": [],
  "ground": [
   "MISS:155.515",
   "MISS:155.515"
  ]
 },
 "G4_kapsam_disi": {
  "passed": 2,
  "runs": 2,
  "secs": [
   3.0,
   3.0
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   3,
   3
  ],
  "tokens": [
   15694,
   15694
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G5_karsilastirma": {
  "passed": 2,
  "runs": 2,
  "secs": [
   8.3,
   8.3
  ],
  "steps": [
   3,
   3
  ],
  "turns": [
   4,
   4
  ],
  "tokens": [
   26293,
   26293
  ],
  "fails": [],
  "ground": [
   "MISS:2,80, 2,83, 2,84, 2,89, 2,92, 3,02, 3,04, 3,10, 3,12, 3,16, 3,25, 2,8, 3,3, 29,7, 50,5",
   "MISS:2,80, 2,83, 2,84, 2,89, 2,92, 3,02, 3,04, 3,10, 3,12, 3,16, 3,25, 2,8, 3,3, 29,7, 50,5"
  ]
 },
 "G7_tablo_uzerinde_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   7.7,
   7.7
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   35051,
   35051
  ],
  "fails": [],
  "ground": [
   "OK | MISS:2,21, 2,50, 2,44, 2,43, 1,36, 1,94, 2,37, 2,48, 2,95, 2,59, 3,07",
   "OK | MISS:2,21, 2,50, 2,44, 2,43, 1,36, 1,94, 2,37, 2,48, 2,95, 2,59, 3,07"
  ]
 },
 "G6_tabloyu_bozmadan": {
  "passed": 2,
  "runs": 2,
  "secs": [
   8.3,
   8.2
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   35340,
   35340
  ],
  "fails": [],
  "ground": [
   "OK | OK",
   "OK | OK"
  ]
 }
}
```
</details>

<details><summary>parallel ayrıntı</summary>

```json
{
 "G1_tek_deger": {
  "passed": 2,
  "runs": 2,
  "secs": [
   3.6,
   3.7
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   5,
   5
  ],
  "tokens": [
   20315,
   20315
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G2_aylik_seri": {
  "passed": 2,
  "runs": 2,
  "secs": [
   10.0,
   5.0
  ],
  "steps": [
   5,
   5
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   26118,
   26118
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G3_turetilmis_hesap": {
  "passed": 0,
  "runs": 2,
  "secs": [
   7.1,
   9.5
  ],
  "steps": [
   5,
   5
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   26742,
   26729
  ],
  "fails": [
   "tablo kontrolü başarısız: 12 satır",
   "tablo kontrolü başarısız: 12 satır"
  ],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G4_kapsam_disi": {
  "passed": 2,
  "runs": 2,
  "secs": [
   12.0,
   8.7
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   24847,
   24841
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G5_karsilastirma": {
  "passed": 2,
  "runs": 2,
  "secs": [
   11.6,
   7.0
  ],
  "steps": [
   5,
   5
  ],
  "turns": [
   5,
   5
  ],
  "tokens": [
   21833,
   21833
  ],
  "fails": [],
  "ground": [
   "MISS:2.160.903, 30,4, 47,2",
   "MISS:2.160.903, 30,4, 47,2"
  ]
 },
 "G7_tablo_uzerinde_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   10.2,
   8.9
  ],
  "steps": [
   7,
   7
  ],
  "turns": [
   9,
   9
  ],
  "tokens": [
   38789,
   38691
  ],
  "fails": [],
  "ground": [
   "OK | MISS:2,21, 2,50, 2,44, 2,43, 1,36, 1,94, 2,37, 2,48, 2,95, 2,59, 3,07",
   "OK | MISS:2,21, 2,50, 2,44, 2,43, 1,36, 1,94, 2,37, 2,48, 2,95, 2,59, 3,07"
  ]
 },
 "G6_tabloyu_bozmadan": {
  "passed": 2,
  "runs": 2,
  "secs": [
   10.9,
   10.9
  ],
  "steps": [
   10,
   10
  ],
  "turns": [
   12,
   12
  ],
  "tokens": [
   56130,
   56130
  ],
  "fails": [],
  "ground": [
   "OK | OK",
   "OK | OK"
  ]
 }
}
```
</details>

<details><summary>preload+parallel ayrıntı</summary>

```json
{
 "G1_tek_deger": {
  "passed": 2,
  "runs": 2,
  "secs": [
   1.8,
   1.8
  ],
  "steps": [
   1,
   1
  ],
  "turns": [
   2,
   2
  ],
  "tokens": [
   10511,
   10511
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G2_aylik_seri": {
  "passed": 2,
  "runs": 2,
  "secs": [
   4.4,
   6.0
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   3,
   3
  ],
  "tokens": [
   16929,
   16965
  ],
  "fails": [],
  "ground": [
   "MISS:155.515",
   "MISS:155.515"
  ]
 },
 "G3_turetilmis_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   8.6,
   9.1
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   3,
   3
  ],
  "tokens": [
   17410,
   17455
  ],
  "fails": [],
  "ground": [
   "OK",
   "MISS:155.515"
  ]
 },
 "G4_kapsam_disi": {
  "passed": 2,
  "runs": 2,
  "secs": [
   2.3,
   2.3
  ],
  "steps": [
   1,
   1
  ],
  "turns": [
   2,
   2
  ],
  "tokens": [
   10454,
   10454
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G5_karsilastirma": {
  "passed": 2,
  "runs": 2,
  "secs": [
   5.7,
   9.7
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   3,
   3
  ],
  "tokens": [
   17736,
   17737
  ],
  "fails": [],
  "ground": [
   "MISS:155.515, 741.132",
   "MISS:155.515, 741.132"
  ]
 },
 "G7_tablo_uzerinde_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   8.8,
   17.1
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   35448,
   35453
  ],
  "fails": [],
  "ground": [
   "MISS:155.515 | MISS:2,21, 2,50, 2,44, 2,43, 1,36, 1,94, 2,37, 2,48, 2,95, 2,59, 3,07",
   "MISS:155.515 | MISS:2,21, 2,50, 2,44, 2,43, 1,36, 1,94, 2,37, 2,48, 2,95, 2,59, 3,07"
  ]
 },
 "G6_tabloyu_bozmadan": {
  "passed": 2,
  "runs": 2,
  "secs": [
   9.5,
   9.6
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   35752,
   35752
  ],
  "fails": [],
  "ground": [
   "MISS:155.515 | OK",
   "MISS:155.515 | OK"
  ]
 }
}
```
</details>

<details><summary>preload+parallel+short ayrıntı</summary>

```json
{
 "G1_tek_deger": {
  "passed": 2,
  "runs": 2,
  "secs": [
   2.3,
   2.1
  ],
  "steps": [
   1,
   1
  ],
  "turns": [
   2,
   2
  ],
  "tokens": [
   10652,
   10643
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G2_aylik_seri": {
  "passed": 2,
  "runs": 2,
  "secs": [
   2.3,
   2.3
  ],
  "steps": [
   1,
   1
  ],
  "turns": [
   2,
   2
  ],
  "tokens": [
   10877,
   10877
  ],
  "fails": [],
  "ground": [
   "MISS:156.549",
   "MISS:156.549"
  ]
 },
 "G3_turetilmis_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   3.2,
   3.2
  ],
  "steps": [
   1,
   1
  ],
  "turns": [
   2,
   2
  ],
  "tokens": [
   11272,
   11272
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G4_kapsam_disi": {
  "passed": 2,
  "runs": 2,
  "secs": [
   3.8,
   3.7
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   4,
   4
  ],
  "tokens": [
   21669,
   21669
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G5_karsilastirma": {
  "passed": 2,
  "runs": 2,
  "secs": [
   2.8,
   2.8
  ],
  "steps": [
   1,
   1
  ],
  "turns": [
   2,
   2
  ],
  "tokens": [
   11210,
   11210
  ],
  "fails": [],
  "ground": [
   "MISS:2,5",
   "MISS:2,5"
  ]
 },
 "G7_tablo_uzerinde_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   4.3,
   4.3
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   4,
   4
  ],
  "tokens": [
   22231,
   22231
  ],
  "fails": [],
  "ground": [
   "MISS:156.549 | MISS:2,2, 2,5",
   "MISS:156.549 | MISS:2,2, 2,5"
  ]
 },
 "G6_tabloyu_bozmadan": {
  "passed": 2,
  "runs": 2,
  "secs": [
   4.7,
   4.7
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   4,
   4
  ],
  "tokens": [
   22419,
   22419
  ],
  "fails": [],
  "ground": [
   "MISS:156.549 | OK",
   "MISS:156.549 | OK"
  ]
 }
}
```
</details>

<details><summary>preload+parallel+ground ayrıntı</summary>

```json
{
 "G1_tek_deger": {
  "passed": 2,
  "runs": 2,
  "secs": [
   1.8,
   1.8
  ],
  "steps": [
   1,
   1
  ],
  "turns": [
   2,
   2
  ],
  "tokens": [
   10511,
   10511
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G2_aylik_seri": {
  "passed": 2,
  "runs": 2,
  "secs": [
   7.9,
   13.4
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   37640,
   37640
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G3_turetilmis_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   9.3,
   8.7
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   39386,
   39263
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G4_kapsam_disi": {
  "passed": 2,
  "runs": 2,
  "secs": [
   1.9,
   1.9
  ],
  "steps": [
   1,
   1
  ],
  "turns": [
   2,
   2
  ],
  "tokens": [
   10430,
   10430
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G5_karsilastirma": {
  "passed": 2,
  "runs": 2,
  "secs": [
   5.0,
   5.0
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   3,
   3
  ],
  "tokens": [
   17714,
   17714
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G7_tablo_uzerinde_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   15.3,
   17.6
  ],
  "steps": [
   6,
   6
  ],
  "turns": [
   10,
   10
  ],
  "tokens": [
   65146,
   65152
  ],
  "fails": [],
  "ground": [
   "OK | MISS:2,211078, 2,496313, 2,444998, 2,431501, 1,357539, 1,944571, 2,369128, 2,475957, 2,946462, 2,589139, 3,066321",
   "OK | MISS:2,211078, 2,496313, 2,444998, 2,431501, 1,357539, 1,944571, 2,369128, 2,475957, 2,946462, 2,589139, 3,066321"
  ]
 },
 "G6_tabloyu_bozmadan": {
  "passed": 2,
  "runs": 2,
  "secs": [
   13.0,
   12.9
  ],
  "steps": [
   6,
   6
  ],
  "turns": [
   9,
   9
  ],
  "tokens": [
   57376,
   57376
  ],
  "fails": [],
  "ground": [
   "OK | OK",
   "OK | OK"
  ]
 }
}
```
</details>

<details><summary>preload+parallel+escalate ayrıntı</summary>

```json
{
 "G1_tek_deger": {
  "passed": 2,
  "runs": 2,
  "secs": [
   1.8,
   1.8
  ],
  "steps": [
   1,
   1
  ],
  "turns": [
   2,
   2
  ],
  "tokens": [
   10511,
   10511
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G2_aylik_seri": {
  "passed": 2,
  "runs": 2,
  "secs": [
   3.8,
   3.8
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   3,
   3
  ],
  "tokens": [
   16929,
   16929
  ],
  "fails": [],
  "ground": [
   "MISS:155.515",
   "MISS:155.515"
  ]
 },
 "G3_turetilmis_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   4.4,
   4.5
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   3,
   3
  ],
  "tokens": [
   17436,
   17436
  ],
  "fails": [],
  "ground": [
   "MISS:155.515",
   "MISS:155.515"
  ]
 },
 "G4_kapsam_disi": {
  "passed": 2,
  "runs": 2,
  "secs": [
   1.9,
   1.9
  ],
  "steps": [
   1,
   1
  ],
  "turns": [
   2,
   2
  ],
  "tokens": [
   10430,
   10430
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G5_karsilastirma": {
  "passed": 2,
  "runs": 2,
  "secs": [
   5.0,
   5.0
  ],
  "steps": [
   2,
   2
  ],
  "turns": [
   3,
   3
  ],
  "tokens": [
   17714,
   17714
  ],
  "fails": [],
  "ground": [
   "OK",
   "OK"
  ]
 },
 "G7_tablo_uzerinde_hesap": {
  "passed": 2,
  "runs": 2,
  "secs": [
   7.8,
   7.8
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   35453,
   35453
  ],
  "fails": [],
  "ground": [
   "MISS:155.515 | MISS:2,21, 2,50, 2,44, 2,43, 1,36, 1,94, 2,37, 2,48, 2,95, 2,59, 3,07",
   "MISS:155.515 | MISS:2,21, 2,50, 2,44, 2,43, 1,36, 1,94, 2,37, 2,48, 2,95, 2,59, 3,07"
  ]
 },
 "G6_tabloyu_bozmadan": {
  "passed": 2,
  "runs": 2,
  "secs": [
   8.4,
   8.4
  ],
  "steps": [
   4,
   4
  ],
  "turns": [
   6,
   6
  ],
  "tokens": [
   35752,
   35752
  ],
  "fails": [],
  "ground": [
   "MISS:155.515 | OK",
   "MISS:155.515 | OK"
  ]
 }
}
```
</details>
