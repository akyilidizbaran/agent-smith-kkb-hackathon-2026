# Generic + Ad-hoc Ingestion: inceleme düzeltme raporu

Doğrulanan branch: `feature/generic-adhoc-ingestion-v1`.
Başlangıç ve bitiş HEAD: `994654f5ba63e61c4b40dade7824df8c14e4f63b`.
Gerçek depo: `/Users/elifgungen/Documents/kkb hackathon/AgentSmithler_WorkSpace/lakehouse-core`.
Codex'in başlangıç çalışma klasörü boş olduğundan mevcut depo salt okunur kontrollerle bulundu.

Reset, stash, rebase, merge, git commit veya push yapılmadı. Mevcut commitlenmemiş çalışma
korundu. Gold, Silver, source-specific connector/parser kodlarına ve baseline testlerine
dokunulmadı. Mevcut `uv.lock`, `catalog/series.py`, `catalog/registration.py` ve `errors.py`
değişiklikleri bu turda değiştirilmeden korundu.

## Sonuç

Yayın artık `bronze_path` dosyasını okur; bellekteki DataFrame'i değiştirmek yayımlanan değeri
değiştirmez. `read_identity` ile source, dataset, artifact SHA, schema version, representation
ve parser config SHA doğrulanır. Asset/batch/config eşleşmesi ve kayıtlı request provenance
kontrol edilir. Ad-hoc model geçerli UUID run_id gerektirir; yayın, eşleşen source/dataset
altındaki başarılı veya uyarılı `meta.run` kaydını zorunlu kılar. SQL run_id alanı NOT NULL'dır.

Parser seçimleri yalnız `FetchSpec.parameters` üzerinden verilir; `GenericTabularParser`
constructor'ında seçim parametresi kaldırıldı. Tek allow-list seçimleri kanonik JSON'a ve
SHA-256'ya dönüştürür. Aynı RAW artifact'in farklı sheet/table seçimleri ayrı Bronze yollarına
ve request provenance kayıtlarına gider. Mevcut kaynakların config hash'i olmayan kimlik ve
Parquet yolları değişmez. Kalite bayrağı kalıcı ingest warning kayıtlarından gelir.

## Kırmızı → yeşil kanıtı

Düzeltmeden önce mevcut Generic/Ad-hoc paketi: **162 passed**.
13 bulgu için önce eklenen parametrik regression testleri: **50 failed**, beklenen karşı-örnekler.
Ek incelemedeki eksik `representation` vakası ayrıca önce **1 failed** olarak doğrulandı.
Sonraki olumlu ve sınır testleriyle toplam **73 yeni test vakası** eklendi; hedef paket
**235 passed**. Hatalı formül testi veri kaybını kabul etmeyecek şekilde değiştirildi.

Aşağıdaki kısaltmalar doğrudan test dosyalarına gider:
[G: Generic regressions](../../tests/generic/test_review_regressions.py),
[A: Ad-hoc regressions](../../tests/adhoc/test_review_regressions.py).

