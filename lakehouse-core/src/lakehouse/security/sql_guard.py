"""Small lexical allowlist for agent-generated read-only DuckDB SQL."""

from __future__ import annotations

from dataclasses import dataclass


class SqlGuardError(ValueError):
    """Raised when SQL is outside the read-only query contract."""


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str


_DENIED_KEYWORDS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "drop",
        "create",
        "alter",
        "attach",
        "detach",
        "copy",
        "install",
        "load",
        "export",
        "import",
        "pragma",
        "call",
        "set",
        "reset",
        "use",
        "merge",
        "truncate",
        "grant",
        "revoke",
        "vacuum",
    }
)
_DENIED_EXTERNAL_NAMES = frozenset(
    {
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "parquet_scan",
        "read_json",
        "read_json_auto",
        "read_ndjson",
        "read_text",
        "read_blob",
        "glob",
        "httpfs",
        "csv_scan",
        "arrow_scan",
        "delta_scan",
        "iceberg_scan",
        "sqlite_scan",
        "postgres_scan",
        "mysql_scan",
        "query",
        "query_table",
    }
)


def _tokenize(sql: str) -> list[_Token]:
    if not isinstance(sql, str) or not sql.strip():
        raise SqlGuardError("SQL must be a non-empty string")

    tokens: list[_Token] = []
    index = 0
    while index < len(sql):
        character = sql[index]
        if character.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = len(sql) if newline == -1 else newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end == -1:
                raise SqlGuardError("unterminated SQL comment")
            index = end + 2
            continue
        if character in "'\"`":
            quote = character
            end = index + 1
            while end < len(sql):
                if sql[end] == quote:
                    if end + 1 < len(sql) and sql[end + 1] == quote and quote != "`":
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            else:
                raise SqlGuardError("unterminated SQL quoted value")
            kind = "STRING" if quote == "'" else "QUOTED_IDENTIFIER"
            tokens.append(_Token(kind, sql[index:end]))
            index = end
            continue
        if character.isalpha() or character == "_":
            end = index + 1
            while end < len(sql) and (sql[end].isalnum() or sql[end] in "_$"):
                end += 1
            tokens.append(_Token("WORD", sql[index:end].lower()))
            index = end
            continue
        tokens.append(_Token("PUNCT", character))
        index += 1
    return tokens


def validate_read_only_sql(sql: str) -> str:
    """Validate and return SQL whose only top-level form is a read-only query."""

    tokens = _tokenize(sql)
    semicolon_positions = [index for index, token in enumerate(tokens) if token.text == ";"]
    if semicolon_positions:
        if len(semicolon_positions) != 1 or semicolon_positions[0] != len(tokens) - 1:
            raise SqlGuardError("multiple SQL statements are not allowed")
        tokens = tokens[:-1]

    if not tokens or tokens[0].kind != "WORD" or tokens[0].text not in {"select", "with"}:
        raise SqlGuardError("only SELECT or WITH ... SELECT queries are allowed")

    words = {token.text for token in tokens if token.kind == "WORD"}
    denied = words & _DENIED_KEYWORDS
    if denied:
        raise SqlGuardError(f"denied SQL keyword: {sorted(denied)[0]}")
    external = words & _DENIED_EXTERNAL_NAMES
    quoted_external = {
        token.text[1:-1].lower()
        for token in tokens
        if token.kind == "QUOTED_IDENTIFIER" and token.text[1:-1].lower() in _DENIED_EXTERNAL_NAMES
    }
    if external or quoted_external:
        denied_name = sorted(external | quoted_external)[0]
        raise SqlGuardError(f"external access function is denied: {denied_name}")
    if tokens[0].text == "with" and "select" not in words:
        raise SqlGuardError("WITH query must contain a SELECT")

    for index, token in enumerate(tokens[:-1]):
        if token.kind == "WORD" and token.text in {"from", "join"}:
            next_token = tokens[index + 1]
            if next_token.kind == "STRING":
                raise SqlGuardError("external file paths are not allowed in FROM or JOIN")

    return sql.strip()


__all__ = ["SqlGuardError", "validate_read_only_sql"]
