"""register_series: a machine may propose, only a human may verify.

Every record here is SYNTHETIC and written to a temporary database. The Git-versioned catalog
under `catalog/series/` is never touched, and a test proves it.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from src.lakehouse.catalog.registration import (
    RegistrationConflict,
    RegistrationError,
    register_series,
)
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.db.connection import connect_untrusted

from tests.generic._support import SYNTHETIC_SERIES_RECORD


@pytest.fixture()
def connection(tmp_path: Path):
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    try:
        yield connection
    finally:
        connection.close()


def _row(connection, series_id: str = "adhoc:synthetic_series"):
    return connection.execute(
        "SELECT semantic_confidence, semantic_source, status, first_obs, last_obs, "
        "catalog_content_sha256 FROM meta.series WHERE series_id = ?",
        [series_id],
    ).fetchone()


# ------------------------------------------------------------------- happy path


def test_a_proposal_lands_as_a_derived_profiler_draft(connection) -> None:
    result = register_series(connection, SYNTHETIC_SERIES_RECORD)

    assert result.inserted is True
    assert result.unchanged is False
    confidence, source, status, first_obs, last_obs, digest = _row(connection)
    assert (confidence, source, status) == ("derived", "profiler", "draft")
    assert first_obs is None and last_obs is None
    assert digest == result.content_sha256


def test_the_same_proposal_twice_is_idempotent(connection) -> None:
    first = register_series(connection, SYNTHETIC_SERIES_RECORD)
    # TIMESTAMPTZ is read through epoch_ms, the convention this repository already uses:
    # converting one to a Python datetime would require pytz, which is not a dependency.
    before = connection.execute(
        "SELECT epoch_ms(updated_at) FROM meta.series WHERE series_id = ?",
        ["adhoc:synthetic_series"],
    ).fetchone()

    second = register_series(connection, SYNTHETIC_SERIES_RECORD)

    assert second.inserted is False
    assert second.unchanged is True
    assert second.content_sha256 == first.content_sha256
    after = connection.execute(
        "SELECT epoch_ms(updated_at) FROM meta.series WHERE series_id = ?",
        ["adhoc:synthetic_series"],
    ).fetchone()
    assert after == before


def test_the_content_hash_is_deterministic(connection, tmp_path: Path) -> None:
    first = register_series(connection, SYNTHETIC_SERIES_RECORD)

    other = bootstrap_database(tmp_path / "other.duckdb")
    try:
        second = register_series(other, dict(SYNTHETIC_SERIES_RECORD))
    finally:
        other.close()

    assert first.content_sha256 == second.content_sha256


# -------------------------------------------------------- evidence cannot be claimed


@pytest.mark.parametrize("confidence", ["verified", "unknown"])
def test_a_stronger_confidence_is_refused(connection, confidence: str) -> None:
    with pytest.raises(RegistrationError, match="derived"):
        register_series(connection, SYNTHETIC_SERIES_RECORD, confidence=confidence)
    assert _row(connection) is None


@pytest.mark.parametrize("source", ["manual", "source_docs", "source_service"])
def test_a_human_semantic_source_is_refused(connection, source: str) -> None:
    with pytest.raises(RegistrationError, match="profiler"):
        register_series(connection, SYNTHETIC_SERIES_RECORD, semantic_source=source)
    assert _row(connection) is None


@pytest.mark.parametrize("status", ["active", "deprecated"])
def test_a_published_status_is_refused(connection, status: str) -> None:
    with pytest.raises(RegistrationError, match="draft"):
        register_series(connection, SYNTHETIC_SERIES_RECORD, status=status)
    assert _row(connection) is None


def test_evidence_fields_inside_the_record_are_overridden_not_honoured(connection) -> None:
    """A record carrying its own `verified` cannot slip past the parameter checks."""

    smuggled = dict(SYNTHETIC_SERIES_RECORD)
    smuggled["semantic_confidence"] = "verified"
    smuggled["semantic_source"] = "source_service"
    smuggled["status"] = "active"

    register_series(connection, smuggled)

    assert _row(connection)[:3] == ("derived", "profiler", "draft")


# ------------------------------------------------------------------- protection


def test_a_verified_record_is_never_overwritten(connection) -> None:
    """The repository catalog is loaded at bootstrap; those rows are off-limits."""

    verified = connection.execute(
        "SELECT series_id FROM meta.series WHERE semantic_confidence = 'verified' LIMIT 1"
    ).fetchone()
    assert verified is not None, "precondition: bootstrap loaded the repository catalog"
    series_id = verified[0]
    snapshot = (
        "SELECT series_id, name_tr, unit, measure_type, semantic_confidence, "
        "semantic_source, status, catalog_content_sha256, epoch_ms(updated_at) "
        "FROM meta.series WHERE series_id = ?"
    )
    before = connection.execute(snapshot, [series_id]).fetchall()

    record = dict(SYNTHETIC_SERIES_RECORD)
    record["series_id"] = series_id
    record["native_code"] = series_id.split(":", 1)[1]

    with pytest.raises(RegistrationConflict, match="reviewed record"):
        register_series(connection, record, source_id=series_id.split(":", 1)[0])

    assert connection.execute(snapshot, [series_id]).fetchall() == before


def test_an_active_row_is_never_overwritten(connection) -> None:
    register_series(connection, SYNTHETIC_SERIES_RECORD)
    connection.execute(
        "UPDATE meta.series SET status = 'active' WHERE series_id = ?",
        ["adhoc:synthetic_series"],
    )

    changed = dict(SYNTHETIC_SERIES_RECORD)
    changed["name_tr"] = "SYNTHETIC farkli ad"
    with pytest.raises(RegistrationConflict, match="published or withdrawn"):
        register_series(connection, changed)


def test_a_different_draft_for_the_same_id_is_a_conflict(connection) -> None:
    register_series(connection, SYNTHETIC_SERIES_RECORD)

    changed = dict(SYNTHETIC_SERIES_RECORD)
    changed["unit"] = "pct"
    with pytest.raises(RegistrationConflict, match="different content"):
        register_series(connection, changed)

    # The stored draft is untouched.
    assert connection.execute(
        "SELECT unit FROM meta.series WHERE series_id = ?", ["adhoc:synthetic_series"]
    ).fetchone() == ("TRY_mn",)


# ------------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "mutation, expected",
    [
        ({"series_id": "wrong:prefix"}, "namespace"),
        ({"description": "   "}, "required"),
        ({"frequency": "fortnightly"}, "frequency"),
        ({"measure_type": "guess"}, "measure_type"),
        ({"frequency": "weekly"}, "week_anchor"),
        ({"measure_type": "flow_ytd"}, "cumulative_reset"),
        ({"typo_field": "x"}, "unsupported field"),
    ],
)
def test_the_catalog_rules_are_reused_not_reimplemented(
    connection, mutation: dict, expected: str
) -> None:
    """Same eighteen rules as the YAML loader; there is one validator, not two."""

    record = dict(SYNTHETIC_SERIES_RECORD)
    record.update(mutation)

    with pytest.raises(RegistrationError, match=expected):
        register_series(connection, record)
    assert _row(connection) is None


def test_a_failed_validation_leaves_the_catalog_untouched(connection) -> None:
    before = connection.execute("SELECT count(*) FROM meta.series").fetchone()[0]

    record = dict(SYNTHETIC_SERIES_RECORD)
    record["measure_type"] = "nonsense"
    with pytest.raises(RegistrationError):
        register_series(connection, record)

    assert connection.execute("SELECT count(*) FROM meta.series").fetchone()[0] == before


def test_a_non_dict_record_is_refused(connection) -> None:
    with pytest.raises(RegistrationError, match="dict"):
        register_series(connection, ["not", "a", "dict"])  # type: ignore[arg-type]


# ------------------------------------------------------------------ boundaries


def test_registration_never_writes_to_the_yaml_catalog(connection) -> None:
    catalog_root = Path("catalog/series")
    before = {path: path.read_bytes() for path in sorted(catalog_root.glob("*.yml"))}
    assert before, "precondition: the repository catalog exists"

    register_series(connection, SYNTHETIC_SERIES_RECORD)

    after = {path: path.read_bytes() for path in sorted(catalog_root.glob("*.yml"))}
    assert after == before


def test_coverage_columns_are_neither_written_nor_cleared(connection) -> None:
    register_series(connection, SYNTHETIC_SERIES_RECORD)
    connection.execute(
        "UPDATE meta.series SET first_obs = DATE '2020-01-01', last_obs = DATE '2020-12-31' "
        "WHERE series_id = ?",
        ["adhoc:synthetic_series"],
    )

    # Re-registering the identical record must not disturb operational coverage.
    register_series(connection, SYNTHETIC_SERIES_RECORD)

    assert _row(connection)[3:5] == (
        __import__("datetime").date(2020, 1, 1),
        __import__("datetime").date(2020, 12, 31),
    )


def test_a_read_only_connection_cannot_register(tmp_path: Path) -> None:
    db_path = tmp_path / "lakehouse.duckdb"
    bootstrap_database(db_path).close()

    untrusted = connect_untrusted(db_path)
    try:
        with pytest.raises(duckdb.Error):
            register_series(untrusted, SYNTHETIC_SERIES_RECORD)
    finally:
        untrusted.close()
