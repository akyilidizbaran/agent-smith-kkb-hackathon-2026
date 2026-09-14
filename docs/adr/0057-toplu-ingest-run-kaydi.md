# ADR-0057: Toplu katalog ingest'i de run/artifact/uyarı kaydı tutar; eksik seri başarı sayılmaz

**Durum:** Kabul edildi · **Tarih:** 2026-09-14 · **Milestone:** M07

## Bağlam
Ölçüldü (M01 ön kontrolü, 13 Eylül demo DB): 295 artifact, **0 run**. `IngestionPipeline` run/uyarı kaydı tutuyordu
ama demo kurulumunun çağırdığı `scripts/run_catalog_ingestion.py` onu (bilinçli olarak, varlık başına iniş için)
atlıyor, parser uyarılarını yalnız ekrana yazıyordu. Silver `_run_context` run bulamayınca uyarısız sayıyordu:
uyarılı gözlem yeniden kurulumda sessizce `ok` olabiliyordu. `--only` ile istenen seri katalogda yoksa çıktı yine
"başarılı" diyordu.

## Karar
1. **Aynı sözleşme, varlık başına iniş korunarak** (T02–T04): seri başına `meta.run` açılır; her varlık kaydedilir ve
   ayrıştırmadan ÖNCE `meta.run_artifact`'e bağlanır; parser uyarıları Bronze yazımından ÖNCE `meta.ingest_warning`'e
   yazılır; run bir kez `success`/`warning`/`failed` olarak `rows_out` ile kapanır.
2. **Hata metni** `describe_exception` ile maskelenir ve kısaltılır (T05); bir varlığın hatası diğerlerini durdurmaz ama
   run'ı `failed` yapar.
3. **Kesinti** (T11): betik başlarken `running` kalmış run'lar "interrupted" nedeniyle `failed` kapatılır (tek yazar);
   yarım RAW/Bronze içerik adreslidir, sonraki run yeniden bağlar.
4. **Kapsam raporu** (T10): `--report` JSON (istenen/eksik/ok/uyarı/paylaşılan/başarısız/atlanan); `--only`/`--only-file`
   ile istenip katalogda olmayan seri çıkış kodunu 1 yapar.
5. **Dönem** `--start/--end` (varsayılan 2016-01-01 → 2026-06-30, K04).

## Sonuçlar
- Testler (`tests/scripts/test_run_catalog_ingestion.py`, 6): run+bağ+uyarı, maskelenmiş hata, kısmi başarısızlık, idempotent
  yeniden koşu, bayat run, eksik seri. Lakehouse paketi 1.079 → 1.085, hepsi geçti.
- Canlı mini koşu: 3 run (2 uyarılı), 4 bağ, eksik istek raporu "başarısız".
- Mevcut testlerle kapanan: T06 Silver uyarıyı geri okur (`tests/silver/test_build.py`), T07 artifact kimlik kuralları
  (`tests/infrastructure/test_artifacts.py`, `test_parquet.py`), T09 sınır tekrarı tekilleşir / revizyon kurulumu durdurur
  (`test_build.py`). T08 (tarihsel 95 çatışma envanteri) 2016 kurulumu üzerinde ölçülür (M08 raporu).
