# ADR-0086 — Web kaynak yönlendirme planını metadata üzerinden üretme

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-19
- **İlgili çalışma:** PR #17 güvenli parçalarının aşamalı entegrasyonu, M1

## Bağlam

PR #17 web araştırmasını arama, kaynak keşfi, içerik okuma, tablo yükleme ve kanıt sunumuna kadar genişletiyor. Bu davranışı doğrudan merge etmek yerel `agent.py` / `tools/web.py` değişiklikleriyle çakışır ve bazı PR davranışları mevcut güvenlik/kanıt ilkeleriyle uyumlu değildir. Özellikle katalog verisinin bulunamaması tek başına internetten veri çekme izni veya kaynağın yayımlanmamış olduğunun kanıtı sayılamaz.

İlk adımda agent'a bağlanmadan, web araştırması için güvenilir kaynak ve sorgu planı üretme kurallarını ayrı, test edilebilir ve metadata güdümlü bir katmana almak gerekiyor.

## Karar

1. Kurum→host ve katalog kaynağı→izinli kamu domain'i eşlemeleri `config_data/source_hints.json` içinde tutulur; `source_hints.py` bunları normalize ederek uygulamaya verir.
2. URL normalizasyonu, host allowlist'i/suffix sınırı, web isteği/yasağı, açık kaynak sabitlemesi ve katalog metadata'sından sınırlı fallback arama planı `core/web_routing.py` içindeki saf fonksiyonlarda hesaplanır.
3. Fallback planı yalnız katalog adları ve sınırlı dönem işaretleri gibi kaynak keşfi için gereken metadata'yı kullanır. Ham kullanıcı prompt'u, SQL, yüklenmiş dosya içeriği ve veri satırları dış arama sorgusuna taşınmaz.
4. Kaynağa sabitleme varsa host kümeleri kesiştirilir; bilinmeyen/eksik kaynak metadata'sında, web açıkça yasaklandığında veya özel veri/gizli sorgu işaretlerinde plan fail-closed davranır.
5. Agent/tool akışına bağlama yalnız yetkili biçimde doğrulanmış katalog yokluğu durumlarında yapılır: `lakehouse_search` için `DATASET_NOT_FOUND` + boş aday listesi veya sorgu aracının `OUT_OF_COVERAGE` / `CONFIRMED_ABSENT` sonucu. SQL hatası, fetch/erişim hatası, kaynak uyuşmazlığı veya indekslenmemiş/pending aday otomatik web fallback'i başlatmaz.
6. Kaynak metadata'sı olmayan katalog araması ancak kullanıcı kamu kaynağını açıkça sabitlediyse ve query argümanı özel veri/SQL kalıbı taşımayan kısa bir konu sorgusuysa fallback planı kurabilir. Seri metadata'sı varsa arama sorgusu katalog adlarından ve sınırlı yıl işaretlerinden oluşturulur.
7. Uygun plan bulunduğunda web araçlarının şeması aynı turda açılır. `web_search` sorgu ve domain parametrelerini turn-scoped harness planından alır; model argümanları bu planı genişletemez. Otomatik fallback araması bir turda bir kez tüketilir ve yeni turda plan sıfırlanır.
8. Bot denetimini aşmaya yönelik sahte tarayıcı User-Agent alınmaz. Arama snippet'i sayısal veri kanıtı sayılmaz. Bu kararlar PR #17'nin topluca alınmaması yönündeki inceleme ile uyumludur.

## Gerekçe

- Yapılandırma koddan ayrıldığı için kaynak/domain listesi finans dışı yeni profillere uyarlanabilir; sorgu metnine veya tek bir demoya bağlı davranış eklenmez.
- Saf fonksiyonlar ağ çağrısı olmadan sınanabilir; URL parsing ve domain suffix hataları, hassas bağlamın dışarı sızması ve belirsiz kaynak pin'i erkenden yakalanır.
- Yönlendirme kararıyla veri toplama kararı ayrılır. Bu, katalogda bulunamama, kaynağa erişememe ve kaynağın gerçekten veri yayımlamaması durumlarını birbirine karıştırmayı önler.
- Aşamalı entegrasyon mevcut çalışma ağacındaki kullanıcı değişikliklerini korur ve her katmanın güvenlik/kanıt sözleşmesini kendi regresyonlarıyla doğrulamaya izin verir.

## Doğrulama

- `tests/test_web_routing.py`: URL/host normalizasyonu ve benzer görünen kötü hostlar, web niyeti/yasağı, domain pin'i ile allowlist kesişimi, kamu kaynağı metadata'sı, ham prompt/SQL sızıntısı, özel/eksik/bilinmeyen metadata'da fail-closed ve boş `SOURCE_HINTS_FILE` davranışı.
- İlgili erişim ve web testleri dahil agent-core tam suite: **855 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı.
- İlgili Ruff kontrolleri, kaynak JSON parse ve `git diff --check` başarılı.
- M2 agent/tool gate, negatif SQL failure ve Tavily plan clamp/tek arama regresyonları eklendi. Güncel agent-core suite: **860 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; değişen modüllerde Ruff `F`, JSON parse ve `git diff --check` başarılı. Gerçek Tavily ağı kullanılmadı.

## Sonuçlar ve riskler

- Artı: kaynak yönlendirmesi merkezi, metadata güdümlü ve deterministik test edilebilir.
- Sınır: otomatik fallback yalnız konfigüre edilmiş kamu kaynaklarında ve doğrulanmış yoklukta açılır; katalog adaylarının sırf bulunmaması (explicit source pin yokken) internet aramasına yetmez.
- Açık işler: gerçek katalog yokluğu statülerini araç sözleşmesinde doğrulamak; dinamik tool gate ve domain-filtered aramayı bağlamak; fetch cache'inin aynı-tur sınırını, içerik boyutu hata sınıfını, PDF/OCR provenance'ını ve kanıt UI'ını sonraki milestone'larda tamamlamak.
- Bu ADR web erişimi, scraping veya bot koruması aşma izni vermez.

## Alternatifler

- **PR #17'yi doğrudan merge etmek:** Reddedildi; yerel değişikliklerle çakışma ve sahte User-Agent, OCR doğruluğu ve cache sınırı sorunları.
- **Kaynak ve domain eşlemelerini Python kodunda tutmak:** Reddedildi; yeni kaynaklarda kod değişikliği gerektirir ve konfigürasyon testini zorlaştırır.
- **Ham kullanıcı sorusunu arama sorgusu olarak göndermek:** Reddedildi; özel içerik/SQL sızıntısı ve gereksiz arama bağlamı riski.
- **M1'de agent'ı hemen internet fallback'ine bağlamak:** Ertelendi; doğrulanmış yokluk ile hata/indeks gecikmesi ayrımı M2'de test edilmeden güvenli değildir.
