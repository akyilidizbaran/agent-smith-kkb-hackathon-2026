# ADR-0036: BM25 sözlük dizini sözleşmenin arkasında; "yok" ile "var ama yüklenmemiş" ayrı cevaplar

**Durum:** Kabul edildi (D2) · **Tarih:** 2026-09-12 · **Sıradaki:** D3 kararlılık + güçlendirme

## Bağlam
İki ölçülmüş açık vardı:
1. **Arama basit alt dize sayımıydı.** "kredileri" ile "kredisi" eşleşmiyor, "İhtiyaç" ile
   "ihtiyac" eşleşmiyor; 1.620 seriye ölçeklenmez. Retrieval sözleşmesi (`contracts/retrieval.py`,
   ADR-0021) BM25 için yer bırakmıştı, uygulaması yoktu. Mentör: BM25/embedding/reranker
   yardımcı katmanda serbest, ana LLM MIA kalır.
2. **Arama boş dönünce model dönüyordu.** Gerçek DB'de ihtiyaç ve taşıt kredisi serileri
   katalogda tanımlı ama çekilmemiş; arama boş dönünce model on kez farklı sözcükle aradı
   ve adım bütçesini yaktı (G5/G6, ADR-0031 ölçüm notu). ADR-0026 "var ama yüklenmemiş"
   ayrımını `get_dataset` için yapmıştı, `search` için değil. Sonra G12 ile daha kötüsü
   ölçüldü: arama konut serisini "kredisi" ortak sözcüğüyle döndürünce model konutu taşıt
   sanmadı ama SQL ile keşfe girişti: 10 LLM çağrısı, 125 bin token, cevap yine "yüklenmemiş".

## Karar 1 — `core/lexical.Bm25Index`, iki adaptörün de arkasında
Saf Python Okazaki BM25 (k1 1,5, b 0,75), dış bağımlılık yok, deterministik (skor, sonra
kimlik). Türkçe için iki küçük karar:
- **Katlama:** `İ/ı/ş/ğ/ü/ö/ç` ASCII'ye, küçük harf; kaynak ve soru her iki yazımla geliyor.
- **Ön ek eşleşmesi:** 5+ karakterlik ön ekler dizine girer ("kredi" → "kredisi"), ama
  **tam sözcüğün yarısı ağırlığında** ve **tek başına isabet sayılmaz**: en az bir tam sözcük
  eşleşmesi şart. Ölçüldü: şartsız hâlde "ihtiyaç kredileri" yalnız "kredi" ön ekiyle konut
  serisini döndürüyordu.
- Takma adlar 3× tekrarla ağırlıklı (ADR-0003: kullanıcının söyleyeceği ifadeler); seed
  kataloğunda kolon açıklamaları ve örnek değerler de dizinde.
- Her isabet `meta["matched"] / meta["unmatched"]` taşır: hangi sorgu sözcükleri eşleşti,
  hangileri eşleşmedi. Arama kartı bunu yazar: "eşleşen: kredisi | EŞLEŞMEYEN: tasit — bu
  seri sorunun tamamını karşılamıyor olabilir".

Silver adaptörü isabet yoksa boş döner (ADR-0026 korunur); seed adaptörü tek tablolu
katalogda ilk N tabloya düşer (orada "bulunamadı" yanıltıcı olurdu). Ön-yükleme (ADR-0035)
seçimi de bu dizinden geçer.

## Karar 2 — Yüklenmemiş seriler ayrı dizinde, cevapta ayrı satırda, tekrar denenmez
`SilverLakehouse.search_uningested(query)`: kataloglu ama gözlemi olmayan seriler üzerinde
ayrı BM25 (kimlik + ad). Arama aracı üç durumu ayırır:
- **Sorgulanabilir isabet yok, yüklenmemiş eşleşme var** → `DATASET_NOT_FOUND`, **tekrar
  denenmez**, adaylar yüklenmemiş kimlikler, kart: "Katalogda tanımlı ama HENÜZ YÜKLENMEMİŞ:
  … Yeniden arama yapma; kullanıcıya verinin henüz çekilmediğini söyle."
- **Hiç eşleşme yok** → ilk boş aramada "en fazla bir kez daha ara", ikinci üst üste boş
  aramada tekrar denenmez hata (`EMPTY_LIMIT=2`).
- **Her isabet kısmi ve eşleşmeyen sözcük yüklenmemiş bir seriyi işaret ediyor** (G12'nin
  hâli: konut bulundu, taşıt yüklenmemiş) → kart hem isabetleri hem "onları aranan serinin
  yerine KULLANMA" uyarısını verir; ikinci böyle aramada tekrar denenmez hata
  (`PENDING_LIMIT=2`). Sebep: konut ile ihtiyaç kredisi karşılaştırması gibi sorularda
  konut yarısı meşru, ilk arama onu getirmeli; ikincisi artık keşif değil döngü.

## Karar 3 — Bilinmeyen araç adı tekrar denenebilir
On üç araçla model ara sıra ad uyduruyor ("workspace"). `UNKNOWN_TOOL` tekrar denenmez
sayılınca harness araçsız son tura düştü ve model veri çekmeden cevap yazdı (G11a, gerçek
DB, 1/3). Artık tekrar denenebilir; aday listesi (kayıtlı araç adları) zaten dönüyor.
Ölçüldü: G11a 2/2, 2 adım.

## Ölçüm
- Birim testleri 235 → **242**: dizin (katlama, ön ek, takma ad ağırlığı, deterministik sıra,
  boş), adaptör (ekli sözcük, yüklenmemiş arama), araç (yüklenmemiş → tekrar denenmez;
  boş → ikinci kezde; kısmi → ikinci kezde), kanıt zincirinde türetilmiş kolon.
- **G12** (gerçek DB, "2025 taşıt kredisi aylık"; taşıt katalogda var, yüklü değil):
  ilk sürüm **0/3, 8–11 adım, 125 bin token**; kısmi-isabet kuralı sonrası **3/3, 2 adım,
  4 s, 25 bin token**; cevap: "katalogda tanımlı, verisi çekilmemiş", konut serisi taşıt diye
  kullanılmadı, sayı üretilmedi.
- G5/G6 gerçek DB'de (kapsam dışı vakalar): 10 arama → 2 arama, sonra dur.
- Seed G1–G7: 7/7, adım 2,3, araç hatası 0, anlatı 7/7. Gerçek DB G1, G8–G11: geçiyor,
  kanıt zinciri 4/4.
- Yan bulgu: `workspace_compute_column` türetilmiş kolona provenance yazmıyordu; kanıt zinciri
  sebepsiz "eksik" diyordu. Türetilmiş kolonun provenance'ı artık formülün kendisi; zincir
  kaynak kolonlar üzerinden devam eder; provenance'sız kolon adıyla gap'e yazılır.

## Açık kalan
- Kök ayırma yok; ön ek yaklaşımı Türkçe'nin çoğu ekini karşılıyor, ünlü uyumu değişimlerini
  ("kitap/kitabı") değil. Embedding + RRF sözleşmede hazır, ölçüm gerektirir (ADR-0015).
- `search_uningested` yalnız Silver adaptöründe; seed'de yüklenmemiş kavramı yok.

## İlgili
ADR-0003, ADR-0014 (recall önceliği), ADR-0015, ADR-0021, ADR-0026, ADR-0035. Görev çipi
`task_744beae4` bu ADR ile kapandı.
