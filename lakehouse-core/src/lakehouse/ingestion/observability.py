"""Durable run tracking and parser-warning storage for ingestion.

This module owns two things and nothing else: the lifecycle of a ``meta.run`` row and the
``meta.ingest_warning`` rows produced during that run. It deliberately does not know about
connectors, parsers or storage; :class:`~lakehouse.ingestion.pipeline.IngestionPipeline`
drives it.

Why a separate repository instead of extending ``ArtifactRepository``: artifacts are
metadata *about data* and are immutable once registered, whereas a run is metadata *about a
process* and is mutated exactly once (open, then close). Keeping them apart keeps both
small. Sharing one DuckDB connection between the two is fine and expected.

Trust boundary for stored text:

- **Warnings are stored verbatim.** They are produced by this repository's own parsers, so
  they are first-party text containing no credentials, no locators and no response bodies.
- **Error text is redacted and length-bounded.** A failure can surface an exception from a
  third-party library whose message may embed a request URL, a header dump or part of a
  response body. :func:`redact_error_text` is a best-effort filter over that untrusted text;
  the reliable machine-readable signal is the exception type name and, for
  :class:`~lakehouse.errors.LakehouseError`, its ``error_code``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

import duckdb

from ..contracts.identifiers import (
    validate_dataset_id,
    validate_run_id,
    validate_sha256,
    validate_source_id,
)
from ..errors import LakehouseError


class RunLifecycleError(ValueError):
    """Raised when a run transition would break the open-once/close-once lifecycle."""


class WarningIntegrityError(ValueError):
    """Raised when a warning cannot be attached to a consistent run and artifact."""


RUN_STATUS_RUNNING = "running"
RUN_STATUS_SUCCESS = "success"
RUN_STATUS_WARNING = "warning"
RUN_STATUS_FAILED = "failed"

RUN_STATUSES = frozenset(
    {RUN_STATUS_RUNNING, RUN_STATUS_SUCCESS, RUN_STATUS_WARNING, RUN_STATUS_FAILED}
)
"""Status vocabulary this layer writes to ``meta.run.status``."""

TERMINAL_RUN_STATUSES = frozenset(
    {RUN_STATUS_SUCCESS, RUN_STATUS_WARNING, RUN_STATUS_FAILED}
)
"""Statuses that close a run. ``running`` is the only non-terminal status."""

ERROR_TEXT_LIMIT = 500
"""Maximum characters of free-text error detail retained in ``meta.run.error``.

A hard bound is the second half of the redaction story: it keeps an unexpectedly chatty
third-party exception, or a library that embeds part of a response body in its message,
from being copied into the database in full.
"""

_REDACTED = "<redacted>"

_SENSITIVE_TOKENS = (
    "authorization",
    "proxy-authorization",
    "api_key",
    "apikey",
    "x-api-key",
    "key",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "pwd",
    "secret",
    "client_secret",
    "cookie",
    "set-cookie",
    "session",
)
"""Credential-shaped names whose value is removed from error text.

Deliberately broad: over-redacting an error message costs a little debuggability, while
under-redacting can copy a live credential into the database. ``key`` is in the list because
the EVDS connector sends its API key in a header literally named ``key``.
"""

_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    (?P<quote>["'])?
    \b(?P<name>""" + "|".join(re.escape(token) for token in _SENSITIVE_TOKENS) + r""")\b
    (?P=quote)?
    \s*[:=]\s*
    (?:
        "[^"]*"
      | '[^']*'
      | (?:bearer|basic|digest|token)\s+\S+   # scheme-prefixed credentials
      | [^\s,;}\)\]]+
    )
    """
)

_URL_RE = re.compile(r"(?i)\b(?P<scheme>https?|ftp)://(?P<rest>[^\s'\"<>]+)")


def _redact_url(match: re.Match[str]) -> str:
    """Drop a URL's query string and any embedded userinfo, keeping scheme/host/path."""

    rest = match.group("rest")
    rest = rest.split("?", 1)[0].split("#", 1)[0]
    authority, separator, path = rest.partition("/")
    if "@" in authority:
        authority = f"{_REDACTED}@{authority.rsplit('@', 1)[1]}"
    return f"{match.group('scheme')}://{authority}{separator}{path}"


def redact_error_text(text: str, *, limit: int = ERROR_TEXT_LIMIT) -> str:
    """Return ``text`` with credential-shaped values removed and length bounded.

    Two passes, in this order:

    1. URLs lose their query string, fragment and userinfo. Scheme, host and path survive
       because they are what makes an error diagnosable.
    2. ``name=value`` / ``name: value`` pairs whose name looks like a credential lose their
       value, whether or not the name or value is quoted.

    Finally the result is truncated to ``limit`` characters with an explicit marker, so a
    caller can tell a bounded message from a complete one.
    """

    if not isinstance(text, str):
        raise TypeError("error text must be a string")

    redacted = _URL_RE.sub(_redact_url, text)
    redacted = _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group('name')}={_REDACTED}", redacted
    )
    redacted = redacted.strip()
    if len(redacted) > limit:
        return redacted[:limit] + "...[truncated]"
    return redacted


