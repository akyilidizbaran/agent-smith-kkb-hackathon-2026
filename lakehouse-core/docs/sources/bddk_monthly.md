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

## Genişletme (2026-09-13): 19 kalem daha, hepsi canlı doğrulandı

Kalem ağacı `/BultenAylik/tr/Home/Gelismis` sayfasının HTML'indeki `<optgroup>`/`<option>`
listesinden okundu (option `value` virgüllü kimlik listesidir; ilk kimlik Sektör tarafının
kararlı kalem kimliğidir, `1534,288,219,238` → `1534`). Her kalem için `GelismisRaporGetir`
2025-12 tek dönem, `taraf=10001`, `paraBirimi=TL`, `gosterimTuru=grid` ile çağrıldı; yanıtın
kendi kolon başlığı birimi taşır (`"(milyon TL)"` ya da `"(%)"`), bu yüzden birim payload'dan
değil başlıktan okunur. Rasyolar ve KOBİ kalemlerinde sütun `Toplam` değildir:
`KalemSutunGetir?kalemNoList=<id>` sütun adını verir (`544?Rasyo`, `334?NakdiKrediTp` …).
KOBİ kalemi bu turda alınmadı (hangi sütunun toplam olduğu doğrulanmadı).

| Kalem | `kalemSutun` | Yanıt kolon başlığı | 2025-12 değeri |
|---|---|---|---|
| Tüketici Kredileri | `1533?Toplam` | `Tüketici Kredileri - Tüketici Kredileri (milyon TL)-Toplam` | **2939960** |
| Taşıt | `1535?Toplam` | `Tüketici Kredileri - Tüketici Kredileri - Taşıt (milyon TL)-Toplam` | **52044** |
| İhtiyaç | `1536?Toplam` | `Tüketici Kredileri - Tüketici Kredileri - İhtiyaç (milyon TL)-Toplam` | **2208946** |
| Bireysel Kredi Kartları | `1539?Toplam` | `Tüketici Kredileri - Bireysel Kredi Kartları (milyon TL)-Toplam` | **2804381** |
| Toplam Tük.Krd.+BKK | `1543?Toplam` | `Tüketici Kredileri - Toplam - Tük. Krd. (Dövize End. Dahil) ve Bireysel Kredi Kartları (milyon TL)-Toplam` | **5744345** |
| Takipteki Tüketici | `1544?Toplam` | `Tüketici Kredileri - Takipteki Tüketici Krd. (milyon TL)-Toplam` | **116867** |
| Takipteki Konut | `1545?Toplam` | `Tüketici Kredileri - Takipteki Konut Kredileri (milyon TL)-Toplam` | **1128** |
| Takipteki Taşıt | `1546?Toplam` | `Tüketici Kredileri - Takipteki Taşıt Kredileri (milyon TL)-Toplam` | **334** |
| Takipteki İhtiyaç | `1547?Toplam` | `Tüketici Kredileri - Takipteki İhtiyaç Kredileri (milyon TL)-Toplam` | **115405** |
| Takipteki BKK | `1548?Toplam` | `Tüketici Kredileri - Takipteki Bireysel Kredi Kartları (milyon TL)-Toplam` | **124652** |
| Krediler (Bilanço) | `1160?Toplam` | `Bilanço - Krediler (milyon TL)-Toplam` | **23127970** |
| Takipteki Alacaklar | `1676?Toplam` | `Bilanço - Takipteki Alacaklar (milyon TL)-Toplam` | **593647** |
| Toplam Aktifler | `1688?Toplam` | `Bilanço - Toplam Aktifler (milyon TL)-Toplam` | **46946798** |
| Toplam Özkaynaklar | `1717?Toplam` | `Bilanço - Toplam Özkaynaklar (milyon TL)-Toplam` | **4155620** |
| Toplam Mevduat | `1357?Toplam` | `Mevduat Türler İtibarıyla - 11  Toplam Mevduat (milyon TL)-Toplam` | **27223190** |
| Toplam Mevduat Yurt İçi | `1344?Toplam` | `Mevduat Türler İtibarıyla - 4   Toplam Mevduat - Yurt İçi Yerleşik (milyon TL)-Toplam` | **25549894** |
| NPL oranı (%) | `544?Rasyo` | `Rasyolar - Takipteki Alacaklar (Brüt) / Toplam Nakdi Krediler (%)-Rasyo` | **2.47437** |
| Kredi/Mevduat (%) | `1749?Rasyo` | `Rasyolar - Toplam Nakdi Krediler / Toplam Mevduat (%)-Rasyo` | **88.120059** |
| SYR (%) | `1746?Rasyo` | `Rasyolar - Yasal Özkaynak / Risk Ağırlıklı Kalemler Toplamı (%)-Rasyo` | **19.687081** |

Ham yanıtlar ve kalem ağacı bu turda ölçüldü; katalog girişleri `catalog/series/bddk_monthly.yml`
"Genişletme" bloğunda. Bilanço, Mevduat ve Rasyolar tablolarının kalemleri aynı uçtan aynı
sözleşmeyle döner; frekans aylık, Sektör tarafı, TL. Alınmayan: KOBİ kredileri (sütun belirsiz),
haftalık bültenin ek kalemleri (konumsal kimlik, `docs/sources/bddk_weekly.md`).

