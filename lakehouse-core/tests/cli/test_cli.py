"""Offline acceptance tests for the real ``python -m lakehouse`` command boundary."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from src.lakehouse.catalog.series import load_catalog_files
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
    assert "gold" in completed.stdout and "gold-run" in completed.stdout
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
    # Counted from the repository catalog rather than written as a literal: the catalog grows
    # as sources and series are added, and a hard-coded size makes an unrelated catalog commit
    # fail this test. What bootstrap must guarantee is that the real catalog is loaded whole
    # and that a second run neither duplicates nor drops a row.
    expected_series = len(load_catalog_files(ROOT / "catalog" / "series"))
    assert expected_series >= 5, "repository catalog precondition"
    assert _read(database, "SELECT count(*) FROM meta.series")[0][0] == expected_series
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


def _bronze_from_bddk_monthly_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """One real BDDK monthly artifact in Bronze; returns (database, data_root)."""

    from src.lakehouse.parsers.bddk_monthly import BddkMonthlyParser
    from src.lakehouse.storage.parquet import ParquetStorage
    from src.lakehouse.storage.raw import RawStorage

    database = tmp_path / "data" / "lakehouse.duckdb"
    data_root = tmp_path / "data"
    fixture = ROOT / "tests/fixtures/raw/bddk_monthly/bddk_monthly_housing_loans.json"
    asset = RawStorage(data_root / "raw").store(
        source_id="bddk_monthly",
        dataset_id="bddk_monthly_housing_loans",
        locator="fixture://bddk_monthly",
        content=fixture.read_bytes(),
        media_type="application/json",
        fetched_at=FIXED_TIME,
        extension="json",
        metadata={"requested_kalem_sutun": ["1534?Toplam"]},
    )
    ParquetStorage(data_root / "bronze").write(BddkMonthlyParser().parse(asset))
    return database, data_root


def test_silver_command_publishes_bronze_into_the_trusted_query_surface(
    tmp_path: Path, capsys: Any
) -> None:
    """The step that was missing between ``ingest`` and anything that reads Silver.

    Without this command a complete, successful ingestion still left
    ``silver.fact_observation`` empty, because the only callers of the snapshot operation were
    tests. The command is what makes "source to agent" a path an operator can run.
    """

    database, data_root = _bronze_from_bddk_monthly_fixture(tmp_path)

    exit_code = main(["silver", "--database", str(database), "--data-root", str(data_root)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "status: success" in output
    assert "bronze artifacts staged: 1" in output
    published = _read(
        database, "SELECT count(*) FROM silver.fact_observation"
    )[0][0]
    assert published > 0
    assert f"rows published         : {published}" in output


def test_gold_command_caches_reviewed_metrics_and_records_the_rest_as_refused(
    tmp_path: Path, capsys: Any
) -> None:
    """The committed metric catalog against a Silver holding only the BDDK monthly series.

    One metric can be built (the quarterly housing-loan stock); the other two need series
    this Silver does not hold, so the functions refuse them with ``NO_OBSERVATIONS``. The
    refusal is a recorded outcome with a reason, not a silently missing table.
    """

    database, data_root = _bronze_from_bddk_monthly_fixture(tmp_path)
    assert main(["silver", "--database", str(database), "--data-root", str(data_root)]) == 0
    capsys.readouterr()

    exit_code = main(["gold", "--database", str(database), "--data-root", str(data_root)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "status: success" in output
    assert "tables built           : 1" in output
    assert "gold.konut_kredisi_ceyreklik" in output
    assert "metrics refused        : 2" in output
    assert "NO_OBSERVATIONS" in output
    quarters = _read(database, "SELECT count(*) FROM gold.konut_kredisi_ceyreklik")[0][0]
    assert quarters > 0
    ledger = _read(
        database,
        "SELECT metric_id, status FROM meta.gold_build WHERE is_current ORDER BY metric_id",
    )
    assert ledger == [
        ("konut_faizi_aylik", "refused"),
        ("konut_kredisi_aylik_vs_haftalik", "refused"),
        ("konut_kredisi_ceyreklik", "built"),
    ]


def test_gold_run_writes_one_call_as_json_and_exits_3_on_refusal(
    tmp_path: Path, capsys: Any
) -> None:
    """The read-only single-call path an agent in another process uses."""

    database, data_root = _bronze_from_bddk_monthly_fixture(tmp_path)
    assert main(["silver", "--database", str(database), "--data-root", str(data_root)]) == 0
    capsys.readouterr()
    out = tmp_path / "gold" / "align.json"

    exit_code = main([
        "gold-run", "--database", str(database), "--function", "align_frequency",
        "--series", "bddk_monthly:1534_Toplam", "--target", "quarterly", "--out", str(out),
    ])
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert "status: success" in stdout and "function: align_frequency" in stdout
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["function"] == "align_frequency"
    assert "period_end" in document["columns"] and "artifact_sha256_list" in document["columns"]
    assert len(document["rows"]) == int(_kv(stdout)["rows"])

    refused = main([
        "gold-run", "--database", str(database), "--function", "decompose_cumulative",
        "--series", "bddk_monthly:1534_Toplam", "--out", str(tmp_path / "gold" / "dec.json"),
    ])
    stdout = capsys.readouterr().out
    assert refused == 3
    assert "status: refused" in stdout and "reason: NOT_DECOMPOSABLE" in stdout
    assert not (tmp_path / "gold" / "dec.json").exists()

    missing_target = main([
        "gold-run", "--database", str(database), "--function", "align_frequency",
        "--series", "bddk_monthly:1534_Toplam", "--out", str(tmp_path / "gold" / "x.json"),
    ])
    assert missing_target == 2
    assert "--target is required" in capsys.readouterr().err


def _kv(text: str) -> dict[str, str]:
    pairs = (line.partition(":") for line in text.splitlines() if ":" in line)
    return {key.strip(): value.strip() for key, _, value in pairs}
