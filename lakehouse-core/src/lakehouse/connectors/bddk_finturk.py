"""BDDK FinTürk (İllere Göre) connector: retrieve exact bytes, persist them, parse nothing.

The FinTürk province-level application exposes a JSON endpoint its own report screen uses.
Verified live on 2026-09-10 against ``https://www.bddk.org.tr``:

- ``POST /BultenFinturk/tr/Home/VeriGetir`` returns one province/period/table combination as a
  single-row grid in one call, or all provinces when ``sehirList[0]=HEPSİ``. Observed tables
  (``tabloNo``): ``1`` = Krediler (aggregate
  cash/non-cash totals, no product breakdown), ``3`` = Bireysel Bankacılık (retail lending,
  includes a ``Konut Kredisi`` column — **this is the table this connector requests**), ``4`` =
  Seçilmiş Sektörel Krediler (borrower's industry sector, e.g. İnşaat/Turizm/Ziraat — this is
  sector-of-economy, not loan product, and does **not** contain a housing column). Other
  ``tabloNo`` values (Mevduat, Oranlar, Şubeler/Nüfusa Göre Dağılım, Altın Kredileri) were not
  exercised; see "Confirmation required" in ``docs/sources/bddk_finturk.md``.
- Form fields: ``tabloNo``, ``donem`` (``YYYY-M``, month **not** zero-padded, e.g. ``2025-9``,
  and a single period — the endpoint has no start/end range), ``tarafList[0]`` (party code, same
  ``10001`` = Sektör convention as the weekly/monthly endpoints), ``sehirList[0]`` (province name,
  upper-case Turkish, e.g. ``"YALOVA"``, ``"ANKARA"``, ``"AĞRI"``).
- **Unlike the weekly and monthly endpoints, this request was observed carrying an
  ``ASP.NET_SessionId`` cookie and an ``__RequestVerificationToken_...`` cookie.** Whether the
  endpoint actually validates either against the request (as opposed to merely accepting an
  anonymous session) has **not** been tested — no cookie-less/token-less request was attempted
  live, unlike the weekly endpoint's explicit proof of "no auth required". This connector
  therefore conservatively performs one ``GET`` of the FinTürk report page first, to acquire
  whatever session cookie(s) the server sets, and reuses that session's cookie jar for the
  ``POST``. This is a safe default, not a confirmed requirement; see "Confirmation required" in
  ``docs/sources/bddk_finturk.md``.
- The endpoint takes exactly **one period per call** (unlike the weekly/monthly endpoints, which
  take a date range). **Verified live: only quarter-end months (March/June/September/December)
  return data (HTTP 200); every other month returns HTTP 500** — an unhandled server-side error,
  not an empty/graceful response — for every year tested, 2021-2026. FinTürk publishes this data
  quarterly; the ``donem`` field's month-level syntax does not imply month-level data exists.
  This connector therefore windows a ``FetchSpec``'s ``start_date``..``end_date`` range into one
  request per quarter, and returns one ``FetchedAsset`` per quarter — the shared
  ``BaseConnector.fetch() -> list[FetchedAsset]`` contract already supports this.

TLS: ``www.bddk.org.tr`` serves only its leaf certificate and omits the
``GlobalSign RSA OV SSL CA 2018`` intermediate, so a correctly-configured client fails
verification. This connector never weakens TLS. It accepts an injected ``requests.Session``, so a
deployment can pass one whose ``verify`` points at a CA bundle containing that intermediate
**with verification still on**. A verification failure is reported as ``SOURCE_UNAVAILABLE`` with
``retryable=False``.
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


BDDK_FINTURK_BASE_URL = "https://www.bddk.org.tr"
"""Verified host for the BDDK FinTürk application."""

BDDK_FINTURK_PAGE_PATH = "/BultenFinTurk"
"""Report page; GET once per connector to acquire a session cookie before posting."""

BDDK_FINTURK_DATA_PATH = "/BultenFinturk/tr/Home/VeriGetir"
"""Verified data endpoint returning one province/period/table combination."""

BDDK_FINTURK_TABLO_BIREYSEL = "3"
"""Verified table number for Bireysel Bankacılık, the only table observed to carry a
``Konut Kredisi`` (housing loan) column."""

_RETRYABLE_STATUS = frozenset({408, 429})
_REQUIRED_PARAMETERS = ("sehir",)


def _utc_now() -> datetime:
    """Default wall clock for the moment a response was actually downloaded."""

    return datetime.now(timezone.utc)


_QUARTER_END_MONTHS = (3, 6, 9, 12)
"""Verified live 2026-09-10: requesting any non-quarter-end month returns HTTP 500 (an
unhandled server-side error, not an empty/graceful response) for every year 2021-2026 tested.
FinTürk publishes this data quarterly; the ``donem`` field's month-level granularity does not
mean month-level data exists. See docs/sources/bddk_finturk.md, "Source anomalies"."""


def _periods_in_range(start: date, end: date) -> list[tuple[int, int]]:
    """Return every (year, quarter-end month) pair from ``start`` to ``end`` inclusive.

    The FinTürk endpoint takes exactly one period per request; this is the windowing the
    connector needs to cover a FetchSpec's start_date..end_date range. Only quarter-end months
    are requested — see _QUARTER_END_MONTHS.
    """

    periods: list[tuple[int, int]] = []
    for year in range(start.year, end.year + 1):
        for month in _QUARTER_END_MONTHS:
            period = (year, month)
            if (start.year, start.month) <= period <= (end.year, end.month):
                periods.append(period)
    return periods


class BddkFinTurkConnector(BaseConnector):
    """Fetch BDDK FinTürk province-level reports and store their exact response bytes.

    The connector applies no parsing and no financial transformation. One FetchSpec yields one
    FetchedAsset per quarter in that range, because the source endpoint itself has no range
    concept and only publishes quarterly data. ``sehir=HEPSİ`` is supported for the source's
    all-province response mode; the parser then emits one row per returned province.
    """

    def __init__(
        self,
        storage: RawStorage,
        *,
        base_url: str = BDDK_FINTURK_BASE_URL,
        session: requests.Session | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        request_interval_seconds: float = 0.3,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds must not be negative")

        self._storage = storage
        self._base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._request_interval_seconds = request_interval_seconds
        self._sleep = sleep
        self._clock = clock
        self._session_primed = False

    # ----------------------------------------------------------------- public

    def fetch(self, spec: FetchSpec) -> list[FetchedAsset]:
        """Retrieve one FinTürk report per quarter in the spec's range."""

        if spec.start_date is None or spec.end_date is None:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                "BDDK FinTürk FetchSpec requires both start_date and end_date",
                retryable=False,
            )
        if spec.start_date > spec.end_date:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                "BDDK FinTürk FetchSpec start_date must not be after end_date",
                retryable=False,
            )

        parameters = dict(spec.parameters)
        sehir = self._required(spec, parameters, "sehir")
        taraf = str(parameters.get("tarafKodu", "10001")).strip() or "10001"
        tablo_no = str(parameters.get("tabloNo", BDDK_FINTURK_TABLO_BIREYSEL)).strip()

        self._ensure_session(spec)
        url = f"{self._base_url}{BDDK_FINTURK_DATA_PATH}"

        assets: list[FetchedAsset] = []
        periods = _periods_in_range(spec.start_date, spec.end_date)
        for position, (year, month) in enumerate(periods):
            if position > 0 and self._request_interval_seconds > 0:
                # One (sehir, tabloNo) request covers one quarter; a multi-year range means
                # many sequential requests. Pace successive requests defensively rather than
                # assuming BDDK tolerates a tight loop just because no rate limit was observed
                # at much lower volume elsewhere.
                self._sleep(self._request_interval_seconds)
            donem = f"{year}-{month}"
            form: list[tuple[str, str]] = [
                ("tabloNo", tablo_no),
                ("donem", donem),
                ("tarafList[0]", taraf),
                ("sehirList[0]", sehir),
            ]
            response = self._request_with_retry(spec, url, form)
            fetched_at = self._downloaded_at(spec)
            assets.append(
                self._storage.store(
                    source_id=spec.source_id,
                    dataset_id=spec.dataset_id,
                    locator=url,
                    content=response.content,
                    media_type=self._media_type(response),
                    fetched_at=fetched_at,
                    extension="json",
                    http_status=response.status_code,
                    metadata=self._request_metadata(spec, form, sehir, donem, tablo_no),
                )
            )
        return assets

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

    def _ensure_session(self, spec: FetchSpec) -> None:
        """GET the report page once so the shared session carries whatever cookies BDDK sets.

        Not confirmed to be required by the endpoint (see module docstring); done anyway
        because it is the only observed-safe way to replicate what a real browser sends, and
        costs one extra request per connector instance rather than per fetch.
        """

        if self._session_primed:
            return
        try:
            self._session.get(
                f"{self._base_url}{BDDK_FINTURK_PAGE_PATH}", timeout=spec.timeout
            )
        except requests.exceptions.SSLError as exc:
            raise self._error(
                spec,
                "SOURCE_UNAVAILABLE",
                (
                    "BDDK FinTürk TLS certificate verification failed while priming the "
                    "session. Verify the server certificate chain and supply a "
                    "requests.Session with an appropriate CA bundle, with verification left "
                    "ON. Never disable verification."
                ),
                retryable=False,
            ) from exc
        except requests.RequestException as exc:
            raise self._error(
                spec,
                "SOURCE_UNAVAILABLE",
                "BDDK FinTürk session priming request failed before a response was received",
                retryable=True,
            ) from exc
        self._session_primed = True

    def _required(self, spec: FetchSpec, parameters: dict[str, Any], name: str) -> str:
        value = parameters.get(name)
        text = str(value).strip() if value is not None else ""
        if not text:
            raise self._error(
                spec,
                "UNSUPPORTED_FORMAT",
                f"BDDK FinTürk FetchSpec requires a non-empty '{name}' parameter",
                retryable=False,
            )
        return text

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
                raise self._error(
                    spec,
                    "SOURCE_UNAVAILABLE",
                    (
                        "BDDK FinTürk TLS certificate verification failed. Retrying with the "
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
                    f"BDDK FinTürk request timed out after {spec.timeout} seconds",
                    retryable=True,
                )
                last_error.__cause__ = exc
            except requests.RequestException as exc:
                last_error = self._error(
                    spec,
                    "SOURCE_UNAVAILABLE",
                    "BDDK FinTürk request failed before a response was received",
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
                    f"BDDK FinTürk endpoint responded with HTTP {response.status_code}",
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
        self,
        spec: FetchSpec,
        form: list[tuple[str, str]],
        sehir: str,
        donem: str,
        tablo_no: str,
    ) -> dict[str, Any]:
        """Record request facts only; the response body is never inspected here."""

        return {
            "request_form": [list(pair) for pair in form],
            "requested_sehir": sehir,
            "requested_donem": donem,
            "requested_tablo_no": tablo_no,
            "requested_taraf": next((v for k, v in form if k == "tarafList[0]"), None),
            "api_base_url": self._base_url,
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
    "BDDK_FINTURK_BASE_URL",
    "BDDK_FINTURK_DATA_PATH",
    "BDDK_FINTURK_PAGE_PATH",
    "BDDK_FINTURK_TABLO_BIREYSEL",
    "BddkFinTurkConnector",
]
