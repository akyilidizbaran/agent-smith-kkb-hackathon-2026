"""Idempotent DuckDB schema bootstrap."""

from __future__ import annotations

from pathlib import Path

import duckdb

from ..catalog.series import DEFAULT_CATALOG_ROOT, load_series_catalog
from .connection import DEFAULT_DB_PATH, connect_trusted


_SQL_ROOT = Path(__file__).resolve().parents[3] / "sql" / "bootstrap"


def bootstrap_schema(connection: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """Create the lakehouse schemas and P0 metadata tables idempotently."""

    for sql_path in sorted(_SQL_ROOT.glob("*.sql")):
        connection.execute(sql_path.read_text(encoding="utf-8"))
    return connection


def bootstrap_database(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    catalog_root: Path | None = DEFAULT_CATALOG_ROOT,
) -> duckdb.DuckDBPyConnection:
    """Open and bootstrap a local DuckDB database, returning its connection.

    After the schemas exist, the Git-versioned semantic series catalog is loaded into
    ``meta.series``. The load is idempotent: unchanged records are skipped, so repeated
    bootstraps neither duplicate rows nor churn ``updated_at``. Pass ``catalog_root=None``
    to bootstrap the schema only.
    """

    connection = connect_trusted(db_path)
    try:
        bootstrap_schema(connection)
        if catalog_root is not None:
            load_series_catalog(connection, catalog_root)
        return connection
    except Exception:
        connection.close()
        raise


__all__ = ["bootstrap_database", "bootstrap_schema"]
