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
| Unit of any measure column | ❌ **Not verified** | No unit appears anywhere in the response (no `(milyon TL)`-style suffix like the monthly endpoint) and none was found on the FinTürk page itself in this round |
| Multi-province, multi-period coverage | ❌ **Not verified** | Only `YALOVA` × `2025-9` was captured with `tabloNo=3`. Other provinces/periods are assumed to share the same schema (their own response envelopes for `tabloNo=1`/`4` matched across `ANKARA`/`ADANA`/`AĞRI`) but this is an inference, not a per-province measurement |
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
4. **No unit anywhere.** Neither the response body nor (as far as this round observed) the
   FinTürk page itself states a unit for `Konut Kredisi`. `docs/sources/bddk_monthly.md`'s
   monthly aggregate for a comparable concept is in the hundreds-of-thousands (milyon TL); this
   endpoint's raw values for a single province (e.g. `2104493`) are consistent with **thousand
   TL** rather than million TL, but this is an inference from magnitude, not a citation, and is
   explicitly **not** used as the catalog's unit (`unit: null`, `semantic_confidence: derived`).
5. **Session/antiforgery cookies observed but not proven required.** See "Verification status"
   above. `BddkFinTurkConnector` primes a session with one `GET` before posting, as a
   conservative default matching what a real browser does — this is a choice made in the absence
   of a disproof, not a confirmed requirement.
6. **`formatoptions.defaultValue` is `"0"`** on every measure column, the same display-default
   behaviour as the monthly endpoint (`docs/sources/bddk_monthly.md`, anomaly 5). The parser
   never substitutes a value and emits a warning per fetch instead.

## Confirmation required

1. **Cookie/token necessity.** Untested; see above.
2. **Unit.** Genuinely unknown; do not splice or convert without first finding an authoritative
   unit statement (e.g. on the FinTürk page's table header, the way the weekly endpoint's unit
   was confirmed from `docs/sources/bddk_weekly.md`'s official table header citation).
3. **`tarafList`/`sehirList` repeatability.** Only a single index (`[0]`) was ever sent in the
   captures this contract is based on. Whether the endpoint accepts multiple parties or
   provinces per call, the way the monthly endpoint's `taraf` does, was not tested.
4. **Revision behaviour.** Not observed in this round; treat monthly figures as potentially
   revisable by default, consistent with `docs/sources/bddk_weekly.md`'s stated policy for BDDK
   sources generally.

## Not implemented in this track

- Any `tabloNo` other than `3`.
- Any party other than Sektör (`10001`).
- Any Bronze/Silver/Gold semantics beyond raw pass-through: no unit conversion, no `date_key`,
  no cross-province aggregation.
