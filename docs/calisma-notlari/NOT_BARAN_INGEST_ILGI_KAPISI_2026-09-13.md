# Baran'a not — `ingest_from_url`'a ilgi kapısı (13 Eylül, Büşra)

**Ne yaptım.** Senin dalını (`ab87563`) bizim dala merge ettim; dosyalarına dokunmama kuralını
Büşra'nın kararıyla yalnız **bu iş için** ve yalnız `tools/ingest.py` için esnettik. Değişiklik
küçük ve geri alınabilir; asıl mantık yeni bir dosyada.

**Neden.** ADR-0030'un profilcisi dosyanın *biçimine* bakıyor (tarih %100 ayrışıyor mu, sayı
%100 okunuyor mu, birim başlıkta var mı), *anlamına* bakmıyor. Jüri "2024 konut kredisi"
sorusuna yanlış Excel verirse — içinde tarih ve sayı olduğu sürece — taslak olarak yazılıyordu.
Kart bunu gösteriyor ama kullanıcı doğru dosya sanıyorsa fark etmez. Bizim V3 §3.9 tasarımı
(ARCHITECTURE_V3.md) bu boşluğu kapatıyor; mentörün "kontrollü geri çekilme, sessiz iş yok"
çizgisiyle aynı.

**Dosyalar.**
- **Yeni** `src/kkb_agent/builder/relevance.py` — saf fonksiyon, LLM/ağ yok. Üç ölçüt:
  1. *dönem*: soruda yıl varsa dosyanın tarih aralığı (öneri biçimiyle okunur) o yılı kapsıyor mu;
  2. *terim*: sorunun içerik sözcükleri (durak sözcükler atılmış, kök = ilk 5 harf; "kredisi/kredileri" → "kredi")
     dosya adında ya da kolon başlıklarında geçiyor mu;
  3. *katalog*: soru bir katalog serisine ad/alias ile işaret ediyorsa o serinin sözcükleri dosyada da var mı
     ("enflasyon" ↔ "TÜFE" alias'ı).
  Yalnız **uygulanabilen** ölçütler sayılır; hiçbiri tutmuyorsa `irrelevant`. "Bunu ekle" gibi
  içerik sözcüğü olmayan istekte kapı sessizdir.
- **Değişen** `src/kkb_agent/tools/ingest.py` — 3 dokunuş:
  - import satırı;
  - `IngestParams.user_confirmed: bool = False` (kullanıcı "yine de ekle / doğru dosya bu" dediyse; senin
    `undeclared` kuralınla aynı mantık: modelin bayrağı **yalnız** kullanıcı metninde onay sözü varsa geçer);
  - `run()` adım 2b: öneri çıktıktan sonra, doğrulamadan önce `assess(...)`; alakasızsa
    `ToolResult.fail("FILE_IRRELEVANT", layer="policy", retryable=False, candidates=[öbür dosyalar])`,
    CLI hiç çağrılmaz, okuyucu kapanmaz. Kart sonuna `ilgi puanı: k/n` satırı, yıl kapsamıyorsa ⚠,
    aynı oturumda bakılan daha uygun dosya varsa `NOT:` satırı; `artifacts["relevance"]` kanıt paneli için.
    `existing` listesi artık aynı `list_datasets()` çağrısından (ikinci çağrı yok).
- **Yeni** `tests/test_ingest_relevance.py` — 10 test: kökleme, ilgili/alakasız/yıl uyuşmazlığı,
  alias kurtarışı, kapı sessizliği, araç içinde yazmama + sorma, model bayrağı yetmez, iki dosyada
  kart notu. Dosya okuma sahte DataFrame ile yamalı (Windows'ta `read.py` sürücü harfini şema
  sanıyor — bkz. aşağıdaki 2. madde).

**Senden istediklerim (senin dosyaların, ben dokunmadım).**
1. `core/errors.py`: `ErrorCode` Literal'ına `"FILE_IRRELEVANT"` ekle ve `NOT_RETRYABLE`'a koy
   (aynı dosyayı tekrar istemek sonucu değiştirmez; onay ayrı çağrıdır). Kod bugün string olarak
   çalışıyor, tip denetimi ve hata sayımı için listede olmalı.
2. `builder/read.py:108`: Windows'ta `urlparse("C:\\…").scheme == "c"` → `ReadRefused("desteklenmeyen şema: c")`.
   Tek harfli şemayı sürücü harfi say (`len(parsed.scheme) == 1`) ya da `Path(locator).exists()`'i önce dene.
   Bende 23 testin düşme sebebi bu + `fastapi`/`pypdfium2` kurulu olmaması.
3. Kanıt paneli (ADR-0033): `artifacts["relevance"]`'ı "danışıldı, kullanılmadı" satırına bağlayabilirsin;
   `RelevanceReport.lines()` hazır metin veriyor.
4. Golden'a dört vaka önerisi (§3.9): G12a alakasız dosya (yazılmaz, sorar), G12b doğru + yanlış dosya
   (doğru olan eklenir, kart öbürünü söyler), G12c yıl uyuşmazlığı (⚠ + sorguda `OUT_OF_COVERAGE`),
   G12d bozuk dosya (mevcut `ReadRefused` yolu). Fikstürler yerel, ağ yok.

**Kökleme kaba;** "fiyat" ≠ "kredi" gibi anlamsal ayrımı yalnız alias yakalar — bu kasıtlı, LLM'e
sormadan yapılabilecek kadarı bu.

---

## Ek (14 Eylül) — çapraz kontrol ve birim tahmini

Büşra'nın iki sorusu: (1) gelen veri katalogda da varsa karşılaştırıp doğrulayamaz mıyız,
(2) belgede birim yazmıyorsa "birim nedir?" diye boş soru sormak eksik tasarım değil mi?
İkisi de yazıldı; ikisi de **engellemez, uyarır/önerir**; ikisi de LLM'siz.

**Yeni** `builder/crosscheck.py` — `cross_check(lakehouse, specs, candidate_ids, frame, mapping, semantics)`:
- Yalnız ilgi kapısının bulduğu **tek** katalog adayı varsa ve frekans aynıysa çalışır; aksi hâlde
  "karşılaştırılamadı: <sebep>" (birden çok aday / frekans farklı / seri boş). Yanlış alarm vermemek
  için bilerek dar: haftalık↔aylık, bin↔milyon, takipteki↔toplam hepsi "çelişki" gibi görünürdü.
- Adaptörün `series_sql` + `execute_sql`'i ile katalog serisi okunur (salt okunur, tek sorgu, ms).
  Dönemler ay/çeyrek/yıl anahtarıyla eşlenir; medyan oran ve ona en yakın 10^k ölçek bulunur;
  noktaların %1 içinde kalan payı ölçülür. Üç sonuç: **örtüşüyor** (oran ≈ 1, ≥ %80 nokta),
  **birim farkı** (×1000 gibi ölçekle örtüşüyor), **ÇELİŞİYOR** (ölçekten sonra bile dağınık; en büyük
  3 sapma tarih-değer-değer olarak yazılır).
- Karta `çapraz kontrol (...)` satırı, `artifacts["crosscheck"]`. Cevapta "doğrulandı" DEĞİL
  "örtüşüyor" denir: iki kaynağın aynı sayıyı vermesi doğruluk kanıtı değildir.
- İnternet üzerinden çapraz kontrol **yazılmadı**, bilerek: soru başına 3–5 s ve belirsiz sonuç.
  Yeri, kullanıcı "doğrula" dediğinde ya da kanıt paneline sonradan düşen bir satır (D fazı adayı).

**Yeni** `builder/unit_guess.py` — `guess_unit(texts=…, crosscheck=…, values=…)`:
- Sıra: **metin** (kolon adları + dosya adı + belge notu: "bin TL", "milyar", "%", "kg", "adet", "USD";
  senin `_UNIT_HINTS`'in genişletilmişi, kod değil etiket döner) → **katalog ölçeği** (çapraz kontrol
  "milyon TL" serisiyle ×1000 örtüşüyorsa dosya "milyar TL"; TL merdiveni bin→milyon→milyar) →
  **değer aralığı** (0–100 ondalıklı → yüzde; küçük tam sayılar → adet; ikisi de zayıf).
- Yazmaz. `semantics.unit is None` olduğunda "EKLENMEDİ — sorulmalı" bloğuna
  `birim TAHMİNİ: 'milyon TL' [weak] — sebep` satırı ve modele "kullanıcıya 'bu birim doğru mu?' diye sor;
  onaylarsa `unit=` ile çağır" talimatı girer. Beyan kuralın aynen geçerli: kullanıcı söylemeden yazılmaz.

**Değişen** `tools/ingest.py` (+~25 satır): ilgi kapısından sonra `cross_check`; birim yoksa `guess_unit`;
kart ve artifacts. Testler: `tests/test_ingest_crosscheck.py` (compare ölçek/çelişki/örtüşme, tahmin
üç kaynak, araç içinde kart satırları; sahte lakehouse `series_sql`/`execute_sql`).

**Senden:** kanıt paneline `artifacts["crosscheck"]` satırı; istersen `promote_draft` onay kartına da aynı
satır (insan onaylarken çelişkiyi görsün — asıl güvenlik orada).
