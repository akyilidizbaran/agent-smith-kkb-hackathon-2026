# Katalog büyüyünce arama ne oldu? — 17 Eylül 2026

Dal: `feature/lakehouse-data-breadth` (push edilmedi). İlgili commit'ler: `5079016` (BDDK aylık 22 → 498 seri), `c141a26` (FinTürk 648 → 4.536 seri), `ee39b5e` (FinTürk açıklamalarının sadeleştirilmesi — bu raporun veri ekibi kısmı), `f1521a4` (güncel main'in dala alınması), `d45c53d` (arama hızı düzeltmesi, §4.4), `34baacd` (tablo 3 açıklamaları ve ulusal alias'lar, §4.1-4.2).

**Sonuç:** Veri havuzunu 1.940 seriden 6.304 seriye çıkardık. Ajan artık daha çok soruyu cevaplıyor, ama iki sorun çıktı: (1) en önemli sorumuz olan “konut kredisi ne kadar?” kırılganlaştı, (2) **her arama dört kat yavaşladı** (4 sn → 16-26 sn). İkisinin de kök sebebi ölçüldü. **Arama hızı düzeltildi** (§4.4, `d45c53d`): önbellek zaten yazılmıştı ama tek kelimelik bir karşılaştırma hatası yüzünden hiç tutmuyordu; arama artık ilk çağrıdan sonra 0,02-0,20 sn. **Doğruluk düzeltmeleri de uygulandı** (`ee39b5e`, `34baacd`): gerçek veritabanında 1. sıradaki doğru seri kelime aramasında 14 → 18 (24/24 bulunuyor), anlam aramasında 19 → 21; üç konut kredisi sorusunun üçü de #1. Açık kalan tek madde isteğe bağlı: aday havuzu değişikliği (§4.3) artık kelime aramasında bir şey eklemiyor, anlam aramasında +1; karar ajan tarafına bırakıldı.

## 1. Kısa özet

| | Durum |
|---|---|
| Genel doğruluk | **Daha iyi.** Eski havuzla aynı 15 sorudan 9'u bulunuyordu, yeni havuzla 15'i. Yeni veriyle gelen 5 sorunun hepsi cevaplanabiliyor. |
| Zayıf nokta | Anlam araması çalışmazsa (yedek mod) ulusal konut kredisi serisi arama sonuçlarından tamamen düşüyordu. **Düzeltildi:** yedek modda da #1 (`34baacd`). |
| Doğruluk sebepleri | 3 ayrı: ikisi katalog metninde, biri arama kodunda. Hiçbiri tek başına yetmiyor. |
| Hız | Arama aracı başına **4,2 sn → 16-26 sn** idi; asıl arama 0,17 sn, kalanı her aramada dizinin baştan kurulmasıydı. **Düzeltildi:** ilk çağrıdan sonra 0,02-0,20 sn (`d45c53d`). |
| Düzeltme sonrası (gerçek veritabanı) | Yedek modda 1. sırada doğru seri 14 → 18, 24 sorunun hepsi bulunuyor. Varsayılan modda 19 → 21 (aday havuzu değişikliğiyle 22). |

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
| + Katalog tamamı ve kod düzeltmesi birlikte *(kopyada)* | 18 (24/24) | 22 (24/24) |
| **Tüm katalog düzeltmeleri** *(uygulandı, `ee39b5e` + `34baacd`, gerçek veritabanı)* | **18 (24/24)** | **21 (24/24)** |
| Tüm katalog düzeltmeleri + aday havuzu *(gerçek veritabanı, geçici)* | 18 (24/24) | 22 (24/24) |

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
| “konut kredisi serisiyle aynı çekilişten gelir” | 567 (81 il × 7 sütun) | tablo 3, `cf3e878` (13 Eylül) | **düzeltildi (`34baacd`)** |
| “81 ilin … toplamı … ulusal konut kredisi” | 81 | tablo 3, `c333fec` (11 Eylül) | **düzeltildi (`34baacd`)** |
| tablo 6 kanıt cümlesi “…ANKARA… toplam nakdi krediyle örtüşüyor” | 486 | tablo 6, bu geceki üretim | **düzeltildi (`ee39b5e`)** |
| “Mart/Haziran/Eylül/Aralık” (soruda ay adı geçince bütün il serileri puan topluyor) | 3.888 (tablo 1, 2, 4, 6) + 648 (tablo 3) | — | **hepsi düzeltildi** (`ee39b5e`, `34baacd`) |

**Neden zararlı:** bu notlar doğru ve değerli — ama aramanın gözünde “Adana taşıt kredisi”ni bir konut kredisi serisine, 81 il serisini de “ulusal toplam” serisine benzetiyor. Soruda il yokken yüzlerce il serisi ulusal serinin önüne geçiyor.

**Öneri:** açıklama yalnız o seriyi anlatsın. Kanıt notları silinmesin, `lakehouse-core/docs/sources/bddk_finturk.md` belgesine taşınsın; açıklamada o belgeye işaret kalsın. Tablo 1, 2, 4, 6 için yapıldı ve belgeye “Genişletme (2026-09-16)” ile “Arama hijyeni” bölümleri eklendi. Tablo 3'te de yapıldı (`34baacd`); iki kanıt zaten belgede kayıtlıydı. Kaynağın kendi tanım notları korundu: “(KMH)”, “(tahsili gecikmiş)”, “(ihtiyaç kredileri dahil)”.

**Geçmiş:** cümleler katalog bugünkünden çok daha küçükken eklendi. Dünkü 2.252 serilik katalogda bile konut kredisi sorusu hâlâ 1. sıradaydı; sorun bu geceki büyümeyle görünür hâle geldi.

### 4.2 Ana ulusal seriler insanların kullandığı kelimeleri içermiyor — `bddk_monthly.yml`, `bddk_weekly.yml`

Türkiye'nin toplam konut kredisi serisi (`bddk_monthly:1534_Toplam`), BDDK'nın resmî adıyla: **“Tüketici Kredileri - Konut, Toplam (Sektör)”**.

Jüri ise “**Türkiye'de** konut kredisi ne kadar?” ya da “konut kredisi **toplamı**” diye soracak. Serinin adında, açıklamasında ve 8 alias'ında “Türkiye” kelimesi hiç geçmiyor; bu kelimeyi taşıyan EVDS serileri (“Konut Birim Kira (Türkiye)” gibi) öne geçiyor.

**Uygulandı (`34baacd`):** en önemli 7 ulusal seriye insanların kullandığı ifadeler alias olarak eklendi (zaten var olanlar tekrar eklenmedi):

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

**Güncel durum:** katalog düzeltmeleri uygulandıktan sonra bu değişiklik kelime aramasında hiçbir şey eklemiyor (18 → 18), anlam aramasında 1 soru ekliyor (21 → 22). Artık zorunlu değil; il sayısı ya da benzer il serileri ileride artarsa tekrar önem kazanabilir. Karar ajan tarafının.

**Öneri (isteğe bağlı):** soruda il geçmiyorsa havuzu doldurmadan önce ulusal ve il adaylarını ayırıp ulusalları öne almak. Soruda il geçiyorsa davranış değişmiyor. `CatalogRetriever.search` içinde ~10 satır:

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

### 4.4 Arama her soruda dizini baştan kuruyordu — `agent-core/src/kkb_agent/adapters/silver_lakehouse.py` **(düzeltildi, `d45c53d`)**

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

**Sebep — önbellek vardı ama hiç tutmuyordu.** `_retriever()` dizini yalnız katalog değişince kurmak üzere yazılmış:

```python
if getattr(self, "_retr_for", None) is not id(self._catalog):   # her zaman True
```

`is not` iki değerin *aynı nesne* olup olmadığına bakar, *aynı sayı* olup olmadığına değil. `id()` her çağrıda yeni bir int nesnesi döndürdüğü için koşul hep doğru çıktı ve dizin her aramada (bir aramada iki kez) baştan kuruldu. Aynı kalıp `_uningested_retriever()` ve `DuckDBLakehouse`'ta da vardı. Küçük katalogda bu birkaç saniyeydi; maliyet katalog boyutuyla doğrusal büyüdü.

**Düzeltme (`d45c53d`):** anahtar artık katalog nesnesinin kendisi — `is not self._catalog`, `self._retr_for = self._catalog`. `id() != id()` da yetmezdi: Architect yeni veri ekleyip `reload()` çağırınca eski katalog silinir ve yeni katalog aynı bellek adresini alabilir; o zaman ajan yeni seriyi içermeyen eski dizinle aramaya devam ederdi. Nesnenin kendisi saklandığı için adres başka nesneye geçemiyor. `_catalog` ve `_uningested` her yenilemede yeni sözlük olarak kuruluyor, yerinde değiştirilmiyor; kimlik karşılaştırması bu yüzden doğru sinyal.

**Ölçülen sonuç** (gerçek kod, 6.304 serilik veritabanı, arama aracı başına):

| | 1. arama | sonraki aramalar |
|---|---:|---:|
| Kelime araması, önce | 7,5 sn | 7,5 sn |
| Kelime araması, sonra | 3,8 sn | **0,02-0,17 sn** |
| Anlam araması, sonra | 7,0 sn | **0,17-0,20 sn** |

Arama sonuçları birebir aynı. Yeni test (`test_arama_dizini_her_aramada_kurulmaz_katalog_yenilenince_kurulur`): dizin art arda aramalarda yeniden kurulmuyor; yeni seri yazılıp adaptör yenilenince dizin yeniden kuruluyor ve yeni seri aramada bulunuyor. Test düzeltme olmadan kırılıyor. `agent-core`: 668 geçti, 11 atlandı, 1 kaldı — `test_evidence` yol ayracı olarak `/` bekliyor, yalnız Windows'ta kırılıyor, düzeltmeden önce de aynı.

**Demo öncesi için:** anlam aramasında katalog değiştikten sonraki ilk arama vektörleri yeniden hesaplar (504 sn ölçüldü; sonra önbellekten okunur). Katalog en son değiştikten sonra ajanı bir kez çalıştırıp bir soru sormak yeterli. `agent-core/data/cache/embeddings` klasöründe katalogun her sürümü için ~99 MB dosya birikiyor; eski sürümler silinebilir.

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
| **Arama dizini önbelleğinin karşılaştırma hatası** (`is not id(...)` → `is not self._catalog`) | `agent-core/…/silver_lakehouse.py`, `duckdb_lakehouse.py` | Arama başına 7,5 sn → 0,02-0,20 sn (ölçüldü) | **uygulandı · `d45c53d`** |
| Tablo 1, 2, 4, 6 açıklamalarını sadeleştirmek; il alias'larını ikiye indirmek; Türkçe küçük harf (ŞIRNAK → şırnak) | `generate_bddk_finturk_catalog.py` | Kelime: 1. sırada 14 → 16, kaybolan soru yok. Anlam: 19 → 20; “konut kredisi toplamı” #2 → #1 | **uygulandı · `ee39b5e`** |
| Tablo 3 açıklamalarındaki iki cümleyi ve ay adlarını belgeye taşımak | `bddk_finturk.yml` (el yazısı bölüm) | 648 seride başka seri adı temizlendi | **uygulandı · `34baacd`** |
| 7 ana ulusal seriye alias eklemek | `bddk_monthly.yml`, `bddk_weekly.yml` | Kelime: 16 → 18, 24/24; anlam: 20 → 21; “Türkiye'de konut kredisi” yok → #1 | **uygulandı · `34baacd`** |
| Aday havuzunu il kuralından önce ayırmak | `agent-core/…/retriever.py` | Katalog düzeltmelerinden sonra: kelime +0, anlam +1 | isteğe bağlı · ajan tarafının kararı |

## 7. Bundan sonrası için iki öneri

1. **Açıklama yalnız o seriyi anlatsın.** Nasıl çekildiği, hangi kaynakla doğrulandığı gibi notlar `docs/sources/` belgelerine; katalog açıklamasında o belgeye işaret yeter. Aksi hâlde her kanıt cümlesi aramaya yeni bir “yanlış eşleşme” ekliyor.
2. **Kataloğa toplu seri eklendiğinde arama testi koşulsun.** Bu ölçümde kullanılan 24 soruluk test birkaç dakikada koşuyor ve LLM gerektirmiyor. Repoya alıp “katalog değiştiyse önce bunu çalıştır” kuralı konabilir; bu geceki doğruluk ve hız sorunlarını seri eklendiği anda gösterirdi.

## Ek: ölçüm ortamı

- Çalışma veritabanı: `lakehouse-core/data/lakehouse.duckdb.breadth_test` (6.304 seri, 232.217 gözlem); eski durum için 16 Eylül gece yarısı kopyası (1.941 seri).
- Katalog düzeltmesinin tamamı: `lakehouse.duckdb.search_exp` kopyasında (repoda değişiklik yapılmadan).
- Arama modu `RETRIEVAL_MODE` ortam değişkeniyle zorlandı (`bm25` / `auto`); anlam araması `kkbhackathon2026/Qwen3-Embedding-8B`.
- Deney script'i (monkeypatch dahil) şu an yerel; öneri 7.2 kabul edilirse repoya alınabilir.
- Arama hızı ölçümü `d45c53d` sonrası gerçek kodla, monkeypatch olmadan tekrarlandı.
