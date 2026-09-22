# ADR-0093 — Genel analitik kapasitesi ve SQL sözdizimi toparlama

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-20
- **İlgili çalışma:** MIA benchmark analitik ve araç çağrısı hataları

## Bağlam

Analitik istekler bazı veri kümelerinde ham tabloya dönüşebiliyor. Tek değişkenli aykırılık aracı takvim ayı mevsimselliğini modelleyemiyor. Ayrıca SQL parser hataları güvenlik/politika reddiyle aynı hata koduna düştüğünde model güvenli bir sorguyu düzeltmek yerine yanlış güvenlik engelini tekrar edebiliyor.

## Karar

1. Aylık ve yeterli geçmişe sahip seriler için `seasonal_mad` eklenir: aynı takvim ayları yıllar arasında medyan/MAD ile karşılaştırılır. Yeterli gözlem yoksa yöntem sonuç uydurmaz, kullanıcıya sınırı bildirir.
2. Analitik araç girdisi mevcut tablo, zaman ekseni ve kolon doğrulamasına tabi kalır; yöntem deterministik hesaplanır ve sınırlaması araç çıktısında belirtilir.
3. SQL ayrıştırma/sözdizimi hataları `SQL_SYNTAX_ERROR` olarak retryable bildirilir. DDL, birden fazla statement, dış tablo erişimi ve diğer politika ihlalleri `UNSAFE_SQL` olarak kalır.
4. Yeni hata kodu yalnızca sözdizimi düzeltme yolunu açar; SQL güvenlik guard'ları gevşetilmez.

## Sonuçlar

- Analitik kapsamı, modelden seriye özgü hesap formülü istemeden genişler.
- Güvenli ama hatalı SQL için düzeltme turu mümkün olur; güvenlik sınırı ayrı ve katı kalır.

## Doğrulama

- Seasonal MAD yöntem ve tool testleri; yetersiz/aylık olmayan zaman ekseninde ret testleri.
- `UNION ALL` ve hatalı SQL parse testleri; tam agent-core ve lakehouse CI testleri.