def describe_exception(exception: BaseException, *, limit: int = ERROR_TEXT_LIMIT) -> str:
    """Build the redacted, bounded string stored in ``meta.run.error``.

    The leading segment is always machine-readable and trustworthy: the exception class
    name, plus the structured ``error_code`` when the failure is a
    :class:`~lakehouse.errors.LakehouseError`. Only the trailing free text is untrusted, and
    it has been through :func:`redact_error_text`.
    """

    name = type(exception).__name__
    if isinstance(exception, LakehouseError):
        prefix = f"{name}[{exception.payload.error_code}]"
    else:
        prefix = name

    detail = redact_error_text(str(exception), limit=limit)
    return f"{prefix}: {detail}" if detail else prefix


def _as_utc(value: datetime, field_name: str) -> datetime:
    """Require a timezone-aware timestamp and normalize it to UTC."""

    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class IngestionWarning:
    """One parser warning, positioned deterministically inside its run."""

    run_id: str
    warning_seq: int
    source_id: str
    dataset_id: str
    message: str
    artifact_sha256: str | None = None

    def __post_init__(self) -> None:
        validate_source_id(self.source_id)
        validate_dataset_id(self.dataset_id)
        if self.artifact_sha256 is not None:
            validate_sha256(self.artifact_sha256)
        if not isinstance(self.warning_seq, int) or isinstance(self.warning_seq, bool):
            raise TypeError("warning_seq must be an int")
        if self.warning_seq < 1:
            raise ValueError("warning_seq must start at 1")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("warning message must be a non-empty string")


def _epoch_ms(moment: datetime) -> int:
    """Millisecond epoch, matching DuckDB's ``epoch_ms``.

    Timestamps are compared through this rather than by reading a ``TIMESTAMPTZ`` column
    back as a Python ``datetime``: that conversion requires ``pytz``, which is deliberately
    not a project dependency.
    """

    return int(moment.timestamp() * 1000)


