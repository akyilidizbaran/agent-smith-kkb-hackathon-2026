"""Create and populate ``meta.series_relation`` for an existing DuckDB lakehouse.

The normal bootstrap path creates this table and synchronizes it while loading the Git
catalog.  PR9-era databases already contain a larger generated ``meta.series`` catalog, so
this small migration reads that table directly and applies the same source adapters.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.lakehouse.catalog.relations import infer_series_relations


DDL = """
CREATE SCHEMA IF NOT EXISTS meta;
CREATE TABLE IF NOT EXISTS meta.series_relation (
    series_id VARCHAR PRIMARY KEY,
    concept_id VARCHAR NOT NULL,
    parent_series_id VARCHAR,
    relation_type VARCHAR NOT NULL,
    dimension_path VARCHAR[],
    additivity VARCHAR NOT NULL DEFAULT 'unknown',
    relation_confidence VARCHAR NOT NULL DEFAULT 'derived',
    relation_source VARCHAR NOT NULL DEFAULT 'source_adapter',
    relation_content_sha256 VARCHAR NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);
"""


def sync(database: str | Path) -> int:
    con = duckdb.connect(str(database))
    try:
        con.execute(DDL)
        columns = (
            "series_id, source_id, native_code, dataset_id, name_tr, description, "
            "aliases, tags"
        )
        rows = con.execute(f"SELECT {columns} FROM meta.series WHERE status <> 'deprecated'").fetchall()
        names = [part.strip() for part in columns.split(",")]
        relations = infer_series_relations([dict(zip(names, row)) for row in rows])
        con.execute("BEGIN TRANSACTION")
        for relation in relations:
            con.execute(
                """
                INSERT OR REPLACE INTO meta.series_relation (
                    series_id, concept_id, parent_series_id, relation_type, dimension_path,
                    additivity, relation_confidence, relation_source, relation_content_sha256,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
                """,
                [
                    relation.series_id,
                    relation.concept_id,
                    relation.parent_series_id,
                    relation.relation_type,
                    list(relation.dimension_path),
                    relation.additivity,
                    relation.relation_confidence,
                    relation.relation_source,
                    relation.content_sha256,
                ],
            )
        con.execute("COMMIT")
        return len(relations)
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    count = sync(args.database)
    print(f"series_relation synchronized: {count} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
