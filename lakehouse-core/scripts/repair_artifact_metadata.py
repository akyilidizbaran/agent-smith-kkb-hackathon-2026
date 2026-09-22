"""Repair missing ``meta.artifact`` rows from persisted Silver/RAW facts.

The PR9 database contains the data and the content-addressed RAW files, but a
subset of the ingestion metadata was not carried over.  This script restores
only rows that can be proven from those existing facts; it never downloads a
source or invents a timestamp.

Usage::

    python lakehouse-core/scripts/repair_artifact_metadata.py \
        --database data/lakehouse.duckdb --data-root data
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import duckdb


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/lakehouse.duckdb"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _raw_files(data_root: Path) -> dict[str, Path]:
    """Index current RAW files by their content-addressed filename."""

    found: dict[str, Path] = {}
    for path in sorted((data_root / "raw").glob("**/*.json")):
        digest = path.stem
        if len(digest) != 64:
            continue
        if digest in found and found[digest] != path:
            raise RuntimeError(f"duplicate RAW path for {digest}: {found[digest]} / {path}")
        found[digest] = path.resolve()
    return found


def _catalog_locators(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    rows = connection.execute(
        """
        SELECT source_id, dataset_id, min(metadata_url)
        FROM meta.series
        WHERE metadata_url IS NOT NULL AND metadata_url <> ''
          AND coalesce(status, 'active') <> 'deprecated'
        GROUP BY source_id, dataset_id
        """
    ).fetchall()
    by_dataset = {
        (str(source), str(dataset)): str(locator)
        for source, dataset, locator in rows
        if dataset is not None
    }
    by_source: dict[str, str] = {}
    for (source, _dataset), locator in by_dataset.items():
        by_source.setdefault(source, locator)
    return by_dataset, by_source


def _as_utc(value: object) -> datetime:
    """Convert DuckDB's casted timestamp to an aware UTC datetime."""

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace(" ", "T")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _facts(connection: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str, datetime]]:
    rows = connection.execute(
        """
        SELECT artifact_sha256, source_id, dataset_id,
               CAST(min(fetched_at) AS TIMESTAMP) AS first_fetched_at
        FROM silver.fact_observation
        WHERE artifact_sha256 IS NOT NULL AND fetched_at IS NOT NULL
        GROUP BY artifact_sha256, source_id, dataset_id
        ORDER BY source_id, artifact_sha256, dataset_id
        """
    ).fetchall()
    return [
        (str(sha), str(source), str(dataset), _as_utc(fetched))
        for sha, source, dataset, fetched in rows
    ]


def _request_fingerprint(locator: str) -> str:
    context = json.dumps(
        {"locator": locator, "metadata": {"repaired_from": "silver_and_raw"}},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(context.encode("utf-8")).hexdigest()


def repair(
    connection: duckdb.DuckDBPyConnection,
    *,
    data_root: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    raw = _raw_files(data_root)
    locators, source_locators = _catalog_locators(connection)
    existing = {
        str(row[0])
        for row in connection.execute("SELECT artifact_sha256 FROM meta.artifact").fetchall()
    }

    # One RAW artifact can yield many FinTürk province series.  The artifact
    # itself is source-level, so retain a deterministic representative dataset
    # while the Silver rows remain the authoritative observation mapping.
    grouped: dict[str, tuple[str, str, datetime]] = {}
    for sha, source, dataset, fetched in _facts(connection):
        previous = grouped.get(sha)
        if previous is None:
            grouped[sha] = (source, dataset, fetched)
            continue
        # The representative dataset is deterministic; the observation
        # timestamp remains the earliest factual fetch for this artifact.
        representative = min((previous[0], previous[1]), (source, dataset))
        grouped[sha] = (representative[0], representative[1], min(previous[2], fetched))

    repaired = 0
    skipped_existing = 0
    missing_raw = 0
    missing_locator = 0
    request_rows = 0
    for sha in sorted(grouped):
        if sha in existing:
            skipped_existing += 1
            continue
        source, dataset, fetched_at = grouped[sha]
        path = raw.get(sha)
        if path is None:
            missing_raw += 1
            continue
        locator = locators.get((source, dataset)) or source_locators.get(source)
        if not locator:
            missing_locator += 1
            continue
        seen_at = fetched_at
        values = [
            sha,
            source,
            dataset,
            locator,
            "application/json",
            path.stat().st_size,
            None,
            fetched_at,
            str(path),
            seen_at,
            seen_at,
        ]
        if not dry_run:
            connection.execute(
                """
                INSERT INTO meta.artifact (
                    artifact_sha256, source_id, dataset_id, locator, media_type,
                    byte_size, http_status, fetched_at, raw_path,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            request_fingerprint = _request_fingerprint(locator)
            connection.execute(
                """
                INSERT INTO meta.artifact_request (
                    artifact_sha256, request_fingerprint, locator,
                    request_metadata_json, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (artifact_sha256, request_fingerprint) DO NOTHING
                """,
                [
                    sha,
                    request_fingerprint,
                    locator,
                    json.dumps(
                        {"repaired_from": "silver_and_raw"},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    seen_at,
                    seen_at,
                ],
            )
            request_rows += 1
        repaired += 1

    if not dry_run:
        connection.commit()
    return {
        "silver_artifacts": len(grouped),
        "repaired": repaired,
        "request_rows": request_rows,
        "skipped_existing": skipped_existing,
        "missing_raw": missing_raw,
        "missing_locator": missing_locator,
    }


def main() -> int:
    args = _args()
    db = args.database.resolve()
    data_root = args.data_root.resolve()
    connection = duckdb.connect(str(db), read_only=args.dry_run)
    try:
        report = repair(connection, data_root=data_root, dry_run=args.dry_run)
    finally:
        connection.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["missing_raw"] == 0 and report["missing_locator"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
