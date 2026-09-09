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

## Subtotal / bold signal: where it is and where it is not

**Captured from the live endpoint on 2026-09-09 with one request.**

| Endpoint | Declares `BasitFont`? | `parent`? |
|---|---|---|
| `POST /BultenAylik/tr/Home/GelismisRaporGetir` — **what this connector uses** | ❌ no | ❌ no |
| `POST /BultenAylik/tr/Home/BasitRaporGetir` — simple report, not used here | ✅ yes | ❌ no |

The advanced report declares exactly `BankaAdi, Yil, Ay, <measure>, Sira`. In its rows
`cell[3]` is the **measure value** (`801438`), so a positional `cell[3] == "bold"` test would
misread data as a style token.

The simple report declares `BankaAdi, BasitSira, Ad, BasitFont, Tp, Yp, Toplam` and does carry
the signal: `Tüketici Kredileri (2+3+4)` is marked `'bold'` while leaf rows such as
`Tüketici Kredileri - Konut` carry `''`. That capture is committed as evidence at
`tests/fixtures/raw/bddk_monthly/bddk_monthly_simple_report_basitfont.json` (6 rows, trimmed
from 41, no secrets). Cross-check: its `Toplam` for Konut is `801438`, identical to the
advanced report's 2026-06 value — the same data in a different envelope.

`parent` was **not found on either endpoint** and remains **confirmation required**.

What the parser does with this:

- `BasitFont` and `parent` remain structural names, so they can never be mistaken for measure
  columns if BDDK adds them to the advanced response.
- V1 does **not** add `source_font`, `source_parent`, `source_is_bold` or `is_subtotal` to
  Bronze. On the endpoint we actually ingest these would be permanently `NULL`, and changing
  the output columns without changing `bddk_monthly_observations.v1` would violate the schema
  contract.
- If the team later adopts the simple-report transport, preserving its source style requires
  an explicit parser/schema V2. Interpreting `bold` as a financial subtotal remains a Silver
  decision; display styling alone is not a universal accounting rule.

## TLS: incomplete certificate chain

`www.bddk.org.tr` serves **only its leaf certificate** and omits the
`GlobalSign RSA OV SSL CA 2018` intermediate, so `openssl s_client` reports
`Verify return code: 21 (unable to verify the first certificate)`. Browsers and `curl` hide
this by chasing the certificate's AIA extension; Python's `ssl` module does not, so a plain
`requests` call fails with `CERTIFICATE_VERIFY_FAILED`.

This is a **source-side misconfiguration**, not a local quirk and not a WAF block.

The connector's behaviour:

- `requests.exceptions.SSLError` is caught **before** the generic `RequestException`, because
  `SSLError` is a subclass of it and would otherwise be classified as a transient error.
- It is reported as `SOURCE_UNAVAILABLE` with **`retryable=False`** — retrying a trust failure
  cannot succeed.
- The message names the cause and points at the safe remedy. It contains no headers, cookies,
  tokens or request bodies.
- The connector **never** weakens TLS: no `verify=False`, no suppressed warnings, no
  certificate downloaded at runtime, no unverified certificate committed to the repository.

**The supported fix is an injected session with verification left on.** Both BDDK connectors
accept a `requests.Session`, so a deployment can pass one whose CA bundle contains the missing
intermediate:

```python
session = requests.Session()
session.verify = "/path/to/ca-bundle.pem"   # certifi roots + the intermediate; verify stays ON
connector = BddkMonthlyConnector(storage, session=session)
```

Assembling that bundle into the image or environment is an **Infrastructure** task, not a
Source Access one. The intermediate is published at the `caIssuers` URI inside BDDK's own
certificate.

## Revision behaviour (source fact only)

BDDK's own weekly-bulletin explanation states that **previously published weekly values can be
updated in later releases**. We have not found an equivalent monthly guarantee, so monthly
figures are treated as potentially revisable until BDDK confirms otherwise; this is a
defensive policy, not a claimed monthly source fact.

What this means for Source Access, and where the line is:

- The RAW artifact is content-addressed by SHA-256, so a restated figure necessarily produces
  **different bytes and therefore a different artifact**. Detecting a revision is a matter of
  comparing artifact hashes for the same logical request — `meta.artifact_request` already
  records the request fingerprint that makes that comparison possible.
- **Nothing here implements it.** `meta.dataset_version` lifecycle, vintage selection, a
  revision table, and any Silver/Gold restatement logic are shared/infrastructure concerns and
  are deliberately absent from this track.
- No revision has been *observed* in this project yet; the statement above is the source's,
  not a measurement of ours.
