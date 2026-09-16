# Katalog büyüyünce arama ne oldu? — 17 Eylül 2026

Dal: `feature/lakehouse-data-breadth` (push edilmedi). İlgili commit'ler: `5079016` (BDDK aylık 22 → 498 seri), `c141a26` (FinTürk 648 → 4.536 seri), `ee39b5e` (FinTürk açıklamalarının sadeleştirilmesi — bu raporun veri ekibi kısmı).

**Sonuç:** Veri havuzunu 1.940 seriden 6.304 seriye çıkardık. Ajan artık daha çok soruyu cevaplıyor, ama iki sorun çıktı: (1) en önemli sorumuz olan “konut kredisi ne kadar?” kırılganlaştı, (2) **her arama dört kat yavaşladı** (4 sn → 16-26 sn). İkisinin de kök sebebi ölçüldü. Veri ekibinin kendi kısmı uygulandı; ajan kodu ve el yazısı katalog girişleri için Baran'ın onayı gerekiyor. En öncelikli madde arama hızı (§4.4) — bizim PR'ımız bu düzeltme olmadan main'e girerse ajan main'de de yavaşlar.

## 1. Kısa özet

| | Durum |
|---|---|
| Genel doğruluk | **Daha iyi.** Eski havuzla aynı 15 sorudan 9'u bulunuyordu, yeni havuzla 15'i. Yeni veriyle gelen 5 sorunun hepsi cevaplanabiliyor. |
| Zayıf nokta | Anlam araması çalışmazsa (yedek mod) ulusal konut kredisi serisi arama sonuçlarından tamamen düşüyor. |
| Doğruluk sebepleri | 3 ayrı: ikisi katalog metninde, biri arama kodunda. Hiçbiri tek başına yetmiyor. |
| Hız | Arama aracı başına **4,2 sn → 16-26 sn**. Asıl arama 0,17 sn; kalanı her aramada dizinin baştan kurulması. |
| Düzeltme sonrası (kopyada ölçüldü) | Yedek modda 1. sırada doğru seri 14 → 18, 24 sorunun hepsi bulunuyor. Varsayılan modda 19 → 22. |

## 2. Önce bilinmesi gereken: arama iki modda çalışıyor

Ajan bir soruyu cevaplamadan önce kataloğu arar (`lakehouse_search`). İki yol var:

- **Kelime araması (BM25):** sorudaki kelimeleri serinin adında, açıklamasında ve alias'larında arar. Dış servise ihtiyaç duymaz.
- **Anlam araması (hybrid, embedding):** soru ile serinin anlamca yakınlığına bakar. MIA'nın embedding servisine bağlı.

`RETRIEVAL_MODE=auto` ayarında sistem modu **katalog boyutuna göre kendisi seçiyor**: 5.000 serinin altında kelime, üstünde anlam araması (`RETRIEVAL_HYBRID_MIN=5000`). Eski havuz 1.940 seriyle kelime aramasındaydı; yeni havuz 6.304 seriyle otomatik olarak anlam aramasına geçti.

**Yedek modu neden önemsiyoruz:** embedding servisi cevap vermezse kod sessizce kelime aramasına düşüyor (`retriever.py`: “embedding ucu düşerse BM25 ile devam”). Demo anında bu olursa konut kredisi soruları kelime aramasının davranışına kalır.

## 3. Nasıl ölçtük

- Jürinin soracağı türden **24 soru**: 17 ulusal (konut, taşıt, ihtiyaç, tüketici kredisi, mevduat, faiz, enflasyon, kur…), 2 yeni veriyle gelen, 5 il bazında.
- Her sorunun doğru cevabı olan seri(ler) önceden katalogdan tek tek doğrulandı. Örneğin haftalık `5867/5868/5869` ilk bakışta “toplam” sanıldı, aslında takipteki tablosundan çıktı ve beklenen listesinden düşürüldü.
- Her soru ajanın kendi arama aracına verildi; doğru serinin kaçıncı sırada döndüğü kaydedildi. LLM kullanılmadı, sonuçlar tekrarlanabilir.
- Düzeltmeler repoya dokunmadan denendi: kod düzeltmesi yalnız test süreci içinde geçici uygulandı (monkeypatch), katalog düzeltmesinin tamamı veritabanının bir kopyasında yapıldı.

### Sonuçlar

24 sorudan kaçında doğru seri **1. sırada** çıktı; parantez içi: kaç soruda doğru seri listede hiç yer aldı.

