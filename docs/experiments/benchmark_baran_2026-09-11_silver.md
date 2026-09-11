# Motor karşılaştırması — all seti

tarih=2026-09-11 · repeat=3 · model=kkbhackathon2026/Qwen3.8-27B · veri=data/lakehouse_silver.duckdb

| Motor | vaka pass^k | koşu | ort. s | p50 s | araç adımı | LLM turu | token | araç hatası | hata kodları | grounding temiz |
|---|---|---|---|---|---|---|---|---|---|---|
| team | 17/18 | 51/54 | 6.0 | 4.7 | 4 | 4.8 | - | 3 | OUT_OF_COVERAGE×3 | 48/48 |
| v3 | 16/18 | 48/54 | 3.6 | 3.2 | 1.3 | 2.9 | 15809 | 18 | MISSING_PERIOD_FILTER×9, OUT_OF_COVERAGE×6, EMPTY_DATASET×3 | 45/45 |

## Vaka bazında

| vaka | team pass / s / tur | v3 pass / s / tur | başarısızlık nedenleri |
|---|---|---|---|
| G1_tek_deger | 3/3 / 2.9 / 4.0 | 3/3 / 1.9 / 2.0 |  |
| G2_aylik_seri | 3/3 / 4.7 / 5.0 | 3/3 / 3.2 / 3.0 |  |
| G3_turetilmis_hesap | 3/3 / 5.3 / 5.0 | 0/3 / 3.8 / 3.0 | v3: tablo kontrolü başarısız: 12 satır |
| G4_kapsam_disi | 3/3 / 4.0 / 5.0 | 3/3 / 3.3 / 3.0 |  |
| G5_karsilastirma | 3/3 / 10.6 / 6.0 | 3/3 / 4.7 / 3.0 |  |
| G7_tablo_uzerinde_hesap | 3/3 / 8.7 / 5.0 | 3/3 / 5.3 / 5.0 |  |
| G6_tabloyu_bozmadan | 3/3 / 10.1 / 5.0 | 3/3 / 5.2 / 5.0 |  |
| L1-01 | 3/3 / 3.1 / 4.0 | 3/3 / 2.0 / 2.0 |  |
| L3-02 | 3/3 / 3.3 / 4.0 | 3/3 / 2.3 / 2.0 |  |
| L4-01 | 3/3 / 12.4 / 8.0 | 3/3 / 6.6 / 4.0 |  |
| L6-01 | 3/3 / 4.7 / 5.0 | 3/3 / 3.2 / 2.0 |  |
| L6-04 | 3/3 / 10.8 / 7.0 | 3/3 / 6.6 / 4.0 |  |
| L9-01 | 3/3 / 4.5 / 5.0 | 3/3 / 2.0 / 2.0 |  |
| L9-02 | 3/3 / 4.3 / 4.0 | 3/3 / 4.9 / 4.0 |  |
| L10-01 | 0/3 / 6.6 / 5.0 | 0/3 / 2.6 / 2.3 | team: belirsiz soruya netleştirme sorusu sorulmadı; v3: belirsiz soruya netleştirme sorusu sorulmadı |
| L11-01 | 3/3 / 5.3 / 4.0 | 3/3 / 2.5 / 2.0 |  |
| L11-02 | 3/3 / 4.4 / 4.0 | 3/3 / 3.1 / 2.0 |  |
| L11-03 | 3/3 / 2.2 / 2.0 | 3/3 / 1.9 / 2.0 |  |
