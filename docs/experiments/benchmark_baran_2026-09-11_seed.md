# Motor karşılaştırması — all seti

tarih=2026-09-11 · repeat=3 · model=kkbhackathon2026/Qwen3.8-27B · veri=data/lakehouse.duckdb

| Motor | vaka pass^k | koşu | ort. s | p50 s | araç adımı | LLM turu | token | araç hatası | hata kodları | grounding temiz |
|---|---|---|---|---|---|---|---|---|---|---|
| team | 17/18 | 51/54 | 6.8 | 5.7 | 5.2 | 6.0 | - | 16 | DUPLICATE_CALL×7, MISSING_PERIOD_FILTER×6, OUT_OF_COVERAGE×3 | 48/48 |
| v3 | 17/18 | 51/54 | 3.9 | 3.7 | 1.3 | 2.9 | 16705 | 9 | OUT_OF_COVERAGE×3, EMPTY_DATASET×3, MISSING_PERIOD_FILTER×3 | 45/45 |

## Vaka bazında

| vaka | team pass / s / tur | v3 pass / s / tur | başarısızlık nedenleri |
|---|---|---|---|
| G1_tek_deger | 3/3 / 4.0 / 5.0 | 3/3 / 2.2 / 2.0 |  |
| G2_aylik_seri | 3/3 / 5.5 / 6.0 | 3/3 / 3.5 / 3.0 |  |
| G3_turetilmis_hesap | 3/3 / 11.5 / 10.0 | 3/3 / 5.1 / 3.0 |  |
| G4_kapsam_disi | 3/3 / 4.9 / 6.0 | 3/3 / 2.1 / 2.0 |  |
| G5_karsilastirma | 3/3 / 10.6 / 7.0 | 3/3 / 3.1 / 2.0 |  |
| G7_tablo_uzerinde_hesap | 3/3 / 12.0 / 7.3 | 3/3 / 6.1 / 5.0 |  |
| G6_tabloyu_bozmadan | 3/3 / 12.5 / 6.0 | 3/3 / 6.4 / 5.0 |  |
| L1-01 | 3/3 / 3.8 / 5.0 | 3/3 / 2.2 / 2.0 |  |
| L3-02 | 3/3 / 7.4 / 6.0 | 3/3 / 2.6 / 2.0 |  |
| L4-01 | 3/3 / 7.4 / 6.0 | 3/3 / 4.1 / 2.0 |  |
| L6-01 | 3/3 / 5.8 / 6.0 | 3/3 / 4.5 / 3.0 |  |
| L6-04 | 3/3 / 10.1 / 10.0 | 3/3 / 7.3 / 6.0 |  |
| L9-01 | 3/3 / 5.2 / 6.0 | 3/3 / 2.1 / 2.0 |  |
| L9-02 | 3/3 / 3.6 / 4.0 | 3/3 / 5.0 / 4.0 |  |
| L10-01 | 0/3 / 5.2 / 6.0 | 0/3 / 2.3 / 2.0 | team: belirsiz soruya netleştirme sorusu sorulmadı; v3: belirsiz soruya netleştirme sorusu sorulmadı |
| L11-01 | 3/3 / 6.5 / 5.0 | 3/3 / 3.8 / 2.0 |  |
| L11-02 | 3/3 / 5.0 / 5.0 | 3/3 / 4.4 / 3.0 |  |
| L11-03 | 3/3 / 2.1 / 2.0 | 3/3 / 2.4 / 2.0 |  |
