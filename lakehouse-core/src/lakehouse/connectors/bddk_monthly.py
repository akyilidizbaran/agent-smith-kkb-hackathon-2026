"""BDDK Monthly Bulletin connector: retrieve exact bytes, persist them, parse nothing.

The BDDK monthly bulletin application exposes the JSON endpoint its own advanced-report screen
uses. Verified live on 2026-09-08 against ``https://www.bddk.org.tr``:

- ``POST /BultenAylik/tr/Home/GelismisRaporGetir`` returns one full monthly time series for a
  selected item in a single call.
- Form fields: ``baslangicYil``, ``baslangicAy``, ``bitisYil``, ``bitisAy``, ``periyot``,
  ``paraBirimi``, ``taraf`` (repeatable), ``kalemSutun`` (repeatable), ``gosterimTuru``.
- No API key, no antiforgery token and **no session cookie** are required for this endpoint.
- Requesting several ``kalemSutun`` values that describe the same concept across bulletin schema
  versions makes the service answer HTTP 200 with ``{"success": false, ...}``. For V1 this
  connector therefore accepts **exactly one** ``kalemSutun`` per ``FetchSpec``. A concept whose
  historical schema ids differ (``1534,288,219,238`` for Tüketici Kredileri - Konut) must be
  retrieved with one ``FetchSpec`` per id, and the results reconciled by a later layer.
  ``taraf`` stays repeatable because the service accepts several parties in one call.

The official Excel export at ``POST /BultenAylik/tr/Home/GelismisExceleAktar`` takes the same
form fields and is the documented fallback transport if this JSON endpoint changes. It is not
implemented here; see ``docs/sources/bddk_monthly.md``.

TLS: ``www.bddk.org.tr`` serves only its leaf certificate and omits the
``GlobalSign RSA OV SSL CA 2018`` intermediate, so a correctly-configured client fails
verification. This connector never weakens TLS. It accepts an injected
``requests.Session``, so a deployment can pass one whose ``verify`` points at a CA
bundle containing that intermediate **with verification still on**. A verification
failure is reported as ``SOURCE_UNAVAILABLE`` with ``retryable=False``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import requests

from ..contracts.models import FetchedAsset, FetchSpec
from ..errors import ErrorPayload, LakehouseError
from ..storage.raw import RawStorage
from .base import BaseConnector


BDDK_MONTHLY_BASE_URL = "https://www.bddk.org.tr"
"""Verified host for the BDDK monthly bulletin application."""

BDDK_MONTHLY_REPORT_PATH = "/BultenAylik/tr/Home/GelismisRaporGetir"
"""Advanced report endpoint returning a full monthly series for selected items."""

BDDK_MONTHLY_EXCEL_PATH = "/BultenAylik/tr/Home/GelismisExceleAktar"
"""Documented Excel export fallback; recorded in metadata, not used by this connector."""


def _utc_now() -> datetime:
    """Default wall clock for the moment a response was actually downloaded."""

    return datetime.now(timezone.utc)


_REQUIRED_PARAMETERS = ("periyot", "paraBirimi")
_RETRYABLE_STATUS = frozenset({408, 429})


class BddkMonthlyConnector(BaseConnector):
    """Fetch one BDDK monthly advanced report and store its exact response bytes.

    The connector applies no parsing and no financial transformation. It records the request
    fields, the expected number of monthly periods, and the documented Excel fallback path in
    the artifact metadata so a downstream parser can detect a short response.
    """

    def __init__(
        self,
        storage: RawStorage,
        *,
        base_url: str = BDDK_MONTHLY_BASE_URL,
        session: requests.Session | None = None,
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
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._clock = clock

    # ----------------------------------------------------------------- public

    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        """Retrieve one advanced report and persist it through the shared RAW storage."""

        form = self._build_form(spec)
        url = f"{self._base_url}{BDDK_MONTHLY_REPORT_PATH}"

        response = self._request_with_retry(spec, url, form)
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
            extension="json",
            http_status=response.status_code,
            metadata=self._request_metadata(spec, form),
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

    def _build_form(self, spec: FetchSpec) -> list[tuple[str, str]]:
        """Build the ordered form pairs: ``taraf`` may repeat, ``kalemSutun`` may not."""

        if spec.start_date is None or spec.end_date is None:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                "BDDK monthly FetchSpec requires both start_date and end_date",
                retryable=False,
            )
        if spec.start_date > spec.end_date:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                "BDDK monthly FetchSpec start_date must not be after end_date",
                retryable=False,
            )

        parameters = dict(spec.parameters)
        form: list[tuple[str, str]] = [
            ("baslangicYil", str(spec.start_date.year)),
            ("baslangicAy", str(spec.start_date.month)),
            ("bitisYil", str(spec.end_date.year)),
            ("bitisAy", str(spec.end_date.month)),
        ]
        for name in _REQUIRED_PARAMETERS:
            value = parameters.get(name)
            if value is None or not str(value).strip():
                raise self._error(
                    spec,
                    "UNSUPPORTED_FORMAT",
                    f"BDDK monthly FetchSpec requires a non-empty '{name}' parameter",
                    retryable=False,
                )
            form.append((name, str(value).strip()))

        taraf_values = self._as_list(parameters.get("taraf"))
        if not taraf_values:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                "BDDK monthly FetchSpec requires at least one 'taraf' value",
                retryable=False,
            )
        form.extend(("taraf", value) for value in taraf_values)
        form.append(("kalemSutun", self._single_kalem_sutun(spec, parameters)))

        form.append(("gosterimTuru", str(parameters.get("gosterimTuru", "grid"))))
        return form

    def _single_kalem_sutun(self, spec: FetchSpec, parameters: dict[str, Any]) -> str:
        """Accept exactly one item/column selection per request.

        Live verification showed that sending several ``kalemSutun`` values for one concept
        makes BDDK answer HTTP 200 with ``{"success": false, ...}``. Rejecting that here keeps
        the failure typed, local and free of a wasted request, without the connector having to
        inspect any response body.
        """

        values = self._as_list(parameters.get("kalemSutun"))
        if not values:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                "BDDK monthly FetchSpec requires exactly one 'kalemSutun' value",
                retryable=False,
            )
        if len(values) > 1:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                (
                    f"BDDK monthly FetchSpec accepts exactly one 'kalemSutun' value but "
                    f"{len(values)} were given ({', '.join(values)}); BDDK answers HTTP 200 "
                    "with success:false for multi-item requests. Issue one FetchSpec per item."
                ),
                retryable=False,
            )
        return values[0]

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        if value is None:
            return []
        text = str(value).strip()
        return [text] if text else []

    def _request_with_retry(
        self, spec: FetchSpec, url: str, form: list[tuple[str, str]]
    ) -> requests.Response:
        """Retry only timeouts, connection errors, 408, 429 and 5xx responses."""

        last_error: LakehouseError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._session.post(
                    url,
                    data=form,
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json",
                    },
                    timeout=spec.timeout,
                )
            except requests.exceptions.SSLError as exc:
                # Caught before RequestException: an SSL failure is not transient. BDDK's
                # server sends only its leaf certificate and omits the intermediate, so a
                # correctly-configured client fails verification every time. Retrying cannot
                # help, and the fix is deployment trust material, not a connector setting.
                # The message is deliberately free of headers and request bodies.
                raise self._error(
                    spec,
                    "SOURCE_UNAVAILABLE",
                    (
                        "BDDK monthly TLS certificate verification failed. Retrying with the "
                        "same trust configuration will not help. Verify the server certificate "
                        "chain and supply a requests.Session with an appropriate CA bundle, "
                        "with verification left ON. Never disable verification."
                    ),
                    retryable=False,
                ) from exc
            except requests.Timeout as exc:
                last_error = self._error(
                    spec,
                    "FETCH_TIMEOUT",
                    f"BDDK monthly request timed out after {spec.timeout} seconds",
                    retryable=True,
                )
                last_error.__cause__ = exc
            except requests.RequestException as exc:
                last_error = self._error(
                    spec,
                    "SOURCE_UNAVAILABLE",
                    "BDDK monthly request failed before a response was received",
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
                    f"BDDK monthly endpoint responded with HTTP {response.status_code}",
                    retryable=retryable,
                )
                if not retryable:
                    raise last_error

            if attempt < self._max_attempts:
                self._sleep(self._backoff_seconds * (2 ** (attempt - 1)))

        assert last_error is not None  # loop always assigns before exhausting attempts
        raise last_error

    # --------------------------------------------------------------- metadata

    def _request_metadata(
        self, spec: FetchSpec, form: list[tuple[str, str]]
    ) -> dict[str, Any]:
        """Record request facts only; the response body is never inspected here."""

        start, end = spec.start_date, spec.end_date
        assert start is not None and end is not None  # validated in _build_form
        expected_periods = (end.year - start.year) * 12 + (end.month - start.month) + 1
        return {
            "request_form": [list(pair) for pair in form],
            "requested_start_period": f"{start.year}-{start.month:02d}",
            "requested_end_period": f"{end.year}-{end.month:02d}",
            "expected_period_count": expected_periods,
            "requested_kalem_sutun": [v for k, v in form if k == "kalemSutun"],
            "requested_taraf": [v for k, v in form if k == "taraf"],
            "requested_currency": next((v for k, v in form if k == "paraBirimi"), None),
            "api_base_url": self._base_url,
            "excel_fallback_path": BDDK_MONTHLY_EXCEL_PATH,
        }

    @staticmethod
    def _media_type(response: requests.Response) -> str:
        header = response.headers.get("Content-Type", "").split(";")[0].strip()
        return header or "application/json"

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
    "BDDK_MONTHLY_BASE_URL",
    "BDDK_MONTHLY_EXCEL_PATH",
    "BDDK_MONTHLY_REPORT_PATH",
    "BddkMonthlyConnector",
]
