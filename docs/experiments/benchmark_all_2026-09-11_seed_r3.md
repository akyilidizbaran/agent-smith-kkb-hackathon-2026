# Motor karşılaştırması — all seti

tarih=2026-09-11 · repeat=3 · model=kkbhackathon2026/Qwen3.8-27B · veri=agent-core/data/lakehouse.duckdb (dev seed)

| Motor | vaka pass^k | koşu | ort. s | p50 s | araç adımı | LLM turu | token | araç hatası | hata kodları | grounding temiz |
|---|---|---|---|---|---|---|---|---|---|---|
| team | 14/18 | 45/54 | 9.5 | 8.1 | 5 | 5.7 | - | 17 | MISSING_PERIOD_FILTER×9, DUPLICATE_CALL×7, SQL_FAILED×1 | - |
| v3 | 17/18 | 51/54 | 7.9 | 5.6 | 1.5 | 3.1 | 18623 | 13 | OUT_OF_COVERAGE×5, MISSING_PERIOD_FILTER×5, EMPTY_DATASET×3 | 43/45 |

## Vaka bazında

| vaka | team pass / s / tur | v3 pass / s / tur | başarısızlık nedenleri |
|---|---|---|---|
| G1_tek_deger | 3/3 / 6.6 / 5.0 | 3/3 / 3.7 / 2.0 |  |
| G2_aylik_seri | 3/3 / 8.1 / 6.0 | 3/3 / 5.7 / 3.0 |  |
| G3_turetilmis_hesap | 3/3 / 10.1 / 6.0 | 3/3 / 7.2 / 2.7 |  |
| G4_kapsam_disi | 3/3 / 8.0 / 6.0 | 3/3 / 3.7 / 2.0 |  |
| G5_karsilastirma | 3/3 / 9.7 / 5.0 | 3/3 / 42.0 / 4.7 |  |
| G7_tablo_uzerinde_hesap | 3/3 / 14.0 / 6.0 | 3/3 / 8.0 / 5.7 |  |
| G6_tabloyu_bozmadan | 3/3 / 22.0 / 6.0 | 3/3 / 7.8 / 4.7 |  |
| L1-01 | 3/3 / 5.2 / 5.0 | 3/3 / 2.2 / 2.0 |  |
| L3-02 | 3/3 / 10.7 / 6.7 | 3/3 / 4.8 / 2.3 |  |
| L4-01 | 2/3 / 15.7 / 8.0 | 3/3 / 10.1 / 3.3 | team: adım limiti |
| L6-01 | 3/3 / 9.1 / 6.0 | 3/3 / 6.0 / 2.7 |  |
| L6-04 | 0/3 / 10.3 / 6.0 | 3/3 / 9.7 / 5.3 | team: tablo 2+ satır değil |
| L9-01 | 3/3 / 7.4 / 6.0 | 3/3 / 3.3 / 2.0 |  |
| L9-02 | 1/3 / 6.7 / 7.0 | 3/3 / 5.8 / 4.0 | team: kapsam dışı soruya tablo üretildi |
| L10-01 | 0/3 / 7.0 / 6.0 | 0/3 / 3.7 / 2.0 | team: belirsiz soruya netleştirme sorusu sorulmadı; v3: belirsiz soruya netleştirme sorusu sorulmadı |
| L11-01 | 3/3 / 8.9 / 5.0 | 3/3 / 8.0 / 3.3 |  |
| L11-02 | 3/3 / 7.0 / 5.0 | 3/3 / 6.3 / 3.0 |  |
| L11-03 | 3/3 / 4.1 / 2.0 | 3/3 / 3.5 / 2.0 |  |