| Bulgu | Kapanışı doğrulayan testler |
|---|---|
| 1. Bellek değişikliği eski SHA ile yayımlanıyor | A `test_01_publication_reads_durable_bronze`; `test_01_missing_bronze_never_falls_back_to_memory`; `test_01_quality_uses_durable_warnings` |
| 2. A asset/run ile B batch karıştırılabiliyor | A `test_02_mixed_ingestion_results_are_refused`; `test_02_all_bronze_identity_fields_are_verified` (5 alan); `test_02_missing_representation_metadata_is_refused` |
| 3. run_id eksik veya ilişkisiz olabiliyor | A `test_03_adhoc_result_requires_run_id`; `test_03_publication_requires_matching_successful_run` (eksik/source/dataset/failed); `test_03_sql_rejects_null_run_id` |
| 4. Parser seçimi provenance/kimlik dışında | G `test_04_selections_have_distinct_durable_identities` (XLSX/HTML, tekrar ingest dahil); `test_04_all_choices_are_canonical_and_durable`; `test_04_constructor_cannot_override_artifact_choices`; `test_04_unknown_and_format_invalid_parameters_are_refused`; A `test_04_bronze_configuration_identity_must_match` |
| 5. Quoted virgüller delimiter seçimini bozuyor | G `test_05_quoted_commas_do_not_override_semicolon`; `test_05_multiple_valid_delimiters_require_explicit_choice` |
| 6. Geç workbook ZIP entry yanlış tanınıyor | G `test_06_workbook_entries_after_8kb`; `test_06_zip_payload_markers_are_not_entry_names` |
| 7. XLSX formülü sessiz NULL oluyor | G `test_07_formula_workbook_is_explicitly_refused` (header/data/hidden); `test_07_cached_formula_is_also_refused`; [mevcut parser testi](../../tests/generic/test_parser.py) `test_a_formula_workbook_requires_a_values_only_export` |
| 8. HTML hücresi sessiz kırpılıyor | G `test_08_long_html_cell_is_refused` |
| 9. HTTP response hata halinde açık kalıyor | G `test_09_response_closed_on_every_stream_failure` (limit/timeout/request/unexpected); `test_09_response_closed_for_success_redirect_and_http_error` |
| 10. URL-only constructor limit/clock doğrulamıyor | G `test_10_url_only_constructor_validates_limits`; `test_10_constructor_requires_aware_clock` (naive/offset yok/yanlış tip) |
| 11. Allowed root dosya olabiliyor | G `test_11_allowed_root_must_be_a_directory` |
| 12. Explicit encoding uygulanmıyor | G `test_12_explicit_encoding_is_used_and_recorded`; `test_12_wrong_explicit_encoding_is_refused_without_fallback` |
| 13. Bozuk binlik gruplaması kabul ediliyor | A `test_13_malformed_thousands_groups_are_refused` (7 örnek); `test_13_invalid_grouping_publishes_no_partial_rows`; `test_13_valid_grouping_is_preserved` (6 geçerli örnek) |

## Ek tur: run–artifact provenance boşluğu

13 düzeltme aynen korundu; bu tur yalnız bağımsız karşı-testlerin ürettiği iki sorunu kapattı:

1. `IngestionResult.asset.fetched_at` değiştirilerek sahte tarih yayımlanabiliyordu.
2. Aynı source/dataset'teki başka bir başarılı run'ın `run_id` değeri farklı artifact ile
   kabul ediliyordu; yayın yalnız run'ın source/dataset/status değerlerini kontrol ediyordu.

### Migration tasarımı

`sql/bootstrap/011_run_artifact.sql` additive bir junction tablosu oluşturur:
`meta.run_artifact(run_id, artifact_sha256, source_id, dataset_id, fetched_at,
parser_config_sha256)`, birincil anahtar `(run_id, artifact_sha256)`. SQL CHECK'leri boş
kimlikleri, 64 hex olmayan digest'leri ve NULL `fetched_at` değerini reddeder; regex CHECK'ler
pinli DuckDB 1.5.5 ile doğrulandı. `010` ile aynı gerekçeyle FOREIGN KEY yok: pinli sürümde
child satır varken `UPDATE ... RETURNING` başarısız oluyor ve run kapatma tam olarak bu
sorgudur. Referans kuralları `RunRepository.link_artifact` içinde: run var ve hâlâ `running`
olmalı, run'ın source/dataset'i bağla eşleşmeli, artifact `meta.artifact` içinde kayıtlı ve
aynı source/dataset altında olmalı. Aynı çiftin aynı bilgilerle tekrar bağlanması tam no-op
(`False` döner, satır çoğalmaz); farklı `fetched_at` veya parser hash'i ile tekrar bağlama
`RunArtifactIntegrityError`. Mevcut tablolara sütun eklenmedi; `001–010` ve `020` değişmedi.
`fetched_at`, o run'daki connector zamanıdır ve aynı byte'ların ilk indirilişini tutan
`meta.artifact.fetched_at` değerinden meşru olarak farklı olabilir; bu yüzden bağ, artifact
satırından değil run'dan türetilir.

Pipeline, `ArtifactRepository.register` çağrısından hemen sonra ve parse'tan önce bağı yazar.
Parse veya Bronze yazımı sonradan başarısız olsa da bağ kalır; run ayrıca `failed` kapanır.
Ek saat okuması yapılmadığından baseline zaman damgası testleri değişmedi. Curated kaynaklar
`parser_config_sha256=NULL` ile bağlanır; `IngestionResult` şekli ve Bronze çıktısı aynıdır.

