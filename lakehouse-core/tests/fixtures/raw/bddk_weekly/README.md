# BDDK Weekly Bulletin fixtures

Real responses from `https://www.bddk.org.tr`. No secrets, no cookies, no tokens, no personal
data — this endpoint requires none of them.

## How they were captured

Captured on **2026-09-09** with a plain `POST` to:

```
https://www.bddk.org.tr/BultenHaftalik/tr/Gelismis/KiyaslamaJsonGetir
```

Headers: `Content-Type: application/x-www-form-urlencoded; charset=UTF-8`,
`X-Requested-With: XMLHttpRequest`, `Accept: application/json`, a descriptive `User-Agent`,
and `Referer: https://www.bddk.org.tr/BultenHaftalik/tr/Gelismis`. **No cookie and no
antiforgery token were sent** — verified by issuing the request from a client that had never
loaded any page and receiving a byte-identical successful response.

| File | Request body | Server response |
|---|---|---|
| `bddk_weekly_housing_loans.json` | `dil=tr`, `baslangicTarihi=2.01.2026 00:00:00`, `bitisTarihi=26.06.2026 00:00:00`, `id=1.0.4`, `parabirimi=TRY`, `sutun=3`, `tarafKodu=10001` | HTTP 200, 674 bytes, 26 observations |
| `bddk_weekly_unknown_item.json` | same, but `id=99.9.99` | HTTP 200, **57 bytes** |
| `bddk_weekly_empty_range.json` | same, but `baslangicTarihi=bitisTarihi=2.01.2027 00:00:00` | HTTP 200, **54 bytes** |

## What was changed

`bddk_weekly_unknown_item.json` and `bddk_weekly_empty_range.json` are **verbatim**. Their byte
lengths were checked against the lengths the server reported (57 and 54) and match exactly.

`bddk_weekly_housing_loans.json` is the real response with **only the observation count
reduced**, from 26 to 5. Field names, the envelope, value formats and ordering are untouched.
Both arrays were trimmed at the same indices so they stay parallel.

Kept indices `[0, 10, 11, 12, 25]` of the original 26 — the first and last observation plus the
three-point run that shows the irregular week spacing:

| Original index | `XEkseni` | `YEkseni` |
|---|---|---|
| 0 | `2.01.2026` | `679216.118` |
| 10 | `13.03.2026` | `731311.768` |
| 11 | `19.03.2026` | `734860.422` |
| 12 | `27.03.2026` | `740789.871` |
| 25 | `26.06.2026` | `800464.007` |

No value was edited, added, rounded or invented. JSON separators match the server's compact
output (`,` and `:` without spaces).

## What these fixtures show

1. **Two parallel arrays.** `XEkseni` and `YEkseni` are linked only by position.
2. **Oldest first**, unlike the monthly bulletin's grid.
3. **Irregular week spacing.** `13.03 → 19.03 → 27.03` is 6 days then 8, not 7 and 7. This is
   why indices 10–12 were kept.
4. **Dates are raw `d.MM.yyyy` strings with a non-padded day** (`2.01.2026`).
5. **Unrounded values** (`800464.007`), where the HTML report shows the rounded `800.464`.
   The fixture bytes are exact; once parsed, `value_raw` is the Python `float` for that JSON
   number.
6. **No unit *field*.** `(TRY)` in `Baslik` is the currency leg, not the magnitude. The unit
   itself is published on the official page — the `Krediler` / `Sektör` table header at
   `https://www.bddk.org.tr/BultenHaftalik/` reads `Birim: Milyon TL`, and `a) Konut` is a row
   of that table. So the series **is** in milyon TL; that fact simply does not travel inside
   this payload, which is why the parser emits no unit column.
7. **HTTP 200 with no `success` flag.** An unresolved item returns the placeholder title
   `Grafik Başlığı` with empty arrays; an empty range returns the *real* title with empty
   arrays. The title is the only thing that separates the two conditions.

## Not represented here

No live response containing a JSON `null` value was observed, so **no fixture contains one**.
The parser's null-preservation guard is proven instead by a small synthetic payload written
inline in `tests/parsers/test_bddk_weekly_parser.py`, which is deliberately kept out of this
directory and labelled synthetic in the test.

The same applies to unparallel arrays and to a title outside the observed shape: those code
paths are exercised by clearly-labelled synthetic payloads, not by fabricated fixtures.

## Verified codes

| Concept | `id` (wire) | `kalem_id` (stable, metadata only) | `tarafKodu` | `sutun` | `parabirimi` | Unit |
|---|---|---|---|---|---|---|
| Krediler → Tüketici Kredileri → a) Konut | `1.0.4` | `5690` | `10001` (Sektör) | `3` (Toplam) | `TRY` | milyon TL, from the official table header |

`kalem_id` is required by the connector and is **never** part of the request body; it is
recorded in artifact metadata as the verified source identity and is the only accepted source
of `series_id`.

`5867` is a **different** `a) Konut`, under *Takipteki Alacaklar*. The labels are identical.

## Cross-validated against the live source

On 2026-09-08 the production connector fetched the full `2021-01-01 … 2026-06-26` range live
(286 observations). Its value for `26.06.2026` is `800464.007` — identical to this fixture's
last observation, and `2.01.2026` = `679216.118` likewise matches. The fixture therefore still
represents the real response.

See `docs/sources/bddk_weekly.md` for the full contract, anomalies, the live smoke-test result
and the open TLS-chain blocker.
