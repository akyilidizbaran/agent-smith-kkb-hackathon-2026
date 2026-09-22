# ADR-0087 — Web arama adayları ile veri kanıtının sınırı

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-19
- **İlgili çalışma:** PR #17 entegrasyon planı, M3

## Bağlam

Web arama sağlayıcısı doğru domain filtresi alsa bile dönen URL'ler dış sağlayıcı girdisidir. Sağlayıcı davranışı tek başına güven sınırı olamaz. Arama snippet'i sayısal değer, yönlendirme veya gömülü talimat içerebilir; model onu okunmuş kaynak gibi kullanırsa kanıt panelinde açılmamış bir sayfadan veri üretilmiş olur. Resmî kaynak sayfaları da çoğu zaman landing page olarak başlar ve gerçek CSV/XLSX/PDF aynı host altında bulunur.

## Karar

1. Kullanıcının URL/kurum kaynak pini Tavily `include_domains` alanına uygulanır; modelin `include_domains` argümanı pini genişletemez.
2. Sağlayıcı sonuçları ayrı bir denetimden geçer. Yalnız HTTP(S), geçerli, kimlik bilgisi/port taşımayan ve özel/loopback olmayan URL'ler aday olabilir. Pinned domain varsa sonuç hostu tam host ya da onun alt domain'i olmalı; `evil-bddk.gov.tr` veya `bddk.gov.tr.evil.example` eşleşme sayılmaz.
3. Aramadan geçen URL'ler `sanctioned_locators`'a alınır; reddedilen URL'ler `web_url`'e açılamaz. Arama sonucu tablo veya kaynak kanıtı değildir.
4. Arama yanıtındaki snippet `web_search` aracının model bağlamında yalnız kaynak keşif ipucudur ve hiçbir durumda agent'ın sayısal grounding havuzuna eklenmez. Agent kaynak sayfası açılmadan nihai cevaba geçerse sayısal/factual anlatı yerine deterministik aday/okunma durumu verir.
5. Bilinen doğrudan tablo dosyaları (CSV/TSV/XLS/XLSX/JSON) ve PDF önce sıralanır. Landing page taraması `web_url`'in sayfa/derinlik bütçeleri içinde kalır; bir adım derinlikte crawler yalnız başlangıç URL'siyle aynı host sınırındaki bağlantıları izler. Robots ve fetch güvenlik sınırları aynen geçerlidir.
6. Arama artefact'i aday URL/title, doğrudan dosya işareti, kaynak/domain denetiminden reddedilen adet ve snippet'in doğrulanmadığı bilgisini taşır. Bu alanlar arama bağlamını kullanılan web tablosundan ayrı tutar.

## Gerekçe

- Sağlayıcı filtresi gecikmeyi ve kapsam dışı sonuçları azaltır; post-filter ise sağlayıcı hatası veya test doubles kaynaklı ihlali kapatır.
- İçerik snippet'inin grounding'den çıkarılması, açık URL fetch ve veri/tablo provenance'ı olmadan sayısal iddia yayımlanmasını engeller.
- Aynı hostta sınırlı keşif, kullanıcıdan her dosya URL'sini istemeden landing page'lerden veri dosyasına ulaşır; dış hosta otomatik geçiş yaratmaz.
- Doğrudan dosyaların öncelemesi, web research akışında HTML özetini tekrar tekrar açma ihtiyacını azaltır.

## Doğrulama

- Tavily fake-session testleri explicit domain'in sağlayıcıya geçtiğini ve daha güçlü sonuç denetiminin lookalike, malformed, credentials ve script URL'lerini reddettiğini doğrular.
- Arama sonucunda doğrudan dosya ilk sıraya alınır; PDF linki crawler'da veri dosyası olarak sınıflanır ve aynı-domain tarama mevcut regresyonla sınanır.
- Agent testinde snippet'teki sayısal değer nihai cevaba taşınmaz; sayfa açılmadığı için cevap `NOT_VERIFIED` kapanışıdır.
- M3 sonrası agent-core suite **864 geçti**, 1 mevcut Starlette/AnyIO deprecation uyarısı; değişen modüllerde Ruff `F` ve `git diff --check` başarılı. Canlı Tavily çağrısı yapılmadı.

## Alternatifler

- **Yalnız sağlayıcı `include_domains` filtresine güvenmek:** Reddedildi; sağlayıcı dönüşü ayrı trust boundary'dir.
- **Snippet'i normal tool output'u gibi grounding'e katmak:** Reddedildi; citation/search excerpt sayısal veri kaynağı değildir.
- **Landing page'den farklı domaine otomatik geçmek:** Reddedildi; arama adayını açma politikası ancak same-domain crawl ile sınırlandırılır.
- **Tüm kaynak içeriğini tek `web_search` cevabında anlatmak:** Reddedildi; kaynak sayfası ve tablo `web_url` aracılığıyla açıkça okunmalı ve provenance almalı.