`publish_adhoc_observations`, mevcut run kontrolünden sonra `(run_id, artifact_sha256)`
bağını zorunlu kılar; bağın `source_id`, `dataset_id`, `fetched_at` (mikrosaniye, `epoch_us`
ile) ve `parser_config_sha256` değerleri sonuçla, bağın source/dataset'i de `meta.artifact`
ile eşleşmelidir. Yayımlanan `fetched_at` bellekteki asset'ten değil bu kalıcı bağdan gelir.
TIMESTAMPTZ geri okuması `pytz` gerektirdiğinden değer `epoch_us` üzerinden okunup saf Python
UTC datetime'a çevrilir.

### Kırmızı → yeşil kanıtı

Yeni dosya [tests/adhoc/test_run_artifact_provenance.py](../../tests/adhoc/test_run_artifact_provenance.py)
düzeltmeden önce **30 failed** verdi. İki temel karşı-test tablo eksikliğinden değil
zafiyetin kendisinden düştü: `test_01_forged_asset_fetched_at_is_refused` ve
`test_02_another_successful_run_of_the_same_dataset_is_refused` için pytest çıktısı
`Failed: DID NOT RAISE AdhocPublicationError`. Düzeltmeden sonra aynı dosya **30 passed**.

| İstenen test | Testler |
|---|---|
| 1. Değiştirilmiş `asset.fetched_at` reddediliyor | `test_01_forged_asset_fetched_at_is_refused` (+1 gün, +1 µs, −400 gün); `test_01_published_fetched_at_comes_from_the_durable_link` |
| 2. Aynı dataset'teki başka başarılı run'ın kimliği reddediliyor | `test_02_another_successful_run_of_the_same_dataset_is_refused` (A↔B her iki yön; B'nin `success` ve aynı source/dataset olduğu doğrulanır) |
| 3. Doğru run–artifact bağı kabul ediliyor | `test_03_correct_run_artifact_link_is_accepted`; `test_03_both_runs_over_the_same_bytes_are_publishable` (aynı byte'lar, iki run, iki bağ, tek artifact) |
| 4. Parse başarısız olsa da artifact bağlı kalıyor, run `failed` | `test_04_download_stays_linked_when_a_later_step_fails` (parser / Bronze yazımı); `test_04_generic_parser_refusal_keeps_the_link` (gerçek connector+parser, formül workbook) |
| 5. İdempotent tekrar kayıt veri çoğaltmıyor | `test_05_relinking_the_identical_pair_is_a_no_op` (farklı saat dilimi dahil); `test_05_same_asset_twice_in_one_run_links_once`; `test_05_relinking_with_different_facts_is_a_conflict` (3 örnek) |
| 6. Sahte/uyumsuz kayıt SQL/application kontrollerinden geçemiyor | `test_06_sql_rejects_malformed_link_rows` (7 örnek); `test_06_sql_rejects_a_second_row_for_the_same_pair`; `test_06_application_refuses_inconsistent_links` (6 örnek); `test_06_publication_requires_the_link_to_agree_with_the_artifact` |

### Bu ek turda değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| [011_run_artifact.sql](../../sql/bootstrap/011_run_artifact.sql) | **Yeni:** `meta.run_artifact` tablosu ve CHECK'ler |
| [ingestion/observability.py](../../src/lakehouse/ingestion/observability.py) | `RunArtifactLink`, `RunArtifactIntegrityError`, `RunRepository.link_artifact`, `epoch_us`/`datetime_from_epoch_us` |
| [ingestion/__init__.py](../../src/lakehouse/ingestion/__init__.py) | Yeni adların dışa açılması |
| [ingestion/pipeline.py](../../src/lakehouse/ingestion/pipeline.py) | `register` sonrası, parse öncesi `_link_artifact` |
| [adhoc/publication.py](../../src/lakehouse/adhoc/publication.py) | `_verified_run_artifact_fetched_at`; kalıcı `fetched_at` yayımı |
| [tests/adhoc/test_run_artifact_provenance.py](../../tests/adhoc/test_run_artifact_provenance.py) | **Yeni:** 30 regression/sınır testi |
| [tests/ingestion/test_pipeline_observability.py](../../tests/ingestion/test_pipeline_observability.py) | Karşılaştırma amaçlı no-op test double'a no-op `link_artifact` (tek baseline test dokunuşu) |
| [adhoc-publication-contract.md](../adhoc-publication-contract.md), [generic-ingestion-contract.md](../generic-ingestion-contract.md), [generic-adhoc-ingestion-v1.md](generic-adhoc-ingestion-v1.md) | Run–artifact provenance sözleşmesi |

Gold, Silver, source-specific connector/parser kodları ve önceki 13 düzeltme değişmedi.

## Gerçek son doğrulama

Tüm komutlar gerçek proje klasöründe çalıştırıldı; testler skip veya xfail ile geçiştirilmedi.
İlk turdaki sayılar: 912 / 235 / 138 / 677. Ek turdaki 30 yeni test tümünü ve Generic/Ad-hoc
paketini artırdı; baseline sayısı aynı kaldı.

| Komut | Sonuç | Çıkış kodu |
|---|---|---|
| `uv sync --frozen` | Checked 19 packages in 0.33ms | 0 |
| `uv lock --check` | Resolved 22 packages in 2ms | 0 |
| `uv run pytest -q` | 942 passed in 12.39s | 0 |
| `uv run pytest -q tests/generic tests/adhoc` | 265 passed in 4.01s | 0 |
| `uv run pytest -q tests/gold tests/acceptance` | 138 passed in 3.81s | 0 |
| `uv run pytest -q --ignore=tests/generic --ignore=tests/adhoc` | 677 passed in 8.29s | 0 |
| `make build` | Başarılı; temel veri dizinlerini hazırlar (Silver/Gold derlemesi yapmaz) | 0 |
| `make demo-check` | 2 passed in 0.30s | 0 |
| `git diff --check` | Temiz; çıktı yok (izlenmeyen yeni dosyalar ayrıca grep ile boşluk kontrolünden geçti) | 0 |

## Bu turda değiştirilen dosyalar

Yollar `lakehouse-core/` altındadır. “Yeni” bu düzeltme turunda oluşturulan dosyayı belirtir;
diğerlerinin bir kısmı başlangıçtan beri git tarafından izlenmeyen mevcut çalışmaydı.

| Dosya | Değişiklik |
|---|---|
| [generic/config.py](../../src/lakehouse/generic/config.py) | **Yeni:** ortak allow-list, kanonik JSON/hash, metadata doğrulama |
| [generic/connector.py](../../src/lakehouse/generic/connector.py) | Konfigürasyon provenance'ı, constructor kontrolleri, response finally |
| [generic/parser.py](../../src/lakehouse/generic/parser.py) | Metadata'dan seçim/encoding, RAW SHA kontrolü, quote-aware delimiter, formül reddi |
| [generic/formats.py](../../src/lakehouse/generic/formats.py) | ZIP directory/entry üzerinden XLSX tanıma |
| [generic/_access.py](../../src/lakehouse/generic/_access.py) | Allowed root directory doğrulama |
| [generic/_html.py](../../src/lakehouse/generic/_html.py) | Uzun hücreyi kesmek yerine hata |
| [adhoc/publication.py](../../src/lakehouse/adhoc/publication.py) | Kalıcı Bronze okuma, provenance/run kontrolleri, kalıcı warnings, binlik gruplaması |
| [contracts/models.py](../../src/lakehouse/contracts/models.py) | ParsedBatch'e opsiyonel parser hash'i |
| [storage/parquet.py](../../src/lakehouse/storage/parquet.py) | Hash'i Parquet metadata ve yol kimliğine ekleme; eksik representation reddi |
| [ingestion/pipeline.py](../../src/lakehouse/ingestion/pipeline.py) | Ad-hoc modelde zorunlu UUID run_id; legacy constructor uyumluluğu |
| [020_adhoc_observations.sql](../../sql/bootstrap/020_adhoc_observations.sql) | run_id NOT NULL ve nonblank CHECK |
| [pyproject.toml](../../pyproject.toml) | Formül güvenliği açıklaması güncellendi; dependency listesi değişmedi |
| [tests/generic/_support.py](../../tests/generic/_support.py) | Parser constructor seçim yüzeyini kaldırma |
| [tests/generic/test_parser.py](../../tests/generic/test_parser.py) | Seçimleri FetchSpec'e taşıma, yanlış formül testini değiştirme |
| [tests/generic/test_connector.py](../../tests/generic/test_connector.py) | Bilinmeyen credential parametresinin güvenli reddi; secret sızıntısı kontrolü korundu |
| [tests/generic/test_review_regressions.py](../../tests/generic/test_review_regressions.py) | **Yeni:** Generic regression ve sınır testleri |
| [tests/adhoc/test_review_regressions.py](../../tests/adhoc/test_review_regressions.py) | **Yeni:** yayın kimliği ve sayı regression testleri |
| [generic-ingestion-contract.md](../generic-ingestion-contract.md) | Parser ve provenance sözleşmesi güncellendi |
| [adhoc-publication-contract.md](../adhoc-publication-contract.md) | Kalıcı yayın kontrolleri ve güven sınırları |
| [generic-adhoc-ingestion-v1.md](generic-adhoc-ingestion-v1.md) | Eski formül/encoding/kimlik açıklamaları düzeltildi |
| Bu rapor | **Yeni:** test eşlemesi, sonuçlar, kapsam ve sınırlamalar |

## Kalan dürüst sınırlamalar

- DNS rebinding hâlâ engellenmiyor: requests bağlantısı doğrulanan IP'ye sabitlenmiyor.
- `encoding="auto"` sezgiseldir. Yanlış karakter riski için dört encoding'den biri açıkça
  verilmelidir; tanımlı olmayan codec'ler kabul edilmez.
- Formül bulunan workbook'lar, seçilmeyen veya gizli sheet'lerde bile formül varsa reddedilir.
  Dışarıda hesaplanmış ve yalnız değerleri içeren export gerekir.
- Eski Generic Bronze'larda parser config provenance'ı yoktur; yeni kuralla yeniden ingestion
  gerekir. Düzeltilen `CREATE TABLE IF NOT EXISTS` migration, önceden oluşturulmuş nullable
  tabloyu otomatik dönüştürmez. Mevcut veritabanlarında NULL run'lar çözülerek ayrı bir schema
  migration uygulanmalıdır; bu turda kullanıcı veritabanı dönüştürülmedi.
- `run_id` zorunluluğu ad-hoc sonuçlar içindir. Baseline'ın eski, non-ad-hoc dört argümanlı
  `IngestionResult` kullanımı korunur. SQL'de NOT NULL vardır; run varlığı/source/dataset
  eşleşmesi yayın API'sinde denetlenir, doğrudan trusted SQL aynı kapıdan geçmez.
- Yerel DB ve immutable storage güvenilir kabul edilir. Parquet kimliği dijital imza değildir;
  dosyayı ve metadata'yı birlikte değiştirebilen saldırganı kriptografik olarak engellemez.
  `meta.run_artifact` artık her run'ı indirdiği artifact'lere bağlar; başka run'ın kimliğini
  taşıyan veya pipeline'ın kaydetmediği bir `fetched_at` taşıyan sonuç reddedilir. Trusted SQL
  erişimi olan bir yazar tutarlı bir sahte bağ satırı ekleyebilir; bu sınır kalır.
- `011_run_artifact.sql` öncesinde kaydedilmiş run'ların bağ satırı yoktur; sonuçları ad-hoc
  olarak yayımlanamaz ve yeniden ingestion gerekir. Mevcut kullanıcı veritabanı dönüştürülmedi.
- Ad-hoc yayın kimliği hâlâ series/entity/date/artifact düzeyindedir. Farklı sheet'lerdeki
  farklı değerler aynı yayın kimliğine map edilirse açık `AdhocPublicationConflict` doğar;
  Bronze representation'ları bağımsızdır. Bunun için ayrı seri veya açık seçim gerekir.
- Büyük dosya performansı ve eşzamanlı yayın benchmark'ı yapılmadı. Duplicate kontrolü
  uygulama transaction'ındadır; çok yazarlı çalışma garantisi eklenmedi. JS sayfaları,
  PDF/OCR/VLM, Gold promotion ve Silver kapsamı değişmedi.
