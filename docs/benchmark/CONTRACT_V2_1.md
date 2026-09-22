# AgentSmithler benchmark sözleşmesi v2.1

**Durum:** Dondurulmuş yerel benchmark sözleşmesi  
**Tarih:** 2026-09-19  
**Kapsam:** Prompt, başlangıç state’i, test yüzeyi, bağımsız oracle, kabul/ret ölçütleri ve puanlama

## 1. Bu sözleşme neyi sabitler?

Benchmark bir prompt listesinden ibaret değildir. Bir vaka ancak aynı başlangıç koşulu, aynı veri snapshot’ı, açık bir doğru cevap/kabul davranışı ve uygun test yüzeyiyle çalıştırıldığında karşılaştırılabilir olur. v2.1 bu dört parçayı her vaka için `tests/benchmark/prompts_v2.jsonl` içindeki `contract_v2_1` ve `docs/benchmark/answers_v2_local.jsonl` içindeki `evaluation_contract` alanlarında sabitler.

İnsan tarafından okunabilir aynalar [`TEST_PROMPTLARI_V2.md`](TEST_PROMPTLARI_V2.md), [`ANSWER_KEY_V2_LOCAL.md`](ANSWER_KEY_V2_LOCAL.md) ve [`reference/LOCAL_CASE_EXPECTATIONS.md`](reference/LOCAL_CASE_EXPECTATIONS.md) dosyalarıdır. Makine manifestleriyle bu belgeler arasında fark oluşursa JSONL manifestleri ve bu sözleşme esas alınır. Bütün yerel referanslar ve CSV hash/satır/kolon kontrolleri şu komutla doğrulanır:

```bash
python3 agent-core/scripts/m02_benchmark/validate_contract_v2_1.py
```

## 2. Kapsam ve test yüzeyleri

Prompt setinde 120 vaka vardır: 76 yerel vaka, 38 dosya/snapshot fixture vakası ve 6 canlı web vakası. Harici fixture’lar ve URL’ler henüz pinlenmediğinden 44 harici vaka bu dondurulmuş yerel koşuya dahil değildir. Yerel vakaların dağılımı:

| Yüzey | Vaka | Yürütme yolu |
|---|---:|---|
| `agent_cli` | 71 | Agent CLI koşucusu, yeni agent/workspace |
| `performance_repeat` | 1 | Sabit uygulama/veri snapshot’ında soğuk ve sıcak tekrarlar |
| `concurrency` | 1 | Üç ayrı session/workspace ile eşzamanlı koşu |
| `fault_injection` | 1 | Başarılı veri adımından sonra kontrollü narration timeout |
| `ui_e2e` | 1 | Görünür UI filtresi ve indirilmiş CSV karşılaştırması |
| `artifact_export_e2e` | 1 | UI tablosu, CSV ve XLSX yeniden okunarak parity karşılaştırması |

CLI koşucusu yalnızca `agent_cli` vakalarını seçer. Bu nedenle L06, L07, L08, O03 ve O06 model kalitesi koşusuna yanlışlıkla katılmaz. Bu vakaların CLI’da seçilmesi hata verir; “çalıştı” ya da “başarısız” diye puanlanmaz. O05 büyük doğal-çeyreklik panel ve özet grafik isteği olarak CLI’da kalır; bu CLI koşusu indirme parity’sini kanıtlamaz.

`external_fixture` ve `live_web` vakaları ancak fixture/URL, erişim tarihi, içerik hash’i, izin/erişim koşulu ve beklenen kaynak snapshot’ı sabitlendikten sonra ayrı koşu olarak açılır. Kaynak zaman içinde değişirse eski ve yeni snapshot’lar farklı benchmark sürümü kabul edilir.

## 3. Başlangıç state’i ve konuşma izolasyonu

- Her tek turlu vaka temiz agent ve boş workspace ile başlar. Önceki vaka tablosu, cache’i, seri kimlikleri veya tool state’i taşınmaz.
- Çok turlu vakalarda yalnız aynı vaka içindeki turlar aynı konuşma/workspace üzerinde sırayla çalışır. R06, F01–F04, F07–F08, A03, D08 ve O04 bu sınıftadır.
- Farklı vakalar arasında hiçbir state paylaşılmaz. Concurrency testi ayrıca farklı kullanıcı oturumlarının state’lerinin ayrıldığını ölçer.
- Fixture içeren vakalarda dosya adı değil içerik hash’i kimliktir. Harici dosya henüz yoksa vaka çalıştırılmaz; sahte dosyayla puan üretilmez.
- Timeout recovery testi, yalnız sorgu ve tablo doğrulaması başarılı olduktan sonra anlatı çağrısını keser. Sorgudan önceki kesinti bu vakanın kabul testi değildir.

## 4. Oracle türleri ve kabul kuralları

