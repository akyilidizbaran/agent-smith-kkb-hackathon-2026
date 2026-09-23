"""Byte-identical content can feed a second ad-hoc series, and a refused publication leaves no trace.

Observed 20 Sep 2026 (Architect drive on the full database): the same CSV uploaded under a new
series key failed with "artifact … is not registered under the run-artifact link's
source/dataset" because ``meta.artifact`` keeps the first fetch's dataset (artifact identity is
the bytes, PR #11) while publication still demanded equality. Each refused attempt also left an
orphan draft in ``meta.series`` and a ``meta.run`` row closed as ``success`` with ``rows_out 11``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.lakehouse.adhoc import AdhocObservationMapping, AdhocPublicationError, publish_adhoc_observations
from src.lakehouse.application import run_adhoc_ingestion
from src.lakehouse.catalog.registration import register_series
from src.lakehouse.db.bootstrap import bootstrap_database

from tests.generic._support import FETCHED_AT, SYNTHETIC_SERIES_RECORD, ingest, spec, write_csv


def _mapping(series_id: str) -> AdhocObservationMapping:
    return AdhocObservationMapping(
        series_id=series_id, observation_date_column="donem", value_column="deger", entity_id_column="kurum"
    )


def test_same_bytes_publish_under_a_second_series(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source_file = write_csv(uploads)
    connection, first = ingest(tmp_path, spec(str(source_file)), allowed_local_roots=[uploads])
    try:
        _, second = ingest(
            tmp_path, spec(str(source_file), dataset_id="adhoc_second"),
            allowed_local_roots=[uploads], connection=connection,
        )
        assert first.asset.artifact_sha256 == second.asset.artifact_sha256, "identity is the bytes"
        assert connection.execute(
            "SELECT dataset_id FROM meta.artifact WHERE artifact_sha256 = ?", [first.asset.artifact_sha256]
        ).fetchall() == [("adhoc_synthetic",)], "meta.artifact keeps the first fetch's context only"

        register_series(connection, SYNTHETIC_SERIES_RECORD)
        register_series(connection, {**SYNTHETIC_SERIES_RECORD, "series_id": "adhoc:second_series",
                                     "native_code": "second_series", "dataset_id": "adhoc_second"})
        assert publish_adhoc_observations(connection, first, [_mapping("adhoc:synthetic_series")]).rows_written == 3
        published = publish_adhoc_observations(connection, second, [_mapping("adhoc:second_series")])
        assert published.rows_written == 3, "the per-run link vouches for the bytes, not meta.artifact's first dataset"
        assert connection.execute(
            "SELECT series_id, count(*) FROM adhoc.fact_observation GROUP BY 1 ORDER BY 1"
        ).fetchall() == [("adhoc:second_series", 3), ("adhoc:synthetic_series", 3)]
        assert connection.execute(
            "SELECT DISTINCT run_id FROM adhoc.fact_observation WHERE series_id = 'adhoc:second_series'"
        ).fetchall() == [(second.run_id,)], "provenance points at the run that actually fetched for this series"
    finally:
        connection.close()


def test_refused_publication_leaves_no_orphan_draft_and_marks_the_run_failed(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source_file = write_csv(uploads)
    db = tmp_path / "data" / "lakehouse.duckdb"
    bootstrap_database(db).close()

    with pytest.raises(AdhocPublicationError):
        run_adhoc_ingestion(
            locator=str(source_file), dataset_id="adhoc_synthetic", database=db, data_root=tmp_path / "data",
            allowed_local_roots=[uploads], parser_parameters={},
            mapping=AdhocObservationMapping(series_id="adhoc:synthetic_series", observation_date_column="donem",
                                            value_column="boyle_kolon_yok"),
            series_record=SYNTHETIC_SERIES_RECORD, clock=lambda: FETCHED_AT,
        )

    connection = bootstrap_database(db)
    try:
        assert connection.execute(
            "SELECT count(*) FROM meta.series WHERE series_id = 'adhoc:synthetic_series'"
        ).fetchone() == (0,), "a draft without observations is not left behind"
        status, error = connection.execute(
            "SELECT status, error FROM meta.run WHERE dataset_id = 'adhoc_synthetic' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        assert status == "failed" and error and error.startswith("publication refused:"), (status, error)
        assert connection.execute("SELECT count(*) FROM adhoc.fact_observation").fetchone() == (0,)
        # RAW and Bronze stay: the bytes were fetched and are content-addressed; only the claim of success goes.
        assert connection.execute("SELECT count(*) FROM meta.artifact").fetchone() == (1,)
    finally:
        connection.close()
