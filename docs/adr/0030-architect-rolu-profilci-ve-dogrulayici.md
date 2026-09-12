# ADR-0030: Architect rolü — önce LLM'siz profilci ve doğrulayıcı

**Durum:** Kabul edildi (B1 kısmı) · **Tarih:** 2026-09-12 · **Sıradaki:** B2 alt-agent sarmalayıcısı bu ADR'yi genişletir

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

## Sırada (B2)
Architect'in sarmalayıcısı: ayrı registry (`fetch · profile · propose · verify ·
register_draft · build_silver · build_gold`), yazar bağlantı, `kapat → yaz → yeniden aç`,
Analist'te tek araç `ingest_from_url`. Erişim sonuçları ADR-0028 sözleşmesiyle döner.

## İlgili
ADR-0026 (kataloglu ≠ sorgulanabilir), ADR-0028 (erişim sözleşmesi), ADR-0029 (doğrulayıcı).
Veri ekibi: `catalog/registration.py` (draft sözleşmesi), `adhoc/publication.py`.
