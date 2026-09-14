"""Offline acceptance tests for the real ``python -m lakehouse`` command boundary."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from src.lakehouse.cli import main
from tests.generic._support import write_bytes, write_csv, xlsx_bytes


ROOT = Path(__file__).resolve().parents[2]
FIXED_TIME = datetime(2026, 9, 13, 9, tzinfo=timezone.utc)


class SyntheticResponse:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = json.dumps(payload).encode("utf-8")


class SyntheticSession:
    """Controlled EVDS transport; it never opens a network connection."""

    def __init__(self) -> None:
        self.response = SyntheticResponse(
            {
                "totalCount": 2,
                "items": [
                    {
                        "Tarih": "01-2026",
                        "TP_FG_J0": "100.00",
                        "UNIXTIME": {"$numberLong": "1767214800"},
                    },
                    {
                        "Tarih": "02-2026",
                        "TP_FG_J0": "110.00",
                        "UNIXTIME": {"$numberLong": "1769893200"},
                    },
                ],
                "seriesNames": {"TP_FG_J0": "SYNTHETIC"},
            }
        )
        self.urls: list[str] = []

    def get(self, url: str, *, headers: dict[str, str], **_: Any) -> SyntheticResponse:
        assert headers["key"] == "cli-test-key"
        self.urls.append(url)
        return self.response


def _read(db_path: Path, query: str) -> list[tuple[Any, ...]]:
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        return connection.execute(query).fetchall()
    finally:
        connection.close()


def _known_args(db_path: Path, data_root: Path) -> list[str]:
    return [
        "ingest",
        "--source",
        "evds",
        "--dataset",
        "evds_cpi",
        "--start-date",
        "2026-01-01",
        "--end-date",
        "2026-02-28",
        "--database",
        str(db_path),
        "--data-root",
        str(data_root),
    ]


def _adhoc_args(
    path: Path,
    db_path: Path,
    data_root: Path,
    *,
    allowed_root: Path | None = None,
    extra: list[str] | None = None,
) -> list[str]:
    return [
        "ingest-file",
        str(path),
        "--dataset-id",
        "adhoc_synthetic",
        "--allowed-local-root",
        str(allowed_root or path.parent),
        "--series-id",
        "adhoc:synthetic_series",
        "--date-column",
        "donem",
        "--value-column",
        "deger",
        "--name",
        "Synthetic CLI series",
        "--description",
        "Synthetic CLI test series.",
        "--frequency",
        "monthly",
        "--unit",
        "TRY_mn",
        "--measure-type",
        "stock",
        "--database",
        str(db_path),
        "--data-root",
        str(data_root),
        *(extra or []),
    ]


def test_help_is_a_real_module_entrypoint() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "lakehouse", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "bootstrap" in completed.stdout
    assert "ingest" in completed.stdout
    assert "ingest-file" in completed.stdout
    assert "--api-key" not in completed.stdout
    assert completed.stderr == ""


def test_invalid_arguments_are_nonzero_and_traceback_free() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "lakehouse", "ingest", "--source", "evds"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "required" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_fresh_bootstrap_and_repeat_are_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "data" / "lakehouse.duckdb"
    data_root = tmp_path / "data"

    command = [
        sys.executable,
        "-m",
        "lakehouse",
        "bootstrap",
        "--database",
        str(database),
        "--data-root",
        str(data_root),
    ]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)

    assert first.returncode == second.returncode == 0
    assert "status: success" in first.stdout
    assert _read(database, "SELECT count(*) FROM meta.series")[0][0] == 5
    assert _read(database, "SELECT count(*) FROM meta.artifact")[0][0] == 0


def test_known_source_uses_evds_pipeline_and_repeats_deterministically(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setenv("EVDS_API_KEY", "cli-test-key")
    database = tmp_path / "data" / "lakehouse.duckdb"
    data_root = tmp_path / "data"

    first = main(
        _known_args(database, data_root),
        session=SyntheticSession(),
        clock=lambda: FIXED_TIME,
    )
    first_output = capsys.readouterr()
    second = main(
        _known_args(database, data_root),
        session=SyntheticSession(),
        clock=lambda: FIXED_TIME,
    )
    second_output = capsys.readouterr()

    assert first == second == 0
    for output in (first_output.out, second_output.out):
        assert "status: success" in output
        assert "run_id: " in output
        assert "artifact_sha256: " in output
        assert "bronze_path: " in output
    assert _read(database, "SELECT count(*) FROM meta.artifact")[0][0] == 1
    assert _read(database, "SELECT count(*) FROM meta.run")[0][0] == 2
    assert _read(database, "SELECT count(*) FROM meta.run WHERE status = 'success'")[0][0] == 2
    assert len(list((data_root / "raw").rglob("*.json"))) == 1
    assert len(list((data_root / "bronze").rglob("*.parquet"))) == 1


def test_missing_evds_credential_is_a_failed_run_without_secret_output(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.delenv("EVDS_API_KEY", raising=False)
    database = tmp_path / "data" / "lakehouse.duckdb"

    result = main(
        _known_args(database, tmp_path / "data"),
        session=SyntheticSession(),
        clock=lambda: FIXED_TIME,
    )
    captured = capsys.readouterr()

    assert result != 0
    assert "EVDS_API_KEY" in captured.err
    assert "cli-test-key" not in captured.err
    assert _read(database, "SELECT status FROM meta.run")[0][0] == "failed"


def test_unknown_source_and_dataset_fail_before_successful_run(
    tmp_path: Path, capsys: Any
) -> None:
    database = tmp_path / "unknown.duckdb"
    common = [
        "--start-date",
        "2026-01-01",
        "--end-date",
        "2026-02-28",
        "--database",
        str(database),
    ]

    assert main(["ingest", "--source", "unknown", "--dataset", "x", *common]) != 0
    unknown_source = capsys.readouterr()
    assert "unknown source" in unknown_source.err
    assert not database.exists()

    assert main(["ingest", "--source", "evds", "--dataset", "unknown", *common]) != 0
    unknown_dataset = capsys.readouterr()
    assert "unknown dataset" in unknown_dataset.err
    assert not database.exists()


def test_local_csv_publishes_only_to_adhoc_and_repeats_idempotently(
    tmp_path: Path, capsys: Any
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    path = write_csv(uploads)
    database = tmp_path / "data" / "lakehouse.duckdb"
    data_root = tmp_path / "data"
    args = _adhoc_args(path, database, data_root)

    first = main(args, clock=lambda: FIXED_TIME)
    first_output = capsys.readouterr()
    second = main(args, clock=lambda: FIXED_TIME)
    second_output = capsys.readouterr()

    assert first == second == 0
    assert "source_id: adhoc" in first_output.out
    assert "rows_written: 3" in first_output.out
    assert "rows_unchanged: 3" in second_output.out
    assert _read(database, "SELECT count(*) FROM adhoc.fact_observation")[0][0] == 3
    assert _read(database, "SELECT count(*) FROM meta.series WHERE status = 'draft'")[0][0] == 1
    assert (
        _read(
            database,
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'silver' AND table_name = 'fact_observation'",
        )[0][0]
        == 0
    )


def test_local_xlsx_uses_generic_parser_and_adhoc_publication(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    path = write_bytes(
        uploads,
        "observations.xlsx",
        xlsx_bytes({"Data": [["donem", "deger"], ["2026-01-31", "7.5"]]}),
    )

    result = main(
        _adhoc_args(
            path,
            tmp_path / "data" / "lakehouse.duckdb",
            tmp_path / "data",
            extra=["--format", "xlsx", "--sheet-name", "Data"],
        ),
        clock=lambda: FIXED_TIME,
    )

    assert result == 0
    assert _read(tmp_path / "data" / "lakehouse.duckdb", "SELECT count(*) FROM adhoc.fact_observation")[0][0] == 1


def test_invalid_local_path_and_outside_root_are_rejected(tmp_path: Path, capsys: Any) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    database = tmp_path / "data" / "lakehouse.duckdb"
    data_root = tmp_path / "data"
    missing = uploads / "missing.csv"

    assert main(_adhoc_args(missing, database, data_root)) != 0
    missing_error = capsys.readouterr()
    assert "local path does not exist" in missing_error.err

    outside = tmp_path / "outside.csv"
    outside.write_text("donem,deger\n2026-01-31,1\n", encoding="utf-8")
    assert main(_adhoc_args(outside, database, data_root, allowed_root=uploads)) != 0
    outside_error = capsys.readouterr()
    assert "ACCESS_DENIED" in outside_error.err or "outside" in outside_error.err


def test_ambiguous_generic_input_fails_through_production_parser(
    tmp_path: Path, capsys: Any
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    path = write_csv(uploads, "ambiguous.csv", "a,b;c\n1,2;3\n")

    result = main(
        _adhoc_args(
            path,
            tmp_path / "data" / "lakehouse.duckdb",
            tmp_path / "data",
            extra=["--format", "csv"],
        )
    )
    captured = capsys.readouterr()

    assert result != 0
    assert "delimiter" in captured.err
    assert _read(tmp_path / "data" / "lakehouse.duckdb", "SELECT status FROM meta.run")[0][0] == "failed"
