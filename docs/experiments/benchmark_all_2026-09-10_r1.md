# Motor karşılaştırması — all seti

tarih=2026-09-10 · repeat=1 · model=kkbhackathon2026/Qwen3.8-27B · veri=agent-core/data/lakehouse.duckdb (dev seed)

| Motor | vaka pass^k | koşu | ort. s | p50 s | araç adımı | LLM turu | token | araç hatası | hata kodları | grounding temiz |
|---|---|---|---|---|---|---|---|---|---|---|
| team | 17/18 | 17/18 | 6.0 | 5.8 | 4.9 | 5.6 | - | 3 | ERR×3 | - |
| v3 | 16/18 | 16/18 | 4.1 | 2.7 | 2.1 | 3.4 | 20699 | 6 | MISSING_PERIOD_FILTER×3, OUT_OF_COVERAGE×2, EMPTY_DATASET×1 | 12/14 |

## Vaka bazında

| vaka | team pass / s / tur | v3 pass / s / tur | başarısızlık nedenleri |
|---|---|---|---|
| G1_tek_deger | 1/1 / 5.3 / 5.0 | 1/1 / 1.9 / 2.0 |  |
| G2_aylik_seri | 1/1 / 5.3 / 6.0 | 1/1 / 2.2 / 2.0 |  |
| G3_turetilmis_hesap | 1/1 / 5.8 / 6.0 | 1/1 / 2.6 / 2.0 |  |
| G4_kapsam_disi | 1/1 / 4.4 / 6.0 | 1/1 / 2.9 / 3.0 |  |
| G5_karsilastirma | 1/1 / 6.5 / 5.0 | 1/1 / 6.6 / 6.0 |  |
| G7_tablo_uzerinde_hesap | 1/1 / 8.7 / 6.0 | 1/1 / 5.3 / 5.0 |  |
| G6_tabloyu_bozmadan | 1/1 / 11.2 / 6.0 | 1/1 / 4.6 / 4.0 |  |
| L1-01 | 1/1 / 3.5 / 5.0 | 1/1 / 1.9 / 2.0 |  |
| L3-02 | 1/1 / 6.9 / 7.0 | 1/1 / 2.0 / 2.0 |  |
| L4-01 | 1/1 / 7.2 / 6.0 | 0/1 / 15.5 / 9.0 | v3: adım limiti |
| L6-01 | 1/1 / 5.7 / 6.0 | 1/1 / 2.2 / 2.0 |  |
| L6-04 | 1/1 / 6.6 / 6.0 | 1/1 / 7.9 / 7.0 |  |
| L9-01 | 1/1 / 4.6 / 6.0 | 1/1 / 1.6 / 2.0 |  |
| L9-02 | 1/1 / 5.0 / 7.0 | 1/1 / 4.3 / 4.0 |  |
| L10-01 | 0/1 / 4.5 / 6.0 | 0/1 / 2.1 / 2.0 | team: belirsiz soruya netleştirme sorusu sorulmadı; v3: belirsiz soruya netleştirme sorusu sorulmadı |
| L11-01 | 1/1 / 5.9 / 5.0 | 1/1 / 3.4 / 2.0 |  |
| L11-02 | 1/1 / 9.2 / 5.0 | 1/1 / 5.0 / 4.0 |  |
| L11-03 | 1/1 / 1.8 / 2.0 | 1/1 / 2.2 / 2.0 |  |
