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


CATALOG_MODES = ("default", "none")
_CATALOG_SETTING = "series_catalog"


def read_catalog_mode(connection: duckdb.DuckDBPyConnection) -> str | None:
    """Stored series-catalog mode, or None when the database never recorded one (legacy = default)."""

    row = connection.execute(
        "SELECT value FROM meta.lakehouse_setting WHERE key = ?", [_CATALOG_SETTING]
    ).fetchone()
    return None if row is None else str(row[0])


def write_catalog_mode(connection: duckdb.DuckDBPyConnection, mode: str) -> None:
    if mode not in CATALOG_MODES:
        raise ValueError(f"catalog mode must be one of {CATALOG_MODES}, got {mode!r}")
    connection.execute(
        "INSERT OR REPLACE INTO meta.lakehouse_setting (key, value, updated_at) "
        "VALUES (?, ?, CAST(current_timestamp AS TIMESTAMP))",
        [_CATALOG_SETTING, mode],
    )


def bootstrap_database(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    catalog_root: Path | None = DEFAULT_CATALOG_ROOT,
    catalog_mode: str | None = None,
) -> duckdb.DuckDBPyConnection:
    """Open and bootstrap a local DuckDB database, returning its connection.

    After the schemas exist, the Git-versioned semantic series catalog is loaded into
    ``meta.series``. The load is idempotent: unchanged records are skipped, so repeated
    bootstraps neither duplicate rows nor churn ``updated_at``. Pass ``catalog_root=None``
    to bootstrap the schema only for this call.

    D04 (ADR-0067): ``catalog_mode='none'`` records that this database starts from an EMPTY
    series catalog; every later bootstrap — the ingest, silver, gold and promote commands all
    bootstrap first — honours the stored mode and never reloads the default catalog.
    ``catalog_mode='default'`` re-enables it explicitly. The mode never deletes rows.
    """

    connection = connect_trusted(db_path)
    try:
        bootstrap_schema(connection)
        if catalog_mode is not None:
            write_catalog_mode(connection, catalog_mode)
        mode = catalog_mode or read_catalog_mode(connection) or "default"
        if catalog_root is not None and mode == "default":
            load_series_catalog(connection, catalog_root)
        return connection
    except Exception:
        connection.close()
        raise


__all__ = ["CATALOG_MODES", "bootstrap_database", "bootstrap_schema", "read_catalog_mode", "write_catalog_mode"]
