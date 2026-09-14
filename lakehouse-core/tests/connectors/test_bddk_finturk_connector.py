"""BDDK FinTürk connector tests. No network access: the HTTP session is always a local fake."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from src.lakehouse.connectors.base import BaseConnector
from src.lakehouse.connectors.bddk_finturk import (
    BDDK_FINTURK_BASE_URL,
    BDDK_FINTURK_DATA_PATH,
    BDDK_FINTURK_PAGE_PATH,
    BDDK_FINTURK_TABLO_BIREYSEL,
    BddkFinTurkConnector,
)
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.errors import LakehouseError
from src.lakehouse.storage.raw import RawStorage


FIXTURE = Path("tests/fixtures/raw/bddk_finturk/bddk_finturk_yalova_2025_9.json")
REQUESTED_AT = datetime(2026, 9, 10, 21, 30, tzinfo=timezone.utc)
DOWNLOADED_AT = datetime(2026, 9, 10, 22, 0, 0, tzinfo=timezone.utc)

CONNECTOR_SOURCE = "src/lakehouse/connectors/bddk_finturk.py"


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes, content_type: str = "application/json") -> None:
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type}


class _FakeSession:
    def __init__(self, post_outcomes: list[object], get_outcomes: list[object] | None = None) -> None:
        self._post_outcomes = list(post_outcomes)
        self._get_outcomes = list(get_outcomes) if get_outcomes is not None else [_FakeResponse(200, b"<html></html>", "text/html")]
        self.get_calls: list[dict[str, object]] = []
        self.post_calls: list[dict[str, object]] = []

    def get(self, url: str, *, timeout: float) -> _FakeResponse:
        self.get_calls.append({"url": url, "timeout": timeout})
        outcome = self._get_outcomes.pop(0) if self._get_outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, _FakeResponse)
        return outcome

    def post(
        self,
        url: str,
        *,
        data: list[tuple[str, str]],
        headers: dict[str, str],
        timeout: float,
    ) -> _FakeResponse:
        self.post_calls.append(
            {"url": url, "data": list(data), "headers": dict(headers), "timeout": timeout}
        )
        outcome = self._post_outcomes.pop(0) if self._post_outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, _FakeResponse)
        return outcome


def _ok_response() -> _FakeResponse:
    return _FakeResponse(200, FIXTURE.read_bytes(), "application/json; charset=utf-8")


def _spec(**overrides: object) -> FetchSpec:
    defaults: dict[str, object] = {
        "source_id": "bddk_finturk",
        "dataset_id": "bddk_finturk_yalova_housing_loans",
        "locator": f"{BDDK_FINTURK_BASE_URL}{BDDK_FINTURK_DATA_PATH}",
        "start_date": date(2025, 9, 1),
        "end_date": date(2025, 9, 30),
        "parameters": {"sehir": "YALOVA"},
        "timeout": 30.0,
        "requested_at": REQUESTED_AT,
    }
    defaults.update(overrides)
    return FetchSpec(**defaults)  # type: ignore[arg-type]


def _connector(
    tmp_path: Path,
    post_outcomes: list[object],
    get_outcomes: list[object] | None = None,
    **kwargs: object,
) -> tuple[BddkFinTurkConnector, _FakeSession]:
    session = _FakeSession(post_outcomes, get_outcomes)
    kwargs.setdefault("clock", lambda: DOWNLOADED_AT)
    kwargs.setdefault("request_interval_seconds", 0.0)
    kwargs.setdefault("sleep", lambda _seconds: None)
    connector = BddkFinTurkConnector(
        RawStorage(tmp_path / "data/raw"),
        session=session,  # type: ignore[arg-type]
        backoff_seconds=0.0,
        **kwargs,  # type: ignore[arg-type]
    )
    return connector, session


def test_connector_implements_base_and_builds_the_verified_form(tmp_path: Path) -> None:
    connector, session = _connector(tmp_path, [_ok_response()])

    connector.fetch(_spec())

    assert isinstance(connector, BaseConnector)
    assert session.get_calls[0]["url"] == f"{BDDK_FINTURK_BASE_URL}{BDDK_FINTURK_PAGE_PATH}"
    call = session.post_calls[0]
    assert call["url"] == f"{BDDK_FINTURK_BASE_URL}{BDDK_FINTURK_DATA_PATH}"
    assert call["data"] == [
        ("tabloNo", BDDK_FINTURK_TABLO_BIREYSEL),
        ("donem", "2025-9"),
        ("tarafList[0]", "10001"),
        ("sehirList[0]", "YALOVA"),
    ]
    assert call["headers"]["Accept"] == "application/json"
    assert call["timeout"] == 30.0


def test_multiple_quarters_produce_one_asset_each(tmp_path: Path) -> None:
    """A range spanning two quarter-end months yields two FetchedAssets, one request each."""

    connector, session = _connector(tmp_path, [_ok_response(), _ok_response()])

    assets = connector.fetch(_spec(start_date=date(2025, 6, 1), end_date=date(2025, 9, 30)))

    assert len(assets) == 2
    donems = [
        next(value for name, value in call["data"] if name == "donem")  # type: ignore[union-attr]
        for call in session.post_calls
    ]
    assert donems == ["2025-6", "2025-9"]


def test_non_quarter_end_months_are_excluded_from_the_range(tmp_path: Path) -> None:
    """Verified live: off-quarter months return HTTP 500. The connector never requests them."""

    connector, session = _connector(tmp_path, [])

    assets = connector.fetch(_spec(start_date=date(2025, 1, 1), end_date=date(2025, 2, 28)))

    assert assets == []
    assert session.post_calls == []
    # the session is still primed even when no period in range is requestable
    assert len(session.get_calls) == 1


def test_missing_sehir_parameter_is_rejected_before_any_request(tmp_path: Path) -> None:
    connector, session = _connector(tmp_path, [_ok_response()])

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec(parameters={}))

    assert excinfo.value.payload.error_code == "UNSUPPORTED_FORMAT"
    assert session.get_calls == []
    assert session.post_calls == []


def test_start_date_after_end_date_is_rejected_before_any_request(tmp_path: Path) -> None:
    connector, session = _connector(tmp_path, [_ok_response()])

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec(start_date=date(2025, 9, 30), end_date=date(2025, 6, 1)))

    assert excinfo.value.payload.error_code == "UNSUPPORTED_FORMAT"
    assert session.get_calls == []
    assert session.post_calls == []


def test_session_is_primed_once_per_connector_not_per_fetch(tmp_path: Path) -> None:
    connector, session = _connector(
        tmp_path, [_ok_response(), _ok_response(), _ok_response()]
    )

    connector.fetch(_spec(start_date=date(2025, 6, 1), end_date=date(2025, 9, 30)))
    connector.fetch(_spec(dataset_id="bddk_finturk_ankara_housing_loans", parameters={"sehir": "ANKARA"}))

    assert len(session.get_calls) == 1
    assert len(session.post_calls) == 3


def test_tablo_no_and_taraf_kodu_default_and_can_be_overridden(tmp_path: Path) -> None:
    connector, session = _connector(tmp_path, [_ok_response()])

    connector.fetch(
        _spec(parameters={"sehir": "YALOVA", "tarafKodu": "10002", "tabloNo": "4"})
    )

    pairs = session.post_calls[0]["data"]
    assert ("tabloNo", "4") in pairs  # type: ignore[operator]
    assert ("tarafList[0]", "10002") in pairs  # type: ignore[operator]


def test_requests_are_paced_between_quarters_not_before_the_first(tmp_path: Path) -> None:
    sleeps: list[float] = []
    connector, _ = _connector(
        tmp_path,
        [_ok_response(), _ok_response(), _ok_response()],
        sleep=sleeps.append,
        request_interval_seconds=0.3,
    )

    connector.fetch(_spec(start_date=date(2025, 3, 1), end_date=date(2025, 9, 30)))

    assert sleeps == [0.3, 0.3]


def test_successful_response_is_written_through_shared_raw_storage(tmp_path: Path) -> None:
    connector, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    assert asset.raw_path.parent == tmp_path / "data/raw/bddk_finturk/2026-09-10"
    assert asset.raw_path.read_bytes() == FIXTURE.read_bytes()
    assert asset.http_status == 200
    assert asset.metadata["requested_sehir"] == "YALOVA"
    assert asset.metadata["requested_donem"] == "2025-9"
    assert asset.metadata["requested_tablo_no"] == BDDK_FINTURK_TABLO_BIREYSEL


def test_identical_response_is_not_written_twice(tmp_path: Path) -> None:
    connector, _ = _connector(tmp_path, [_ok_response(), _ok_response()])

    first = connector.fetch(_spec())[0]
    second = connector.fetch(
        _spec(requested_at=datetime(2026, 9, 11, tzinfo=timezone.utc))
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
    assert len(session.post_calls) == 2


@pytest.mark.parametrize(
    ("status_code", "retryable", "attempts"),
    [(429, True, 2), (500, True, 2), (404, False, 1)],
)
def test_http_failures_are_classified_and_create_no_artifact(
    tmp_path: Path, status_code: int, retryable: bool, attempts: int
) -> None:
    """500 is the exact status BDDK returns for a non-quarter-end month; kept retryable
    generically, since the connector itself already avoids ever requesting those months."""

    failure = _FakeResponse(status_code, b"failure", "text/html")
    connector, session = _connector(tmp_path, [failure, failure], max_attempts=2)

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "HTTP_ERROR"
    assert excinfo.value.payload.retryable is retryable
    assert len(session.post_calls) == attempts
    assert not list((tmp_path / "data/raw").rglob("*"))


def test_a_failed_quarter_stops_the_whole_fetch_call(tmp_path: Path) -> None:
    """fetch() raises on the first failing period; it does not silently skip and continue."""

    failure = _FakeResponse(404, b"not found", "text/html")
    connector, session = _connector(
        tmp_path, [_ok_response(), failure], max_attempts=1
    )

    with pytest.raises(LakehouseError):
        connector.fetch(_spec(start_date=date(2025, 6, 1), end_date=date(2025, 9, 30)))

    assert len(session.post_calls) == 2


def test_fetched_at_can_differ_across_quarters_in_one_fetch_call(tmp_path: Path) -> None:
    ticks = iter(
        [
            datetime(2026, 9, 10, 22, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 10, 22, 0, 5, tzinfo=timezone.utc),
        ]
    )
    connector, _ = _connector(
        tmp_path,
        [_ok_response(), _ok_response()],
        clock=lambda: next(ticks),
    )

    assets = connector.fetch(_spec(start_date=date(2025, 6, 1), end_date=date(2025, 9, 30)))

    assert assets[0].fetched_at != assets[1].fetched_at
    assert assets[1].fetched_at > assets[0].fetched_at


def test_naive_clock_is_rejected(tmp_path: Path) -> None:
    connector, _ = _connector(
        tmp_path, [_ok_response()], clock=lambda: datetime(2026, 9, 10, 22, 0)
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
        clock=lambda: datetime(2026, 9, 11, 1, 0, 0, tzinfo=istanbul),
    )

    asset = connector.fetch(_spec())[0]

    assert asset.fetched_at.tzinfo == timezone.utc


def test_connector_does_not_parse_the_response(tmp_path: Path) -> None:
    connector, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    assert asset.raw_path.read_bytes() == FIXTURE.read_bytes()
    source_text = Path(CONNECTOR_SOURCE).read_text(encoding="utf-8")
    assert "json.loads" not in source_text
    assert "pandas" not in source_text


# ------------------------------------------------------------ TLS classification


def test_tls_failure_while_priming_the_session_is_not_retryable(tmp_path: Path) -> None:
    error = requests.exceptions.SSLError("certificate verify failed")
    connector, session = _connector(
        tmp_path, [_ok_response()], get_outcomes=[error], max_attempts=3
    )

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    payload = excinfo.value.payload
    assert payload.error_code == "SOURCE_UNAVAILABLE"
    assert payload.retryable is False
    assert session.post_calls == []


def test_tls_failure_during_post_is_not_retryable(tmp_path: Path) -> None:
    error = requests.exceptions.SSLError("certificate verify failed")
    connector, session = _connector(tmp_path, [error] * 3, max_attempts=3)

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    payload = excinfo.value.payload
    assert payload.error_code == "SOURCE_UNAVAILABLE"
    assert payload.retryable is False
    assert len(session.post_calls) == 1
    assert not list((tmp_path / "data/raw").rglob("*"))


def test_connector_never_disables_tls_verification() -> None:
    """A regression guard: nothing in this module may weaken TLS."""

    source = Path(CONNECTOR_SOURCE).read_text(encoding="utf-8")

    assert "verify=False" not in source
    assert "verify = False" not in source
    assert "InsecureRequestWarning" not in source
    assert "disable_warnings" not in source
    assert "_create_unverified_context" not in source
