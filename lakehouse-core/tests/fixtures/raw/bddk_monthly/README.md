# BDDK Monthly Bulletin RAW Fixtures

Small, secret-free excerpts of **real** BDDK responses. The endpoint needs no API key, no
session cookie and no antiforgery token, so these fixtures contain no credential of any kind —
only response bodies.

## How they were captured

Captured on **2026-09-08** from `https://www.bddk.org.tr` with a single unauthenticated call:

```
POST /BultenAylik/tr/Home/GelismisRaporGetir
Content-Type: application/x-www-form-urlencoded

baslangicYil=2021&baslangicAy=1&bitisYil=2026&bitisAy=6
&periyot=1&paraBirimi=TL&taraf=10001&kalemSutun=1534%3FToplam&gosterimTuru=grid
```

The live response contained **66 monthly rows** for 2021-01 … 2026-06. Only the row count was
reduced, to the three newest and the two oldest rows, and `data.records` was updated to match.
Column models, group headers and every kept value are exactly as BDDK returned them.

## Files

| File | What it is |
|---|---|
| `bddk_monthly_housing_loans.json` | Successful advanced report for item `1534` (`Tüketici Kredileri - Konut`), `taraf=10001` (Sektör), `paraBirimi=TL`. |
| `bddk_monthly_simple_report_basitfont.json` | **Evidence only — a different endpoint.** `POST /BultenAylik/tr/Home/BasitRaporGetir`, `tabloNo=4&yil=2026&ay=6&paraBirimi=TL&taraf=10001`, captured 2026-09-09. Trimmed from 41 rows to 6; nothing else changed. It proves that `BasitFont` marks these source display rows as bold on an endpoint the connector does **not** use; it is not treated as a universal subtotal rule. No parser consumes it. |
| `bddk_monthly_application_error.json` | Verbatim body returned when several `kalemSutun` values for the same concept are requested together. **HTTP status was 200.** The connector now rejects that combination before sending a request, so this fixture guards the parser's second line of defence. |

## Verified request codes

| Field | Value | Meaning |
|---|---|---|
| `kalemSutun` | `1534?Toplam` | Tüketici Kredileri → Konut, "Toplam" column |
| `taraf` | `10001` | Sektör |
| `paraBirimi` | `TL` | Turkish lira report |
| `periyot` | `1` | Monthly |
| `gosterimTuru` | `grid` | Tabular payload rather than chart payload |

None of these codes was invented; each was read from the BDDK advanced-report screen's own
form options.

## Source anomalies these fixtures encode

1. **HTTP 200 does not mean success.** `bddk_monthly_application_error.json` is a real 200
   response carrying `{"success": false, "error": "Gelişmiş Rapor üretilirken hata oluştu!"}`.
2. **Rows are positional.** `data.rows[i].cell` is an array that only has meaning when zipped
   against `colModels[*].name`.
3. **The unit is embedded in the column name.** The measure column is
   `"Tüketici Kredileri - Tüketici Kredileri - Konut (milyon TL)-Toplam"`; BDDK exposes no
   separate unit field. `colNames` shows only `"Toplam"`, so `colModels` is the field of record.
4. **Rows are newest first** (2026-06 … 2021-01), and BDDK ships its own rank in `Sira`.
5. **The grid declares `formatoptions.defaultValue = "0"`.** That is a *display* default in the
   BDDK UI, so an absent value can be rendered as zero there. The parser never substitutes a
   value and raises this as a warning instead.
6. **One concept can have several item ids.** The advanced screen offers
   `1534,288,219,238` for `Tüketici Kredileri - Konut`; these are per-schema-version ids.
   Requesting `1534` alone returns the full 2021-01 … 2026-06 range; requesting the group
   together triggers the `success:false` body above. Each id must therefore be fetched with its
   own `FetchSpec`.

## Golden values

From the live 66-row response, in `milyon TL`:

| Period | Value |
|---|---|
| 2021-01 | 276785 |
| 2026-06 | 801438 |

## Expected parser behaviour

`BddkMonthlyParser` reads only the local path and returns one row per (period, measure) pair
with `year_raw`, `month_raw` and `value_raw` kept verbatim. It performs no numeric casting, no
date construction, no unit conversion, no reordering and no aggregation.
