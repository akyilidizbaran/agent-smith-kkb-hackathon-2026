"""Configurable DuckDB connections with defensive runtime settings."""

from __future__ import annotations

from pathlib import Path

import duckdb


DEFAULT_DB_PATH = Path("data/lakehouse.duckdb")
"""Default local database path; callers may provide an explicit path."""

_SECURITY_SETTINGS = (
    "enable_external_access",
    "autoload_known_extensions",
    "autoinstall_known_extensions",
)
"""Baseline safeguards applied to every connection (trusted and untrusted)."""

_UNTRUSTED_EXTENSION_SETTINGS = (
    "allow_community_extensions",
    "allow_unsigned_extensions",
)
"""Extra extension safeguards applied only to guarded agent connections."""

_LOCK_SETTING = "lock_configuration"
"""Final hardening: freezes configuration so no later SET can relax it."""


def _available_settings(connection: duckdb.DuckDBPyConnection) -> set[str]:
    """Return the runtime setting names DuckDB actually exposes."""

    return {
        row[0] for row in connection.execute("SELECT name FROM duckdb_settings()").fetchall()
    }


def apply_runtime_security(connection: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    """Disable supported DuckDB external access and extension auto-loading settings.

    The setting catalogue is queried at runtime so unsupported names are never
    guessed or silently sent to DuckDB. External access is required for this
    foundation; the extension settings are defence-in-depth when available.
    """

    available = _available_settings(connection)
    if "enable_external_access" not in available:
        raise RuntimeError("DuckDB does not expose enable_external_access")

    applied: list[str] = []
    for setting in _SECURITY_SETTINGS:
        if setting in available:
            connection.execute(f"SET {setting} = false")
            applied.append(setting)
    return tuple(applied)


def apply_untrusted_hardening(connection: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    """Apply defence-in-depth hardening for guarded agent SQL connections.

    Assumes :func:`apply_runtime_security` has already run. Extension safeguards
    are disabled first; ``lock_configuration`` is applied LAST so that no
    subsequent ``SET`` can relax any safeguard for the life of the connection.
    Every name is verified against the runtime catalogue before use.
    """

    available = _available_settings(connection)
    applied: list[str] = []
    for setting in _UNTRUSTED_EXTENSION_SETTINGS:
        if setting in available:
            connection.execute(f"SET {setting} = false")
            applied.append(setting)
    # lock_configuration MUST be the final safeguard applied.
    if _LOCK_SETTING in available:
        connection.execute(f"SET {_LOCK_SETTING} = true")
        applied.append(_LOCK_SETTING)
    return tuple(applied)


def _open(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    read_only: bool = False,
) -> duckdb.DuckDBPyConnection:
    """Open a local DuckDB connection and apply baseline runtime safeguards."""

    path = Path(db_path)
    if not read_only and str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(path), read_only=read_only)
    try:
        apply_runtime_security(connection)
    except Exception:
        connection.close()
        raise
    return connection


def connect_trusted(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    read_only: bool = False,
) -> duckdb.DuckDBPyConnection:
    """Open a writable internal connection for controlled infrastructure operations.

    DuckDB external access remains disabled. Trusted code can use
    ParquetStorage.register_local_parquet to register a validated local file
    without exposing arbitrary filesystem or network SQL access. The
    configuration is intentionally NOT locked so internal operations retain
    normal capabilities; agent SQL must never run on a trusted connection.
    """

    return _open(db_path, read_only=read_only)


def connect_untrusted(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> duckdb.DuckDBPyConnection:
    """Open a read-only, hardened connection intended for guarded agent SQL.

    Baseline safeguards plus extension safeguards are applied, and the
    configuration is locked as the final step. This is the only connection
    profile accepted by :class:`~lakehouse.query.executor.QueryExecutor`.
    """

    connection = _open(db_path, read_only=True)
    try:
        apply_untrusted_hardening(connection)
    except Exception:
        connection.close()
        raise
    return connection


def connect(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    read_only: bool = False,
) -> duckdb.DuckDBPyConnection:
    """Backward-compatible alias for the trusted internal connection."""

    return connect_trusted(db_path, read_only=read_only)


__all__ = [
    "DEFAULT_DB_PATH",
    "apply_runtime_security",
    "apply_untrusted_hardening",
    "connect",
    "connect_trusted",
    "connect_untrusted",
]
