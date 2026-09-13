"""Ad-hoc publication: an explicit mapping, and nothing inferred.

Every file is SYNTHETIC and written by the test. The recurring point is that a number or a
date whose reading is not stated is refused rather than guessed.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.lakehouse.adhoc import (
    AdhocObservationMapping,
    AdhocPublicationConflict,
    AdhocPublicationError,
    publish_adhoc_observations,
)
from src.lakehouse.catalog.registration import register_series

from tests.generic._support import SYNTHETIC_SERIES_RECORD, ingest, spec, write_csv


def _prepare(tmp_path: Path, body: str, *, register: bool = True, record=None):
    uploads = tmp_path / "uploads"
    uploads.mkdir(exist_ok=True)
    write_csv(uploads, body=body)
    connection, result = ingest(
        tmp_path, spec(str(uploads / "synthetic.csv")), allowed_local_roots=[uploads]
    )
    if register:
        register_series(connection, record or SYNTHETIC_SERIES_RECORD)
    return connection, result


def _rows(connection):
    return connection.execute(
        "SELECT series_id, entity_id, observation_date, value, quality_flag "
        "FROM adhoc.fact_observation ORDER BY series_id, observation_date"
    ).fetchall()


def _mapping(**overrides) -> AdhocObservationMapping:
    base = {
        "series_id": "adhoc:synthetic_series",
        "observation_date_column": "donem",
        "value_column": "deger",
    }
    base.update(overrides)
    return AdhocObservationMapping(**base)


# ------------------------------------------------------------------ dates


def test_iso_dates_need_no_declaration(tmp_path: Path) -> None:
    connection, result = _prepare(
        tmp_path, "donem,deger\n2026-01-31,10.5\n2026-02-28,11.0\n"
    )
    try:
        publish_adhoc_observations(connection, result, [_mapping()])
        assert [row[2] for row in _rows(connection)] == [
            date(2026, 1, 31),
            date(2026, 2, 28),
        ]
    finally:
        connection.close()


def test_a_turkish_date_needs_an_explicit_format(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n31.01.2026,10.5\n")
    try:
        with pytest.raises(AdhocPublicationError, match="date_format"):
            publish_adhoc_observations(connection, result, [_mapping()])
    finally:
        connection.close()


def test_an_explicit_turkish_date_format_is_honoured(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n31.01.2026,10.5\n")
    try:
        publish_adhoc_observations(
            connection, result, [_mapping(date_format="%d.%m.%Y")]
        )
        assert _rows(connection)[0][2] == date(2026, 1, 31)
    finally:
        connection.close()


def test_an_ambiguous_slash_date_is_never_guessed(tmp_path: Path) -> None:
    """01/02/2026 is January 2nd or February 1st; the data cannot say which."""

    connection, result = _prepare(tmp_path, "donem,deger\n01/02/2026,10.5\n")
    try:
        with pytest.raises(AdhocPublicationError, match="Day-first and month-first"):
            publish_adhoc_observations(connection, result, [_mapping()])
    finally:
        connection.close()


def test_a_value_that_does_not_match_the_declared_format_is_refused(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,10.5\n")
    try:
        with pytest.raises(AdhocPublicationError, match="does not match the declared"):
            publish_adhoc_observations(
                connection, result, [_mapping(date_format="%d.%m.%Y")]
            )
    finally:
        connection.close()


def test_a_missing_date_is_refused(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n,10.5\n")
    try:
        with pytest.raises(AdhocPublicationError, match="blank"):
            publish_adhoc_observations(connection, result, [_mapping()])
    finally:
        connection.close()


# ----------------------------------------------------------------- numbers


def test_a_comma_decimal_needs_to_be_declared(tmp_path: Path) -> None:
    """'1,5' is one-and-a-half or fifteen hundred; both readings are consistent."""

    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,\"1,5\"\n")
    try:
        with pytest.raises(AdhocPublicationError, match="decimal_separator"):
            publish_adhoc_observations(connection, result, [_mapping()])
    finally:
        connection.close()


def test_a_declared_comma_decimal_is_read_correctly(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,\"1,5\"\n")
    try:
        publish_adhoc_observations(
            connection, result, [_mapping(decimal_separator=",")]
        )
        assert _rows(connection)[0][3] == 1.5
    finally:
        connection.close()


def test_turkish_thousands_and_decimal_together(tmp_path: Path) -> None:
    connection, result = _prepare(
        tmp_path, "donem,deger\n2026-01-31,\"1.234.567,89\"\n"
    )
    try:
        publish_adhoc_observations(
            connection,
            result,
            [_mapping(decimal_separator=",", thousands_separator=".")],
        )
        assert _rows(connection)[0][3] == 1234567.89
    finally:
        connection.close()


def test_a_dot_in_a_comma_decimal_file_without_a_declared_thousands_is_refused(
    tmp_path: Path,
) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,\"1.234,5\"\n")
    try:
        with pytest.raises(AdhocPublicationError, match="thousands_separator"):
            publish_adhoc_observations(
                connection, result, [_mapping(decimal_separator=",")]
            )
    finally:
        connection.close()


def test_a_non_numeric_value_is_refused(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,yok\n")
    try:
        with pytest.raises(AdhocPublicationError, match="is not a number"):
            publish_adhoc_observations(connection, result, [_mapping()])
    finally:
        connection.close()


@pytest.mark.parametrize("text", ["NaN", "nan", "Infinity", "-Infinity", "inf"])
def test_non_finite_text_is_refused(tmp_path: Path, text: str) -> None:
    connection, result = _prepare(tmp_path, f"donem,deger\n2026-01-31,{text}\n")
    try:
        with pytest.raises(AdhocPublicationError):
            publish_adhoc_observations(connection, result, [_mapping()])
    finally:
        connection.close()


def test_an_empty_cell_stays_null_and_is_flagged(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,\n")
    try:
        publish_adhoc_observations(connection, result, [_mapping()])
        row = _rows(connection)[0]
        assert row[3] is None
        assert row[3] != 0
        assert row[4] == "missing_value"
    finally:
        connection.close()


def test_an_invalid_separator_choice_is_refused_at_construction() -> None:
    with pytest.raises(AdhocPublicationError, match="decimal_separator"):
        _mapping(decimal_separator=";")
    with pytest.raises(AdhocPublicationError, match="must differ"):
        _mapping(decimal_separator=",", thousands_separator=",")


# ----------------------------------------------------------------- mapping


def test_a_missing_column_is_named(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,1\n")
    try:
        with pytest.raises(AdhocPublicationError, match="not in the parsed table"):
            publish_adhoc_observations(
                connection, result, [_mapping(value_column="yok")]
            )
    finally:
        connection.close()


def test_several_series_from_one_file(tmp_path: Path) -> None:
    second = dict(SYNTHETIC_SERIES_RECORD)
    second["series_id"] = "adhoc:synthetic_other"
    second["native_code"] = "synthetic_other"

    connection, result = _prepare(
        tmp_path, "donem,kredi,faiz\n2026-01-31,100,12.5\n2026-02-28,110,12.0\n"
    )
    try:
        register_series(connection, second)
        published = publish_adhoc_observations(
            connection,
            result,
            [
                _mapping(value_column="kredi"),
                _mapping(series_id="adhoc:synthetic_other", value_column="faiz"),
            ],
        )
        assert published.rows_written == 4
        assert {row[0] for row in _rows(connection)} == {
            "adhoc:synthetic_series",
            "adhoc:synthetic_other",
        }
    finally:
        connection.close()


def test_a_repeated_series_id_in_the_mappings_is_refused(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,1\n")
    try:
        with pytest.raises(AdhocPublicationError, match="repeat a series_id"):
            publish_adhoc_observations(connection, result, [_mapping(), _mapping()])
    finally:
        connection.close()


def test_two_rows_for_the_same_period_in_one_file_are_refused(tmp_path: Path) -> None:
    connection, result = _prepare(
        tmp_path, "donem,deger\n2026-01-31,1\n2026-01-31,2\n"
    )
    try:
        with pytest.raises(AdhocPublicationError, match="more than once"):
            publish_adhoc_observations(connection, result, [_mapping()])
    finally:
        connection.close()


def test_the_mapping_cannot_carry_semantics() -> None:
    """Frequency, unit and measure type are catalog facts, not mapping fields."""

    import dataclasses

    fields = {field.name for field in dataclasses.fields(AdhocObservationMapping)}
    assert not fields & {
        "measure_type",
        "frequency",
        "unit",
        "default_agg",
        "aggregation",
        "semantic_confidence",
    }


# -------------------------------------------------------------- catalog gate


def test_an_uncatalogued_series_is_refused(tmp_path: Path) -> None:
    connection, result = _prepare(
        tmp_path, "donem,deger\n2026-01-31,1\n", register=False
    )
    try:
        with pytest.raises(AdhocPublicationError, match="no meta.series row"):
            publish_adhoc_observations(connection, result, [_mapping()])
    finally:
        connection.close()


def test_a_series_from_another_source_is_refused(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,1\n")
    try:
        with pytest.raises(AdhocPublicationError, match="only 'adhoc'"):
            publish_adhoc_observations(
                connection, result, [_mapping(series_id="evds:TP.KTF12")]
            )
    finally:
        connection.close()


def test_a_dataset_mismatch_is_refused(tmp_path: Path) -> None:
    record = dict(SYNTHETIC_SERIES_RECORD)
    record["dataset_id"] = "adhoc_something_else"
    connection, result = _prepare(
        tmp_path, "donem,deger\n2026-01-31,1\n", record=record
    )
    try:
        with pytest.raises(AdhocPublicationError, match="one of the two is wrong"):
            publish_adhoc_observations(connection, result, [_mapping()])
    finally:
        connection.close()


def test_semantics_come_from_the_catalog_not_the_file(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,1\n")
    try:
        publish_adhoc_observations(connection, result, [_mapping()])
        row = connection.execute(
            "SELECT frequency, unit, measure_type FROM adhoc.fact_observation"
        ).fetchone()
        assert row == ("monthly", "TRY_mn", "stock")
    finally:
        connection.close()


# ----------------------------------------------- idempotence, conflict, atomicity


def test_republishing_the_same_artifact_is_idempotent(tmp_path: Path) -> None:
    connection, result = _prepare(
        tmp_path, "donem,deger\n2026-01-31,10.5\n2026-02-28,11.0\n"
    )
    try:
        first = publish_adhoc_observations(connection, result, [_mapping()])
        second = publish_adhoc_observations(connection, result, [_mapping()])

        assert first.rows_written == 2
        assert second.rows_written == 0
        assert second.rows_unchanged == 2
        assert len(_rows(connection)) == 2
    finally:
        connection.close()


def test_a_different_value_for_the_same_identity_is_a_conflict(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,10.5\n")
    try:
        publish_adhoc_observations(connection, result, [_mapping()])
        connection.execute(
            "UPDATE adhoc.fact_observation SET value = 99.0 WHERE observation_date = ?",
            [date(2026, 1, 31)],
        )
        with pytest.raises(AdhocPublicationConflict, match="mapping mistake"):
            publish_adhoc_observations(connection, result, [_mapping()])
    finally:
        connection.close()


def test_a_failure_in_the_second_mapping_rolls_back_the_first(tmp_path: Path) -> None:
    second = dict(SYNTHETIC_SERIES_RECORD)
    second["series_id"] = "adhoc:synthetic_other"
    second["native_code"] = "synthetic_other"

    connection, result = _prepare(
        tmp_path, "donem,kredi,faiz\n2026-01-31,100,bozuk\n"
    )
    try:
        register_series(connection, second)
        with pytest.raises(AdhocPublicationError):
            publish_adhoc_observations(
                connection,
                result,
                [
                    _mapping(value_column="kredi"),
                    _mapping(series_id="adhoc:synthetic_other", value_column="faiz"),
                ],
            )
        # Validation happens before any insert, so nothing at all was written.
        assert _rows(connection) == []
    finally:
        connection.close()


# ----------------------------------------------------------------- provenance


def test_provenance_comes_from_the_ingestion_not_the_caller(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,10.5\n")
    try:
        publish_adhoc_observations(connection, result, [_mapping()])
        row = connection.execute(
            "SELECT source_id, dataset_id, artifact_sha256, schema_version, vintage_id, "
            "run_id, epoch_ms(fetched_at) FROM adhoc.fact_observation"
        ).fetchone()
        assert row[0] == "adhoc"
        assert row[1] == "adhoc_synthetic"
        assert row[2] == result.asset.artifact_sha256
        assert row[3] == "adhoc_tabular.v1"
        assert row[4] == f"artifact:{result.asset.artifact_sha256}"
        assert row[5] == result.run_id
        assert row[6] == int(result.asset.fetched_at.timestamp() * 1000)
    finally:
        connection.close()


def test_silver_is_never_touched(tmp_path: Path) -> None:
    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,10.5\n")
    try:
        publish_adhoc_observations(connection, result, [_mapping()])
        assert connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'silver'"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_catalog_coverage_is_not_updated_by_adhoc_data(tmp_path: Path) -> None:
    """first_obs/last_obs describe the Silver snapshot; ad-hoc rows are not one."""

    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,10.5\n")
    try:
        publish_adhoc_observations(connection, result, [_mapping()])
        assert connection.execute(
            "SELECT first_obs, last_obs FROM meta.series WHERE series_id = ?",
            ["adhoc:synthetic_series"],
        ).fetchone() == (None, None)
    finally:
        connection.close()


def test_the_storage_layer_refuses_a_foreign_source_id(tmp_path: Path) -> None:
    """The CHECK constraint holds even for a direct INSERT."""

    import duckdb

    connection, result = _prepare(tmp_path, "donem,deger\n2026-01-31,1\n")
    try:
        publish_adhoc_observations(connection, result, [_mapping()])
        with pytest.raises(duckdb.Error):
            connection.execute(
                "INSERT INTO adhoc.fact_observation "
                "SELECT series_id, entity_id, observation_date, period_start, period_end, "
                "value, frequency, unit, measure_type, quality_flag, 'evds', dataset_id, "
                "artifact_sha256, fetched_at, schema_version, vintage_id, run_id "
                "FROM adhoc.fact_observation"
            )
    finally:
        connection.close()
