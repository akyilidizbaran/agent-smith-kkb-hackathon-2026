"""Shared fixtures for the Gold test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.lakehouse.db.bootstrap import bootstrap_database


@pytest.fixture()
def connection(tmp_path: Path):
    """A bootstrapped trusted database holding the real Git-versioned catalog."""

    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    try:
        yield connection
    finally:
        connection.close()
