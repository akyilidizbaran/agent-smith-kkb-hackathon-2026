# Branch özeti — `feature/lakehouse-source-access`

**Sahip:** Elif Güngen

**Amaç:** EVDS ve BDDK Aylık kaynaklarını ortak lakehouse sözleşmesine uygun
biçimde RAW ve Bronze sınırına getirmek.

## Neden yapıldı?

Harici veri kaynaklarının endpoint, tarih, sayı ve hata davranışları birbirinden
farklıdır. Bu dal, kaynak ayrıntılarını sistemin geri kalanından ayırır. Böylece
Silver ve agent ekipleri HTTP endpointlerini veya ham JSON biçimlerini bilmeden
kararlı `ParsedBatch` çıktılarıyla çalışabilir.

## Neler yapıldı?

- EVDS Connector ve Parser
- BDDK Aylık Connector ve Parser
- İstek zamanı ile gerçek indirme zamanının ayrılması
- API anahtarının yalnız ortam değişkeninden okunması
- BDDK'nın tek `kalemSutun` kuralının doğrulanması
- Gerçek cevap biçimlerini temsil eden secretsız fixture'lar
- Tarih, sayı, null, hata, retry ve gözlem sayısı kontrolleri
- Tamamen ağsız unit ve integration testleri
- Kaynak anomalileri ve doğrulama seviyelerinin belgelenmesi

## Sorumluluk sınırı

Connector yalnız veriyi indirir ve değişmez RAW dosyasına yazar. Parser RAW
dosyasını okuyarak kaynağa sadık Bronze tablosunu üretir. Stok/akım yorumu, birim
dönüşümü, frekans hizalama ve Gold analizi bu dalın işi değildir.

## Önemli kimlikler

- `evds:TP.KTF12` — haftalık konut kredisi faiz oranı
- `bddk_monthly:1534_Toplam` — aylık konut kredisi bakiyesi
- Dataset kimlikleri: `evds_housing_interest` ve
  `bddk_monthly_housing_loans`

## Kanıt ve bilinen sınır

- Endpoint ve seri kodları tahmin edilmemiş, kaynak dokümanlarıyla kaydedilmiştir.
- Fixture testleri internet olmadan tekrar üretilebilir.
- EVDS'in resmî API anahtarlı endpoint'i, anahtar sağlandığında dar bir canlı
  smoke test ile tekrar doğrulanmalıdır.

## İlgili commitler

- `5c3e035` — EVDS ve BDDK Aylık connector/parser uygulaması
- `a734995` — toplantı ve gereksinim inceleme notları
- `9a5dc8a` — Source Access karar ve hazırlık dokümantasyonu

Bu çalışma daha sonra `feature/lakehouse-integration` dalına alınmıştır.
