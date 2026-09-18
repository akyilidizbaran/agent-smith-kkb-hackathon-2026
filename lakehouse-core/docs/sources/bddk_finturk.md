# Source: BDDK FinTürk (İllere Göre)

`source_id`: `bddk_finturk`

## Verification status — read this before trusting anything below

| Item | Status | Evidence |
|---|---|---|
| Endpoint, method, form field names | **Verified live** 2026-09-10 | Captured via browser DevTools Network tab on `https://www.bddk.org.tr/BultenFinTurk`, three real `POST /BultenFinturk/tr/Home/VeriGetir` requests inspected |
| `tabloNo=3` (Bireysel Bankacılık) carries `Konut Kredisi` | **Verified live** | Real response for `sehirList[0]=YALOVA`, `donem=2025-9` returned `KonutKredisi` in `colModels`, value `2104493` |
| `tabloNo=1` (Krediler) does **not** carry a housing breakdown | **Verified live** | Real response for `ANKARA`, `2025-9`: only aggregate columns (`ToplamNakdiKrediler`, `NakdiKrediler`, `TakiptekiAlacaklar`, `GayrinakdiKrediler`) |
| `tabloNo=4` (Seçilmiş Sektörel Krediler) does **not** carry a housing breakdown | **Verified live** | Real response for `AĞRI`, `2025-9`: columns are borrower industry sectors (İnşaat, Turizm, Ziraat, Enerji, Denizcilik, ...), not loan product |
| Every other `tabloNo` (Mevduat, Oranlar, Şubeler/Nüfusa Göre Dağılım, Altın Kredileri ve Altın Mevduatı) | ❌ **Not verified** | Not requested in this round; not needed once `tabloNo=3` was confirmed to carry housing |
| Session cookie / antiforgery cookie presence | **Verified live — presence only** | The captured request carried `ASP.NET_SessionId` and an `__RequestVerificationToken_...` cookie |
| Whether those cookies are actually validated (vs. accepted anonymously) | ❌ **Not verified** | Unlike the weekly endpoint's explicit cookie-less proof, no cookie-less/token-less request was attempted against this endpoint |
| Production connector against the live endpoint | **Verified live** 2026-09-10 | `BddkFinTurkConnector` + real `requests.Session`, `sehir=YALOVA`, one month (2025-09): HTTP 200, 8 measure rows, values byte-identical to the DevTools capture below |
| Response envelope shape | **Verified live** | `{"success": true, "Json": {colNames, colModels, data: {rows: [{cell: [...]}]}}}`, structurally identical to `docs/sources/bddk_monthly.md`'s envelope |
| Unit of the `tabloNo=3` measure columns | **Verified** 2026-09-11 | **Bin TL.** Two independent proofs, below: the source page's own table selector labels `tabloNo=3` as `Bireysel Bankacılık (Bin TL)`, and the live 81-province sum reproduces the separately verified BDDK Aylık national total to within 0.001%. The response body still carries no unit — the evidence is the page and the arithmetic, not the payload |
| Multi-province coverage | **Verified live** 2026-09-11 | All 81 catalogued provinces fetched for `2025-09` through the production connector and parser: 81/81 HTTP 200, every response carried a `KonutKredisi` column, every derived `series_id` matched its catalog entry. Earlier this was an inference from one province; it is now a measurement over all of them. Multi-*period* breadth beyond the YALOVA backfill is still inferred from the quarter probe |
| Data is published **quarterly, not monthly** | **Verified live** 2026-09-10 | Every `donem` from 2021-1 to 2026-6 (66 values) probed directly: only March/June/September/December return HTTP 200; every other month returns HTTP 500 (unhandled server error), for every year tested |

**How this was captured:** a person (not this connector) used a real browser's DevTools Network
tab against `https://www.bddk.org.tr/BultenFinTurk`, selecting different kalem (Krediler /
Seçilmiş Sektörel Krediler / Bireysel Bankacılık) and province filters, and reported the Request
Payload and Response body for three requests. This is the same category of evidence
`docs/sources/bddk_weekly.md` calls "Verified from page source" / a rendered report — it proves
the contract shape, not that this project's own connector code reproduces it correctly end to end.

