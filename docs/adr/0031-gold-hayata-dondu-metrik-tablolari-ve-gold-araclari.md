# ADR-0031: Gold hayata döndü — kataloglanmış metrik tabloları, `gold-run` sınırı ve `gold_*` araçları

**Durum:** Kabul edildi (B3) · **Tarih:** 2026-09-12 · **Sıradaki:** C1 grafik + denetçi

## Bağlam
Veri ekibinin Gold sözleşmesi netti: Gold **fonksiyondur**, tablo değil. `align_frequency /
decompose_cumulative / join_on_period` kuralı `meta.series`'ten okur, güvensizse sebebiyle
reddeder, salt-okunur bağlantıda çalışır. Üçü de gerçek veride doğrulanmıştı. Eksik olan
iki şeydi:

1. **Agent onlara ulaşamıyordu.** Agent `lakehouse-core`'u import etmez (ADR-0024); fonksiyon
   paketin içinde, agent dışarıda. "Çeyreklik göster" dendiğinde model SQL'de `AVG(value)`
   yazıyor, stoku ortalıyordu — doğru kural yazılıydı ama erişilemezdi.
2. **Hazır bir Gold yüzeyi yoktu.** Sözleşme "materyalizasyon fonksiyonlar güvenilir olunca"
   diyordu. Demo için jürinin gözünde "Gold katmanı nerede?" sorusunun cevabı bir tablo
   olmalı; ama tablo yapılırsa sözleşmenin üç kuralı (katalog karar verir, fail-closed,
   salt-okunur) korunmalı.

Kullanıcıyla karar (yol haritası B3): komut + adaptörde görünürlük + araçlar **tek paket**;
"tablo yalnız diskte durursa demoda hiçbir şey değişmez".

## Karar 1 — Tablo, kataloglanmış bir fonksiyon çağrısının önbelleğidir (veri ekibi tarafı)
`catalog/gold/*.yml` — seri kataloğu gibi insan yazımlı, Git'te incelenen metrik kataloğu.
Bir kayıt **hangi** fonksiyon, **hangi** seriler, **hangi** hedef dönem der; **nasıl**
birleşeceğini diyemez — fonksiyon kurulum anında yine `meta.series`'i okur.
`python -m lakehouse gold` her metriği güncel Silver'dan tek işlemde kurar:

- **Red kaydedilir, örtbas edilmez.** Fonksiyon reddederse kurulum devam eder, metriğin
  `meta.gold_build` satırı `refused` + sebep olur, önceki kurulumdan kalan tablo **düşürülür**.
  Hâlâ cevap veren bayat tablo, olmayan tablodan kötüdür.
- **Her satır kurulumunu taşır.** Fonksiyonun verdiği satır provenance'ına
  (`artifact_sha256_list`, `source_observation_dates`) ek: `gold_build_id`, `gold_built_at`,
  `gold_catalog_content_sha256`, `silver_fingerprint`.
- **Bayatlık ölçülür, varsayılmaz.** `silver_fingerprint` = her Silver gözlemi üzerinden
  sıralı md5. `silver` yeniden kurulunca değişir; tabloya yazılı olanla canlı olan farklıysa
  tablo bayattır. Zaman damgasına güvenilmez.
- Katalogdan çıkan metriğin tablosu düşer; **komutun kurmadığı tabloya dokunulmaz**.
- Tipler beyan edilir: `value` DOUBLE (tümü NULL olsa da), dönemler DATE, sayımlar INTEGER,
  `source_observation_dates` DATE[], öbür listeler VARCHAR[]. Pandas'ın örneklemle
  çıkarsadığı tip kurulumdan kuruluma değişebilirdi.

`allow_unverified_semantics: true` yalnız `unverified_reason` ile: sözleşmenin insandan
istediği onay yazılı olmak zorunda.

