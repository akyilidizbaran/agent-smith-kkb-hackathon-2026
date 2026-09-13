# ADR-0060: Kaynağa özel ipuçları yapılandırmada; finans dışı adaptörle jeneriklik uyum testi

**Durum:** Kabul edildi · **Tarih:** 2026-09-14 · **Milestone:** M03

## Bağlam
Jeneriklik zorunlu (transkript 12:33). İnceleme: çekirdek `facets.py` kaynak kimliklerini, `access_policy.py` EVDS
hostlarını ve kurum adlarını kodda taşıyordu; `small_talk.py`'de alan sözcükleri vardı; `anomaly_detect` açıklamasında
"bakiye" örneği modele gidiyordu (uyum testi yakaladı).

## Karar
1. `kkb_agent/config_data/source_hints.json` + `source_hints.py` yükleyici (`SOURCE_HINTS_FILE` ile değiştirilir; yoksa
   boş). Çekirdek bu dosyadan okur; boş yapılandırmada motor çalışır (URL sabitleme ve genel anahtar adı kuralı sürer).
2. Modele giden metinlerde alan terimi yok: araç açıklaması düzeltildi, test iki yerde (profil ve bellek-içi katalogla
   render edilmiş sistem promptu + tüm araç şemaları).
3. **Uyum testi:** `LakehouseClient` sözleşmesini sağlayan bellek-içi, finans dışı (sentetik sağlık) bir adaptör ajan
   koduna dokunmadan araçlara takılır; arama, tanım, kolon ekleme ve anomali beklenen sonuçla çalışır. REST/DB/stream
   adaptörleri uygulanmadı; eklenme yeri ve sözleşmesi bu test ve `docs/M03_VERI_SOZLESMESI.md`.
4. Destek matrisi ve sınır: zaman serisi Silver'da; tarihsiz/işlem tabloları oturumda, otomatik yayına girmez.

## Sonuçlar
Testler `test_m03_kaynak_ipuclari.py` (3), `test_m03_jenerik.py` (3); ajan paketi 375 geçti.
