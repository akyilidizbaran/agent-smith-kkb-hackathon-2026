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
| **Official keyed endpoint, successful live data** | **LIVE_NOT_VERIFIED** | Prior diagnostics on 2026-09-11 returned HTTP 401 with the available credential; no successful authenticated data response was obtained. No authentication diagnostics were repeated in Phase 3.3A. |
| **`TP.FG.J0` (TÜFE) response, live or captured** | **CAPTURED LIVE** 2026-09-11 | `tests/fixtures/raw/evds/evds_cpi_monthly_live_keyed.json`, from the documented key-authenticated endpoint — see "Live keyed capture" below. `tests/integration/test_evds_cpi_silver.py` still uses its synthetic payload, so gate step 4 is open |
| **`TP.FG.J0` reference/base (`2003=100`)** | **VERIFIED_PUBLIC** | TCMB-hosted Central Bank Review appendix explicitly maps the code to general CPI (2003=100); corroborated by public EVDS listing and TÜİK methodology below. This is not live API evidence. |
| **`TP.FG.J0` values against a published figure** | **AGREES** 2026-09-11 | Year-on-year change computed from the live response reproduces TÜİK's published December headline inflation exactly: 2023-12 **64,77%**, 2024-12 **44,38%**. This is a consistency check on the captured values, not a substitute for gate step 4. |

### What this means in practice

- `POST /igmevdsms-dis/fe` is an **undocumented internal endpoint of the EVDS web application**.
  It was used **only to learn the response shape**. It must **not** be used as a production
  transport or as a fallback: it is unversioned, unsupported, may change without notice, and
  using it would route production traffic through an interface TCMB does not publish for
  integration. The connector calls the documented keyed endpoint exclusively.
- The two endpoints are served by the same EVDS3 backend and take the same `type=json`
  contract, so the envelope is **expected** to be identical — but that is an expectation, not a
  measurement.

### `TP.FG.J0` (TÜFE) — what is and is not established

The series is **catalogued and mapped**, and the generic EVDS connector, parser and Silver
adapter carry it end to end with no source-specific code
(`tests/integration/test_evds_cpi_silver.py`). That is a statement about *this repository's
code*, proved with synthetic bytes.

Public evidence reviewed on **2026-09-11** establishes the historical native code, general
CPI identity and 2003=100 reference. Monthly publication and index nature are supported by
TÜİK documentation. TÜİK produces the statistics; TCMB distributes them through EVDS.
The catalog now uses `semantic_source: source_docs`, while `semantic_confidence: derived`
is retained. `default_agg: last` is a project policy, not a verified provider default.
Catalog `status: active` is retained as project configuration; it does not prove that this
native code remains actively updated by the provider.

The prior production request returned HTTP 401 with the available credential. This does
**not** establish that the series or endpoint semantics are wrong. Authenticated EVDS3
live API response was NOT verified in this environment: exact envelope, live field names,
values and Connector -> Parser compatibility remain unverified.

#### Public evidence and retrieval limits