## Karar 2 — Tek çağrı, salt-okunur, süreç sınırından: `gold-run`
`python -m lakehouse gold-run --function … --series … --target … --out x.json` sertleştirilmiş
salt-okunur profille (`connect_untrusted`) **bir** fonksiyonu çalıştırır, sonucu JSON
belgesi olarak yazar (tarih ISO, liste dizi, eksik `null`). Red bir sonuçtur: `status:
refused` + `reason` + `message`, çıkış **3** (2 = hata).

Neden import değil, alt süreç: ingest ile aynı sınır (ADR-0030). Fark: yazma yok, dolayısıyla
`kapat → yaz → yeniden aç` yok — DuckDB birden çok salt-okunur süreci aynı anda kabul
ediyor; Analist'in okuyucusu açıkken `gold-run` yan yana çalışıyor. Ölçüldü: gerçek alt
süreç çağrısı **0,3 s**. Neden JSON, Parquet değil: agent ortamında Arrow yok ve Gold
çerçeveleri küçük — gözlem değil, dönem.

## Karar 3 — Adaptörde `gold.*` dataset, üç `gold_*` aracı, kural prompt'ta (agent tarafı)
- **`GoldCapable` sözleşmesi** (`contracts/lakehouse.py`): `gold_align / gold_decompose /
  gold_join → QueryResult`, red `GoldRefused(reason, series_id)`. `LakehouseClient`'tan ayrı:
  seed adaptörü sunmaz, sunmayınca araçlar kayıt edilmez ve Gold kuralı prompt'a girmez
  (olmayan aracı öğütlemek UNKNOWN_TOOL üretir).
- **Adaptör defteri okur, tabloyu değil.** `meta.gold_build`'de güncel ve `built` olan her
  metrik bir `DatasetSpec`: kimliği gerçek tablo adı (`gold.konut_kredisi_ceyreklik`) —
  arama ipucu gerekmez, `FROM`'a yazılır. Kolonlar `DESCRIBE`'dan, birim/ölçüm tipi/kural
  serilerin `meta.series` satırından; join kolonları `<seri>@<varlık>::value`. Not satırı:
  "GOLD TABLOSU (align_frequency): … Kural katalogdan — stok → dönemin son gözlemi (last).
  Yeniden toplama/ortalama alma." Defterde `refused` olan ya da diskte olmayan tablo
  listelenmez; defterde olmayan `gold.*` tablosu da listelenmez — kim kurduğu belli olmayan
  tablo modele gösterilmez. Canlı parmak izi farklıysa `⚠ BAYAT` notu ve sorgu uyarısı.
- **Üç araç** (`tools/gold.py`), roller `execute`: referans kontrolü sınır doğrulayıcıda
  (olmayan/yüklenmemiş seri CLI çağrılmadan durur; `gold.` kimliği "bu zaten tablo,
  lakehouse_query ile sorgula"), dönem filtresi deterministik (`period_from/to`: YYYY,
  YYYY-AA, YYYY-AA-GG), dönem dışıysa tablo kurulmaz ve kapsam söylenir. Sonuç aktif analiz
  tablosu: kanıt kolonları (`source_observation_dates`, `artifact_sha256_list`) kalır,
  kurulum/iç alanlar düşer. Red → `GOLD_REFUSED` (politika katmanı, **tekrar denenmez**),
  Türkçe sebep + alternatif ("gold_align ile indirge", "ham hâlini lakehouse_query ile göster").
- **`allow_unverified_semantics` modele açılmadı.** Sözleşme: "insanın 'evet' demesi, agent
  aktarır". Modelin kendi inisiyatifiyle çevireceği bir düğme olamaz; kullanıcı onayı için
  ayrı bir kanal (`clarify`, D-stretch) gerekir. Şimdilik red kullanıcıya gider.

