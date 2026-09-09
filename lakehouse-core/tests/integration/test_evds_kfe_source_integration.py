"""Offline end-to-end test for `TP.KFE.TR` through the **generic** EVDS source classes.

The point of this test is what it does *not* contain: there is no `KfeConnector` and no
`KfeParser`. A second EVDS series reaches Bronze through exactly the same `EvdsConnector` and
`EvdsParser` that `TP.KTF12` uses, with only a `FetchSpec` telling them apart. If a future
series ever needs its own connector class, this test is where that regression shows up.

Everything is real production code — RAW storage, artifact repository, parquet storage and the
ingestion pipeline. Two inputs are substituted, neither of them source logic:

- the HTTP transport, which replays committed fixture bytes instead of opening a socket, and
- the connector clock, so `fetched_at` and the RAW path are deterministic.

This is an offline test of real code, **not** a live call to EVDS.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.evds import (
    EVDS_API_KEY_ENV,
    EvdsConnector,
)
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.parsers.evds import EVDS_SCHEMA_VERSION, EvdsParser
from src.lakehouse.storage.parquet import ParquetStorage, read_identity
from src.lakehouse.storage.raw import RawStorage, sha256_bytes


FIXTURE = Path("tests/fixtures/raw/evds/evds_kfe_monthly.json")
CATALOG = Path("catalog/series/evds.yml")

SOURCE_ID = "evds"
DATASET_ID = "evds_housing_price_index"
SERIES_CODE = "TP.KFE.TR"
SERIES_ID = "evds:TP.KFE.TR"

FETCHED_AT = datetime(2026, 9, 9, 6, 15, 42, tzinfo=timezone.utc)
REQUESTED_AT = datetime(2026, 9, 8, 21, 30, tzinfo=timezone.utc)
FAKE_KEY = "integration-test-key-not-a-real-credential"
EXPECTED_ROWS = 3


class FixtureResponse:
    """HTTP response stub exposing only the fields the connector consumes."""

    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200
        self.headers = {"Content-Type": "application/json; charset=utf-8"}


class FixtureSession:
    """Injected transport returning committed fixture bytes without opening a socket."""

    def __init__(self, fixture: Path) -> None:
        self._response = FixtureResponse(fixture.read_bytes())
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def get(self, url: str, *, headers: dict[str, str], **_: Any) -> FixtureResponse:
        self.calls.append(("GET", url, dict(headers)))
        return self._response


def _spec() -> FetchSpec:
    return FetchSpec(
        source_id=SOURCE_ID,
        dataset_id=DATASET_ID,
        locator="fixture://evds/evds_kfe_monthly.json",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        parameters={"series": SERIES_CODE, "frequency": "5"},
        requested_at=REQUESTED_AT,
    )


def _pipeline(tmp_path: Path, session: FixtureSession):
    raw_storage = RawStorage(tmp_path / "data/raw")
    parquet_storage = ParquetStorage(tmp_path / "data/bronze")
    trusted = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    pipeline = IngestionPipeline(
        connector=EvdsConnector(
            raw_storage,
            session=session,  # type: ignore[arg-type]
            max_attempts=1,
            clock=lambda: FETCHED_AT,
        ),
        parser=EvdsParser(),
        artifact_repository=ArtifactRepository(trusted),
        parquet_storage=parquet_storage,
    )
    return pipeline, trusted, parquet_storage


def test_kfe_reaches_bronze_through_the_generic_evds_classes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FetchSpec → EvdsConnector → RAW → meta.artifact(+_request) → EvdsParser → Bronze."""

    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    session = FixtureSession(FIXTURE)
    pipeline, trusted, parquet_storage = _pipeline(tmp_path, session)

    first = pipeline.run(_spec())[0]
    second = pipeline.run(_spec())[0]

    # --- no bespoke class was involved
    assert type(pipeline.connector).__name__ == "EvdsConnector"
    assert type(pipeline.parser).__name__ == "EvdsParser"

    # --- RAW is byte-identical to the committed fixture
    assert first.asset.raw_path.is_file()
    assert first.asset.raw_path.read_bytes() == FIXTURE.read_bytes()
    assert first.asset.artifact_sha256 == sha256_bytes(FIXTURE.read_bytes())
    assert first.asset.source_id == SOURCE_ID
    assert first.asset.dataset_id == DATASET_ID
    assert first.asset.fetched_at == FETCHED_AT

    # --- the artifact and its request provenance are persisted, once
    assert first.artifact_inserted is True
    assert second.artifact_inserted is False
    assert trusted.execute("SELECT count(*) FROM meta.artifact").fetchone() == (1,)
    assert len(list((tmp_path / "data/raw").rglob("*.json"))) == 1
    persisted = trusted.execute(
        """
        SELECT locator, request_metadata_json
        FROM meta.artifact_request
        WHERE artifact_sha256 = ?
        """,
        [first.asset.artifact_sha256],
    ).fetchone()
    assert persisted is not None
    assert persisted[0] == first.asset.locator
    assert json.loads(persisted[1]) == first.asset.metadata
    assert first.asset.metadata["requested_series"] == [SERIES_CODE]

    # --- the parsed batch keeps the three monthly observations verbatim
    frame = first.parsed_batch.dataframe
    assert first.parsed_batch.schema_version == EVDS_SCHEMA_VERSION
    assert first.parsed_batch.artifact_sha256 == first.asset.artifact_sha256
    assert len(frame) == EXPECTED_ROWS
    assert set(frame["series_id"]) == {SERIES_ID}
    assert list(frame["date_raw"]) == ["01-2026", "02-2026", "03-2026"]
    assert list(frame["value_raw"]) == ["211.73", "215.40", "219.52"]
    assert first.parsed_batch.warnings == []

    # --- Bronze carries the representation identity
    identity = read_identity(first.bronze_path)
    assert identity.source_id == SOURCE_ID
    assert identity.dataset_id == DATASET_ID
    assert identity.artifact_sha256 == first.asset.artifact_sha256
    assert identity.schema_version == EVDS_SCHEMA_VERSION
    assert second.bronze_path == first.bronze_path

    trusted.close()


