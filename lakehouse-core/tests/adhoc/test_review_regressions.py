"""Publication boundary regressions from the independent review; synthetic data only."""
from dataclasses import replace
from uuid import uuid4

import duckdb
import pytest

from src.lakehouse.adhoc import AdhocPublicationError, publish_adhoc_observations
from src.lakehouse.adhoc.publication import _parse_value
from src.lakehouse.storage.parquet import ParquetStorage, read_identity
from tests.adhoc.test_publication import _prepare, _mapping, _rows
from tests.generic._support import ingest, spec, write_csv


def test_01_publication_reads_durable_bronze(tmp_path):
    connection, result = _prepare(tmp_path, 'donem,deger\n2026-01-31,10.5\n')
    try:
        result.parsed_batch.dataframe.loc[0, 'deger'] = '999'
        publish_adhoc_observations(connection, result, [_mapping()])
        assert _rows(connection)[0][3] == 10.5
    finally:
        connection.close()


def test_02_mixed_ingestion_results_are_refused(tmp_path):
    connection, a = _prepare(tmp_path, 'donem,deger\n2026-01-31,10.5\n')
    try:
        path = write_csv(tmp_path / 'uploads', 'b.csv', 'donem,deger\n2026-01-31,999\n')
        _, b = ingest(tmp_path, spec(str(path)), allowed_local_roots=[tmp_path], connection=connection)
        with pytest.raises(AdhocPublicationError):
            publish_adhoc_observations(connection, replace(a, parsed_batch=b.parsed_batch), [_mapping()])
        assert _rows(connection) == []
    finally:
        connection.close()


@pytest.mark.parametrize('field,value', [('source_id', 'other'), ('dataset_id', 'other'), ('artifact_sha256', '0' * 64), ('schema_version', 'other'), ('representation', 'silver')])
def test_02_all_bronze_identity_fields_are_verified(tmp_path, field, value):
    connection, result = _prepare(tmp_path, 'donem,deger\n2026-01-31,10.5\n')
    try:
        identity = replace(read_identity(result.bronze_path), **{field: value})
        forged = ParquetStorage(tmp_path / 'forged').write_frame(result.parsed_batch.dataframe, identity=identity)
        with pytest.raises(AdhocPublicationError):
            publish_adhoc_observations(connection, replace(result, bronze_path=forged), [_mapping()])
        assert _rows(connection) == []
    finally:
        connection.close()


@pytest.mark.parametrize('run_id', [None, '', 'invalid'])
def test_03_adhoc_result_requires_run_id(tmp_path, run_id):
    connection, result = _prepare(tmp_path, 'donem,deger\n2026-01-31,10.5\n')
    try:
        with pytest.raises(ValueError, match='run_id'):
            replace(result, run_id=run_id)
    finally:
        connection.close()


@pytest.mark.parametrize('kind', ['missing', 'source', 'dataset', 'failed'])
def test_03_publication_requires_matching_successful_run(tmp_path, kind):
    connection, result = _prepare(tmp_path, 'donem,deger\n2026-01-31,10.5\n')
    try:
        if kind == 'missing':
            result = replace(result, run_id=str(uuid4()))
        elif kind == 'failed':
            connection.execute("UPDATE meta.run SET status='failed' WHERE run_id=?", [result.run_id])
        else:
            column = 'source_id' if kind == 'source' else 'dataset_id'
            connection.execute(f"UPDATE meta.run SET {column}='other' WHERE run_id=?", [result.run_id])
        with pytest.raises(AdhocPublicationError, match='run'):
            publish_adhoc_observations(connection, result, [_mapping()])
        assert _rows(connection) == []
    finally:
        connection.close()


def test_03_sql_rejects_null_run_id(tmp_path):
    connection, result = _prepare(tmp_path, 'donem,deger\n2026-01-31,10.5\n')
    try:
        publish_adhoc_observations(connection, result, [_mapping()])
        with pytest.raises(duckdb.ConstraintException):
            connection.execute('UPDATE adhoc.fact_observation SET run_id=NULL')
    finally:
        connection.close()


@pytest.mark.parametrize('value', ['1,23,456', '1234,567', ',123', '123,', '1,,234', '1,234.5,6', '1,234e1,2'])
def test_13_malformed_thousands_groups_are_refused(value):
    with pytest.raises(AdhocPublicationError, match='group'):
        _parse_value(value, _mapping(thousands_separator=','), 0)


def test_02_missing_representation_metadata_is_refused(tmp_path):
    import pyarrow.parquet as pq

    connection, result = _prepare(tmp_path, 'donem,deger\n2026-01-31,10.5\n')
    try:
        table = pq.read_table(result.bronze_path)
        metadata = dict(table.schema.metadata)
        del metadata[b'lakehouse.representation']
        path = tmp_path / 'missing-representation.parquet'
        pq.write_table(table.replace_schema_metadata(metadata), path)
        with pytest.raises(AdhocPublicationError):
            publish_adhoc_observations(connection, replace(result, bronze_path=path), [_mapping()])
    finally:
        connection.close()


@pytest.mark.parametrize('field,value', [('parser_config_sha256', '0' * 64), ('parser_config_sha256', None)])
def test_04_bronze_configuration_identity_must_match(tmp_path, field, value):
    connection, result = _prepare(tmp_path, 'donem,deger\n2026-01-31,10.5\n')
    try:
        identity = replace(read_identity(result.bronze_path), **{field: value})
        path = ParquetStorage(tmp_path / 'forged').write_frame(result.parsed_batch.dataframe, identity=identity)
        with pytest.raises(AdhocPublicationError, match='Bronze identity'):
            publish_adhoc_observations(connection, replace(result, bronze_path=path), [_mapping()])
        assert _rows(connection) == []
    finally:
        connection.close()


def test_01_missing_bronze_never_falls_back_to_memory(tmp_path):
    connection, result = _prepare(tmp_path, 'donem,deger\n2026-01-31,10.5\n')
    try:
        with pytest.raises(AdhocPublicationError, match='Bronze'):
            publish_adhoc_observations(connection, replace(result, bronze_path=tmp_path / 'absent.parquet'), [_mapping()])
        assert _rows(connection) == []
    finally:
        connection.close()


def test_01_quality_uses_durable_warnings(tmp_path):
    connection, result = _prepare(tmp_path, 'donem,deger,extra\n2026-01-31,10.5\n')
    try:
        result.parsed_batch.warnings.clear()
        publish_adhoc_observations(connection, result, [_mapping()])
        assert _rows(connection)[0][4] == 'source_warning'
    finally:
        connection.close()


def test_13_invalid_grouping_publishes_no_partial_rows(tmp_path):
    connection, result = _prepare(tmp_path, 'donem,deger\n2026-01-31,"1,234"\n2026-02-28,"1,23,456"\n')
    try:
        with pytest.raises(AdhocPublicationError, match='group'):
            publish_adhoc_observations(connection, result, [_mapping(thousands_separator=',')])
        assert _rows(connection) == []
    finally:
        connection.close()


@pytest.mark.parametrize('raw,decimal,thousands,expected', [
    ('1,234,567.89', '.', ',', 1234567.89),
    ('-1.234.567,89', ',', '.', -1234567.89),
    ('12 345', '.', ' ', 12345),
    ("123'456", '.', "'", 123456),
    ('1,234e2', '.', ',', 123400),
    ('123456', '.', ',', 123456),
])
def test_13_valid_grouping_is_preserved(raw, decimal, thousands, expected):
    assert _parse_value(raw, _mapping(decimal_separator=decimal, thousands_separator=thousands), 0) == expected
