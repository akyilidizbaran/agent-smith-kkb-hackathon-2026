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
   emreder. Kanıt paneli web zinciriyle aynı: URL + belge sha256 + çekim zamanı + OCR bilgisi.
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

## Canlı prova (13 Eylül, demo günü PDF canlı verilecek)

Borsa İstanbul'un 20 PDF'i indirildi (8 metal tablosu tek sayfa yatay; 24 sayfalık aylık rapor
×7; 2–5 sayfalık elmas/cevher belgeleri; kmo.pdf) ve OCR hattından geçirildi:

| Belge | Sayfa | Süre | Sonuç |
|---|---|---|---|
| gümüş / paladyum / platin işlem ve ithalat tabloları | 1 (yatay) | 1,9–2,0 s | altınla aynı yapı, 14/14 sayısal |
| kmo.pdf (ödünç piyasası 2000–2026) | 1 (dikey) | 4,0 s | 104×5 tablo |
| cevher üretim bildirimleri | 2 (yatay) | 6,8 s | sayfa başına bir tablo, colspan başlık "ALTIN / GOLD \| Toplam", 14/14 sayısal, satır toplamı tutarlı |
| elmas ve kıymetli taş işlemleri | 4 (dikey) | 24,5 s | 15 tablo, ilk geçişte 0 sayısal kolon (aşağıda) |
| aylık piyasa raporu Haziran 2026 | 24 (dikey), 1–5 ve 6–10 okundu | 7,8 + 8,2 s | kapak/metin sayfalarında tablo yok, tablo sayfaları çözülüyor |
| ith_au sayfası JPEG q35 ölçek 1,0 (56 KB) | görüntü | 5,3 s | **sessizce yanlış**: başlıklar "Val / Year, Oct./Jan.", 2025 satırı 17.582 (gerçek 126.272) |

Dört kaçak ölçülüp kapatıldı:
1. **OCR virgülü nokta okuyor:** "133.119.720.04", "0.00" → hiçbir kolon sayıya çevrilemedi.
   `normalize_ocr_decimals`: son noktadan sonra tam 2 hane varsa ve hücrede virgül yoksa o nokta
   ondalık virgüldür; 3'lü gruplar dokunulmaz; yalnız OCR tablolarında.
2. **Tek noktalı sayılar belirsiz kalıyordu** ("1.484", "514.813"): tablo düzeyinde ayraç kuralı
   (aynı tablonun çözülmüş kolonları oy verir) ve karışık kolon kuralı (düz tam sayılarla yan yana
   3'lü gruplar binliktir). Kolon yalnız noktalı değerlerden oluşuyorsa yine belirsiz kalır, söylenir.
3. **Üç satırlı başlık ve birim satırı:** `promote_header_rows` 3 satıra kadar; "2025 | TL | USD |
   Miktar/Amount carat" gibi ilk hücresi rowspan'lı yıl artığı olan, kalanında rakam bulunmayan satır
   başlığa katılır (veri satırı olsa sayı taşırdı). Elmas tabloları 0/10 → **9/10**, 0/14 → 12/14 sayısal.
4. **Düşük kaliteli tarama sessizce yanlış:** iki deterministik kalite izi. (a) satır toplamı
   denetimi: toplam kolonu olan tabloda satırların kaçında öbür kolonların toplamı toplamla
   örtüşüyor; %50'nin altı "düşük". (b) yapı izi: başlıklar okunmadı ya da rakam-harf karışık hücre
   oranı ≥ %15 ve sayısal kolon < %30 → "belirsiz". İkisi de karta "DİKKAT … bu tablodan sayı verme"
   notu düşer; küçük görsel 2× büyütülerek OCR'a gider (bu örnekte yetmedi, uyarı devreye girdi).
5. **Sayfa seçimi ve zaman bütçesi:** `pages='3'`, `'2-4'`; belge başına 90 s; aşılınca okunan
   kadarı döner ve kart kalan sayfalar için `pages` ister. Kural prompt'ta.

6. **Tablo etiketi sayfa bağlamıdır:** cevher belgesinde sayfa 1 altın, sayfa 2 gümüş; iki tablo
   aynı yapıda, gümüş tablosunun başlığında metal adı yok. Ölçüldü (G18c, 0/2): model gümüş
   tablosunu "Altın/Gold tablosu" diye verdi. Her OCR tablosu "sayfa n: <sayfa başlığı>" etiketi
   taşır; liste kartı, yükleme kartı ve provenance bunu gösterir.

Golden G18a 2/2, G18b 2/2. G18c ilk 0/2 → etiketten sonra 3 koşuda üç cevap da doğru (28.088,44 kg,
gümüş 71.787 hiç geçmedi); bir koşu kanıt panelinde düştü: model belgenin güncelleme tarihini
"27.07.2026" diye yazdı, sayı ayrıştırıcı bunu 27,07 okudu. Tarih yazımları artık maskelenir (test).

## Açık kalan
- Rapor sayfalarında "%3,2" gibi işaretli yüzdeler ve yan yana ikiz tablolar kısmen metin kalıyor.
- RAW'a belgenin kendisi girmiyor (CSV giriyor); veri ekibinin `ingest-file`'ına "ek artifact"
  seçeneği eklenince kapanır.
- Taranmış/düşük kaliteli belge, yatay sayfa, çok sayfalı belgede tablonun bölünmesi ölçülmedi.
- Grafik görseli (çubuk/çizgi grafiğinden sayı okuma) OCR'ın işi değil; Qwen3.8 vision ile
  ayrı bir yol, planlı değil.
- OCR çağrısı süreç başına bütçelenmedi (Tavily'deki gibi); MIA'da kota yok (mentör), ama
  sayfa sınırı 5.
