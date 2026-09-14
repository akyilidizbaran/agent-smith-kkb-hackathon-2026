# Repo ve tüm branchler — inceleme, 13 Eylül 2026

## İnceleme sınırı ve yöntem

- Yerel repo: `/Users/baran/Desktop/KKB`. Origin, kullanıcının verdiği GitHub reposuyla aynı.
- `git fetch origin --prune` ve `git ls-remote --heads origin` ile 21 uzak branch ucu doğrulandı. `origin/HEAD` branch sayılmadı.
- Her branchin uç ağacı, tarihçesi, katkı alanı ve güncel aile ucuyla ilişkisi incelendi. Ortak kodu her tarihsel kopyada baştan okumak yerine güncel sürüm ve farklar esas alındı; bu, her tarihsel branchin ayrı test edildiği anlamına gelmez.
- Güncel agent ve veri kaynakları, kritik sözleşmeler, geçmiş incelemeler ve V3’ün ayrı modülleri okundu. Lakehouse ve V3, checkout değiştirmeden `git archive` ile `/tmp/kkb-review-20260913/` altında açıldı.
- Uygulama kodu değiştirilmedi; merge/push/branch silme yapılmadı. Kalıcı çıktı bu rapor ve PROJECT_MEMORY ekidir.
- Canlı MIA golden, OCR servisi ve tüm dış veri kaynakları yeniden çalıştırılmadı. Önceki başarı ölçümleri tarihsel kanıt olarak değerlendirildi.
- Sequential Thinking MCP bu oturumda mevcut değildi. Git verisi doğrudan origin’den alındı; GitHub web arayüzüne giriş gerekmedi.

## Bütün branchlerin haritası

