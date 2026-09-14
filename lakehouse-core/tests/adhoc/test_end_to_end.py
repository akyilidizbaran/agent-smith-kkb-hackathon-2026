"""The mandatory vertical slice: a local CSV becomes a queryable ad-hoc observation.

Every stage is production code -- the real connector, the real ingestion pipeline with its
observability, the real parser, real Bronze Parquet, the real catalog validator and the real
publication path. The only thing invented here is the CSV itself, which is SYNTHETIC and
written by the test.

The final read goes over ``connect_untrusted``, which is the connection the agent gets, after
the trusted handle has been closed. That is the whole point of the slice: proving the chain
ends somewhere the agent can actually reach, and nowhere it can write.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.lakehouse.adhoc import AdhocObservationMapping, publish_adhoc_observations
from src.lakehouse.catalog.registration import register_series
from src.lakehouse.db.connection import connect_untrusted
from src.lakehouse.gold import GoldError, align_frequency
from src.lakehouse.query.executor import QueryExecutor
from src.lakehouse.security.sql_guard import SqlGuardError
from src.lakehouse.storage.parquet import ParquetStorage, read_identity
from src.lakehouse.storage.raw import sha256_bytes

from tests.generic._support import (
    FETCHED_AT,
    SYNTHETIC_CSV,
    SYNTHETIC_SERIES_RECORD,
    ingest,
    spec,
    write_csv,
)


def test_local_csv_reaches_the_agent_through_the_adhoc_table(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source_file = write_csv(uploads)
    db_path = tmp_path / "data/lakehouse.duckdb"

    # --- connector -> RAW -> parser -> Bronze -------------------------------
    connection, result = ingest(
        tmp_path, spec(str(source_file)), allowed_local_roots=[uploads]
    )
    try:
        # exact bytes, unmodified
        assert result.asset.artifact_sha256 == sha256_bytes(
            SYNTHETIC_CSV.encode("utf-8")
        )
        assert result.asset.raw_path.read_bytes() == source_file.read_bytes()
        assert result.asset.media_type == "text/csv"
        assert result.asset.fetched_at == FETCHED_AT

        # artifact + request provenance
        artifact_row = connection.execute(
            "SELECT source_id, dataset_id, media_type, byte_size FROM meta.artifact "
            "WHERE artifact_sha256 = ?",
            [result.asset.artifact_sha256],
        ).fetchone()
        assert artifact_row == (
            "adhoc",
            "adhoc_synthetic",
            "text/csv",
            len(SYNTHETIC_CSV.encode("utf-8")),
        )
        assert connection.execute(
            "SELECT count(*) FROM meta.artifact_request WHERE artifact_sha256 = ?",
            [result.asset.artifact_sha256],
        ).fetchone() == (1,)

        # the ingestion run is recorded and reaches the result
        assert result.run_id is not None
        assert connection.execute(
            "SELECT status, source_id, dataset_id FROM meta.run WHERE run_id = ?",
            [result.run_id],
        ).fetchone() == ("success", "adhoc", "adhoc_synthetic")

        # Bronze keeps the source's own text. CSV has no NULL: an empty field is an empty
        # string, and Bronze records exactly that rather than deciding what it meant. The
        # explicit mapping is where "empty means no measurement" is stated.
        bronze = ParquetStorage.read(result.bronze_path)
        assert list(bronze.columns) == ["donem", "deger", "kurum"]
        assert bronze["deger"].tolist() == ["100.5", "", "120.25"]
        assert read_identity(result.bronze_path).schema_version == "adhoc_tabular.v1"

        # --- catalog: a draft, never a verified record ----------------------
        registration = register_series(connection, SYNTHETIC_SERIES_RECORD)
        assert registration.inserted is True
        assert connection.execute(
            "SELECT semantic_confidence, semantic_source, status, first_obs, last_obs "
            "FROM meta.series WHERE series_id = ?",
            ["adhoc:synthetic_series"],
        ).fetchone() == ("derived", "profiler", "draft", None, None)

        # --- explicit mapping -> adhoc.fact_observation ---------------------
        published = publish_adhoc_observations(
            connection,
            result,
            [
                AdhocObservationMapping(
                    series_id="adhoc:synthetic_series",
                    observation_date_column="donem",
                    value_column="deger",
                    entity_id_column="kurum",
                )
            ],
        )
        assert published.rows_written == 3

        # Silver was never touched by any of this.
        assert connection.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'silver' AND table_name = 'fact_observation'"
        ).fetchone() == (0,)
    finally:
        connection.close()

    # --- the agent's side: read-only, hardened, guarded --------------------
    untrusted = connect_untrusted(db_path)
    try:
        executor = QueryExecutor(untrusted)
        query_result = executor.execute(
            """
            SELECT series_id, entity_id, observation_date, value, frequency, unit,
                   measure_type, quality_flag, source_id, artifact_sha256, run_id
            FROM adhoc.fact_observation
            ORDER BY observation_date
            """
        )

        assert query_result.row_count == 3
        first = query_result.rows[0]
        assert first[:8] == (
            "adhoc:synthetic_series",
            "SYNTHETIC-A",
            date(2026, 1, 31),
            100.5,
            "monthly",
            "TRY_mn",
            "stock",
            "ok",
        )
        assert first[8] == "adhoc"
        assert first[9] == result.asset.artifact_sha256
        assert first[10] == result.run_id

        # the source's empty cell became NULL at the mapping, and is flagged rather than
        # turned into a measured zero
        february = query_result.rows[1]
        assert february[2] == date(2026, 2, 28)
        assert february[3] is None
        assert february[7] == "missing_value"

        # the agent cannot write through this connection
        with pytest.raises(SqlGuardError):
            executor.execute("DELETE FROM adhoc.fact_observation")
        with pytest.raises(duckdb.Error):
            untrusted.execute(
                "INSERT INTO adhoc.fact_observation SELECT * FROM adhoc.fact_observation"
            )
    finally:
        untrusted.close()


def test_a_draft_adhoc_series_is_still_refused_by_gold(tmp_path: Path) -> None:
    """Publishing into the ad-hoc table does not make a machine proposal usable."""

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_csv(uploads)

    connection, result = ingest(
        tmp_path, spec(str(uploads / "synthetic.csv")), allowed_local_roots=[uploads]
    )
    try:
        register_series(connection, SYNTHETIC_SERIES_RECORD)
        publish_adhoc_observations(
            connection,
            result,
            [
                AdhocObservationMapping(
                    series_id="adhoc:synthetic_series",
                    observation_date_column="donem",
                    value_column="deger",
                )
            ],
        )

        with pytest.raises(GoldError) as excinfo:
            align_frequency(connection, "adhoc:synthetic_series", "monthly")
        # Gold refuses on status first: a draft is not published for use.
        assert excinfo.value.refusal.reason == "INACTIVE_SERIES"
    finally:
        connection.close()


def test_a_parser_warning_survives_all_the_way_to_the_adhoc_row(tmp_path: Path) -> None:
    """A ragged CSV warns; the warning must reach observability and the published quality."""

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_csv(
        uploads,
        body="donem,deger\n2026-01-31,100.5\n2026-02-28,110.0,extra-field\n",
    )

    connection, result = ingest(
        tmp_path, spec(str(uploads / "synthetic.csv")), allowed_local_roots=[uploads]
    )
    try:
        assert result.parsed_batch.warnings, "precondition: the parser warned"

        # observability persisted it verbatim
        stored = connection.execute(
            "SELECT message FROM meta.ingest_warning WHERE run_id = ? ORDER BY warning_seq",
            [result.run_id],
        ).fetchall()
        assert [row[0] for row in stored] == result.parsed_batch.warnings
        assert connection.execute(
            "SELECT status FROM meta.run WHERE run_id = ?", [result.run_id]
        ).fetchone() == ("warning",)

        register_series(connection, SYNTHETIC_SERIES_RECORD)
        publish_adhoc_observations(
            connection,
            result,
            [
                AdhocObservationMapping(
                    series_id="adhoc:synthetic_series",
                    observation_date_column="donem",
                    value_column="deger",
                )
            ],
        )

        flags = connection.execute(
            "SELECT DISTINCT quality_flag FROM adhoc.fact_observation"
        ).fetchall()
        assert flags == [("source_warning",)]
    finally:
        connection.close()
