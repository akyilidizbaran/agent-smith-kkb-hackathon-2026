"""BDDK weekly connector tests. No network access: the HTTP session is always a local fake."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from src.lakehouse.connectors.base import BaseConnector
from src.lakehouse.connectors.bddk_weekly import (
    BDDK_WEEKLY_BASE_URL,
    BDDK_WEEKLY_REPORT_PATH,
    BDDK_WEEKLY_SERIES_PATH,
    BddkWeeklyConnector,
    format_weekly_date,
)
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.errors import LakehouseError
from src.lakehouse.storage.raw import RawStorage


FIXTURE = Path("tests/fixtures/raw/bddk_weekly/bddk_weekly_housing_loans.json")
CONNECTOR_SOURCE = "src/lakehouse/connectors/bddk_weekly.py"

REQUESTED_AT = datetime(2026, 9, 9, 21, 30, tzinfo=timezone.utc)
DOWNLOADED_AT = datetime(2026, 9, 10, 6, 15, 42, tzinfo=timezone.utc)


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes, content_type: str) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type}


class _FakeSession:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def post(
        self,
        url: str,
        *,
        data: list[tuple[str, str]],
        headers: dict[str, str],
        timeout: float,
    ) -> _FakeResponse:
        self.calls.append(
            {"url": url, "data": list(data), "headers": dict(headers), "timeout": timeout}
        )
        outcome = self._outcomes.pop(0) if self._outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, _FakeResponse)
        return outcome


def _ok_response() -> _FakeResponse:
    return _FakeResponse(200, FIXTURE.read_bytes(), "application/json; charset=utf-8")


def _spec(**overrides: object) -> FetchSpec:
    defaults: dict[str, object] = {
        "source_id": "bddk_weekly",
        "dataset_id": "bddk_weekly_housing_loans",
        "locator": f"{BDDK_WEEKLY_BASE_URL}{BDDK_WEEKLY_SERIES_PATH}",
        "start_date": date(2026, 1, 2),
        "end_date": date(2026, 6, 26),
        "parameters": {
            "id": "1.0.4",
            "kalem_id": "5690",
            "expected_measure_label": "a) Konut",
            "expected_currency": "TRY",
            "expected_column": "Toplam",
            "parabirimi": "TRY",
            "sutun": "3",
            "tarafKodu": "10001",
        },
        "timeout": 30.0,
        "requested_at": REQUESTED_AT,
    }
    defaults.update(overrides)
    return FetchSpec(**defaults)  # type: ignore[arg-type]


def _connector(
    tmp_path: Path, outcomes: list[object], **kwargs: object
) -> tuple[BddkWeeklyConnector, _FakeSession]:
    session = _FakeSession(outcomes)
    kwargs.setdefault("clock", lambda: DOWNLOADED_AT)
    connector = BddkWeeklyConnector(
        RawStorage(tmp_path / "data/raw"),
        session=session,  # type: ignore[arg-type]
        backoff_seconds=0.0,
        sleep=lambda _seconds: None,
        **kwargs,  # type: ignore[arg-type]
    )
    return connector, session


# ------------------------------------------------------------------ request shape


def test_connector_implements_base_and_sends_the_verified_request(tmp_path: Path) -> None:
    """Verified live: POST, this path, these field names, this date format."""

    connector, session = _connector(tmp_path, [_ok_response()])

    connector.fetch(_spec())

    assert isinstance(connector, BaseConnector)
    call = session.calls[0]
    assert call["url"] == f"{BDDK_WEEKLY_BASE_URL}{BDDK_WEEKLY_SERIES_PATH}"
    assert call["data"] == [
        ("dil", "tr"),
        ("baslangicTarihi", "2.01.2026 00:00:00"),
        ("bitisTarihi", "26.06.2026 00:00:00"),
        ("id", "1.0.4"),
        ("parabirimi", "TRY"),
        ("sutun", "3"),
        ("tarafKodu", "10001"),
    ]
    assert call["timeout"] == 30.0


def test_weekly_date_format_does_not_pad_the_day() -> None:
    """The live endpoint takes ``2.01.2026 00:00:00``, not ``02.01.2026``."""

    assert format_weekly_date(date(2026, 1, 2)) == "2.01.2026 00:00:00"
    assert format_weekly_date(date(2026, 6, 26)) == "26.06.2026 00:00:00"
    assert format_weekly_date(date(2021, 1, 8)) == "8.01.2021 00:00:00"


def test_no_cookie_or_antiforgery_token_is_sent(tmp_path: Path) -> None:
    """Verified live: the endpoint answers a cookie-less client, so none is invented here."""

    connector, session = _connector(tmp_path, [_ok_response()])

    connector.fetch(_spec())

    headers = session.calls[0]["headers"]
    assert "Cookie" not in headers  # type: ignore[operator]
    sent_fields = {name for name, _ in session.calls[0]["data"]}  # type: ignore[union-attr]
    assert "__RequestVerificationToken" not in sent_fields


@pytest.mark.parametrize(
    "missing",
    ["id", "kalem_id", "expected_measure_label", "expected_currency",
     "expected_column", "parabirimi", "sutun", "tarafKodu"],
)
def test_missing_required_parameter_fails_before_any_request(
    tmp_path: Path, missing: str
) -> None:
    connector, session = _connector(tmp_path, [_ok_response()])
    parameters = {
        "id": "1.0.4",
        "kalem_id": "5690",
        "expected_measure_label": "a) Konut",
        "expected_currency": "TRY",
        "expected_column": "Toplam",
        "parabirimi": "TRY",
        "sutun": "3",
        "tarafKodu": "10001",
    }
    parameters.pop(missing)

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec(parameters=parameters))

    payload = excinfo.value.payload
    assert payload.error_code == "UNSUPPORTED_FORMAT"
    assert payload.retryable is False
    assert missing in payload.message
    assert session.calls == []


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "kalem_id",
        "expected_measure_label",
        "expected_currency",
        "expected_column",
        "parabirimi",
        "sutun",
        "tarafKodu",
    ],
)
def test_repeated_single_valued_field_is_rejected_before_any_request(
    tmp_path: Path, field: str
) -> None:
    """Nothing was observed about repeated values, so they are refused rather than guessed."""

    connector, session = _connector(tmp_path, [_ok_response()])
    parameters: dict[str, object] = {
        "id": "1.0.4",
        "kalem_id": "5690",
        "expected_measure_label": "a) Konut",
        "expected_currency": "TRY",
        "expected_column": "Toplam",
        "parabirimi": "TRY",
        "sutun": "3",
        "tarafKodu": "10001",
    }
    parameters[field] = [parameters[field], "other"]

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec(parameters=parameters))

    assert excinfo.value.payload.error_code == "UNSUPPORTED_FORMAT"
    assert excinfo.value.payload.retryable is False
    assert "exactly one" in excinfo.value.payload.message
    assert session.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_date": None},
        {"end_date": None},
        {"start_date": date(2026, 6, 26), "end_date": date(2026, 1, 2)},
    ],
)
def test_invalid_date_bounds_fail_before_any_request(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    connector, session = _connector(tmp_path, [_ok_response()])

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec(**overrides))

    assert excinfo.value.payload.error_code == "UNSUPPORTED_FORMAT"
    assert excinfo.value.payload.retryable is False
    assert session.calls == []


# ------------------------------------------------------------------- RAW storage


def test_successful_response_is_written_through_shared_raw_storage(tmp_path: Path) -> None:
    connector, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    assert asset.raw_path.parent == tmp_path / "data/raw/bddk_weekly/2026-09-10"
    assert asset.raw_path.read_bytes() == FIXTURE.read_bytes()
    assert asset.http_status == 200
    assert asset.media_type == "application/json"
    assert asset.byte_size == len(FIXTURE.read_bytes())


def test_connector_stores_bytes_without_parsing_them(tmp_path: Path) -> None:
    """The stored artifact is the exact response; the connector never looks inside it."""

    connector, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    assert asset.raw_path.read_bytes() == FIXTURE.read_bytes()
    assert "XEkseni" not in asset.metadata
    assert "YEkseni" not in asset.metadata
    assert set(asset.metadata) == {
        "request_form",
        "requested_start_date",
        "requested_end_date",
        "requested_chart_id",
        "requested_kalem_id",
        "expected_measure_label",
        "expected_currency",
        "expected_column",
        "requested_currency",
        "requested_column",
        "requested_taraf",
        "api_base_url",
        "html_report_fallback_path",
    }


def test_request_metadata_records_the_verified_request_facts(tmp_path: Path) -> None:
    connector, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    assert asset.metadata["requested_chart_id"] == "1.0.4"
    assert asset.metadata["requested_kalem_id"] == "5690"
    assert asset.metadata["requested_currency"] == "TRY"
    assert asset.metadata["requested_column"] == "3"
    assert asset.metadata["requested_taraf"] == "10001"
    assert asset.metadata["requested_start_date"] == "2.01.2026 00:00:00"
    assert asset.metadata["requested_end_date"] == "26.06.2026 00:00:00"
    assert asset.metadata["html_report_fallback_path"] == BDDK_WEEKLY_REPORT_PATH


def test_identical_response_is_not_written_twice(tmp_path: Path) -> None:
    connector, _ = _connector(tmp_path, [_ok_response(), _ok_response()])

    first = connector.fetch(_spec())[0]
    second = connector.fetch(_spec(requested_at=datetime(2026, 9, 11, tzinfo=timezone.utc)))[0]

    assert first.raw_path == second.raw_path
    assert first.artifact_sha256 == second.artifact_sha256
    assert len(list((tmp_path / "data/raw").rglob("*.json"))) == 1


# ----------------------------------------------------------------- retry policy


def test_timeout_is_classified_as_a_retryable_fetch_timeout(tmp_path: Path) -> None:
    connector, session = _connector(
        tmp_path, [requests.Timeout("slow")] * 3, max_attempts=3
    )

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "FETCH_TIMEOUT"
    assert excinfo.value.payload.retryable is True
    assert len(session.calls) == 3


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503])
def test_retryable_http_statuses_are_retried(tmp_path: Path, status: int) -> None:
    failing = _FakeResponse(status, b"", "text/html")
    connector, session = _connector(
        tmp_path, [failing, failing, _ok_response()], max_attempts=3
    )

    asset = connector.fetch(_spec())[0]

    assert len(session.calls) == 3
    assert asset.http_status == 200


@pytest.mark.parametrize("status", [400, 403, 404, 410])
def test_permanent_http_errors_are_not_retried(tmp_path: Path, status: int) -> None:
    connector, session = _connector(
        tmp_path, [_FakeResponse(status, b"", "text/html")], max_attempts=3
    )

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "HTTP_ERROR"
    assert excinfo.value.payload.retryable is False
    assert len(session.calls) == 1


def test_failed_http_response_never_becomes_an_asset(tmp_path: Path) -> None:
    connector, _ = _connector(
        tmp_path, [_FakeResponse(404, b"not found", "text/html")], max_attempts=1
    )

    with pytest.raises(LakehouseError):
        connector.fetch(_spec())

    assert not list((tmp_path / "data/raw").rglob("*"))


def test_connection_error_is_retryable_and_source_unavailable(tmp_path: Path) -> None:
    connector, session = _connector(
        tmp_path, [requests.ConnectionError("down")] * 2, max_attempts=2
    )

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "SOURCE_UNAVAILABLE"
    assert excinfo.value.payload.retryable is True
    assert len(session.calls) == 2


# ------------------------------------------------------------------------ clock


def test_fetched_at_is_the_download_time_not_the_request_time(tmp_path: Path) -> None:
    connector, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    assert asset.fetched_at == DOWNLOADED_AT
    assert asset.fetched_at != REQUESTED_AT
    assert asset.fetched_at > REQUESTED_AT
    assert asset.raw_path.parent.name == "2026-09-10"


def test_fetched_at_is_read_after_the_response_arrives(tmp_path: Path) -> None:
    ticks = iter(
        [
            datetime(2026, 9, 10, 6, 15, 42, tzinfo=timezone.utc),
            datetime(2026, 9, 10, 6, 15, 47, tzinfo=timezone.utc),
        ]
    )
    connector, session = _connector(
        tmp_path,
        [requests.Timeout("slow"), _ok_response()],
        clock=lambda: next(ticks),
        max_attempts=3,
    )

    asset = connector.fetch(_spec())[0]

    assert len(session.calls) == 2
    assert asset.fetched_at == datetime(2026, 9, 10, 6, 15, 42, tzinfo=timezone.utc)


def test_naive_clock_is_rejected(tmp_path: Path) -> None:
    connector, _ = _connector(
        tmp_path, [_ok_response()], clock=lambda: datetime(2026, 9, 10, 6, 15)
    )

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "SOURCE_UNAVAILABLE"
    assert "timezone-aware" in excinfo.value.payload.message


def test_non_utc_clock_is_normalized_to_utc(tmp_path: Path) -> None:
    istanbul = timezone(timedelta(hours=3))
    connector, _ = _connector(
        tmp_path,
        [_ok_response()],
        clock=lambda: datetime(2026, 9, 10, 9, 15, 42, tzinfo=istanbul),
    )

    asset = connector.fetch(_spec())[0]

    assert asset.fetched_at == DOWNLOADED_AT
    assert asset.fetched_at.tzinfo == timezone.utc


# ------------------------------------------------------- kalem_id is identity


@pytest.mark.parametrize("blank", ["", "   ", None, [], ()])
def test_blank_kalem_id_fails_before_any_request(tmp_path: Path, blank: object) -> None:
    """`kalem_id` is the only stable identity, so a blank one is refused, not defaulted."""

    connector, session = _connector(tmp_path, [_ok_response()])

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(
            _spec(
                parameters={
                    "id": "1.0.4",
                    "expected_measure_label": "a) Konut",
                    "expected_currency": "TRY",
                    "expected_column": "Toplam",
                    "kalem_id": blank,
                    "parabirimi": "TRY",
                    "sutun": "3",
                    "tarafKodu": "10001",
                }
            )
        )

    payload = excinfo.value.payload
    assert payload.error_code == "UNSUPPORTED_FORMAT"
    assert payload.retryable is False
    assert "kalem_id" in payload.message
    assert session.calls == []
    assert not list((tmp_path / "data/raw").rglob("*"))


def test_multiple_kalem_ids_fail_before_any_request(tmp_path: Path) -> None:
    connector, session = _connector(tmp_path, [_ok_response()])

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(
            _spec(
                parameters={
                    "id": "1.0.4",
                    "expected_measure_label": "a) Konut",
                    "expected_currency": "TRY",
                    "expected_column": "Toplam",
                    "kalem_id": ["5690", "5867"],
                    "parabirimi": "TRY",
                    "sutun": "3",
                    "tarafKodu": "10001",
                }
            )
        )

    payload = excinfo.value.payload
    assert payload.error_code == "UNSUPPORTED_FORMAT"
    assert payload.retryable is False
    assert "exactly one" in payload.message
    assert "kalem_id" in payload.message
    assert session.calls == []
    assert not list((tmp_path / "data/raw").rglob("*"))


def test_identity_expectations_are_never_sent_on_the_wire(tmp_path: Path) -> None:
    """The endpoint has no such fields; they are identity metadata only."""

    connector, session = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    sent_fields = [name for name, _ in session.calls[0]["data"]]  # type: ignore[union-attr]
    assert {
        "kalem_id",
        "expected_measure_label",
        "expected_currency",
        "expected_column",
    }.isdisjoint(sent_fields)
    assert "5690" not in [value for _, value in session.calls[0]["data"]]  # type: ignore[union-attr]
    assert asset.metadata["requested_kalem_id"] == "5690"
    assert asset.metadata["expected_measure_label"] == "a) Konut"
    assert asset.metadata["expected_currency"] == "TRY"
    assert asset.metadata["expected_column"] == "Toplam"


def test_kalem_id_is_recorded_stripped_and_single(tmp_path: Path) -> None:
    connector, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(
        _spec(
            parameters={
                "id": "1.0.4",
                "expected_measure_label": "a) Konut",
                "expected_currency": "TRY",
                "expected_column": "Toplam",
                "kalem_id": "  5690  ",
                "parabirimi": "TRY",
                "sutun": "3",
                "tarafKodu": "10001",
            }
        )
    )[0]

    assert asset.metadata["requested_kalem_id"] == "5690"


# ------------------------------------------------------------ TLS classification


def test_tls_verification_failure_is_not_retryable(tmp_path: Path) -> None:
    """BDDK omits its intermediate certificate. That is source-side and permanent."""

    error = requests.exceptions.SSLError(
        "HTTPSConnectionPool(host='www.bddk.org.tr', port=443): "
        "certificate verify failed: unable to get local issuer certificate"
    )
    connector, session = _connector(tmp_path, [error] * 3, max_attempts=3)

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    payload = excinfo.value.payload
    assert payload.error_code == "SOURCE_UNAVAILABLE"
    assert payload.retryable is False
    assert "TLS certificate verification failed" in payload.message
    # a permanent failure must not be retried
    assert len(session.calls) == 1
    assert not list((tmp_path / "data/raw").rglob("*"))


def test_tls_error_is_classified_before_the_generic_request_exception(
    tmp_path: Path,
) -> None:
    """SSLError subclasses RequestException; order decides retryable vs not."""

    assert issubclass(requests.exceptions.SSLError, requests.RequestException)

    tls_connector, _ = _connector(
        tmp_path, [requests.exceptions.SSLError("verify failed")], max_attempts=2
    )
    with pytest.raises(LakehouseError) as tls:
        tls_connector.fetch(_spec())

    generic_connector, _ = _connector(
        tmp_path, [requests.ConnectionError("down")] * 2, max_attempts=2
    )
    with pytest.raises(LakehouseError) as generic:
        generic_connector.fetch(_spec())

    assert tls.value.payload.retryable is False
    assert generic.value.payload.retryable is True
    assert tls.value.payload.error_code == generic.value.payload.error_code


def test_tls_error_message_carries_no_headers_or_secrets(tmp_path: Path) -> None:
    connector, _ = _connector(
        tmp_path,
        [requests.exceptions.SSLError("certificate verify failed")],
        max_attempts=1,
    )

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    message = excinfo.value.payload.message
    assert "Cookie" not in message
    assert "X-Requested-With" not in message
    assert "__RequestVerificationToken" not in message
    assert "verify=False" not in message
    # it must point at the safe remedy, not a workaround
    assert "verification left ON" in message or "verification still on" in message.lower()


def test_connector_never_disables_tls_verification() -> None:
    """A regression guard: nothing in this module may weaken TLS."""

    source = Path(CONNECTOR_SOURCE).read_text(encoding="utf-8")

    assert "verify=False" not in source
    assert "verify = False" not in source
    assert "InsecureRequestWarning" not in source
    assert "disable_warnings" not in source
    assert "_create_unverified_context" not in source
