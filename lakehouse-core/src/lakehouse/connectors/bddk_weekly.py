"""BDDK Weekly Bulletin connector: retrieve exact bytes, persist them, parse nothing.

The weekly bulletin application exposes a small time-series JSON endpoint used by the chart
modal of its advanced-report screen. Verified live on 2026-09-09 against
``https://www.bddk.org.tr``:

- ``POST /BultenHaftalik/tr/Gelismis/KiyaslamaJsonGetir`` returns one weekly series as two
  parallel arrays in a single call.
- **No authentication, no session cookie and no antiforgery token are required.** This was
  proven by issuing the request from a cookie-less client that had never loaded any page and
  receiving a byte-identical successful response.
- Form fields: ``dil``, ``baslangicTarihi``, ``bitisTarihi``, ``id``, ``parabirimi``,
  ``sutun``, ``tarafKodu``.

The weekly contract is **not** the monthly contract, and the differences are deliberate here
rather than copied:

- Dates use ``d.MM.yyyy HH:mm:ss`` with a **non-padded day** (``2.01.2026 00:00:00``), while the
  monthly endpoint takes separate year/month integers.
- The currency field is ``parabirimi`` and its verified value is ``TRY``; the monthly endpoint
  uses ``paraBirimi`` with ``TL``. The weekly report form uses yet another spelling
  (``SeciliParalar=TL``).
- The column selector is a **numeric** ``sutun`` (``3`` observed for "Toplam"), while the
  monthly endpoint encodes it inside ``kalemSutun`` as ``<item id>?Toplam``.
- ``id`` is a **positional chart address** (``1.0.4``), not the stable item id. The stable
  native item id is the ``Kalem-<id>`` value from the item tree (``5690`` for
  Krediler → Tüketici Kredileri → a) Konut).
- Because ``id`` is positional, the caller must also state ``expected_measure_label``,
  ``expected_currency`` and ``expected_column``. They never go on the wire; the parser
  compares them with the title the response came back with and refuses a mismatch.

``kalem_id`` is therefore a **mandatory** ``FetchSpec`` parameter even though it is **never
sent on the wire**. It is the only stable identity of the concept: ``id=1.0.4`` is positional
and can address a different bulletin line after a layout change, so a series must not be
identified by it. The connector records ``kalem_id`` in artifact metadata as the verified
source identity, and refuses a request that does not carry exactly one.

The endpoint accepts exactly one ``id`` because the application's own ``VeriGetir`` sends a
single ``id`` per call; no multi-item behaviour was observed or assumed. This is **not** the
monthly "one ``kalemSutun`` per FetchSpec" rule carried over, it is the weekly endpoint's own
shape.

The advanced report at ``POST /BultenHaftalik/tr/Gelismis/GelismisRaporGetir`` returns the same
numbers inside a ~490 KB HTML page and needs an antiforgery token plus a session cookie. It is
the documented fallback transport and is recorded in metadata, not implemented here. See
``docs/sources/bddk_weekly.md``.

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
from datetime import date, datetime, timezone
from typing import Any

import requests

from ..contracts.models import FetchedAsset, FetchSpec
from ..errors import ErrorPayload, LakehouseError
from ..storage.raw import RawStorage
from .base import BaseConnector


BDDK_WEEKLY_BASE_URL = "https://www.bddk.org.tr"
"""Verified host for the BDDK weekly bulletin application."""

BDDK_WEEKLY_SERIES_PATH = "/BultenHaftalik/tr/Gelismis/KiyaslamaJsonGetir"
"""Verified time-series endpoint returning one weekly series as parallel arrays."""

BDDK_WEEKLY_REPORT_PATH = "/BultenHaftalik/tr/Gelismis/GelismisRaporGetir"
"""HTML advanced report; documented fallback transport, recorded in metadata only."""

BDDK_WEEKLY_DATE_FORMAT = "{day}.{month:02d}.{year} 00:00:00"
"""Verified request date format: non-padded day, zero-padded month, midnight suffix."""


def _utc_now() -> datetime:
    """Default wall clock for the moment a response was actually downloaded."""

    return datetime.now(timezone.utc)


def format_weekly_date(value: date) -> str:
    """Format a date the way the weekly endpoint expects it (``2.01.2026 00:00:00``)."""

    return BDDK_WEEKLY_DATE_FORMAT.format(day=value.day, month=value.month, year=value.year)


_REQUIRED_WIRE_PARAMETERS = ("id", "parabirimi", "sutun", "tarafKodu")
"""Fields the endpoint itself takes. Each is single-valued."""

_REQUIRED_IDENTITY_PARAMETERS = (
    "kalem_id",
    "expected_measure_label",
    "expected_currency",
    "expected_column",
)
"""Verified source identity: required, validated, and deliberately never sent on the wire.

