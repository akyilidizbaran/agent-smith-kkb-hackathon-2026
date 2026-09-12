# ADR-0041: Görüntü ve PDF girişi — sayfa → OCR → tablo, kanıt zinciri belgenin baytlarında biter

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Sıradaki:** D8 veri genişliği, D9 arayüz

## Bağlam
Demo açılış slaydı "Borsa İstanbul Altın İşlemleri PDF'inden değer çıkarma"yı açıkça istiyor.
ADR-0022 (10 Eylül) MIA `Unlimited-OCR`'ın bu PDF'lerde metin katmanından üstün olduğunu
ölçmüştü; kod yoktu. Kloudeks tek anahtarla üç model veriyor (sohbet, embedding, OCR); OCR
`/chat/completions` ucundan base64 `image_url` ile çalışır, çağrı başına 3 görsel.

## Karar
1. **Tek giriş noktası, iki araç.** `web_url` bir PDF/PNG/JPG adresi ya da izinli kökteki belgeyi
   görünce OCR yoluna girer ve tabloları HTML sayfası gibi listeler/yükler; `ingest_from_url`
   aynı yolu izleyip seçilen tabloyu (en büyük ya da `table_index`) izinli köke CSV yazar ve
   veri ekibinin `ingest-file` komutuna o CSV'yi verir. Araç sayısı değişmez.
2. **Hat deterministik** (`vision/ocr.py`): pypdfium2 ile sayfa → PNG (2×), en çok 5 sayfa
   (`truncated` bayrağı), sayfa başına tek OCR çağrısı (rehberdeki `<image>\ndocument parsing`,
   `temperature=0`, `skip_special_tokens=false`, `vllm_xargs`), ilk `<|det|>` öncesi atılır.
3. **OCR HTML'i sayfa HTML'i gibi işlenir** — aynı `_string_tables` ve profilci sayı dilbilgisi
   (ADR-0034). Bunun için iki genelleme gerekti, ikisi de ölçülerek:
   - `<td rowspan=2>AY/MONTH</td><td colspan=3>TL</td>…` açılmadan üst başlıklar yanlış kolonlara
     kayıyordu; `_grid_rows` colspan/rowspan'ı ızgaraya açar (read_html davranışı).
   - OCR başlığı `<th>` değil ilk satır(lar)da `<td>` verir; `promote_header_rows` hiç rakam
     içermeyen ilk en çok 2 satırı kolon adı yapar, çok satırlı başlığı "TL | Hacim" diye birleştirir.
   - "-", "n.a.", "…" yer tutucuları boş sayılır: tek "-" hücresi altı ay kolonunu metin bırakıyordu.
   - Kart tablosu bilimsel gösterim yazmaz (93.824.682.381 kartta 9.38e+10 çıkıyordu).
4. **OCR bir okumadır, doğrulama değil.** Sayfa notu ve provenance uyarısı "görüntüden OCR ile
   okundu (model, sayfa), sayılar doğrulanmadı" der; kart modele bunu kullanıcıya söylemesini
   emreder. Kanıt paneli web zinciriyle aynı: URL + belge sha256 + çekiliş zamanı + OCR bilgisi.
5. **OCR yoksa uydurma yok.** `VISION_MODEL` tanımsızsa belge "OCR olmadan okunamaz" der;
   servis hatası sayfa notuna düşer, tablo boş kalır.
6. **Ingest provenance.** RAW'a OCR tablosunun CSV'si girer (veri ekibinin CLI'ı tablo dosyası
   alır); belge bayt bayt izinli köke kopyalanır, sha256'sı, sayfası, tablo numarası ve OCR
   modeli katalog açıklamasında ve kartta. RAW'a belgenin kendisinin girmesi açık iş.

## Ölçüm (13 Eylül, Borsa İstanbul PDF'leri, MIA Unlimited-OCR)

| Belge | Sayfa | OCR süresi | Tablo | Sonuç |
|---|---|---|---|---|
| `ith_au.pdf` altın ithalat (kg), yıl×ay | 1 | 5,8 s (8.867 kr) | 32×14, **14/14 kolon sayısal** | 2025 Ocak 9.654,00; başlıklar "Yıl / Year", "Oca./Jan."… |
| `kmp_au.pdf` altın işlem, çok satırlı başlık | 1 | 1,9 s (2.908 kr) | 13×11, başlıklar "TL \| Hacim/Volume (TL)" … | 2026 Ocak TL hacmi 93.824.682.381; "13.837" belirsiz bırakıldı (binlik mi ondalık mı) — doğru |

İlk denemede `ith_au` 8/14 sayısal (tek "-" hücresi) ve `kmp_au` başlıkları kaymış (colspan)
çıktı; ikisi de ölçülüp düzeltildi. Birim testleri 287 → 296 (OCR temizleme, PDF render,
rehber istek biçimi, belge sayfası, `web_url` PDF, ingest PDF → CSV → CLI, OCR yoksa red,
ızgara/başlık/yer tutucu). Golden G18a/G18b: §Golden.

## Golden (MIA Qwen3.8-27B + Unlimited-OCR, yerel PDF fikstürleri, 13 Eylül)

| Vaka | Soru | Sonuç | Adım | Süre | Prompt token |
|---|---|---|---|---|---|
| G18a altın ithalat | "2025 Ocak ayı altın ithalatı" (`ith_au.pdf`) | **2/2** | 2 (`web_url` liste → yükle) | 26 s | 35,6k |
| G18b altın işlem | "2026 Ocak TL altın işlem hacmi" (`kmp_au.pdf`) | **2/2** | 2 | 21 s | 50,4k |

G18b ilk koşuda 0/2: kanıt paneli sorudaki "2026"yı ve biçimi belirsiz diye metin kalmış
"13.837" / "1017" hücrelerini "tabloda yok" sayıyordu. Soruda geçen sayı yankı sayılır (anlatı
doğrulamayla aynı kural), metin hücreler Türkçe dilbilgisiyle okunup karşılaştırılır; sonra 2/2.
Cevaplar kartın istediği gibi "OCR ile okundu, doğrulanmadı" uyarısını taşıdı. Demo kabul (11 senaryo,
G18a dâhil, mevcut DB): **11/11**, kanıt zinciri 11/11; HTML tablo hattındaki genellemeler G11a/G13'ü bozmadı.

## Açık kalan
- RAW'a belgenin kendisi girmiyor (CSV giriyor); veri ekibinin `ingest-file`'ına "ek artifact"
  seçeneği eklenince kapanır.
- Taranmış/düşük kaliteli belge, yatay sayfa, çok sayfalı belgede tablonun bölünmesi ölçülmedi.
- Grafik görseli (çubuk/çizgi grafiğinden sayı okuma) OCR'ın işi değil; Qwen3.8 vision ile
  ayrı bir yol, planlı değil.
- OCR çağrısı süreç başına bütçelenmedi (Tavily'deki gibi); MIA'da kota yok (mentör), ama
  sayfa sınırı 5.
