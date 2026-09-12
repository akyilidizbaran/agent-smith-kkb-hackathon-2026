# ADR-0030: Architect rolü — LLM'siz profilci + doğrulayıcı ve tek kapı `ingest_from_url`

**Durum:** Kabul edildi (B1 + B2) · **Tarih:** 2026-09-12 · **Sıradaki:** B3 — `build_silver` / `build_gold` Architect'in registry'sine

## Bağlam
Demo senaryosunun 2. sorusu: jüri yeni veri getirir, agent ingest eder **ve belgeler**.
Bugün ingest yolu var (`python -m lakehouse ingest-file`) ama operatörden 15 alan istiyor:
7 eşleme alanı (`AdhocObservationMapping`: tarih/değer/entity kolonu, tarih biçimi,
ayraçlar) ve 8 anlam alanı (`_adhoc_record`: ad, açıklama, frekans, birim, ölçüm tipi…).
Jüri elinde CSV ile geldiğinde o alanları kimse dolduramaz.

Veri ekibinin sözleşmesi bunun için yazılmış: `register_series` yalnız
`derived / profiler / draft` yazabiliyor ve draft seriyi Gold kullanamıyor. Yani "makine
önerir, insan onaylar" ayrımı politika değil, kod. Eksik olan makine tarafı.

Tek harness, iki rol kararı (yol haritası): Analist okur, Architect yazar. Architect'in
çekirdeği LLM olmak zorunda değil — ve olmamalı. Bir kolonun tarih olup olmadığı bir
yorum değil, bir ölçümdür.

## Karar (B1)
`kkb_agent/builder/` — iki modül, sıfır LLM, sıfır ağ, `lakehouse-core` import'u yok.

**Profilci** (`profile.py`): generic parser'ın verdiği **metin** tablosunu kolon kolon ölçer.
"Hangi tarih biçimleri satırların %100'ünü ayrıştırıyor", "hangi (ondalık, binlik) çifti
%100 ayrıştırıyor", tekillik, monotonluk, kardinalite. Sonra **önerir** — her alanın
yanında gerekçe ve güven (`strong / weak / none`):

| alan | kanıt |
|---|---|
| tarih kolonu / biçimi | %100 ayrıştıran biçim; tekil ve artan sırada mı |
| değer kolonu / ayraçlar | %100 ayrıştıran tek ayraç çifti; birden çok sayısal kolon varsa alternatifler listelenir |
| entity kolonu | tam bir tane az-kardinaliteli metin kolonu varsa; tek değerli olan sabittir, boyut değil |
| frekans | ardışık tarih farklarının medyanı (28–31 → aylık, 5–9 → haftalık, …) |
| ölçüm tipi | başlık ve seyirden: endeks/oran/adet için zayıf kanıt; tek yönlü negatifsiz seyir → `stock` (zayıf); aksi hâlde **`unknown`** |
| birim | yalnız başlıktan (`milyon TL`, `%`, `endeks`); veriden çıkarılamaz → `None` |

**Belirsizlikte tahmin yok.** `01/02/2026` hem 1 Şubat hem 2 Ocak'tır; iki biçim de
%100 geçer. Öneri bu alanı `confidence=none` ile işaretler, doğrulayıcı yayınlamayı
durdurur, cevap "kullanıcıya sorulmalı" olur. İnişli çıkışlı bir seri stok mu akım mı
veriden bilinemez → `measure_type: unknown`. Bu dürüst bir kayıt: `unknown` Silver'a
giremez, Gold'a giremez; sahte bir `stock` girer ve yanlış toplanır.

**Doğrulayıcı** (`verify.py`): öneriyi aynı veriye karşı, **yayınlama katmanının kendi
kurallarıyla** sınar. Sayı dilbilgisi `lakehouse.adhoc.publication._parse_value`'nun
birebir kopyası (yorumda işaretli): burada geçen orada da geçer. Yedi kontrol: `adhoc:`
alanı, series_id çakışması, kolonların varlığı, tarihlerin beyan edilen biçimle %100'ü,
değerlerin beyan edilen ayraçlarla %100'ü (boş hücre NULL kalır, 0 olmaz), **hiçbir satırın
sessizce düşmemesi**, aynı (tarih, entity)'nin bir kez geçmesi (yayınlamada revizyon
çatışması olur), belirsiz alan olmaması. Kalan kontrol raporu düşürür; hiçbir şey
onarılmaz.

## Neden bu sıra: önce ölçüm, sonra model
Architect'in LLM'e bırakacağı tek iş, *alternatifler arasında seçmek ve kullanıcıya
sormak*: üç sayısal kolondan hangisi, iki entity adayından hangisi, belirsiz tarih
biçiminde hangisi. Kolonun tarih olup olmadığını modele sormak, 187 satırın 187'sinde
ayrışıp ayrışmadığını ölçmekten daha az güvenilir ve daha pahalı.

## Ölçüm
13 test, hepsi sentetik ve gerçekçi: ISO ve Türkçe yazım (`31.01.2025`, `1.234,5`),
boş hücre, belirsiz gün/ay, çoklu sayısal kolon, entity boyutu vs sabit, tarihsiz tablo,
kanıtsız ölçüm tipi, bozuk satırın sessiz düşmemesi, tekrarlı tarih, alan/çakışma.
Agent birim testleri: 130 → 143.

