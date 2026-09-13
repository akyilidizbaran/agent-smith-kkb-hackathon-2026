"""Offline acceptance tests for deterministic EVDS windowed ingestion."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import duckdb
import pandas as pd
import pytest
import requests

from src.lakehouse.application import run_known_source_ingestion
from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.cli import main
from src.lakehouse.connectors.evds import EvdsConnector
from src.lakehouse.contracts.models import FetchedAsset, FetchSpec, ParsedBatch
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.errors import LakehouseError
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.ingestion.windowing import (
    DateWindow,
    EVDS_MAX_WINDOW_DAYS,
    EvdsWindowFailure,
    EvdsWindowReconciler,
    plan_evds_windows,
    reject_evds_truncation,
    windowed_fetch_specs,
    wrap_window_failure,
)
from src.lakehouse.parsers.evds import EvdsParser
from src.lakehouse.storage.parquet import ParquetStorage
from src.lakehouse.storage.raw import RawStorage, sha256_bytes


FIXED_TIME = datetime(2026, 9, 13, 9, tzinfo=timezone.utc)


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.status_code = status_code
        self.content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}


def _payload(*rows: tuple[str, str | None, str]) -> dict[str, Any]:
    items = [
        {
            "Tarih": observation_date,
            "TP_FG_J0": value,
            "UNIXTIME": {"$numberLong": unix_time},
        }
        for observation_date, value, unix_time in rows
    ]
    return {
        "totalCount": len(items),
        "items": items,
        "seriesNames": {"TP_FG_J0": "Synthetic CPI"},
    }


class _WindowSession:
    """Return a scripted response based on the requested EVDS window start date."""

    def __init__(self, outcomes: dict[date, object]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def get(self, url: str, *, headers: dict[str, str], **_: Any) -> _Response:
        assert headers["key"] == "window-test-key"
        self.calls.append(url)
        request_parts = urlsplit(url).path.rsplit("/", 1)[-1]
        raw_start = parse_qs("?" + request_parts)["startDate"][0]
        start = datetime.strptime(raw_start, "%d-%m-%Y").date()
        outcome = self.outcomes[start]
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            outcome = outcome()
        assert isinstance(outcome, dict)
        return _Response(outcome)


class _SequenceSession:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, _url: str, *, headers: dict[str, str], **_: Any) -> _Response:
        assert headers["key"] == "window-test-key"
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, dict)
        return _Response(outcome)


def _base_spec(start: date, end: date) -> FetchSpec:
    return FetchSpec(
        source_id="evds",
        dataset_id="evds_cpi",
        locator="registry://evds/evds_cpi",
        start_date=start,
        end_date=end,
        parameters={"series": "TP.FG.J0", "type": "json"},
        requested_at=FIXED_TIME,
    )


def _query(path: Path, statement: str) -> list[tuple[Any, ...]]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        return connection.execute(statement).fetchall()
    finally:
        connection.close()


def _pipeline(tmp_path: Path, session: Any, *, max_attempts: int = 1) -> IngestionPipeline:
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb", catalog_root=None)
    connector = EvdsConnector(
        RawStorage(tmp_path / "raw"),
        session=session,
        max_attempts=max_attempts,
        backoff_seconds=0.0,
        sleep=lambda _: None,
        clock=lambda: FIXED_TIME,
    )
    return IngestionPipeline(
        connector=connector,
        parser=EvdsParser(),
        artifact_repository=ArtifactRepository(connection),
        parquet_storage=ParquetStorage(tmp_path / "bronze"),
        clock=lambda: FIXED_TIME,
    )


def _asset(tmp_path: Path, label: str) -> FetchedAsset:
    content = label.encode("utf-8")
    digest = sha256_bytes(content)
    path = tmp_path / f"{digest}.json"
    path.write_bytes(content)
    return FetchedAsset(
        source_id="evds",
        dataset_id="evds_cpi",
        locator=f"fixture://{label}",
        media_type="application/json",
        byte_size=len(content),
        fetched_at=FIXED_TIME,
        artifact_sha256=digest,
        raw_path=path,
        http_status=200,
    )


def _batch(
    asset: FetchedAsset,
    rows: list[tuple[str, str | None, str]],
) -> ParsedBatch:
    return ParsedBatch(
        source_id=asset.source_id,
        dataset_id=asset.dataset_id,
        artifact_sha256=asset.artifact_sha256,
        schema_version="fixture-v1",
        dataframe=pd.DataFrame(
            [
                {
                    "series_id": "evds:TP.FG.J0",
                    "date_raw": observation_date,
                    "unixtime": unix_time,
                    "value_raw": value,
                    "artifact_sha256": asset.artifact_sha256,
                }
                for observation_date, value, unix_time in rows
            ],
            dtype=object,
        ),
    )


def test_planner_is_stable_and_covers_inclusive_boundaries() -> None:
    start = date(2026, 1, 1)
    end = date(2027, 1, 1)
    first = plan_evds_windows(start, end)
    second = plan_evds_windows(start, end)

    assert first == second
    assert first[0] == DateWindow(date(2026, 1, 1), date(2026, 12, 31))
    assert first[-1] == DateWindow(date(2027, 1, 1), date(2027, 1, 1))
    assert first[0].start_date == start
    assert first[-1].end_date == end
    for previous, current in zip(first, first[1:]):
        assert current.start_date == previous.end_date.fromordinal(
            previous.end_date.toordinal() + 1
        )


@pytest.mark.parametrize(
    ("start", "end", "expected_count"),
    [
        (date(2026, 1, 1), date(2026, 1, 1), 1),
        (date(2024, 2, 28), date(2024, 3, 1), 1),
        (date(2026, 1, 1), date(2026, 12, 31), 1),
        (date(2026, 1, 1), date(2027, 1, 1), 2),
        (date(2026, 12, 31), date(2027, 1, 2), 1),
    ],
)
def test_planner_handles_single_day_leap_year_and_calendar_transitions(
    start: date, end: date, expected_count: int
) -> None:
    windows = plan_evds_windows(start, end)
    assert len(windows) == expected_count
    assert windows[0].start_date == start
    assert windows[-1].end_date == end


def test_planner_rejects_reversed_ranges_and_invalid_policy() -> None:
    with pytest.raises(ValueError):
        plan_evds_windows(date(2027, 1, 1), date(2026, 1, 1))
    with pytest.raises(ValueError):
        plan_evds_windows(date(2026, 1, 1), date(2026, 1, 2), max_window_days=0)


def test_windowed_specs_retain_logical_context_without_mutating_base() -> None:
    base = _base_spec(date(2026, 1, 1), date(2027, 1, 1))
    windows = plan_evds_windows(base.start_date, base.end_date)

    specs = windowed_fetch_specs(base, windows)

    assert base.parameters == {"series": "TP.FG.J0", "type": "json"}
    assert specs[0].start_date == date(2026, 1, 1)
    assert specs[0].end_date == date(2026, 12, 31)
    assert specs[1].start_date == date(2027, 1, 1)
    assert specs[1].parameters["window_index"] == 2
    assert specs[1].parameters["window_count"] == 2
    assert specs[1].parameters["logical_start_date"] == "2026-01-01"
    assert specs[1].parameters["logical_end_date"] == "2027-01-01"


def test_reconciler_deduplicates_same_value_and_keeps_first_artifact(
    tmp_path: Path,
) -> None:
    first_asset = _asset(tmp_path, "first")
    second_asset = _asset(tmp_path, "second")
    boundary = ("01-2027", "100.00", "1798761600")
    reconciler = EvdsWindowReconciler()

    reconciler.validate_batch(
        first_asset,
        _batch(first_asset, [("12-2026", "99.00", "1796083200"), boundary]),
    )
    reconciler.validate_batch(
        second_asset,
        _batch(second_asset, [boundary, ("02-2027", "101.00", "1801440000")]),
    )

    combined = reconciler.combined()
    assert len(combined) == 3
    assert combined["value_raw"].tolist() == ["99.00", "100.00", "101.00"]
    assert combined.loc[combined["value_raw"] == "100.00", "artifact_sha256"].iloc[0] == (
        first_asset.artifact_sha256
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("100.00", "101.00"),
        (None, "101.00"),
    ],
)
def test_reconciler_rejects_revision_and_null_conflicts(
    tmp_path: Path, left: str | None, right: str | None
) -> None:
    first_asset = _asset(tmp_path, "conflict-first")
    second_asset = _asset(tmp_path, "conflict-second")
    rows = [("01-2027", left, "1798761600")]
    other_rows = [("01-2027", right, "1798761600")]
    reconciler = EvdsWindowReconciler()
    reconciler.validate_batch(first_asset, _batch(first_asset, rows))

    with pytest.raises(LakehouseError, match="conflicting EVDS boundary observation") as raised:
        reconciler.validate_batch(second_asset, _batch(second_asset, other_rows))

    assert raised.value.payload.error_code == "REVISION_CONFLICT"


def test_reconciler_accepts_null_boundary_duplicates(tmp_path: Path) -> None:
    first_asset = _asset(tmp_path, "null-first")
    second_asset = _asset(tmp_path, "null-second")
    reconciler = EvdsWindowReconciler()

    reconciler.validate_batch(
        first_asset,
        _batch(first_asset, [("01-2027", None, "1798761600")]),
    )
    reconciler.validate_batch(
        second_asset,
        _batch(second_asset, [("01-2027", None, "1798761600")]),
    )

    assert len(reconciler.combined()) == 1


def test_truncation_warning_is_fail_closed() -> None:
    asset = FetchedAsset(
        source_id="evds",
        dataset_id="evds_cpi",
        locator="fixture://truncated",
        media_type="application/json",
        byte_size=1,
        fetched_at=FIXED_TIME,
        artifact_sha256=sha256_bytes(b"x"),
        raw_path=Path("x.json"),
        http_status=200,
    )
    batch = ParsedBatch(
        source_id="evds",
        dataset_id="evds_cpi",
        artifact_sha256=asset.artifact_sha256,
        schema_version="fixture-v1",
        dataframe=pd.DataFrame({"value_raw": ["x"]}),
        warnings=["1000 observations reached the EVDS per-request limit of 1000"],
    )

    with pytest.raises(LakehouseError) as raised:
        reject_evds_truncation(asset, batch)
    assert raised.value.payload.error_code == "OBSERVATION_COUNT_MISMATCH"


def test_long_range_uses_one_logical_run_and_separate_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVDS_API_KEY", "window-test-key")
    session = _WindowSession(
        {
            date(2026, 1, 1): _payload(("01-2026", "100.00", "1767225600")),
            date(2027, 1, 1): _payload(("01-2027", "101.00", "1798761600")),
        }
    )
    database = tmp_path / "data" / "lakehouse.duckdb"
    data_root = tmp_path / "data"

    summary = run_known_source_ingestion(
        source_id="evds",
        dataset_id="evds_cpi",
        start_date=date(2026, 1, 1),
        end_date=date(2027, 1, 1),
        database=database,
        data_root=data_root,
        session=session,
        clock=lambda: FIXED_TIME,
    )

    assert len(session.calls) == 2
    assert summary.status == "success"
    assert summary.window_count == 2
    assert len(summary.artifact_sha256s) == 2
    assert len(summary.bronze_paths) == 2
    assert summary.observation_count == 2
    assert _query(database, "SELECT count(*) FROM meta.run")[0][0] == 1
    assert _query(database, "SELECT status FROM meta.run")[0][0] == "success"
    assert _query(database, "SELECT count(*) FROM meta.artifact")[0][0] == 2
    assert _query(database, "SELECT count(*) FROM meta.run_artifact")[0][0] == 2
    assert _query(database, "SELECT count(*) FROM meta.artifact_request")[0][0] == 2
    assert len(list((data_root / "raw").rglob("*.json"))) == 2
    assert len(list((data_root / "bronze").rglob("*.parquet"))) == 2
    metadata = _query(
        database,
        "SELECT request_metadata_json FROM meta.artifact_request ORDER BY request_metadata_json",
    )
    assert '"window_count":2' in metadata[0][0]
    assert "window-test-key" not in str(metadata)


def test_failed_middle_window_keeps_prior_evidence_and_run_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVDS_API_KEY", "window-test-key")
    start = date(2026, 1, 1)
    session = _WindowSession(
        {
            date(2026, 1, 1): _payload(("01-2026", "100.00", "1767225600")),
            date(2027, 1, 1): requests.ConnectionError("synthetic outage"),
            date(2028, 1, 1): _payload(("01-2028", "102.00", "1830297600")),
        }
    )
    pipeline = _pipeline(tmp_path, session)
    specs = windowed_fetch_specs(
        _base_spec(start, date(2028, 1, 1)),
        plan_evds_windows(start, date(2028, 1, 1)),
    )
    try:
        with pytest.raises(EvdsWindowFailure) as raised:
            pipeline.run_specs(specs, failure_mapper=wrap_window_failure)
        assert raised.value.index == 2
        assert raised.value.window == DateWindow(date(2027, 1, 1), date(2027, 12, 31))
        assert len(session.calls) == 2
        connection = pipeline.artifact_repository.connection
        assert connection.execute("SELECT status FROM meta.run").fetchone()[0] == "failed"
        error = connection.execute("SELECT error FROM meta.run").fetchone()[0]
        assert "2027-01-01" in error
        assert "2027-12-31" in error
        assert connection.execute("SELECT count(*) FROM meta.artifact").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM meta.run_artifact").fetchone()[0] == 1
        assert len(list((tmp_path / "raw").rglob("*.json"))) == 1
        assert len(list((tmp_path / "bronze").rglob("*.parquet"))) == 1
    finally:
        pipeline.artifact_repository.connection.close()


def test_window_reuses_existing_connector_retry_behavior(tmp_path: Path) -> None:
    session = _SequenceSession(
        [
            requests.Timeout("transient"),
            _payload(("01-2026", "100.00", "1767225600")),
        ]
    )
    connector = EvdsConnector(
        RawStorage(tmp_path / "raw"),
        session=session,
        max_attempts=2,
        backoff_seconds=0.0,
        sleep=lambda _: None,
        clock=lambda: FIXED_TIME,
    )
    spec = _base_spec(date(2026, 1, 1), date(2026, 1, 31))

    import os

    os.environ["EVDS_API_KEY"] = "window-test-key"
    try:
        assets = connector.fetch(spec)
    finally:
        os.environ.pop("EVDS_API_KEY", None)

    assert len(assets) == 1
    assert session.calls == 2


def _cli_args(database: Path, data_root: Path, end_date: str) -> list[str]:
    return [
        "ingest",
        "--source",
        "evds",
        "--dataset",
        "evds_cpi",
        "--start-date",
        "2026-01-01",
        "--end-date",
        end_date,
        "--database",
        str(database),
        "--data-root",
        str(data_root),
    ]


def test_cli_prints_multi_window_summary_and_failed_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setenv("EVDS_API_KEY", "window-test-key")
    success_session = _WindowSession(
        {
            date(2026, 1, 1): _payload(("01-2026", "100.00", "1767225600")),
            date(2027, 1, 1): _payload(("01-2027", "101.00", "1798761600")),
        }
    )
    result = main(
        _cli_args(tmp_path / "success.duckdb", tmp_path / "success-data", "2027-01-01"),
        session=success_session,
        clock=lambda: FIXED_TIME,
    )
    output = capsys.readouterr()
    assert result == 0
    assert "window_count: 2" in output.out
    assert "artifact_count: 2" in output.out
    assert "artifact_sha256s: " in output.out
    assert "bronze_paths: " in output.out
    assert "status: success" in output.out

    failed_session = _WindowSession(
        {
            date(2026, 1, 1): _payload(("01-2026", "100.00", "1767225600")),
            date(2027, 1, 1): requests.ConnectionError("synthetic outage"),
        }
    )
    result = main(
        _cli_args(tmp_path / "failed.duckdb", tmp_path / "failed-data", "2027-01-01"),
        session=failed_session,
        clock=lambda: FIXED_TIME,
    )
    error = capsys.readouterr()
    assert result != 0
    assert "status: failed" in error.err
    assert "run_id: " in error.err
    assert "failed_window_start: 2027-01-01" in error.err
    assert "failed_window_end: 2027-01-01" in error.err
    assert "window-test-key" not in error.err


def test_default_policy_is_the_documented_observation_safe_cap() -> None:
    assert EVDS_MAX_WINDOW_DAYS == 365
