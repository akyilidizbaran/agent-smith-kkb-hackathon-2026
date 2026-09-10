# ADR-0022: PDF'ten tablo çıkarımı — OCR öncelikli, metin katmanı yedek

**Durum:** Kabul edildi · **Tarih:** 2026-09-10 · **Ölçüm:** Borsa İstanbul altın PDF'leri, MIA Unlimited-OCR

## Bağlam
Demo günü Borsa İstanbul'un "Altın İşlemleri" PDF'inden değer çıkarılması istenecek
(açılış slaydında yazılı). En riskli parça buydu; ölçülmemişti.

## Ölçüm
İki gerçek PDF (`kmp_au.pdf` altın işlem verileri, `ith_au.pdf` altın ithalat), sayfa → PNG
(pypdfium2, 2x) → `kkbhackathon2026/Unlimited-OCR`, rehberdeki `<image>\ndocument parsing`
istemi ve `vllm_xargs` ayarlarıyla.

| | Metin katmanı (pypdfium2) | MIA OCR |
|---|---|---|
| `kmp_au` (çok satırlı başlık, TL/USD/EUR grupları) | 1.179 kr, başlıklar parçalanmış, tablo yapısı kayıp | 2,4 s · `<table>` **rowspan/colspan ile doğru**, sayılar okunuyor |
| `ith_au` (düz yıl×ay tablosu) | 4.433 kr, satırlar temiz | 4,7 s · ilk 4 sayı birebir eşleşti |

OCR her iki belgede de doğru; karmaşık başlıklı tabloda metin katmanından **üstün**.
Çıktı `<|det|>tür [x0,y0,x1,y1]<|/det|>` yerleşim etiketleri + HTML `<table>` — `pandas.read_html`
ile doğrudan DataFrame'e dönüyor.

**Tuzak:** OCR çıktısının başında anlamsız bir önek gelebiliyor ("ovi podataka i sistovosti…",
`ith_au`'da 150+ kr). İlk `<|det|>` öncesi atılmalı; atılmazsa tabloya karışmaz ama modele
giderse kafa karıştırır.

## Karar
1. **Tablolar için OCR öncelikli.** Sayfa PNG'ye çevrilir, OCR'a gider, `<table>`'lar
   `read_html` ile DataFrame olur. Yerleşim etiketleri (`title`, `header`, `table`)
   belgenin başlığını ve tablo sayısını verir — `DatasetSpec.description` için hazır girdi.
2. **Metin katmanı yedek ve düz metin için.** Prose/dipnot çıkarımında ve OCR başarısız
   olursa. Sayfa başına maliyet: OCR 2–5 s; metin katmanı anlık.
3. **Önek temizliği zorunlu:** ilk `<|det|>` öncesi atılır.
4. Sayfa başına tek görsel (3 görsel/çağrı sınırı var ama tek sayfa tek çağrı daha
   öngörülebilir); çok sayfalı PDF sayfa sayfa, ilk sayfada tablo yoksa devam.

## Sonuç
Demo senaryosunun en riskli parçası ölçüldü ve çalışıyor. `ingest_from_url` alt-agent'ının
PDF yolu: fetch → pypdfium2 render → OCR → önek at → `read_html` → profil → katalog (derived).
