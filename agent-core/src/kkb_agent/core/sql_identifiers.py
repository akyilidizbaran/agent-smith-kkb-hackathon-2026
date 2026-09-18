"""Deterministic quoting for known SQL identifiers."""

from __future__ import annotations

import re
from collections.abc import Iterable

_SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WORD_CHAR = re.compile(r"[A-Za-z0-9_$]")


def quote_identifier(identifier: str) -> str:
    """Return one SQL-standard double-quoted identifier."""
    return '"' + str(identifier).replace('"', '""') + '"'


def _is_boundary(text: str, index: int) -> bool:
    return index < 0 or index >= len(text) or _WORD_CHAR.fullmatch(text[index]) is None


def quote_known_identifiers(sql: str, identifiers: Iterable[str]) -> str:
    """Quote known non-simple identifiers outside SQL literals and comments."""
    names = sorted(
        {
            str(identifier)
            for identifier in identifiers
            if str(identifier) and not _SIMPLE_IDENTIFIER.fullmatch(str(identifier))
        },
        key=len,
        reverse=True,
    )
    if not names or not sql:
        return sql

    out: list[str] = []
    index = 0
    length = len(sql)
    quote: str | None = None
    while index < length:
        if quote == "'":
            out.append(sql[index])
            if sql[index] == "'":
                if index + 1 < length and sql[index + 1] == "'":
                    out.append(sql[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if quote == '"':
            out.append(sql[index])
            if sql[index] == '"':
                if index + 1 < length and sql[index + 1] == '"':
                    out.append(sql[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            end = length if end < 0 else end
            out.append(sql[index:end])
            index = end
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            end = length if end < 0 else end + 2
            out.append(sql[index:end])
            index = end
            continue
        if sql[index] in ("'", '"'):
            quote = sql[index]
            out.append(sql[index])
            index += 1
            continue

        matched = next(
            (
                name
                for name in names
                if sql.startswith(name, index)
                and _is_boundary(sql, index - 1)
                and _is_boundary(sql, index + len(name))
            ),
            None,
        )
        if matched is not None:
            out.append(quote_identifier(matched))
            index += len(matched)
        else:
            out.append(sql[index])
            index += 1
    return "".join(out)


__all__ = ["quote_identifier", "quote_known_identifiers"]
