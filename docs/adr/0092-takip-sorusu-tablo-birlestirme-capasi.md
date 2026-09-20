# ADR-0092 — Takip sorusunda aktif tablonun birleştirme çapası olması

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-20
- **İlgili çalışma:** MIA benchmark follow-up state kaybı

## Bağlam

Bir takip mesajı yeni kaynak veya seri ekleyebilir. Mevcut takip sınıflandırması bunu her zaman önceki tabloyu kullanma isteğinden ayıramaz; önceki tablodaki seri kimlikleri/provenance kaybolabilir veya yalnız eski tablo yanıt olarak dönebilir.

## Karar

1. Aktif tabloya açık gönderim, birleştirme/ekleme eylemi ve yeni hedef alanı birlikte varsa istek tablo bileşimidir.
2. Önceki doğrulanmış tablo, seri kimlikleri ve provenance'ı yeni isteğin birleştirme çapası olarak modele aktarılır.
3. Yeni istenen kaynak veya seri yine katalogdan keşfedilip doğrulanır; eski tablonun tek başına yeni isteği karşıladığı kabul edilmez.
4. Join anahtarı ve kapsam uygunluğu workspace/Gold araçlarının doğrulamasına bırakılır. Açık tablo referansı yoksa sıradan yeni sorgular eski tabloyu miras almaz.

## Sonuçlar

- Takip dönüşümleri önceki aktif veri kimliğini koruyabilirken yeni kaynak ekleme yeni retrieval ve doğrulama gerektirir.
- Harness sorgu cümlesine özel dataset ID veya seri kuralı taşımaz.

## Doğrulama

- Takip niyeti sınıflandırması, provenance bağlamı ve aktif tablo guard'ı için agent testleri.

