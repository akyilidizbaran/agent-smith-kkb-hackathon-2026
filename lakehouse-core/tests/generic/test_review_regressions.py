"""Synthetic regressions for the independent Generic/Ad-hoc review."""
import io
import json
import zipfile
from datetime import datetime, tzinfo

import pytest
import requests

from src.lakehouse.errors import LakehouseError
from src.lakehouse.generic import GenericTabularConnector, GenericTabularParser
from src.lakehouse.storage.raw import RawStorage
from src.lakehouse.storage.parquet import ParquetStorage, read_identity
from tests.generic._support import ingest, spec, xlsx_bytes, FakeResponse, FakeSession, public_resolver


def fetch(tmp_path, name, content, parameters=None):
    path = tmp_path / name
    path.write_bytes(content)
    return GenericTabularConnector(RawStorage(tmp_path / 'raw'), allowed_local_roots=[tmp_path]).fetch(
        spec(str(path), parameters=parameters))[0]


def test_05_quoted_commas_do_not_override_semicolon(tmp_path):
    asset = fetch(tmp_path, 'a.csv', b'"label,with,commas";value\n"row,with,commas";123\n')
    batch = GenericTabularParser().parse(asset)
    assert list(batch.dataframe.columns) == ['label,with,commas', 'value']
    assert batch.dataframe.iloc[0].tolist() == ['row,with,commas', '123']
    assert batch.warnings == []


def test_05_multiple_valid_delimiters_require_explicit_choice(tmp_path):
    asset = fetch(tmp_path, 'a.csv', b'a,b,c;d\n1,2,3;4\n')
    with pytest.raises(LakehouseError, match='delimiter'):
        GenericTabularParser().parse(asset)


def test_06_workbook_entries_after_8kb(tmp_path):
    original = xlsx_bytes({'Data': [['a', 'b'], [1, 2]]})
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(buf, 'w') as target:
        target.writestr('padding.bin', b'x' * 10000)
        for info in source.infolist():
            target.writestr(info.filename, source.read(info))
    assert b'xl/workbook.xml' not in buf.getvalue()[:8192]
    asset = fetch(tmp_path, 'a.xlsx', buf.getvalue())
    assert GenericTabularParser().parse(asset).dataframe.iloc[0].tolist() == ['1', '2']


@pytest.mark.parametrize('location', ['header', 'data', 'hidden'])
def test_07_formula_workbook_is_explicitly_refused(tmp_path, location):
    sheets = {'Data': [['a', 'b'], [1, 2]]}
    if location == 'hidden':
        sheets['Notes'] = [['a'], ['=1+1']]
    else:
        sheets['Data'][0 if location == 'header' else 1][1] = '=1+1'
    asset = fetch(tmp_path, 'a.xlsx', xlsx_bytes(sheets, hidden=('Notes',) if location == 'hidden' else ()))
    with pytest.raises(LakehouseError, match='formula'):
        GenericTabularParser().parse(asset)


def test_08_long_html_cell_is_refused(tmp_path):
    content = ('<table><tr><th>a</th></tr><tr><td>' + 'x' * 32769 + '</td></tr></table>').encode()
    asset = fetch(tmp_path, 'a.html', content)
    with pytest.raises(LakehouseError, match='32768'):
        GenericTabularParser().parse(asset)


@pytest.mark.parametrize('failure', ['limit', 'timeout', 'request', 'unexpected'])
def test_09_response_closed_on_every_stream_failure(tmp_path, monkeypatch, failure):
    monkeypatch.setattr('src.lakehouse.generic._access._resolve_all', public_resolver)
    errors = {'limit': None, 'timeout': requests.Timeout(), 'request': requests.ConnectionError(), 'unexpected': RuntimeError('stream')}
    response = FakeResponse(content=b'a,b\n1,2\n', raise_on_iter=errors[failure])
    connector = GenericTabularConnector(RawStorage(tmp_path / 'raw'), session=FakeSession([response]), max_attempts=1, max_bytes=1)
    with pytest.raises((LakehouseError, RuntimeError)):
        connector.fetch(spec('https://example.com/a.csv'))
    assert response.closed


