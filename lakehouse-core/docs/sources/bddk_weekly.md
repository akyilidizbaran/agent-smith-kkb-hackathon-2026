# Source: BDDK Weekly Bulletin (Haftalık Bülten)

`source_id`: `bddk_weekly`

## Verification status

| Item | Status | Evidence |
|---|---|---|
| Endpoint, method, field names, date format | **Verified live** 2026-09-09 | Successful `POST` returning a 674-byte JSON series |
| No auth / no cookie / no antiforgery token | **Verified live** | A cookie-less client that had never loaded any page received a byte-identical successful response |
| `id`, `parabirimi`, `sutun`, `tarafKodu` values | **Verified live** | `1.0.4` / `TRY` / `3` / `10001` returned `a) Konut (TRY) [Toplam]` |
| Stable item id `5690` | **Verified from page source** | `KalemToggle(5690, 'a) Konut')` and `id="Kalem-5690"` in the item tree |
| `5690` → `1.0.4` mapping | **Observed once, not proven stable** | Read out of one rendered report; see "Confirmation required" |
| Unresolved item and empty range behaviour | **Verified live** | Two real HTTP 200 responses, both captured as fixtures |
| Unit of the selected series | **Verified from the official table header** | `https://www.bddk.org.tr/BultenHaftalik/` renders `Krediler` / `Sektör` / `Tarih: … | Birim: **Milyon TL**`, and `a) Konut` is a row of that table |
| Unit inside the JSON payload | **Confirmed absent** | `KiyaslamaJsonGetir` carries no unit field; `(TRY)` in `Baslik` is the currency leg |
| Production connector against the live endpoint | **Verified live** 2026-09-08 | `BddkWeeklyConnector` + real `requests.Session`, full 2021-01-01 … 2026-06-26 range: HTTP 200, `application/json`, 6807 bytes, 286 observations |
| Connector retry / clock / storage branches | **Verified by test only** | Fake in-process session; no socket is opened |
| TLS chain served by `www.bddk.org.tr` | **Verified live — incomplete** | The server sends only the leaf certificate; see "Operational blocker" |
| Revision / historical restatement behaviour | ❌ **Not verified** | Not observed in this round |

Real requests were kept to a minimum: nine during endpoint discovery (two page GETs, two
report POSTs, five JSON POSTs), then one bulletin page GET plus one successful production
connector call during the live smoke test — and one connector call that failed on TLS before
it ever reached the application.

### Live smoke test result (2026-09-08)

Production `BddkWeeklyConnector` with a real `requests.Session`, RAW storage in a temporary
directory outside the repository, no fake session:

| | |
|---|---|
| Request | `id=1.0.4`, `kalem_id=5690`, `parabirimi=TRY`, `sutun=3`, `tarafKodu=10001`, `2021-01-01` … `2026-06-26` |
| HTTP status / media type | `200` / `application/json` |
| Response size | 6807 bytes |
| Observations | **286**, no nulls, no parser warnings |
| Coverage | asked from `2021-01-01`, first published week returned is `8.01.2021` = `277871.046`; last is `26.06.2026` = `800464.007` |
| Years present | 2021 – 2026 |
| `series_id` | `bddk_weekly:5690_3` |
| RAW SHA-256 | `e53284e98eedff0897d7ab4bf39948f08b72fa3930accba01afd1b1561ef148a` |
| `kalem_id` on the wire | no — metadata only, as designed |

The live value for `26.06.2026` is `800464.007`, identical to the committed fixture, which
cross-validates the fixture against the source.

**Headers were sufficient as they are.** The call succeeded with the connector's existing
`X-Requested-With` and `Accept` headers and the stock `python-requests/2.34.2` User-Agent, with
**no `Referer`** and no cookie. No WAF, bot-check or rate-limit response was observed, so no
header was added.

## Verified endpoint contract

BDDK publishes no API documentation for this path. The contract below was read from the
advanced-report screen at `/BultenHaftalik/tr/Gelismis` and confirmed by real calls.

