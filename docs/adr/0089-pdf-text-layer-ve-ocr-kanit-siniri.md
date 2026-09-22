# ADR-0089 — PDF metin katmanı ve OCR kanıt sınırı

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-19
- **İlgili çalışma:** PR #17 entegrasyon planı, M5

## Bağlam

Web üzerinden açılan PDF'ler aranabilir metin katmanı veya yalnızca sayfa görüntüsü taşıyabilir. Mevcut OCR hattı belgeyi sayfa sayfa tablo olarak okur; OCR hücrelerinin aynı PDF içindeki searchable metinle bağımsız olarak karşılaştırılması yapılmıyor. Bu nedenle text-layer varlığı OCR tablosunu doğrulanmış saymaya yetmez. Ayrıca OCR kapalı veya başarısız olduğunda erişilebilir PDF'i “veri yok” gibi göstermek yanlıştır.

## Karar

1. PDF sayfalarının seçili aralığı pypdfium2 Unicode-aware `get_text_bounded()` ile okunur; metin ve sayfa sayısı/karakter bütçesi artefact metadata'sında tutulur.
2. Text-layer çıktısı yalnız düz metindir. Kod bunu yapılandırılmış tabloya dönüştürmez veya tablo bulunduğunu iddia etmez; bu yol `structured_tables=false` olarak işaretlenir.
3. OCR yapılandırılmış tablo çıkarmaya devam eder. Text-layer da varsa metin sayfa bağlamı olarak eklenir; OCR kalite kapısı, uyarı ve `ocr_unverified` davranışı aynen kalır. Hücre-hücre bağımsız karşılaştırma yapılmadığı açıkça yazılır.
4. Tarama PDF'inde text-layer yoksa veya OCR/text çıkarımı hata verirse, durum `DOCUMENT_EXTRACTION_FAILED` / çıkarım artefact'iyle veri yokluğu ve erişim engelinden ayrılır. OCR ya da metin katmanı hatası aynı baytlarla otomatik tekrar edilmez.
5. Kullanılan web tablosunun provenance uyarıları çıkarım yöntemi, okunan sayfalar ve toplam sayfa sayısını taşır. PDF'in hash/fetch zamanı mevcut kaynak iziyle korunur.

## Gerekçe

- Text-layer metin alıntısı sağlar; PDFium text API'si kendiliğinden tablo yerleşim analizi sağlamaz.
- OCR tablo yapısını bulabilir, fakat sayısal hücreleri hatalı okuyabilir. Kaynak metinle kıyaslama ve tablo bütünlüğü sağlanana kadar OCR uyarısı kalmalıdır.
- Belge çıkarım durumu erişim/yokluk semantiğinden ayrılır; anlatı “veri yok” sonucuna yanlış dönmez.
- Seçili sayfa ve metin bütçesi büyük belgelerde sınırsız işlemeyi önler.

## Doğrulama

- Offline PDFium fixture'ı yerel text-layer metnini doğrular; boş/taranmış PDF OCR istemcisi olmadan yapılandırılmış veri sunmaz.
- OCR+text-layer birleşiminde OCR sayısal tablo hâlâ unverified kalır; OCR hata verince yerel PDF metin katmanı kullanılabilir.
- PDF tablo çıkarımının başarısız olduğu `web_url` çağrısı `DOCUMENT_EXTRACTION_FAILED` döndürür ve `web.extraction` artefact'ini taşır.
- Agent-core suite: **876 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; ilgili Ruff `F` ve `git diff --check` başarılı.

## Alternatifler

- **Text layer var diye OCR değerlerini doğrulanmış saymak:** Reddedildi; PDF text API'si karakter metni verir, OCR hücre koordinatları/satır-kolon anlamıyla karşılaştırılmaz.
- **Tüm PDF'leri OCR'a bırakmak:** Reddedildi; searchable metin katmanı ücretsiz ve deterministic prose kanıtı sağlayabilir.
- **PDF text layer'ı heuristikle tabloya çevirmek:** Ertelendi; sütun/satır geometrisi güvenilir bir genel tablo sözleşmesi olmadan sayı üretiminde hataya yol açar.
