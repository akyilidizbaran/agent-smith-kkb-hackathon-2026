"""EVDS connector tests. No network access: the HTTP session is always a local fake."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from src.lakehouse.connectors.base import BaseConnector
from src.lakehouse.connectors.evds import (
    EVDS_API_KEY_ENV,
    EVDS_BASE_URL,
    EVDS_OBSERVATION_LIMIT,
    EvdsConnector,
)
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.errors import LakehouseError
from src.lakehouse.storage.raw import RawStorage


FIXTURE = Path("tests/fixtures/raw/evds/evds_ktf12_weekly.json")
FAKE_KEY = "unit-test-key-not-a-real-credential"
REQUESTED_AT = datetime(2026, 9, 8, 21, 30, tzinfo=timezone.utc)
DOWNLOADED_AT = datetime(2026, 9, 9, 6, 15, 42, tzinfo=timezone.utc)


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes, content_type: str) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type}


class _FakeSession:
    """Record requests and replay scripted outcomes; never touches the network."""

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _FakeResponse:
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        outcome = self._outcomes.pop(0) if self._outcomes else self._outcomes
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, _FakeResponse)
        return outcome


def _ok_response() -> _FakeResponse:
    return _FakeResponse(200, FIXTURE.read_bytes(), "application/json;charset=UTF-8")


def _spec(**overrides: object) -> FetchSpec:
    defaults: dict[str, object] = {
        "source_id": "evds",
        "dataset_id": "evds_housing_interest",
        "locator": f"{EVDS_BASE_URL}/series=TP.KTF12",
        "start_date": date(2021, 1, 1),
        "end_date": date(2026, 6, 30),
        "parameters": {"series": "TP.KTF12", "type": "json", "frequency": "3"},
        "timeout": 15.0,
        "requested_at": REQUESTED_AT,
    }
    defaults.update(overrides)
    return FetchSpec(**defaults)  # type: ignore[arg-type]


def _connector(
    tmp_path: Path, outcomes: list[object], **kwargs: object
) -> tuple[EvdsConnector, _FakeSession, RawStorage]:
    storage = RawStorage(tmp_path / "data/raw")
    session = _FakeSession(outcomes)
    kwargs.setdefault("clock", lambda: DOWNLOADED_AT)
    connector = EvdsConnector(
        storage,
        session=session,  # type: ignore[arg-type]
        backoff_seconds=0.0,
        sleep=lambda _seconds: None,
        **kwargs,  # type: ignore[arg-type]
    )
    return connector, session, storage


# 1. Connector accepts the shared FetchSpec and implements the shared base class.
def test_connector_implements_base_and_accepts_shared_fetch_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    connector, session, _ = _connector(tmp_path, [_ok_response()])

    assets = connector.fetch(_spec())

    assert isinstance(connector, BaseConnector)
    assert len(assets) == 1
    url = str(session.calls[0]["url"])
    assert url.startswith(f"{EVDS_BASE_URL}/series=TP.KTF12")
    assert "startDate=01-01-2021" in url
    assert "endDate=30-06-2026" in url
    assert "type=json" in url and "frequency=3" in url
    assert session.calls[0]["timeout"] == 15.0


# 2. A successful response is written through the shared RawStorage.
def test_successful_response_is_written_through_shared_raw_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    connector, _, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    expected_root = tmp_path / "data/raw/evds/2026-09-09"
    assert asset.raw_path.parent == expected_root
    assert asset.raw_path.name == f"{asset.artifact_sha256}.json"
    assert asset.raw_path.read_bytes() == FIXTURE.read_bytes()
    assert asset.http_status == 200
    assert asset.media_type == "application/json"
    assert asset.metadata["requested_series"] == ["TP.KTF12"]
    assert asset.metadata["observation_limit"] == EVDS_OBSERVATION_LIMIT
    assert asset.metadata["requested_start_date"] == "01-01-2021"


# 3. The same response bytes are not physically written twice.
def test_identical_response_is_not_written_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    connector, _, _ = _connector(tmp_path, [_ok_response(), _ok_response()])

    first = connector.fetch(_spec())[0]
    second = connector.fetch(
        _spec(requested_at=datetime(2026, 9, 9, tzinfo=timezone.utc))
    )[0]

    assert first.artifact_sha256 == second.artifact_sha256
    assert first.raw_path == second.raw_path
    assert len(list((tmp_path / "data/raw").rglob("*.json"))) == 1


# 4. The API key never reaches an artifact, its metadata, the locator, or the logs.
def test_api_key_never_leaks_into_artifacts_metadata_or_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    connector, session, _ = _connector(tmp_path, [_ok_response()])

    with caplog.at_level(logging.DEBUG):
        asset = connector.fetch(_spec())

    stored = asset[0]
    assert session.calls[0]["headers"] == {"key": FAKE_KEY, "Accept": "application/json"}
    assert FAKE_KEY not in stored.locator
    assert FAKE_KEY not in json.dumps(stored.metadata, default=str)
    assert FAKE_KEY not in stored.raw_path.read_text(encoding="utf-8")
    assert FAKE_KEY not in str(stored.raw_path)
    assert FAKE_KEY not in caplog.text


def test_missing_api_key_fails_without_naming_any_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(EVDS_API_KEY_ENV, raising=False)
    connector, session, _ = _connector(tmp_path, [_ok_response()])

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "SOURCE_UNAVAILABLE"
    assert excinfo.value.payload.retryable is False
    assert EVDS_API_KEY_ENV in excinfo.value.payload.message
    assert session.calls == []
    assert not list((tmp_path / "data/raw").rglob("*"))


# 5. A timeout returns the shared FETCH_TIMEOUT error code.
def test_timeout_returns_fetch_timeout_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    outcomes: list[object] = [requests.Timeout("slow"), requests.Timeout("slow")]
    connector, session, _ = _connector(tmp_path, outcomes, max_attempts=2)

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "FETCH_TIMEOUT"
    assert excinfo.value.payload.retryable is True
    assert len(session.calls) == 2
    assert not list((tmp_path / "data/raw").rglob("*"))


def test_timeout_recovers_when_a_later_attempt_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    connector, session, _ = _connector(
        tmp_path, [requests.Timeout("slow"), _ok_response()], max_attempts=3
    )

    asset = connector.fetch(_spec())[0]

    assert len(session.calls) == 2
    assert asset.http_status == 200


# 6. 429 and transient server errors are marked retryable; 4xx client errors are not.
@pytest.mark.parametrize("status_code", [408, 429, 500, 502, 503])
def test_transient_http_statuses_are_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    failure = _FakeResponse(status_code, b"", "text/plain")
    connector, session, _ = _connector(tmp_path, [failure, failure], max_attempts=2)

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "HTTP_ERROR"
    assert excinfo.value.payload.retryable is True
    assert len(session.calls) == 2


@pytest.mark.parametrize("status_code", [400, 403, 404])
def test_client_errors_are_not_retried_and_are_not_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    failure = _FakeResponse(status_code, b'{"status":"403"}', "application/json")
    connector, session, _ = _connector(tmp_path, [failure, failure], max_attempts=3)

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "HTTP_ERROR"
    assert excinfo.value.payload.retryable is False
    assert len(session.calls) == 1


# 7. A failed HTTP response never becomes a successful artifact.
@pytest.mark.parametrize("status_code", [403, 500])
def test_failed_http_response_creates_no_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    failure = _FakeResponse(status_code, b"failure body", "text/plain")
    connector, _, _ = _connector(tmp_path, [failure, failure, failure], max_attempts=2)

    with pytest.raises(LakehouseError):
        connector.fetch(_spec())

    assert not list((tmp_path / "data/raw").rglob("*"))


def test_missing_series_or_dates_are_rejected_before_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    connector, session, _ = _connector(tmp_path, [_ok_response()])

    with pytest.raises(LakehouseError) as no_series:
        connector.fetch(_spec(parameters={"type": "json"}))
    with pytest.raises(LakehouseError) as no_dates:
        connector.fetch(_spec(end_date=None))

    assert no_series.value.payload.error_code == "UNSUPPORTED_FORMAT"
    assert no_dates.value.payload.error_code == "UNSUPPORTED_FORMAT"
    assert session.calls == []


def test_connector_does_not_parse_or_transform_the_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stored bytes are byte-identical to the response; no aggregation is applied."""

    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    connector, _, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    assert asset.raw_path.read_bytes() == FIXTURE.read_bytes()
    assert asset.byte_size == FIXTURE.stat().st_size
    source_text = Path("src/lakehouse/connectors/evds.py").read_text(encoding="utf-8")
    assert "json.loads" not in source_text
    assert "pandas" not in source_text


