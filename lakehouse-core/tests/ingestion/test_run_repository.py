"""Unit tests for the run/warning repository and its redaction helpers.

These tests touch DuckDB and the migration, but never a connector, parser or the pipeline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.errors import ErrorPayload, LakehouseError
from src.lakehouse.ingestion.observability import (
    ERROR_TEXT_LIMIT,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    RUN_STATUS_WARNING,
    TERMINAL_RUN_STATUSES,
    IngestionWarning,
    RunLifecycleError,
    RunRepository,
    WarningIntegrityError,
    describe_exception,
    redact_error_text,
)
from src.lakehouse.storage.raw import sha256_bytes


RUN_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
STARTED_AT = datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc)
ENDED_AT = datetime(2026, 9, 10, 6, 0, 5, tzinfo=timezone.utc)
DIGEST = sha256_bytes(b"artifact")


def _repository(tmp_path: Path) -> RunRepository:
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    return RunRepository(connection)


def _epoch(moment: datetime) -> int:
    """Millisecond epoch, matching DuckDB's ``epoch_ms``."""

    return int(moment.timestamp() * 1000)


def _register_artifact(
    repository: RunRepository,
    *,
    source_id: str = "fake_source",
    dataset_id: str = "fake_dataset",
    digest: str = DIGEST,
) -> str:
    """Register a minimal artifact so warnings can legally reference it."""

    repository.connection.execute(
        """
        INSERT INTO meta.artifact (
            artifact_sha256, source_id, dataset_id, locator, media_type,
            byte_size, http_status, fetched_at, raw_path, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, 'fixture://a', 'application/json', 8, 200, ?, '/tmp/a', ?, ?)
        """,
        [digest, source_id, dataset_id, STARTED_AT, STARTED_AT, STARTED_AT],
    )
    return digest


def _open_run(repository: RunRepository, **overrides) -> None:
    """Open the canonical test run."""

    repository.start(
        **{
            "run_id": RUN_ID,
            "source_id": "fake_source",
            "dataset_id": "fake_dataset",
            "started_at": STARTED_AT,
            **overrides,
        }
    )


def _run_row(repository: RunRepository) -> tuple:
    # TIMESTAMPTZ columns are read back through epoch_ms, the convention this repository
    # already uses elsewhere: converting one to a Python datetime would pull in pytz, which
    # is not a project dependency.
    return repository.connection.execute(
        """
        SELECT run_id, epoch_ms(started_at), epoch_ms(ended_at), status,
               rows_in, rows_out, error, source_id, dataset_id
        FROM meta.run
        """
    ).fetchone()


# --------------------------------------------------------------------- schema


def test_migration_creates_warning_table_and_extends_run(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        tables = {
            row[0]
            for row in repository.connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'meta'"
            ).fetchall()
        }
        assert "ingest_warning" in tables

        columns = {
            row[0]
            for row in repository.connection.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'meta' AND table_name = 'ingest_warning'
                """
            ).fetchall()
        }
        assert columns == {
            "run_id",
            "warning_seq",
            "source_id",
            "dataset_id",
            "artifact_sha256",
            "message",
            "created_at",
        }

        run_columns = {
            row[0]
            for row in repository.connection.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'meta' AND table_name = 'run'
                """
            ).fetchall()
        }
        assert {"source_id", "dataset_id"} <= run_columns
    finally:
        repository.connection.close()


