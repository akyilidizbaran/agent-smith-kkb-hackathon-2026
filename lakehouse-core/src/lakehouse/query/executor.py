"""Bounded read-only DuckDB query execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from ..security.sql_guard import validate_read_only_sql


class TrustedConnectionError(ValueError):
    """Raised when QueryExecutor is given a connection outside the agent profile."""


def _setting(connection: duckdb.DuckDBPyConnection, name: str) -> Any:
    """Return a DuckDB runtime setting value, or None if it is not exposed."""

    available = {
        row[0] for row in connection.execute("SELECT name FROM duckdb_settings()").fetchall()
    }
    if name not in available:
        return None
    return connection.execute("SELECT current_setting(?)", [name]).fetchone()[0]


def _verify_untrusted_connection(connection: duckdb.DuckDBPyConnection) -> None:
    """Ensure the connection matches the read-only, hardened agent profile.

    The check uses only real DuckDB runtime settings (verified against the
    catalogue): a writable/trusted connection is refused so that the SQL Guard
    is never the sole barrier for agent-generated SQL.
    """

    access_mode = _setting(connection, "access_mode")
    if access_mode != "read_only":
        raise TrustedConnectionError(
            "QueryExecutor requires a read-only connection "
            f"(access_mode={access_mode!r}); use connect_untrusted() for agent SQL"
        )
    if _setting(connection, "enable_external_access") is not False:
        raise TrustedConnectionError(
            "QueryExecutor requires enable_external_access=false; "
            "use connect_untrusted() for agent SQL"
        )
    # lock_configuration is set only by connect_untrusted's hardening step and
    # marks a fully hardened agent connection.
    if _setting(connection, "lock_configuration") is not True:
        raise TrustedConnectionError(
            "QueryExecutor requires a hardened connection with lock_configuration=true; "
            "use connect_untrusted() for agent SQL"
        )


@dataclass(frozen=True)
class QueryResult:
    """Small internal result envelope for bounded SELECT queries."""

    columns: list[str]
    rows: list[tuple[Any, ...]]
    row_count: int
    truncated: bool
    executed_sql: str


class QueryExecutor:
    """Execute only guarded, bounded SQL on an untrusted read-only connection."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        _verify_untrusted_connection(connection)
        self._connection = connection

    def execute(self, sql: str, *, max_rows: int = 1_000) -> QueryResult:
        """Run a read-only query and retain at most ``max_rows`` rows."""

        if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
            raise ValueError("max_rows must be a positive integer")
        executed_sql = validate_read_only_sql(sql)
        cursor = self._connection.execute(executed_sql)
        columns = [description[0] for description in cursor.description or ()]
        rows = cursor.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        if truncated:
            rows = rows[:max_rows]
        return QueryResult(
            columns=columns,
            rows=[tuple(row) for row in rows],
            row_count=len(rows),
            truncated=truncated,
            executed_sql=executed_sql,
        )


__all__ = ["QueryExecutor", "QueryResult", "TrustedConnectionError"]
