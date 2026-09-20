# ADR-0090 — Web kanıtında arama, okuma ve tablo seçimi

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-19
- **İlgili çalışma:** PR #17 entegrasyon planı, M6

## Bağlam

Web araştırmasında arama sonucu yalnızca adaydır; URL'nin gerçekten okunması ve sayfadaki belirli bir tablonun analiz çalışma alanına alınması ayrı olaylardır. Önceki panel bu durumları tek bir `web_sources` listesinde gösteriyor, PDF çıkarım yöntemini, sayfa kapsamını ve seçilmiş tabloyu taşımıyordu. Ayrıca araç okuma/çıkarım hataları bazı kod yollarında ziyaret artefact'ini cevap nesnesine eklemiyordu. Anlatım servisi son aşamada kesilirse başarılı araç sonucunun ve tablonun da kaybolmaması gerekir.

## Karar

1. `context_sources` yalnız web aramasından gelen adayları taşır ve “bağlam, veri değil” olarak gösterilir.
2. Okunmuş fakat tabloya seçilmemiş sayfalar `web_reads` alanında tutulur. Kaynak URL, HTTP durum kodu, SHA-256, çekim zamanı ve varsa PDF çıkarım yöntemi/sayfaları saklanır.
3. Çalışma tablosuna alınan sayfalar `web_sources` alanında tutulur; `table_used=true`, tablo indeksi/etiketi/ölçüsü ve aynı tur cache kullanım bilgisi kanıta eklenir. Aynı URL'nin daha önceki discovery kaydı bu seçilmiş kaynakla birleştirilir.
4. Erişim engeli, atlanan URL ve indirme boyutu sınırı `web_unused` altında ayrı gerekçeyle gösterilir. Başarısız `web_url` çağrıları da mümkün olan erişim artefact'ini cevap kanıtına taşır.
5. Seçilmiş web kaynağının tam metadata'sı çalışma alanında sonraki turlar için hatırlanır. Cevap kanıtı API'si ve iki arayüz gösterimi (kanıt paneli ve kanıt yolculuğu) arama/okuma/tablo durumlarını birbirine karıştırmaz.
6. Anlatım çağrısı tablo yüklendikten sonra zaman aşımına uğrarsa doğrulanmış tablo, kaynak artefact'i ve kanıt paneli korunur; kullanıcıya tablo dışı yorum üretilmediği bildirilir. OCR uyarısı/çıkarım sınırı bu kurtarma yolunda kaybolmaz.

## Gerekçe

- Aday URL'yi okunmuş kaynak gibi veya okunmuş metni seçilmiş analiz tablosu gibi sunmak kanıt zincirini olduğundan güçlü gösterir.
- URL hash'i ve çekim zamanı, fetch edilmiş baytları; tablo indeksi ve ölçüsü ise çalışma tablosuna alınan yapıyı izlenebilir kılar.
- Aynı URL'nin discovery ve seçim artefact'leri birleştirilir; panelde çift kayıt oluşmaz.
- Başarısız anlatım veri alımını geri almaz ve gereksiz pahalı yeniden sorgu ihtiyacını azaltır.

## Doğrulama

- Web arama adayı, okunmuş PDF metin katmanı, seçilmiş tablo, boyut sınırı ve erişim engeli kanıtı offline fixture'larla sınanır.
- Gerçek `AnalyticsAgent` akışında anlatım timeout'u taklit edilir; çalışma tablosu, URL hash'i, tablo seçimi ve `FOUND` durumu cevapta korunur.
- `journeyStops` JavaScript'i Node üzerinden çalıştırılarak URL okunduğu halde tablo seçilmemiş durum doğrulanır.
- Tam regresyon, benchmark sözleşmesi/koşucu kontrolü ve sınırlı kamu URL smoke denemesi M7'de yürütülecek.

## Sonuçlar

- `EvidencePanel` sözleşmesine `web_reads` eklendi; arama adayları `context_sources`'ta, seçilen tablolar `web_sources`'ta kalıyor.
- API metadata'sı ve UI kanıt zinciri zenginleşti. `web_url` seçim/erişim hatalarının artefact'leri de saklanıyor.
- `web_reads` yapılandırılmış tabloyu garanti etmez; sayısal analiz talebi için tablo eksikliği ayrıca görünür kalır.
