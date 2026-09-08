import pytest

from src.lakehouse.security.sql_guard import SqlGuardError, validate_read_only_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH values_cte AS (SELECT 1 AS value) SELECT value FROM values_cte",
        "/* harmless comment */ SELECT 'DROP' AS value; -- trailing comment",
    ],
)
def test_read_only_select_forms_are_allowed(sql: str) -> None:
    assert validate_read_only_sql(sql).startswith(("SELECT", "WITH", "/*"))


@pytest.mark.parametrize(
    "keyword",
    [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "CREATE",
        "ALTER",
        "ATTACH",
        "DETACH",
        "COPY",
        "INSTALL",
        "LOAD",
        "EXPORT",
        "IMPORT",
        "PRAGMA",
        "CALL",
        "SET",
        "RESET",
        "MERGE",
        "TRUNCATE",
        "VACUUM",
    ],
)
def test_write_and_configuration_statements_are_denied(keyword: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_read_only_sql(f"{keyword} something")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('secret.csv')",
        "SELECT * FROM read_parquet('secret.parquet')",
        "SELECT * FROM glob('*.csv')",
        "SELECT * FROM \"read_csv\"('secret.csv')",
        "SELECT * FROM read_json('secret.json')",
        "SELECT * FROM read_text('secret.txt')",
        "SELECT * FROM read_blob('secret.bin')",
        "SELECT * FROM parquet_scan('secret.parquet')",
        "SELECT * FROM query_table('secret.parquet')",
    ],
)
def test_external_file_access_is_denied(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_read_only_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; DROP TABLE meta.artifact",
        "SELECT 1 /* comment */; DROP TABLE meta.artifact",
        "SEL/**/ECT 1",
        "-- comment\nDROP TABLE meta.artifact",
        "SELECT 1; SELECT 2",
    ],
)
def test_comments_whitespace_and_multistatements_do_not_bypass_guard(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_read_only_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM query('SELECT 42')",
        "SELECT 1 FROM query('SELECT 1')",
        "WITH x AS (SELECT * FROM query('SELECT 1')) SELECT * FROM x",
        "SELECT * FROM query('SELECT * FROM read_csv(''secret.csv'')')",
        "SELECT * FROM \"query\"('SELECT 1')",
    ],
)
def test_duckdb_query_table_function_is_denied(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_read_only_sql(sql)