### Live smoke test result (2026-09-10)

Production `BddkFinTurkConnector` + `BddkFinTurkParser`, real `requests.Session` (not a fixture),
run through the full pipeline (RAW → `meta.artifact` → Bronze Parquet):

| | |
|---|---|
| Request | `sehir=YALOVA`, `tarafKodu=10001`, `tabloNo=3`, one calendar month (2025-09) |
| HTTP status / media type | `200` / `application/json` |
| Rows produced | **8** (one per measure column: TasitKredisi, KonutKredisi, KrediliMevduatHesabi, DigerTuketiciKredileri, BireyselKrediKartlari, and their 3 Takipteki counterparts) |
| `KonutKredisi` value | `2104493`, identical to the DevTools capture above — confirms the connector reproduces exactly what a real browser session received |
| `series_id` for the housing row | `bddk_finturk:YALOVA_KonutKredisi`, matching `catalog/series/bddk_finturk.yml` exactly |
| Parser warnings | none |

This confirms the endpoint contract, the session-priming `GET`, and the parser's column
handling all work together for this one (province, quarter) pair.

### Full-range backfill result (2026-09-10)

The same connector/parser were then run for `sehir=YALOVA` across the full `2021-01-01` to
`2026-06-30` range (`scripts/run_catalog_ingestion.py`):

| | |
|---|---|
| Periods requested | 22 quarters (2021 Q1 – 2026 Q2) |
| RAW artifacts fetched | 22/22, all HTTP 200 |
| Bronze rows written | 22/22 (8 measure series each = 176 rows total for this province) |
| Failures | 0 |

One bug was found and fixed during this run, not in the connector but in how the *ingestion
script* handled a batch containing an asset already in Bronze from the earlier single-quarter
smoke test: the first attempt aborted partway through the batch on that one already-present
quarter and silently left 3 later quarters (2025-12, 2026-3, 2026-6) fetched to RAW but never
written to Bronze. `scripts/run_catalog_ingestion.py` was changed to land each asset
independently instead of treating a connector's whole batch as all-or-nothing; a re-run then
produced the 22/22 result above. This was a script-level fix, not a change to any shared
`lakehouse-core/src` code.

**Not yet confirmed by any run so far:**

1. **Cookie/token necessity is still untested.** Every run so far went through
   `_ensure_session`'s GET-first path; whether skipping it would also have succeeded (meaning
   the cookies are incidental, not enforced) was not measured — a cookie-less request was not
   attempted.

### All-province backfill result (2026-09-10, after this smoke test)

Following the single-province proof above, all 81 provinces in
`catalog/series/bddk_finturk.yml` were fetched live through this same connector/parser,
via `scripts/run_catalog_ingestion.py` over the full `2021-01-01`–`2026-06-30` range:

| | |
|---|---|
| Provinces requested | 81/81 |
| Periods per province | 22 quarters (2021 Q1 – 2026 Q2) |
| RAW artifacts fetched | 1782/1782 (81 × 22), all HTTP 200 |
| Bronze rows written | 1782/1782, 0 failures |

This supersedes the "only Yalova" caveat below: every province in the catalog has now had
its own live-verified fetch through this connector, not just an inferred schema match from
manual DevTools captures.

## Verified endpoint contract

BDDK publishes no API documentation for this path. The contract below was read from real
DevTools captures against the FinTürk report screen at `https://www.bddk.org.tr/BultenFinTurk`.

| Item | Value |
|---|---|
| Host | `https://www.bddk.org.tr` |
| Report page (GET, to acquire a session) | `/BultenFinTurk` |
| Data endpoint | `POST /BultenFinturk/tr/Home/VeriGetir` |
| Encoding | `application/x-www-form-urlencoded` |
| Response | `application/json; charset=utf-8` |

### Form fields

