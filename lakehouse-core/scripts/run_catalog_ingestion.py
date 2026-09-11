"""Catalog-driven real ingestion: fetch every active series meta.series knows
about, generically, with zero per-series code in this file.

The list of series is NOT hardcoded here — it is read from meta.series (the
catalog loaded from catalog/series/*.yml by bootstrap_database()). Adding a
new series to a catalog YAML and re-running bootstrap makes it show up here
automatically. What each source needs to build a real FetchSpec lives in
ingestion_registry.py, keyed by source_id, not by series.

This is a manual validation/ingestion utility, NOT wired into CI or the
Makefile. Run it on demand, by hand.

Usage (from lakehouse-core/, with DBeaver disconnected from
data/lakehouse.duckdb):

    uv run python scripts/run_catalog_ingestion.py
"""

from __future__ import annotations

import truststore

truststore.inject_into_ssl()

import sys
import time
from datetime import date
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from _env import load_dotenv_simple

load_dotenv_simple(_REPO_ROOT)

from ingestion_registry import CONNECTOR_REGISTRY, SeriesRow

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.errors import ErrorPayload, LakehouseError
from src.lakehouse.storage.parquet import ParquetConflictError, ParquetStorage
from src.lakehouse.storage.raw import RawStorage

DEFAULT_START = date(2021, 1, 1)
DEFAULT_END = date(2026, 6, 30)

_ERROR_HINTS = {
    "SOURCE_UNAVAILABLE": (
        "Network/TLS/auth problem. For EVDS this usually means EVDS_API_KEY is "
        "not set. For BDDK, a TLS failure even after truststore injection means "
        "the Windows store could not resolve the missing intermediate cert."
    ),
    "SCHEMA_MISMATCH": (
        "Response shape did not match what the parser expected (identity "
        "mismatch, source changed, or a wrong parameter)."
    ),
    "EMPTY_DATASET": "Source answered but returned zero observations for this range.",
    "FETCH_TIMEOUT": "The request timed out after retries.",
}


def _require_repo_root_cwd() -> None:
    cwd = Path.cwd().resolve()
    if cwd != _REPO_ROOT:
        print(
            "ERROR: run this script with the working directory set to "
            f"{_REPO_ROOT} (lakehouse-core/), not {cwd}.\n"
            "Fix: cd into lakehouse-core/ and rerun "
            "`uv run python scripts/run_catalog_ingestion.py`."
        )
        raise SystemExit(2)


def _load_active_series(connection) -> list[SeriesRow]:
    """Read every active series meta.series currently knows about.

    This is the entire "which series exist" answer for this script — it comes
    from the real catalog, not from a list written here.
    """

    rows = connection.execute(
        """
        SELECT series_id, source_id, native_code, dataset_id, name_tr
        FROM meta.series
        WHERE status = 'active'
        ORDER BY source_id, series_id
        """
    ).fetchall()
    return [SeriesRow(*row) for row in rows]


def _validate_asset(spec: FetchSpec, asset) -> None:
    """Same identity check IngestionPipeline._validate_asset makes, reimplemented here
    (not imported — it's a private method) so a bad asset is still caught before parsing."""

    if asset.source_id != spec.source_id or asset.dataset_id != spec.dataset_id:
        raise LakehouseError(
            ErrorPayload(
                error_code="SCHEMA_MISMATCH",
                message=(
                    f"FetchSpec/FetchedAsset mismatch: expected "
                    f"{spec.source_id}/{spec.dataset_id}, got "
                    f"{asset.source_id}/{asset.dataset_id}"
                ),
                source_id=spec.source_id,
                dataset_id=spec.dataset_id,
                retryable=False,
            )
        )


def _validate_batch(asset, batch) -> None:
    """Same identity check IngestionPipeline._validate_batch makes, reimplemented here."""

    if (
        batch.source_id != asset.source_id
        or batch.dataset_id != asset.dataset_id
        or batch.artifact_sha256 != asset.artifact_sha256
    ):
        raise LakehouseError(
            ErrorPayload(
                error_code="SCHEMA_MISMATCH",
                message="FetchedAsset/ParsedBatch identity mismatch",
                source_id=asset.source_id,
                dataset_id=asset.dataset_id,
                retryable=False,
            )
        )


