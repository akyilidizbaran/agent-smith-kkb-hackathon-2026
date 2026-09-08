from pathlib import Path

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
    assert {"source", "artifact", "run", "dataset_version"} <= tables
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
