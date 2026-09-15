# Motor karşılaştırması — all seti

tarih=2026-09-10 · repeat=3 · model=kkbhackathon2026/Qwen3.8-27B · veri=agent-core/data/lakehouse.duckdb (dev seed)

| Motor | vaka pass^k | koşu | ort. s | p50 s | araç adımı | LLM turu | token | araç hatası | hata kodları | grounding temiz |
|---|---|---|---|---|---|---|---|---|---|---|
| v3 | 17/18 | 51/54 | 4.1 | 3.4 | 1.6 | 3.2 | 18874 | 12 | MISSING_PERIOD_FILTER×6, OUT_OF_COVERAGE×3, EMPTY_DATASET×3 | 41/45 |

## Vaka bazında

| vaka | v3 pass / s / tur | başarısızlık nedenleri |
|---|---|---|
| G1_tek_deger | 3/3 / 2.3 / 2.0 |  |
| G2_aylik_seri | 3/3 / 3.4 / 3.0 |  |
| G3_turetilmis_hesap | 3/3 / 4.4 / 3.0 |  |
| G4_kapsam_disi | 3/3 / 2.2 / 2.0 |  |
| G5_karsilastirma | 3/3 / 6.7 / 5.0 |  |
| G7_tablo_uzerinde_hesap | 3/3 / 6.7 / 5.7 |  |
| G6_tabloyu_bozmadan | 3/3 / 5.9 / 5.0 |  |
| L1-01 | 3/3 / 2.0 / 2.0 |  |
| L3-02 | 3/3 / 2.2 / 2.0 |  |
| L4-01 | 3/3 / 7.0 / 4.0 |  |
| L6-01 | 3/3 / 3.4 / 2.3 |  |
| L6-04 | 3/3 / 7.5 / 6.0 |  |
| L9-01 | 3/3 / 1.7 / 2.0 |  |
| L9-02 | 3/3 / 4.4 / 4.0 |  |
| L10-01 | 0/3 / 2.2 / 2.0 | v3: belirsiz soruya netleştirme sorusu sorulmadı |
| L11-01 | 3/3 / 4.9 / 2.7 |  |
| L11-02 | 3/3 / 4.8 / 3.0 |  |
| L11-03 | 3/3 / 2.3 / 2.0 |  |
