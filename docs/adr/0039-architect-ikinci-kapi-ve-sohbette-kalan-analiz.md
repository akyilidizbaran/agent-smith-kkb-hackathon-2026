# ADR-0039: Architect'in ikinci kapısı ve sohbette kalan analiz — iki uçtan uca deney

**Durum:** Kabul edildi · **Tarih:** 2026-09-12 · **Sıradaki:** E kapanış (kullanıcı onayıyla)

## Bağlam
D4'e kadar "Architect" tek kapıydı: `ingest_from_url` dosyayı **taslak** seri olarak yazar
(ADR-0030), taslak sorgulanabilir ama Gold'a giremez, semantik `derived`. Taslağı kataloğa alan
insan adımı yalnız veri ekibinin YAML'ıydı; sohbetteki kullanıcının "onaylıyorum" demesinin bir
karşılığı yoktu. Analist tarafında da eksik vardı: `web_url` ile yüklenen tabloyu veri
havuzuna yazmadan filtrelemenin/toplamanın yolu yoktu (yalnız `compute_column`).

İki deney istendi, ikisi de finans dışı veriyle ve yalnız agent üzerinden:
1. **Architect:** bir veri seti Bronze → Silver → Gold katmanlarından geçsin, her katman
   doğrulansın.
2. **Analist:** başka bir veri seti yalnız sohbette kalsın, veritabanına **hiç** yazılmasın,
   gerekli çıktılar (tablo, hesap, grafik, kanıt) alınabilsin.

## Karar

### Architect'in ikinci kapısı: terfi
- Veri ekibi tarafı (`feature/lakehouse-integration-r3` `46b9c8b`): `catalog/promotion.py`
  `promote_draft_series` — yalnız `adhoc` + `draft`; tek işlemde `status → active`,
  `semantic_source → manual`, `semantic_confidence` **derived kalır** (onay doğrulama değildir);
  satırlar `adhoc.fact_observation` → `silver.fact_observation`, provenance dokunulmadan,
  tekrarlanabilir. Silver yeniden kurulurken aktif ad-hoc seriler her yolda eklenir
  (`_append_promoted_adhoc`; ölçüldü: Bronze boşken terfi edilmiş satırlar düşüyordu). CLI
  `promote-draft --series`. Taze veritabanında Silver yoksa oluşturulur.
- Agent tarafı: `promote_draft` aracı. Niyet kapısı (ADR-0037'nin devamı): kullanıcı metninde
  onay ifadesi ("onaylıyorum", "kataloğa al", "yayınla") **ve** seri anahtarı geçmeli; yalnız
  `adhoc` + TASLAK notlu seri; yazma ayrı süreçte veri ekibinin komutuyla, okuyucu kapat →
  yaz → yeniden aç (ADR-0024 aynen).

### Beyan edilen anlam, uydurulan değil
`ingest_from_url` `unit / measure_type / default_agg / frequency` alır. **Ölçüldü:** ilk
koşuda model kullanıcı hiçbir şey söylememişken `°C` ve `stock` uydurup yazdı. `undeclared()`
kapısı: kullanıcı metninde birebir geçmeyen birim ve anahtar sözcüğü geçmeyen ölçüm tipi/kural
yok sayılır, araç "EKLENMEDİ … beyan kullanıcıdan gelmeli" der ve sorar. Kullanıcı söyleyince
öneri beyanla dolar, her alan "kullanıcı beyanı" kanıt satırıyla yazılır.

### Gold için rıza ve `GOLD_REQUIRED`
- Terfi edilmiş seri de doğrulanmamıştır; `gold_*` araçları `allow_unverified` ancak kullanıcı
  "doğrulanmamış olsa da kullan / riski kabul ediyorum" derse (`unverified_consent`) geçer.
- **Ölçüldü:** model aylık ortalamayı `lakehouse_query` içinde `AVG … GROUP BY ay` ile hesapladı;
  kural stok olsaydı sessizce yanlış olurdu, gözlem izi de kopardı. Yeni politika hatası
  `GOLD_REQUIRED` (tekrar denenebilir): `gold_*` kayıtlıyken dönem toplayan/ortalayan SQL
  reddedilir, ipucu `gold_align/gold_join`'e yönlendirir. Seçenek bırakılmaz (ADR-0010/0011).

### Sohbette kalan analiz: `workspace_query`
Aktif tablo `t` adıyla sertleştirilmiş bellek-içi DuckDB'ye kaydedilir (dış erişim kapalı,
tek SELECT, sözcük engel listesi — `compute_column` ile aynı motor); başka ilişki yoktur, veri
havuzuna **dokunulmaz**. **Varsayılan bakış modu:** sonuç karta yazılır, tablo değişmez, sonuç
kanıt paneli için not edilir. `as_active_table=true` ile sonuç yeni aktif tablo olur (kırpma),
kaynak kolonların provenance'ı taşınır. **Ölçüldü:** ilk sürümde her sorgu tabloyu eziyordu;
24 satırlık nüfus tablosu 5 satıra, sonra tek satırlık özete indi, "toplam yüzde" 2019–2023
üzerinden hesaplandı ve grafik turu düştü.

### Kanıt zinciri, sohbette kalan analiz için
- Cevaptaki sayı önceki tablo sürümünde ya da bakış sorgusu sonucunda olabilir; panel bunları
  "önceki tablo (-n)" / "bakış sorgusu: <sql>" halkasıyla eşler. Araç çıktısından gelen sayı sayıdır.
