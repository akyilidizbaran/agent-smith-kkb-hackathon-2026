"""Shared helpers for the Gold test suite.

Two kinds of input are used, and they are kept strictly apart:

* **Real fixtures.** `tests/fixtures/raw/` bytes driven through the real connector, parser,
  ingestion pipeline, Silver adapter and materialization. These prove behaviour on the data
  the demo will actually use.
* **SYNTHETIC catalog rows and observations.** The Git-versioned catalog has no `ratio`,
  `flow_periodic`, `flow_ytd`, `flow_cumulative`, `count` or `unknown` series, so those
  branches cannot be exercised with real data. Everything synthetic is namespaced under
  `synthetic:` and inserted into the **test database only**; `catalog/series/*.yml` is never
  touched, and none of these values represents a real economic quantity.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.bddk_weekly import BddkWeeklyConnector
from src.lakehouse.connectors.evds import EVDS_API_KEY_ENV, EvdsConnector
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.parsers.bddk_weekly import BddkWeeklyParser
from src.lakehouse.parsers.evds import EvdsParser
from src.lakehouse.silver.adapters.bddk_weekly import bddk_weekly_to_staging
from src.lakehouse.silver.adapters.evds import evds_cpi_to_staging, evds_ktf12_to_staging
from src.lakehouse.silver.foundation import materialize_fact_observation_snapshot
from src.lakehouse.silver.pipeline import stage_ingestion_result
from src.lakehouse.storage.parquet import ParquetStorage
from src.lakehouse.storage.raw import RawStorage


FIXTURE_ROOT = Path("tests/fixtures/raw")
FETCHED_AT = datetime(2026, 9, 12, 8, tzinfo=timezone.utc)
REQUESTED_AT = datetime(2026, 9, 12, 7, tzinfo=timezone.utc)


# --------------------------------------------------------------- SYNTHETIC catalog

SYNTHETIC_SERIES: dict[str, dict[str, Any]] = {
    "stock_monthly": {
        "series_id": "synthetic:stock_monthly",
        "frequency": "monthly",
        "measure_type": "stock",
        "default_agg": "last",
        "semantic_confidence": "verified",
        "unit": "TRY_mn",
    },
    "stock_quarterly": {
        "series_id": "synthetic:stock_quarterly",
        "frequency": "quarterly",
        "measure_type": "stock",
        "default_agg": "last",
        "semantic_confidence": "verified",
        "unit": "TRY_mn",
    },
    "flow_weekly": {
        "series_id": "synthetic:flow_weekly",
        "frequency": "weekly",
        "week_anchor": "friday",
        "measure_type": "flow_periodic",
        "default_agg": "sum",
        "semantic_confidence": "verified",
        "unit": "TRY_mn",
    },
    "ratio_weekly": {
        "series_id": "synthetic:ratio_weekly",
        "frequency": "weekly",
        "week_anchor": "friday",
        "measure_type": "ratio",
        "semantic_confidence": "verified",
        "unit": "pct",
    },
    "count_weekly": {
        "series_id": "synthetic:count_weekly",
        "frequency": "weekly",
        "week_anchor": "friday",
        "measure_type": "count",
        "semantic_confidence": "verified",
        "unit": None,
    },
    "unknown_weekly": {
        "series_id": "synthetic:unknown_weekly",
        "frequency": "weekly",
        "week_anchor": "friday",
        "measure_type": "unknown",
        "semantic_confidence": "verified",
        "unit": None,
    },
    "rate_no_agg_weekly": {
        "series_id": "synthetic:rate_no_agg",
        "frequency": "weekly",
        "week_anchor": "friday",
        "measure_type": "rate",
        "default_agg": None,
        "semantic_confidence": "verified",
        "unit": "pct",
    },
    "rate_sum_weekly": {
        "series_id": "synthetic:rate_sum",
        "frequency": "weekly",
        "week_anchor": "friday",
        "measure_type": "rate",
        "default_agg": "sum",
        "semantic_confidence": "verified",
        "unit": "pct",
    },
    "rate_weekly": {
        "series_id": "synthetic:rate_weekly",
        "frequency": "weekly",
        "week_anchor": "friday",
        "measure_type": "rate",
        "default_agg": "avg",
        "semantic_confidence": "verified",
        "unit": "pct",
    },
    "ytd_monthly": {
        "series_id": "synthetic:ytd_monthly",
        "frequency": "monthly",
        "measure_type": "flow_ytd",
        "cumulative_reset": "yearly",
        "semantic_confidence": "verified",
        "unit": "TRY_mn",
    },
    "ytd_no_reset_monthly": {
        "series_id": "synthetic:ytd_no_reset",
        "frequency": "monthly",
        "measure_type": "flow_ytd",
        "cumulative_reset": None,
        "semantic_confidence": "verified",
        "unit": "TRY_mn",
    },
    "cumulative_monthly": {
        "series_id": "synthetic:cumulative_monthly",
        "frequency": "monthly",
        "measure_type": "flow_cumulative",
        "semantic_confidence": "verified",
        "unit": "TRY_mn",
    },
    "ytd_derived_monthly": {
        "series_id": "synthetic:ytd_derived",
        "frequency": "monthly",
        "measure_type": "flow_ytd",
        "cumulative_reset": "yearly",
        "semantic_confidence": "derived",
        "unit": "TRY_mn",
    },
}
"""SYNTHETIC catalog rows. Test-database only; not real series and not real semantics."""


def add_synthetic_series(
    connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]
) -> str:
    """Insert one SYNTHETIC ``meta.series`` row into the test database."""

    connection.execute(
        """
        INSERT INTO meta.series (
            series_id, source_id, native_code, dataset_id, name_tr, description,
            frequency, week_anchor, unit, measure_type, default_agg, cumulative_reset,
            semantic_confidence, semantic_source, status, catalog_content_sha256
        ) VALUES (?, 'synthetic', ?, 'synthetic_dataset', 'SYNTHETIC',
                  'SYNTHETIC test-only series; not a real economic quantity',
                  ?, ?, ?, ?, ?, ?, ?, 'manual', 'active', ?)
        """,
        [
            spec["series_id"],
            spec["series_id"].split(":", 1)[1],
            spec["frequency"],
            spec.get("week_anchor"),
            spec.get("unit"),
            spec["measure_type"],
            spec.get("default_agg"),
            spec.get("cumulative_reset"),
            spec["semantic_confidence"],
            "0" * 64,
        ],
    )
    return spec["series_id"]


def staging_rows(
    series_id: str,
    observations: list[tuple[date, str | None]],
    *,
    entity_id: str | None = None,
    digest: str = "a",
    source_warning: str | None = None,
) -> pd.DataFrame:
    """Build a SYNTHETIC Silver staging frame for one series."""

    records = [
        {
            "series_id": series_id,
            "entity_id": entity_id,
            "observation_date": observation_date,
            "period_start": None,
            "period_end": None,
            "value_raw": value,
            "source_id": "synthetic",
            "dataset_id": "synthetic_dataset",
            "artifact_sha256": digest * 64,
            "fetched_at": FETCHED_AT,
            "schema_version": "synthetic.v1",
            "vintage_id": f"artifact:{digest * 64}",
            "run_id": None,
            "source_warning": source_warning,
        }
        for observation_date, value in observations
    ]
    frame = pd.DataFrame.from_records(records)
    frame["value_raw"] = pd.Series(
        [record["value_raw"] for record in records], dtype=object, index=frame.index
    )
    return frame


# ------------------------------------------------------------- real fixture paths


class _FixtureResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}


class _FixtureSession:
    def __init__(self, content: bytes) -> None:
        self._response = _FixtureResponse(content)

    def post(self, url: str, **_: Any) -> _FixtureResponse:
        return self._response

    def get(self, url: str, **_: Any) -> _FixtureResponse:
        return self._response


def _run(tmp_path: Path, *, connector_factory, parser, spec, adapter):
    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    pipeline = IngestionPipeline(
        connector=connector_factory(RawStorage(tmp_path / "data/raw")),
        parser=parser,
        artifact_repository=ArtifactRepository(connection),
        parquet_storage=ParquetStorage(tmp_path / "data/bronze"),
    )
    result = pipeline.run(spec)[0]
    staging, _ = stage_ingestion_result(result, adapter=adapter)
    silver = materialize_fact_observation_snapshot(connection, staging)
    return connection, silver


def ingest_bddk_weekly(tmp_path: Path):
    """Real BDDK weekly fixture, all the way to a materialized Silver snapshot."""

    content = (FIXTURE_ROOT / "bddk_weekly/bddk_weekly_housing_loans.json").read_bytes()
    session = _FixtureSession(content)
    return _run(
        tmp_path,
        connector_factory=lambda storage: BddkWeeklyConnector(
            storage, session=session, max_attempts=1, clock=lambda: FETCHED_AT
        ),
        parser=BddkWeeklyParser(),
        spec=FetchSpec(
            source_id="bddk_weekly",
            dataset_id="bddk_weekly_housing_loans",
            locator="fixture://bddk_weekly",
            start_date=date(2026, 1, 2),
            end_date=date(2026, 6, 26),
            parameters={
                "dil": "tr",
                "id": "1.0.4",
                "parabirimi": "TRY",
                "sutun": "3",
                "tarafKodu": "10001",
                "kalem_id": "5690",
                "expected_measure_label": "a) Konut",
                "expected_currency": "TRY",
                "expected_column": "Toplam",
            },
            requested_at=REQUESTED_AT,
        ),
        adapter=bddk_weekly_to_staging,
    )


def ingest_evds_ktf12(tmp_path: Path, monkeypatch: Any):
    """Real EVDS KTF12 fixture, all the way to a materialized Silver snapshot."""

    monkeypatch.setenv(EVDS_API_KEY_ENV, "gold-test-only-key")
    content = (FIXTURE_ROOT / "evds/evds_ktf12_weekly.json").read_bytes()
    session = _FixtureSession(content)
    return _run(
        tmp_path,
        connector_factory=lambda storage: EvdsConnector(
            storage, session=session, max_attempts=1, clock=lambda: FETCHED_AT
        ),
        parser=EvdsParser(),
        spec=FetchSpec(
            source_id="evds",
            dataset_id="evds_housing_interest",
            locator="fixture://evds",
            start_date=date(2021, 1, 1),
            end_date=date(2026, 6, 30),
            parameters={"series": "TP.KTF12", "type": "json"},
            requested_at=REQUESTED_AT,
        ),
        adapter=evds_ktf12_to_staging,
    )


_SYNTHETIC_CPI_PAYLOAD = {
    "totalCount": 3,
    "items": [
        {"Tarih": "01-2026", "TP_FG_J0": "100.00", "UNIXTIME": {"$numberLong": "1767214800"}},
        {"Tarih": "02-2026", "TP_FG_J0": "110.00", "UNIXTIME": {"$numberLong": "1769893200"}},
        {"Tarih": "03-2026", "TP_FG_J0": "120.00", "UNIXTIME": {"$numberLong": "1772312400"}},
    ],
    "seriesNames": {"TP_FG_J0": "SYNTHETIC - not a real TCMB series name"},
}
"""SYNTHETIC. No official ``TP.FG.J0`` response has ever been captured; see docs/sources/evds.md."""


def ingest_evds_cpi(tmp_path: Path, monkeypatch: Any):
    """SYNTHETIC TÜFE payload through the real EVDS path, for the confidence-gate tests."""

    monkeypatch.setenv(EVDS_API_KEY_ENV, "gold-test-only-key")
    session = _FixtureSession(
        json.dumps(_SYNTHETIC_CPI_PAYLOAD, ensure_ascii=False).encode("utf-8")
    )
    return _run(
        tmp_path,
        connector_factory=lambda storage: EvdsConnector(
            storage, session=session, max_attempts=1, clock=lambda: FETCHED_AT
        ),
        parser=EvdsParser(),
        spec=FetchSpec(
            source_id="evds",
            dataset_id="evds_cpi",
            locator="synthetic://evds/TP.FG.J0",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            parameters={"series": "TP.FG.J0", "type": "json"},
            requested_at=REQUESTED_AT,
        ),
        adapter=evds_cpi_to_staging,
    )


__all__ = [
    "SYNTHETIC_SERIES",
    "add_synthetic_series",
    "ingest_bddk_weekly",
    "ingest_evds_cpi",
    "ingest_evds_ktf12",
    "staging_rows",
]
