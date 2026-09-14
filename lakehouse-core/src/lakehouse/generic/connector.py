"""A connector for data nobody wrote a connector for.

The source-specific connectors in this package each encode one endpoint's quirks. This one
encodes none: it takes a local path or an http(s) URL, proves it is allowed to read it, and
stores the exact bytes. It only inspects format signals. Everything about what the bytes *mean*
belongs to :mod:`lakehouse.generic.parser` and, beyond that, to an explicit mapping.

``source_id`` is fixed to ``adhoc`` in this version. A single reserved namespace makes the
provenance question structural rather than conventional: a ``series_id`` beginning ``adhoc:``
came from a file somebody handed us during a session, and ``adhoc.fact_observation`` is the
only fact table it can reach. Allowing an arbitrary ``source_id`` here would let user-supplied
data borrow the identity of a reviewed source, which is exactly the confusion the namespace
exists to prevent.
"""

from __future__ import annotations

import time
import math
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import requests

from ..connectors.base import BaseConnector
from ..contracts.models import FetchedAsset, FetchSpec
from ..errors import ErrorPayload, LakehouseError
from ..storage.raw import RawStorage
from ._access import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_REDIRECTS,
    AccessDeniedError,
    LocalFilePolicy,
    assert_url_is_allowed,
    read_local_file,
)
from .formats import MEDIA_TYPES, FormatError, resolve_format
from .config import canonical_parser_config, parser_config_hash


ADHOC_SOURCE_ID: Final[str] = "adhoc"
"""The only source id this connector writes under."""

_RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({408, 429})
_CHUNK_BYTES: Final[int] = 64 * 1024


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _error(
    spec: FetchSpec, code: str, message: str, *, retryable: bool
) -> LakehouseError:
    return LakehouseError(
        ErrorPayload(
            error_code=code,
            message=message,
            source_id=spec.source_id,
            dataset_id=spec.dataset_id,
            retryable=retryable,
        )
    )


def _safe_locator(url: str) -> str:
    """Strip the query string and any credentials before the locator is stored.

    A query string on an ad-hoc URL is where an API key or a signed-URL token lives. The
    locator is written to ``meta.artifact`` and appears in error messages, so the query is
    dropped wholesale rather than filtered key by key: an allow-list of "safe" parameter names
    would be wrong the first time a source invents a new one.
    """

    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    suffix = "?<redacted>" if parts.query else ""
    return f"{parts.scheme}://{host}{parts.path}{suffix}"