def test_migration_is_idempotent_across_repeated_bootstraps(tmp_path: Path) -> None:
    """Acceptance criterion 14: re-running the migration must not raise."""

    db_path = tmp_path / "lakehouse.duckdb"
    for _ in range(3):
        connection = bootstrap_database(db_path)
        connection.close()

    repository = RunRepository(bootstrap_database(db_path))
    try:
        run_columns = [
            row[0]
            for row in repository.connection.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'meta' AND table_name = 'run'
                """
            ).fetchall()
        ]
        # ADD COLUMN IF NOT EXISTS must not append duplicates on every bootstrap.
        assert run_columns.count("source_id") == 1
        assert run_columns.count("dataset_id") == 1
    finally:
        repository.connection.close()


# ------------------------------------------------------------------ lifecycle


def test_start_opens_a_running_row_with_unknown_counters(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        repository.start(
            run_id=RUN_ID,
            source_id="fake_source",
            dataset_id="fake_dataset",
            started_at=STARTED_AT,
        )
        row = _run_row(repository)
        assert row[0] == RUN_ID
        assert row[1] == _epoch(STARTED_AT)
        assert row[2] is None
        assert row[3] == RUN_STATUS_RUNNING
        assert row[4] is None  # rows_in is never claimed for byte-oriented ingestion
        assert row[5] is None
        assert row[6] is None
        assert row[7] == "fake_source"
        assert row[8] == "fake_dataset"
    finally:
        repository.connection.close()


@pytest.mark.parametrize("status", sorted(TERMINAL_RUN_STATUSES))
def test_finish_closes_the_run_with_each_terminal_status(tmp_path: Path, status: str) -> None:
    repository = _repository(tmp_path)
    try:
        repository.start(
            run_id=RUN_ID,
            source_id="fake_source",
            dataset_id="fake_dataset",
            started_at=STARTED_AT,
        )
        error = "RuntimeError: boom" if status == RUN_STATUS_FAILED else None
        repository.finish(
            run_id=RUN_ID, status=status, ended_at=ENDED_AT, rows_out=7, error=error
        )
        row = _run_row(repository)
        assert row[2] == _epoch(ENDED_AT)
        assert row[3] == status
        assert row[4] is None
        assert row[5] == 7
    finally:
        repository.connection.close()


def test_finish_rejects_a_non_terminal_status(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        repository.start(
            run_id=RUN_ID,
            source_id="fake_source",
            dataset_id="fake_dataset",
            started_at=STARTED_AT,
        )
        with pytest.raises(ValueError, match="terminal run status"):
            repository.finish(
                run_id=RUN_ID, status=RUN_STATUS_RUNNING, ended_at=ENDED_AT
            )
    finally:
        repository.connection.close()


def test_naive_timestamps_are_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        with pytest.raises(ValueError, match="timezone-aware"):
            repository.start(
                run_id=RUN_ID,
                source_id="fake_source",
                dataset_id="fake_dataset",
                started_at=datetime(2026, 9, 10, 6, 0),
            )
    finally:
        repository.connection.close()


def test_non_utc_timestamps_are_normalized_to_utc(tmp_path: Path) -> None:
    """Acceptance criterion 9: stored moments are UTC regardless of caller offset."""

    repository = _repository(tmp_path)
    try:
        istanbul = timezone(timedelta(hours=3))
        repository.start(
            run_id=RUN_ID,
            source_id="fake_source",
            dataset_id="fake_dataset",
            started_at=datetime(2026, 9, 10, 9, 0, tzinfo=istanbul),
        )
        assert _run_row(repository)[1] == _epoch(STARTED_AT)
    finally:
        repository.connection.close()


def test_negative_rows_out_is_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        repository.start(
            run_id=RUN_ID,
            source_id="fake_source",
            dataset_id="fake_dataset",
            started_at=STARTED_AT,
        )
        with pytest.raises(ValueError, match="must not be negative"):
            repository.finish(
                run_id=RUN_ID,
                status=RUN_STATUS_SUCCESS,
                ended_at=ENDED_AT,
                rows_out=-1,
            )
    finally:
        repository.connection.close()


# ------------------------------------------------------------------- warnings


def test_record_warnings_stores_every_message_verbatim(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        repository.start(
            run_id=RUN_ID,
            source_id="fake_source",
            dataset_id="fake_dataset",
            started_at=STARTED_AT,
        )
        _register_artifact(repository)
        messages = [
            "1000 observations reached the EVDS per-request limit of 1000; the response "
            "may be silently truncated",
            "column 'x' declares a grid display defaultValue of '0'",
        ]
        repository.record_warnings(
            [
                IngestionWarning(
                    run_id=RUN_ID,
                    warning_seq=index,
                    source_id="fake_source",
                    dataset_id="fake_dataset",
                    artifact_sha256=DIGEST,
                    message=message,
                )
                for index, message in enumerate(messages, start=1)
            ],
            created_at=STARTED_AT,
        )
        rows = repository.connection.execute(
            """
            SELECT warning_seq, source_id, dataset_id, artifact_sha256, message,
                   epoch_ms(created_at)
            FROM meta.ingest_warning WHERE run_id = ? ORDER BY warning_seq
            """,
            [RUN_ID],
        ).fetchall()
        assert [row[0] for row in rows] == [1, 2]
        assert [row[4] for row in rows] == messages
        assert all(row[3] == DIGEST for row in rows)
        assert all(row[5] == _epoch(STARTED_AT) for row in rows)
    finally:
        repository.connection.close()


def test_recording_an_empty_warning_list_writes_nothing(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        repository.record_warnings([], created_at=STARTED_AT)
        assert repository.connection.execute(
            "SELECT count(*) FROM meta.ingest_warning"
        ).fetchone() == (0,)
    finally:
        repository.connection.close()


def test_duplicate_warning_sequence_in_one_run_is_rejected(tmp_path: Path) -> None:
    """The (run_id, warning_seq) primary key is the deterministic warning identity."""

    repository = _repository(tmp_path)
    try:
        repository.start(
            run_id=RUN_ID,
            source_id="fake_source",
            dataset_id="fake_dataset",
            started_at=STARTED_AT,
        )
        warning = IngestionWarning(
            run_id=RUN_ID,
            warning_seq=1,
            source_id="fake_source",
            dataset_id="fake_dataset",
            message="first",
        )
        repository.record_warnings([warning], created_at=STARTED_AT)
        with pytest.raises(Exception):
            repository.record_warnings([warning], created_at=STARTED_AT)
    finally:
        repository.connection.close()


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"warning_seq": 0}, "must start at 1"),
        ({"message": "   "}, "non-empty string"),
        ({"source_id": "Bad Source"}, "snake_case"),
        ({"artifact_sha256": "nothex"}, "hexadecimal digest"),
    ],
)
def test_ingestion_warning_validates_its_fields(kwargs: dict, expected: str) -> None:
    base = {
        "run_id": RUN_ID,
        "warning_seq": 1,
        "source_id": "fake_source",
        "dataset_id": "fake_dataset",
        "message": "a warning",
    }
    with pytest.raises(ValueError, match=expected):
        IngestionWarning(**{**base, **kwargs})


def test_ingestion_warning_allows_an_unattributed_artifact() -> None:
    warning = IngestionWarning(
        run_id=RUN_ID,
        warning_seq=1,
        source_id="fake_source",
        dataset_id="fake_dataset",
        message="not tied to one artifact",
    )
    assert warning.artifact_sha256 is None


# ------------------------------------------------------------------ redaction


@pytest.mark.parametrize(
    "text, must_not_contain",
    [
        ("https://evds3.tcmb.gov.tr/path?key=SUPERSECRET123&type=json", "SUPERSECRET123"),
        ("https://host/igmevdsms-dis/series=TP.X&key=REALSECRET", "REALSECRET"),
        ("Authorization: Bearer abc123XYZtoken", "abc123XYZtoken"),
        ("headers={'key': 'MY-REAL-EVDS-KEY'}", "MY-REAL-EVDS-KEY"),
        ("api_key=AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        ("token: t0ps3cr3t", "t0ps3cr3t"),
        ("https://user:hunter2@host.example.com/data", "hunter2"),
        ('password = "p@ssw0rd"', "p@ssw0rd"),
        ("x-api-key: zzz999", "zzz999"),
        ("cookie: session=deadbeef", "deadbeef"),
    ],
)
def test_redaction_removes_credential_shaped_values(text: str, must_not_contain: str) -> None:
    assert must_not_contain not in redact_error_text(text)


def test_redaction_keeps_diagnosable_context() -> None:
    redacted = redact_error_text("connection refused to https://www.bddk.org.tr/x?key=a")
    assert "connection refused" in redacted
    assert "www.bddk.org.tr" in redacted


def test_redaction_leaves_ordinary_text_untouched() -> None:
    message = "5 periods returned but 66 were requested"
    assert redact_error_text(message) == message


def test_redaction_bounds_length_so_response_bodies_cannot_be_copied_whole() -> None:
    redacted = redact_error_text("B" * 5_000)
    assert redacted.endswith("...[truncated]")
    assert len(redacted) == ERROR_TEXT_LIMIT + len("...[truncated]")


def test_describe_exception_leads_with_the_structured_error_code() -> None:
    error = LakehouseError(
        ErrorPayload(
            error_code="HTTP_ERROR",
            message="EVDS responded with HTTP 403",
            source_id="evds",
            dataset_id="evds_housing_price_index",
            retryable=False,
        )
    )
    assert describe_exception(error) == "LakehouseError[HTTP_ERROR]: EVDS responded with HTTP 403"


def test_describe_exception_redacts_third_party_text() -> None:
    described = describe_exception(RuntimeError("failed with key=LIVE-SECRET"))
    assert described.startswith("RuntimeError:")
    assert "LIVE-SECRET" not in described


def test_describe_exception_survives_an_empty_message() -> None:
    assert describe_exception(RuntimeError()) == "RuntimeError"


def test_finish_stores_a_failure_description_without_secrets(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        repository.start(
            run_id=RUN_ID,
            source_id="fake_source",
            dataset_id="fake_dataset",
            started_at=STARTED_AT,
        )
        repository.finish(
            run_id=RUN_ID,
            status=RUN_STATUS_FAILED,
            ended_at=ENDED_AT,
            rows_out=0,
            error=describe_exception(RuntimeError("boom api_key=LIVE-SECRET")),
        )
        row = _run_row(repository)
        assert row[3] == RUN_STATUS_FAILED
        assert "LIVE-SECRET" not in row[6]
        assert "RuntimeError" in row[6]
    finally:
        repository.connection.close()


def test_status_vocabulary_is_closed() -> None:
    assert RUN_STATUS_RUNNING not in TERMINAL_RUN_STATUSES
    assert TERMINAL_RUN_STATUSES == {
        RUN_STATUS_SUCCESS,
        RUN_STATUS_WARNING,
        RUN_STATUS_FAILED,
    }


# ------------------------------------------------- lifecycle is enforced, not assumed


def test_start_rejects_a_run_id_that_is_not_a_uuid(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        with pytest.raises(ValueError, match="must be a valid UUID"):
            _open_run(repository, run_id="not-a-uuid")
    finally:
        repository.connection.close()


def test_finish_rejects_a_run_id_that_is_not_a_uuid(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        with pytest.raises(ValueError, match="must be a valid UUID"):
            repository.finish(
                run_id="not-a-uuid", status=RUN_STATUS_SUCCESS, ended_at=ENDED_AT
            )
    finally:
        repository.connection.close()


def test_start_returns_the_canonical_run_id(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        returned = repository.start(
            run_id=RUN_ID.upper(),
            source_id="fake_source",
            dataset_id="fake_dataset",
            started_at=STARTED_AT,
        )
        assert returned == RUN_ID
        assert _run_row(repository)[0] == RUN_ID
    finally:
        repository.connection.close()


def test_opening_the_same_run_twice_is_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        with pytest.raises(Exception):
            _open_run(repository)
    finally:
        repository.connection.close()


def test_closing_a_run_that_does_not_exist_is_rejected(tmp_path: Path) -> None:
    """Acceptance criterion 4."""

    repository = _repository(tmp_path)
    try:
        with pytest.raises(RunLifecycleError, match="does not exist"):
            repository.finish(
                run_id=RUN_ID, status=RUN_STATUS_SUCCESS, ended_at=ENDED_AT, rows_out=0
            )
    finally:
        repository.connection.close()


@pytest.mark.parametrize("first_status", sorted(TERMINAL_RUN_STATUSES))
def test_closing_a_terminal_run_again_is_rejected(tmp_path: Path, first_status: str) -> None:
    """Acceptance criterion 5: a run is closed exactly once."""

    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        repository.finish(
            run_id=RUN_ID,
            status=first_status,
            ended_at=ENDED_AT,
            rows_out=3,
            error="RuntimeError: boom" if first_status == RUN_STATUS_FAILED else None,
        )
        with pytest.raises(RunLifecycleError, match="already closed"):
            repository.finish(
                run_id=RUN_ID, status=RUN_STATUS_SUCCESS, ended_at=ENDED_AT, rows_out=99
            )

        # The refused second close must not have altered the stored row.
        row = _run_row(repository)
        assert row[3] == first_status
        assert row[5] == 3
    finally:
        repository.connection.close()


def test_ending_before_starting_is_rejected(tmp_path: Path) -> None:
    """Acceptance criterion 6."""

    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        with pytest.raises(RunLifecycleError, match="cannot end before it started"):
            repository.finish(
                run_id=RUN_ID,
                status=RUN_STATUS_SUCCESS,
                ended_at=STARTED_AT - timedelta(seconds=1),
                rows_out=0,
            )
        assert _run_row(repository)[3] == RUN_STATUS_RUNNING
    finally:
        repository.connection.close()


def test_ending_exactly_at_the_start_moment_is_allowed(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        repository.finish(
            run_id=RUN_ID, status=RUN_STATUS_SUCCESS, ended_at=STARTED_AT, rows_out=0
        )
        assert _run_row(repository)[3] == RUN_STATUS_SUCCESS
    finally:
        repository.connection.close()


def test_failed_run_must_carry_error_detail(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        for blank in (None, "", "   "):
            with pytest.raises(ValueError, match="non-empty error detail"):
                repository.finish(
                    run_id=RUN_ID,
                    status=RUN_STATUS_FAILED,
                    ended_at=ENDED_AT,
                    error=blank,
                )
        assert _run_row(repository)[3] == RUN_STATUS_RUNNING
    finally:
        repository.connection.close()


@pytest.mark.parametrize("status", [RUN_STATUS_SUCCESS, RUN_STATUS_WARNING])
def test_successful_run_must_not_carry_error_detail(tmp_path: Path, status: str) -> None:
    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        with pytest.raises(ValueError, match="must not carry error detail"):
            repository.finish(
                run_id=RUN_ID, status=status, ended_at=ENDED_AT, error="something"
            )
    finally:
        repository.connection.close()


def test_a_run_row_is_modified_exactly_once(tmp_path: Path) -> None:
    """The 'open once, close once' claim, proven rather than asserted in a docstring."""

    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        assert _run_row(repository)[3] == RUN_STATUS_RUNNING

        repository.finish(
            run_id=RUN_ID, status=RUN_STATUS_SUCCESS, ended_at=ENDED_AT, rows_out=1
        )
        closed = _run_row(repository)

        for status in sorted(TERMINAL_RUN_STATUSES):
            with pytest.raises(RunLifecycleError):
                repository.finish(
                    run_id=RUN_ID,
                    status=status,
                    ended_at=ENDED_AT,
                    rows_out=1234,
                    error="x" if status == RUN_STATUS_FAILED else None,
                )

        assert _run_row(repository) == closed
        assert repository.connection.execute("SELECT count(*) FROM meta.run").fetchone() == (1,)
    finally:
        repository.connection.close()


# --------------------------------------------- warning / run / artifact integrity


def _warning(**overrides) -> IngestionWarning:
    return IngestionWarning(
        **{
            "run_id": RUN_ID,
            "warning_seq": 1,
            "source_id": "fake_source",
            "dataset_id": "fake_dataset",
            "message": "a warning",
            **overrides,
        }
    )


def test_warnings_for_a_missing_run_are_rejected(tmp_path: Path) -> None:
    """Acceptance criterion 7."""

    repository = _repository(tmp_path)
    try:
        with pytest.raises(WarningIntegrityError, match="the run does not exist"):
            repository.record_warnings([_warning()], created_at=STARTED_AT)
        assert repository.connection.execute(
            "SELECT count(*) FROM meta.ingest_warning"
        ).fetchone() == (0,)
    finally:
        repository.connection.close()


def test_warnings_for_a_closed_run_are_rejected(tmp_path: Path) -> None:
    """Acceptance criterion 8."""

    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        repository.finish(
            run_id=RUN_ID, status=RUN_STATUS_SUCCESS, ended_at=ENDED_AT, rows_out=0
        )
        with pytest.raises(WarningIntegrityError, match="already closed"):
            repository.record_warnings([_warning()], created_at=ENDED_AT)
    finally:
        repository.connection.close()


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_id": "other_source"},
        {"dataset_id": "other_dataset"},
        {"source_id": "other_source", "dataset_id": "other_dataset"},
    ],
)
def test_warnings_that_disagree_with_the_run_identity_are_rejected(
    tmp_path: Path, overrides: dict
) -> None:
    """Acceptance criterion 9."""

    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        with pytest.raises(WarningIntegrityError, match="but the run recorded"):
            repository.record_warnings([_warning(**overrides)], created_at=STARTED_AT)
        assert repository.connection.execute(
            "SELECT count(*) FROM meta.ingest_warning"
        ).fetchone() == (0,)
    finally:
        repository.connection.close()


def test_warnings_naming_an_unregistered_artifact_are_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        with pytest.raises(WarningIntegrityError, match="not\\s+registered in meta.artifact"):
            repository.record_warnings(
                [_warning(artifact_sha256=DIGEST)], created_at=STARTED_AT
            )
    finally:
        repository.connection.close()


def test_warnings_naming_an_artifact_from_another_dataset_are_rejected(tmp_path: Path) -> None:
    """Acceptance criterion 10."""

    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        _register_artifact(repository, dataset_id="another_dataset")
        with pytest.raises(WarningIntegrityError, match="belongs to"):
            repository.record_warnings(
                [_warning(artifact_sha256=DIGEST)], created_at=STARTED_AT
            )
        assert repository.connection.execute(
            "SELECT count(*) FROM meta.ingest_warning"
        ).fetchone() == (0,)
    finally:
        repository.connection.close()


def test_warnings_for_two_different_runs_cannot_be_mixed_in_one_call(tmp_path: Path) -> None:
    other_run_id = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        _open_run(repository, run_id=other_run_id)
        with pytest.raises(WarningIntegrityError, match="exactly one run"):
            repository.record_warnings(
                [_warning(), _warning(run_id=other_run_id, warning_seq=2)],
                created_at=STARTED_AT,
            )
        assert repository.connection.execute(
            "SELECT count(*) FROM meta.ingest_warning"
        ).fetchone() == (0,)
    finally:
        repository.connection.close()


def test_record_warnings_rejects_a_run_id_that_is_not_a_uuid(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    try:
        with pytest.raises(ValueError, match="must be a valid UUID"):
            repository.record_warnings(
                [_warning(run_id="not-a-uuid")], created_at=STARTED_AT
            )
    finally:
        repository.connection.close()


def test_a_rejected_batch_leaves_no_partial_rows(tmp_path: Path) -> None:
    """The first warning is valid; the second is not. Neither may land."""

    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        with pytest.raises(WarningIntegrityError):
            repository.record_warnings(
                [
                    _warning(warning_seq=1, message="valid"),
                    _warning(warning_seq=2, source_id="other_source"),
                ],
                created_at=STARTED_AT,
            )
        assert repository.connection.execute(
            "SELECT count(*) FROM meta.ingest_warning"
        ).fetchone() == (0,)
    finally:
        repository.connection.close()


# ------------------------------------------------------- storage-level constraints


@pytest.mark.parametrize(
    "warning_seq, message",
    [(0, "a message"), (-1, "a message"), (1, "   "), (1, "")],
)
def test_storage_rejects_bad_rows_even_without_the_repository(
    tmp_path: Path, warning_seq: int, message: str
) -> None:
    """The CHECK constraints hold for anything that writes the table directly."""

    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        with pytest.raises(Exception):
            repository.connection.execute(
                """
                INSERT INTO meta.ingest_warning (
                    run_id, warning_seq, source_id, dataset_id,
                    artifact_sha256, message, created_at
                ) VALUES (?, ?, 'fake_source', 'fake_dataset', NULL, ?, ?)
                """,
                [RUN_ID, warning_seq, message, STARTED_AT],
            )
    finally:
        repository.connection.close()


def test_a_run_with_warnings_can_still_be_closed(tmp_path: Path) -> None:
    """Regression guard for the foreign key that was measured and removed.

    A `FOREIGN KEY (run_id) REFERENCES meta.run(run_id)` on meta.ingest_warning makes this
    exact sequence fail on DuckDB 1.5.5: once a warning references the run, the conditional
    `UPDATE ... RETURNING` that closes it is refused as a constraint violation, leaving the
    run `running` forever. See the comment block in
    sql/bootstrap/010_ingestion_observability.sql.
    """

    repository = _repository(tmp_path)
    try:
        _open_run(repository)
        _register_artifact(repository)
        repository.record_warnings(
            [_warning(artifact_sha256=DIGEST)], created_at=STARTED_AT
        )
        repository.finish(
            run_id=RUN_ID, status=RUN_STATUS_WARNING, ended_at=ENDED_AT, rows_out=2
        )
        assert _run_row(repository)[3] == RUN_STATUS_WARNING
    finally:
        repository.connection.close()
