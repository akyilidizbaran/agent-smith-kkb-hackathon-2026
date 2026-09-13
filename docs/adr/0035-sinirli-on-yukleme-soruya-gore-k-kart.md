# ADR-0035: Sınırlı ön-yükleme — soruya göre seçilen k kart ve gerçek değerler, token bütçesiyle

**Durum:** Kabul edildi (D1) · **Tarih:** 2026-09-12 · **Sıradaki:** D2 BM25 dizini · ADR-0013'ü uygular

## Bağlam
ADR-0013 dokuz gün önce planlanmıştı: bir sorunun ilk 3–4 turu arama (search → describe →
distinct_values), hiçbiri karar değil; her arama modele gidip dönüyor. Ön koşulu "katalog
büyüsün" idi; büyüdü (1.620 seri, 6 sorgulanabilir + 3 Gold tablosu). Büşra'nın V3 ölçümü
(E8, Blok C) yolu gösterdi: katalog ~6k token altındayken tamamı prompt'ta doğruluğu
düşürmüyor ve turları 6,9 → 3,9'a indiriyor; üstünde hem yavaşlıyor hem hata artıyor.
Ama "tamamı" gerçek katalogda 44 bin token'dı (ADR-0026 ile 522). Yol haritası D1: tamamı
değil, retriever'ın seçtiği k seri, bütçe token'la sınırlı.

## Karar
`core/context.build_question_context(lakehouse, question, budget_tokens=6000, k=8)`,
soru geldiğinde deterministik çalışır ve tek system mesajının sonuna eklenir:

1. **Seçim:** katalog k'den küçükse hepsi; değilse `search_datasets(question, k)`.
   Retrieval sözleşmenin arkasında; D2'de BM25 gelince bu satır değişir, gerisi değişmez.
2. **Kompakt kart:** kimlik, ad, kısa açıklama, ölçümler ve birim, kapsam, erişim SQL'i
   (kimlik tablo adı değilse), uyarı notları (doğrulanmamış, taslak, bayat, Gold). Tam
   prompt kartının kolon listesi yok; gerekirse `describe` duruyor.
3. **Gerçek değerler** (ADR-0009 bozulmaz): küçük katalogda (≤ 12 dataset) kırılım
   kolonlarının `DISTINCT` değerleri kartla gelir, alt toplam satırları işaretli, "SADECE
   BİRİNİ seç" uyarısıyla. Model değerleri görmüşse `distinct_values` turu yapılmış sayılır.
4. **Bütçe:** kartlar retrieval sırasıyla eklenir, bütçe dolunca kesilir; kalan seriler
   tek satırlık dizin olarak girer, o da sığmazsa yalnız sayı ve "lakehouse_search ile bul".
5. **Kural prompt'ta:** "Kartı gördüğün seri için search/describe çağırma; değerler
   listelendiyse distinct_values de gerekmez; doğrudan sorguya geç. Kartlarda olmayan seri
   gerekirse lakehouse_search." Araçlar kayıtlı kalır (ADR-0013'ün riski: yanlış ön-yükleme
   modeli hapsetmemeli).
6. **Ölçü aracı:** `AgentAnswer.usage` (prompt/completion token, çağrı sayısı) ve
   `AgentAnswer.context`; golden koşucusu vaka başına ortalama prompt token ve LLM çağrısı
   basar. `PRELOAD_BUDGET_TOKENS=0` kapatır; `PRELOAD_K` seçim sayısı.

## Ölçüm (aynı gün, aynı model, ön-yükleme kapalı → açık)

| Küme | Doğruluk | Araç adımı / vaka | LLM çağrısı / vaka | Prompt token / vaka | Toplam süre |
|---|---|---|---|---|---|
| Seed G1–G7 | 7/7 → 7/7 | 7,0 → **3,3** | 9,0 → **5,3** | 54.953 → **36.354** | 91 s → 69 s |
| Gerçek DB G1, G8, G9, G10, G11a–c | 7/7 → 7/7 | 3,0 → **1,6** | 4,3 → **3,1** | 30.682 → **26.919** | 36 s → 36 s |

- Retrieve rolü adımları seed'de 35 → 11: keşif turları LLM turu olmaktan çıktı, karar
  turları (execute 13 → 12) aynı kaldı. G1 ve G4 tek adıma indi (`lakehouse_query`).
- Ön-yükleme bedeli: seed'de 1 kart + değerler ~1.139 token; gerçek DB'de 8 kart + 1 dizin
  satırı ~1.844 token. Hedef 6.000'in altında.
- Kanıt zinciri gerçek DB'de 5/5 tam kaldı; anlatı doğrulama temiz.
- Hedef "V3'ün 2,9 turuna yaklaşmak" aşıldı: gerçek DB'de 1,6 araç adımı, 3,1 LLM çağrısı.

## Neden tamamı değil, k kart
Gerçek katalogda "tamamı" 44 bin token'dı ve V3 eşiği 6k'da doğruluğun düştüğünü ölçtü.
Seçimin bedeli: retriever yanlış seçerse model kartlarda olmayan seriyi `lakehouse_search`
ile bulmak zorunda, yani eski yola düşer; hapsolmaz. D2'de BM25 seçimi güçlendirecek ve
arama boş dönünce "katalogda var, yüklenmemiş" bilgisi gelecek.

## Açık kalan
- Token tahmini karakter/3,2; gerçek sayı usage'dan okunuyor ve raporlanıyor, bütçe kararı
  tahminle veriliyor. Sapma ölçülmedi; D3'te usage ile karşılaştırılacak.
- Değer listesi yalnız küçük katalogda; Silver seri-merkezli katalogda kırılım `entity_id`
  ve hariç tutuluyor. FinTürk 81 il gelince il değerleri kart yerine seri kimliğinde.
- Çok turlu konuşmada ön-yükleme her soruda yeniden kurulur; önceki turun kartları
  history'de kalmıyor, yalnız system mesajı güncelleniyor. Ölçüldü: G6/G7 ikinci turda doğru.

## İlgili
ADR-0009 (gerçek değerler), ADR-0013 (planlanan karar), ADR-0014 (recall önceliği),
ADR-0026 (sorgulanabilir seri), V3 `core/context.py` (E8 ölçümü, esin kaynağı).
