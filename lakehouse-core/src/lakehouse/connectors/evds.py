"""EVDS (TCMB) source connector: retrieve exact bytes, persist them, parse nothing.

Endpoint contract is taken from the official *EVDS Web Servis Kılavuzu* published by TCMB at
``https://evds3.tcmb.gov.tr/igmevdsms-dis/documents/showDocument?docId=8``:

- Base URL ``https://evds3.tcmb.gov.tr/igmevdsms-dis``. The legacy ``evds2`` service path
  redirects here, so ``evds2`` URLs must not be used.
- The API key travels in the ``key`` HTTP request header. Requests without it are rejected
  with HTTP 403.
- Request dates use ``dd-mm-yyyy``.
- A single request returns at most 1000 observations, counted backwards from ``endDate``.
  Larger ranges are silently truncated, so the caller must window its requests.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote

import requests

from ..contracts.models import FetchedAsset, FetchSpec
from ..errors import ErrorPayload, LakehouseError
from ..storage.raw import RawStorage
from .base import BaseConnector


EVDS_BASE_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis"
"""Documented EVDS3 web service base URL."""

EVDS_API_KEY_ENV = "EVDS_API_KEY"
"""Default environment variable holding the API key. The value is never stored or logged."""

EVDS_OBSERVATION_LIMIT = 1000
"""Documented maximum number of observations returned by one request."""

EVDS_DATE_FORMAT = "%d-%m-%Y"
"""Documented request date format."""


def _utc_now() -> datetime:
    """Default wall clock for the moment a response was actually downloaded."""

    return datetime.now(timezone.utc)


_RETRYABLE_STATUS = frozenset({408, 429})
_PASSTHROUGH_PARAMETERS = (
    "type",
    "frequency",
    "aggregationTypes",
    "formulas",
    "decimalSeperator",
)


def _format_date(value: date) -> str:
    return value.strftime(EVDS_DATE_FORMAT)


class EvdsConnector(BaseConnector):
    """Fetch one EVDS request and store its exact response bytes as a RAW artifact.

    The connector performs no parsing, unit handling, frequency conversion, or any other
    financial transformation. It records the request parameters it used in the artifact
    metadata so that a downstream parser can detect a silently truncated response.
    """

    def __init__(
        self,
        storage: RawStorage,
        *,
        base_url: str = EVDS_BASE_URL,
        session: requests.Session | None = None,
        api_key_env: str = EVDS_API_KEY_ENV,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")

        self._storage = storage
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._api_key_env = api_key_env
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._clock = clock

    # ----------------------------------------------------------------- public

    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        """Retrieve one EVDS response and persist it through the shared RAW storage."""

        series = self._series_parameter(spec)
        url = self._build_url(spec, series)
        api_key = self._read_api_key(spec)

        response = self._request_with_retry(spec, url, api_key)
        # ``requested_at`` is when the caller built the request; ``fetched_at`` is when
        # the successful response actually arrived. They are different concepts.
        fetched_at = self._downloaded_at(spec)
        asset = self._storage.store(
            source_id=spec.source_id,
            dataset_id=spec.dataset_id,
            locator=url,
            content=response.content,
            media_type=self._media_type(response),
            fetched_at=fetched_at,
            extension=self._extension(spec),
            http_status=response.status_code,
            metadata=self._request_metadata(spec, series),
        )
        return [asset]


    def _downloaded_at(self, spec: FetchSpec) -> datetime:
        """Return the UTC moment the successful response was received."""

        moment = self._clock()
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise self._error(
                spec,
                "SOURCE_UNAVAILABLE",
                "connector clock must return a timezone-aware datetime",
                retryable=False,
            )
        return moment.astimezone(timezone.utc)

    # ---------------------------------------------------------------- request

    def _series_parameter(self, spec: FetchSpec) -> str:
        """Read the ``series`` request parameter without inventing a default series code."""

        raw = spec.parameters.get("series")
        if isinstance(raw, (list, tuple)):
            codes = [str(code).strip() for code in raw if str(code).strip()]
        elif isinstance(raw, str):
            codes = [code.strip() for code in raw.split("-") if code.strip()]
        else:
            codes = []

        if not codes:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                "EVDS FetchSpec requires a non-empty 'series' parameter",
                retryable=False,
            )
        return "-".join(codes)

    def _build_url(self, spec: FetchSpec, series: str) -> str:
        """Compose the documented ``series=...&startDate=...&endDate=...`` request URL."""

        if spec.start_date is None or spec.end_date is None:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                "EVDS FetchSpec requires both start_date and end_date",
                retryable=False,
            )
        if spec.start_date > spec.end_date:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                "EVDS FetchSpec start_date must not be after end_date",
                retryable=False,
            )

        parts = [
            f"series={quote(series, safe='.-_')}",
            f"startDate={_format_date(spec.start_date)}",
            f"endDate={_format_date(spec.end_date)}",
        ]
        parameters = dict(spec.parameters)
        parameters.setdefault("type", "json")
        for name in _PASSTHROUGH_PARAMETERS:
            value = parameters.get(name)
            if value is not None and str(value).strip():
                parts.append(f"{name}={quote(str(value), safe='.-_')}")

        base = f"{self._base_url}/{parts[0]}"
        return "&".join([base, *parts[1:]])

    def _read_api_key(self, spec: FetchSpec) -> str:
        """Read the API key from the environment. The value never enters an error message."""

        variable = spec.headers_ref or self._api_key_env
        api_key = os.environ.get(variable, "").strip()
        if not api_key:
            raise self._error(
                spec,
                "SOURCE_UNAVAILABLE",
                (
                    f"EVDS API key is not available; set the {variable} environment variable. "
                    "The key is never read from code, fixtures, or committed files."
                ),
                retryable=False,
            )
        return api_key

    def _request_with_retry(
        self, spec: FetchSpec, url: str, api_key: str
    ) -> requests.Response:
        """Issue the request, retrying only timeouts, connection errors, 408, 429, and 5xx."""

        last_error: LakehouseError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._session.get(
                    url,
                    headers={"key": api_key, "Accept": "application/json"},
                    timeout=spec.timeout,
                )
            except requests.Timeout as exc:
                last_error = self._error(
                    spec,
                    "FETCH_TIMEOUT",
                    f"EVDS request timed out after {spec.timeout} seconds",
                    retryable=True,
                )
                last_error.__cause__ = exc
            except requests.RequestException as exc:
                last_error = self._error(
                    spec,
                    "SOURCE_UNAVAILABLE",
                    "EVDS request failed before a response was received",
                    retryable=True,
                )
                last_error.__cause__ = exc
            else:
                if 200 <= response.status_code < 300:
                    return response

                retryable = (
                    response.status_code in _RETRYABLE_STATUS or response.status_code >= 500
                )
                last_error = self._error(
                    spec,
                    "HTTP_ERROR",
                    f"EVDS responded with HTTP {response.status_code}",
                    retryable=retryable,
                )
                if not retryable:
                    raise last_error

            if attempt < self._max_attempts:
                self._sleep(self._backoff_seconds * (2 ** (attempt - 1)))

        assert last_error is not None  # loop always assigns before exhausting attempts
        raise last_error

    # --------------------------------------------------------------- metadata

    def _request_metadata(self, spec: FetchSpec, series: str) -> dict[str, Any]:
        """Record request facts only; the response body is never inspected here."""

        parameters = dict(spec.parameters)
        return {
            "requested_series": series.split("-"),
            "requested_start_date": _format_date(spec.start_date) if spec.start_date else None,
            "requested_end_date": _format_date(spec.end_date) if spec.end_date else None,
            "requested_frequency": parameters.get("frequency"),
            "requested_aggregation_types": parameters.get("aggregationTypes"),
            "requested_formulas": parameters.get("formulas"),
            "requested_decimal_separator": parameters.get("decimalSeperator"),
            "observation_limit": EVDS_OBSERVATION_LIMIT,
            "api_base_url": self._base_url,
        }

    @staticmethod
    def _media_type(response: requests.Response) -> str:
        header = response.headers.get("Content-Type", "").split(";")[0].strip()
        return header or "application/json"

    @staticmethod
    def _extension(spec: FetchSpec) -> str:
        requested = str(spec.parameters.get("type", "json")).strip().lower()
        return requested if requested in {"json", "csv", "xml"} else "json"

    @staticmethod
    def _error(
        spec: FetchSpec, error_code: str, message: str, *, retryable: bool
    ) -> LakehouseError:
        return LakehouseError(
            ErrorPayload(
                error_code=error_code,
                message=message,
                source_id=spec.source_id,
                dataset_id=spec.dataset_id,
                retryable=retryable,
            )
        )


__all__ = [
    "EVDS_API_KEY_ENV",
    "EVDS_BASE_URL",
    "EVDS_DATE_FORMAT",
    "EVDS_OBSERVATION_LIMIT",
    "EvdsConnector",
]