| Item | Value |
|---|---|
| Host | `https://www.bddk.org.tr` |
| Time-series endpoint | `POST /BultenHaftalik/tr/Gelismis/KiyaslamaJsonGetir` |
| HTML report (fallback) | `POST /BultenHaftalik/tr/Gelismis/GelismisRaporGetir` |
| Authentication | **None.** No API key, no antiforgery token, **no session cookie.** |
| Encoding | `application/x-www-form-urlencoded` |
| Response | `application/json; charset=utf-8` |

### Form fields

| Field | Verified value | Notes |
|---|---|---|
| `dil` | `tr` | Language |
| `baslangicTarihi` | `2.01.2026 00:00:00` | `d.MM.yyyy HH:mm:ss`, **day is not zero-padded** |
| `bitisTarihi` | `26.06.2026 00:00:00` | Same format |
| `id` | `1.0.4` | **Positional chart address**, not the stable item id |
| `parabirimi` | `TRY` | Not `TL` |
| `sutun` | `3` | Numeric. `3` returned `[Toplam]`; `TP`/`YP` codes are unverified |
| `tarafKodu` | `10001` | Sektör. Same party codes as the monthly bulletin |

### This is not the monthly contract

The weekly endpoint was verified independently rather than assumed to match
`docs/sources/bddk_monthly.md`. Every one of these differs:

| Concern | Monthly | Weekly |
|---|---|---|
| Date input | `baslangicYil` / `baslangicAy` integers | one `baslangicTarihi` string, day not padded |
| Currency field | `paraBirimi` = `TL` | `parabirimi` = `TRY` |
| Column selector | inside `kalemSutun` as `1534?Toplam` | separate numeric `sutun` = `3` |
| Item address | stable item id `1534` | positional chart id `1.0.4` |
| Party field | `taraf`, repeatable | `tarafKodu`, single |
| Response | `{"success":…, "Json":{colModels, data.rows}}` | `{"Baslik", "XEkseni", "YEkseni"}` |
| Row order | newest first | **oldest first** |
| Failure signal | `success: false` | placeholder title + empty arrays |

The monthly connector's "exactly one `kalemSutun` per FetchSpec" rule was **not** carried over
as a rule. The weekly connector accepts one value per single-valued field because the
application's own `VeriGetir` sends each field exactly once, and because nothing was observed
about repeated values. Refusing them locally avoids guessing against the live source.

## Selected series

**Krediler → Toplam Krediler → Tüketici Kredileri → a) Konut**, Sektör, Toplam column, TL.

This is the first-choice concept from the task, and it does exist in the weekly bulletin, so no
fallback was needed.

| Identifier | Value | Kind |
|---|---|---|
| Stable native item id | `5690` | From `KalemToggle(5690, 'a) Konut')` / `id="Kalem-5690"`. **Mandatory** in the `FetchSpec`; never sent on the wire |
| Wire chart id | `1.0.4` | Positional; what the endpoint actually addresses |
| Party | `10001` | Sektör |
| Column | `3` | Resolved to `Toplam` by the service |
| Currency | `TRY` | |

`series_id` is built from the **stable** id: `bddk_weekly:5690_3`. `kalem_id` is a **required**
`FetchSpec` parameter even though the endpoint has no such field — it is validated, kept out of
the request body, and recorded in artifact metadata as the verified source identity. The
positional chart id is carried alongside as data and is **never** an identity fallback: a
request without exactly one `kalem_id` is refused before any HTTP call, and an artifact whose
metadata lacks `requested_kalem_id` fails the parser with `SCHEMA_MISMATCH`.

Beware: there is a **second `a) Konut`** in the tree, item `5867`, under *Takipteki Alacaklar*
(non-performing loans). `5690` is the loan balance. The Turkish labels are identical.

## Source anomalies

1. **Two parallel arrays, not records.** `XEkseni` and `YEkseni` are linked only by position.
   The parser treats a length mismatch as `SCHEMA_MISMATCH` rather than zipping and truncating.
