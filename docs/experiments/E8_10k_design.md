# E8-10k — katalog özeti → `search_series` geçişinin EVDS ölçeğinde doğrulanması

> Tasarım: 10 Eylül 2026 (2. oturum) · Script: `scripts/exp_e8_10k.py` · Önceki: `E8_catalog_threshold.md` (60/200/1000/3000)
> Etiketler: `[ORG] [DOC] [EMP] [SRC] [INF] [ASM] [REC]`

## 1. Neden 3000 üst sınır değil

- E8 `[EMP]`: tam katalog prompt'ta 1000 seride %98 / 2,4 s, 3000'de %92 / 10,9 s (91k token). Kırılma doğrulukta 1000'den, gecikmede 200'den sonra. Karar: prompt'a ≤ ~6k token, üstünde `search_series` top-30.
- EVDS ölçeği on binlerce seri `[ASM]` (tam sayı ölçülmedi; data ekibinin `catalog/series/evds.yml` şu an birkaç seri). openecon-data 330k göstergeyi 11 sağlayıcıdan indeksliyor `[SRC]` — README "semantic routing" diyor ama **mekanizmayı açıklamıyor**; yöntem referansı değil, ölçek örneği.
- 10.000 seri × ~28 token/satır ≈ **280k token**. Ölçülen en uzun prompt 91k `[EMP]`; bağlam üst sınırı (`max_model_len`) **ölçülmedi** `[ASM]` — script'in 0. adımı `/v1/models`'tan okur. 280k büyük olasılıkla sınırın dışında; zaten 3000'de bozulan tam-katalog kolunu 10k'da koşmak anlamsız.

**Sonuç:** 10k kademesi eşiğin kendisini değil, **geçiş modunu** test eder: `search_series` (BM25) top-K → ≤1k token aday listesi → model seçer. V3 §3.5 ve edge-case 22'nin iddiası "eşik üstünde de doğruluk korunur"; bu deney o iddiayı ölçer.

## 2. Hipotez ve başarı ölçütü