| Field | Verified value(s) | Notes |
|---|---|---|
| `tabloNo` | `1`, `3`, `4` observed; `3` used by this connector | Selects which report table; **not** a loan-product selector on its own — see table below |
| `donem` | `2025-9` | `YYYY-M`, month **not** zero-padded. One period per request — no start/end range exists on this endpoint |
| `tarafList[0]` | `10001` | Sektör; same party-code convention as the weekly/monthly endpoints. Only index `[0]` was observed; whether more indices are accepted is untested |
| `sehirList[0]` | `ANKARA`, `ADANA`, `AĞRI`, `YALOVA` (all observed) | Upper-case Turkish province name. Only index `[0]` was observed |

### `tabloNo` → table meaning (verified subset)

| `tabloNo` | Table | Carries `Konut Kredisi`? |
|---|---|---|
| `1` | Krediler (aggregate cash/non-cash totals) | No |
| `3` | Bireysel Bankacılık (retail lending) | **Yes** — `KonutKredisi`, `TakiptekiKonutKredisi` |
| `4` | Seçilmiş Sektörel Krediler (borrower's industry sector) | No — this is sector-of-economy (İnşaat, Turizm, Ziraat, Enerji, Denizcilik, ...), not loan product |
| others | Mevduat, Oranlar, Şubeler/Nüfusa Göre Dağılım, Altın Kredileri ve Altın Mevduatı | Not checked |

### `tabloNo=3` (Bireysel Bankacılık) response shape

```json
{"success": true, "Json": {
  "colNames": ["Eftodu", "Yıl", "Ay", "Şehir", "Grup", "Taşıt Kredisi", "Konut Kredisi",
               "Kredili Mevduat Hesabı", "Diğer Tüketici Kredileri", "Bireysel Kredi Kartları",
               "Takipteki Taşıt Kredisi", "Takipteki Konut Kredisi",
               "Takipteki Diğer Tüketici Kredileri"],
  "colModels": [{"name": "EftKodu", "hidden": true, ...}, {"name": "Yil", ...},
                {"name": "Ay", ...}, {"name": "Sehir", ...}, {"name": "Grup", ...},
                {"name": "TasitKredisi", "formatter": "integer",
                 "formatoptions": {"thousandsSeparator": ".", "defaultValue": "0"}, ...},
                {"name": "KonutKredisi", "formatter": "integer", ...}, "...5 more measure columns"],
  "data": {"page": "1", "total": "1", "records": "1",
           "rows": [{"cell": [10001, 2025, 9, "YALOVA", "SEKTÖR",
                               192843, 2104493, 2436929, 4911508, 8316033,
                               1614, 2295, 394348]}]}}}
```

One request returns exactly **one row** (one city, one period) with **8 measure columns**:
`TasitKredisi`, `KonutKredisi`, `KrediliMevduatHesabi`, `DigerTuketiciKredileri`,
`BireyselKrediKartlari`, `TakiptekiTasitKredisi`, `TakiptekiKonutKredisi`,
`TakiptekiDigerTuketiciKredileri`. This project's catalog uses only `KonutKredisi`; the parser
emits all 8 as separate series (`BddkFinTurkParser` does not filter), because deciding which
measures matter is a catalog decision, not a parsing one.

## Source anomalies

1. **Data is quarterly; the form's month-level `donem` field is misleading.** Every `donem` value
   from `2021-1` through `2026-6` (66 values, all years) was probed directly against
   `VeriGetir`. Only quarter-end months — March, June, September, December — return HTTP 200.
   Every other month returns **HTTP 500** (`Runtime Error`, an unhandled server-side exception,
   not `{"success": false, ...}` or an empty grid). This is a genuine source behaviour, not a
   connector bug: BDDK's own server throws when asked for a period it has no data for, instead
   of answering gracefully. `BddkFinTurkConnector` therefore only ever requests quarter-end
   months (`_QUARTER_END_MONTHS = (3, 6, 9, 12)`) and treats HTTP 500 the same as any other
   retryable server error — it does **not** special-case it as "no data", because a 500 on a
   quarter-end month would still indicate a real problem worth surfacing.
2. **One request = one row, one quarter, no range.** Unlike the weekly/monthly endpoints, `donem`
   is a single period, not a start/end pair. `BddkFinTurkConnector` windows a `FetchSpec`'s date
   range into one request per quarter internally, returning one `FetchedAsset` per quarter — this
   windowing has been run live for one province across the full 2021-2026 range (see "Live smoke
   test result").
3. **`tabloNo` is not a loan-product selector.** It selects a whole report table (Krediler /
   Bireysel Bankacılık / Seçilmiş Sektörel Krediler / ...), each with its own, differently-shaped
   set of measure columns. Guessing a `tabloNo` without capturing its response first is exactly
   how `1` and `4` were ruled out in this round — do not assume a new `tabloNo` carries housing
   data without checking.
4. **Unit: Bin TL — established 2026-09-11.** The response body still states no unit. The
   unit was established from two independent directions instead, and both had to agree before
   the catalog was moved off `unit: null`.

   **(a) The source's own label.** `https://www.bddk.org.tr/BultenFinTurk` renders the table
   chooser as a `<select id="ddlTablo">` whose option *values* are exactly the `tabloNo` this
   connector sends on the wire, and whose labels state each table's unit. Captured verbatim in
   `tests/fixtures/pages/bddk_finturk_table_units.html`:

   ```html
   <option value="3">Bireysel Bankacılık (Bin TL)</option>
   ```

   This is the same category of evidence `docs/sources/bddk_weekly.md` calls "verified from
   page source", and it is bound to the wire parameter rather than to a screenshot of a
   rendered grid.

   **(b) A cross-source identity, measured live.** All 81 catalogued provinces were fetched for
   `2025-09` through the production connector and parser, and their `KonutKredisi` values
   summed. The result was compared against `bddk_monthly:1534_Toplam` — a different endpoint,
   a different parser, and a series whose own unit (`milyon TL`) is stated in its response and
   already verified:

   | | |
   |---|---|
   | Provinces fetched | 81/81, no failures |
   | Sum of raw province values (2025-09) | `623,770,000` |
   | Read as **Bin TL** | `623,770` milyon TL |
   | BDDK Aylık national total (2025-09, milyon TL) | `623,765` |
   | Difference | **0.0008%** (rounding: FinTürk rounds to a thousand TL, the monthly bulletin to a million) |

   The other two readings are not close calls. As `milyon TL`, İstanbul alone would be 294× the
   national stock; as plain `TL`, all 81 provinces together would come to 624 million lira.

   The same run is also the first province-wide verification of the catalog itself: every one of
   the 81 province entries resolved to a live response with a `KonutKredisi` column, which the
   earlier single-province (YALOVA) check could only assume.

   Catalog effect: all 81 entries move from `unit: null` / `semantic_confidence: derived` to
   `unit: TRY_th` / `semantic_confidence: verified`. Note that (b) also confirms these are
   *sector* totals comparable to the national series, not a subset of banks.

## Confirmation required

1. **Cookie/token necessity.** Untested; see above.
2. **Unit — resolved, see above.** Established as Bin TL on 2026-09-11 from the source page's
   own table label plus an 81-province cross-check against the monthly bulletin. The remaining
   unit question is the *other* tables (`tabloNo` 1, 2, 4, 7 are all labelled Bin TL on the same
   selector, but none of them has been cross-checked the way table 3 has).

## Not implemented in this track

- Any party other than Sektör (`10001`).
- Any Bronze/Silver/Gold semantics beyond raw pass-through: no unit conversion, no `date_key`,
  no cross-province aggregation.

## Geniş kapsam kurulumu (2026-09-18)

The demo baseline now uses the five FinTürk tables that produce the requested
`56 kolon × 81 il = 4.536 seri` breadth. The live table selector and a 2025-09
response were checked before ingestion:

| tabloNo | source label | measure columns | in-scope series |
|---:|---|---:|---:|
| 1 | Krediler (Bin TL) | 4 | 324 |
| 2 | Mevduat (Bin TL) | 7 | 567 |
| 3 | Bireysel Bankacılık (Bin TL) | 8 | 648 |
| 4 | Seçilmiş Sektörel Krediler (Bin TL) | 31 | 2,511 |
| 6 | Şubeler (Adet) ve Nüfusa Göre Dağılım (TL) | 6 | 486 |
| **Toplam** |  | **56** | **4,536** |

`tabloNo=5` (Oranlar) and `tabloNo=7` (Altın Kredileri ve Altın Mevduatı) are
deliberately outside this demo baseline, matching the agreed 56-column scope.
All requests use the Sektör party (`tarafKodu=10001`). The endpoint's `HEPSİ`
province selection returns all provinces in one response; tables 1–4 also return
an extra `YURT DIŞI` row, which is excluded from the 81-province catalog.

The catalog and database were expanded to 4,536 active FinTürk series. A full
quarterly backfill from 2016-03 through 2026-06 landed 210 immutable RAW/Bronze
artifacts (42 quarters × 5 tables) and 190,512 Silver observations. Existing
table-3 series IDs are preserved; their dataset identity is now the shared
`bddk_finturk_table3`, which makes all five bulk table datasets consistent.
New table-1/2/4/6 records carry `semantic_confidence: derived` until their
table-specific units and measure semantics receive the same independent
cross-check as table 3.

## Genişletme (2026-09-13): tabloNo=3 yanıtının diğer 7 ölçüm sütunu kataloğa alındı

`tabloNo=3` yanıtı bir il ve dönem için 8 ölçüm sütunu döndürür ve parser hepsini
`bddk_finturk:<İL>_<Kolon>` kimliğiyle Bronze'a yazar (yukarıdaki YALOVA örneği: 8 satır).
Bugüne kadar yalnız `KonutKredisi` katalogluydu; Silver diğer 7'sini `not in meta.series`
gerekçesiyle tutuyordu. 13 Eylül'de `TasitKredisi`, `DigerTuketiciKredileri`,
`KrediliMevduatHesabi`, `BireyselKrediKartlari`, `TakiptekiTasitKredisi`,
`TakiptekiKonutKredisi`, `TakiptekiDigerTuketiciKredileri` sütunları 81 il için kataloğa
girdi (7 × 81 = 567 seri; `catalog/series/bddk_finturk.yml` "Genişletme" bloğu). Ek istek
gerekmez: aynı çekilişin aynı yanıtı. Birim ve frekans konut kolonuyla aynı (Bin TL, çeyreklik);
kolon adları yukarıdaki doğrulanmış `colModels` listesinden.

`scripts/run_catalog_ingestion.py` aynı FetchSpec'i paylaşan serileri bir kez çeker (bir ilin
8 serisi = 1 istek/dönem); 13 Eylül değişikliği.

`dataset_id` notu: 7 yeni sütunun serileri ilin konut girdisiyle aynı `dataset_id`'yi taşır
(`bddk_finturk_<il>_housing_loans`). Sebep ölçüldü: bir çekiliş tek asset üretir ve parser bütün
satırlara o asset'in `dataset_id`'sini yazar; Silver'ın staging denetimi katalogdaki
`dataset_id` ile Bronze'dakinin birebir örtüşmesini ister (ilk deneme
`bddk_finturk:ADANA_DigerTuketiciKredileri` için "invalid catalog semantics" ile düştü). Ad
tarihsel bir yanlış adlandırmadır: dataset "tabloNo=3, Bireysel Bankacılık, il" çekilişidir,
yalnız konut değil; mevcut Bronze artifact'lerini yetim bırakmamak için değiştirilmedi.

