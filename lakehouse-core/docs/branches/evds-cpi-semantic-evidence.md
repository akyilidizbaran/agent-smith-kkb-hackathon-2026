# TP.FG.J0 Public Semantic Evidence

Phase 3.3A; verification date: 2026-09-11. Starting branch:
`feature/lakehouse-operationalization`, HEAD
`375cd22f293189efc4607d844ecaf818d1fb359d`, clean tree; reported baseline: 970 tests.

## What is verified publicly

The historical code identifies the general monthly CPI index associated with the
2003=100 reference. This closes public semantic evidence only. An index level must
not be interpreted as monthly inflation percent or silently combined with a different base.

| Claim | Classification | Evidence / scope |
|---|---|---|
| Native code TP.FG.J0 | VERIFIED_PUBLIC | P3 Appendix A explicitly names it |
| General CPI identity | VERIFIED_PUBLIC | P3 code mapping, corroborated by P1/P2 |
| Monthly frequency | VERIFIED_PUBLIC | P4 monthly publication; P3 monthly sample |
| Index nature | VERIFIED_PUBLIC | P2 methodology, P3 reference, P4 distinction from changes |
| Unit = index | VERIFIED_PUBLIC | Catalog vocabulary expresses the documented index level |
| Reference/base = 2003=100 | VERIFIED_PUBLIC | P3 explicit mapping plus P1/P2; historical reference |
| Source institution | VERIFIED_PUBLIC | TÜİK producer (P2/P4); TCMB EVDS distributor (P1/P3) |
| Current provider active/archived status | LIVE_NOT_VERIFIED | Navigation label does not establish current native-code status |
| Exact authenticated API response envelope | LIVE_NOT_VERIFIED | No successful authenticated CPI data capture |
| Exact live field names | LIVE_NOT_VERIFIED | Synthetic fields are contract assumptions only |
| Live 2025-01 value | LIVE_NOT_VERIFIED | No observation verified or adopted |
| Production Connector -> Parser live compatibility | LIVE_NOT_VERIFIED | Offline synthetic test is not a live test |
| default_agg = last | PROJECT_DERIVED | Existing project aggregation policy, not provider evidence |
| dataset_id = evds_cpi and Silver mapping | PROJECT_DERIVED | Local registry and offline integration tests |
| Aliases and catalog status = active | PROJECT_DERIVED | Search vocabulary and retained project configuration |

## What remains unverified live

Authenticated EVDS3 response envelope remains unverified. Prior production requests
returned HTTP 401 with the available credential. This does not establish incorrect series
or endpoint semantics. No authentication diagnostics were continued in this phase.
The current provider status, values, date encoding and successful live parser compatibility
remain follow-up work. P1 also lists a 2025=100 group: do not infer continuity or splice it
with this historical reference. Production real conversion remains gated on live evidence.

## Evidence sources

P1-P4, their exact first-party links, retrieval methods and limitations are recorded in
[EVDS source documentation](../sources/evds.md#public-evidence-and-retrieval-limits).
P3 is a directly retrieved TCMB-hosted research PDF; P1, P2 and P4 were checked through
indexed first-party text because direct extraction returns JavaScript shells. No API
response, metadata-service success or current publication status is inferred from that text.

## Catalog confidence decision

**REMAINS_DERIVED.** The general [catalog contract](../catalog-contract.md#confidence-levels)
defines verified as evidence for every semantic field, including unit; it does not impose
a universal live-service requirement. However, the existing CPI-specific checklist in
`docs/sources/evds.md` also requires an authenticated fixture, capture provenance and a
fixture-backed integration test. Those requirements remain unmet, and current provider
status is unresolved. Neither the contract nor that promotion gate was weakened.

`semantic_source` changes from `manual` to `source_docs` to identify public documentary
provenance. The description replaces the obsolete unsupported-base warning with scoped
2003=100 evidence and explicit live limitations. Confidence stays `derived`.

Starting record: `series_id=evds:TP.FG.J0`, `native_code=TP.FG.J0`, `dataset_id=evds_cpi`,
`name_tr=Tüketici Fiyat Endeksi (TÜFE, genel)`, `frequency=monthly`, `unit=index`,
`measure_type=index`, `default_agg=last`, `semantic_confidence=derived`,
`semantic_source=manual`, `status=active`. The former description described an index level,
Gold-only real conversion and Silver non-rebasing, but said the base lacked evidence.
Aliases remain: tüfe, tufe, enflasyon, tüketici fiyat endeksi, fiyat endeksi, TÜFE endeksi,
genel fiyat endeksi. Tags remain: enflasyon, fiyat, endeks, tcmb, tuik.
The existing `metadata_url` points to EVDS3 `serieList` for this code; it is retained as a
reference, not evidence of a successful request. No custom evidence fields are added to
the strict catalog schema; evidence belongs in source documentation.

## Why no live fixture was created

No successful authenticated CPI data response exists from these diagnostics. A public
document or synthetic JSON cannot substitute for captured source bytes. Existing synthetic
tests remain clearly labelled and outside `tests/fixtures/raw/`. Their index-level, null,
monthly-boundary and Silver-mapping checks remain offline. A catalog regression checks
public documentary provenance while retaining derived confidence.

## Security

No credential, credential-bearing URL, request-header values or local secret file is part
of this change. Public document identifiers in references are not credentials. This phase
uses only public evidence and offline validation. No authentication attempts or push.
