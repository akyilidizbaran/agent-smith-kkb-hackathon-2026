"""Batch catalog ingestion keeps the same provenance contract as IngestionPipeline (M07, ADR-0057).

Before this, ``scripts/run_catalog_ingestion.py`` registered artifacts and wrote Bronze but opened
no ``meta.run``, linked nothing in ``meta.run_artifact`` and only printed parser warnings — so a
Silver rebuild could not recover them and a warned observation would come back as ``ok``
(measured 13 Sept on the demo DB: 295 artifacts, 0 runs). Only the connector and parser are
stubs; DuckDB, the artifact repository, RAW and Parquet storage are real.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import run_catalog_ingestion as rci  # noqa: E402
from ingestion_registry import ConnectorBinding, SeriesRow  # noqa: E402

from src.lakehouse.catalog.artifacts import ArtifactRepository  # noqa: E402
from src.lakehouse.connectors.base import BaseConnector  # noqa: E402
from src.lakehouse.contracts.models import FetchedAsset, FetchSpec, ParsedBatch  # noqa: E402
from src.lakehouse.db.bootstrap import bootstrap_database  # noqa: E402
from src.lakehouse.errors import ErrorPayload, LakehouseError  # noqa: E402
from src.lakehouse.ingestion.observability import RunRepository  # noqa: E402
from src.lakehouse.storage.parquet import ParquetStorage  # noqa: E402
from src.lakehouse.storage.raw import RawStorage, sha256_bytes  # noqa: E402

SOURCE, DATASET = "fake_source", "fake_dataset"
FETCHED_AT = datetime(2026, 9, 13, 5, 0, tzinfo=timezone.utc)


def _asset(tmp_path: Path, payload: bytes, *, source=SOURCE, dataset=DATASET) -> FetchedAsset:
    path = tmp_path / f"{sha256_bytes(payload)}.json"
    path.write_bytes(payload)
    return FetchedAsset(source_id=source, dataset_id=dataset, locator="fixture://a.json", media_type="application/json",
                        byte_size=len(payload), fetched_at=FETCHED_AT, artifact_sha256=sha256_bytes(payload),
                        raw_path=path, http_status=200)


def _batch(asset: FetchedAsset, warnings=None, rows=2) -> ParsedBatch:
    return ParsedBatch(source_id=asset.source_id, dataset_id=asset.dataset_id, artifact_sha256=asset.artifact_sha256,
                       schema_version="fixture-v1", dataframe=pd.DataFrame({"value": list(range(rows))}),
                       warnings=list(warnings or []))


def _binding(assets=None, *, fail_fetch: str | None = None, fail_parse: set[str] | None = None, warn: dict | None = None):
    class Conn(BaseConnector):
        def __init__(self, raw, session=None):
            pass

        def fetch(self, spec: FetchSpec):
            if fail_fetch:
                raise LakehouseError(ErrorPayload(error_code="SOURCE_UNAVAILABLE", message=fail_fetch,
                                                  source_id=spec.source_id, dataset_id=spec.dataset_id, retryable=True))
            return list(assets or [])

    class Parser:
        def parse(self, asset):
            if fail_parse and asset.artifact_sha256 in fail_parse:
                raise LakehouseError(ErrorPayload(error_code="PARSE_FAILED", message="bad json",
                                                  source_id=asset.source_id, dataset_id=asset.dataset_id, retryable=False))
            return _batch(asset, (warn or {}).get(asset.artifact_sha256))

    return ConnectorBinding(connector_cls=Conn, parser_cls=Parser,
                            build_spec=lambda row, start, end: FetchSpec(source_id=row.source_id, dataset_id=row.dataset_id,
                                                                         locator="fixture://spec", start_date=start, end_date=end))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    con = bootstrap_database(tmp_path / "data" / "lakehouse.duckdb")
    yield {"con": con, "raw": RawStorage(tmp_path / "data" / "raw"), "bronze": ParquetStorage(tmp_path / "data" / "bronze"),
           "arts": ArtifactRepository(con), "tmp": tmp_path}
    con.close()


ROW = SeriesRow(series_id="fake_source:x", source_id=SOURCE, native_code="x", dataset_id=DATASET, name_tr="x")


def _runs(con):
    return con.execute("SELECT status, rows_out, error FROM meta.run ORDER BY started_at").fetchall()


def test_run_is_recorded_artifacts_linked_warnings_persisted(env, monkeypatch) -> None:
    a1, a2 = _asset(env["tmp"], b'{"a":1}'), _asset(env["tmp"], b'{"a":2}')
    monkeypatch.setitem(rci.CONNECTOR_REGISTRY, SOURCE, _binding([a1, a2], warn={a2.artifact_sha256: ["default 0 is not a measured zero"]}))
    out = rci._run_one(ROW, env["raw"], None, env["arts"], env["bronze"], start=date(2016, 1, 1), end=date(2016, 6, 30))
    assert out.status == "warning" and out.new == 2 and out.rows_out == 4 and out.warnings == 1 and out.run_id
    assert _runs(env["con"]) == [("warning", 4, None)]
    links = env["con"].execute("SELECT artifact_sha256 FROM meta.run_artifact WHERE run_id = ? ORDER BY 1", [out.run_id]).fetchall()
    assert sorted(x[0] for x in links) == sorted([a1.artifact_sha256, a2.artifact_sha256])
    w = env["con"].execute("SELECT warning_seq, artifact_sha256, message FROM meta.ingest_warning").fetchall()
    assert w == [(1, a2.artifact_sha256, "default 0 is not a measured zero")]


def test_fetch_failure_closes_run_as_failed_with_redacted_error(env, monkeypatch) -> None:
    monkeypatch.setitem(rci.CONNECTOR_REGISTRY, SOURCE, _binding(fail_fetch="GET https://x.invalid/y?key=LIVE-SECRET failed"))
    out = rci._run_one(ROW, env["raw"], None, env["arts"], env["bronze"])
    (status, rows, error), = _runs(env["con"])
    assert out.status == "failed" and status == "failed" and rows == 0 and error and "LIVE-SECRET" not in error
    assert "LIVE-SECRET" not in (out.error or "")


def test_one_bad_asset_fails_the_run_but_lands_the_others(env, monkeypatch) -> None:
    a1, a2 = _asset(env["tmp"], b'{"b":1}'), _asset(env["tmp"], b'{"b":2}')
    monkeypatch.setitem(rci.CONNECTOR_REGISTRY, SOURCE, _binding([a1, a2], fail_parse={a1.artifact_sha256}))
    out = rci._run_one(ROW, env["raw"], None, env["arts"], env["bronze"])
    assert out.status == "failed" and out.new == 1 and out.failed == 1 and "1/2 asset" in out.error
    assert _runs(env["con"])[0][0] == "failed"
    # the failed asset was registered and linked before parsing: "this run fetched it" survives
    assert env["con"].execute("SELECT count(*) FROM meta.run_artifact").fetchone()[0] == 2


def test_rerun_is_idempotent_and_opens_a_new_run(env, monkeypatch) -> None:
    a1 = _asset(env["tmp"], b'{"c":1}')
    monkeypatch.setitem(rci.CONNECTOR_REGISTRY, SOURCE, _binding([a1]))
    first = rci._run_one(ROW, env["raw"], None, env["arts"], env["bronze"])
    second = rci._run_one(ROW, env["raw"], None, env["arts"], env["bronze"])
    assert first.status == "ok" and second.status == "ok" and first.run_id != second.run_id
    assert env["con"].execute("SELECT count(*) FROM meta.artifact").fetchone()[0] == 1, "no duplicate artifact"
    assert [r[0] for r in _runs(env["con"])] == ["success", "success"]


def test_stale_running_run_is_closed_as_interrupted(env) -> None:
    repo = RunRepository(env["con"])
    rid = repo.start(run_id="11111111-1111-4111-8111-111111111111", source_id=SOURCE, dataset_id=DATASET,
                     started_at=datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc))
    closed = rci.close_stale_runs(env["con"], now=datetime(2026, 9, 13, 2, 0, tzinfo=timezone.utc))
    assert closed == [rid]
    status, _, error = _runs(env["con"])[0]
    assert status == "failed" and error.startswith("interrupted")
    assert rci.close_stale_runs(env["con"], now=datetime(2026, 9, 13, 3, 0, tzinfo=timezone.utc)) == []


def test_only_with_a_missing_series_is_not_success(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[2])

    class MonthlyConn(BaseConnector):
        def __init__(self, raw, session=None):
            self.raw = raw

        def fetch(self, spec):
            payload = f'{{"series":"{spec.dataset_id}"}}'.encode()
            return [_asset(tmp_path, payload, source=spec.source_id, dataset=spec.dataset_id)]

    class P:
        def parse(self, asset):
            return _batch(asset)

    monkeypatch.setitem(rci.CONNECTOR_REGISTRY, "bddk_monthly", ConnectorBinding(
        connector_cls=MonthlyConn, parser_cls=P,
        build_spec=lambda row, s, e: FetchSpec(source_id=row.source_id, dataset_id=row.dataset_id, locator="fixture://m", start_date=s, end_date=e)))
    monkeypatch.setattr(rci.time, "sleep", lambda s: None)
    report = tmp_path / "report.json"
    code = rci.main(["--database", str(tmp_path / "db.duckdb"), "--data-root", str(tmp_path / "data"),
                     "--only", "bddk_monthly:1534_Toplam,yok:seri", "--report", str(report)])
    data = json.loads(report.read_text())
    assert code == 1 and data["ok"] is False and data["missing"] == ["yok:seri"] and data["counts"]["ok"] == 1
    assert data["start"] == "2016-01-01"
    assert rci.main(["--database", str(tmp_path / "db.duckdb"), "--data-root", str(tmp_path / "data"),
                     "--start", "2026-01-01", "--end", "2025-01-01"]) == 2


def test_evds_is_windowed_and_a_full_limit_response_is_truncation(env, monkeypatch) -> None:
    """EVDS silently truncates at 1,000 observations (measured: daily FX started in 2023 instead of 2016)."""
    requested: list[tuple[date, date]] = []

    class EvdsConn(BaseConnector):
        def __init__(self, raw, session=None):
            pass

        def fetch(self, spec):
            requested.append((spec.start_date, spec.end_date))
            payload = f'{{"w":"{spec.start_date}"}}'.encode()
            return [_asset(env["tmp"], payload, source="evds", dataset="evds_fx")]

    rows = {"n": 300}

    class P:
        def parse(self, asset):
            return _batch(asset, rows=rows["n"])

    monkeypatch.setitem(rci.CONNECTOR_REGISTRY, "evds", ConnectorBinding(
        connector_cls=EvdsConn, parser_cls=P,
        build_spec=lambda row, s, e: FetchSpec(source_id="evds", dataset_id="evds_fx", locator="evds", start_date=s, end_date=e,
                                               parameters={"series": row.native_code})))
    row = SeriesRow(series_id="evds:FX", source_id="evds", native_code="FX", dataset_id="evds_fx", name_tr="fx")
    out = rci._run_one(row, env["raw"], None, env["arts"], env["bronze"], start=date(2016, 1, 1), end=date(2018, 12, 31))
    # 365 günlük pencereler (2016 artık yıl → 3 yıl 4 pencere): bitişik, boşluksuz, aralığı tam kapsar
    assert requested[0][0] == date(2016, 1, 1) and requested[-1][1] == date(2018, 12, 31) and len(requested) == 4
    assert all((b - a).days <= 364 for a, b in requested)
    assert all((nxt[0] - prev[1]).days == 1 for prev, nxt in zip(requested, requested[1:]))
    assert out.status == "ok" and out.new == len(requested)
    rows["n"] = 1000
    requested.clear()
    out2 = rci._run_one(row, env["raw"], None, env["arts"], env["bronze"], start=date(2019, 1, 1), end=date(2019, 6, 30))
    assert out2.status == "failed" and "per-request limit" in out2.error and out2.new == 0


def test_an_empty_window_in_a_windowed_fetch_is_a_warning_not_a_failure(env, monkeypatch) -> None:
    """Canlı tam set (17 Eyl 2026): 25 EVDS serisinde son pencere (2026-01..06) gözlemsiz döndü — kaynak o dönemi henüz
    yayımlamamış. Bu ingest hatası değil, kayıtlı uyarıdır; öteki pencereler iner. Her pencere boşsa yine hatadır. Boş
    gövde her seride aynı baytlardır: ikinci seri kimlik çatışması değil, aynı artifact'ı görür."""
    EMPTY = b'{"totalCount":0,"items":[]}'

    class EvdsConn(BaseConnector):
        def __init__(self, raw, session=None):
            pass

        def fetch(self, spec):
            body = EMPTY if spec.end_date.year >= 2018 else f'{{"w":"{spec.start_date}"}}'.encode()
            return [_asset(env["tmp"], body, source="evds", dataset=spec.dataset_id)]

    class P:
        def parse(self, asset):
            if asset.raw_path.read_bytes() == EMPTY:
                raise LakehouseError(ErrorPayload(error_code="EMPTY_DATASET", message="EVDS response contains no observations",
                                                  source_id=asset.source_id, dataset_id=asset.dataset_id, retryable=False))
            return _batch(asset)

    monkeypatch.setitem(rci.CONNECTOR_REGISTRY, "evds", ConnectorBinding(
        connector_cls=EvdsConn, parser_cls=P,
        build_spec=lambda row, s, e: FetchSpec(source_id="evds", dataset_id=row.dataset_id, locator="evds", start_date=s,
                                               end_date=e, parameters={"series": row.native_code})))
    row = SeriesRow(series_id="evds:X", source_id="evds", native_code="X", dataset_id="evds_x", name_tr="x")
    out = rci._run_one(row, env["raw"], None, env["arts"], env["bronze"], start=date(2016, 1, 1), end=date(2018, 6, 30))
    # üç pencere: 2016 ve 2017 dolu, 2018 (son) boş
    assert out.status == "warning" and out.new == 2 and out.empty == 1 and out.failed == 0 and out.error is None
    assert _runs(env["con"])[0][0] == "warning"
    (message,), = env["con"].execute("SELECT message FROM meta.ingest_warning").fetchall()
    assert "window 3/3" in message and "no observations" in message

    # Aynı boş baytlar başka bir seriden, tek pencereyle: kimlik çatışması yok; her pencere boş → EMPTY_DATASET hatası.
    row2 = SeriesRow(series_id="evds:Y", source_id="evds", native_code="Y", dataset_id="evds_y", name_tr="y")
    out2 = rci._run_one(row2, env["raw"], None, env["arts"], env["bronze"], start=date(2018, 1, 1), end=date(2018, 6, 30))
    assert out2.status == "failed" and "EMPTY_DATASET" in out2.error and "identity conflict" not in out2.error
    assert env["con"].execute("SELECT count(*) FROM meta.artifact WHERE byte_size = ?", [len(EMPTY)]).fetchone()[0] == 1