## Genişletme (2026-09-16): tablo 1, 2, 4 ve 6

Kapsam: `tabloNo` 1 (Krediler), 2 (Mevduat), 4 (Seçilmiş Sektörel Krediler) ve 6 (Şubeler ve
Nüfusa Göre Dağılım), yalnız Sektör tarafı (`tarafKodu=10001`). Tablo 5 (Oranlar) 1-4'ten
hesaplanabildiği, tablo 7 (Altın) konu dışı olduğu için alınmadı. Girdiler
`scripts/generate_bddk_finturk_catalog.py` ile canlı kaynaktan üretilir: 48 ölçü sütunu × 81 il
= 3.888 seri (sütun sayıları: 4 / 7 / 31 / 6).

### Birimler — kaynağın kendi tablo seçicisinden

| tabloNo | Seçicideki etiket | Katalog birimi |
|---|---|---|
| 1 | Krediler (Bin TL) | `TRY_th` |
| 2 | Mevduat (Bin TL) | `TRY_th` |
| 4 | Seçilmiş Sektörel Krediler (Bin TL) | `TRY_th` |
| 6 | Şubeler (Adet) ve Nüfusa Göre Dağılım (TL) | sütuna göre: `SubeSayisi`, `SubeyeDusenNufus` → `adet`; `KisiBasi*` → `TRY` |