2. **Oldest first**, the opposite of the monthly grid.
3. **Weeks are not evenly spaced.** The live series steps `13.03.2026 → 19.03.2026 →
   27.03.2026`, i.e. 6 days then 8. Any weekly-frequency assumption downstream must handle
   this; the parser regularizes nothing.
4. **HTTP 200 does not mean success, and there is no `success` flag.** An unresolved chart id
   returns `{"Baslik":"Grafik Başlığı","XEkseni":[],"YEkseni":[]}`. The connector stores that
   faithfully; the parser rejects it as `SOURCE_UNAVAILABLE` (not retryable — the id is wrong).
5. **An empty range looks almost the same** but keeps the real title:
   `{"Baslik":"a) Konut (TRY) ","XEkseni":[],"YEkseni":[]}`. The title is the only signal that
   separates the two, so the parser distinguishes them and raises `EMPTY_DATASET` here.
6. **The unit is published on the table, not in the payload.** The official weekly bulletin
   page states `Birim: Milyon TL` in the `Krediler` / `Sektör` table header, and `a) Konut` is
   a row of that table — so the unit of the selected series **is** known: **milyon TL**. What
   is absent is any unit *field in the JSON*: `KiyaslamaJsonGetir` returns only `Baslik`,
   `XEkseni` and `YEkseni`, and the `(TRY)` inside `Baslik` is the **currency leg**, not the
   magnitude. The HTML report header's `TOPLAM (TL)` is likewise a currency. The parser
   therefore produces no unit column, because it may only report what the payload contains.
   A later Silver mapping may apply `unit = milyon TL` on the strength of the official table
   header, which is source evidence rather than an inference.
7. **The chart payload is unrounded where the screen is rounded.** It returns `800464.007`
   where the HTML report displays `800.464` (Turkish thousands separator, rounded).
8. **The JSON's decimals are not extra precision over the bulletin.** The published table is
   in milyon TL, so `800464.007` is milyon TL with three decimals while the report screen
   renders the rounded `800.464`. The RAW artifact is the exact response bytes; the parser's
   `value_raw` is the Python numeric value of that JSON number, which is a `float` and carries
   the usual binary floating-point representation limits.
9. **Three spellings of currency in one application**: `parabirimi=TRY` on this endpoint,
   `SeciliParalar=TL` on the report form, `paraBirimi=TL` on the monthly endpoint.
10. **The `sutun` field is numeric here** (`3` = Toplam) but a word in the report form
    (`kalemSutun=Toplam`).

## Confirmation required

1. **Where the unit may be applied.** The unit itself is settled: the official table header
   says `Birim: Milyon TL`. What remains a decision rather than an unknown is *where* it is
   attached. It is not in the JSON, so the parser does not emit it; a Silver mapping should
   attach `unit = milyon TL` citing the table header. The monthly bulletin's `801438` milyon TL
   for 2026-06 against this series' `800464.007` for `26.06.2026` is a **consistency check
   only** — different reference dates, and magnitude agreement is not evidence of a unit.
2. **`5690 → 1.0.4` mapping stability.** The chart id is positional and was read from one
   rendered report. If BDDK reorders the bulletin, `1.0.4` may address a different line while
   `5690` still means Konut. There is no verified lookup endpoint for this mapping. Until one
   exists, the chart id must be supplied by the caller and re-checked when the bulletin layout
   changes.
3. **`sutun` codes for TP and YP.** Only `3` (Toplam) was exercised. `1`/`2` are a guess and
   were not sent.
4. **Revisions.** BDDK's weekly-bulletin explanation states that previously published values
   can be updated in later releases, but no restatement was observed in this round, so no
   revision-detection behaviour is claimed.
5. **Rate limiting.** No documented limit and none encountered in nine requests. The connector
   applies backoff on 408/429/5xx but no proactive throttle.
6. **Full history depth — resolved.** The full `2021-01-01 … 2026-06-26` range was fetched
   live in one call and returned 286 observations across 2021–2026, so no windowing is needed
   at this depth. A request that starts before the first published week is clamped forward to
   it (`2021-01-01` → `8.01.2021`) rather than erroring.

