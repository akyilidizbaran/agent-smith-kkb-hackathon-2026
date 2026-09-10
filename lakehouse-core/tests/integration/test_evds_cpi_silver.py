"""EVDS TÜFE (``TP.FG.J0``) through the generic connector, parser and Silver adapter.

> **EVIDENCE WARNING — READ BEFORE TRUSTING ANY NUMBER IN THIS FILE.**
>
> No official ``TP.FG.J0`` response has ever been captured by this repository, and no API key
> was available when this test was written. The payload below is **synthetic**: it reproduces
> the EVDS envelope *shape* that `src/lakehouse/parsers/evds.py` documents and that committed
> fixtures for other series confirm, with deliberately round, obviously fake index values.
>
> It is therefore a **contract test**, not a data test. It proves that the generic EVDS path
> carries a monthly index series end to end with no source-specific code. It proves **nothing**
> about TÜFE's real values, its base year, or the official keyed endpoint's date format.
>
> It is kept out of `tests/fixtures/raw/` on purpose: that directory holds captured source
> bytes, and putting invented bytes there would make a fabrication look like evidence.
> See `docs/sources/evds.md` for the live-verification status.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.evds import EVDS_API_KEY_ENV, EvdsConnector
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.parsers.evds import EvdsParser
from src.lakehouse.silver.adapters.evds import (
    SUPPORTED_CPI_SERIES_ID,
    evds_cpi_to_staging,
)
from src.lakehouse.silver.foundation import materialize_fact_observation_snapshot
from src.lakehouse.silver.pipeline import stage_ingestion_result
from src.lakehouse.storage.parquet import ParquetStorage
from src.lakehouse.storage.raw import RawStorage


FETCHED_AT = datetime(2026, 9, 11, 8, tzinfo=timezone.utc)
REQUESTED_AT = datetime(2026, 9, 11, 7, tzinfo=timezone.utc)
ISTANBUL = timezone(timedelta(hours=3))

# Synthetic. Round numbers so no reader can mistake them for published TÜFE values.
# UNIXTIME values are the first of each month at 00:00 Istanbul time, matching the shape the
# committed EVDS fixtures for other series show.
_SYNTHETIC_CPI_RESPONSE: dict[str, Any] = {
    "totalCount": 3,
    "items": [
        {"Tarih": "01-2026", "TP_FG_J0": "100.00", "UNIXTIME": {"$numberLong": "1767214800"}},
        {"Tarih": "02-2026", "TP_FG_J0": "110.00", "UNIXTIME": {"$numberLong": "1769893200"}},
        {"Tarih": "03-2026", "TP_FG_J0": None, "UNIXTIME": {"$numberLong": "1772312400"}},
    ],
    "seriesNames": {"TP_FG_J0": "SYNTHETIC - not a real TCMB series name"},
}


class _SyntheticResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}


class _SyntheticSession:
    """Replays the synthetic payload; never opens a socket."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._response = _SyntheticResponse(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def get(self, url: str, *, headers: dict[str, str], **_: Any) -> _SyntheticResponse:
        self.calls.append(("GET", url, dict(headers)))
        return self._response


def _spec() -> FetchSpec:
    return FetchSpec(
        source_id="evds",
        dataset_id="evds_cpi",
        locator="synthetic://evds/TP.FG.J0",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        parameters={"series": "TP.FG.J0", "type": "json"},
        requested_at=REQUESTED_AT,
    )


def _ingest(tmp_path: Path, monkeypatch: Any, session: _SyntheticSession):
    monkeypatch.setenv(EVDS_API_KEY_ENV, "p0-contract-test-only-key")
    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    pipeline = IngestionPipeline(
        connector=EvdsConnector(
            RawStorage(tmp_path / "data/raw"),
            session=session,
            max_attempts=1,
            clock=lambda: FETCHED_AT,
        ),
        parser=EvdsParser(),
        artifact_repository=ArtifactRepository(connection),
        parquet_storage=ParquetStorage(tmp_path / "data/bronze"),
    )
    return connection, pipeline.run(_spec())[0]


# ------------------------------------------------- the generic path needs no new code


