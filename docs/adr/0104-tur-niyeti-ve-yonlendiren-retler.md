# ADR-0104: Tur niyeti tek yerde; yürütülmemiş retler teslimi kapatmaz, retler yol gösterir

**Durum:** Kabul edildi · **Tarih:** 2026-09-23 · **İlgili:** ADR-0103 (DeepSeek), PROJECT_MEMORY 2.140–2.142

## Bağlam
DeepSeek 76 vakalık koşunun (68,1/100) ham kaydı ve çekirdeğin kural envanteri iki sorun gösterdi.

**Niyet dağınıktı.** Soruyu sınıflandıran desenler `core/agent.py`'de dağınıktı; her kontrol ham metni kendisi okuyordu.
- Kaynak özeti 9 turda istenen sonucun yerine geçti: F01/F03/F04/F07/F08, D04, I08, O07, O08. O turlar kaynak sormuyordu,
  kelime yalnız kısıt olarak geçiyordu.
- "fark" dönüşüm sayılmıyordu; "aylık farkı hesapla" (F07.2) tablo teslimi sanıldı.

**Retler modelin yolunu kesiyordu.** Başarısız vakalarda sık görülen kodlar: CATALOG_SEARCH_BUDGET (7 vaka), GOLD_REQUIRED (7),
CLARIFY_NOT_ALLOWED (4), DUPLICATE_CALL (4).
- Yürütülmemiş bir netleştirme reddi bile doğrulanmış tablo teslimini ve deterministik tamamlamayı kapatıyordu, çünkü
  "başarısız adım var" sayılıyordu.
- GOLD_REFUSED modele başka bir Gold aracını öneriyor, ama turu aynı anda bitiriyordu.
- Turu bitirmeyen retlerin mesajı yine "kullanıcıya durumu açıkla" diye kapanıyordu.
- Arama bütçesi dolunca model adayları bulamayıp döngüye giriyordu.
- Kaynak kısayolu konuşma hafızasına yazmıyordu; `ask()`'teki sonradan düzenlemeler bir önceki turun cevabını eziyordu.

## Karar
1. **`core/turn_intent.py`:**
   - Desenler buraya değiştirilmeden taşındı.
   - `classify(question)` bir `TurnIntent` döndürür (önbellekli). Alanları: chart, analytics, transformation, table_delivery,
     narrative_or_analysis, interpretation, comparison, premise, source_question, join, file_ref ve `read_only_source`.
   - Öncelik kuralı (`read_only_source`: kaynak sorusu, tablo ya da dönüşüm istemiyor) tek yerde durur.
   - `agent.py` artık ham desenle soru okumaz, `classify(question).x` okur.
   - Tek bilinçli desen değişikliği: `fark` / `difference` dönüşüm sayılır; "farklı" sayılmaz.
2. **Niyet test tablosu:** `tests/test_turn_intent.py` + `tests/fixtures/turn_intent_benchmark.json`. 76 vakanın 82 turunun
   sınıflandırması kilitlidir; bir desen değişince hangi turun kaydığı listelenir.
3. **Yürütülmemiş retler (CLARIFY_NOT_ALLOWED, DUPLICATE_CALL, CATALOG_SEARCH_BUDGET) başarısız veri adımı sayılmaz**
   (`_has_blocking_failure`). Veri adımı hataları ve doğrulama geri göndermeleri teslimi kapatmaya devam eder.
4. **Retler yol gösterir:**
   - Arama bütçesi reddi, bu turdaki aramaların bulduğu seri kimliklerini `ADAYLAR` olarak taşır.
   - GOLD_REFUSED, alternatifi modelin kendisinin yürütebileceği bir durumsa (NOT_DECOMPOSABLE, DECOMPOSITION_REQUIRED,
     INACTIVE_SERIES, UPSAMPLING_REFUSED) turu bitirmez. Kullanıcı onayı gereken UNVERIFIED_SEMANTICS turu kapatır.
   - `terminal=False` retlerin kapanış cümlesi artık "tekrarlama, tur devam ediyor" diyor; "kullanıcıya durumu açıkla" demiyor.
5. **Kaynak kısayolu** turu konuşma hafızasına yazar.

## Kapsam dışı (bilerek)
- `agent.py`'nin dosyalara bölünmesi.
- Sonradan metin düzenlemelerinin (`_final_exit`, `humanize_internal`, notlar) tek sonlandırma katmanına toplanması.

İkisi de benchmark puanını değiştirmez; son değişiklik turunda riskleri yüksek.

## Sonuçlar
- Tam `agent-core` suite 969 geçti.
- Etki, 71 vakanın 3'er tekrarıyla ölçülür (`docs/experiments/v2_deepseek_adr0104_r3_20260923*`). Sayısal vakalar
  `scripts/m02_benchmark/score_v2.py` ile puanlanır; bu betik 23 Eylül'de elle verilen puanlarla 27 sayısal vakanın 26'sında
  aynı sınıfı veriyor. Davranış ve politika vakaları sözleşmedeki rubrikle ayrıca puanlanır.