def test_a22_warned_artifact_ingested_twice_is_idempotent_and_keeps_each_runs_warning(env, monkeypatch) -> None:
    """K02-T08 (A22): the same bytes with a parser warning, fetched by two runs. Data lands once (one artifact, one Bronze
    file with unchanged bytes); each run keeps its own link and its own warning row, so a later Silver rebuild can still
    say which run saw the warning."""
    a1 = _asset(env["tmp"], b'{"w":1}')
    message = "default 0 is not a measured zero"
    monkeypatch.setitem(rci.CONNECTOR_REGISTRY, SOURCE, _binding([a1], warn={a1.artifact_sha256: [message]}))
    first = rci._run_one(ROW, env["raw"], None, env["arts"], env["bronze"], start=date(2016, 1, 1), end=date(2016, 6, 30))
    bronze_files = sorted((env["tmp"] / "data" / "bronze").rglob("*.parquet"))
    import hashlib
    digests = [hashlib.sha256(p.read_bytes()).hexdigest() for p in bronze_files]
    second = rci._run_one(ROW, env["raw"], None, env["arts"], env["bronze"], start=date(2016, 1, 1), end=date(2016, 6, 30))
    con = env["con"]
    assert first.status == second.status == "warning" and first.run_id != second.run_id
    assert con.execute("SELECT count(*) FROM meta.artifact WHERE artifact_sha256 = ?", [a1.artifact_sha256]).fetchone()[0] == 1
    links = con.execute("SELECT run_id FROM meta.run_artifact WHERE artifact_sha256 = ? ORDER BY run_id", [a1.artifact_sha256]).fetchall()
    assert sorted(r[0] for r in links) == sorted([first.run_id, second.run_id])
    warnings = con.execute("SELECT run_id, artifact_sha256, message FROM meta.ingest_warning ORDER BY run_id").fetchall()
    assert sorted(warnings) == sorted([(first.run_id, a1.artifact_sha256, message), (second.run_id, a1.artifact_sha256, message)])
    after = sorted((env["tmp"] / "data" / "bronze").rglob("*.parquet"))
    assert after == bronze_files and [hashlib.sha256(p.read_bytes()).hexdigest() for p in after] == digests, "Bronze idempotent"
    assert [r[0] for r in _runs(con)] == ["warning", "warning"]
