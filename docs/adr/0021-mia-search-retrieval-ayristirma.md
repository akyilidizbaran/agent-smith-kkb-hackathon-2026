# ADR-0021: MIA, Search ve Retrieval üç ayrı sağlayıcı katmanı

**Durum:** Kabul edildi · **Tarih:** 2026-09-10 · **Kaynak:** Mentör yanıtı

## Bağlam
Mentöre üç soru sorulmuştu: kota/hız limiti, web search için dış servis politikası,
yerel yardımcı modeller. Üçü de cevaplandı:

1. **Kota:** Özel request/token limiti yok; kapasite yetersiz kalırsa artırılır.
   "Mimariyi kota kaygısıyla kısıtlamanıza gerek yok; retry/backoff koyun."
2. **Web search/scraping:** Serbest — Tavily, Firecrawl vb. Kısıt yalnız Snowflake,
   BigQuery gibi cloud warehouse'larda. "Provider bağımsız/modüler tasarlayın."
3. **Yerel yardımcı modeller:** Sentence-transformer, reranker, BM25 retrieval/ranking
   tarafında serbest. "Ana LLM MIA kalacak şekilde ayrı katmanda konumlandırın."

Ve açık talimat: *"MIA / Search / Retrieval katmanlarını birbirinden ayrıştırarak
ilerleyin; ileride servis veya yöntem değişse bile ana yapıyı değiştirmek zorunda
kalmayalım."*

## Karar
`LLMClient` için zaten uygulanan deseni iki katmana daha uygulamak:

| Katman | Sözleşme | Sağlayıcı |
|---|---|---|
| LLM | `llm/LLMClient` | MIA (sabit) |
| Search | `contracts/search.SearchClient` | Tavily / Firecrawl / DuckDuckGo — `.env` |
| Retrieval | `contracts/retrieval.{LexicalIndex, Embedder, Reranker}` | DuckDB FTS · MIA embedding · yerel cross-encoder — bağımsız değiştirilebilir |

Agent ve araçlar yalnız Protocol'leri görür. Retrieval'ın üç yeteneği ayrı Protocol'dür;
birini değiştirmek diğerine dokunmaz. `reciprocal_rank_fusion` modelsiz birleştirme
sağlar.

Retry: 429'da `Retry-After` header'ına uyulur, yoksa üstel bekleme.

## Etkileri
- **ADR-0015 yeniden açıldı.** Embedding/reranker artık kural engeliyle değil, yalnız
  ölçümle ertelenir. Tetikleyici aynı: katalog büyümesi.
- **Web araçları önündeki engel kalktı.** `web_search` / `web_url` `SearchClient`'a karşı
  yazılabilir; sağlayıcı seçimi ayrı, ucuz bir karar.
- **Kota kaygısı kalktı:** nihai sentez turunda reasoning açmak, LLM-as-reranker gibi
  token isteyen tercihler artık ölçümle değerlendirilebilir.

## Değerlendirilen alternatif
Search'ü doğrudan bir sağlayıcının SDK'sına bağlamak — hızlı ama mentörün açıkça
istemediği bağımlılık. Reddedildi.