| Varyant | Kelime araması (yedek) | Anlam araması (varsayılan) |
|---|---:|---:|
| Bugünkü hâl | 14 (21/24) | 19 (24/24) |
| + Veri ekibi kısmı *(uygulandı, `ee39b5e`)* | 16 (21/24) | 20 (24/24) |
| + Kod düzeltmesi (aday havuzu) | 14 (22/24) | 21 (24/24) |
| + Katalog düzeltmesinin tamamı *(veri ekibi + tablo 3 + ulusal alias'lar, kopyada)* | 17 (23/24) | 22 (24/24) |
| **+ Katalog tamamı ve kod düzeltmesi birlikte** *(kopyada)* | **18 (24/24)** | **22 (24/24)** |

Konut kredisi soruları özelinde:

| Soru | Kelime · bugün | Kelime · hepsi | Anlam · bugün | Anlam · hepsi |
|---|---:|---:|---:|---:|
| Konut kredisi toplamı 2026 Haziran'da ne kadar? | yok | #1 | #2 | #1 |
| Konut kredisi toplamı 2025 sonunda ne kadar? | yok | #4 | #2 | #1 |
| Türkiye'de konut kredisi ne kadar? | yok | #1 | #3 | #1 |
| Konut kredileri son bir yılda ne kadar büyüdü? | #2 | #3 | #1 | #1 |

Dürüst bir not: kod düzeltmesi *tek başına* anlam aramasında bir soruyu kötüleştirdi (“Türkiye'de konut kredisi” #3 → #5); katalog düzeltmesi de *tek başına* kelime aramasında “inşaat kredisi” sorusunu düşürdü. Birlikte uygulandığında iki yan etki de kayboluyor.

## 4. Bulunan dört sebep

### 4.1 Bazı serilerin açıklaması başka serilerin adını geçiriyor — `catalog/series/bddk_finturk.yml`

Arama, bir serinin ne olduğunu adına, açıklamasına ve alias'larına bakarak anlıyor. FinTürk il serilerinin açıklamalarında, o serinin kendisini değil *başka* serileri anlatan teknik notlar vardı.

Adana'nın **taşıt** kredisi serisinin açıklaması:

> “Aynı isteğin aynı yanıtındaki bir sütun: **konut kredisi** serisiyle aynı çekilişten gelir, ayrı istek gerektirmez…”

Adana'nın **konut** kredisi serisinin açıklaması:

> “…**81 ilin** 2025-09 **toplamı**, bağımsız olarak doğrulanmış BDDK Aylık **ulusal konut kredisi** stokuyla %0,001 içinde örtüşüyor…”

| Cümle | Seri sayısı | Kimin | Durum |
|---|---:|---|---|
| “konut kredisi serisiyle aynı çekilişten gelir” | 567 (81 il × 7 sütun) | tablo 3, `cf3e878` (13 Eylül) | onay bekliyor |
| “81 ilin … toplamı … ulusal konut kredisi” | 81 | tablo 3, `c333fec` (11 Eylül) | onay bekliyor |
| tablo 6 kanıt cümlesi “…ANKARA… toplam nakdi krediyle örtüşüyor” | 486 | tablo 6, bu geceki üretim | **düzeltildi (`ee39b5e`)** |
| “Mart/Haziran/Eylül/Aralık” (soruda ay adı geçince bütün il serileri puan topluyor) | 3.888 (tablo 1, 2, 4, 6) + 648 (tablo 3) | — | 3.888 **düzeltildi**; tablo 3 onay bekliyor |

**Neden zararlı:** bu notlar doğru ve değerli — ama aramanın gözünde “Adana taşıt kredisi”ni bir konut kredisi serisine, 81 il serisini de “ulusal toplam” serisine benzetiyor. Soruda il yokken yüzlerce il serisi ulusal serinin önüne geçiyor.

**Öneri:** açıklama yalnız o seriyi anlatsın. Kanıt notları silinmesin, `lakehouse-core/docs/sources/bddk_finturk.md` belgesine taşınsın; açıklamada o belgeye işaret kalsın. Tablo 1, 2, 4, 6 için bu yapıldı ve belgeye “Genişletme (2026-09-16)” ile “Arama hijyeni” bölümleri eklendi.

**Geçmiş:** cümleler katalog bugünkünden çok daha küçükken eklendi. Dünkü 2.252 serilik katalogda bile konut kredisi sorusu hâlâ 1. sıradaydı; sorun bu geceki büyümeyle görünür hâle geldi.

### 4.2 Ana ulusal seriler insanların kullandığı kelimeleri içermiyor — `bddk_monthly.yml`, `bddk_weekly.yml`

Türkiye'nin toplam konut kredisi serisi (`bddk_monthly:1534_Toplam`), BDDK'nın resmî adıyla: **“Tüketici Kredileri - Konut, Toplam (Sektör)”**.

Jüri ise “**Türkiye'de** konut kredisi ne kadar?” ya da “konut kredisi **toplamı**” diye soracak. Serinin adında, açıklamasında ve 8 alias'ında “Türkiye” kelimesi hiç geçmiyor; bu kelimeyi taşıyan EVDS serileri (“Konut Birim Kira (Türkiye)” gibi) öne geçiyor.

**Öneri:** en önemli 7 ulusal seriye insanların kullandığı ifadeleri alias olarak eklemek. Kopyada denenen liste:

| Seri | Eklenen alias'lar |
|---|---|
| `bddk_monthly:1534_Toplam` (konut) | türkiye konut kredisi, toplam konut kredisi, konut kredisi toplamı, türkiye geneli konut kredisi |
| `bddk_weekly:5690_3` (haftalık konut) | türkiye konut kredisi haftalık, konut kredisi toplamı haftalık |
| `bddk_monthly:1535_Toplam` (taşıt) | taşıt kredisi toplamı, türkiye taşıt kredisi, toplam taşıt kredisi |
| `bddk_monthly:1536_Toplam` (ihtiyaç) | ihtiyaç kredisi toplamı, türkiye ihtiyaç kredisi, toplam ihtiyaç kredisi |
| `bddk_monthly:1533_Toplam` (tüketici) | tüketici kredisi toplamı, türkiye tüketici kredileri, toplam tüketici kredisi |
| `bddk_monthly:1357_Toplam` (mevduat) | mevduat toplamı, türkiye toplam mevduat, türkiye geneli mevduat |
| `bddk_monthly:1160_Toplam` (krediler) | türkiye toplam krediler, sektör toplam kredi, kredi toplamı |

### 4.3 Aday havuzu, “il yoksa il serilerini geri at” kuralından önce kesiliyor — `agent-core/src/kkb_agent/core/retriever.py`

Arama önce en yüksek puanlı **50 adayı** seçiyor (`pool = max(k * CANDIDATE_MULTIPLIER, 50)`), sonra kuralları uyguluyor. Kural doğru yazılmış: soruda il yoksa il serileri geriye itiliyor (`apply_facets`). Ama kural yalnız o 50 aday içinde sıralama yapabiliyor.

```
Soru: "Konut kredisi toplamı 2026 Haziran'da ne kadar?"   (kelime araması)

Aday havuzu          : 50 seri  →  48'i il serisi
81 il konut kredisi  : puan 16,5 – 17,5
Ulusal haftalık      : puan 15,9  →  sıralamada #84, havuza giremiyor
Ulusal aylık         : puan 12,9  →  sıralamada #109, havuza giremiyor
```

**Öneri:** soruda il geçmiyorsa havuzu doldurmadan önce ulusal ve il adaylarını ayırıp ulusalları öne almak. Soruda il geçiyorsa davranış değişmiyor. `CatalogRetriever.search` içinde ~10 satır:

```python
by_id = {r.id: r for r in self.records}

def split_pool(cands):
    if facets.provinces:                    # soruda il var → bugünkü davranış
        return list(cands)[:pool]
    national   = [c for c in cands if by_id[c.id].province is None]
    provincial = [c for c in cands if by_id[c.id].province is not None]
    return national[:pool] + provincial[:pool]

lexical = split_pool(self._bm25.search(query, k=len(self.records)))
# yoğun (anlam) adayları için de aynı split_pool
```

Maliyet: 6.304 seride tüm sıralamayı almak milisaniyeler sürüyor (saf BM25 araması 0,17 sn ölçüldü).

### 4.4 Arama her soruda dizini baştan kuruyor — `agent-core/src/kkb_agent/adapters/silver_lakehouse.py` **(öncelikli)**

`lakehouse_search` aracının bir çağrısı, 24 soruluk testte:

| Havuz / mod | Arama başına (medyan) |
|---|---:|
| Eski (1.941 seri), kelime | 4,2 sn |
| Yeni (6.304 seri), kelime | **17,3 sn** |
| Yeni (6.304 seri), anlam | **26 sn** |

Bir çağrının profili (yeni havuz, kelime araması, `cProfile`):

```
Asıl BM25 araması                          0,17 sn
lakehouse_search aracının toplamı         16,32 sn
  SilverLakehouse._retriever()  × 2       16,26 sn   ← her çağrıda yeni nesne
    CatalogRetriever.__init__   × 3       15,42 sn
      lexical.index → tokenize  25.246 kez, fold içinde 21,7 milyon karakter işlemi
```

**Sebep:** `_retriever()` (`silver_lakehouse.py:562`) her çağrıldığında kataloğu veritabanından okuyup arama dizinini sıfırdan kuruyor; sonuç saklanmıyor (iki ardışık çağrı iki ayrı nesne döndürüyor). Bir aramada iki kez çağrılıyor. Küçük katalogda bu birkaç saniyeydi; maliyet katalog boyutu ve metin uzunluğuyla doğrusal büyüyor.

**Neden önemli:** ajan tek bir cevap için genelde 1-3 kez arıyor → cevap başına **30-60 saniye** ek bekleme. Anlam aramasında ayrıca katalog değiştikten sonraki **ilk arama 504 saniye** sürdü (6.304 serinin vektörleri yeniden hesaplanıyor; sonra önbellekten okunuyor).

**Öneri:** dizini bir kez kurup saklamak; yalnız katalog değişince (`reload()`, ingest, promote) yeniden kurmak. Beklenen (profilden, ölçülmedi): arama başına ~0,2 sn + anlam aramasında sorgunun tek embedding çağrısı, katalog boyutundan bağımsız.

**Demo öncesi için:** katalog en son değiştikten sonra ajanı bir kez çalıştırıp bir soru sormak (vektör önbelleğini ısıtmak). `agent-core/data/cache/embeddings` klasöründe katalogun her sürümü için ~99 MB dosya birikiyor; eski sürümler silinebilir.

## 5. “Eskiden iyi çalışıyordu” — neden?

Eski havuzda aynı sorunun ilk üç sonucu:

```
1. Konut kredisi (haftalık, ulusal)     ← doğru
2. Tüketici kredileri toplam
3. ADANA konut kredisi                   ← soruda il yok, il serisi zaten 3. sıradaydı
```

İl serilerinin ulusal soruları kalabalıklaştırması eskiden de vardı; ulusal seri ince bir farkla önde kalıyordu. Kelime aramasında puanlar göreli: bir kelimenin değeri, havuzda o kelimenin ne kadar yaygın olduğuna ve belgelerin ortalama uzunluğuna göre hesaplanıyor. 4.364 seri eklenince bu istatistikler değişti ve o ince fark tersine döndü. Kod ya da veri yanlış değişmedi; denge kaydı.

## 6. Önerilen değişiklikler

| Değişiklik | Nerede | Etki | Durum |
|---|---|---|---|
| **Arama dizinini her aramada baştan kurmamak** (önbellek) | `agent-core/…/silver_lakehouse.py` | Arama başına ~16 sn → ~0,2 sn beklenir | **Baran'ın kararı · öncelikli** |
| Tablo 1, 2, 4, 6 açıklamalarını sadeleştirmek; il alias'larını ikiye indirmek; Türkçe küçük harf (ŞIRNAK → şırnak) | `generate_bddk_finturk_catalog.py` | Kelime: 1. sırada 14 → 16, kaybolan soru yok. Anlam: 19 → 20; “konut kredisi toplamı” #2 → #1 | **uygulandı · `ee39b5e`** |
| Tablo 3 açıklamalarındaki iki cümleyi ve ay adlarını belgeye taşımak | `bddk_finturk.yml` (el yazısı bölüm) | 648 seride başka seri adı temizlenir | Baran'ın onayı |
| 7 ana ulusal seriye alias eklemek | `bddk_monthly.yml`, `bddk_weekly.yml` | “Türkiye'de konut kredisi” yok → #1 | Baran'ın onayı |
| Aday havuzunu il kuralından önce ayırmak | `agent-core/…/retriever.py` | Yedek modda 24/24 bulunma | Baran'ın kararı |

## 7. Bundan sonrası için iki öneri

1. **Açıklama yalnız o seriyi anlatsın.** Nasıl çekildiği, hangi kaynakla doğrulandığı gibi notlar `docs/sources/` belgelerine; katalog açıklamasında o belgeye işaret yeter. Aksi hâlde her kanıt cümlesi aramaya yeni bir “yanlış eşleşme” ekliyor.
2. **Kataloğa toplu seri eklendiğinde arama testi koşulsun.** Bu ölçümde kullanılan 24 soruluk test birkaç dakikada koşuyor ve LLM gerektirmiyor. Repoya alıp “katalog değiştiyse önce bunu çalıştır” kuralı konabilir; bu geceki doğruluk ve hız sorunlarını seri eklendiği anda gösterirdi.

## Ek: ölçüm ortamı

- Çalışma veritabanı: `lakehouse-core/data/lakehouse.duckdb.breadth_test` (6.304 seri, 232.217 gözlem); eski durum için 16 Eylül gece yarısı kopyası (1.941 seri).
- Katalog düzeltmesinin tamamı: `lakehouse.duckdb.search_exp` kopyasında (repoda değişiklik yapılmadan).
- Arama modu `RETRIEVAL_MODE` ortam değişkeniyle zorlandı (`bm25` / `auto`); anlam araması `kkbhackathon2026/Qwen3-Embedding-8B`.
- Deney script'i (monkeypatch dahil) şu an yerel; bulgu 7.2 kabul edilirse repoya alınabilir.