- `workspace_query` ile kırpılmış web tablosu ve türetilmiş kolonlar web zincirini bozmaz
  (`sources` "web — <başlık>" ön ekiyle tanınır; ölçüldü: liste üyeliği testi yüzünden
  "dönem kolonu yok" diye kopuk görünüyordu).
- Sayfa önceki turda çekildiyse workspace hatırlar (`web_pages`: URL → sha256 + zaman); sonraki
  turların paneli "0 artifact" yerine o sayfayı gösterir.

### Harness: grafik istendiyse grafik
Kullanıcı grafik istediyse (`grafi|çiz|görselle|chart|harita`) ve `chart` çağrılmadan cevap
yazıldıysa bir kez geri gönderilir (ölçüldü: model tabloyu "doğrulamak" için sorgu üstüne sorgu
attı, grafiksiz cevap yazdı). Grafik kartı çizilen satırları taşır ve "araç çağırmayı bırak"
der (ölçüldü: grafik sonrası 8 fazla adım). Nedensellik filtresine "etkisiyle", "nedeniyle"
eklendi (ölçüldü: "sığınmacıların etkisiyle artış hızlanmış" — veride olmayan sebep — geçti).

## Ölçüm (12 Eylül, `/tmp/kkb_demo_acceptance` kopyası üzerinde, model Qwen3.8-27B)

**Deney 1 — Architect, Melbourne günlük minimum sıcaklık (1981–1990, 3.650 gün, GitHub ham CSV).**

| Tur | Kullanıcı | Olan |
|---|---|---|
| 1 | "taslak seri olarak ekle" | profil: tarih + değer, günlük; birim/ölçüm tipi yok → **soruldu** (model `°C`/`stock` uydurdu, kapı yok saydı) |
| 2 | "birim °C, index, aylık kural ortalama; ekle" | `ingest_from_url` → RAW → Bronze → `adhoc` taslak, 3.650 satır, beyan kanıt satırlı |
| 3 | "taslağı onaylıyorum, kataloğa al" | `promote_draft` → taslak → aktif, Silver'a 3.650 satır, semantik `derived` |
| 4 | "1985 aylık ortalama; doğrulanmamış olsa da kullan" | `gold_align(monthly)` rızayla → 12 ay; kanıt zinciri **tam: 13/13 sayı · 365 gözlem → 1 artifact** |
| 5 | "çizgi grafiğini çiz" | `chart` 6/6 kural, PNG; kanıt zinciri tam |

Token: tur başına 20–56 bin prompt, 2–4 çağrı. İlk koşuda model tur 1'de `°C`/`stock` uydurdu
(kapı yok saydı, sordu) ve tur 4'te `AVG … GROUP BY ay` SQL'i yazdı (`GOLD_REQUIRED` → `gold_align`);
ikinci koşuda ikisi de olmadı. "Önce veriyi çek" uyarısı terfi ve grafik sonrası boşa tetiklendi
(bir fazla adım) → iş yapan araç ya da hazır tablo varken susturuldu.

Ayrı süreçte doğrulama: `meta.series` `active / derived / manual / °C / index / avg / daily`;
`adhoc` 3.650, `silver` 3.650 (1981-01-01 → 1990-12-31); `meta.artifact` HTTP 200 + RAW yolu;
`meta.run` success; RAW 67.921 bayt içerik adresli; Bronze parquet `artifact_sha256=…`;
`gold-run align_frequency monthly` 120 satır, 1985'te 12 ay (Ocak 14,22 °C, Temmuz 6,14 °C,
31'er gözlem, kural `avg`).

**Deney 2 — Analist, Our World in Data Türkiye nüfusu (CSV, 261 satır), sohbette.**

| Tur | Kullanıcı | Olan |
|---|---|---|
| 1 | "2000 ve sonrası yıllık nüfusu göster, kaydetme" | `web_url` (sha256 + zaman) → `workspace_query` kırpma 24 satır → tablo; kanıt **tam** 48/48, 1 web sayfası |
| 2 | "toplam yüzde artış, yıllık artış sütunu, en hızlı yıl" | `compute_column` LAG → bakış sorguları: %33,39 (65.425.957 → 87.270.502), 2015 (+1.978.068); kanıt **tam** 5/5 |
| 3 | "çizgi grafiğini çiz" | `chart` 6/6, PNG; kanıt **tam** 7/7 |

Veritabanı parmak izi ayrı süreçte önce/sonra: `meta.series` 1.621, `adhoc` 6, `silver` 684,
`meta.artifact` 48, `meta.run` 2, RAW/Bronze dosya listesi, dosya sha256 — **fark yok**.
Token: tur başına 44–60 bin prompt, 4–6 çağrı.

Birim testleri 252 → 270. Demo kabul senaryoları (mevcut DB): 7/8 — G9 yine anlatı aritmetiği
(model farkları hesapladı, ADR-0037'deki 4/5 kalıntısı), diğer 7 tam.

## Açık kalan
- G9 anlatı aritmetiği: model tabloda olmayan farkları yazıyor; guard bir kez geri gönderiyor,
  ikinci kez işaretliyor. Kalıcı çözüm `workspace_compute_column` zorunluluğu değil, fark
  isteyen sorularda Gold `decompose` ya da hazır fark kolonu.
- Deney 2 turunda `web_url` iki kez çağrılıyor (liste + yükleme); tek çağrıya indirilebilir.
- Grafik başlığında yıl kolonu ondalıklı (2000.0); web tablolarında birim yok, başlık
  "birim belirtilmemiş" diyor — doğru ama çirkin.