def test_kfe_run_never_leaks_the_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The key travels in a request header only; nothing persisted may contain it."""

    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    session = FixtureSession(FIXTURE)
    pipeline, trusted, _ = _pipeline(tmp_path, session)

    result = pipeline.run(_spec())[0]

    # the key really was sent, so the assertions below are not vacuous
    assert session.calls[0][2].get("key") == FAKE_KEY

    assert FAKE_KEY not in result.asset.locator
    assert FAKE_KEY not in str(result.asset.raw_path)
    assert FAKE_KEY not in json.dumps(result.asset.metadata, ensure_ascii=False)
    assert FAKE_KEY not in result.asset.raw_path.read_text(encoding="utf-8")
    assert FAKE_KEY not in result.bronze_path.read_bytes().decode("latin-1")

    persisted = trusted.execute(
        "SELECT locator, request_metadata_json FROM meta.artifact_request"
    ).fetchall()
    assert persisted
    assert all(FAKE_KEY not in field for row in persisted for field in row)
    trusted.close()


def test_kfe_error_messages_never_contain_the_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.lakehouse.errors import LakehouseError

    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)
    connector = EvdsConnector(
        RawStorage(tmp_path / "data/raw"),
        session=FixtureSession(FIXTURE),  # type: ignore[arg-type]
        max_attempts=1,
        clock=lambda: FETCHED_AT,
    )

    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(
            FetchSpec(
                source_id=SOURCE_ID,
                dataset_id=DATASET_ID,
                locator="fixture://evds",
                start_date=date(2026, 3, 31),
                end_date=date(2026, 1, 1),  # end before start
                parameters={"series": SERIES_CODE},
                requested_at=REQUESTED_AT,
            )
        )

    assert FAKE_KEY not in str(excinfo.value)
    assert FAKE_KEY not in excinfo.value.payload.message


def test_kfe_identifiers_match_the_committed_catalog_record() -> None:
    """The catalog and this pipeline must agree on dataset_id and series_id."""

    document = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    entry = next(e for e in document["series"] if e["series_id"] == SERIES_ID)

    assert document["source_id"] == SOURCE_ID
    assert entry["dataset_id"] == DATASET_ID
    assert entry["native_code"] == SERIES_CODE
    assert entry["frequency"] == "monthly"
    assert entry["measure_type"] == "index"


def test_kfe_pipeline_opens_no_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("KFE integration attempted network access")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setenv(EVDS_API_KEY_ENV, FAKE_KEY)

    pipeline, trusted, _ = _pipeline(tmp_path, FixtureSession(FIXTURE))
    result = pipeline.run(_spec())[0]

    assert len(result.parsed_batch.dataframe) == EXPECTED_ROWS
    trusted.close()