@pytest.mark.parametrize('kwargs', [{'max_bytes': 0}, {'max_bytes': -1}, {'backoff_seconds': -0.1}])
def test_10_url_only_constructor_validates_limits(tmp_path, kwargs):
    with pytest.raises(ValueError):
        GenericTabularConnector(RawStorage(tmp_path / 'raw'), **kwargs)


class NoOffset(tzinfo):
    def utcoffset(self, dt):
        return None


@pytest.mark.parametrize('moment', [datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=NoOffset()), 'bad'])
def test_10_constructor_requires_aware_clock(tmp_path, moment):
    with pytest.raises((ValueError, TypeError), match='clock'):
        GenericTabularConnector(RawStorage(tmp_path / 'raw'), clock=lambda: moment)


def test_11_allowed_root_must_be_a_directory(tmp_path):
    path = tmp_path / 'file.csv'
    path.write_text('a,b\n1,2\n')
    with pytest.raises(ValueError, match='director'):
        GenericTabularConnector(RawStorage(tmp_path / 'raw'), allowed_local_roots=[path])


def test_12_explicit_encoding_is_used_and_recorded(tmp_path):
    asset = fetch(tmp_path, 'a.csv', b'label,value\n\xfd,123\n', {'encoding': 'latin-1'})
    batch = GenericTabularParser().parse(asset)
    assert batch.dataframe.iloc[0, 0] == 'ý'
    assert asset.metadata['parser_config']['encoding'] == 'latin-1'


@pytest.mark.parametrize('parameters', [{'surprise': 'secret'}, {'sheet_name': 'A'}, {'table_index': 0}, {'records_field': 'rows'}, {'encoding': 'utf-7'}, {'delimiter': 'xx'}])
def test_04_unknown_and_format_invalid_parameters_are_refused(tmp_path, parameters):
    with pytest.raises(LakehouseError):
        asset = fetch(tmp_path, 'a.csv', b'a,b\n1,2\n', parameters)
        GenericTabularParser().parse(asset)


def test_04_constructor_cannot_override_artifact_choices(tmp_path):
    asset = fetch(tmp_path, 'a.xlsx', xlsx_bytes({'A': [['a'], [1]], 'B': [['a'], [2]]}), {'sheet_name': 'A'})
    with pytest.raises((TypeError, LakehouseError)):
        GenericTabularParser(parameters={'sheet_name': 'B'}).parse(asset)


@pytest.mark.parametrize('kind', ['xlsx', 'html'])
def test_04_selections_have_distinct_durable_identities(tmp_path, kind):
    if kind == 'xlsx':
        content = xlsx_bytes({'A': [['a'], [1]], 'B': [['a'], [2]]})
        choices = [{'sheet_name': 'A'}, {'sheet_name': 'B'}]
    else:
        content = b'<table><tr><th>a</th></tr><tr><td>1</td></tr></table><table><tr><th>a</th></tr><tr><td>2</td></tr></table>'
        choices = [{'table_index': 0}, {'table_index': 1}]
    path = tmp_path / ('a.' + kind)
    path.write_bytes(content)
    connection, a = ingest(tmp_path, spec(str(path), parameters=choices[0]), allowed_local_roots=[tmp_path])
    try:
        _, b = ingest(tmp_path, spec(str(path), parameters=choices[1]), allowed_local_roots=[tmp_path], connection=connection)
        assert a.asset.artifact_sha256 == b.asset.artifact_sha256
        assert a.bronze_path != b.bronze_path
        assert ParquetStorage.read(a.bronze_path).iloc[0, 0] == '1'
        assert ParquetStorage.read(b.bronze_path).iloc[0, 0] == '2'
        assert read_identity(a.bronze_path).parser_config_sha256 != read_identity(b.bronze_path).parser_config_sha256
        metadata = [json.loads(row[0]) for row in connection.execute('SELECT request_metadata_json FROM meta.artifact_request').fetchall()]
        assert len(metadata) == 2
        assert {m['parser_config_sha256'] for m in metadata} == {a.asset.metadata['parser_config_sha256'], b.asset.metadata['parser_config_sha256']}
        _, again = ingest(tmp_path, spec(str(path), parameters=choices[0]), allowed_local_roots=[tmp_path], connection=connection)
        assert again.bronze_path == a.bronze_path
    finally:
        connection.close()