``id`` is a **positional** chart address. If BDDK reorders the bulletin, the same ``id`` can
start returning a different line, and nothing in the HTTP exchange would say so. These fields
carry what the caller believes the series is, so the parser can compare them against the
title the response actually came back with and refuse a silent swap. They are mandatory in
this narrow V1 connector: a request that cannot state what it expects cannot be checked, and
an unchecked positional address is exactly the failure being guarded against.
"""

_RETRYABLE_STATUS = frozenset({408, 429})


class BddkWeeklyConnector(BaseConnector):
    """Fetch one BDDK weekly series and store its exact response bytes.

    The connector applies no parsing and no financial transformation. It records the request
    fields and the documented HTML fallback path in the artifact metadata so a downstream
    parser can reason about the request without re-deriving it.
    """

    def __init__(
        self,
        storage: RawStorage,
        *,
        base_url: str = BDDK_WEEKLY_BASE_URL,
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
        """Retrieve one weekly series and persist it through the shared RAW storage."""

        form = self._build_form(spec)
        url = f"{self._base_url}{BDDK_WEEKLY_SERIES_PATH}"

        response = self._request_with_retry(spec, url, form)
        # ``requested_at`` is when the caller built the request; ``fetched_at`` is when the
        # successful response actually arrived. They are different concepts.
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
        """Build the verified ordered form pairs. Every field is single-valued."""

        if spec.start_date is None or spec.end_date is None:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                "BDDK weekly FetchSpec requires both start_date and end_date",
                retryable=False,
            )
        if spec.start_date > spec.end_date:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                "BDDK weekly FetchSpec start_date must not be after end_date",
                retryable=False,
            )

        parameters = dict(spec.parameters)
        form: list[tuple[str, str]] = [
            ("dil", str(parameters.get("dil", "tr")).strip() or "tr"),
            ("baslangicTarihi", format_weekly_date(spec.start_date)),
            ("bitisTarihi", format_weekly_date(spec.end_date)),
        ]
        for name in _REQUIRED_WIRE_PARAMETERS:
            form.append((name, self._single_value(spec, parameters, name)))

        # Validated for identity only. Deliberately absent from ``form``: the endpoint has no
        # such field, and sending an unknown field is not something the source was observed
        # to accept.
        for name in _REQUIRED_IDENTITY_PARAMETERS:
            self._single_value(spec, parameters, name)
        return form

    def _single_value(
        self, spec: FetchSpec, parameters: dict[str, Any], name: str
    ) -> str:
        """Require exactly one non-empty value for a field the endpoint takes once.

        The weekly endpoint's own client sends each of these fields exactly once. Nothing was
        observed about repeated values, so a repeated value is refused locally instead of being
        guessed at against the live source.
        """

        raw = parameters.get(name)
        values = (
            [str(item).strip() for item in raw if str(item).strip()]
            if isinstance(raw, (list, tuple))
            else ([str(raw).strip()] if raw is not None and str(raw).strip() else [])
        )
        if not values:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                f"BDDK weekly FetchSpec requires a non-empty '{name}' parameter",
                retryable=False,
            )
        if len(values) > 1:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                (
                    f"BDDK weekly FetchSpec accepts exactly one '{name}' value but "
                    f"{len(values)} were given ({', '.join(values)}); the weekly endpoint "
                    "takes this field once. Issue one FetchSpec per value."
                ),
                retryable=False,
            )
        return values[0]

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
                        "BDDK weekly TLS certificate verification failed. Retrying with the "
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
                    f"BDDK weekly request timed out after {spec.timeout} seconds",
                    retryable=True,
                )
                last_error.__cause__ = exc
            except requests.RequestException as exc:
                last_error = self._error(
                    spec,
                    "SOURCE_UNAVAILABLE",
                    "BDDK weekly request failed before a response was received",
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
                    f"BDDK weekly endpoint responded with HTTP {response.status_code}",
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
        """Record request facts only; the response body is never inspected here.

        ``requested_kalem_id`` is the stable native item id from the weekly item tree. It is
        not a wire field — the endpoint addresses the series by the positional ``id`` — but it
        is the **only** identifier a parser may build a ``series_id`` from, so it is carried
        here rather than being re-derived from a Turkish label or from the positional id.
        """

        fields = dict(form)
        # Guaranteed present, single and non-empty by ``_build_form``.
        parameters = dict(spec.parameters)
        identity = {
            name: self._single_value(spec, parameters, name)
            for name in _REQUIRED_IDENTITY_PARAMETERS
        }
        kalem_id = identity["kalem_id"]
        return {
            "request_form": [list(pair) for pair in form],
            "requested_start_date": fields.get("baslangicTarihi"),
            "requested_end_date": fields.get("bitisTarihi"),
            "requested_chart_id": fields.get("id"),
            "requested_kalem_id": kalem_id,
            "expected_measure_label": identity["expected_measure_label"],
            "expected_currency": identity["expected_currency"],
            "expected_column": identity["expected_column"],
            "requested_currency": fields.get("parabirimi"),
            "requested_column": fields.get("sutun"),
            "requested_taraf": fields.get("tarafKodu"),
            "api_base_url": self._base_url,
            "html_report_fallback_path": BDDK_WEEKLY_REPORT_PATH,
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
    "BDDK_WEEKLY_BASE_URL",
    "BDDK_WEEKLY_DATE_FORMAT",
    "BDDK_WEEKLY_REPORT_PATH",
    "BDDK_WEEKLY_SERIES_PATH",
    "BddkWeeklyConnector",
    "format_weekly_date",
]