Tablo 6'nın karışık birimi aritmetikle doğrulandı (ANKARA, 2025-09): 982 şube × 4.867 kişi/şube
= 4,78 milyon kişi; 595.699,42 TL/kişi × 4,78 milyon = 2,85 trilyon TL, tablo 1'in aynı il ve
çeyrek için verdiği toplam nakdi kredi 2.892.401.068 bin TL. ADANA 2025-09'da kişi başı toplam
mevduat × nüfus / 1000 = 354.980.410, tablo 2'nin toplamı 355.009.176 bin TL (%99,99).

### Kimlik ve dataset

- `series_id` ASCII'dir ve parser'ın kendi harf haritasıyla üretilir (`ÇORUM` → `CORUM`);
  `native_code` kaynağın yazımını korur.
- `dataset_id` il × tablo başına tektir (`bddk_finturk_<il>_krediler`, `_mevduat`,
  `_sektorel_krediler`, `_subeler_nufus`). Bu, yukarıdaki 13 Eylül notunda kayda geçmiş olan
  kuralın aynısıdır; ilk üretimde gözden kaçtı ve tek illik denemede aynı "invalid catalog
  semantics" hatasıyla yakalandı.
- Endpoint sütunu değil tablo numarasını aldığı için sütun → `tabloNo` eşlemesi
  `scripts/bddk_finturk_table_map.json` içinde üretilmiş olarak tutulur ve
  `scripts/ingestion_registry.py` tarafından okunur.