@pytest.mark.parametrize('name,content,parameters', [
    ('a.csv', b'a;b\n1;2\n', {'delimiter': ';', 'encoding': 'utf-8'}),
    ('a.tsv', b'a\tb\n1\t2\n', {'delimiter': '\t', 'encoding': 'utf-8-sig'}),
    ('a.json', b'{"rows":[{"a":1}]}', {'records_field': 'rows', 'encoding': 'utf-8'}),
    ('a.html', b'<table><tr><th>a</th></tr><tr><td>1</td></tr></table>', {'table_index': 0, 'encoding': 'utf-8'}),
])
def test_04_all_choices_are_canonical_and_durable(tmp_path, name, content, parameters):
    from src.lakehouse.generic.config import parser_config_hash
    path = tmp_path / name
    path.write_bytes(content)
    connection, result = ingest(tmp_path, spec(str(path), parameters=parameters), allowed_local_roots=[tmp_path])
    try:
        config = result.asset.metadata['parser_config']
        assert all(config[key] == value for key, value in parameters.items())
        digest = parser_config_hash(config)
        assert digest == parser_config_hash(dict(reversed(list(config.items()))))
        assert result.parsed_batch.parser_config_sha256 == digest
        assert read_identity(result.bronze_path).parser_config_sha256 == digest
        durable = json.loads(connection.execute('SELECT request_metadata_json FROM meta.artifact_request').fetchone()[0])
        assert durable['parser_config'] == config
        assert durable['parser_config_sha256'] == digest
    finally:
        connection.close()


@pytest.mark.parametrize('status', [200, 302, 404, 503])
def test_09_response_closed_for_success_redirect_and_http_error(tmp_path, monkeypatch, status):
    monkeypatch.setattr('src.lakehouse.generic._access._resolve_all', public_resolver)
    response = FakeResponse(status_code=status, content=b'a,b\n1,2\n')
    connector = GenericTabularConnector(RawStorage(tmp_path / 'raw'), session=FakeSession([response]), max_attempts=1)
    if status == 200:
        connector.fetch(spec('https://example.com/a.csv'))
    else:
        with pytest.raises(LakehouseError):
            connector.fetch(spec('https://example.com/a.csv'))
    assert response.closed


def test_12_wrong_explicit_encoding_is_refused_without_fallback(tmp_path):
    asset = fetch(tmp_path, 'a.csv', b'a,b\n\xfd,1\n', {'encoding': 'utf-8'})
    with pytest.raises(LakehouseError, match='explicit encoding'):
        GenericTabularParser().parse(asset)


def test_06_zip_payload_markers_are_not_entry_names(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('note.txt', b'xl/workbook.xml [Content_Types].xml')
    with pytest.raises(LakehouseError, match='zip archive'):
        fetch(tmp_path, 'a.xlsx', buffer.getvalue())


def test_07_cached_formula_is_also_refused(tmp_path):
    original = xlsx_bytes({'Data': [['a', 'b'], [1, '=1+1']]})
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(buffer, 'w') as target:
        for info in source.infolist():
            content = source.read(info)
            if info.filename == 'xl/worksheets/sheet1.xml':
                from xml.etree import ElementTree as ET
                tree = ET.fromstring(content)
                ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                formula_cell = next(cell for cell in tree.iter(ns + 'c') if cell.find(ns + 'f') is not None)
                formula_cell.find(ns + 'v').text = '2'
                content = ET.tostring(tree)
            target.writestr(info.filename, content)
    asset = fetch(tmp_path, 'a.xlsx', buffer.getvalue())
    with pytest.raises(LakehouseError, match='formula'):
        GenericTabularParser().parse(asset)
