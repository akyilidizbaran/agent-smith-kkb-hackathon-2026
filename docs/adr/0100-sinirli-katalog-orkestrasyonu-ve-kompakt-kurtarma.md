# ADR-0100 — Sınırlı katalog orkestrasyonu ve kompakt kurtarma

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-20
- **İlgili çalışma:** V2 ilk 10 vaka MIA benchmark'ında görülen katalog arama döngüleri ve recovery zaman aşımı

## Bağlam

İlk 10 vaka koşusunda P05, R02 ve R03 çok sayıda katalog araması, yinelenen çağrı ve uzun recovery bağlamı üretti. Bazı tablosuz recovery çağrıları zaman aşımına uğradı; harness, arama veya araç hatasıyla karşılaşmış olmayı kimi zaman model servisinin genel kesinti mesajına indirgedi. Aynı sorun tek bir soru biçimine bağlı değil: keşif araçlarının sınırlandırılması, kanıt durumunun taşınması ve başarısız turun güvenli kapatılması gerekiyor.

## Karar

1. `lakehouse_search` çağrıları tur başına varsayılan **5 gerçek yürütmeyle** sınırlıdır. Limit `AnalyticsAgent` kurucusunda ayarlanabilir; yinelenen imzalar mevcut döngü kilidince ayrıca engellenir. Limit aşımı `CATALOG_SEARCH_BUDGET` terminal hatasıdır; bu durum tek başına veri yokluğu kanıtı sayılmaz.
2. Recovery ve adım/süre sınırı çağrıları tüm araç konuşmasını yeniden göndermez. Kısa istek, mevcut availability durumu, son dört hata özeti, yalnız doğrulanmış aktif tablodan türetilen `NarrationFacts` ve en çok üç yerel katalog/şema çıktısı kullanılır. Katalog metni talimat değil veri olarak etiketlenir; web sayfa gövdeleri ve diğer ham araç geçmişi recovery bağlamına taşınmaz.
3. Model servisi recovery sırasında yanıt vermezse harness `CONFIRMED_ABSENT`, `ACCESS_BLOCKED` ve `RETRIEVAL_FAILED` durumlarını deterministik olarak kullanıcıya aktarır. Retrieval hatası, verinin kaynakta bulunmadığı biçiminde sunulmaz; sayı uydurulmaz. Durum `UNKNOWN` ise önceki genel kesinti cevabı korunur.
4. Metrikler artifact'e katalog arama sayısını, sınırı ve sınırın dolup dolmadığını ekler. Bu alanlar benchmark'ta çağrı azalmasıyla birlikte doğruluk ve kapsam kaybı olup olmadığını ölçmek için kullanılacaktır.

## Sonuçlar ve riskler

- Farklı sözcüklerle yinelenen katalog keşfi aynı turu sınırsız büyütemez; başarısız recovery tüm konuşma geçmişini tekrar işlemez.
- Beşten fazla ayrı katalog araması gerektiren geçerli bir istek erken sonlanabilir. Sınır yapılandırılabilir; MIA benchmark tekrarında doygunluk ve doğru sonuç oranı birlikte ölçülmeden daha düşük değere ayarlanmaz.
- Recovery timeout'unda cevap daha kısa ve daha az yorumlayıcı olabilir; buna karşılık kanıt durumu kaybolmaz ve kullanıcı hatayı veri yokluğu sanmaz.

## Doğrulama

- Yinelenen keşif, arama bütçesinin tükenmesi, kompakt recovery bağlamı, retrieval hatasında yanlış yokluk iddiası ve yetkili yokluk bilgisinin korunması için regresyon testleri.
- Tam `agent-core` testi, benchmark sözleşme doğrulayıcısı ve hata/lint kontrolü.
- Gerçek MIA A/B koşusu sonraki ölçüm adımıdır; yerel testler provider latency kazanımını kanıtlamaz.
