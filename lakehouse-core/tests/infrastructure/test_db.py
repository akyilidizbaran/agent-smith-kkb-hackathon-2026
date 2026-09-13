from pathlib import Path
from datetime import datetime, timezone

import duckdb

from src.lakehouse.db.bootstrap import bootstrap_database, bootstrap_schema
from src.lakehouse.db.connection import connect


def test_bootstrap_creates_required_schemas_and_meta_tables(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    schemas = {
        row[0]
        for row in connection.execute(
            "SELECT schema_name FROM information_schema.schemata"
        ).fetchall()
    }
    tables = {
        row[0]
        for row in connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'meta'
            """
        ).fetchall()
    }

    assert {"meta", "bronze", "silver", "gold"} <= schemas
    assert {"source", "artifact", "artifact_request", "run", "dataset_version"} <= tables
    connection.close()


def test_bootstrap_is_idempotent(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")

    bootstrap_schema(connection)
    bootstrap_schema(connection)

    assert connection.execute("SELECT count(*) FROM meta.artifact").fetchone() == (0,)
    connection.close()


def test_connection_applies_only_supported_security_settings() -> None:
    connection = connect(":memory:")

    for setting in (
        "enable_external_access",
        "autoload_known_extensions",
        "autoinstall_known_extensions",
    ):
        assert connection.execute(f"SELECT current_setting('{setting}')").fetchone()[0] is False
    connection.close()


def test_bootstrap_upgrades_legacy_artifact_table_idempotently(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.duckdb"
    connection = duckdb.connect(str(database_path))
    connection.execute("CREATE SCHEMA meta")
    connection.execute("CREATE SCHEMA bronze")
    connection.execute("CREATE SCHEMA silver")
    connection.execute("CREATE SCHEMA gold")
    connection.execute(
        """
        CREATE TABLE meta.artifact (
            artifact_sha256 VARCHAR PRIMARY KEY,
            source_id VARCHAR NOT NULL,
            dataset_id VARCHAR NOT NULL,
            locator VARCHAR NOT NULL,
            media_type VARCHAR NOT NULL,
            byte_size BIGINT NOT NULL,
            http_status INTEGER,
            fetched_at TIMESTAMPTZ NOT NULL,
            raw_path VARCHAR NOT NULL,
            first_seen_at TIMESTAMPTZ NOT NULL,
            last_seen_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    timestamp = datetime(2026, 9, 9, tzinfo=timezone.utc)
    connection.execute(
        """
        INSERT INTO meta.artifact VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ["a" * 64, "legacy", "dataset", "fixture://legacy", "application/json", 1, 200, timestamp, "legacy.json", timestamp, timestamp],
    )
    connection.close()

    upgraded = bootstrap_database(database_path)
    assert upgraded.execute(
        "SELECT count(*) FROM meta.artifact_request"
    ).fetchone() == (0,)
    assert upgraded.execute(
        "SELECT count(*) FROM meta.artifact WHERE source_id = 'legacy'"
    ).fetchone() == (1,)
    bootstrap_schema(upgraded)
    assert upgraded.execute("SELECT count(*) FROM meta.artifact").fetchone() == (1,)
    upgraded.close()
