# Finans alanı — bankacılık ve makro seriler

Bu dosya motorun DEĞİL alanın bilgisidir. `## measure_rules` ve `## evidence_domains`
bölümlerini kod okur; `## note:` ve `## template:` bölümleri modele gider (bütçe
altındaysa gömülü, üstündeyse `lookup_domain_note` ile). Alias'lar burada değil,
katalogda (`ColumnSpec.aliases`) tutulur.

## measure_rules

| semantic_type | allowed | forbidden | hint |
|---|---|---|---|
| stock | last, diff, pct_change | sum | Stok serisi dönem sonu bakiyesidir; aylık toplamı anlamsız, değişim için ardışık fark alınır. |
| flow | sum, avg, pct_change | last | Akım serisi dönem içi tutardır; çeyreğe geçerken toplanır. |
| rate | avg, pp_change | sum, pct_change | Faiz/oran serilerinde değişim yüzde PUAN ile ifade edilir; yüzde değişim yanıltır. |
| index | last, avg, pct_change, rebase | sum | Endeks seviyesi toplanmaz; baz dönem belirtilir. |
| ratio | recompute, pp_change | avg, sum | Oran doğrudan ortalanamaz; pay ve payda ayrı çekilip yeniden hesaplanır. |
| count | last, sum, diff | avg-over-entities | Adet serisi stok gibi davranır. |

## evidence_domains

| domain | priority | note |
|---|---|---|
| tcmb.gov.tr | 1 | Para politikası kararları, EVDS |
| bddk.org.tr | 1 | Bankacılık düzenlemeleri, aylık bülten |
| resmigazete.gov.tr | 1 | Yürürlük tarihleri |
| tuik.gov.tr | 1 | TÜFE, konut satışları |
| borsaistanbul.com | 2 | Endeks ve piyasa verileri |

## note: alt toplam ve mükerrer sayım

BDDK bültenlerinde "Tüketici Kredileri (2+3+4)" gibi kalemler ALT TOPLAMDIR. Alt
toplam satırı alt kalemlerle birlikte toplanırsa mükerrer sayım olur. Tek kalem
incelenirken `is_alt_toplam = FALSE` filtresi kullanılır; toplam istendiğinde ya
alt toplam satırı ya alt kalemler alınır, ikisi birden değil.

## note: birim ve çarpan

BDDK aylık bülten tutarları MİLYON TL; haftalık bülten ve bazı tablolar BİN TL
yayınlar. Cevapta sayı, katalogdaki birim etiketiyle birlikte verilir
("678.970 milyon TL"); birim çevirisi modelde değil araçta yapılır.

## note: konut kredisi düzenlemeleri 2021-2025

- 2021-2022: TCMB politika faizi indirimleri; konut kredisi faizleri kamu bankaları
  öncülüğünde düşük seyretti. (Tarih doğrulaması: `evidence_lookup` ile resmî kaynak.)
- 2023 H2: Parasal sıkılaşma; konut kredisi faizleri hızla yükseldi, bakiye reel
  olarak geriledi.
- 2024-2025: Kredi büyüme sınırları (TCMB makroihtiyati çerçeve). Bakiye artışı
  nominal; reel karşılaştırma için TÜFE ile deflate edilmelidir.
Bu maddeler bağlam içindir; anlatımda tarih ve sayı ancak araç çıktısına dayanır.

## template: karşılaştırma anlatımı

Yapı: (1) hangi iki seri, hangi dönem, hangi birimler; (2) yön ve büyüklük yalnız
araç çıktısındaki sayılarla; (3) faiz için "puan", tutar için "yüzde"; (4)
nedensellik dili YOK — "birlikte hareket etti", "öncülük etti" kullanılır,
"neden oldu" kullanılmaz; (5) kaynak ve dönem kapsamı.

## template: veri yok cevabı

Tek paragraf: istenen dönemin veride bulunmadığı, eldeki kapsamın ne olduğu
(başlangıç → bitiş), tahmin verilmediği. SQL, kolon adı, araç adı yazılmaz.