def test_fetched_at_is_the_download_time_not_the_request_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`requested_at` is when the caller built the spec; `fetched_at` is when bytes arrived."""

    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    connector, _, _ = _connector(tmp_path, [_ok_response()])

    asset = connector.fetch(_spec())[0]

    assert asset.fetched_at == DOWNLOADED_AT
    assert asset.fetched_at != REQUESTED_AT
    assert asset.fetched_at > REQUESTED_AT
    assert asset.raw_path.parent.name == "2026-09-09"


def test_fetched_at_is_read_after_the_response_arrives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retried request must be stamped with the time of the attempt that succeeded."""

    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    ticks = iter(
        [
            datetime(2026, 9, 9, 6, 15, 42, tzinfo=timezone.utc),
            datetime(2026, 9, 9, 6, 15, 47, tzinfo=timezone.utc),
        ]
    )
    connector, session, _ = _connector(
        tmp_path,
        [requests.Timeout("slow"), _ok_response()],
        clock=lambda: next(ticks),
        max_attempts=3,
    )

    asset = connector.fetch(_spec())[0]

    assert len(session.calls) == 2
    assert asset.fetched_at == datetime(2026, 9, 9, 6, 15, 42, tzinfo=timezone.utc)


def test_naive_clock_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    connector, _, _ = _connector(
        tmp_path, [_ok_response()], clock=lambda: datetime(2026, 9, 9, 6, 15)
    )

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(_spec())

    assert excinfo.value.payload.error_code == "SOURCE_UNAVAILABLE"
    assert "timezone-aware" in excinfo.value.payload.message


def test_non_utc_clock_is_normalized_to_utc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    istanbul = timezone(timedelta(hours=3))
    connector, _, _ = _connector(
        tmp_path,
        [_ok_response()],
        clock=lambda: datetime(2026, 9, 9, 9, 15, 42, tzinfo=istanbul),
    )

    asset = connector.fetch(_spec())[0]

    assert asset.fetched_at == DOWNLOADED_AT
    assert asset.fetched_at.tzinfo == timezone.utc