## Karar (B2) — Analist'ten Architect'e tek kapı: `ingest_from_url`

**Yazma, sözleşme sınırının öbür tarafında kalır.** Agent `lakehouse-core`'u import etmez;
ingest'i veri ekibinin operatör yüzeyi olan `python -m lakehouse ingest-file` ile, ayrı bir
süreçte ister (`builder/ingest.py`, `LakehouseCLI`). Aynı sertleştirilmiş connector, aynı
parser, aynı draft sözleşmesi, aynı provenance; biz 15 alanı doldurup çıktının
`anahtar: değer` satırlarını okuruz. Mentörün jüri sorusu ("yarın REST API / DB / stream
verirsek?") burada da aynı cevabı alır: yeni kaynak türü onların tarafında bir connector,
bu dosya değişmez.

**Akış deterministik, LLM yok** (`tools/ingest.py`):

```
erişim (ADR-0028) → danışma okuması → profil → öneri (kanıtla) → doğrulama (yayınlama kuralları)
  → belirsizse KULLANICIYA SOR, yazma          ← CLI hiç çağrılmaz
  → okuyucuyu kapat → CLI draft'a yazar → okuyucuyu yeniden aç
  → belge kartı (run_id, artifact_sha256, bronze yolu, eşleme, kanıt, uyarılar)
```

- **Kapat → yaz → yeniden aç** tasarım detayı değil, fizik: DuckDB tek yazar kabul ediyor
  (ölçüldü: Analist'in okuyucusu açıkken aynı süreçten de başka süreçten de yazar
  açılamıyor). `LakehouseClient` sözleşmesine `close()` / `reload()` eklendi; `reload`
  aynı sertleştirmeyle yeniden açar ve kataloğu yeniden okur.
- **Yazma yeteneği Analist'te yok.** Bağlantı salt-okunur kalır; yazan ayrı süreçteki CLI'dır
  ve o da yalnız `adhoc` + `draft` yazabilir. Curated Silver'a bu yoldan girilemez.
- **Danışma okuması** (`builder/read.py`) kalıcı hiçbir şey yazmaz; yerel dosya yalnız
  izinli kökten (`INGEST_ALLOWED_ROOT`), URL yalnız http(s), özel IP yok, boyut sınırı;
  erişim sonucu ADR-0028 zarfıyla. Kaynağın gerçek çekilişi ve Bronze'a yazılışı CLI'da.
- **Birim yoksa yazılmaz.** Veriden çıkarılamaz; kaynak belgesi ya da kullanıcı söyler.
  `measure_type: unknown` ise yazılır ve kartta söylenir — dürüst kayıt.
- **Aynı dosya ikinci kez:** çakışma kontrolü yalnız küratörlü/başka kaynaklı serilerle;
  kendi taslağına düşen yeniden ingest'i veri ekibinin yayınlama kuralı çözer
  (aynı satır "değişmeyen", aynı tarihe farklı değer revizyon çatışması). Ölçüldü:
  `yazılan 0, değişmeyen 6`, gözlem sayısı artmadı.

**Taslak seri Analist'e görünür.** İlk uçtan uca koşuda ingest başarılıydı ama adaptör
"yeni: []" gösteriyordu — gözlemler `adhoc.fact_observation`'da, adaptör yalnız Silver'ı
sayıyordu. Adaptör artık iki ilişkiyi de sayar; `source_id='adhoc'` olan seri adhoc
ilişkisinden sorgulanır (`series_sql`, `preview`, fiziksel sorgu notu), notunda **TASLAK**
yazar ("bir insan onaylamadı; Gold hesapları uygulanmaz; cevapta taslak olduğunu söyle").
`health()` `draft_series` ve `adhoc_observations` sayar. Adhoc şeması olmayan
veritabanı (seed/test) yine yüklenir.

## Ölçüm (B2)
Gerçek uçtan uca, gerçek CLI alt süreci, gerçek DuckDB: Türkçe yazımlı CSV
(`31.01.2025;1.234,5`) → eşleme `%d.%m.%Y`, ondalık `,`, binlik `.`, birim `TRY_mn`
başlıktan, frekans `monthly` (medyan 30 gün), ölçüm `stock` (zayıf, kartta söylendi) →
`meta.series` satırı `derived / profiler / draft`, `adhoc.fact_observation` 6 satır,
`run_id` ve `artifact_sha256` kartta → reload sonrası Analist 6 sorgulanabilir seri görüyor,
`1.234,5` → `1234.50` doğru. Birim testleri 143 → 152; golden'a G8 (ingest + sorgu, iki turlu).

## Açık kalan
Alternatifler arasında seçim (üç sayısal kolondan hangisi, belirsiz tarih biçimi) bugün
kullanıcıya soruluyor; Architect'in LLM'li alt-agent hâli o seçimi konuşarak yapacak.
`build_silver` / `build_gold` komutları (B3) Architect'in registry'sine gelecek.

## İlgili
ADR-0026 (kataloglu ≠ sorgulanabilir), ADR-0028 (erişim sözleşmesi), ADR-0029 (doğrulayıcı).
Veri ekibi: `catalog/registration.py` (draft sözleşmesi), `adhoc/publication.py`.
