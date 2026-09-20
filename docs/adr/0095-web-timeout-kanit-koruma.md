# ADR-0095 — Web araştırma zaman aşımında kanıtı koruma

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-20
- **İlgili çalışma:** MIA benchmark web-research timeout incelemesi

## Bağlam

Web araştırması sırasında arama ve sayfa okuma araçları başarıyla çalışsa bile son model çağrısı zaman aşımına uğrayabiliyordu. Bu durumda kullanıcı genel bir servis hatası görüyor, o turda okunan kaynakların izi yanıta taşınmıyor ve mevcut oturum tablosu yeni isteğin yanıtıymış gibi karışabiliyordu. Ayrıca kanıt paneli `web_reads` alanını içeride ürettiği hâlde API serileştiricisi bunu UI'a aktarmıyordu.

## Karar

1. Anlatı/sonuç çağrısı kesilince bu turun başarılı web artefact'leri korunur. Okunmuş sayfa varsa yalnız kaynak okuma durumunu bildir; yalnız arama sonucu varsa onu açıkça “aday/bağlam, veri kanıtı değil” olarak bildir.
2. Bu fallback içerik sentezlemez, sayısal iddia üretmez ve başarı/ veri bulundu durumu vermez. `availability_status` `UNKNOWN` kalır; modelin tamamlayamadığı sentez doğrulanmış analiz gibi sunulmaz.
3. Web-only fallback kanıt paneli yeni, boş `AnalysisWorkspace` üzerinden kurulur. Önceki turun aktif tablosu veya kolonları bu isteğin kanıtına bağlanmaz; mevcut oturum çalışma alanı silinmez.
4. API `web_reads` alanını serileştirir. Böylece “okundu ancak tablo olarak seçilmedi” kaynakları kanıt yolculuğunda gösterilebilir.
5. Web kanıtı olmayan genel model kesintisinde cevap önceki tabloyu açıkça bu turun dışında tutar ve sayı üretmez.

## Gerekçe

- Başarılı araç işini atıp kullanıcıyı tüm pahalı araştırmayı yeniden çalıştırmaya zorlamaz.
- Kaynak okuma ile içerik doğruluğu/sentezi arasındaki sınırı korur; arama snippet'inden sayı çıkarılmaz.
- Önceki tablonun yeni ve ilgisiz soruya sızmasını önler.
- İç evidence sözleşmesi ile API/UI payload'ı aynı alan kümesini taşır.

## Doğrulama

- Gerçek ajan akışında: eski aktif tablo + web sayfası okuma + son çağrı timeout'u. Cevap `UNKNOWN`, tablo payload'ı boş, eski sayı yanıtta yok, okunan URL evidence `web_reads` alanında.
- Arama-only timeout senaryosunda URL `context_sources` içinde kalır ve metin snippet'lerin veri kanıtı olmadığını söyler.
- Tam agent-core suite: **899 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı. Benchmark sözleşmesi: 120 vaka / 76 oracle / 31 doğrulanmış artifact. Değişen modüllerde Ruff `F` ve `git diff --check` başarılı.
- Gerçek MIA/Tavily çağrısı yapılmadı; canlı servis davranışı manuel demo testinde doğrulanacak.

## Alternatifler

- **Araştırma artifact'lerini atıp genel timeout mesajı vermek:** Reddedildi; tamamlanmış kaynak edinimi görünmez olur ve tekrar iş üretir.
- **Okunan sayfaları otomatik özetlemek:** Reddedildi; bu yol yine model çağrısına/hesaplamaya ihtiyaç duyar ve doğrulanmamış sentezi doğrulanmış gibi sunabilir.
- **Önceki workspace tablosunu fallback'e eklemek:** Reddedildi; yeni sorunun bağlamına ait olduğu kanıtlanmış değildir.