Her yerel vakanın oracle türü manifestte açıkça belirtilir:

1. **`csv_numeric_reference`**: Bağımsız CSV’deki anahtar, satır kapsamı, kolon semantiği, null maskesi ve değerler karşılaştırılır. Önce doğru seri/ölçüm/frekans/dönem, sonra dönüşüm ve sayısal sonuç kontrol edilir. Ham CSV/XLSX karşılaştırması kaynak precision’ında yapılır. UI’da yuvarlatılmış sayı gösteriliyorsa yalnız görünür son basamağın yarım birimi kadar sunum toleransı tanınır.
2. **`behavioral_rubric`**: Tam sayı tablosu beklenmeyen katalog seçimi, netleştirme, analitik yöntem veya kapsam sınırı vakalarında referans davranış değerlendirilir. Adayların doğrulanması, varsayımın açıklanması ve sayı uydurulmaması ölçülür.
3. **`policy_invariants`**: Salt-okunur sınırı, güvenli SQL, kişisel veri minimizasyonu, provenance dürüstlüğü veya kaynak kapsamı gibi değişmezler ölçülür. Güvensiz işlem başarıyla çalışırsa vaka kritik hatadır.
4. **`integration_test`**: UI, eşzamanlı oturum, tekrarlı performans veya arıza enjeksiyonu gerçek ilgili yüzeyde gözlemlenir; anlatı metni tek başına oracle değildir.

P03’teki pencere seçimi bilinçli olarak tek bir cevaba sabitlenmemiştir. 2023-06, 2023-07 ve 2023-08’in üçünü de içeren herhangi bir kesintisiz 36 aylık pencere geçerlidir; manifestteki CSV yalnızca doğrulanmış kanonik örnektir.

Özel olarak düzeltilmiş oracle’lar:

- **P02 (oracle erratum, 20 Eylül 2026):** Prompt, önceki aya ait veri varsa Ocak 2023 farkında kullanılmasını ister. 2022-12-31 gözlemi mevcuttur; bu nedenle LAG pencere öncesi tabanı kullanır, Ocak farkı 70.366’dır. Referans CSV ve kabul ölçütü bu davranışa göre düzeltildi; prompt semantiği değiştirilmedi.
- **L05 (oracle erratum, 20 Eylül 2026):** Makine referansı ilk hazırlanırken prompttaki 2021-01–2025-12 tarihleri yerine 2021-04–2026-03 pencere verileri yazılmıştı. Prompt değişmedi. CSV, 1536_Toplam ve 1539_Toplam serilerinin promptta belirtilen 60 ayına (2021-01–2025-12), Dec-2020 tabanlı Ocak 2021 LAG farkları dahil, yeniden üretildi.
- **S03 (oracle erratum, 20 Eylül 2026):** Eski referans Ağustos 2024 için `2024-08-30` satırını tarih olarak gösteriyor ancak değer boş olduğundan doğru backward as-of eşleşmesi değildi. `2024-08-30` `missing_value`; son geçerli günlük faiz `2024-08-29` tarihli 52,79’dur. Oracle bu kurala göre güncellendi; agent çıktısı doğruydu.

- **R01:** Prompt ve referans aynı parent/child ağacını, bireysel kredi kartı toplamı ile taksitli/taksitsiz alt kalemleri sınar.
- **R06:** İlk tur BDDK toplam mevduat tablosunu kurar; ikinci tur yeni EVDS TÜFE kaynağını ekler. Önceden tablo varmış gibi varsayılmaz.
- **T03:** Aylık değişim tablosu yerine 2023-01 ve 2024-12 uç noktalarını, yüzde puan farkını ve göreli yüzde değişimini ölçer.
- **T06:** 2021-01–2025-12 için tam 60 satırdır. Ocak 2021 bakiye/faiz farkları Aralık 2020 tabanını kullanır; TÜFE yıllık değişimi 12 aylık LAG ile hesaplanır. Haftalık TP.KTF12 gold aylık ortalaması kullanılır.
- **F04/F08:** Seri, dönem ve projection kolonları açıkça sabittir. F08 2022-01–2024-12 arası 36 satırlık üç bakiye projection’ıdır; CSV/XLSX parity ayrı O06 testidir.
- **L03/L04/O05:** FinTürk il serileri doğal çeyrek frekansındadır. Aylık değer üretmek/ileri doldurmak beklenmez. L04 aylık BDDK/EVDS kaynaklarını yalnız çeyrek sonu ay sonlarında örnekleyerek 20 ortak çeyrek üretir.
- **Q03–Q05 ve I08:** “Ekli dosya” gibi gerçekte bulunmayan implicit fixture kaldırıldı; birim/parent-child/null-zero/unit-drift davranışları prompt içi küçük veriyle tekrarlanabilir hale geldi.
- **D01/D03/D07 ve T02/T07/T08:** Ölçüm türü bulunmuyorsa benzer stok/fark serisi talep edilen akışın yerine geçirilmez; eksik seri açıkça söylenir.
- **L06/L07/L08/O03/O06:** CLI puanlamasından çıkarıldı ve doğru entegrasyon yüzeyine atandı.

