# ADR-0088 — Web fetch boyut sınırı ve tur kapsamlı cache

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-19
- **İlgili çalışma:** PR #17 entegrasyon planı, M4

## Bağlam

Web kaynağı indirme sınırını aştığında crawler bunu erişim engeli veya veri yokluğu gibi raporlayabiliyordu. Aynı sayfayı tablo seçimi için yeniden çekmek de aynı turda ikinci ağ/OCR maliyeti doğuruyordu. Süreçler arası ya da turlar arası kalıcı cache ise güncel olmayan içeriği güncelmiş gibi kullanma riski taşır.

## Karar

1. Fetch katmanı `ContentTooLarge` özel türü üretir; crawler bunu `blocked` veya `skipped` yerine `limit_exceeded` alanında taşır.
2. `web_url`, ana içerik tamamen boyut sınırında kaldığında `CONTENT_TOO_LARGE` hatası verir. Bu kod erişim hatası/veri yokluğu değildir ve aynı URL/bütçe ile yeniden denenmez. Erişilen sayfanın bazı tabloları varken başka bir bağlantı boyutu aşarsa kısmi kullanılabilir içerik sunulur ve aşım açık uyarı/artefact olarak kalır.
3. Başarılı bir `web_url` keşfi araç örneğinin belleğinde, yalnız aynı turda ve toplamda 8 kayıt / 16 MiB içerik sınırıyla tutulur. Yeni turda cache temizlenir; başarısız keşif ve sınırı aşan içerik cache'e girmez.
4. Cache anahtarı normalized locator, PDF sayfa seçimi, sayfa bütçesi ve derinlikten oluşur. Locator şema/host harf biçimini normalize eder, varsayılan portu ve fragment'i çıkarır; query/path korunur. Doğrudan sayfa okumada (`max_depth=0`) `purpose` çıkarılır, çünkü yalnız modelin amacı değişince alınan byte/çıkarım değişmez. Derin taramada amaç anahtarın parçasıdır; link sıralamasını etkileyebilir. `table_index`, `text_from` ve kullanıcı onayı cache kimliği değildir: var olan sayfa farklı tabloyu seçmek veya yeni metin aralığı göstermek için yeniden kullanılabilir.
5. Aynı turda aynı metin aralığı tekrar istendiğinde araç, aynı excerpt'i prompt bağlamına yeniden eklemek yerine önceki çıktıya yönlendiren kısa bir not döndürür. Yeni `text_from` aralığı cached belgeden sunulabilir. `refresh=true` cache'i atlar.
6. Cache kullanımı `web.cache_reused` artefact alanında görünür; veri provenance'ı kaynağın hash'i ve çekim zamanını korur. Cache diske veya sohbetler arasına yazılmaz.

## Gerekçe

- Boyut hatası ile HTTP/bot/robots erişim sonuçlarını ve kaynak yokluğunu birbirine karıştırmaz.
- Aynı kullanıcı turundaki keşif/seçim, amacı değişmiş doğrudan sayfa okuması ve tekrarlanan aynı metin penceresinde ağ, OCR ve prompt maliyetini azaltır.
- Derin taramada amaç kapsamını korur; farklı link ilgisi aynı cache girdisiyle karıştırılmaz.
- Kayıt ve byte sınırı, büyük belgelerin araç belleğini sınırsız büyütmesini önler.
- Süreç ve tur kapsamı dışına cache taşımamak bayat verinin sessizce kullanılmasını engeller.
- Refresh ve değişen keşif amacı açıkça yeni kaynağa gitmeye izin verir.

## Doğrulama

- Fetch/crawler ve web aracı testleri boyut aşımını, yapılandırılmış `CONTENT_TOO_LARGE` artefact'ini ve retry edilemez recovery davranışını doğrular.
- Başarılı same-turn seçim ve doğrudan sayfada amaç değişimi tek fetch yapar; derin taramada amaç değişimi, yeni tur ve `refresh=true` yeniden fetch eder; başarısız ve byte bütçesi üzerindeki keşif yeniden kullanılamaz.
- Aynı metin penceresinin tekrarında excerpt yeniden üretilmez; farklı pencere cached içerikten sunulur. URL normalizasyonu scheme/host/default-port/fragment regresyonlarıyla sınanır.
- Agent-core suite: ilk entegrasyon **870 geçti**; 20 Eylül cache düzeltmesi sonrası tam suite **899 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı. Canlı web/Tavily isteği yapılmadı.

## Alternatifler

- **Her `web_url` çağrısında tekrar çekmek:** Reddedildi; keşif→seçim çiftinde gereksiz ağ/OCR gecikmesi.
- **Amaç değişince her durumda yeniden fetch:** Reddedildi; doğrudan sayfa okumasında amaç içerik/çıkarımı değiştirmez. Derin taramada amaç link seçimini etkilediği için anahtarda tutulur.
- **Uzun ömürlü/diske yazılan URL cache'i:** Reddedildi; güncel olmayan kaynak içeriğini provenance olmadan yeniden kullanabilir.
- **Boyut sınırını erişim engeli veya veri yokluğu saymak:** Reddedildi; sebebi yanlış raporlar ve yanlış recovery davranışı doğurur.