- **P1: [EVDS public series navigation](https://evds3.tcmb.gov.tr/tumSeriler/3003/bie_mbblnca)**:
  the indexed first-party page lists "Tüketici Fiyat Endeksi (Genel) (2003=100)"
  under TÜİK CPI, alongside a 2025=100 group. This is navigation on another group's
  page, not native-code metadata. Direct text retrieval returned a JavaScript shell;
  the indexed label corroborates identity, but does not establish active/archived status.
- **P2: [TÜİK CPI calculation explanation](https://data.tuik.gov.tr/Bulten/DownloadFile?p=e57pu%2FoqllLLsPnCJ%2FWfZBbWEES14WLyBBzOSfPLheutBKMQ72Flp%2FSc3W8IItrFMn7J3h2YyHL0XrBe1T9AblCZzd2Dq8C2hMJuRPE18x0%3D)**:
  indexed official text describes the 2003=100 CPI as a chained index with annual
  basket/weight updates. Direct retrieval redirects to the TÜİK JavaScript portal.
  The public download identifier is not an authentication token. This historical
  methodology does not imply that every currently published CPI uses this reference.
- **P3: [Şahin and Ülke, Central Bank Review 15(1), 2015, pp. 65-93](https://www.tcmb.gov.tr/wps/wcm/connect/8cd1b17c-73fc-4552-ae36-2aa7c9cf170a/Jan15-4.pdf?CACHEID=ROOTWORKSPACE-8cd1b17c-73fc-4552-ae36-2aa7c9cf170a-m3fw4IA&MOD=AJPERES)**:
  directly retrieved PDF, printed p. 85 (PDF page 21), Appendix A, Table A1,
  price row maps `TP.FG.J0: 0.GENEL` to post-2003 CPI (2003=100), sourced from EVDS.
  This TCMB-hosted research publication is historical evidence, not a current API
  specification or institutional endorsement of its authors' views. Its abstract
  identifies a monthly sample; section 3 inconsistently calls the price variable PPI,
  so the explicit appendix mapping is used together with P1/P2, not that prose alone.
- **P4: [TÜİK August 2019 CPI bulletin and metadata](https://data.tuik.gov.tr/Bulten/Index?p=Tuketici-Fiyat-Endeksi-Agustos-2019-30856)**:
  indexed official text distinguishes index levels from percentage changes, identifies
  TÜİK as processor, and describes monthly release of results. Direct retrieval requires
  JavaScript after redirect. This supports monthly CPI semantics, not present-day API fields.

All four references were independently checked through first-party public content or its
indexed text on 2026-09-11. No third-party financial interpretation is used. Retrieval date
is not publication date; search-engine relative dates are not adopted as source dates.
See [the evidence matrix and confidence decision](../branches/evds-cpi-semantic-evidence.md).

**To raise it to `verified`, this is what has to arrive:**

1. One real keyed-endpoint response for `TP.FG.J0` over a short range, committed as a fixture
   under `tests/fixtures/raw/evds/` with **no key in the bytes, the filename or the metadata**.
2. The request URL and the capture date recorded in this document.
3. Base-year evidence from a TCMB/TÜİK source, cited here — not inferred from the values.
   **Public portion completed in Phase 3.3A**, as documented above.
4. `tests/integration/test_evds_cpi_silver.py` re-pointed at that fixture, with the synthetic
   payload deleted rather than kept alongside it.

The public reference/base may now be stated with the scope above. The existing promotion
gate is unchanged: public semantics do not substitute for steps 1, 2 and 4 or establish
current provider status.

### Live keyed capture (2026-09-11) — gate steps 1 and 2 are now met

A working `EVDS_API_KEY` became available and the documented endpoint was called for real.

| | |
|---|---|
| Endpoint | `GET https://evds3.tcmb.gov.tr/igmevdsms-dis/series=TP.FG.J0&startDate=01-01-2021&endDate=30-06-2026&type=json` (key passed as a header, never in a committed file) |
| Captured | 2026-09-11 |
| HTTP status | 200, `application/json` |
| Observations returned | 61 (2021-01 … 2026-01) |
| Fixture | `tests/fixtures/raw/evds/evds_cpi_monthly_live_keyed.json` — four observations, response body only, no key in the bytes, the filename or the metadata |
| Known-value agreement | Year-on-year from the captured index: 2023-12 → **64,77%**, 2024-12 → **44,38%**, matching TÜİK's published December headline inflation |
| Index level | 2021-01 = 513,30 and 2023-12 = 1.859,38, consistent with the `2003=100` reference established from public sources above |

Two contract differences from the web-application captures were found in the same call and
apply to every EVDS series, not only this one — monthly `Tarih` is `2021-1` rather than
`01-2021`, and `seriesNames` is absent entirely. Both are recorded in
`tests/fixtures/raw/evds/README.md`; the Silver mapping now reads the date from `UNIXTIME`
(`src/lakehouse/silver/adapters/_evds_time.py`).

**What is still open:** gate step 4 — `tests/integration/test_evds_cpi_silver.py` has to be
re-pointed at this fixture with the synthetic payload deleted rather than kept beside it.
Until then `semantic_confidence` stays `derived`, and a presentation must not call this series
live-provider-verified.

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

- **Successful authenticated data from the documented keyed endpoint remains unverified.**
  Prior requests returned HTTP 401; see "Verification status" and the pending smoke test.
  `/fe` is a shape-discovery tool only and must not become a production fallback.
- The exact `Tarih` format for quarterly, semi-annual and yearly frequencies is unverified.
- No rate limit is documented. The guide only advises fetching once per day.

## Küratörlü ek (2026-09-13): kur, faiz, mevduat faizi, kart harcaması, para arzı, TÜFE

`catalog/series/evds.yml` üretilen bloğun altına elle yazılmış 8 giriş eklendi; TÜFE genel
endeksi (`TP.TUKFIY2025.GENEL`) üretilmiş girdi olarak duruyordu, semantiği küratörlü yapıldı.
Kanıt: EVDS'nin kendi `/datagroups/mode=0` ve `/serieList/fe/type=json&code=<grup>` yanıtları
(13 Eylül, `EVDS_API_KEY` ile). Frekans `FREQUENCY_STR`'den, birim veri grubunun `BIRIMI`
alanından; ölçüm tipi ve indirgeme kuralı serinin adından ve tanımından (oran → avg,
stok → last, akım → sum).

| Seri | Veri grubu | FREQUENCY_STR | BIRIMI | Katalog |
|---|---|---|---|---|
| TP.DK.USD.A.YTL, TP.DK.EUR.A.YTL | bie_dkdovytl Döviz Kurları | GÜNLÜK | Türk lirası | daily, TRY, rate, avg |
| TP.BISPOLFAIZ.TUR | bie_bispolfaiz Merkez Bankaları Politika Faiz Oranı | AYLIK | Yüzde | monthly, pct, rate, avg |
| TP.APIFON4 | bie_apifon TCMB Net Fonlaması ve AOFM | İŞ GÜNÜ | milyon TL ve yüzde (bu seri yüzde) | business_daily, pct, rate, avg |
| TP.TRY.MT02 | bie_mt100h Mevduat Faiz Oranları (Akım) | HAFTALIK(CUMA) | Ağırlıklı ortalama | weekly/friday, pct, rate, avg |
| TP.KKHARTUT.KT1 | bie_kkhartut Kart Harcama Tutarı (Akım) | HAFTALIK(CUMA) | bin TL | weekly/friday, TRY_th, flow_periodic, sum |
| TP.HPBITABLO1.11, .18 | bie_hpbitablo1 Para Arzı (M2, M3) | HAFTALIK(CUMA) | bin TL | weekly/friday, TRY_th, stock, last |
| TP.TUKFIY2025.GENEL | bie_tukfiy2025 TÜFE (2025=100) | AYLIK | (boş) | monthly, index, index, last |

Alınmayan: `bie_kt100h`/`bie_kt210a` kredi faizlerinin diğer serileri (üretilmiş blokta
`unknown` olarak duruyor; TP.KTF12 küratörlü), TLREF (`bie_bisttlref`), rezervler.

## TÜFE 2025=100 küratörlüğü (14 Eylül 2026)

`evds:TP.TUKFIY2025.GENEL` otomatik üretilmiş adıyla ("Genel Endeks", etiket `konut`) katalogdaydı. Ölçülen
sonuç (agent canlı prova, 14 Eylül): "enflasyondan arındır" isteğinde arama bu seriyi bulamadı, model yüklü
olmayan `TP.FG.J0`'ı seçti ve "TÜFE yüklenmemiş" dedi. Birim/ölçüm tipi/baz zaten yukarıdaki tabloda
(`bie_tukfiy2025 TÜFE (2025=100)`, monthly, index) kayıtlıydı; bu küratörlük yalnız **ad, açıklama, takma ad
ve etiketleri** düzeltir, veriyi değiştirmez. Seri 2025 öncesini de 2025=100 bazında taşır (2021-01 = 16,13).
`TP.FG.J0` (2003=100) ile birleştirme (splice) yapılmaz: iki baz arasında dönüşüm katsayısı kaynakta
yayınlanmadıkça ikisi ayrı seri olarak kalır.
