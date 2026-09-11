# Motor karşılaştırması — all seti

tarih=2026-09-11 · repeat=3 · model=kkbhackathon2026/Qwen3.8-27B · veri=agent-core/data/lakehouse.duckdb (dev seed)

| Motor | vaka pass^k | koşu | ort. s | p50 s | araç adımı | LLM turu | token | araç hatası | hata kodları | grounding temiz |
|---|---|---|---|---|---|---|---|---|---|---|
| team | 13/18 | 45/54 | 8.4 | 7.1 | 4.7 | 5.4 | - | 33 | SQL_FAILED×21, MISSING_PERIOD_FILTER×6, DUPLICATE_CALL×5, DATASET_NOT_FOUND×1 | - |
| v3 | 16/18 | 48/54 | 3.7 | 3.1 | 1.3 | 2.9 | 15587 | 15 | MISSING_PERIOD_FILTER×6, OUT_OF_COVERAGE×6, EMPTY_DATASET×3 | 45/45 |

## Vaka bazında

| vaka | team pass / s / tur | v3 pass / s / tur | başarısızlık nedenleri |
|---|---|---|---|
| G1_tek_deger | 3/3 / 5.0 / 4.0 | 3/3 / 1.8 / 2.0 |  |
| G2_aylik_seri | 3/3 / 8.6 / 6.0 | 3/3 / 3.4 / 3.0 |  |
| G3_turetilmis_hesap | 3/3 / 7.0 / 5.0 | 0/3 / 4.4 / 3.0 | v3: tablo kontrolü başarısız: 12 satır |
| G4_kapsam_disi | 2/3 / 8.4 / 7.0 | 3/3 / 2.8 / 2.3 | team: cevapta '2021' geçmiyor |
| G5_karsilastirma | 3/3 / 11.6 / 5.0 | 3/3 / 6.5 / 3.0 |  |
| G7_tablo_uzerinde_hesap | 3/3 / 15.0 / 5.7 | 3/3 / 5.7 / 5.0 |  |
| G6_tabloyu_bozmadan | 3/3 / 15.1 / 5.7 | 3/3 / 5.7 / 5.0 |  |
| L1-01 | 3/3 / 4.9 / 5.0 | 3/3 / 1.8 / 2.0 |  |
| L3-02 | 3/3 / 7.1 / 4.3 | 3/3 / 2.8 / 2.0 |  |
| L4-01 | 2/3 / 22.3 / 8.7 | 3/3 / 7.0 / 4.0 | team: adım limiti |
| L6-01 | 3/3 / 5.4 / 5.0 | 3/3 / 3.4 / 2.0 |  |
| L6-04 | 3/3 / 7.0 / 5.0 | 3/3 / 6.5 / 4.0 |  |
| L9-01 | 3/3 / 4.9 / 5.7 | 3/3 / 1.7 / 2.0 |  |
| L9-02 | 0/3 / 6.9 / 8.0 | 3/3 / 4.1 / 4.0 | team: kapsam dışı soruya tablo üretildi |
| L10-01 | 0/3 / 8.1 / 5.0 | 0/3 / 2.1 / 2.0 | team: belirsiz soruya netleştirme sorusu sorulmadı; v3: belirsiz soruya netleştirme sorusu sorulmadı |
| L11-01 | 3/3 / 6.9 / 5.3 | 3/3 / 2.2 / 2.0 |  |
| L11-02 | 2/3 / 5.1 / 4.0 | 3/3 / 2.8 / 2.0 | team: cevapta olmaması gereken: %300 arttı; team: cevapta olmaması gereken: 300 arttı |
| L11-03 | 3/3 / 2.5 / 2.0 | 3/3 / 1.6 / 2.0 |  |
