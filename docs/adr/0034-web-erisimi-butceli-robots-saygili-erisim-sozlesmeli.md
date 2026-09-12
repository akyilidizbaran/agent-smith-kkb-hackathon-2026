# ADR-0034: Web erişimi — bütçeli, robots'a saygılı, erişim sözleşmesinden geçen; arama yalnız anahtar varsa

**Durum:** Kabul edildi (C3) · **Tarih:** 2026-09-12 · **Sıradaki:** D fazı (ön-yükleme, BM25, kararlılık, demo kabul)

## Bağlam
Şartname web araması ve URL okuma araçlarını sayıyor; mentör "web search serbest" dedi ama
üç sınır koydu (12 Eyl): hesap açılmaz, CAPTCHA/bot denetimi aşılmaz, kimlik bilgisi yalnız
gizli katmanda; erişilemeyen kaynak açıkça söylenir ve seçenek sunulur; kullanıcı kaynağı
sabitlediyse sessizce başka kaynağa geçilmez; tarama bütçe ve ilgi tabanlıdır. A1 (ADR-0028)
bunları erişim sözleşmesi olarak yazmıştı; C3 sözleşmenin üstüne aracı koyuyor.

İki ölçüm tasarımı belirledi:
1. **`requests` yoktu.** Sahte oturumla geçen testler gerçek bir adrese hiç çıkmamıştı; ilk
   canlı çağrı `ModuleNotFoundError` ile düştü ve G11c "erişilemez" vakası yanlış sebeple
   geçti. httpx üstünde dar bir oturum yazıldı (`web/session.py`), TLS OS deposundan
   (`truststore`), `verify=False` asla.
2. **pandas'ın sayı tahmini yüz kat hata üretti.** `read_html(thousands=".")` TCMB sayfasının
   "31.51"ini 3151 yaptı — sessiz. Tablolar artık METİN olarak çıkarılır, sayıya çevirme
   profilcinin (B1) dilbilgisiyle yapılır: hangi (ondalık, binlik) çiftinin kolonun %100'ünü
   ayrıştırdığı ölçülür; birden çok çift farklı sayılar veriyorsa ("3.151") kolon metin kalır
   ve araç kartına not düşer. Yüzde işareti ve NBSP hücreden atılır, dilbilgisine dokunulmaz.

## Karar 1 — `web_url`: oku, listele, istenirse tabloyu yükle; erişemezsen sözleşmeyle dön
`web_url(url, purpose, table_index?, max_pages≤5, max_depth≤1)`:
- **Sınırlar:** http(s) ya da izinli kökteki yerel dosya; özel/loopback adres yok (SSRF);
  sayfa başına bayt sınırı; robots.txt host başına bir kez çekilir ve uyulur (`Disallow` →
  `blocked/robots_disallow`, sayfa hiç istenmez); User-Agent kendini tanıtır.
- **Bütçeli tarama:** aynı alan adı; önce doğrudan veri bağlantıları (.csv/.xlsx/.json),
  sonra soru ve amaç sözcükleriyle örtüşen bağlantılar; sayfa, derinlik ve süre sınırı;
  taranıp kullanılmayan ve erişilemeyen sayfalar `artifacts["web"]` ile **kanıt paneline**
  gider, cevaba değil.
- **Liste modu** (ilk çağrı): başlık, HTTP, bayt, sha256, çekiliş zamanı, tablolar
  (numara, boyut, kolonlar, ilk 3 satır), metin özeti, sayı biçimi notları, **yıl
  denetimi** (soruda geçen yıl sayfada hiç geçmiyorsa "DİKKAT: … GEÇMİYOR — kaynak sabitse
  bulunmadığını söyle, uydurma") ve erişim satırı.
- **Yükleme modu** (`table_index`): tablo aktif analiz tablosu olur; provenance
  `web_url <url> tablo#k`, `source_urls=[url]`, uyarıda sha256 + zaman + HTTP + "birimler
  sayfanın beyanı, katalog doğrulaması yok".
- **Erişilemezse** ADR-0028 zarfı: `ACCESS_BLOCKED / NEEDS_CREDENTIAL / SOURCE_NOT_FOUND`,
  tekrar denenmez; kaynak sabitse "KAYNAK SABİT — kullanıcıya sor", serbestse "alternatif
  denenebilir, açıkça yaz".

## Karar 2 — `web_search` yalnız anahtar varsa; sonuç veri değildir
Tavily (`TAVILY_API_KEY`). Anahtar yoksa araç **kayıt edilmez** ve prompt'a "web araması bu
ortamda kapalı; kullanıcıdan adres iste" kuralı girer — olmayan aracı öğütlemek
UNKNOWN_TOOL üretir, taklit etmek sözleşmeyi bozar. Anahtar varsa sonuçlar başlık + adres +
alıntıdır; sayı oradan okunmaz, sayfa `web_url` ile açılır. 401/429/ulaşılamaz → aynı zarf.

## Karar 3 — Kanıt zinciri web'de sayfanın baytlarında biter
Web tablosunun kolonları için Silver gözlemi aranmaz; zincir `URL + sha256 + çekiliş zamanı
+ HTTP` ile **tam** sayılır ve panelde "WEB KAYNAĞI" satırı olur. Taranıp kullanılmayan
sayfalar "TARANDI, KULLANILMADI / ERİŞİLEMEDİ" altında.

## Ölçüm
- Birim testleri 208 → **229**: çekme (sha+zaman, robots, bot/404/ulaşılamaz, izinli kök,
  boyut), çıkarım (tablo/metin/bağlantı, CSV, nokta ondalık, belirsiz biçim, yüzde), tarama
  (bütçe ve öncelik, derinlik 0), araç (liste → yükle, yıl yok notu, sabit kaynakta sor,
  bot engelinde hesap seçeneği yok, yerel fikstür, olmayan tablo), arama (anahtar yok →
  NEEDS_CREDENTIAL, sonuç veri değil), kanıt zinciri.
- **Golden G11**, üç erişim hâli yerel fikstürlerle (ağ yok, deterministik), MIA:
  - G11a **var**: 3/3, 2 adım (liste → yükle), cevap 31,07 tablodan.
  - G11b **yok**: 3/3, 1 adım; sayfa açıldı, 2025 yok, agent "bulunmuyor" dedi, lakehouse'a
    geçmedi, 2024'ü 2025 diye vermedi. Golden şemasına `table_optional` eklendi.
  - G11c **erişilemez**: 3/3, 1 adım, `ACCESS_BLOCKED`; agent erişemediğini ve sebebini söyledi.
- Gerçek siteler: TCMB Tüketici Fiyatları sayfası HTTP 200, 96 KB, 0,5 s, 260×3 tablo,
  31,51 doğru okundu; BDDK eski adres 404 → `SOURCE_NOT_FOUND` + kaynak sabit kuralı; TÜİK
  bülten sayfası 2 KB JS kabuğu, tablo yok, "2025 geçmiyor" notu — yanlış iddia yok.

## Açık kalan
- Tarama derinliği 1 ile sınırlı; PDF okunmuyor (kurum bültenleri çoğu PDF) — D fazı adayı.
- JS ile dolan sayfalar (TÜİK) boş gelir; tarayıcı yok ve olmayacak (bot denetimi çizgisi).
- `web_search` anahtar olmadan ölçülemedi; Tavily anahtarı gelirse aynı testler canlıda koşar.

## İlgili
ADR-0028 (erişim ve geri çekilme sözleşmesi), ADR-0030 (profilci dilbilgisi), ADR-0033
(kanıt paneli). Mentör kararları 12 Eyl.
