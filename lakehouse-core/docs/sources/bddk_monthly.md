# Source: BDDK Monthly Bulletin (Aylık Bülten)

`source_id`: `bddk_monthly`

## Verified endpoint contract

Verified live on 2026-09-08 against `https://www.bddk.org.tr`. BDDK publishes no API
documentation for this path; the contract below was read from the advanced-report screen at
`/BultenAylik/tr/Home/Gelismis` and confirmed by real calls.

| Item | Value |
|---|---|
| Host | `https://www.bddk.org.tr` |
| Time-series endpoint | `POST /BultenAylik/tr/Home/GelismisRaporGetir` |
| Single-period endpoint | `POST /BultenAylik/tr/Home/BasitRaporGetir` |
| Item/column tree | `GET /BultenAylik/tr/Home/KalemSutunGetir?kalemNoList=<id>` |
| Excel export (fallback) | `POST /BultenAylik/tr/Home/GelismisExceleAktar`, same form fields |
| Authentication | **None.** No API key, no antiforgery token, **no session cookie.** |
| Encoding | `application/x-www-form-urlencoded`; repeatable `taraf` and `kalemSutun` fields |
| Response | `application/json` |

### Form fields

| Field | Example | Notes |
|---|---|---|
| `baslangicYil` / `baslangicAy` | `2021` / `1` | Inclusive start |
| `bitisYil` / `bitisAy` | `2026` / `6` | Inclusive end |
| `periyot` | `1` | 1 monthly, 3 quarterly, 6 semi-annual, 12 yearly |
| `paraBirimi` | `TL` | `TL` or `USD` |
| `taraf` | `10001` | Repeatable. `10001` Sektör, `10002` Mevduat, `10003` Katılım, … |
| `kalemSutun` | `1534?Toplam` | `<item id>?<Tp\|Yp\|Toplam>`. **The connector accepts exactly one per `FetchSpec`** — see below. |
| `gosterimTuru` | `grid` | `grid` for tabular payload |

### V1 rule: one `kalemSutun` per `FetchSpec`

Live verification showed that sending several `kalemSutun` values that describe the same
concept makes BDDK answer **HTTP 200 with `{"success": false, ...}`**. The connector therefore
accepts **exactly one** `kalemSutun` per `FetchSpec` and raises a typed, non-retryable
`UNSUPPORTED_FORMAT` error before any request is issued when more than one is supplied.

`taraf` stays repeatable: BDDK does accept several parties in one call.

**Historical schema ids are fetched separately.** One concept can carry several item ids, one
per bulletin schema version — `Tüketici Kredileri - Konut` is offered as `1534,288,219,238`.
Each id must be retrieved with **its own `FetchSpec`**, and the resulting series reconciled by a
later layer through a `native_code_aliases`-style mapping. Concatenating them into one request
is a known-bad combination, not an optimization.

This rule lives in the connector, not the parser: rejecting it locally costs no request and
requires no inspection of a response body, which keeps the connector's "retrieve bytes, parse
nothing" boundary intact. The parser separately rejects any `success:false` body that does
arrive, so both layers are covered.

**One call returns the whole range.** A single request for 2021-01 → 2026-06 returned all
66 monthly observations, so no windowing is needed at this scale.

### Correction to an earlier assumption

An earlier research note claimed this endpoint requires an ASP.NET session cookie. That is
**wrong**. The same request succeeds with no cookie and returns byte-identical content. The
earlier failure was caused by sending several `kalemSutun` values at once, not by the missing
cookie.

## Verified codes used by this track

| Concept | `kalemSutun` | `taraf` | `paraBirimi` |
|---|---|---|---|
| Tüketici Kredileri – Konut, Toplam | `1534?Toplam` | `10001` (Sektör) | `TL` |

Golden values from the live 66-row response, in `milyon TL`: **2021-01 = 276785**,
**2026-06 = 801438**.

## Source anomalies

1. **HTTP 200 does not mean success.** A failed report returns HTTP 200 with
   `{"success": false, "error": "Gelişmiş Rapor üretilirken hata oluştu!"}`. The connector
   stores that body as a faithful RAW artifact; the parser rejects it with
   `SOURCE_UNAVAILABLE` (retryable). Detecting it in the connector would require parsing the
   body, which the boundary contract forbids.
2. **Rows are positional `cell` arrays** that are meaningless without `colModels[*].name`.
3. **The unit lives inside the column name** (`... (milyon TL)-Toplam`). There is no unit
   field. `colNames` shows only `"Toplam"`, so `colModels` is the field of record.
4. **Rows are returned newest first**, with BDDK's own rank in `Sira`.
5. **`formatoptions.defaultValue` is `"0"`.** This is a UI display default; an absent value can
   appear as zero in the BDDK grid. The parser never substitutes a value and emits a warning.
6. **A single concept has several item ids.** `Tüketici Kredileri - Konut` is offered as
   `1534,288,219,238` — one id per bulletin schema version. `1534` alone covers
   2021-01 … 2026-06; requesting the whole group triggers the `success:false` body. The
   connector rejects multi-item requests outright (see "V1 rule" above); a future
   `native_code_aliases` field should carry the alternates.
7. **Values may be rounded.** BDDK's own weekly-bulletin explanation states that sub-items need
   not sum exactly to their totals because of rounding, so reconciliation checks need a
   tolerance rather than equality.
8. **Column labels are unstable identifiers.** The measure column name is a Turkish label that
   loses characters (`ü`, `ı`, `ş`) when reduced to the identifier alphabet the shared
   `series_id` contract allows, and BDDK can reword it. The parser therefore prefers the
   requested `kalemSutun` id recorded in artifact metadata, producing
   `bddk_monthly:1534_Toplam`, and only falls back to a label slug with a warning.
9. **Turkish number formatting applies to the Excel path**, not to this JSON path: the JSON
   endpoint returns native numbers. The Excel fallback needs `.` thousands and `,` decimal
   handling.

## Not implemented in this track

- Weekly bulletin (`/BultenHaftalik/...`) and FinTürk (`/BultenFinturk/...`).
- The Excel export fallback. Its path is recorded in artifact metadata as
  `excel_fallback_path` so a later track can switch transport without changing the contract.
- Any Bronze/Silver/Gold materialization, date construction, or unit conversion.
