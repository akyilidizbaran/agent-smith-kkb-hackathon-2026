# ADR-0023: Web araması Tavily; sayfa çekme kendi uygulamamız

**Durum:** Kabul edildi · **Tarih:** 2026-09-10 · **Bağlam:** ADR-0021 (katman ayrımı)

## İhtiyaç
İki ayrı iş: (a) **arama** — "2023-03'te dünya piyasalarında ne oldu" tipi bağlam soruları,
Türkçe sonuç, tarih aralığı, haber odaklı; (b) **çekme** — verilen URL'den tablo/metin/PDF
(BIST100 sayfası, Borsa İstanbul PDF listesi).

## Karşılaştırma (2026)
| | Güçlü yanı | Ücretsiz | Bize uyum |
|---|---|---|---|
| **Tavily** | LLM-odaklı arama; `topic=news/finance`, `start_date/end_date`, `country`, `language`, `include_raw_content` | 1.000 kredi/ay, basic 1 kredi | (a) için tam |
| Exa | semantik/nöral arama | 1.000 istek/ay | araştırma ağırlıklı; bizim sorular anahtar-kelime + tarih |
| Firecrawl | sayfa → markdown, tarama | sayfa başına | (b) için iyi ama kendi fetch'imiz zaten çalışıyor |
| Serper | ham Google, en ucuz | — | LLM'e uygun biçim yok, sonradan işlem gerekir |

Not: Tavily Şubat 2026'da Nebius tarafından satın alındı; ADR-0021'in sağlayıcı-bağımsız
katmanı bu tür değişimlere karşı zaten koruyor.

## Karar
- `SearchClient.search` → **Tavily**, varsayılan `topic="news"`, `language="tr"`,
  soru bir dönem içeriyorsa `start_date/end_date`. Kredi: basic, 1/çağrı.
- `SearchClient.fetch` → **kendi uygulamamız**: `httpx` + `truststore` (BDDK/BIST için
  doğrulandı), HTML tablo için `read_html`, PDF için ADR-0022 yolu. Sağlayıcıya kredi
  ödenmez, çekme davranışı bizim kontrolümüzde kalır.
- Sağlayıcı `.env`'de: `SEARCH_PROVIDER=tavily`, `TAVILY_API_KEY`. DuckDuckGo anahtarsız
  yedek olarak ikinci uygulama.

## Tavily'nin kendi çekmesi
Tavily'nin `/extract` uç noktası var ("bir ya da daha çok URL'den LLM'e hazır temiz içerik");
Tavily'nin kendi önerisi de iki adım: `/search` → `/extract`. PDF desteği ve URL başına kredi
belgelenmemiş. Bu yüzden `fetch` için birincil uygulama bizim kodumuz; Tavily extract,
`SearchClient.fetch`'in **ikinci uygulaması** olarak eklenebilir (HTML sayfalar için hızlı,
PDF için değil). Arama sonucundan gelen URL'yi kendi `fetch`'imizle çekmek zaten çalışıyor.

## Sonuç
Web araçları `SearchClient`'a karşı yazılır; Tavily'yi değiştirmek bir uygulama dosyası.
Mentör kararıyla uyumlu: arama katmanı ayrı, provider-bağımsız.
