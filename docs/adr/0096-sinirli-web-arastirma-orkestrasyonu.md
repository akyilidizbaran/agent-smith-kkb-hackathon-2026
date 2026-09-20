# ADR-0096: Tur bütçeli web araştırma orkestrasyonu

**Durum:** Kabul edildi  
**Tarih:** 20 Eylül 2026  
**Bağlam:** ADR-0087, ADR-0088, ADR-0090 ve ADR-0095'in devamı

## Bağlam

Bir web araştırma turu arama, sayfa okuma ve sentez arasında kontrolsüz tekrar yapabiliyordu. 20 Eylül'deki manuel izde tur 116,2 saniye sürdü: ikinci arama kararı yanlışlıkla `narration` fazına ve 2.800 token bütçesine girdi; son sentez çağrısı ise 60 saniyede kesildi. Arama parçacıkları kanıt değildir; buna rağmen her ek arama modele yeni ve uzun bağlam ekliyordu. Sorun tek bir şirket sorusuna özgü değil, araştırma döngüsünün bütçesiz ve faz durumundan habersiz olmasından kaynaklanıyordu.

## Karar

Her kullanıcı turunda sıfırlanan `WebResearchState` araştırma kontrolünü harness'te tutar. Model kaynak arama ve okuma kararlarını verir; harness tekrarları, kapsamı ve dış metnin modele taşınan miktarını sınırlar.

- Varsayılan üst sınırlar tur başına **3 arama**, **5 benzersiz okunan sayfa** ve modele eklenen dış araştırma metninde **48.000 karakter**. Arama sonucu en fazla 5 aday ve aday başına en fazla 500 karakterlik snippet ile modele gider. Kaynak artifact'leri tam kalır; metin bütçesi dolunca yalnız modele giden bağlam kırpılır ve cevapta belirsizlik bildirimi eklenir.
- Arama sorguları Unicode/Türkçe harf normalizasyonuyla karşılaştırılır; aynı sorgu yeniden çalıştırılmaz. Önceki arama aday döndürdüyse yeni aramadan önce adaylardan en az biri okunmalıdır. Sonraki aramalar ayrıca `research_gap` alanında hangi doğrulanmamış iddiayı/çelişkiyi hedeflediğini belirtmelidir. İlk arama için bu alan gerekmez.
- Limit/tekrar hataları yeniden denenemez; “önce kaynağı aç” ve “araştırma boşluğunu belirt” hataları araç döngüsünü onarabilir. Tarayıcı `max_pages` değeri kalan tur bütçesine göre kırpılır.
- Web araştırması sürerken web arama/açma kararları `tool` token fazında kalır. Bu, başarılı bir önceki araç çağrısının anlatımın başladığı varsayılmasını önler. `tool` çağrılarında `LLM_TOOL_TIMEOUT_S`, anlatım ve recovery'de kendi süre sınırları uygulanır; fazlardan biri diğerinin timeout değerini devralmaz.
- Model sentezi sağlayıcı hatasıyla tamamlanamazsa var olan deterministik source-only fallback ve kanıt zinciri korunur. Okunmuş içerik kanıt panelinde kalır; yalnız arama adayı varsa snippet'ten sayı/özet üretilmez.

## Gerekçe ve alternatifler

Sabit tur bütçesi aynı kaynağı tekrar tekrar arayıp prompt'u büyütmeyi önler; `research_gap` farklı bir aramaya gerek olup olmadığını açıklar. Arama ve sayfa okuma için ayrı fazlar kontrol çağrılarını narration bütçesinden ayırır. Araştırma süresi için anlatım timeout'unu kullanmak reddedildi: bu, yavaş ama hâlâ ilerleyen araç kararlarını ilgisiz bir 60 saniye sınırıyla erken keser. Ayrı konulara/şirketlere özgü prompt kuralları eklenmedi.

Alternatif olarak tüm aramaları paralel başlatmak değerlendirildi. Kaynaklar okunmadan tekrar arama yapmak kanıt ayrımını zayıflattığı ve bağlamı büyüttüğü için bu aşamada seçilmedi. Bütçeler sonraki benchmark ölçümüne göre yapılandırılabilir; kullanıcı sorgusuna göre iç kodda istisna oluşturulmaz.

## Sonuçlar ve riskler

- Tekrar aramaların ve modele taşınan dış metnin üst sınırı belirgindir; kullanım sayaçları `usage.web_research` altında izlenebilir.
- Kaynağı açmadan yeni arama yapılamaması keşif hızını azaltabilir. Model bunu “yeni bilgi boşluğu” ile gerekçelendirebildiğinde farklı kaynağa geçebilir.
- Web `tool` fazındaki son LLM çağrısı hem yeni araç çağırabilir hem kısa sentez yazabilir; bu çağrının token fazı `tool` kalır. Uzun anlatı gerekiyorsa kısa ve kanıt bağlı cevap tercih edilir; geniş anlatı doğruluğun şartı değildir.
- Bütçe limitleri araştırmanın doğruluğunu tek başına garanti etmez. Kaynak sahipliği/şirket kimliği gibi iddialarda tüzel kişi eşleşmesi ve kaynak güvenilirliği sonraki benchmarklarda ayrıca puanlanmalıdır.

## Doğrulama

- `WebResearchState` birim testleri: sorgu normalizasyonu/tekrar, kaynak açma ve boşluk koşulu, sayfa/metin bütçesi.
- Agent entegrasyon testi: planning → web kontrolü için tool fazı → senteze giden tool fazı; çağrı başına token bütçesi ve tool timeout'unun narration timeout'undan bağımsız kalması.
- Tam `agent-core` suite ve benchmark v2.1 sözleşme doğrulayıcısı çalıştırılır. Canlı MIA/Tavily benchmark'ı bu ADR doğrulamasının parçası değildir.