## Operational blocker: incomplete TLS chain

`www.bddk.org.tr` presents **only its leaf certificate** and omits the
`GlobalSign RSA OV SSL CA 2018` intermediate. `openssl s_client` reports
`Verify return code: 21 (unable to verify the first certificate)`.

Browsers and `curl` paper over this by chasing the certificate's AIA extension or by reusing a
cached intermediate. Python's `ssl` module does **not**, so a plain `requests` call fails with
`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`. The GlobalSign *root* is in
`certifi`; the missing link is the intermediate, which `certifi` correctly does not ship.

This is a **source-side misconfiguration**, not a local quirk, not a WAF block and not
something the connector can fix. It applies identically to `BddkMonthlyConnector`, which has
simply never been exercised against the live host.

The smoke test resolved it **without weakening verification** by handing the connector a
`requests.Session` whose `verify` points at `certifi` roots plus the intermediate published at
the `caIssuers` URI inside BDDK's own certificate
(`http://secure.globalsign.com/cacert/gsrsaovsslca2018.crt`). Certificate verification stayed
on throughout.

**This is deployment configuration, not connector code, and it is deliberately not implemented
in this track.** It is a shared operational decision: the deployment should either ship that
intermediate in the container's CA bundle or supply a pre-configured session. Disabling
verification is not an acceptable answer. `BddkWeeklyConnector` accepts an injected `session`,
so no code change is required once the team decides.

**The connector's error classification for this case is worth reviewing.** A TLS trust failure
surfaces as `requests.RequestException` and is currently reported as `SOURCE_UNAVAILABLE` with
`retryable=True`. Retrying will never succeed, so `retryable=False` would be more accurate —
but distinguishing TLS failures from genuinely transient connection errors is a shared
classification decision, so it was left unchanged here rather than altered unilaterally.

## Not implemented in this track

- The HTML report transport. Its path is recorded in artifact metadata as
  `html_report_fallback_path` so a later track can switch transport without changing the
  contract. It returns the same numbers inside a ~490 KB page and **does** require an
  antiforgery token plus a session cookie, obtained from `GET /BultenHaftalik/tr/Gelismis` and
  posted with `Kalemler`, `Taraflar`, `kalemSutun`, `SeciliParalar`, `BaslangicTarihi`,
  `BitisTarihi`, `dil`.
- Any other weekly item, party, currency or column.
- Any Bronze/Silver/Gold semantics: no `date_key`, no Friday anchoring, no frequency
  alignment, no `measure_type`, no unit conversion.

## Chart-id drift guard

`id=1.0.4` is a **positional** chart address. If BDDK reorders the bulletin, the same `id` can
return a different line and the HTTP exchange gives no sign of it: status 200, same envelope,
plausible numbers, wrong series. The only in-band evidence of *which* series came back is
`Baslik`.

The `FetchSpec` therefore carries three expectations alongside `kalem_id`:

| Parameter | Value for this series |
|---|---|
| `expected_measure_label` | `a) Konut` |
| `expected_currency` | `TRY` |
| `expected_column` | `Toplam` |

They are **never sent on the wire** — the endpoint has no such fields — and are recorded in
artifact metadata. After parsing `Baslik`, the parser compares each against what the response
actually said.

- The comparison is **deterministic**: exact equality after collapsing internal whitespace and
  trimming. No case folding, no fuzzy or model-based matching — a near-match would defeat the
  check.
- Any mismatch is `SCHEMA_MISMATCH` with `retryable=False`.
- A title that does not parse into the observed `<label> (<currency>) [<column>]` shape is
  also rejected: unparseable means unverifiable.
- All three expectations are **mandatory** in this narrow V1 connector. A request that cannot
  state what it expects cannot be checked, and an unchecked positional address is precisely
  the failure being guarded against. A missing or blank expectation is `SCHEMA_MISMATCH`.
- `1.0.4` is never a `series_id` source under any circumstance; `series_id` comes only from
  the stable `kalem_id`.

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
