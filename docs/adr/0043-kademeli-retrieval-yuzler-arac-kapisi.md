# ADR-0043: Kademeli retrieval — küçükte arama yok, ortada yüzlü BM25, büyükte hibrit; araç kapısı

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Sıradaki:** D9 arayüz, E kapanış

## Bağlam
Katalog 5 seriden 2.214'e çıkınca (ADR-0042) aynı sorular daha çok adım aldı (G1 1 → 3,
G14 4 → 8, G10 2 → 6). Sebep ölçüldü: BM25 "konut kredisi bakiyesi" sorusunda ilk 8'i 81
ilin konut serisiyle dolduruyor, ulusal seri geride kalıyor; "İzmir taşıt kredisi"nde Ankara
ile İzmir aynı puanı alıyor (il adı tek sözcük, "taşıt kredisi" takma adlarda 3×). Aynı anda
18 aracın şeması her çağrıda ~5.300 token ve model araç seçiminde de yanılıyor. Kullanıcının
çizgisi: proje çok kataloglu sistemlere göre kurulmalı; küçük katalogda basit, büyükte daha
güçlü çözüm, eşikler ölçülerek.

## Karar
1. **Modele giden kart sayısı sabit, aday havuzu ölçekle büyür.** Kısıt prompt bütçesi;
   retrieval kapsamı modelden önce genişler, modele 8–12 kart gider.
2. **Üç kademe, tek sınıf** (`core/retriever.py` `CatalogRetriever`, `RetrievalPolicy`):
   `preload_all` (katalog ≤ `RETRIEVAL_SMALL_MAX`=60: arama yok, hepsi kart, bütçe keser),
   `bm25` (yüzlü BM25, aday havuzu k×10), `hybrid` (≥ `RETRIEVAL_HYBRID_MIN`=5000 ve embedder
   varsa: BM25 ∪ embedding → RRF → yüzler → k). `RETRIEVAL_MODE=auto|preload_all|bm25|hybrid`.
   Adaptörler (Silver, seed) ve ölçüm koşucusu aynı nesneyi kullanır: ölçülen şey çalışan şeydir.