## Ölçüm
- **Veri ekibi tarafı:** demo veritabanında 3 metrik kuruldu (`konut_kredisi_ceyreklik` 22
  çeyrek; `konut_kredisi_aylik_vs_haftalik` 66 ay, dış birleşim; `konut_faizi_aylik` 67 ay,
  avg). 2025 Q4 = 678.970 milyon TL — G1'in BDDK'dan doğrulanmış değeriyle aynı. Stok seriye
  `decompose` → NOT_DECOMPOSABLE; taslak seriye `align` → INACTIVE_SERIES (hiçbir override
  gevşetmez). Testler 1050 → 1083 (katalog doğrulama ×10, kurulum+provenance, red+bayat
  düşürme, idempotent yeniden kurulum, parmak izi, yetim tablo, sentetik join, serileştirme,
  CLI `gold`/`gold-run`).
- **Agent tarafı:** birim testleri 155 → 174 (araçlar ×15 sahte CLI ile, adaptör ×4:
  defterden görünürlük, BAYAT, deftersiz DB, CLI'sız çağrı). Gerçek alt süreçle uçtan uca:
  align 0,3 s, join 0,3 s, red 0,3 s.
- **Golden G9** (iki turlu, gerçek DB, MIA): "2025 çeyreklik göster" → model hazır Gold
  tablosunu buldu (arama → describe → SQL `FROM gold.konut_kredisi_ceyreklik`), 4 satır, Q4
  678.970. İkinci tur "bu seriyi birikimli kabul edip akımlara ayrıştır" (yanlış öncül) →
  `gold_decompose` NOT_DECOMPOSABLE, cevap: "konut kredisi bakiyesi birikimli bir seri
  değil … stok". **Golden'ın ilk sürümü 0/3 kaldı** — `gold_align` şart koşuyordu; oysa
  hazır tabloyu sorgulamak da Gold'dur ve daha ucuzdur. Golden şemasına `tool_path_checks`
  eklendi (adım listesi üzerinde denetim); G9 iki meşru yolu da kabul eder.
  **Sonuç: G9 3/3 kararlı, 5 adım, ort. 9 s** (arama → describe → SQL → arama →
  `gold_decompose` reddi). Seed regresyonu G1–G7 **7/7**, 0 anlatı hatası (değişmedi).
  Gerçek demo DB'de tüm set 7/9: G5 ve G6 düştü, sebebi Gold değil kapsam — demo DB'de
  ihtiyaç/taşıt kredisi serisi yok, model on kez arama yapıp adım bütçesini yaktı. Bu ayrı
  bir bulgu: arama boş dönünce "katalogda var, yüklenmemiş" bilgisini vermiyor (ADR-0026'nın
  `get_dataset` tarafı var, `search` tarafı yok) — D3'e not.

## Sonuç
Gold sözleşmesinin üç kuralı tabloda da yaşıyor: katalog karar verir (metrik kataloğu
kuralı seçemez), fail-closed (red defterde, tablo düşer), salt-okunur (`gold-run`). Jürinin
"Gold nerede?" sorusunun cevabı: `SELECT * FROM gold.konut_kredisi_ceyreklik` — her satırda
hangi Silver'dan, hangi RAW'dan, hangi kurulumla.

## Açık kalan
- `python -m lakehouse gold` bir operatör komutu; Architect'in registry'sine (`build_gold`)
  alınması ve `silver`'dan sonra otomatik tetiklenmesi (B2'nin `kapat → yaz → yeniden aç`
  yoluyla) yapılmadı. Bayatlık görünür olduğu için acil değil.
- Çözümlenmiş (decompose) serinin çeyreğe indirgenmesi sözleşmede yok (V1); araç da yok.
- Kullanıcı onayı kanalı (`allow_unverified_semantics`) — D-stretch `clarify`.

## İlgili
ADR-0024 (sözleşme sınırı), ADR-0026 (kataloglu ≠ sorgulanabilir), ADR-0029 (doğrulayıcı),
ADR-0030 (ingest, aynı alt süreç sınırı). Veri ekibi: `docs/gold-contract.md` §9,
`catalog/gold/`, `sql/bootstrap/030_gold_build.sql`, `lakehouse/gold/{catalog,build,serialize}.py`.
