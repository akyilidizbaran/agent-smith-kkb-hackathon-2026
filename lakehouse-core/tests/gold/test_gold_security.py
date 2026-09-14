"""Gold's security boundary: read-only, parameterized, and unable to change the rules.

Two properties matter here. First, an agent that controls the arguments must not be able to
reach past them -- neither into SQL nor into the aggregation policy. Second, Gold must run on
the same hardened read-only connection the agent already uses, because a tool that needs a
writable handle would hand the model far more than it needs.
"""

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.db.connection import connect_untrusted
from src.lakehouse.gold import (
    GoldError,
    align_frequency,
    decompose_cumulative,
    join_on_period,
)
from src.lakehouse.silver.foundation import materialize_fact_observation_snapshot

from ._support import SYNTHETIC_SERIES, add_synthetic_series, staging_rows


STOCK = "synthetic:stock_monthly"


def _published(tmp_path: Path) -> Path:
    """Publish a small Silver snapshot, then close the trusted handle."""

    db_path = tmp_path / "lakehouse.duckdb"
    connection = bootstrap_database(db_path)
    try:
        add_synthetic_series(connection, SYNTHETIC_SERIES["stock_monthly"])
        materialize_fact_observation_snapshot(
            connection,
            staging_rows(
                STOCK, [(date(2026, 1, 31), "100.0"), (date(2026, 2, 28), "110.0")]
            ),
        )
    finally:
        connection.close()
    return db_path


# ------------------------------------------------------------------- injection


@pytest.mark.parametrize(
    "hostile",
    [
        "evds:TP.KTF12'; DROP TABLE silver.fact_observation; --",
        "' OR '1'='1",
        "x' UNION SELECT * FROM meta.series --",
        "'; UPDATE meta.series SET measure_type='flow_periodic'; --",
        "synthetic:stock_monthly'--",
    ],
)
def test_a_hostile_series_id_is_a_value_not_sql(tmp_path: Path, hostile: str) -> None:
    """Every identifier is bound as a parameter, so it can only ever fail to match a row."""

    db_path = _published(tmp_path)
    connection = bootstrap_database(db_path)
    try:
        with pytest.raises(GoldError) as excinfo:
            align_frequency(connection, hostile, "monthly")
        assert excinfo.value.refusal.reason == "SERIES_NOT_CATALOGUED"

        # Nothing was dropped, updated or leaked.
        assert connection.execute(
            "SELECT count(*) FROM silver.fact_observation"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT measure_type FROM meta.series WHERE series_id = ?", [STOCK]
        ).fetchone() == ("stock",)
    finally:
        connection.close()


@pytest.mark.parametrize("target", ["monthly'; DROP TABLE meta.series; --", "MONTHLY", ""])
def test_a_hostile_target_frequency_is_refused_before_any_sql(
    tmp_path: Path, target: str
) -> None:
    db_path = _published(tmp_path)
    connection = bootstrap_database(db_path)
    try:
        with pytest.raises(GoldError) as excinfo:
            align_frequency(connection, STOCK, target)
        assert excinfo.value.refusal.reason == "UNSUPPORTED_TARGET_FREQUENCY"
        assert connection.execute(
            "SELECT count(*) FROM meta.series"
        ).fetchone()[0] > 0
    finally:
        connection.close()


def test_no_gold_function_takes_a_semantic_rule_as_a_parameter() -> None:
    """The agent chooses the question; the catalog chooses the arithmetic."""

    forbidden = {
        "measure_type",
        "default_agg",
        "week_anchor",
        "aggregation",
        "frequency",
        "source_frequency",
        "semantic_confidence",
        "unit",
        "cumulative_reset",
    }
    for function in (align_frequency, decompose_cumulative, join_on_period):
        parameters = set(inspect.signature(function).parameters)
        assert not parameters & forbidden, f"{function.__name__} exposes {parameters & forbidden}"


# ---------------------------------------------------- runs on the agent surface


