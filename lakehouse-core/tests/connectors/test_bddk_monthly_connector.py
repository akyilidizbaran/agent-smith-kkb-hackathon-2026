"""BDDK monthly connector tests. No network access: the HTTP session is always a local fake."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from src.lakehouse.connectors.base import BaseConnector
from src.lakehouse.connectors.bddk_monthly import (
    BDDK_MONTHLY_BASE_URL,
    BDDK_MONTHLY_EXCEL_PATH,
    BDDK_MONTHLY_REPORT_PATH,
    BddkMonthlyConnector,
)
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.errors import LakehouseError
from src.lakehouse.storage.raw import RawStorage


FIXTURE = Path("tests/fixtures/raw/bddk_monthly/bddk_monthly_housing_loans.json")
REQUESTED_AT = datetime(2026, 9, 8, 21, 30, tzinfo=timezone.utc)
DOWNLOADED_AT = datetime(2026, 9, 9, 6, 15, 42, tzinfo=timezone.utc)

CONNECTOR_SOURCE = "src/lakehouse/connectors/bddk_monthly.py"


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
        "source_id": "bddk_monthly",
        "dataset_id": "bddk_monthly_housing_loans",
        "locator": f"{BDDK_MONTHLY_BASE_URL}{BDDK_MONTHLY_REPORT_PATH}",
        "start_date": date(2021, 1, 1),
        "end_date": date(2026, 6, 30),
        "parameters": {
            "periyot": "1",
            "paraBirimi": "TL",
            "taraf": "10001",
            "kalemSutun": "1534?Toplam",
        },
        "timeout": 30.0,
        "requested_at": REQUESTED_AT,
    }
    defaults.update(overrides)
    return FetchSpec(**defaults)  # type: ignore[arg-type]


def _connector(
    tmp_path: Path, outcomes: list[object], **kwargs: object
) -> tuple[BddkMonthlyConnector, _FakeSession]:
    session = _FakeSession(outcomes)
    kwargs.setdefault("clock", lambda: DOWNLOADED_AT)
    connector = BddkMonthlyConnector(
        RawStorage(tmp_path / "data/raw"),
        session=session,  # type: ignore[arg-type]
        backoff_seconds=0.0,
        sleep=lambda _seconds: None,
        **kwargs,  # type: ignore[arg-type]
    )
    return connector, session


def test_connector_implements_base_and_builds_the_verified_form(tmp_path: Path) -> None:
    connector, session = _connector(tmp_path, [_ok_response()])

    connector.fetch(_spec())

    assert isinstance(connector, BaseConnector)
    call = session.calls[0]
    assert call["url"] == f"{BDDK_MONTHLY_BASE_URL}{BDDK_MONTHLY_REPORT_PATH}"
    assert call["data"] == [
        ("baslangicYil", "2021"),
        ("baslangicAy", "1"),
        ("bitisYil", "2026"),
        ("bitisAy", "6"),
        ("periyot", "1"),
        ("paraBirimi", "TL"),
        ("taraf", "10001"),
        ("kalemSutun", "1534?Toplam"),
        ("gosterimTuru", "grid"),
    ]
    assert call["timeout"] == 30.0


def test_taraf_may_repeat_while_kalem_sutun_stays_single(tmp_path: Path) -> None:
    """BDDK accepts several parties in one call; several items in one call it does not."""

    connector, session = _connector(tmp_path, [_ok_response()])

    connector.fetch(
        _spec(
            parameters={
                "periyot": "1",
                "paraBirimi": "TL",
                "taraf": ["10001", "10002"],
                "kalemSutun": "1534?Toplam",
            }
        )
    )

    pairs = session.calls[0]["data"]
    assert [value for name, value in pairs if name == "taraf"] == ["10001", "10002"]  # type: ignore[union-attr]
    assert [value for name, value in pairs if name == "kalemSutun"] == ["1534?Toplam"]  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "kalem_sutun",
    [
        ["1534?Toplam", "288?Toplam"],
        ["1534?Toplam", "288?Toplam", "219?Toplam", "238?Toplam"],
        ("1534?Toplam", "1534?Tp"),
    ],
)
def test_multiple_kalem_sutun_values_are_rejected_before_any_request(
    tmp_path: Path, kalem_sutun: object
) -> None:
    """Live verification: BDDK answers HTTP 200 with success:false for multi-item requests.

    The connector must fail locally and typed rather than spend a request on a known-bad
    combination, and it must do so without inspecting any response body.
    """

    connector, session = _connector(tmp_path, [_ok_response()])

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(
            _spec(
                parameters={
                    "periyot": "1",
                    "paraBirimi": "TL",
                    "taraf": "10001",
                    "kalemSutun": kalem_sutun,
                }
            )
        )

    payload = excinfo.value.payload
    assert payload.error_code == "UNSUPPORTED_FORMAT"
    assert payload.retryable is False
    assert "exactly one" in payload.message
    assert session.calls == []
    assert not list((tmp_path / "data/raw").rglob("*"))


def test_historical_schema_ids_are_fetched_one_spec_at_a_time(tmp_path: Path) -> None:
    """`1534,288,219,238` are per-schema-version ids of one concept: one FetchSpec each."""

    connector, session = _connector(tmp_path, [_ok_response(), _ok_response()])

    for item_id in ("1534?Toplam", "288?Toplam"):
        connector.fetch(
            _spec(
                parameters={
                    "periyot": "1",
                    "paraBirimi": "TL",
                    "taraf": "10001",
                    "kalemSutun": item_id,
                }
            )
        )

    sent = [
        [value for name, value in call["data"] if name == "kalemSutun"]  # type: ignore[union-attr]
        for call in session.calls
    ]
    assert sent == [["1534?Toplam"], ["288?Toplam"]]


def test_successful_response_is_written_through_shared_raw_storage(tmp_path: Path) -> None:
    connector, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    assert asset.raw_path.parent == tmp_path / "data/raw/bddk_monthly/2026-09-09"
    assert asset.raw_path.read_bytes() == FIXTURE.read_bytes()
    assert asset.http_status == 200
    assert asset.metadata["expected_period_count"] == 66
    assert asset.metadata["requested_kalem_sutun"] == ["1534?Toplam"]
    assert asset.metadata["requested_currency"] == "TL"
    assert asset.metadata["excel_fallback_path"] == BDDK_MONTHLY_EXCEL_PATH


def test_identical_response_is_not_written_twice(tmp_path: Path) -> None:
    connector, _ = _connector(tmp_path, [_ok_response(), _ok_response()])

    first = connector.fetch(_spec())[0]
    second = connector.fetch(
        _spec(requested_at=datetime(2026, 9, 10, tzinfo=timezone.utc))
    )[0]

    assert first.raw_path == second.raw_path
    assert len(list((tmp_path / "data/raw").rglob("*.json"))) == 1


def test_timeout_and_transient_errors_are_retryable(tmp_path: Path) -> None:
    connector, session = _connector(
        tmp_path, [requests.Timeout("slow"), requests.Timeout("slow")], max_attempts=2
    )

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "FETCH_TIMEOUT"
    assert excinfo.value.payload.retryable is True
    assert len(session.calls) == 2


@pytest.mark.parametrize(
    ("status_code", "retryable", "attempts"),
    [(429, True, 2), (503, True, 2), (404, False, 1)],
)
def test_http_failures_are_classified_and_create_no_artifact(
    tmp_path: Path, status_code: int, retryable: bool, attempts: int
) -> None:
    failure = _FakeResponse(status_code, b"failure", "text/html")
    connector, session = _connector(tmp_path, [failure, failure], max_attempts=2)

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "HTTP_ERROR"
    assert excinfo.value.payload.retryable is retryable
    assert len(session.calls) == attempts
    assert not list((tmp_path / "data/raw").rglob("*"))


@pytest.mark.parametrize(
    "parameters",
    [
        {"paraBirimi": "TL", "taraf": "10001", "kalemSutun": "1534?Toplam"},
        {"periyot": "1", "taraf": "10001", "kalemSutun": "1534?Toplam"},
        {"periyot": "1", "paraBirimi": "TL", "kalemSutun": "1534?Toplam"},
        {"periyot": "1", "paraBirimi": "TL", "taraf": "10001"},
    ],
)
def test_missing_required_parameters_are_rejected_before_any_request(
    tmp_path: Path, parameters: dict[str, object]
) -> None:
    connector, session = _connector(tmp_path, [_ok_response()])

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec(parameters=parameters))

    assert excinfo.value.payload.error_code == "UNSUPPORTED_FORMAT"
    assert session.calls == []


def test_connector_does_not_parse_the_response(tmp_path: Path) -> None:
    connector, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    assert asset.raw_path.read_bytes() == FIXTURE.read_bytes()
    source_text = Path("src/lakehouse/connectors/bddk_monthly.py").read_text(encoding="utf-8")
    assert "json.loads" not in source_text
    assert "pandas" not in source_text


def test_fetched_at_is_the_download_time_not_the_request_time(tmp_path: Path) -> None:
    """`requested_at` is when the caller built the spec; `fetched_at` is when bytes arrived."""

    connector, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    assert asset.fetched_at == DOWNLOADED_AT
    assert asset.fetched_at != REQUESTED_AT
    assert asset.fetched_at > REQUESTED_AT
    assert asset.raw_path.parent.name == "2026-09-09"


def test_fetched_at_is_read_after_the_response_arrives(tmp_path: Path) -> None:
    """A retried request must be stamped with the time of the attempt that succeeded."""

    ticks = iter(
        [
            datetime(2026, 9, 9, 6, 15, 42, tzinfo=timezone.utc),
            datetime(2026, 9, 9, 6, 15, 47, tzinfo=timezone.utc),
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
    assert asset.fetched_at == datetime(2026, 9, 9, 6, 15, 42, tzinfo=timezone.utc)


def test_naive_clock_is_rejected(tmp_path: Path) -> None:
    connector, _ = _connector(
        tmp_path, [_ok_response()], clock=lambda: datetime(2026, 9, 9, 6, 15)
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
        clock=lambda: datetime(2026, 9, 9, 9, 15, 42, tzinfo=istanbul),
    )

    asset = connector.fetch(_spec())[0]

    assert asset.fetched_at == DOWNLOADED_AT
    assert asset.fetched_at.tzinfo == timezone.utc


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


def test_series_key_parameter_is_metadata_not_a_form_field(tmp_path: Path) -> None:
    """A historical schema id is fetched on behalf of a catalogued series (M07 follow-up, 21 Sept).

    ``series_key`` tells the parser where to publish; BDDK must never see it, and an ordinary
    request must not grow a new metadata key.
    """

    connector, session = _connector(tmp_path, [_ok_response(), _ok_response()])

    asset = connector.fetch(_spec(parameters={"periyot": "1", "paraBirimi": "TL", "taraf": ["10001"],
                                              "kalemSutun": "288?Toplam", "gosterimTuru": "grid",
                                              "series_key": "1534_Toplam"}))[0]
    plain = connector.fetch(_spec())[0]

    assert asset.metadata["requested_series_key"] == "1534_Toplam"
    assert asset.metadata["requested_kalem_sutun"] == ["288?Toplam"]
    assert all(name != "series_key" for name, _ in session.calls[0]["data"])
    assert "requested_series_key" not in plain.metadata