class GenericTabularConnector(BaseConnector):
    """Fetch arbitrary tabular bytes from a local file or an http(s) URL.

    Parameters that matter:

    ``allowed_local_roots``
        Explicit list of directories local reads may come from. There is no default and no
        implicit "current directory": a connector constructed without roots cannot read a
        local file at all.
    ``max_bytes``
        Hard ceiling, enforced on local reads and on streamed responses. A response is
        abandoned mid-stream when it goes over, so an unbounded body never reaches memory.
    ``clock``
        Validated at construction, then read **after** the bytes arrive, so ``fetched_at`` is when the
        data was actually in hand rather than when the request was built.
    """

    def __init__(
        self,
        storage: RawStorage,
        *,
        allowed_local_roots: list[str | Path] | None = None,
        session: requests.Session | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if not math.isfinite(backoff_seconds) or backoff_seconds < 0:
            raise ValueError("backoff_seconds must be finite and non-negative")
        moment = clock()
        if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("connector clock must return a timezone-aware datetime")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if max_redirects < 0:
            raise ValueError("max_redirects must not be negative")
        self._storage = storage
        self._local_policy = (
            LocalFilePolicy(tuple(allowed_local_roots), max_bytes=max_bytes)
            if allowed_local_roots
            else None
        )
        self._session = session or requests.Session()
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._clock = clock

    # ----------------------------------------------------------------- public

    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        """Read one local file or URL and persist its exact bytes as a RAW artifact."""

        if spec.source_id != ADHOC_SOURCE_ID:
            raise _error(
                spec,
                "UNSUPPORTED_FORMAT",
                f"the generic connector only writes under source_id {ADHOC_SOURCE_ID!r}, "
                f"got {spec.source_id!r}",
                retryable=False,
            )

        locator = spec.locator.strip()
        explicit_format = spec.parameters.get("format")
        if explicit_format is not None and not isinstance(explicit_format, str):
            raise _error(
                spec, "UNSUPPORTED_FORMAT", "'format' must be a string", retryable=False
            )

        if locator.lower().startswith(("http://", "https://")):
            content, content_type, status, safe_locator, name = self._fetch_url(spec, locator)
        else:
            content, content_type, status, safe_locator, name = self._read_local(spec, locator)

        if not content:
            raise _error(
                spec, "EMPTY_DATASET", "the source returned zero bytes", retryable=False
            )

        try:
            resolved = resolve_format(
                content=content,
                locator_name=name,
                content_type=content_type,
                explicit_format=explicit_format,
            )
            parser_config = canonical_parser_config(resolved, spec.parameters)
        except FormatError as exc:
            raise _error(spec, "UNSUPPORTED_FORMAT", str(exc), retryable=False) from exc

        fetched_at = self._downloaded_at(spec)
        asset = self._storage.store(
            source_id=spec.source_id,
            dataset_id=spec.dataset_id,
            locator=safe_locator,
            content=content,
            media_type=MEDIA_TYPES[resolved],
            fetched_at=fetched_at,
            extension=resolved,
            http_status=status,
            metadata={
                **self._metadata(spec, resolved, content_type, len(content)),
                "parser_config": parser_config,
                "parser_config_sha256": parser_config_hash(parser_config),
            },
        )
        return [asset]

    # ------------------------------------------------------------ local files

    def _read_local(
        self, spec: FetchSpec, locator: str
    ) -> tuple[bytes, str | None, int | None, str, str]:
        if self._local_policy is None:
            raise _error(
                spec,
                "ACCESS_DENIED",
                "this connector was built without allowed_local_roots, so it cannot read "
                "local files",
                retryable=False,
            )
        try:
            resolved, content = read_local_file(locator, self._local_policy)
        except AccessDeniedError as exc:
            raise _error(spec, "ACCESS_DENIED", str(exc), retryable=False) from exc
        except OSError as exc:
            raise _error(
                spec, "SOURCE_UNAVAILABLE", "local file could not be read", retryable=False
            ) from exc
        return content, None, None, f"file://{resolved}", resolved.name

    # ------------------------------------------------------------------- URLs

    def _fetch_url(
        self, spec: FetchSpec, url: str
    ) -> tuple[bytes, str | None, int | None, str, str]:
        last_error: LakehouseError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return self._request_once(spec, url)
            except LakehouseError as exc:
                if not exc.payload.retryable:
                    raise
                last_error = exc
            if attempt < self._max_attempts:
                self._sleep(self._backoff_seconds * (2 ** (attempt - 1)))
        assert last_error is not None
        raise last_error

    def _request_once(
        self, spec: FetchSpec, url: str
    ) -> tuple[bytes, str | None, int | None, str, str]:
        current = url
        for hop in range(self._max_redirects + 1):
            try:
                assert_url_is_allowed(current)
            except AccessDeniedError as exc:
                raise _error(spec, "ACCESS_DENIED", str(exc), retryable=False) from exc

            try:
                response = self._session.get(
                    current,
                    timeout=spec.timeout,
                    stream=True,
                    allow_redirects=False,
                )
            except requests.Timeout as exc:
                raise _error(
                    spec,
                    "FETCH_TIMEOUT",
                    f"request timed out after {spec.timeout} seconds",
                    retryable=True,
                ) from exc
            except requests.RequestException as exc:
                raise _error(
                    spec,
                    "SOURCE_UNAVAILABLE",
                    "request failed before a response was received",
                    retryable=True,
                ) from exc

            try:
                status = response.status_code
                if status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise _error(
                            spec, "HTTP_ERROR", f"HTTP {status} with no Location", retryable=False
                        )
                    # Every hop is validated from scratch: a public URL redirecting to the cloud
                    # metadata endpoint is the whole reason redirects are followed manually.
                    current = requests.compat.urljoin(current, location)
                    continue

                if not 200 <= status < 300:
                    retryable = status in _RETRYABLE_STATUS or status >= 500
                    # The body is deliberately not read or quoted: an error page can contain the
                    # request, including anything sensitive that was in it.
                    raise _error(
                        spec, "HTTP_ERROR", f"source responded with HTTP {status}", retryable=retryable
                    )

                content = self._read_stream(spec, response)
                content_type = response.headers.get("Content-Type")
                name = Path(urlsplit(current).path).name or "download"
                return content, content_type, status, _safe_locator(current), name
            finally:
                self._close(response)

        raise _error(
            spec,
            "ACCESS_DENIED",
            f"more than {self._max_redirects} redirects; the chain was abandoned",
            retryable=False,
        )

    def _read_stream(self, spec: FetchSpec, response: requests.Response) -> bytes:
        """Accumulate the body in chunks, stopping the moment it goes over the limit."""

        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
                if not chunk:
                    continue
                total += len(chunk)
                if total > self._max_bytes:
                    raise _error(
                        spec,
                        "ACCESS_DENIED",
                        f"response exceeds the {self._max_bytes} byte limit and was abandoned "
                        "mid-stream",
                        retryable=False,
                    )
                chunks.append(chunk)
        except requests.Timeout as exc:
            raise _error(
                spec, "FETCH_TIMEOUT", "the response body timed out", retryable=True
            ) from exc
        except requests.RequestException as exc:
            raise _error(
                spec, "SOURCE_UNAVAILABLE", "the response body could not be read", retryable=True
            ) from exc
        return b"".join(chunks)

    @staticmethod
    def _close(response: requests.Response) -> None:
        try:
            response.close()
        except Exception:  # noqa: BLE001 - closing must never mask the real error
            pass

    # --------------------------------------------------------------- metadata

    def _downloaded_at(self, spec: FetchSpec) -> datetime:
        moment = self._clock()
        if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
            raise _error(
                spec,
                "SOURCE_UNAVAILABLE",
                "connector clock must return a timezone-aware datetime",
                retryable=False,
            )
        return moment.astimezone(timezone.utc)

    def _metadata(
        self,
        spec: FetchSpec,
        resolved_format: str,
        content_type: str | None,
        byte_size: int,
    ) -> dict[str, Any]:
        """Record what the request was, never what was in it.

        ``spec.parameters`` is not copied wholesale: a caller may have put an auth token or a
        signed URL in there, and artifact metadata is long-lived and widely read. Only the
        fields this connector actually acted on are kept.
        """

        return {
            "requested_format": spec.parameters.get("format"),
            "resolved_format": resolved_format,
            "declared_content_type": (content_type or "").split(";")[0].strip() or None,
            "byte_size": byte_size,
            "max_bytes": self._max_bytes,
            "max_redirects": self._max_redirects,
        }


__all__ = ["ADHOC_SOURCE_ID", "GenericTabularConnector"]
