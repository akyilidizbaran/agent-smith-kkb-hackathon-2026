# Source: EVDS (TCMB Electronic Data Delivery System)

`source_id`: `evds`

## Verification status — read this before trusting anything below

Different parts of this integration carry **different levels of evidence**. Passing tests do
**not** mean the official endpoint has been exercised.

| Item | Status | Evidence |
|---|---|---|
| Official keyed endpoint contract (base URL, `key` header, parameters, date format, 1000-observation cap) | **Verified from documentation** | TCMB's own *EVDS Web Servis Kılavuzu*, `/igmevdsms-dis/documents/showDocument?docId=8` |
| `evds2` service path is dead | **Verified live** | `GET https://evds2.tcmb.gov.tr/service/evds/...` returned HTTP 302 to `evds3` on 2026-09-08 |
| Missing key is rejected | **Verified live** | Keyless request returned HTTP 403 `{"status":"403","message":"Required request header 'key' is not present"}` |
| Connector HTTP behaviour (retry, classification, key handling, RAW write) | **Verified by test only** | All connector tests use a **fake in-process session**. No socket is opened. |
| Parser response shape (envelope, `Tarih`, `UNIXTIME`, string values, nulls) | **Verified against `/fe` captures** | Fixtures came from the EVDS3 web application's own `POST /igmevdsms-dis/fe` endpoint, not from the documented keyed endpoint |
| **Official keyed endpoint, live** | ❌ **NOT VERIFIED** | No API key was available. The keyed endpoint has never been called by this track. |

### What this means in practice

- `POST /igmevdsms-dis/fe` is an **undocumented internal endpoint of the EVDS web application**.
  It was used **only to learn the response shape**. It must **not** be used as a production
  transport or as a fallback: it is unversioned, unsupported, may change without notice, and
  using it would route production traffic through an interface TCMB does not publish for
  integration. The connector calls the documented keyed endpoint exclusively.
- The two endpoints are served by the same EVDS3 backend and take the same `type=json`
  contract, so the envelope is **expected** to be identical — but that is an expectation, not a
  measurement.

### Required smoke test once an API key exists

Before any of this is relied on, run a **single narrow live call** against the documented
endpoint and re-validate the fixtures:

1. Set `EVDS_API_KEY` in the local environment only (never in a file that is committed).
2. Request **one series over a short range**, for example `TP.KFE.TR` for `01-01-2026` to
   `30-06-2026` at `frequency=5` — six observations, well under the 1000-observation cap.
3. Confirm HTTP 200 and that the body has `items`, a `Tarih` field, a `UNIXTIME` field, and one
   column per requested series.
4. Compare the envelope key-for-key against `tests/fixtures/raw/evds/*.json`. If anything
   differs, **replace the fixtures with the keyed-endpoint capture** and update
   `EvdsParser` and this document.
5. Confirm the observation count matches the expected number of periods, to exercise the
   silent-truncation guard.

Until step 4 has been done, treat every parser assertion about the response shape as
provisional.

## Verified endpoint contract

Taken from the official *EVDS Web Servis Kılavuzu*, published by TCMB at
`https://evds3.tcmb.gov.tr/igmevdsms-dis/documents/showDocument?docId=8`.

| Item | Value |
|---|---|
| Base URL | `https://evds3.tcmb.gov.tr/igmevdsms-dis` |
| Observation request | `GET /series=<CODE>[-<CODE>...]&startDate=dd-mm-yyyy&endDate=dd-mm-yyyy&type=json` |
| Data-group request | `GET /datagroup=<CODE>&startDate=...&endDate=...&type=csv` |
| Series metadata | `GET /serieList/type=json&code=<datagroup or series code>` |
| Data groups | `GET /datagroups/mode=0&type=json`, `GET /datagroups/mode=1&code=<code>&type=json` |
| Categories | `GET /categories/type=json` |
| Authentication | API key in the **`key` HTTP request header**. A missing key returns HTTP 403 with `{"status":"403","message":"Required request header 'key' is not present"}`. |
| Request date format | `dd-mm-yyyy` |
| Response formats | `json`, `csv`, `xml` |
| Hard limit | **1000 observations per request**, counted backwards from `endDate`. A wider range is truncated **silently**. |
| Optional parameters | `frequency` (1 daily … 8 yearly), `aggregationTypes` (`avg,min,max,first,last,sum`), `formulas` (0–8), `decimalSeperator` |

**The `evds2` service path is dead.** `https://evds2.tcmb.gov.tr/service/evds/...` responds with
HTTP 302 to `evds3.tcmb.gov.tr`. Most public examples and older client libraries still target
`evds2` and will fail. Verified 2026-09-08.

## Verified series codes used by this track

| Series | Code | Frequency | Source-declared default aggregation |
|---|---|---|---|
| Housing loan interest rate (flow, %) | `TP.KTF12` | Weekly (Friday) | Average |
| Residential property price index | `TP.KFE.TR` | Monthly | Average |
| USD buying rate | `TP.DK.USD.A.YTL` | Daily | Average |

Codes and their metadata come from EVDS's own series-list service; none was invented.

## Source anomalies

1. **`Tarih` has no single format.** `MM-DD-YYYY` for daily and weekly, `MM-YYYY` for monthly.
   Ambiguous for days 1–12 in isolation. Use `UNIXTIME` (epoch seconds, Istanbul local
   midnight) as the authoritative field.
2. **Values are strings.** `"18.61"`, not `18.61`. The decimal separator is caller-controlled
   through `decimalSeperator`.
3. **Nulls are JSON `null`.** Non-trading days appear as rows with a `null` value rather than
   being omitted. They must never be coerced to `0`.
4. **The response can exceed the requested end date.** A request for `endDate=30-06-2026`
   returned a final weekly observation dated `07-03-2026` (3 July 2026).
5. **Column names replace dots with underscores.** `TP.KFE.TR` becomes `TP_KFE_TR`. Lossy for
   codes containing a real underscore, so the request's series list is the mapping of record.
6. **Silent truncation at 1000 observations.** Requests must be windowed. The connector records
   `observation_limit` in the artifact metadata; the parser warns when the returned count
   reaches it. `OBSERVATION_COUNT_MISMATCH` is the shared error code for the upstream check.
7. `frequency` is a **conversion** request, not a filter: asking for daily data on a weekly
   series produces rows with `null` between publications.

## Secret handling

The API key is read only from an environment variable (`EVDS_API_KEY` by default, or the name
carried by `FetchSpec.headers_ref`). It is never written to code, fixtures, the artifact
locator, artifact metadata, logs, or exception messages. `.env` is git-ignored and
`.env.example` holds names only.

## Open items

- **The documented keyed endpoint has never been called live.** See "Verification status"
  above for exactly what is and is not verified, and for the smoke test to run once a key
  exists. `/fe` is a shape-discovery tool only and must not become a production fallback.
- The exact `Tarih` format for quarterly, semi-annual and yearly frequencies is unverified.
- No rate limit is documented. The guide only advises fetching once per day.
