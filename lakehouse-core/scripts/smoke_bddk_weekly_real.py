"""Manual smoke test: real, non-mocked end-to-end ingestion for the 4 catalog series.

Fetches all 4 series currently defined in catalog/series/*.yml (2 BDDK, 2 EVDS)
from their live endpoints through the real connector -> RAW -> artifact
registry -> parser -> Bronze Parquet pipeline, landing data in this repo's
data/ tree.

This is a manual validation utility, NOT a production ingestion entrypoint.
It is not wired into CI or the Makefile. Run it on demand, by hand.

Each series is run independently: one failing (e.g. missing EVDS_API_KEY)
does not stop the others.

Usage (from lakehouse-core/, with DBeaver disconnected from
data/lakehouse.duckdb):

    uv run python scripts/smoke_bddk_weekly_real.py
"""

from __future__ import annotations

import truststore

truststore.inject_into_ssl()

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.base import BaseConnector
from src.lakehouse.connectors.bddk_monthly import BddkMonthlyConnector
from src.lakehouse.connectors.bddk_weekly import (
    BDDK_WEEKLY_SERIES_PATH,
    BddkWeeklyConnector,
)
from src.lakehouse.connectors.evds import EvdsConnector
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.errors import LakehouseError
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.parsers.base import BaseParser
from src.lakehouse.parsers.bddk_monthly import BddkMonthlyParser
from src.lakehouse.parsers.bddk_weekly import BddkWeeklyParser
from src.lakehouse.parsers.evds import EvdsParser
from src.lakehouse.storage.parquet import ParquetStorage
from src.lakehouse.storage.raw import RawStorage


@dataclass(frozen=True)
class IngestionJob:
    """One (connector, parser, spec) triple to run through the shared pipeline shape."""

    name: str
    connector: BaseConnector
    parser: BaseParser
    spec: FetchSpec


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
    "UNSUPPORTED_FORMAT": "FetchSpec is missing/has an invalid required parameter.",
}


def _require_repo_root_cwd() -> None:
    cwd = Path.cwd().resolve()
    if cwd != _REPO_ROOT:
        print(
            "ERROR: run this script with the working directory set to "
            f"{_REPO_ROOT} (lakehouse-core/), not {cwd}.\n"
            "Data paths (data/raw, data/bronze, data/lakehouse.duckdb) resolve "
            "relative to the working directory. Fix: cd into lakehouse-core/ "
            "and rerun `uv run python scripts/smoke_bddk_weekly_real.py`."
        )
        raise SystemExit(2)


def _build_jobs(raw_storage: RawStorage, session: requests.Session) -> list[IngestionJob]:
    return [
        IngestionJob(
            name="bddk_weekly:5690_3 (Konut Kredileri, Haftalık)",
            connector=BddkWeeklyConnector(raw_storage, session=session),
            parser=BddkWeeklyParser(),
            spec=FetchSpec(
                source_id="bddk_weekly",
                dataset_id="bddk_weekly_housing_loans",
                locator=f"https://www.bddk.org.tr{BDDK_WEEKLY_SERIES_PATH}",
                start_date=date(2021, 1, 1),
                end_date=date(2026, 6, 26),
                parameters={
                    "id": "1.0.4",
                    "kalem_id": "5690",
                    "expected_measure_label": "a) Konut",
                    "expected_currency": "TRY",
                    "expected_column": "Toplam",
                    "parabirimi": "TRY",
                    "sutun": "3",
                    "tarafKodu": "10001",
                },
            ),
        ),
        IngestionJob(
            name="bddk_monthly:1534_Toplam (Tüketici Kredileri - Konut, Aylık)",
            connector=BddkMonthlyConnector(raw_storage, session=session),
            parser=BddkMonthlyParser(),
            spec=FetchSpec(
                source_id="bddk_monthly",
                dataset_id="bddk_monthly_housing_loans",
                locator="https://www.bddk.org.tr/BultenAylik/tr/Home/BasitRaporGetir",
                start_date=date(2021, 1, 1),
                end_date=date(2026, 6, 1),
                parameters={
                    "periyot": "1",
                    "paraBirimi": "TL",
                    "taraf": ["10001"],
                    "kalemSutun": "1534?Toplam",
                    "gosterimTuru": "grid",
                },
            ),
        ),
        IngestionJob(
            name="evds:TP.KTF12 (Konut Kredisi Faiz Oranı)",
            connector=EvdsConnector(raw_storage),
            parser=EvdsParser(),
            spec=FetchSpec(
                source_id="evds",
                dataset_id="evds_housing_interest",
                locator="evds",
                start_date=date(2021, 1, 1),
                end_date=date(2026, 6, 30),
                parameters={"series": "TP.KTF12"},
            ),
        ),
        IngestionJob(
            name="evds:TP.KFE.TR (Konut Fiyat Endeksi)",
            connector=EvdsConnector(raw_storage),
            parser=EvdsParser(),
            spec=FetchSpec(
                source_id="evds",
                dataset_id="evds_housing_price_index",
                locator="evds",
                start_date=date(2021, 1, 1),
                end_date=date(2026, 6, 30),
                parameters={"series": "TP.KFE.TR"},
            ),
        ),
    ]


def _run_one(
    job: IngestionJob,
    artifact_repository: ArtifactRepository,
    parquet_storage: ParquetStorage,
) -> bool:
    """Run one job through the shared pipeline shape. Return True on success."""

    print(f"\n=== {job.name} ===")
    pipeline = IngestionPipeline(
        connector=job.connector,
        parser=job.parser,
        artifact_repository=artifact_repository,
        parquet_storage=parquet_storage,
    )
    try:
        results = pipeline.run(job.spec)
    except LakehouseError as exc:
        payload = exc.payload
        print("  FAILED")
        print(f"  error_code : {payload.error_code}")
        print(f"  retryable  : {payload.retryable}")
        print(f"  message    : {payload.message}")
        hint = _ERROR_HINTS.get(payload.error_code)
        if hint:
            print(f"  hint       : {hint}")
        return False

    result = results[0]
    df = result.parsed_batch.dataframe
    print("  SUCCESS")
    print(f"  artifact_sha256   : {result.asset.artifact_sha256}")
    print(f"  artifact_inserted : {result.artifact_inserted}")
    print(f"  bronze_path       : {result.bronze_path}")
    print(f"  row_count         : {len(df)}")
    if result.parsed_batch.warnings:
        print(f"  warnings          : {result.parsed_batch.warnings}")
    return True


def main() -> int:
    _require_repo_root_cwd()

    raw_storage = RawStorage()
    parquet_storage = ParquetStorage()
    trusted = bootstrap_database()
    artifact_repository = ArtifactRepository(trusted)
    session = requests.Session()

    jobs = _build_jobs(raw_storage, session)
    outcomes: dict[str, bool] = {}
    try:
        for job in jobs:
            outcomes[job.name] = _run_one(job, artifact_repository, parquet_storage)
    finally:
        trusted.close()
        session.close()

    print("\n=== SUMMARY ===")
    succeeded = sum(1 for ok in outcomes.values() if ok)
    for name, ok in outcomes.items():
        print(f"  [{'OK' if ok else 'FAIL'}] {name}")
    print(f"\n{succeeded}/{len(outcomes)} series ingested successfully.")

    return 0 if succeeded == len(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