3. **Yüzler puan değil eleme/öncelik** (`core/facets.py`): il (81 il, Türkçe ekleriyle),
   frekans (günlük/haftalık/aylık/çeyreklik/yıllık; iki sözcük varsa karar yok, guard'la aynı),
   kaynak (BDDK/EVDS/FinTürk). İl sorulduysa başka ilin serisi elenir, ulusal seri geride
   kalır; sorulmadıysa il serileri ulusalın arkasına. Frekans sorulduysa aynı frekans önde, daha
   ince olan ortada (Gold indirger), daha kaba sona (üretilemez; `FREQUENCY_MISMATCH` ile tutarlı).
4. **Embedding, büyük kademe için** (`adapters/mia_embedder.py`): MIA `Qwen3-Embedding-8B`
   (4096), 64'lük dilimler, anahtar başlıkta; katalog vektörleri diske önbelleklenir
   (`EmbeddingCache`, anahtar model + kimlik + metin sha256; 2.214 seri 36 MB). Ölçüldü: 32 metin
   1,55 s. Sorgu başına tek vektör çağrısı.
5. **Retrieval golden** (`scripts/retrieval_golden.py`): katalogdan üretilen sorgular (ad +
   takma adlar) + 34 elle yazılmış Türkçe soru; recall@1 / recall@8, kademe başına. Eşikler
   buradan konur ve buraya yazılır. Büyük ölçek için EVDS'nin tamamı (53.792 seri) canlı
   listelendi, yalnız retrieval ölçümünde kullanılır (yüklenmez).
6. **Araç kapısı** (`core/tool_gate.py`): her tur soruya göre araç alt kümesi. Her zaman:
   lakehouse ×4, workspace ×4, gold ×3. Sinyalle: chart (grafik sözcükleri), analitik
   (aykırı/kırılma/öncülük/korelasyon), web (adres/sayfa/ara), Architect (yazma niyeti ya da
   taslak/onay/ekle). Kapı sunulan şemayı daraltır, yetkiyi değil: kapalı aracı model adıyla
   çağırırsa çalışır. `TOOL_GATE=off` ölçüm için.

## Ölçüm (13 Eylül)

**Retrieval golden, 2.214 serilik demo kataloğu, 2.926 sorgu (2.892 üretilmiş + 34 elle):**

| Mod | recall@1 | recall@8 |
|---|---|---|
| BM25, yüzsüz (eski) | 0,649 | 0,864 |
| BM25 + yüzler | **0,888** | **0,996** |
| hibrit + yüzler | **0,940** | **1,000** |

Yüzsüz kaçaklar tam beklenen türden: "adana konut kredisi" → EVDS konut satış serileri
(il yüzü olmadan "konut" her yerde). Yüzlü kaçaklar anlamsal: "Afyonkarahisar Konut Birim
Fiyatları" → FinTürk kredi serileri (fiyat ≠ kredi, sözlük ayıramıyor); "(TL, Stok, %)" faiz
serileri → BDDK bakiye serileri. Bunlar hibritin işi.

Hibritin tek kaçağı "mevduat faizi 3 aylık": "3 aylık" vade sözcüğü frekans yüzü sayılıp haftalık
seri geriye atıldı → sayıyla gelen frekans sözcüğü yüz değildir (düzeltildi, test).

**Büyük ölçek (EVDS 53.792'den 3.000 örneklem, yalnız ad ve veri grubu, takma ad yok, seri başına 1 sorgu):**

| Mod | recall@1 | recall@8 | süre (3.001 sorgu) |
|---|---|---|---|
| BM25 yüzsüz | 0,792 | 0,973 | 8 s |
| BM25 + yüzler | 0,787 | 0,971 | 8 s |
| hibrit + yüzler | **0,821** | **0,993** | 224 s (sorgu vektörleri dâhil) |

Yüzler burada nötr (EVDS adlarında il/frekans sözcüğü seyrek; "(1 Aylık İşlem)" gibi vade
ifadeleri yüz sanıldı, düzeltildi). Hibrit recall@8'i 0,971 → 0,993'e taşıyor; adları "Toplam
(Arşiv)", "C. İmalat" gibi bağlamsız seriler her yöntemde kaçıyor, onlar veri grubu düzeyinde
iki aşamalı aramanın işi (açık).

**Eşik kararı.** Modele giden 8 kart için ölçü recall@8: 2.214 seride yüzlü BM25 zaten 0,996,
hibrit 1,000 (+0,4 puan) ve bunun bedeli soru başına bir embedding çağrısı (~0,3 s) ile ağ
bağımlılığı → orta kademede BM25 kalır. 3.000+ seride hibritin kazancı +2,2 puan → `RETRIEVAL_HYBRID_MIN`
5.000'de bırakıldı; 3.000–5.000 arası gri bölge, katalog o boyuta gelince aynı koşucuyla yeniden
ölçülür. Embedding ucu düşerse retriever BM25 ile devam eder ve `last_error` yazar.

**Senaryolar (yüzler + araç kapısı, 11 kabul senaryosu, genişletilmiş 2.214 serilik DB):** 11/11,
kanıt zinciri 11/11. Aynı DB'de yüzsüz ve kapısız koşuya göre:

| Vaka | Adım önce → sonra | Prompt token önce → sonra |
|---|---|---|
| G1 tek değer | 3 → 2 | 50,9k → 26,2k |
| G14 tabloyu bozmadan Gold sütunu | 8 → 4 | 147,9k → 67,0k |
| G10 grafik | 6 → 2 | 111,8k → 38,5k |
| G17 öncülük | 4 → 2 | 71,8k → 29,6k |
| G15 aykırı ay | 3 → 2 | 63,7k → 31,9k |
| G9 Gold çeyreklik + red | 4 → 5 | 70,7k → 62,0k |
| 11 vaka toplamı | 36 → 27 | ≈ 690k → ≈ 416k |

Adımlar 5 serilik DB'nin seviyesine döndü (G14 4, G10 2); token yaklaşık %40 düştü.

## Açık kalan
- Ölçüm-tipi yüzü (faiz/oran vs bakiye) yok; "(TL, Stok, %)" kaçakları için ucuz aday.
- Hibritte yeniden sıralayıcı (reranker) yok; MIA'da yok, yerel cross-encoder ölçülmedi.
- `preload_all` kademesinde bütçe kartları keserse sıralama katalog sırasıdır, soruya göre değil.
