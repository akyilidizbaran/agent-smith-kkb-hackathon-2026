# ADR-0102 — Lakehouse CI parçalama ve ilişki kataloğu eşitlemesi

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-21
- **İlgili çalışma:** PR #9 ile 6.304 aktif seriye çıkan lakehouse test paketinde GitHub Actions A/C işlerinin 60 dakikada kesilmesi

## Bağlam

Actions koşusu `35538510918` içinde A ve C işleri sırasıyla yaklaşık %29 ve %62 ilerlemede, 60 dakikalık iş sınırında `cancelled` oldu. B tamamlandı ancak o da sınıra yakındı. Test adımında assertion hatası veya hata izi yoktu. Önceki A/B/C dağılımı yaklaşık 1,9k serilik katalog ölçümüne göre dengelenmişti; geniş katalogda aynı dağılım sürdürülebilir değildi.

Ek olarak, her `bootstrap_database` çağrısında katalog ilişki grafiğinin binlerce satırı tek tek `INSERT OR REPLACE` ediliyordu. İçerik hash'i değişmemiş ilişkilerin yeniden yazılması veri değişikliği üretmiyor ve tekrarlı bootstrap'ı gereksiz yere pahalılaştırıyordu.

## Karar

1. Lakehouse testleri 60 dakikalık sınırı körlemesine yükseltmek yerine A–H olmak üzere sekiz paralel parçaya ayrılır. Her `tests/<dizin>` tam bir parçaya atanır; workflow kapsama adımı bu kuralı denetler. Yeni test dizinleri aynı denetime eklenir.
2. İlişki eşitlemesinde `relation_content_sha256` mevcut kayıtla aynıysa satır yazılmaz. Değişmiş/yeni kayıtlar tek hazırlanmış DuckDB `executemany` çağrısıyla yazılır. `_upsert_series_relations` mevcut dönüş sözleşmesini koruyarak ilişki sayısını döndürür.
3. Pytest başarılı tamamlandığında en yavaş 20 testi raporlar (`--durations=20`), böylece sonraki parça dengelemesi ölçüme dayanabilir.
4. Tüm katalog kaydı ve ilişki çıkarım kuralları aynı kalır; bu düzenleme kaynak, veri kapsamı, id, ilişki semantiği veya testlerden hiçbirini kaldırmaz.

## Gerekçe ve sınırlar

- Timeout'u artırmak işi daha uzun süre bekletir; test maliyetini veya neden dengesiz olduğunu ölçmez. Daha küçük job'lar parça başına süreyi ve sonraki profillemeyi iyileştirir.
- Hash karşılaştırması, hash'in kapsadığı bütün persisted alanları içerdiğinden, unchanged row için güvenli no-op'tur. Değişen hash ise aynı upsert yolu üzerinden güncellenir.
- Yerel ölçümde aynı katalogla ikinci bootstrap 5,766 saniyeden 0,717 saniyeye indi; ilk bootstrap 6,884 / 7,502 saniye ölçüldüğünden bu iyileştirme ilk kurulum için hız kanıtı değildir.
- Sekiz parçanın gerçek GitHub süresi henüz ölçülmedi; push/PR koşusu gereklidir. Yeni dağılımın ayrıca ayarlanması `--durations=20` çıktısına göre yapılır.

## Doğrulama

- Yeni ilişki idempotency/update ve katalog bootstrap regresyonlarıyla `tests/catalog/test_series_relations.py` + `tests/integration/test_series_catalog_bootstrap.py`: **22 geçti**.
- `tests/acceptance`: **37 geçti**. Tüm lakehouse testleri **1.133** olarak keşfedildi; tam yerel paket büyük katalog maliyeti nedeniyle tamamlanmadı, bu nedenle tam-suite pass iddiası yoktur.
- Workflow YAML geçerli; A–H matrix'i test taşıyan 15 dizini birer kez kapsıyor. `compileall` ve `git diff --check` başarılı.
- Değişen test dosyası Ruff kontrolünden geçti. `series.py` için dört Ruff bulgusu mevcut HEAD'de de bulunduğundan bu değişiklikte yeni lint ihlali sayılmıyor. Yeni GitHub Actions koşusu henüz başlatılmadı.
