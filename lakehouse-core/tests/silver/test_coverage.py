"""Catalog coverage derived from the Silver snapshot.

``meta.series.first_obs`` / ``last_obs`` are the agent layer's out-of-range guard: when a user
asks about 2015 the agent is supposed to answer "this series starts in 2021" instead of
inventing something. That guard is only as good as these two columns, and until now nothing
computed them.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pytest

from src.lakehouse.catalog.series import load_series_catalog
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.silver.coverage import CoverageError, refresh_series_coverage
from src.lakehouse.silver.foundation import (
    SilverValidationError,
    materialize_fact_observation_snapshot,
)


FETCHED_AT = datetime(2026, 9, 11, tzinfo=timezone.utc)

_SERIES = {
    "evds:TP.KTF12": ("evds", "evds_housing_interest"),
    "evds:TP.KFE.TR": ("evds", "evds_housing_price_index"),
    "evds:TP.FG.J0": ("evds", "evds_cpi"),
    "bddk_weekly:5690_3": ("bddk_weekly", "bddk_weekly_housing_loans"),
}


def _rows(series_id: str, observation_dates: list[date], *, digest: str = "a") -> list[dict]:
    source_id, dataset_id = _SERIES[series_id]
    return [
        {
            "series_id": series_id,
            "entity_id": "bddk:10001" if source_id == "bddk_weekly" else None,
            "observation_date": observation_date,
            "period_start": None,
            "period_end": None,
            "value_raw": "1.5",
            "source_id": source_id,
            "dataset_id": dataset_id,
            "artifact_sha256": digest * 64,
            "fetched_at": FETCHED_AT,
            "schema_version": "coverage_test.v1",
            "vintage_id": f"artifact:{digest * 64}",
            "run_id": None,
            "source_warning": None,
        }
        for observation_date in observation_dates
    ]


def _staging(*groups: list[dict]) -> pd.DataFrame:
    records = [row for group in groups for row in group]
    frame = pd.DataFrame.from_records(records)
    frame["value_raw"] = pd.Series(
        [row["value_raw"] for row in records], dtype=object, index=frame.index
    )
    return frame


def _coverage(connection: duckdb.DuckDBPyConnection) -> dict[str, tuple]:
    return {
        row[0]: (row[1], row[2])
        for row in connection.execute(
            "SELECT series_id, first_obs, last_obs FROM meta.series ORDER BY series_id"
        ).fetchall()
    }


@pytest.fixture()
def connection(tmp_path: Path):
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    try:
        yield connection
    finally:
        connection.close()


# ----------------------------------------------------------------- computation


def test_single_series_gets_its_own_min_and_max(connection) -> None:
    materialize_fact_observation_snapshot(
        connection,
        _staging(
            _rows(
                "evds:TP.KTF12",
                [date(2021, 1, 1), date(2023, 6, 30), date(2026, 6, 26)],
            )
        ),
    )

    coverage = _coverage(connection)
    assert coverage["evds:TP.KTF12"] == (date(2021, 1, 1), date(2026, 6, 26))


def test_each_series_keeps_a_separate_window(connection) -> None:
    materialize_fact_observation_snapshot(
        connection,
        _staging(
            _rows("evds:TP.KTF12", [date(2021, 1, 1), date(2026, 6, 26)]),
            _rows("evds:TP.FG.J0", [date(2024, 1, 31), date(2025, 12, 31)], digest="b"),
            _rows("bddk_weekly:5690_3", [date(2022, 3, 4)], digest="c"),
        ),
    )

    coverage = _coverage(connection)
    assert coverage["evds:TP.KTF12"] == (date(2021, 1, 1), date(2026, 6, 26))
    assert coverage["evds:TP.FG.J0"] == (date(2024, 1, 31), date(2025, 12, 31))
    assert coverage["bddk_weekly:5690_3"] == (date(2022, 3, 4), date(2022, 3, 4))
    # A catalogued series that was never materialized has no window to advertise.
    assert coverage["evds:TP.KFE.TR"] == (None, None)


def test_a_narrower_snapshot_recomputes_rather_than_widens(connection) -> None:
    materialize_fact_observation_snapshot(
        connection,
        _staging(
            _rows("evds:TP.KTF12", [date(2021, 1, 1), date(2026, 6, 26)])
        ),
    )
    assert _coverage(connection)["evds:TP.KTF12"] == (date(2021, 1, 1), date(2026, 6, 26))

    materialize_fact_observation_snapshot(
        connection,
        _staging(_rows("evds:TP.KTF12", [date(2024, 5, 3), date(2024, 5, 10)])),
    )

    # The old, wider window must not survive a whole-snapshot replacement.
    assert _coverage(connection)["evds:TP.KTF12"] == (date(2024, 5, 3), date(2024, 5, 10))


def test_a_series_dropped_from_the_snapshot_loses_its_window(connection) -> None:
    materialize_fact_observation_snapshot(
        connection,
        _staging(
            _rows("evds:TP.KTF12", [date(2021, 1, 1)]),
            _rows("evds:TP.FG.J0", [date(2025, 1, 31)], digest="b"),
        ),
    )
    assert _coverage(connection)["evds:TP.FG.J0"] == (date(2025, 1, 31), date(2025, 1, 31))

    materialize_fact_observation_snapshot(
        connection, _staging(_rows("evds:TP.KTF12", [date(2021, 1, 1)]))
    )

    coverage = _coverage(connection)
    assert coverage["evds:TP.KTF12"] == (date(2021, 1, 1), date(2021, 1, 1))
    # Stale coverage for a series nobody publishes any more would be a silent lie.
    assert coverage["evds:TP.FG.J0"] == (None, None)


def test_an_empty_snapshot_clears_every_window(connection) -> None:
    """An empty snapshot is a legitimate state, not an error."""

    materialize_fact_observation_snapshot(
        connection, _staging(_rows("evds:TP.KTF12", [date(2021, 1, 1)]))
    )
    assert _coverage(connection)["evds:TP.KTF12"] != (None, None)

    empty = _staging(_rows("evds:TP.KTF12", [date(2021, 1, 1)])).iloc[0:0]
    materialize_fact_observation_snapshot(connection, empty)

    assert connection.execute(
        "SELECT count(*) FROM silver.fact_observation"
    ).fetchone() == (0,)
    assert all(window == (None, None) for window in _coverage(connection).values())


def test_refresh_is_not_hard_coded_to_known_series(connection) -> None:
    """A series added to the catalog later is covered with no code change."""

    connection.execute(
        """
        INSERT INTO meta.series (
            series_id, source_id, native_code, dataset_id, name_tr, description,
            frequency, unit, measure_type, semantic_confidence, semantic_source,
            status, catalog_content_sha256
        ) VALUES (
            'evds:TP.LATER', 'evds', 'TP.LATER', 'evds_cpi', 'Sonradan', 'Test',
            'monthly', 'index', 'index', 'derived', 'manual', 'active', 'd'
        )
        """
    )
    rows = _rows("evds:TP.FG.J0", [date(2025, 1, 31)])
    for row in rows:
        row["series_id"] = "evds:TP.LATER"
    materialize_fact_observation_snapshot(connection, _staging(rows))

    assert _coverage(connection)["evds:TP.LATER"] == (date(2025, 1, 31), date(2025, 1, 31))


# ------------------------------------------------------------------ robustness


def test_refresh_without_a_snapshot_is_an_explicit_error(connection) -> None:
    """Missing is not the same as empty; NULLing the catalog silently would look like data."""

    with pytest.raises(CoverageError, match="does not exist"):
        refresh_series_coverage(connection)


def test_coverage_survives_a_catalog_reload(connection, tmp_path: Path) -> None:
    """The loader owns semantics; it must never clear operational coverage."""

    materialize_fact_observation_snapshot(
        connection,
        _staging(_rows("evds:TP.KTF12", [date(2021, 1, 1), date(2026, 6, 26)])),
    )
    before = _coverage(connection)["evds:TP.KTF12"]

    load_series_catalog(connection)

    assert _coverage(connection)["evds:TP.KTF12"] == before


def test_a_coverage_failure_leaves_the_previous_trusted_state_intact(
    connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Materialization and coverage are one unit of work.

    If coverage cannot be computed, publishing the new snapshot anyway would advertise a
    window that was never derived from it. DuckDB rolls back the table swap together with the
    catalog update, so the previous snapshot and the previous coverage both survive.
    """

    materialize_fact_observation_snapshot(
        connection,
        _staging(_rows("evds:TP.KTF12", [date(2021, 1, 1), date(2021, 1, 8)])),
    )
    good_rows = connection.execute(
        "SELECT observation_date FROM silver.fact_observation ORDER BY observation_date"
    ).fetchall()
    good_coverage = _coverage(connection)

    def _explode(_connection: Any) -> int:
        raise CoverageError("simulated coverage failure")

    monkeypatch.setattr(
        "src.lakehouse.silver.foundation.refresh_series_coverage", _explode
    )

    with pytest.raises(CoverageError, match="simulated"):
        materialize_fact_observation_snapshot(
            connection,
            _staging(_rows("evds:TP.FG.J0", [date(2099, 1, 31)], digest="b")),
        )

    assert (
        connection.execute(
            "SELECT observation_date FROM silver.fact_observation ORDER BY observation_date"
        ).fetchall()
        == good_rows
    )
    assert _coverage(connection) == good_coverage


def test_a_rejected_snapshot_never_touches_coverage(connection) -> None:
    """Validation failures happen before the transaction, so nothing is published."""

    materialize_fact_observation_snapshot(
        connection, _staging(_rows("evds:TP.KTF12", [date(2021, 1, 1)]))
    )
    good_coverage = _coverage(connection)

    bad = _staging(_rows("evds:TP.KTF12", [date(2021, 1, 1)]))
    bad.loc[0, "series_id"] = "evds:NOT.IN.CATALOG"

    with pytest.raises(SilverValidationError):
        materialize_fact_observation_snapshot(connection, bad)

    assert _coverage(connection) == good_coverage
    assert connection.execute(
        "SELECT count(*) FROM silver.fact_observation"
    ).fetchone() == (1,)


def test_refresh_returns_the_number_of_covered_series(connection) -> None:
    materialize_fact_observation_snapshot(
        connection,
        _staging(
            _rows("evds:TP.KTF12", [date(2021, 1, 1)]),
            _rows("evds:TP.FG.J0", [date(2025, 1, 31)], digest="b"),
        ),
    )

    assert refresh_series_coverage(connection) == 2
