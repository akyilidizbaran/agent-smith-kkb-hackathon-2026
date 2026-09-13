"""Register a machine-proposed series as a **draft**, without touching the YAML catalog.

The Git-versioned catalog under ``catalog/series/`` is the record of what a human reviewed.
That property is what makes ``semantic_confidence: verified`` mean anything, and a profiler
writing into those files would quietly destroy it. So this module writes only to
``meta.series``, only as a draft, and cannot be argued into anything stronger.

The three fields that carry the evidence claim are **not parameters in any meaningful sense**:
``semantic_confidence`` is fixed at ``derived``, ``semantic_source`` at ``profiler`` and
``status`` at ``draft``. They appear in the signature so a reader sees what will be written
and so a caller passing the wrong value gets a refusal rather than a surprise -- not so the
value can be chosen.

A ``draft`` series is deliberately unusable by Gold: :func:`lakehouse.gold.align_frequency`
refuses anything that is not ``active``, and it also refuses anything that is not ``verified``.
That is the point. A profiler's guess becomes usable only after a human promotes it, and this
version ships no promotion path on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import duckdb

from .series import CatalogError, SeriesRecord, build_series_record


DRAFT_CONFIDENCE: Final[str] = "derived"
DRAFT_SEMANTIC_SOURCE: Final[str] = "profiler"
DRAFT_STATUS: Final[str] = "draft"

_PROTECTED_STATUSES: Final[frozenset[str]] = frozenset({"active", "deprecated"})
"""A row a human published, or withdrew, is never rewritten by a machine proposal."""

_PROTECTED_CONFIDENCES: Final[frozenset[str]] = frozenset({"verified"})

_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "series_id",
    "source_id",
    "native_code",
    "dataset_id",
    "name_tr",
    "description",
    "aliases",
    "tags",
    "frequency",
    "week_anchor",
    "unit",
    "measure_type",
    "default_agg",
    "cumulative_reset",
    "semantic_confidence",
    "semantic_source",
    "metadata_url",
    "status",
    "catalog_content_sha256",
)
"""Mirrors the loader's write columns. ``first_obs``, ``last_obs`` and ``updated_at`` are
absent: coverage is operational and belongs to the Silver refresh, not to a registration."""


class RegistrationError(ValueError):
    """Raised when a proposed series cannot be registered as written."""


class RegistrationConflict(RegistrationError):
    """Raised when a different record already occupies the same ``series_id``."""


@dataclass(frozen=True)
class RegistrationResult:
    """What one registration did."""

    series_id: str
    inserted: bool
    unchanged: bool
    content_sha256: str


def _existing(
    connection: duckdb.DuckDBPyConnection, series_id: str
) -> tuple[str, str, str] | None:
    row = connection.execute(
        """
        SELECT catalog_content_sha256, semantic_confidence, status
        FROM meta.series
        WHERE series_id = ?
        """,
        [series_id],
    ).fetchone()
    return None if row is None else (row[0], row[1], row[2])


def _values(record: SeriesRecord) -> list[Any]:
    payload = record.payload()
    return [payload[name] for name in _WRITE_COLUMNS[:-1]] + [record.content_sha256]


def register_series(
    connection: duckdb.DuckDBPyConnection,
    record: dict[str, Any],
    *,
    source_id: str = "adhoc",
    confidence: str = DRAFT_CONFIDENCE,
    semantic_source: str = DRAFT_SEMANTIC_SOURCE,
    status: str = DRAFT_STATUS,
) -> RegistrationResult:
    """Insert a proposed series into ``meta.series`` as a draft.

    ``record`` is a plain dict in the same shape a catalog YAML entry uses, and it goes
    through :func:`lakehouse.catalog.series.build_series_record` -- the same eighteen rules the
    file loader applies. There is no second validator to drift out of step.

    Behaviour that matters:

    - **Draft only.** ``confidence``, ``semantic_source`` and ``status`` must be the draft
      values or the call is refused. A caller cannot mint a ``verified`` or ``active`` row.
    - **Never overwrites a reviewed row.** An existing ``verified`` record, or one that is
      ``active`` or ``deprecated``, is protected: the call raises rather than replacing it.
    - **Idempotent for identical content.** Re-registering the same proposal is a no-op, and
      ``updated_at`` does not churn.
    - **Conflicts are loud.** The same ``series_id`` with different content raises
      :class:`RegistrationConflict` instead of silently replacing what is there.
    - **Coverage is untouched.** ``first_obs`` and ``last_obs`` are neither written nor
      cleared; they describe the Silver snapshot and this is not one.
    - **One transaction.** A validation or constraint failure leaves ``meta.series`` exactly
      as it was.
    """

    if confidence != DRAFT_CONFIDENCE:
        raise RegistrationError(
            f"programmatic registration writes {DRAFT_CONFIDENCE!r} records only; "
            f"{confidence!r} would claim evidence this path cannot produce. A verified entry "
            "belongs in catalog/series/*.yml, reviewed in Git"
        )
    if semantic_source != DRAFT_SEMANTIC_SOURCE:
        raise RegistrationError(
            f"programmatic registration records semantic_source {DRAFT_SEMANTIC_SOURCE!r} "
            f"only, not {semantic_source!r}"
        )
    if status != DRAFT_STATUS:
        raise RegistrationError(
            f"programmatic registration writes {DRAFT_STATUS!r} rows only; {status!r} would "
            "make a machine proposal usable by Gold without review"
        )
    if not isinstance(record, dict):
        raise RegistrationError("record must be a dict shaped like a catalog entry")

    entry = dict(record)
    # The three evidence fields are set here, not read from the caller's dict, so a record
    # carrying its own `semantic_confidence: verified` cannot slip past the checks above.
    entry["semantic_confidence"] = DRAFT_CONFIDENCE
    entry["semantic_source"] = DRAFT_SEMANTIC_SOURCE
    entry["status"] = DRAFT_STATUS

    try:
        validated = build_series_record(
            entry, source_id, where="register_series()"
        )
    except CatalogError as exc:
        raise RegistrationError(str(exc)) from exc

    current = _existing(connection, validated.series_id)
    if current is not None:
        existing_hash, existing_confidence, existing_status = current
        if existing_confidence in _PROTECTED_CONFIDENCES:
            raise RegistrationConflict(
                f"{validated.series_id!r} is already registered as "
                f"{existing_confidence!r}; a reviewed record is never replaced by a machine "
                "proposal"
            )
        if existing_status in _PROTECTED_STATUSES:
            raise RegistrationConflict(
                f"{validated.series_id!r} already has status {existing_status!r}; a machine "
                "proposal does not overwrite a published or withdrawn series"
            )
        if existing_hash == validated.content_sha256:
            # Same proposal, already stored. Returning quietly keeps a retrying profiler from
            # churning updated_at on every attempt.
            return RegistrationResult(
                series_id=validated.series_id,
                inserted=False,
                unchanged=True,
                content_sha256=validated.content_sha256,
            )
        raise RegistrationConflict(
            f"{validated.series_id!r} already exists as a draft with different content; "
            "delete or promote the existing draft before proposing a different one"
        )

    placeholders = ", ".join("?" for _ in _WRITE_COLUMNS)
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            f"INSERT INTO meta.series ({', '.join(_WRITE_COLUMNS)}, updated_at) "
            f"VALUES ({placeholders}, current_timestamp)",
            _values(validated),
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    return RegistrationResult(
        series_id=validated.series_id,
        inserted=True,
        unchanged=False,
        content_sha256=validated.content_sha256,
    )


__all__ = [
    "DRAFT_CONFIDENCE",
    "DRAFT_SEMANTIC_SOURCE",
    "DRAFT_STATUS",
    "RegistrationConflict",
    "RegistrationError",
    "RegistrationResult",
    "register_series",
]