def test_gold_runs_on_the_hardened_read_only_connection(tmp_path: Path) -> None:
    """The same connection profile the agent gets is enough for every Gold function."""

    db_path = _published(tmp_path)
    untrusted = connect_untrusted(db_path)
    try:
        assert untrusted.execute(
            "SELECT current_setting('access_mode')"
        ).fetchone()[0] == "read_only"
        assert untrusted.execute(
            "SELECT current_setting('enable_external_access')"
        ).fetchone()[0] is False

        aligned = align_frequency(untrusted, STOCK, "monthly")
        assert [float(value) for value in aligned["value"]] == [100.0, 110.0]

        joined = join_on_period(untrusted, [STOCK], "monthly")
        assert len(joined) == 2
    finally:
        untrusted.close()


def test_gold_never_writes(tmp_path: Path) -> None:
    """A read-only connection would refuse a write, so this proves none is attempted."""

    db_path = _published(tmp_path)
    untrusted = connect_untrusted(db_path)
    try:
        align_frequency(untrusted, STOCK, "quarterly")
        # If any Gold code path had tried to write, the call above would have raised.
        with pytest.raises(duckdb.Error):
            untrusted.execute("CREATE TABLE gold_probe AS SELECT 1")
    finally:
        untrusted.close()


def test_external_file_access_stays_closed_while_gold_runs(tmp_path: Path) -> None:
    db_path = _published(tmp_path)
    untrusted = connect_untrusted(db_path)
    try:
        align_frequency(untrusted, STOCK, "monthly")
        with pytest.raises(duckdb.PermissionException) as excinfo:
            untrusted.execute("SELECT * FROM read_csv_auto('/etc/passwd')")
        assert "file system operations are disabled" in str(excinfo.value)
    finally:
        untrusted.close()


# ------------------------------------------------------------------ immutability


def test_silver_and_the_catalog_are_unchanged_by_every_gold_function(
    tmp_path: Path,
) -> None:
    db_path = _published(tmp_path)
    connection = bootstrap_database(db_path)
    try:
        add_synthetic_series(connection, SYNTHETIC_SERIES["cumulative_monthly"])
        # TIMESTAMPTZ is read through epoch_ms, the convention this repository already uses:
        # converting one to a Python datetime would require pytz, which is not a dependency.
        silver_snapshot = (
            "SELECT series_id, entity_id, observation_date, value, quality_flag, "
            "artifact_sha256, vintage_id, run_id, epoch_ms(fetched_at) "
            "FROM silver.fact_observation ORDER BY observation_date"
        )
        silver_before = connection.execute(silver_snapshot).fetchall()
        catalog_before = connection.execute(
            "SELECT series_id, measure_type, default_agg, first_obs, last_obs "
            "FROM meta.series ORDER BY series_id"
        ).fetchall()

        align_frequency(connection, STOCK, "monthly")
        align_frequency(connection, STOCK, "quarterly")
        join_on_period(connection, [STOCK], "monthly")
        with pytest.raises(GoldError):
            decompose_cumulative(connection, STOCK)

        assert connection.execute(silver_snapshot).fetchall() == silver_before
        assert (
            connection.execute(
                "SELECT series_id, measure_type, default_agg, first_obs, last_obs "
                "FROM meta.series ORDER BY series_id"
            ).fetchall()
            == catalog_before
        )
    finally:
        connection.close()


def test_gold_creates_no_relations_of_its_own(tmp_path: Path) -> None:
    db_path = _published(tmp_path)
    connection = bootstrap_database(db_path)
    try:
        before = set(
            row[0]
            for row in connection.execute(
                "SELECT table_schema || '.' || table_name FROM information_schema.tables"
            ).fetchall()
        )
        align_frequency(connection, STOCK, "monthly")
        join_on_period(connection, [STOCK], "quarterly")
        after = set(
            row[0]
            for row in connection.execute(
                "SELECT table_schema || '.' || table_name FROM information_schema.tables"
            ).fetchall()
        )
        assert before == after
    finally:
        connection.close()