@dataclass
class RunRepository:
    """Open, annotate and close ``meta.run`` rows and their ``meta.ingest_warning`` rows.

    The repository holds no clock: every timestamp arrives as an argument so callers and
    tests decide time explicitly.

    A run is opened exactly once and closed exactly once. Every transition is guarded both
    by an explicit pre-check that produces a readable error and by a conditional statement
    that performs the transition atomically, so two concurrent closes cannot both succeed.
    """

    connection: duckdb.DuckDBPyConnection

    # ---------------------------------------------------------------- lifecycle

    def start(
        self,
        *,
        run_id: str,
        source_id: str,
        dataset_id: str,
        started_at: datetime,
    ) -> str:
        """Open a run as ``running`` and return its canonical id.

        ``ended_at``, ``rows_in``, ``rows_out`` and ``error`` stay NULL. Re-opening an id
        that already exists is rejected by the ``meta.run`` primary key.
        """

        canonical_run_id = validate_run_id(run_id)
        validate_source_id(source_id)
        validate_dataset_id(dataset_id)
        started = _as_utc(started_at, "started_at")
        self.connection.execute(
            """
            INSERT INTO meta.run (
                run_id, started_at, ended_at, status,
                rows_in, rows_out, error, source_id, dataset_id
            ) VALUES (?, ?, NULL, ?, NULL, NULL, NULL, ?, ?)
            """,
            [canonical_run_id, started, RUN_STATUS_RUNNING, source_id, dataset_id],
        )
        return canonical_run_id

    def finish(
        self,
        *,
        run_id: str,
        status: str,
        ended_at: datetime,
        rows_out: int | None = None,
        error: str | None = None,
    ) -> None:
        """Close an open run with a terminal status.

        ``rows_in`` is never written: source-to-Bronze ingestion receives bytes, not rows.
        ``rows_out`` is the number of Bronze rows the run actually persisted, so a failed
        run keeps whatever partial progress it made instead of reporting nothing.

        Rejects, with an explicit error: a run that does not exist, a run that is already
        closed, an ``ended_at`` earlier than the run's own ``started_at``, a ``failed``
        status carrying no error detail, and a successful status carrying error detail.
        """

        canonical_run_id = validate_run_id(run_id)
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError(
                f"finish() requires a terminal run status, got {status!r}; "
                f"expected one of {sorted(TERMINAL_RUN_STATUSES)}"
            )
        if status == RUN_STATUS_FAILED:
            if not isinstance(error, str) or not error.strip():
                raise ValueError("a failed run must carry non-empty error detail")
        elif error is not None:
            raise ValueError(f"a {status!r} run must not carry error detail")
        if rows_out is not None:
            if isinstance(rows_out, bool) or not isinstance(rows_out, int):
                raise TypeError("rows_out must be an int or None")
            if rows_out < 0:
                raise ValueError("rows_out must not be negative")
        ended = _as_utc(ended_at, "ended_at")

        current = self.connection.execute(
            "SELECT status, epoch_ms(started_at) FROM meta.run WHERE run_id = ?",
            [canonical_run_id],
        ).fetchone()
        if current is None:
            raise RunLifecycleError(f"run {canonical_run_id} does not exist and cannot be closed")
        current_status, started_epoch_ms = current
        if current_status != RUN_STATUS_RUNNING:
            raise RunLifecycleError(
                f"run {canonical_run_id} is already closed with status {current_status!r}; "
                "a run is closed exactly once"
            )
        if _epoch_ms(ended) < started_epoch_ms:
            raise RunLifecycleError(
                f"run {canonical_run_id} cannot end before it started"
            )

        # The status guard is repeated in the UPDATE so the transition itself is atomic:
        # whichever caller gets here first flips the row, and any second caller matches no
        # rows and is refused rather than silently overwriting a closed run.
        applied = self.connection.execute(
            """
            UPDATE meta.run
            SET ended_at = ?, status = ?, rows_out = ?, error = ?
            WHERE run_id = ? AND status = ?
            RETURNING run_id
            """,
            [
                ended,
                status,
                rows_out,
                error,
                canonical_run_id,
                RUN_STATUS_RUNNING,
            ],
        ).fetchall()
        if not applied:
            raise RunLifecycleError(
                f"run {canonical_run_id} was closed concurrently; a run is closed exactly once"
            )

    # ----------------------------------------------------------------- warnings

    def record_warnings(
        self, warnings: Sequence[IngestionWarning], *, created_at: datetime
    ) -> None:
        """Store parser warnings verbatim against an open, matching run.

        A run with no warnings writes nothing. Everything else is checked before a single
        row is inserted, so a partially valid batch never lands half-written: the warnings
        must all belong to one run, that run must exist and still be ``running``, their
        source and dataset must match the run's own, and any artifact digest they carry
        must name a registered artifact belonging to the same source and dataset.
        """

        if not warnings:
            return
        created = _as_utc(created_at, "created_at")

        run_ids = {validate_run_id(warning.run_id) for warning in warnings}
        if len(run_ids) != 1:
            raise WarningIntegrityError(
                "record_warnings() accepts warnings for exactly one run, got "
                f"{len(run_ids)}: {sorted(run_ids)}"
            )
        run_id = run_ids.pop()

        run = self.connection.execute(
            "SELECT status, source_id, dataset_id FROM meta.run WHERE run_id = ?",
            [run_id],
        ).fetchone()
        if run is None:
            raise WarningIntegrityError(
                f"cannot record warnings for run {run_id}: the run does not exist"
            )
        run_status, run_source_id, run_dataset_id = run
        if run_status != RUN_STATUS_RUNNING:
            raise WarningIntegrityError(
                f"cannot record warnings for run {run_id}: it is already closed with "
                f"status {run_status!r}"
            )

        for warning in warnings:
            if (warning.source_id, warning.dataset_id) != (run_source_id, run_dataset_id):
                raise WarningIntegrityError(
                    f"warning {warning.warning_seq} of run {run_id} claims "
                    f"{warning.source_id}/{warning.dataset_id} but the run recorded "
                    f"{run_source_id}/{run_dataset_id}"
                )

        self._verify_artifacts(warnings, run_id, run_source_id, run_dataset_id)

        self.connection.executemany(
            """
            INSERT INTO meta.ingest_warning (
                run_id, warning_seq, source_id, dataset_id,
                artifact_sha256, message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                [
                    run_id,
                    warning.warning_seq,
                    warning.source_id,
                    warning.dataset_id,
                    warning.artifact_sha256,
                    warning.message,
                    created,
                ]
                for warning in warnings
            ],
        )

    def _verify_artifacts(
        self,
        warnings: Sequence[IngestionWarning],
        run_id: str,
        run_source_id: str,
        run_dataset_id: str,
    ) -> None:
        """Refuse a warning that names an artifact which is missing or belongs elsewhere."""

        digests = {
            warning.artifact_sha256
            for warning in warnings
            if warning.artifact_sha256 is not None
        }
        for digest in sorted(digests):
            artifact = self.connection.execute(
                "SELECT source_id, dataset_id FROM meta.artifact WHERE artifact_sha256 = ?",
                [digest],
            ).fetchone()
            if artifact is None:
                raise WarningIntegrityError(
                    f"cannot record warnings for run {run_id}: artifact {digest} is not "
                    "registered in meta.artifact"
                )
            if tuple(artifact) != (run_source_id, run_dataset_id):
                raise WarningIntegrityError(
                    f"artifact {digest} belongs to {artifact[0]}/{artifact[1]} but run "
                    f"{run_id} covers {run_source_id}/{run_dataset_id}"
                )


__all__ = [
    "ERROR_TEXT_LIMIT",
    "RUN_STATUSES",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_RUNNING",
    "RUN_STATUS_SUCCESS",
    "RUN_STATUS_WARNING",
    "TERMINAL_RUN_STATUSES",
    "IngestionWarning",
    "RunLifecycleError",
    "RunRepository",
    "WarningIntegrityError",
    "describe_exception",
    "redact_error_text",
]
