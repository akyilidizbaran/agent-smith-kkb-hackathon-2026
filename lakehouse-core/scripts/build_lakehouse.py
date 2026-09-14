"""Build the whole lakehouse from an empty directory with one command, and time every step.

    uv run python scripts/build_lakehouse.py --database data/lakehouse.duckdb --data-root data

Steps, in order (each is the existing operator command, nothing new is implemented here):

1. ``python -m lakehouse bootstrap``            schema + catalog (catalog/series/*.yml)
2. ``scripts/run_catalog_ingestion.py``         every active catalogued series, one request per
                                                 FetchSpec (BDDK weekly/monthly/FinTürk, EVDS
                                                 weekly/monthly/quarterly)
3. ``python -m lakehouse ingest`` per dataset    EVDS datasets whose frequency is daily or
                                                 business_daily: these exceed EVDS's 1,000
                                                 observations per request over 2021-2026, so
                                                 they go through the windowed CLI path
4. ``python -m lakehouse silver``               Bronze -> silver.fact_observation
5. ``python -m lakehouse gold``                 catalogued metrics -> gold.* tables

Which datasets take the windowed path is decided from the catalog (frequency), not from a
list in this file. ``--only`` restricts step 2 to a comma-separated series_id list (the same
flag the runner takes) and step 3 to the datasets those series belong to, so a small demo
build and the full build are the same script.

Credentials come from the environment (``EVDS_API_KEY``); ``.env`` in the repo root is read
if present, exactly as the runner does. Nothing here prints a secret.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from _env import load_dotenv_simple

load_dotenv_simple(_REPO_ROOT)

from src.lakehouse.catalog.series import load_catalog_files

WINDOWED_FREQUENCIES = frozenset({"daily", "business_daily"})
DEFAULT_START = "2021-01-01"
DEFAULT_END = "2026-06-30"


def _run(label: str, command: list[str], timings: list[tuple[str, float, int]]) -> int:
    print(f"\n===== {label} =====", flush=True)
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=_REPO_ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    elapsed = time.perf_counter() - started
    timings.append((label, elapsed, completed.returncode))
    print(f"----- {label}: {elapsed:.1f} s, exit {completed.returncode}", flush=True)
    return completed.returncode


def _windowed_datasets(only: set[str] | None) -> list[str]:
    datasets: set[str] = set()
    for record in load_catalog_files():
        if record.status != "active" or record.frequency not in WINDOWED_FREQUENCIES:
            continue
        if record.source_id != "evds" or record.dataset_id is None:
            continue
        if only is not None and record.series_id not in only:
            continue
        datasets.add(record.dataset_id)
    return sorted(datasets)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build bootstrap -> ingest -> silver -> gold.")
    parser.add_argument("--database", default="data/lakehouse.duckdb")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--only", default=None, help="comma-separated series ids (default: all)")
    parser.add_argument("--start-date", default=DEFAULT_START)
    parser.add_argument("--end-date", default=DEFAULT_END)
    parser.add_argument("--skip-ingest", action="store_true", help="bootstrap, silver, gold only")
    args = parser.parse_args()

    python = [sys.executable]
    storage = ["--database", args.database, "--data-root", args.data_root]
    only = set(args.only.split(",")) if args.only else None
    timings: list[tuple[str, float, int]] = []

    if _run("bootstrap", [*python, "-m", "lakehouse", "bootstrap", *storage], timings):
        return 1

    if not args.skip_ingest:
        runner = [*python, "scripts/run_catalog_ingestion.py", *storage]
        if args.only:
            runner += ["--only", args.only]
        # The runner exits 1 when any series fails; a partial catalog is still worth publishing,
        # so the failure is recorded in the timing table rather than aborting the build.
        _run("ingest (catalog runner)", runner, timings)

        for dataset_id in _windowed_datasets(only):
            _run(
                f"ingest windowed {dataset_id}",
                [*python, "-m", "lakehouse", "ingest", *storage, "--source", "evds",
                 "--dataset", dataset_id, "--start-date", args.start_date,
                 "--end-date", args.end_date],
                timings,
            )

    if _run("silver", [*python, "-m", "lakehouse", "silver", *storage], timings):
        return 1
    if _run("gold", [*python, "-m", "lakehouse", "gold", *storage], timings):
        return 1

    print("\n===== timings =====")
    total = 0.0
    for label, elapsed, code in timings:
        total += elapsed
        print(f"{label:40} {elapsed:8.1f} s   exit {code}")
    print(f"{'TOTAL':40} {total:8.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
