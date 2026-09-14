# EVDS Windowed Ingestion

## Problem

The EVDS service can return at most 1,000 observations for one request. A response
that reaches that limit may be silently incomplete, so a long date range must not be
treated as one complete result.

## Behavior

The existing lakehouse ingest command plans the requested inclusive date range into
deterministic windows of at most 365 calendar days:

    logical date range
        -> ordered windows
        -> one normal EVDS request per window
        -> one normal parser/Bronze result per response
        -> deterministic reconciliation
        -> complete success only after every window succeeds

The 365-day cap is based on the daily worst case under the verified 1,000-observation
response limit. Weekly, monthly, and other supported frequencies therefore use the same
conservative cap. This is an observation-size policy, not an HTTP rate-limit or quota rule.
Window starts and ends are inclusive; adjacent windows have no gap and no overlap.

## Provenance

All windows share one meta.run row. Each successful response is passed through the
existing EvdsConnector, stored as its own content-addressed RAW artifact, registered in
meta.artifact, linked in meta.run_artifact, parsed by EvdsParser, and written to its
own Bronze Parquet file. The request metadata records the window index/count and the
logical range without credentials.

Window reconciliation does not create a combined artifact or a synthetic SHA. Each retained
observation keeps the artifact_sha256 from the window that supplied it.

## Duplicate policy

The logical identity is series, optional entity, and EVDS UNIXTIME (falling back to
date_raw). A repeated identity with the same raw value is a deterministic boundary
duplicate; the first ordered window is retained. NULL and NULL are equivalent.
NULL versus a value, or two different non-null raw values, raises an explicit
REVISION_CONFLICT; neither value is silently preferred.

## Failure behavior

Window processing is sequential and fail-fast. If a later window fails, the shared run is
closed as failed, the failed window coordinates and reason are retained in run error
metadata, and earlier RAW/artifact/Bronze evidence remains available. The CLI returns a
non-zero status and never reports a partial result as successful.

An individual response that still carries the existing EVDS per-request-limit warning is
also rejected as OBSERVATION_COUNT_MISMATCH after its RAW and Bronze evidence are written.

## CLI

The command is unchanged:

    uv run python -m lakehouse ingest \
      --source evds \
      --dataset evds_cpi \
      --start-date 2026-01-01 \
      --end-date 2027-01-01

A short range uses one request and retains the prior singular artifact_sha256 and
bronze_path output fields. A multi-window success prints the window count, all artifact
SHA values, all Bronze paths, and the reconciled observation count. A failure prints the
logical run_id and failed window start/end.

## Security

Credentials still come from EVDS_API_KEY, or from the existing --headers-ref environment
variable reference. The window coordinator does not receive or persist secret values, and
the existing EVDS transport, TLS behavior, retry, and backoff are reused for every window.

## Current limits

This phase uses controlled offline transport tests only. It does not claim live EVDS CPI
evidence, an official base year, or a verified catalog confidence level. HTTP rate quotas,
Silver publication, and Gold semantics are outside this change.