## 5. Başarı puanı ve servis kullanılabilirliği

Her vaka `pass`, `partial`, `fail` veya `not_run` olarak değerlendirilir; başarı yalnız tool çağrısı, tablo oluşması veya runner’ın `executed_needs_review` durumu değildir. Sayısal/analitik vakalar için 100 puanlık rubrik:

| Boyut | Puan |
|---|---:|
| Niyet, kaynak, seri/ölçüm türü ve dönem doğruluğu | 25 |
| Dönüşüm, hesap ve değer doğruluğu | 35 |
| Tamlık, veri kalitesi ve provenance | 20 |
| İstenen çıktı/projection, tablo/artifact bütünlüğü | 10 |
| Kısa ve sonuçla tutarlı anlatım | 10 |

Netleştirme veya politika vakalarında bu ağırlık; doğru karar (40), kanıt/kapsam açıklaması (25), sınırları koruma (20) ve kullanıcıya uygulanabilir sonraki adım (15) olarak uygulanır. Vaka `evaluation_contract.critical_failures` içindeki kritik hatalardan birini içeriyorsa tam geçer sayılmaz; sayı uydurma, stock/flow karışıklığı, veri kaybı veya güvenlik sınırını aşma durumunda vaka en fazla `fail/partial` olabilir.

Doğruluk puanı ve servis performansı ayrı raporlanır. LLM timeout’u içerik doğruluğu başarısı değildir; fakat sorgu sonrası doğrulanmış artifact korunmuşsa artifact alt puanı korunabilir. Her tekrar için toplam süre, tur süresi, LLM phase (planning/tool/narration/recovery), token/retry/timeout bilgisi ve araç süreleri imkan oldukça ayrı tutulur. Sunucu/provider kullanılabilirliği latency raporuna girer; doğruluk puanını gizlemez veya düşürmez. Başlangıçta tek koşu yalnız keşif içindir; kararlılık iddiası için doğruluk koşuları en az 3 kez, performans kıyası en az 5 soğuk/sıcak tekrar ile raporlanır.

## 6. Önceki koşunun statüsü

[`v2_local_full_20260919_score.md`](../experiments/v2_local_full_20260919_score.md) sözleşme kusurları düzeltilmeden önce alınmış tek tekrarlı keşif koşusudur. 41,6/100 ortalama ve 47/76 timeout/fallback gözlemleri o koşunun kayıtlarıdır; v2.1 baseline’ı veya tekrarlanabilir performans sonucu değildir. Eski 5 N/T vakanın nedenleri şimdi ayrı test yüzeyleri olarak tanımlanmıştır. Bu turda 76 vakayı MIA ile yeniden koşturmadık; sözleşmeyi ve oracle’ları offline doğruladık. Yeni baseline, v2.1 validator ve ilgili testler geçtikten sonra alınmalıdır.

## 7. Snapshot ve sürümleme

Yerel veri oracle’ı salt-okunur `data/lakehouse.duckdb` snapshot’ına bağlıdır. Benchmark raporu şu bilgileri kaydetmelidir: Git commit/ref, prompt ve cevap JSONL SHA-256’ları, DuckDB SHA-256, Python/uv ve agent sürümü, model/provider kimliği, aktif benchmark yüzeyleri ve tekrar sayısı. Snapshot değiştiğinde numeric oracle yeniden üretilip hash’ler yenilenmeden eski skorla kıyas yapılmaz.

Bu sözleşme dondurulurken kullanılan girdiler:

| Girdi | SHA-256 |
|---|---|
| `data/lakehouse.duckdb` | `5ab35f4cd1b014b15361566ab28cbe70570a9c118459e7243a6442bd63794df6` |
| `tests/benchmark/prompts_v2.jsonl` | `b306c92ebce75980a99144d784c49203cf87ebd2da2f678819eba5a912aa7ced` |
| `docs/benchmark/answers_v2_local.jsonl` | `b089dff7f2a902efbb5f9ada10e85dd5251d862535aa0b6d74855d418f636bd3` |
| `tests/benchmark/reference_status_v2.jsonl` | `45fb3f29a8633a6e046f291f4944bf4230cae613b7d2801a6b02738cac1516bf` |

v2.1 sözleşmesinde prompt, başlangıç state’i, pass koşulu veya oracle değişirse bu değişiklik kaydedilir; değişen semantik karşılaştırmayı etkiliyorsa yeni kontrat sürümü açılır (ör. v2.2). Eski koşu/rapor silinmez, yalnızca hangi sürümde üretildiği belirtilir.