### Çekim ve doğrulama (2026-09-16)

`run_catalog_ingestion.py`: 3.840/3.840 seri, 0 hata (320 gerçek çekim, 3.520 paylaşılan) + ADANA
denemesi 48/48. Silver'da 4.536 FinTürk serisi × 22 çeyrek = 99.792 gözlem, 81 il, eksik çeyreği
olan seri yok.

Aylık bültenle ulusal uzlaşma, 2025-12:

| Ölçü | 81 il toplamı | Aylık bülten | Not |
|---|---|---|---|
| Toplam mevduat (milyon TL) | 25.549.895 | 25.549.894 (`1344?Toplam`, yurt içi yerleşik) | Toplam mevduat (`1357`) 27.223.190; fark yurt dışı yerleşiklerin, hiçbir ile ait olmayan mevduatı |
| Konut kredisi (milyon TL) | 678.975 | 678.970 (`1534?Toplam`) | |
| Toplam nakdi kredi (milyon TL) | 23.451.862 | 23.127.970 (`1160?Toplam`, bilanço) | ~%1,4; tanımlar birebir aynı değil |
| İnşaat sektörü kredisi (bin TL) | 1.446.597.282 | 1.516.423.663 (`1452?ToplamNakdi`) | ~%4,6; "seçilmiş sektörel" ile sektörel dağılım tanımı farklı |

### Arama hijyeni: katalog açıklaması neden kısa

Katalog açıklamaları ajanın aramasında dizinlenir. Bu tabloların ilk üretiminde açıklamalar kanıt
metnini de taşıyordu: tablo 6'nın 486 serisinde yukarıdaki ANKARA aritmetiği ("…toplam nakdi
krediyle örtüşüyor"), 3.888 serinin hepsinde "Mart/Haziran/Eylül/Aralık". 2026-09-16 ölçümünde bu
tür başka seri adları ve tarih kelimeleri, il belirtilmeyen ulusal sorularda il serilerinin ulusal
serilerin önüne geçmesine katkı verdi (24 soruluk arama testi; "Konut kredisi toplamı" sorusunda
ulusal seri kelime aramasında ilk 50 adayın dışına düştü). Bu yüzden açıklama artık yalnız seriyi
anlatır — tablo, ölçü, il, taraf, stok/sayım niteliği, çeyreklik yayın ve birim — ve kanıtlar bu
belgede durur.
