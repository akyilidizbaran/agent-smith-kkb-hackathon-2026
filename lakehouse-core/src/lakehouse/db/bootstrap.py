"""Idempotent DuckDB schema bootstrap."""

from __future__ import annotations

from pathlib import Path

import duckdb

from .connection import DEFAULT_DB_PATH, connect_trusted


_SQL_ROOT = Path(__file__).resolve().parents[3] / "sql" / "bootstrap"


def bootstrap_schema(connection: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """Create the lakehouse schemas and P0 metadata tables idempotently."""

    for sql_path in sorted(_SQL_ROOT.glob("*.sql")):
        connection.execute(sql_path.read_text(encoding="utf-8"))
    return connection


def bootstrap_database(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> duckdb.DuckDBPyConnection:
    """Open and bootstrap a local DuckDB database, returning its connection."""

    connection = connect_trusted(db_path)
    try:
        return bootstrap_schema(connection)
    except Exception:
        connection.close()
        raise


__all__ = ["bootstrap_database", "bootstrap_schema"]