| | |
|---|---|
| H1 | 3k/10k/30k seride BM25 top-30 → model seçimi, uçtan uca doğrulukta E8'in 200-seri seviyesinden (%98) en fazla 2 puan düşer: **≥ %96** |
| H2 | Retrieval tavanı (hedef top-30'da mı) **≥ %98**; uçtan uca hata çoğunlukla model seçiminden değil retrieval kaçırmasından gelirse hybrid kolu (D-3) devreye girer |
| H3 | p50 gecikme **< 1 s** (aday listesi ~1k token → prefill ~70 ms + üretim ~40 token) |
| Karar | H1 ∧ H3 sağlanırsa V3 §3.5 bütçe kuralı EVDS ölçeğinde onaylı; H2 düşer ama H1 sağlanırsa top-K büyütülür (30→50), H1 düşerse hybrid (E-RET) P1'den P0'a çıkar |

## 3. Tasarım

**Katalog (`build_hard`)** — E8'in rastgele filler'ı 10k'da anlamsız (çakışmaz). Bunun yerine her gerçek seriden EVDS/BDDK-benzeri **yakın kopyalar** üretilir: banka grubu (6), il (20), para birimi (TP/YP/toplam), frekans (4), vintage/baz yıl (6). Ad ve alias'lar büyük ölçüde paylaşılır; yalnız ayırt edici nitelik değişir. Bu, gerçek kataloğun risk profilidir `[INF]`: "konut kredisi bakiyesi" sorgusuna 30 aday içinde 25 tanesi "konut kredisi bakiyesi (X)" olacak.

**Sorgular** — E8'in 50 standart sorgusu (hedefler her zaman gerçek seriler) + **20 `hard_variant`** sorgu (hedef bir yakın kopya; sorgu ayırt edici niteliği açıkça söyler: "katılım bankaları konut kredisi bakiyesi"). İkincisi BM25'in niteliği ayırt edip edemediğini ölçer.

**Kollar**

| Kol | Aday üretimi | Ne zaman |
|---|---|---|
| `bm25` | bm25s, Türkçe katlamalı tokenizer (bake-off ile aynı) top-K | Varsayılan |
| `hybrid` | BM25 ∪ Qwen3-Embedding dense, RRF | `--dense`; H2 düşerse |
| `full` | Tam katalog prompt'ta | `--full`; yalnız tahmini token < 0,8 × `max_model_len` ise, aksi hâlde satır "atlandı" olarak yazılır |

**Metrikler** — R@K (retrieval tavanı), uçtan uca doğruluk, prompt token, p50/p95, kategori kırılımı (exact/abbrev/synonym/english/typo/misleading/natural/hard_variant). Hata listesi her satırda "hedef top-K'da var mıydı" bilgisiyle: retrieval hatası ile model hatası ayrışır.

**Sabitler** — non-thinking, T=0, `max_tokens=40`, K=30 (V3 §3.5 ile aynı); E8 ile aynı system prompt yapısı (yalnız "KATALOG" yerine "ADAYLAR").

## 4. Bilinen sınırlar

- Sorgular ve alias'lar aynı kişi tarafından yazıldı (bake-off uyarısıyla aynı); iyimser olabilir. Gerçek `meta.series` gelince aynı script gerçek katalogla koşulur (`build_hard` yerine dosyadan yükleme — bekleyen madde).
- Yakın-kopya üreteci deterministik ve sentetik; gerçek EVDS'de ayırt edici nitelik bazen yalnız seri kodunda (TP.FG.J0) olur, isimde olmaz. Bu durumu kapsamıyor `[INF]`; katalog alias'ları bunu karşılamalı (data ekibi sözleşmesi).
- `max_model_len` probe'u `/v1/models` alanına bağlı; vLLM bazı sürümlerde döndürmez. Döndürmezse `full` kolu atlanır ve satırda belirtilir.

## 5. Koşu

```bash
python scripts/exp_e8_10k.py --probe-only                       # 0. adım: bağlam sınırı
python scripts/exp_e8_10k.py --sizes 3000,10000,30000 --k 30    # bm25 kolu (~210 kısa MIA çağrısı, ~3 dk)
python scripts/exp_e8_10k.py --sizes 10000 --dense              # H2 düşerse hybrid
```

Sonuç dosyası: `docs/experiments/E8_10k_results.md` (tablo + hata listeleri). V3 §5 tablosuna "E8-10k" satırı sonuçla birlikte eklenir.

## 6. İlk koşu (v1, düz BM25) — H1 ve H2 düştü; iki sebep

`E8_10k_results_v1_flat.md` `[EMP]` (10 Eylül, 2. oturum; 70 sorgu, K=30, p50 0,22 s):

| N | R@30 | uçtan uca | hard_variant |
|---|---|---|---|
| 3.000 | %83 | %63 | 7/20 |
| 10.000 | %77 | %56 | 3/20 |
| 30.000 | %69 | %49 | 0/20 |

Hata listesi iki ayrı nedene ayrışıyor:

1. **Yapısal (gerçek bulgu).** Bir kavramın çok sayıda yakın kopyası olunca düz top-K o kopyalarla dolar ve **kanonik seri listeden düşer**: "mortgage bakiyesi" 3.000 seride bile top-30'a girmedi, 30 sıranın hepsi "konut kredileri bakiyesi (X)" varyantlarıydı. BM25'in uzunluk normalizasyonu taban seriyi öne çıkarmaya yetmiyor; alias'lar paylaşıldığı için tf-idf ayırt etmiyor `[INF]`. Sonuç: `search_series` düz liste değil **iki aşamalı** olmalı — önce kavram (taban seri), sonra o kavramın sorguyla örtüşen boyutları (banka grubu / il / para birimi / frekans). Bu, openecon'un "provider → series" yönlendirmesine ve EVDS'nin kendi hiyerarşisine denk düşer. **Gerekli veri:** `meta.series`'te kavram/ebeveyn anahtarı (data ekibine istek; bugün yok `[ASM]`).
2. **Üreteç kusuru (test artefaktı).** v1'de kavram başına ~50 (3k) → ~500 (30k) varyant üretiliyordu — gerçekçi değil; "Adana politika faizi", "kamu bankaları ev satışları" gibi anlamsız kombinasyonlar vardı (model "NONE" dedi, aslında haklı); bazı varyantlar taban seriyle aynı frekansı tekrarlıyordu (ayırt edilemez). Bu yüzden v1 sayıları alt sınır, üst sınır değil.

## 7. İkinci koşu (v2) — sonuç ve karar

`E8_10k_results.md` `[EMP]` (70 sorgu, K=30, G=8×V=4):

| N | kol | R@30 | uçtan uca | prompt token | p50 s | hard_variant |
|---|---|---|---|---|---|---|
| 3.000 | bm25 | %96 | %90 | 1.172 | 0,18 | 20/20 |
| 3.000 | grouped | %96 | %93 | 934 | 0,18 | 19/20 |
| 10.000 | bm25 | %96 | %90 | 1.139 | 0,18 | 20/20 |
| 10.000 | grouped | %96 | %91 | 936 | 0,18 | 19/20 |
| 30.000 | bm25 | %96 | %90 | 1.152 | 0,18 | 19/20 |
| 30.000 | grouped | %97 | %91 | 954 | 0,19 | 19/20 |

- **Ölçek etkisi yok:** 3k → 30k arasında hiçbir metrik düşmüyor. Geçiş modu EVDS ölçeğinde çalışıyor (H3 ✓; H1/H2 ✗ ama sebep ölçek değil).
- **Kalan hata sabit ve retrieval kaynaklı:** her boyutta aynı 3–4 sorgu top-30'a girmiyor — "bankaların özkaynağı ne kadar" (çekimli biçim, alias yok), "işletmelere verilen krediler" (alias yok), "TP döviz mevduatı" (çelişkili üretilmiş sorgu, artefakt). Bake-off'un kalan hatasıyla aynı sınıf (`RETRIEVAL_bakeoff.md`). Çözüm K değil: alias kalitesi (data ekibi), Türkçe ek kırpma, gerekirse hybrid (D-3).
- **`grouped` > `bm25`:** +1–3 puan, %20 daha az token, ve düz BM25'in "mortgage bakiyesi"de kanonik seriyi varyanta kaptırma hatasını düzeltiyor. v1'deki çöküşün (R@30 %69) tekrarlanmaması, gerçek riskin "varyant sayısı" olduğunu gösteriyor: kavram başına ~16 varyantta düz BM25 de yeterli, ~500'de değil. EVDS'nin gerçek dağılımı ölçülmedi `[ASM]` → gerçek `meta.series` gelince aynı script koşulur.
- **Karar `[REC]`:** V3 §3.5 eşik kuralı korunur; `search_series` iki aşamalı tasarlanır (kavram → boyut), `meta.series`'te kavram/ebeveyn anahtarı istenir; alias/çekim iyileştirmesi P0'a girer (ucuz), hybrid D-3'e bağlı kalır.

**Revizyon (v2, `scripts/exp_e8_10k.py`):** kavram başına ≤48 varyant, yalnız kategoriye uygun boyutlar (il/banka grubu sadece banka serilerine, para birimi sadece TL tutar serilerine, frekans yalnız tabandan farklıysa), kalan yer ilgisiz kavramlarla (E8 filler'ı) doldurulur; 3k'da 956 varyant + 1.984 filler, 30k'da 956 + 28.984. Yeni kol **`grouped`**: BM25 kavram indeksinde top-8 → her kavram + sorgu token'larıyla örtüşen ≤4 varyantı → ≤30 satır. Hipotezler v2 için yeniden: H1/H2 `grouped` kolunda test edilir; `bm25` kolu karşılaştırma tabanıdır.
