import pytest

from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.db.connection import (
    connect_trusted,
    connect_untrusted,
)
from src.lakehouse.query.executor import QueryExecutor, TrustedConnectionError


def _setting(connection, name):
    return connection.execute("SELECT current_setting(?)", [name]).fetchone()[0]


def test_untrusted_connection_is_read_only_hardened_and_locked(tmp_path):
    db = tmp_path / "lakehouse.duckdb"
    bootstrap_database(db).close()

    untrusted = connect_untrusted(db)
    try:
        assert _setting(untrusted, "access_mode") == "read_only"
        assert _setting(untrusted, "enable_external_access") is False
        assert _setting(untrusted, "autoload_known_extensions") is False
        assert _setting(untrusted, "autoinstall_known_extensions") is False
        assert _setting(untrusted, "allow_community_extensions") is False
        assert _setting(untrusted, "allow_unsigned_extensions") is False
        assert _setting(untrusted, "lock_configuration") is True
    finally:
        untrusted.close()


@pytest.mark.parametrize(
    "setting",
    ["enable_external_access", "allow_community_extensions", "allow_unsigned_extensions"],
)
def test_locked_untrusted_settings_cannot_be_reopened(tmp_path, setting):
    db = tmp_path / "lakehouse.duckdb"
    bootstrap_database(db).close()

    untrusted = connect_untrusted(db)
    try:
        with pytest.raises(Exception):
            untrusted.execute(f"SET {setting} = true")
    finally:
        untrusted.close()


def test_trusted_connection_is_not_locked(tmp_path):
    db = tmp_path / "lakehouse.duckdb"
    connection = connect_trusted(db)
    try:
        assert _setting(connection, "enable_external_access") is False
        assert _setting(connection, "lock_configuration") is False
    finally:
        connection.close()


def test_query_executor_rejects_trusted_connection(tmp_path):
    db = tmp_path / "lakehouse.duckdb"
    connection = connect_trusted(db)
    try:
        with pytest.raises(TrustedConnectionError):
            QueryExecutor(connection)
    finally:
        connection.close()


def test_query_executor_rejects_read_only_but_unlocked_connection(tmp_path):
    db = tmp_path / "lakehouse.duckdb"
    bootstrap_database(db).close()
    # Read-only but WITHOUT the untrusted hardening/lock -> still refused.
    conn = connect_trusted(db, read_only=True)
    try:
        with pytest.raises(TrustedConnectionError):
            QueryExecutor(conn)
    finally:
        conn.close()


def test_query_executor_accepts_untrusted_connection(tmp_path):
    db = tmp_path / "lakehouse.duckdb"
    bootstrap_database(db).close()
    untrusted = connect_untrusted(db)
    try:
        executor = QueryExecutor(untrusted)
        result = executor.execute("SELECT 1 AS value")
        assert result.rows == [(1,)]
        assert result.columns == ["value"]
    finally:
        untrusted.close()