def _run_one(
    row: SeriesRow,
    raw_storage: RawStorage,
    session: requests.Session,
    artifact_repository: ArtifactRepository,
    parquet_storage: ParquetStorage,
) -> bool:
    """Fetch and land every asset a series' FetchSpec produces.

    Deliberately does NOT use IngestionPipeline.run(): that method processes every asset
    a connector returns as one all-or-nothing batch, so a single already-ingested asset
    (a real, expected case once a multi-period connector like BddkFinTurkConnector is
    re-run over a range it partly already covers) aborts the whole call and silently
    drops any later, genuinely-new assets in the same batch. This function fetches once,
    then lands each asset independently, so one quarter/month already in Bronze cannot
    hide others that are not. This is a script-local choice, not a change to the shared
    pipeline.
    """

    print(f"\n=== {row.series_id} ({row.name_tr}) ===")

    binding = CONNECTOR_REGISTRY.get(row.source_id)
    if binding is None:
        print(f"  SKIPPED: no connector registered for source_id={row.source_id!r}")
        return False

    try:
        spec = binding.build_spec(row, DEFAULT_START, DEFAULT_END)
    except ValueError as exc:
        print(f"  SKIPPED: {exc}")
        return False

    connector = binding.connector_cls(raw_storage, session=session)
    parser = binding.parser_cls()

    try:
        assets = connector.fetch(spec)
    except LakehouseError as exc:
        payload = exc.payload
        print("  FAILED (fetch)")
        print(f"  error_code : {payload.error_code}")
        print(f"  message    : {payload.message}")
        hint = _ERROR_HINTS.get(payload.error_code)
        if hint:
            print(f"  hint       : {hint}")
        return False

    if not assets:
        print("  FAILED: connector returned no assets")
        return False

    ok_count = 0
    already_count = 0
    fail_count = 0
    for asset in assets:
        try:
            _validate_asset(spec, asset)
            artifact_inserted = artifact_repository.register(asset)
            parsed_batch = parser.parse(asset)
            _validate_batch(asset, parsed_batch)
            bronze_path = parquet_storage.write(parsed_batch)
        except ParquetConflictError:
            # Same RAW artifact re-processed at a different wall-clock time: fetched_at
            # is embedded in every Bronze row, so a second parse of identical source
            # bytes is legitimately a different Bronze representation. Bronze already
            # holds this one asset; that is a per-asset skip, not a failure of the rest.
            already_count += 1
            continue
        except ValueError as exc:
            # ArtifactRepository.register() raises a plain ValueError (not a LakehouseError)
            # when the same artifact_sha256 was already registered under different
            # immutable metadata (source_id/dataset_id/media_type/byte_size/http_status/
            # raw_path) -- e.g. a series moved to a different dataset_id between catalog
            # regenerations, as happened when TP.KTF12/TP.KFE.TR's dataset_id changed from
            # the original hand-curated evds.yml to the auto-generated one. This is a real
            # identity conflict worth flagging distinctly, but must not abort every other
            # series' processing the way an uncaught exception would.
            print(f"  FAILED (artifact identity conflict): {exc}")
            fail_count += 1
            continue
        except LakehouseError as exc:
            payload = exc.payload
            print(f"  FAILED (asset {asset.locator}, fetched_at={asset.fetched_at})")
            print(f"    error_code : {payload.error_code}")
            print(f"    message    : {payload.message}")
            fail_count += 1
            continue

        ok_count += 1
        row_count = len(parsed_batch.dataframe)
        print(
            f"  OK   fetched_at={asset.fetched_at}  rows={row_count}  "
            f"inserted={artifact_inserted}  -> {bronze_path.name}"
        )
        if parsed_batch.warnings:
            print(f"       warnings: {parsed_batch.warnings}")

    print(
        f"  -- {row.series_id}: {ok_count} new, {already_count} already in Bronze, "
        f"{fail_count} failed, out of {len(assets)} fetched asset(s)"
    )
    return fail_count == 0


def main() -> int:
    _require_repo_root_cwd()

    trusted = bootstrap_database()
    raw_storage = RawStorage()
    parquet_storage = ParquetStorage()
    artifact_repository = ArtifactRepository(trusted)
    session = requests.Session()

    series = _load_active_series(trusted)
    print(f"Katalogda {len(series)} aktif seri bulundu.")

    outcomes: dict[str, bool] = {}
    try:
        for position, row in enumerate(series):
            if position > 0:
                # Generic, source-agnostic pacing between DIFFERENT series' first requests.
                # Connectors that need per-request pacing within one series' own fetch()
                # (e.g. BddkFinTurkConnector across quarters) already handle that themselves;
                # this is the outer loop's own courtesy delay so a catalog with hundreds or
                # thousands of series (e.g. the EVDS housing-theme extension) doesn't fire
                # requests back-to-back with zero pacing between series.
                time.sleep(0.2)
            outcomes[row.series_id] = _run_one(
                row, raw_storage, session, artifact_repository, parquet_storage
            )
    finally:
        trusted.close()
        session.close()

    print("\n=== SUMMARY ===")
    for series_id, ok in outcomes.items():
        print(f"  [{'OK' if ok else 'FAIL'}] {series_id}")
    succeeded = sum(1 for ok in outcomes.values() if ok)
    print(f"\n{succeeded}/{len(outcomes)} series ingested successfully.")
    return 0 if succeeded == len(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