## Kümülatif kalemler (2026-09-14): Kar Zarar tablosu yıl içi birikimlidir

Brief'in "bazı BDDK verileri yıllık bazda kümülatif gider; ayrıştırılmalı" notu için Kar Zarar
tablosundan iki kalem canlı ölçüldü (`GelismisRaporGetir`, 2025-01 → 2026-02, `taraf=10001`,
`paraBirimi=TL`; kalem ağacı `Gelismis` sayfasının `<optgroup label="Kar Zarar">` listesinden).
Her iki kalem de **yılbaşından itibaren birikir ve Ocak'ta sıfırlanır**:

| Kalem | `kalemSutun` | 2025-01 | 2025-06 | 2025-12 | 2026-01 | 2026-02 |
|---|---|---|---|---|---|---|
| Dönem Net Kârı (Zararı) | `194?Toplam` | 47347 | 422459 | 940183 | 87249 | 169401 |
| Toplam Faiz (Kar Payı) Gelirleri | `158?Toplam` | 621187 | 3855642 | 8355475 | 789354 | 1497867 |

Bilanço tablosundaki `1715?Toplam` ("Bilanço - Dönem Karı (Zararı)") 194 ile aynı değerleri
döndürüyor (aynı ölçümün ikinci adresi); katalogda yalnız 194 var. Katalog: `measure_type:
flow_ytd`, `cumulative_reset: yearly`; aylık akım Gold `decompose_cumulative` ile türetilir
(`catalog/gold/kredi_kirilimi.yml`, `net_kar_aylik`). "Paylaşım başlangıcından itibaren
kümülatif" giden bir kalem bu turda bulunamadı; Kar Zarar tablosundaki tüm kalemler aynı yıl içi
kalıptadır (yalnız 194 ve 158 ölçüldü).

## Mevduat vade kovaları (2026-09-23): 24 kalem × 6 kova, canlı doğrulandı

`Mevduat Vade İtibarıyla` tablosunun güncel şema kalemleri 520–543'tür (24 kalem). Her kalem için
`KalemSutunGetir?kalemNoList=<kalem>` aynı yedi sütunu bildirir (23 Eylül, 24 istek, hepsi aynı):

| `kalemSutun` eki | Kaynağın etiketi | Vade aralığı (ay) |
|---|---|---|
| `Vadesiz` | Vadesiz | [0, 0] |
| `BirAyaKadar` | 1 Aya Kadar | (0, 1] |
| `BirAyUcAy` | 1-3 Ay Arası | (1, 3] |
| `UcAyAltiAy` | 3-6 Ay Arası | (3, 6] |
| `AltiAyBirYil` | 6-12 Ay Arası | (6, 12] |
| `BirYil` | 1  Yıl Üzeri (kaynakta çift boşluk) | (12, ∞) |
| `Toplam` | Toplam | tümü |

Canlı ölçümler (`GelismisRaporGetir`, taraf=10001, paraBirimi=TL, periyot=1):

- **Toplanabilirlik.** 520 (TP, yurt içi yerleşik) ve 524 (DTH, yurt içi yerleşik) için
  2020-12 → 2025-12 arasındaki 61 ayın hepsinde altı kovanın toplamı Toplam'a eşittir; en
  büyük fark 2 milyon TL'dir. Bu fark kaynağın her sütunu tam milyon TL'ye yuvarlamasından
  gelir; altı kovada sınır 6 × 0,5 = 3'tür. `scripts/check_breakdown_sums.py` bu kuralı
  yüklenmiş havuzda her kalem ve her ay için denetler.
- **Birim.** Rapor başlığı her kalemde `(milyon TL)`; kova sütununun Bronze adı Toplam'la aynı
  biçimdedir: `Mevduat Vade İtibarıyla - 1   TP Mevduat / Katılım Fonları - Yurt İçi Yerleşik (milyon TL)-BirYil`.
- **Kapsam.** Kalem 520 kimliğiyle 2016-01 ve 2020 ayları da döner (ör. 2020-12 TP Toplam
  1.502.152, DTH Toplam 1.458.547). Havuzda bu kalemlerin 2021-01'den başlaması kaynaktan değil,
  o yüklemenin 2021-01-01 başlangıcından kaynaklanıyordu.
- **Eski şema.** Aynı optgroup'ta 729–737 kalemleri (Tasarruf Mevduatı, Özel Cari Hesaplar …)
  dört şema kimliği taşır (`729,720,711,702`) ve 2025-12 için satır döndürmez; katalogda
  `deprecated` kalırlar, kovaları eklenmez.

Kova serileri `scripts/generate_bddk_monthly_catalog.py --group "Mevduat Vade İtibarıyla"
--add-columns --probed-on 2026-09-23` ile eklendi (144 giriş; mevcut girişlerin hiçbiri
değişmedi). Toplam ile kovaları arasındaki ilişki `src/lakehouse/catalog/relations.py`'de
kaynak kimliğinden üretilir (ADR-0108).