def test_generic_connector_and_parser_handle_cpi_without_source_specific_code(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """No ``CpiConnector`` and no ``CpiParser`` exist, and none are needed.

    The only thing that distinguishes TÜFE from the other EVDS series in this path is the
    ``FetchSpec``. If a future change forces a source-specific class for a new EVDS series,
    this is where the regression shows up.
    """

    session = _SyntheticSession(_SYNTHETIC_CPI_RESPONSE)
    connection, result = _ingest(tmp_path, monkeypatch, session)
    try:
        bronze = ParquetStorage.read(result.bronze_path)

        assert set(bronze["series_id"]) == {SUPPORTED_CPI_SERIES_ID}
        assert set(bronze["dataset_id"]) == {"evds_cpi"}
        # The dotted native code becomes an underscored response column; the parser maps it
        # back using the code the connector actually requested.
        assert set(bronze["series_column"]) == {"TP_FG_J0"}
        assert len(bronze) == 3

        # The API key travels in a header and must never appear in the stored locator.
        assert "p0-contract-test-only-key" not in result.asset.locator
        assert "key" not in result.asset.metadata
    finally:
        connection.close()


def test_cpi_reaches_silver_as_an_index_level(tmp_path: Path, monkeypatch: Any) -> None:
    """TÜFE is published as the index level the source gave, never as a change rate."""

    session = _SyntheticSession(_SYNTHETIC_CPI_RESPONSE)
    connection, result = _ingest(tmp_path, monkeypatch, session)
    try:
        staging, _ = stage_ingestion_result(result, adapter=evds_cpi_to_staging)
        silver = materialize_fact_observation_snapshot(connection, staging)

        assert set(silver["series_id"]) == {SUPPORTED_CPI_SERIES_ID}
        assert set(silver["measure_type"]) == {"index"}
        assert set(silver["unit"]) == {"index"}
        assert set(silver["frequency"]) == {"monthly"}

        values = [
            None if value is None or pd.isna(value) else float(value)
            for value in silver["value"]
        ]
        # Levels, verbatim. A month-over-month change would have produced 10.0, and a
        # rebasing would have produced something other than the source numbers.
        assert values == [100.0, 110.0, None]
        assert 10.0 not in [v for v in values if v is not None]
    finally:
        connection.close()


def test_cpi_month_bounds_agree_with_the_unambiguous_unixtime_field(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """``Tarih`` is ``MM-YYYY`` here, but the cross-check is what makes it safe.

    EVDS date strings are ambiguous in general; ``UNIXTIME`` is not. Deriving the month
    independently from ``UNIXTIME`` means a future keyed-endpoint response that orders the
    date differently cannot pass unnoticed.
    """

    session = _SyntheticSession(_SYNTHETIC_CPI_RESPONSE)
    connection, result = _ingest(tmp_path, monkeypatch, session)
    try:
        bronze = ParquetStorage.read(result.bronze_path)
        staging, _ = stage_ingestion_result(result, adapter=evds_cpi_to_staging)
        silver = materialize_fact_observation_snapshot(connection, staging)

        expected_starts = [
            datetime.fromtimestamp(int(value), ISTANBUL).date()
            for value in bronze["unixtime"]
        ]
        assert list(silver["period_start"]) == expected_starts
        assert list(silver["observation_date"]) == list(silver["period_end"])
        for _, row in silver.iterrows():
            assert row["period_start"].day == 1
            assert row["period_end"] >= row["period_start"]
        assert list(silver["observation_date"]) == [
            date(2026, 1, 31),
            date(2026, 2, 28),
            date(2026, 3, 31),
        ]
    finally:
        connection.close()


def test_cpi_source_null_stays_null(tmp_path: Path, monkeypatch: Any) -> None:
    """A missing CPI month must not become a measured zero index."""

    session = _SyntheticSession(_SYNTHETIC_CPI_RESPONSE)
    connection, result = _ingest(tmp_path, monkeypatch, session)
    try:
        staging, _ = stage_ingestion_result(result, adapter=evds_cpi_to_staging)
        silver = materialize_fact_observation_snapshot(connection, staging)

        march = silver[silver["observation_date"] == date(2026, 3, 31)].iloc[0]
        assert march["value"] is None or pd.isna(march["value"])
        assert march["quality_flag"] == "missing_value"
    finally:
        connection.close()


def test_cpi_adapter_refuses_another_series(tmp_path: Path, monkeypatch: Any) -> None:
    """The CPI mapping must not silently absorb a different EVDS series."""

    session = _SyntheticSession(_SYNTHETIC_CPI_RESPONSE)
    connection, result = _ingest(tmp_path, monkeypatch, session)
    try:
        bronze = ParquetStorage.read(result.bronze_path)
        wrong = bronze.copy()
        wrong["series_id"] = "evds:TP.KFE.TR"
        from src.lakehouse.silver.foundation import SilverValidationError
        from src.lakehouse.storage.parquet import read_identity

        with pytest.raises(SilverValidationError):
            evds_cpi_to_staging(wrong, identity=read_identity(result.bronze_path))
    finally:
        connection.close()


def test_cpi_provenance_and_lineage_survive(tmp_path: Path, monkeypatch: Any) -> None:
    """The new series inherits the same provenance guarantees as the existing four."""

    session = _SyntheticSession(_SYNTHETIC_CPI_RESPONSE)
    connection, result = _ingest(tmp_path, monkeypatch, session)
    try:
        staging, bronze_identity = stage_ingestion_result(
            result, adapter=evds_cpi_to_staging
        )
        silver = materialize_fact_observation_snapshot(connection, staging)

        assert set(silver["source_id"]) == {"evds"}
        assert set(silver["dataset_id"]) == {"evds_cpi"}
        assert set(silver["artifact_sha256"]) == {result.asset.artifact_sha256}
        assert set(silver["schema_version"]) == {bronze_identity.schema_version}
        assert silver["fetched_at"].notna().all()
        assert set(silver["run_id"]) == {result.run_id}
        assert silver["vintage_id"].notna().all()
    finally:
        connection.close()
