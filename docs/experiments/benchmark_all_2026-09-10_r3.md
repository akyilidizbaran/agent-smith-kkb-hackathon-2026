# Motor karşılaştırması — all seti

tarih=2026-09-10 · repeat=3 · model=kkbhackathon2026/Qwen3.8-27B · veri=agent-core/data/lakehouse.duckdb (dev seed)

| Motor | vaka pass^k | koşu | ort. s | p50 s | araç adımı | LLM turu | token | araç hatası | hata kodları | grounding temiz |
|---|---|---|---|---|---|---|---|---|---|---|
| team | 17/18 | 51/54 | 5.7 | 5.3 | 4.8 | 5.6 | - | 9 | ERR×9 | - |
| v3 | 16/18 | 48/54 | 5.1 | 4.0 | 2.1 | 3.4 | 21018 | 15 | TOOL_FAILED×6, OUT_OF_COVERAGE×3, EMPTY_DATASET×3, MISSING_PERIOD_FILTER×3 | 39/42 |

## Vaka bazında

| vaka | team pass / s / tur | v3 pass / s / tur | başarısızlık nedenleri |
|---|---|---|---|
| G1_tek_deger | 3/3 / 4.0 / 5.0 | 3/3 / 2.0 / 2.0 |  |
| G2_aylik_seri | 3/3 / 5.3 / 6.0 | 3/3 / 2.9 / 2.0 |  |
| G3_turetilmis_hesap | 3/3 / 6.2 / 6.0 | 3/3 / 3.1 / 2.0 |  |
| G4_kapsam_disi | 3/3 / 4.6 / 6.0 | 3/3 / 1.8 / 2.0 |  |
| G5_karsilastirma | 3/3 / 6.5 / 5.0 | 3/3 / 13.0 / 7.0 |  |
| G7_tablo_uzerinde_hesap | 3/3 / 8.8 / 6.0 | 3/3 / 5.5 / 5.0 |  |
| G6_tabloyu_bozmadan | 3/3 / 11.1 / 6.0 | 3/3 / 5.0 / 4.0 |  |
| L1-01 | 3/3 / 3.4 / 5.0 | 3/3 / 1.8 / 2.0 |  |
| L3-02 | 3/3 / 6.9 / 6.0 | 3/3 / 2.6 / 2.0 |  |
| L4-01 | 3/3 / 7.4 / 6.0 | 0/3 / 15.9 / 9.0 | v3: adım limiti |
| L6-01 | 3/3 / 5.5 / 6.0 | 3/3 / 2.7 / 2.0 |  |
| L6-04 | 3/3 / 5.0 / 6.0 | 3/3 / 7.4 / 6.0 |  |
| L9-01 | 3/3 / 4.4 / 6.0 | 3/3 / 3.3 / 2.0 |  |
| L9-02 | 3/3 / 5.1 / 7.0 | 3/3 / 4.5 / 4.0 |  |
| L10-01 | 0/3 / 4.5 / 6.0 | 0/3 / 4.4 / 2.0 | team: belirsiz soruya netleştirme sorusu sorulmadı; v3: belirsiz soruya netleştirme sorusu sorulmadı |
| L11-01 | 3/3 / 6.0 / 5.0 | 3/3 / 10.1 / 3.3 |  |
| L11-02 | 3/3 / 5.9 / 5.0 | 3/3 / 4.1 / 3.0 |  |
| L11-03 | 3/3 / 1.8 / 2.0 | 3/3 / 2.2 / 2.0 |  |