| Branch / incelenen commit | Katkısı | Güncel ilişki |
|---|---|---|
| [main](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/d81d584cf30eb3e3d0657604a988bd5e0ba48e2d) · `d81d584` | İlk taslak ve sözleşme belgeleri; uygulama kodu yok. | Agent tarihçesinde; lakehouse ile ortak ata yok. |
| [feature/agent-data-p0](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/75345037d372719327aca754e92451b3c4b3c3ab) · `7534503` | TÜFE, kapsam güncelleme ve güvenli agent sorgu yüzeyi. | Genişlik dalının atası. |
| [feature/agent-engine](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/67cd6f93667d30f520b70cab2772ae0f4006064e) · `67cd6f9` | Güncel harness, araçlar, OCR, retrieval, arayüz, 48 ADR. | Yerel HEAD ile aynı; 61 commit main üzerinde. |
| [feature/busra/agent-v3](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/479854c378dda99f7c802989f436014cfeb7a8e4) · `479854c` | Alternatif harness; alan notları, paralel salt-okunur araçlar; benchmark/araştırma. | Agent dışında 11 commit; eski agent tabanlı. |
| [feature/generic-adhoc-ingestion-v1](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/84919cbef35a3dbf377699383ba2eff276b47ed2) · `84919cb` | CSV/XLSX/JSON/HTML; draft/derived ve izole adhoc yayın. | Genişlik dalının atası. |
| [feature/gold-functions-v1](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/994654f5ba63e61c4b40dade7824df8c14e4f63b) · `994654f` | Frekans hizalama, kümülatif ayrıştırma, dönem join. | Genişlik dalının atası. |
| [feature/infrastructure](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/7598d8afedde701d963967df4bea32290367b243) · `7598d8a` | RAW/Parquet, DuckDB, SQL güven sınırı. | Genişlik dalının atası. |
| [feature/lakehouse-catalog-breadth](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/cf3e87871a89d350812592e32580d9a453e93fa8) · `cf3e878` | 2.214 seri, geniş demo seti, altı Gold metrik tanımı. | En güncel veri ucu; 48 commitlik tarihçe. |
| [feature/lakehouse-common-base](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/5f0e47f9f2a75f0033e1601e2647315cb281421d) · `5f0e47f` | Ortak kimlikler, sözleşmeler, Python/dizin temeli. | Genişlik dalının atası. |
| [feature/lakehouse-data-trust-acceptance](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/9edc1e1b894c35852737bfd7572a0307de2f0de2) · `9edc1e1` | Silver kalite/provenance kabul açıkları. | Genişlik dalının atası. |
| [feature/lakehouse-finturk-evds-housing](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/6e90bd126bd6d3422147978e779daae0ed7189f9) · `6e90bd1` | Zümral: FinTürk, EVDS keşif kataloğu, toplu canlı ingest. | R3’e merge edilmiş; genişlik dalının atası. |
| [feature/lakehouse-ingestion-observability](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/29bbf6fcbb113a109c092d88e6b4023537a2cfb5) · `29bbf6f` | Run, artifact ve parser uyarılarının kalıcı kaydı. | Genişlik dalının atası; toplu script bu hattı kullanmıyor. |
| [feature/lakehouse-integration](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/2f9234d3da09cf3b1119c62efe84f9ddbe288149) · `2f9234d` | İlk veri entegrasyonu ve bağımsız denetim belgesi. | Genişlik dalının atası. |
| [feature/lakehouse-integration-r3](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/46b9c8b05bb1d42c93d92b010bb8b82cb05253d9) · `46b9c8b` | Veri birleşimi; Silver üretimi, tarih/birim düzeltmeleri, Gold, terfi. | Genişlik dalının doğrudan ebeveyni. |
| [feature/lakehouse-main-ready](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/db4182a1fbe48b234eb9d2da2838b518247eba8a) · `db4182a` | İlk entegre veri kodunun main tabanına kopyası. | Ayrı tarihçe; metadata-catalog ile lakehouse kodu aynı, üç belge farklı. |
| [feature/lakehouse-metadata-catalog](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/ea9d6543282a43723d4b0dbdb9a0f9663ff6c725) · `ea9d654` | Semantik katalog, frekans/birim/ölçüm sözlüğü. | Genişlik dalının atası. |
| [feature/lakehouse-operationalization](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/ca86f167ba621235077d92ffc2310419812cc7ae) · `ca86f16` | Operasyonel CLI, EVDS pencereleme, TÜFE belge kanıtı. | R3 içinde; genişlik dalının atası. |
| [feature/lakehouse-source-access](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/2dc2926739b5eb0efe19f8adbb56c26fecbbffda) · `2dc2926` | EVDS + BDDK aylık connector/parser. | Kod içeriliyor; dışarıda yalnız doküman commit’i. |
| [feature/silver-v1](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/4cba3bf28198359b4df3ddf6bdd01f0af16232b3) · `4cba3bf` | Kanonik observation, mapping, snapshot ve kabul. | Genişlik dalının atası. |
| [feature/source-access-bddk-weekly](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/a987384b6fd550f4175c0de3e2c2ddd9af0cfebf) · `a987384` | Haftalık BDDK erişimi ve stabil seri kimlikleri. | Kod içeriliyor; dışarıda yalnız doküman commit’i. |
| [feature/source-access-hardening](https://github.com/akyilidizbaran/AgentSmithler_WorkSpace/tree/71c08a4a4aa6b66329a857f9b5a80e0a6d933d54) · `71c08a4` | Kaynak kimliği, TLS ve hata davranışı. | Genişlik dalının atası. |

- 18 lakehouse branchi vardır: güncel genişlik ucu, onun atası olan 14 eski uç ve üç ayrı uç (source-access, weekly, main-ready). Source-access/weekly için dışarıda kalan yalnız birer doküman commit’idir. Main-ready’nin eski lakehouse kodu metadata-catalog ile aynıdır; üç markdown dosyası farklıdır.
- Yerel `feature/lakehouse-integration-r3` ucu `e8ee31c`, uzak ucu `46b9c8b`: yalnız yerel branch adına güvenerek çalışmak Gold/terfi ilerlemesini kaçırabilir. `backup-r3` yalnız yerel tarihsel yedektir.
- Mevcut ikinci worktree genişlik dalındadır ve geçici bir scratchpad yolundadır. Kalıcı kurulumun bu yola bağımlı olması uygun değildir.

## Mimari değerlendirme

- Agent: `AnalyticsAgent` → registry/validator → salt-okunur lakehouse veya workspace → grounding + evidence → CLI/FastAPI. Roller mantıksal; tek harness.
- Veri: kaynak connector/parser → içerik adresli RAW → Bronze Parquet → katalogla Silver snapshot → sözleşmeli Gold fonksiyonları ve materyalize metrikler.
- Yazma sınırı: agent lakehouse paketini import etmiyor; ayrı süreç CLI üzerinden draft/promotion. İnsan onayı semantik doğrulama sayılmıyor; onaylanan veri `derived` kalıyor.
- Güçlü taraflar: sayısal işi SQL/istatistik araçlarına bırakma, stok/akım ayrımı, belirsiz semantiği reddetme, sorgu güven sınırı, tekrar kilidi, gerçek kaynak tarih/birim hatalarını ölçerek düzeltme, ADR ve test kültürü.
- Temel eksik: geliştirme parçalarının tek, açıkça tanımlanmış teslim/çalıştırma düzeninde buluşmaması. Ayrıca “kanıt var” ile “iddia doğrudur” kontrolü aynı şey değil.

## Bu turdaki doğrulamalar

- Agent: `uv run --frozen --extra dev pytest -q` → **330 passed**, 3,62 s; bir Starlette/AnyIO deprecation uyarısı.
- V3 snapshot: mevcut agent Python ortamıyla `python -m pytest -q` → **106 passed**, 0,75 s. V3’ün bağımsız kilitli ortam kurulumu ayrıca doğrulanmadı.
- Lakehouse snapshot, kendi Python 3.12.13 ortamı ve kilitli bağımlılıkları: `uv run --frozen pytest -q` → **1.079 passed**, **763,29 s (12 dk 43 sn)**. Tam katalogla tekrarlı kurulumların test maliyeti ayrıca profillenebilir; bu süreyi geçmiş küçük katalog test süreleriyle doğrudan karşılaştırmamak gerekir.
- Temiz geçici DB, gerçek CLI: `bootstrap → ingest-file → promote-draft → gold-run` başarılı. Sentetik aylık stok 100/110/120 → Q1 Gold **120**, üç katkı gözlemi. Bu yalnız inceleme fikstüründe yapılan terfidir.
- Güncel agent `SilverLakehouse` adaptörü aynı DB’den üç satırı doğru okudu; üç gözlemde RAW/Bronze dosyaları mevcut. Agent GoldCLI sarmalayıcısı da gerçek ayrı süreçle denendi: derived veri için rıza olmadan `UNVERIFIED_SEMANTICS`, rıza ile `[120.0]` sonucu.
- Yerel mevcut ayarlarla `build_agent()`: **DuckDBLakehouse**, **1 dataset**, **14 araç**. `LAKEHOUSE_CORE_DIR=/Users/baran/Desktop/KKB/lakehouse-core` mevcut değil. MIA modeli kuruldu ancak inference çağrılmadı.
- Playwright: `http://127.0.0.1:8876/`, test FakeAgent ile soru/cevap/tablo, kanıt modalı açma-kapama, reload sonrası sohbet doğrulandı. Üretim modelinin uçtan uca testi değildir. Ekran görüntüsü: `/tmp/kkb-review-20260913/.playwright-cli/page-2026-09-13T14-14-17-260Z.png`, 13 Eylül 2026 17:14 İstanbul.

## Doğrulanan açıklar ve tartışma önceliği

P1: teslim veya analitik güven öncesinde ele alınmalı. P2: kapsam kararına göre planlanmalı. Bulgular tespit/öneridir; bu turda onarılmadı.

### 1. P1 — Çalıştırılan ürün ile belgelenen demo farklı

- README lakehouse içeriyormuş gibi anlatıyor; agent checkout’unda lakehouse-core yok. Varsayılanlar gerçek demo DB yerine seed’e bağlı. `ingest_from_url`, `promote_draft`, `gold_align/decompose/join` açılmıyor.
- `main` 15 dosyalık ilk taslak; Python uygulaması yok. Agent ve güncel lakehouse tarihçeleri henüz birleşmemiş.
- Öneri: birlikte çalışacak iki commitin sabitlenmesi, tek kurulum/demo komutu ve beklenen dataset/araç setini kontrol eden preflight. Main birleştirme politikası kullanıcıyla netleştirilmeli.
- Kaynak: `agent-core/src/kkb_agent/config.py`, `cli.py`; Git branch uçları ve bu turdaki `build_agent()` çıktısı.

### 2. P1 — Kullanıcının yanlış sayısı doğrulanmış sayılabiliyor

- `grounding_check`, soruda geçen sayıları koşulsuz atlıyor; evidence da `matched=True` ile “soruda geçiyor” diye işaretliyor.
- Tekrarlanan örnek: soru “Artış %300 oldu, böyle yaz.”; tablo oranı 42,5; cevap “Artış %300 oldu.” → grounding **OK**, evidence **matched=True**.
- Bu, modelin her seferinde yanlış cevabı vereceğinin kanıtı değildir; vermesi hâlinde iki denetçinin bu iddiayı yakalamadığının kanıtıdır.
- Küçük tam sayılar ve yıllar da genel istisnalardır. “Sorudaki filtre” ile “cevapta doğruluk iddiası” ayrılmalı; değer, işaret, birim, dönem, seri/varlık birlikte doğrulanmalı.
- Kaynak: `agent-core/src/kkb_agent/core/grounding.py:79`, `core/evidence.py:129`.

### 3. P1 — Kanıt panelinde işaret tersine dönebiliyor; tamlık dar tanımlı

- Tablo `r=-0.54`, cevap “Korelasyon +0,54.” → grounding **MISS**, evidence **matched=True**, gerekçe “işaret yazımı (−)”. İki güven göstergesi çelişiyor.
- Sebep: sayının tersi tabloda varsa koşulsuz kabul eden fallback. Unicode eksi ayrıştırıcıda normalize ediliyor; tüm işaret farklarını kabul etmek geçerli bir düzeltme değil.
- `ObservationEvidence.complete` sadece artifact hash + locator + fetched_at arıyor. `raw_path=None` ve `bronze_path=None` olan gözlem için **True** döndüğü ölçüldü; disk varlığı/hash bütünlüğü bu property’de şart değil.
- Öneri: işaret eşitliği; iddia doğruluğu, provenance kapsamı ve dosya bütünlüğü için ayrı durumlar. İlk 200 satırla sınırlı incelemede tamlık kapsamı açık yazılmalı.
- Kaynak: `core/evidence.py:191`, `contracts/evidence.py:40`.

### 4. P1 — Web yönlendirmesinde özel adres sınırı korunmuyor

- `fetch_url` sadece ilk hostu kontrol edip `allow_redirects=True` kullanıyor. `robots.txt` isteği de otomatik yönlendirmeli.
- Sahte taşıma ile public URL → `http://127.0.0.1:9999/private` son URL’si kabul edildi; `private_host` sadece ilk public host için çağrıldı. Gerçek bir özel servise istek gönderilmedi.
- Kaynağın ilk URL’si izinli olsa bile redirect hedefi tekrar doğrulanmalı; robots ve normal GET aynı sınırı kullanmalı. Veri ekibinin `src/lakehouse/generic/connector.py:246` yolu bunu zaten yapıyor (`allow_redirects=False`, her hopta doğrulama). İki katmanın aynı erişim sözleşmesine karşı ortak regresyon vakalarıyla denetlenmesi, tekrar güvenlik davranışı ayrışmasını önler.
- Kaynak: `agent-core/src/kkb_agent/web/fetch.py`, `web/session.py`.

### 5. P1 — Öncelik/gecikme analizi veri zamanını yeterince doğrulamıyor

- `max_lag` şemada 24’e kadar açık; 8 gözlem ve 24 gecikme `ValueError: operands could not be broadcast together` üretti. İlgili araç doğrulaması bu parametreyi kabul ediyor.
- Tarihleri sırasız, tekrarlı ve aralığı düzensiz 8 satır da `validate_refs` kontrolünden geçti. Yöntem gerçek takvim yerine satır sırasını dönem sayıyor.
- Öneri: seri uzunluğuna bağlı gecikme sınırı; sıralama/tekillik/frekans/boş dönem kontrolleri. Granger sonucu için dönüşüm, seçilen gecikme ve yöntem önkoşulları görünür olmalı. Bu raporda istatistiksel nedensellik iddiası değerlendirilmedi.
- Kaynak: `tools/analytics.py:250`, `analytics/methods.py` içindeki `cross_correlation`, `lead_lag`.

### 6. P1 — Toplu ingest, mevcut observability uygulamasını kullanmıyor

- Veri ekibinin `IngestionPipeline` ve CLI ingest yolu run/warning kaydına sahip. Fakat demo betiğinin çağırdığı `run_catalog_ingestion.py`, `_run_one` içinde doğrudan artifact register → parser → parquet yapıyor. Parser uyarıları yalnız yazdırılıyor; run repository kullanılmıyor.
- Silver `_run_context`, run kaydı bulamazsa `(None, [])` döndürüyor. Dolayısıyla kaynak uyarılarının Silver kalite işaretine taşınması bu yolda garanti değil.
- Bu turda eski demo DB’nin `meta.run=0` iddiası yeniden ölçülmedi; güncel üretim çağrı yolu koddan doğrulandı.
- Öneri: çok artifactli, kısmi tekrarları sürdürebilen ortak ingest primitive’i; run/artifact/warning kaydı aynı sınırda. Tek artifact tekrarının yeni artifactleri engellememesi gerekçesi korunmalı.
- Kaynak: genişlik dalı `lakehouse-core/scripts/run_catalog_ingestion.py`, `src/lakehouse/silver/build.py:_run_context`.

### 7. P2 — Katalog kapsamı ile analize hazır kapsam ayrılmalı

- YAML’lerden bu tur sayım: **2.214 seri**, **1.533 unknown + birimsiz**, **681 birim/ölçüm türü tanımlı**. Bu 681’in tümünün veri yüklü veya Gold’a uygun olduğu sonucu çıkarılamaz.
- Kaynak dağılımı: FinTürk 648 (81 il × 8 ölçüm), BDDK aylık 20, haftalık 1, EVDS 1.545. Verified 679, derived 1.535.
- EVDS frekansları: 1.067 aylık, 152 çeyreklik, 323 haftalık, 2 günlük, 1 iş günü. Hafızadaki 1.534 unknown / 233 çeyreklik sayıları güncel katalog sayımı değildir.
- `TP.FG.J0` derived kalıyor; yeni `TP.TUKFIY2025.GENEL` demo setinde. Baz değişimi/birleştirme için eski açık ile yeni seri birbirine karıştırılmamalı.
- Demo planı **127 seri**, yalnız **12 il**; 81 il haritası için sınır GeoJSON’u yok. Güncel demo DB’nin gerçekten 127 seri taşıdığı bu tur yeniden sayılmadı.
- Öneri: zorunlu jüri soruları → gereken seriler → semantik doğrulama → yüklü gözlem → Gold hazır matrisi.

### 8. P2 — Teslim ve ürün yüzeyi kararları açık

- UI tek süreçte global tek Session; bütün kullanıcılar aynı agent/history kullanır. Reload geçmişi RAM’den döndürür; sunucu restart’ında kalıcılık yok. Kimlik doğrulama/SSE/iptal ve dosya upload/export uçları yok. Bu, tek bilgisayarda demo için bilinçli kapsam olabilir.
- Soru kutusu dosya kabul ettiğini söylüyor ama native dosya seçici/yükleme yok; kullanıcı dosya yolunu vermeli ve dosya izinli kökte olmalı. İlk 200 satır JSON’a giriyor; tam tablo dışa aktarımı yok.
- `_json_safe(float("inf"))` JSON uyumlu hâle gelmiyor; katı JSON serileştirmesinde ValueError ölçüldü. NaN ele alınmış, sonsuzluk alınmamış.
- 21 branch ucunun hiçbirinde `.github/workflows/` yok. Lakehouse Makefile `build` yalnız dizin oluşturuyor, `demo-check` iki eski contract testi çalıştırıyor. Tam demo kabul komutu agent scripts altında ayrı.
- En son UI değişiklikleri sonrası bütün canlı golden vakalarının tekrarlı ortak raporu bu tur üretilmedi. Eski 11/11 kabul ve 330 birim testi farklı kanıt türleridir; birbirinin yerine geçmez.

## V3 dalından korunmaya değer katkılar

- İlk grounding ölçümleri, iki motor/two-schema benchmark koşucusu ve ham JSON çıktıları.
- Bütçeli markdown alan bilgisi ve `lookup_domain_note` yaklaşımı; salt-okunur araçları paralel çalıştırma ayrımı.
- Büyük katalog deneyleri ve başarısız sorgu alt-kümeleri; mevcut retrieval değerlendirmesine eklenebilir.
- V3’te ölçülerek eklenmiş `max_tokens=700` sınırı ayrıca değerlendirilmeli: güncel agent `_chat` çağrısı istemcinin `max_tokens` parametresini doldurmuyor. Süre/adım/çıktı bütçesi gereksinimi netleştirilmeli; bu tur canlı taşma veya gecikme ölçülmedi.
- Eski rapordaki “V3 daha hızlı/doğru” sonucu `a2deab6` dönemine ait; bugünkü `67cd6f9` ile güncel karşılaştırma değildir. Aynı şekilde o rapordaki “web/OCR/analitik yok” cümleleri bugünkü agent için geçerli değildir.
- Öneri: motoru bütünüyle değiştirme kararı öncesi güncel ortak vaka seti; araştırma/test katkılarını, üretim harness tercihinden ayrı koruma. Yazarlık ve katkı takibi açık tutulmalı.

## Kullanıcıyla netleştirilecek sorular

1. Resmî son değerlendirme ölçütleri ve zorunlu demo soruları neler? 20 Eylül dondurma hâlâ geçerli mi; video/sunum/kurulum dokümanı gibi ek teslim var mı?
2. Ana kullanım hikâyesi konut/kredi analizi mi, genel ekonomik araştırma mı, yoksa yeni alan/veri kabul edebilen Architect mi? Hangisi demo merkezinde?
3. Birincil kullanıcı kim ve hangi kararı vermek için kullanacak? Ekonomist, banka analisti, veri mühendisi veya jüri için beklenen çıktı nasıl farklılaşıyor?
4. Büşra ile tek motor/iş bölümü kararı verildi mi? Hangi arkadaş hangi açık işi şu anda üstleniyor; push edilmemiş çalışma var mı?
5. Kanonik veri ucu olarak catalog-breadth kabul ediliyor mu? Güncel çalışan demo DB ve başlatma komutu nerede; root .env dışında terminal override’ları kullanılıyor mu?
6. Jüri hangi ortamda çalıştıracak: aynı laptop, temiz Windows/Linux kurulum veya paylaşılan sunucu? Aynı anda kaç kullanıcı gerekiyor?
7. Asgari veri kapsamı hangi kurum/seri/tarih/iller? 12 il yeterli mi, 81 il zorunlu mu; 1.533 keşif serisinin hangileri gerçekten kullanılacak?
8. Yeni dosyayı kim onaylayacak; draft→aktif ve derived Gold onayı ayrı adımlar olarak kalmalı mı? Birim/semantik sorularına son kullanıcı cevap verebilir mi?
9. “Kanıt tam” iddianızın kabul ölçütü ne: değer eşleşmesi, doğru dönem/birim/varlık, diskten doğrulanabilir RAW ve yeniden üretilebilir hesap mı? Yanlış iddiada cevabı bloke etmek mi, uyarılı sunmak mı isteniyor?
10. Belirsiz soruda agent hangi alanları mutlaka sormalı (dönem, kaynak, frekans, kredi türü); hangi varsayımları açıkça yapabilir?
11. Web için yalnız statik/açık kaynak yeterli mi? JS sayfaları, erişim engeli ve internet/model kesintisinde jüriye hangi akış gösterilecek?
12. PDF/Excel yerel dosya yükleme ve tam tablo/grafik/rapor indirme zorunlu mu; tercih edilen çıktı formatları neler?
13. Kabul edilebilir cevap süresi, MIA/Tavily bütçesi ve tekrarlı başarı eşiği nedir? Anomali/kırılma/Granger açıklayıcı demo aracı mı, yöntemsel önkoşulları doğrulanmış analitik ürün mü olacak?
14. Son mentör görüşmesinde belgeleri geçersiz kılan karar var mı? Teslime kalan iş için öncelik ve ekip kapasitesi nedir?

## Önerilen tartışma sırası — henüz alınmış karar değil

1. Hedef demo ve kanonik çalıştırma düzeni.
2. Güven doğrulaması / redirect sınırı / analitik veri kontrolleri.
3. Toplu ingestion provenance ve gerekli serilerin semantik hazır oluşu.
4. V3 katkılarının ortak ölçüme alınması ve iş bölümü.
5. Kullanıcı akışı, dosya giriş-çıkışı, gecikme ve temiz kurulum kabulü.
6. Son bütünleşik ölçüm, güncel teslim belgeleri, ardından birleştirme planı.
