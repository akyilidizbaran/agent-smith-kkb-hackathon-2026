# EVDS RAW Fixtures

Small, secret-free excerpts of **real** EVDS3 responses. They contain no API key, no
`Authorization` header, and no request headers of any kind — only response bodies.

## How they were captured

Captured on **2026-09-08** from `evds3.tcmb.gov.tr`. The envelope, field names, value types and
date shapes are exactly as the service returned them. Only the number of observations was
reduced, and `transposedItems` / `transposedColumns` were trimmed to stay consistent with the
kept observations. No value was edited, added, or invented.

> **These fixtures do not come from the official endpoint.** The capture used the EVDS3 web
> application's own `POST /igmevdsms-dis/fe` endpoint, which needs no API key and is **not**
> described in the official *EVDS Web Servis Kılavuzu*. It was used **only to learn the
> response shape** and must **never** be used as a production transport or fallback.
>
> The connector calls the documented, key-authenticated
> `GET /igmevdsms-dis/series=...&type=json` endpoint exclusively. Both endpoints are served by
> the same EVDS3 backend under the same `type=json` contract, so the envelope is *expected* to
> be identical — but **the official keyed endpoint has never been called live**, because no API
> key was available. Passing tests prove parser behaviour against these captures, not that the
> official endpoint returns this shape.
>
> `docs/sources/evds.md` holds the full verification-status table and the narrow live smoke
> test to run once a key exists. Re-capture from the documented endpoint then, and replace
> these files if anything differs.

## Files

| File | Series | Frequency | Why it exists |
|---|---|---|---|
| `evds_ktf12_weekly.json` | `TP.KTF12` — Housing Loans (TRY) (Flow, %) | Weekly (`frequency=3`) | Primary happy path. Includes the trailing observation that falls **after** the requested end date. |
| `evds_kfe_monthly.json` | `TP.KFE.TR` — Residential Property Price Index | Monthly (`frequency=5`) | Proves `Tarih` uses a different shape per frequency. |
| `evds_usd_daily_with_nulls.json` | `TP.DK.USD.A.YTL` — USD buying rate | Daily (`frequency=1`) | Real JSON `null` values on non-trading days. |

## Response shape

```json
{
  "totalCount": 5,
  "items": [
    {"Tarih": "01-01-2021", "YEARWEEK": "2021-1",
     "TP_KTF12": "18.61", "UNIXTIME": {"$numberLong": "1609455600"}}
  ],
  "transposedItems": [...],
  "transposedColumns": [...],
  "seriesNames": {"TP_KTF12": "Housing Loans (TRY) (Flow, %)"},
  "frequencyConversion": {"TP.KTF12": true}
}
```

## Source anomalies these fixtures encode

1. **`Tarih` has no single format.** Weekly and daily responses use `MM-DD-YYYY`
   (`01-15-2021` is 15 January 2021); monthly responses use `MM-YYYY`. For days 1–12 the value
   is ambiguous on its own. `UNIXTIME` is the unambiguous field and is epoch seconds at
   Istanbul local midnight.
2. **Values are strings, not numbers** (`"18.61"`), and the decimal separator is chosen by the
   request's `decimalSeperator` parameter.
3. **Missing observations are JSON `null`**, not `0` and not an omitted row.
4. **The response can exceed the requested range.** `evds_ktf12_weekly.json` ends at
   `07-03-2026` although the request asked for `endDate=30-06-2026`.
5. **Series codes are rewritten in column names**: `TP.KFE.TR` becomes `TP_KFE_TR`. This is
   lossy for any code that contains a real underscore, so the parser prefers the requested
   codes recorded in `FetchedAsset.metadata["requested_series"]`.

## Expected parser behaviour

`EvdsParser` reads only the local path and returns one row per (observation, series) pair with
`date_raw`, `unixtime` and `value_raw` kept verbatim. It performs no numeric casting, no date
normalization, no frequency conversion, and no aggregation.
