"""Independent Silver V1 acceptance suite.

Written against `origin/feature/silver-v1 @ 4cba3bf` without reusing the branch's own test
assertions. Every scenario drives the real connector, the real parser, the real Silver adapter
and the real generic foundation over committed fixtures; nothing is stubbed except the HTTP
transport, which replays fixture bytes.

Tests here assert what the *data* must mean, not what the implementation currently does. A
failing test in this file is a reported acceptance finding, never a reason to change
production code. See docs/acceptance/silver-v1-acceptance-pack.md.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import pytest

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.connectors.bddk_monthly import BddkMonthlyConnector
from src.lakehouse.connectors.bddk_weekly import BddkWeeklyConnector
from src.lakehouse.connectors.evds import EVDS_API_KEY_ENV, EvdsConnector
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.parsers.bddk_monthly import (
    BDDK_MONTHLY_SCHEMA_VERSION,
    BddkMonthlyParser,
)
from src.lakehouse.parsers.bddk_weekly import BddkWeeklyParser
from src.lakehouse.parsers.evds import EvdsParser
from src.lakehouse.silver.adapters.bddk_monthly import bddk_monthly_to_staging
from src.lakehouse.silver.adapters.bddk_weekly import bddk_weekly_to_staging
from src.lakehouse.silver.adapters.evds import evds_kfe_to_staging, evds_ktf12_to_staging
from src.lakehouse.silver.foundation import (
    SilverValidationError,
    materialize_fact_observation_snapshot,
    silver_identity_for,
)
from src.lakehouse.silver.pipeline import stage_ingestion_result
from src.lakehouse.storage.parquet import ParquetStorage, read_identity
from src.lakehouse.storage.raw import RawStorage, sha256_bytes


FIXTURE_ROOT = Path("tests/fixtures/raw")
FETCHED_AT = datetime(2026, 9, 9, 8, tzinfo=timezone.utc)
REQUESTED_AT = datetime(2026, 9, 9, 7, tzinfo=timezone.utc)

# Türkiye has observed a fixed UTC+3 with no DST since 2016, so a fixed offset is exact for
# the 2021-2026 window this project ingests. Used only to decode EVDS UNIXTIME independently
# of the ambiguous `Tarih` string.
ISTANBUL = timezone(timedelta(hours=3))


# --------------------------------------------------------------------- harness


class _FixtureResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}


class _FixtureSession:
    """Replay committed fixture bytes; no socket is ever opened."""

    def __init__(self, fixture: Path) -> None:
        self._response = _FixtureResponse(fixture.read_bytes())

    def post(self, url: str, **_: Any) -> _FixtureResponse:
        return self._response

    def get(self, url: str, **_: Any) -> _FixtureResponse:
        return self._response


class _Ingested:
    """Everything one fixture produced, from RAW bytes through to the Silver frame."""

    def __init__(self, connection, result, bronze, identity, staging, silver) -> None:
        self.connection = connection
        self.result = result
        self.bronze = bronze
        self.identity = identity
        self.staging = staging
        self.silver = silver

    def row(self, observation_date: date) -> dict[str, Any]:
        matching = self.silver[self.silver["observation_date"] == observation_date]
        assert len(matching) == 1, f"expected exactly one row at {observation_date}"
        return matching.iloc[0].to_dict()


def _ingest(
    tmp_path: Path,
    *,
    fixture: Path,
    connector_factory: Callable[[RawStorage], Any],
    parser: Any,
    spec: FetchSpec,
    adapter: Callable[..., pd.DataFrame],
) -> _Ingested:
    raw_storage = RawStorage(tmp_path / "data/raw")
    bronze_storage = ParquetStorage(tmp_path / "data/bronze")
    connection = bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    pipeline = IngestionPipeline(
        connector=connector_factory(raw_storage),
        parser=parser,
        artifact_repository=ArtifactRepository(connection),
        parquet_storage=bronze_storage,
    )
    result = pipeline.run(spec)[0]
    assert result.asset.raw_path.read_bytes() == fixture.read_bytes()
    bronze = ParquetStorage.read(result.bronze_path)
    staging, identity = stage_ingestion_result(result, adapter=adapter)
    silver = materialize_fact_observation_snapshot(connection, staging)
    return _Ingested(connection, result, bronze, identity, staging, silver)


# ------------------------------------------------------------ source harnesses


def _bddk_monthly(tmp_path: Path) -> _Ingested:
    fixture = FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json"
    session = _FixtureSession(fixture)
    return _ingest(
        tmp_path,
        fixture=fixture,
        connector_factory=lambda storage: BddkMonthlyConnector(
            storage, session=session, max_attempts=1, clock=lambda: FETCHED_AT
        ),
        parser=BddkMonthlyParser(),
        spec=FetchSpec(
            source_id="bddk_monthly",
            dataset_id="bddk_monthly_housing_loans",
            locator="fixture://bddk_monthly",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 6, 1),
            parameters={
                "periyot": "1",
                "paraBirimi": "TL",
                "taraf": ["10001"],
                "kalemSutun": "1534?Toplam",
            },
            requested_at=REQUESTED_AT,
        ),
        adapter=bddk_monthly_to_staging,
    )


def _bddk_weekly(tmp_path: Path) -> _Ingested:
    fixture = FIXTURE_ROOT / "bddk_weekly/bddk_weekly_housing_loans.json"
    session = _FixtureSession(fixture)
    return _ingest(
        tmp_path,
        fixture=fixture,
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


def _evds(tmp_path: Path, monkeypatch: Any, *, fixture_name: str, series: str,
          dataset_id: str, adapter: Callable[..., pd.DataFrame]) -> _Ingested:
    fixture = FIXTURE_ROOT / f"evds/{fixture_name}"
    session = _FixtureSession(fixture)
    monkeypatch.setenv(EVDS_API_KEY_ENV, "acceptance-test-only-key")
    return _ingest(
        tmp_path,
        fixture=fixture,
        connector_factory=lambda storage: EvdsConnector(
            storage, session=session, max_attempts=1, clock=lambda: FETCHED_AT
        ),
        parser=EvdsParser(),
        spec=FetchSpec(
            source_id="evds",
            dataset_id=dataset_id,
            locator="fixture://evds",
            start_date=date(2021, 1, 1),
            end_date=date(2026, 6, 30),
            parameters={"series": series, "type": "json"},
            requested_at=REQUESTED_AT,
        ),
        adapter=adapter,
    )


def _evds_ktf12(tmp_path: Path, monkeypatch: Any) -> _Ingested:
    return _evds(
        tmp_path, monkeypatch,
        fixture_name="evds_ktf12_weekly.json",
        series="TP.KTF12",
        dataset_id="evds_housing_interest",
        adapter=evds_ktf12_to_staging,
    )


def _evds_kfe(tmp_path: Path, monkeypatch: Any) -> _Ingested:
    return _evds(
        tmp_path, monkeypatch,
        fixture_name="evds_kfe_monthly.json",
        series="TP.KFE.TR",
        dataset_id="evds_housing_price_index",
        adapter=evds_kfe_to_staging,
    )


def _unixtime_dates(bronze: pd.DataFrame) -> list[date]:
    """Decode the unambiguous EVDS UNIXTIME field into Istanbul calendar dates."""

    return [
        datetime.fromtimestamp(int(value), ISTANBUL).date()
        for value in bronze["unixtime"].tolist()
    ]


# ============================================================================
# A. BDDK Monthly
# ============================================================================


def test_a1_bddk_monthly_is_a_stock_in_million_lira(tmp_path: Path) -> None:
    """Scenario 1: monthly housing loans must reach Silver as a stock."""

    ingested = _bddk_monthly(tmp_path)
    try:
        assert set(ingested.silver["measure_type"]) == {"stock"}
        assert set(ingested.silver["unit"]) == {"TRY_mn"}
        assert set(ingested.silver["frequency"]) == {"monthly"}
    finally:
        ingested.connection.close()


def test_a2_bddk_monthly_values_are_neither_aggregated_nor_differenced(
    tmp_path: Path,
) -> None:
    """Scenario 3: a stock must arrive in Silver exactly as the source published it."""

    ingested = _bddk_monthly(tmp_path)
    try:
        bronze_values = [float(value) for value in ingested.bronze["value_raw"]]
        silver_values = [float(value) for value in ingested.silver["value"]]
        assert sorted(silver_values) == sorted(bronze_values)
        assert len(silver_values) == len(bronze_values)
        # A period-over-period difference would have destroyed the first observation.
        assert 276785.0 in silver_values  # 2021-01, the oldest fixture period
        assert 801438.0 in silver_values  # 2026-06, the newest fixture period
    finally:
        ingested.connection.close()


def test_a3_bddk_monthly_period_is_labelled_by_both_bounds(tmp_path: Path) -> None:
    """Scenario 4: a month must carry its first and last calendar day."""

    ingested = _bddk_monthly(tmp_path)
    try:
        row = ingested.row(date(2026, 6, 30))
        assert row["period_start"] == date(2026, 6, 1)
        assert row["period_end"] == date(2026, 6, 30)
        assert row["observation_date"] == row["period_end"]

        february = ingested.row(date(2021, 2, 28))
        assert february["period_start"] == date(2021, 2, 1)
        assert february["period_end"] == date(2021, 2, 28)
    finally:
        ingested.connection.close()


def test_a4_bddk_monthly_source_unit_conflict_must_not_pass_silently(
    tmp_path: Path,
) -> None:
    """Scenario 7: BDDK publishes some tables in bin TL and others in milyon TL.

    The Bronze row carries the unit BDDK itself embedded in the column name. If that unit
    disagrees with the catalog unit the values are off by a factor of 1000, so Silver must
    refuse rather than relabel. The Bronze frame here is the real fixture output with only
    ``unit_label`` rewritten in memory; no fixture file is modified.
    """

    ingested = _bddk_monthly(tmp_path)
    try:
        assert set(ingested.bronze["unit_label"]) == {"milyon TL"}, "fixture precondition"

        conflicting = ingested.bronze.copy()
        conflicting["unit_label"] = "bin TL"
        with pytest.raises(SilverValidationError):
            bddk_monthly_to_staging(conflicting, identity=ingested.identity)
    finally:
        ingested.connection.close()


def test_a5_bddk_monthly_entities_must_not_collapse_into_one_identity(
    tmp_path: Path,
) -> None:
    """Scenario 6: the sector total and a single bank group are different series.

    Bronze distinguishes them with ``entity_label``. If Silver drops that field and leaves
    ``entity_id`` NULL, two different populations end up sharing one identity and any later
    SUM double counts. Both frames below are the real fixture output with only
    ``entity_label`` and the artifact digest rewritten in memory.
    """

    ingested = _bddk_monthly(tmp_path)
    try:
        assert set(ingested.bronze["entity_label"]) == {"Sektör"}, "fixture precondition"

        other_digest = sha256_bytes(b"a-different-bank-group-artifact")
        other_bronze = ingested.bronze.copy()
        other_bronze["entity_label"] = "Mevduat Bankaları"
        other_bronze["artifact_sha256"] = other_digest
        other_identity = ingested.identity.__class__(
            source_id=ingested.identity.source_id,
            dataset_id=ingested.identity.dataset_id,
            artifact_sha256=other_digest,
            schema_version=ingested.identity.schema_version,
        )

        combined = pd.concat(
            [
                ingested.staging,
                bddk_monthly_to_staging(other_bronze, identity=other_identity),
            ],
            ignore_index=True,
        )
        silver = materialize_fact_observation_snapshot(ingested.connection, combined)

        june = silver[silver["observation_date"] == date(2026, 6, 30)]
        assert len(june) == 2, "precondition: two populations for the same period"
        assert june["entity_id"].nunique(dropna=False) == 2, (
            "sector total and bank group must remain distinguishable in Silver"
        )
    finally:
        ingested.connection.close()


# ============================================================================
# B. BDDK Weekly
# ============================================================================


def test_b1_bddk_weekly_is_a_stock_in_million_lira(tmp_path: Path) -> None:
    """Scenario 2."""

    ingested = _bddk_weekly(tmp_path)
    try:
        assert set(ingested.silver["measure_type"]) == {"stock"}
        assert set(ingested.silver["unit"]) == {"TRY_mn"}
        assert set(ingested.silver["frequency"]) == {"weekly"}
    finally:
        ingested.connection.close()


def test_b2_bddk_weekly_holiday_thursday_is_not_moved_to_friday(tmp_path: Path) -> None:
    """Scenario 5: the committed fixture contains 19.03.2026, a Thursday.

    The catalog declares ``week_anchor: friday``. Silver must publish the date the source
    actually reported; silently snapping it to Friday would invent an observation.
    """

    ingested = _bddk_weekly(tmp_path)
    try:
        assert "19.03.2026" in set(ingested.bronze["date_raw"]), "fixture precondition"
        thursday = date(2026, 3, 19)
        assert thursday.weekday() == 3, "fixture precondition: really a Thursday"

        dates = set(ingested.silver["observation_date"])
        assert thursday in dates
        assert date(2026, 3, 20) not in dates  # the Friday it must not have become
    finally:
        ingested.connection.close()


def test_b3_bddk_weekly_dates_and_values_survive_verbatim(tmp_path: Path) -> None:
    """Scenario 5 and 3 together: every published week reaches Silver unchanged."""

    ingested = _bddk_weekly(tmp_path)
    try:
        expected = {
            date(2026, 1, 2): 679216.118,
            date(2026, 3, 13): 731311.768,
            date(2026, 3, 19): 734860.422,
            date(2026, 3, 27): 740789.871,
            date(2026, 6, 26): 800464.007,
        }
        produced = {
            row["observation_date"]: row["value"]
            for _, row in ingested.silver.iterrows()
        }
        assert produced == expected
        # A weekly stock carries no period label in V1; it must not invent one.
        assert ingested.silver["period_start"].isna().all()
        assert ingested.silver["period_end"].isna().all()
    finally:
        ingested.connection.close()


# ============================================================================
# C. EVDS TP.KTF12  (interest rate)
# ============================================================================


def test_c1_ktf12_stays_a_rate_and_is_never_aggregated(tmp_path: Path, monkeypatch: Any) -> None:
    """Scenarios 8 and 9: an interest rate must not be summed or differenced."""

    ingested = _evds_ktf12(tmp_path, monkeypatch)
    try:
        assert set(ingested.silver["measure_type"]) == {"rate"}
        assert set(ingested.silver["unit"]) == {"pct"}
        assert set(ingested.silver["frequency"]) == {"weekly"}

        bronze_values = [float(value) for value in ingested.bronze["value_raw"]]
        silver_values = [float(value) for value in ingested.silver["value"]]
        assert sorted(silver_values) == sorted(bronze_values)
        assert 18.61 in silver_values and 41.45 in silver_values
    finally:
        ingested.connection.close()


def test_c2_ktf12_dates_agree_with_the_unambiguous_unixtime_field(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The EVDS ``Tarih`` string is ambiguous; ``UNIXTIME`` is not.

    The connector *sends* dates as dd-mm-yyyy while the Silver adapter *reads* the response
    as mm-dd-yyyy. This test decodes UNIXTIME independently and requires the two to agree,
    so a future keyed-endpoint response in the other order cannot pass unnoticed.
    """

    ingested = _evds_ktf12(tmp_path, monkeypatch)
    try:
        assert "unixtime" in ingested.bronze.columns, "Bronze precondition"
        expected = _unixtime_dates(ingested.bronze)
        produced = list(ingested.silver["observation_date"])
        assert produced == expected
    finally:
        ingested.connection.close()


def test_c3_ktf12_weekly_dates_match_the_catalog_friday_anchor(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The catalog declares ``week_anchor: friday`` for this series."""

    ingested = _evds_ktf12(tmp_path, monkeypatch)
    try:
        weekdays = {value.weekday() for value in ingested.silver["observation_date"]}
        assert weekdays == {4}, "every KTF12 observation must land on a Friday"
    finally:
        ingested.connection.close()


# ============================================================================
# D. EVDS TP.KFE.TR  (house price index)
# ============================================================================


def test_d1_kfe_stays_an_index_and_is_never_aggregated(tmp_path: Path, monkeypatch: Any) -> None:
    """Scenarios 8 and 9."""

    ingested = _evds_kfe(tmp_path, monkeypatch)
    try:
        assert set(ingested.silver["measure_type"]) == {"index"}
        assert set(ingested.silver["unit"]) == {"index"}
        assert set(ingested.silver["frequency"]) == {"monthly"}

        bronze_values = [float(value) for value in ingested.bronze["value_raw"]]
        silver_values = [float(value) for value in ingested.silver["value"]]
        assert sorted(silver_values) == sorted(bronze_values)
        assert 211.73 in silver_values
    finally:
        ingested.connection.close()


def test_d2_kfe_month_bounds_agree_with_unixtime(tmp_path: Path, monkeypatch: Any) -> None:
    """The monthly ``Tarih`` is ``MM-YYYY``; UNIXTIME points at the first of that month."""

    ingested = _evds_kfe(tmp_path, monkeypatch)
    try:
        expected_starts = _unixtime_dates(ingested.bronze)
        assert list(ingested.silver["period_start"]) == expected_starts
        for _, row in ingested.silver.iterrows():
            assert row["period_start"].day == 1
            assert row["observation_date"] == row["period_end"]
            assert row["period_end"] >= row["period_start"]
    finally:
        ingested.connection.close()


# ============================================================================
# E. NULL and numeric quality  (generic foundation)
# ============================================================================


def _staging_row(**overrides: Any) -> pd.DataFrame:
    base = {
        "series_id": "evds:TP.KTF12",
        "entity_id": None,
        "observation_date": date(2026, 1, 2),
        "period_start": None,
        "period_end": None,
        "value_raw": "18.61",
        "source_id": "evds",
        "dataset_id": "evds_housing_interest",
        "artifact_sha256": "a" * 64,
        "fetched_at": datetime(2026, 9, 10, tzinfo=timezone.utc),
        "schema_version": "evds_observations.v1",
        "vintage_id": None,
        "run_id": None,
        "source_warning": None,
    }
    base.update(overrides)
    return pd.DataFrame([base])


@pytest.fixture()
def connection(tmp_path: Path):
    connection = bootstrap_database(tmp_path / "lakehouse.duckdb")
    try:
        yield connection
    finally:
        connection.close()


def test_e1_source_null_stays_null_and_is_never_zero(connection) -> None:
    """Scenario 10: an absent observation must not become a measured zero."""

    silver = materialize_fact_observation_snapshot(connection, _staging_row(value_raw=None))
    assert silver.loc[0, "value"] is None or pd.isna(silver.loc[0, "value"])
    assert silver.loc[0, "value"] != 0
    assert silver.loc[0, "quality_flag"] == "missing_value"


@pytest.mark.parametrize(
    "value_raw",
    [float("nan"), float("inf"), float("-inf"), "not-a-number", "", "1,5"],
)
def test_e2_invalid_numbers_are_rejected(connection, value_raw: Any) -> None:
    """Scenario 11: NaN, Infinity and unparseable text must not silently become NULL."""

    with pytest.raises(SilverValidationError):
        materialize_fact_observation_snapshot(connection, _staging_row(value_raw=value_raw))


@pytest.mark.parametrize("observation_date", ["2026-01-02", 20260102, None])
def test_e3_invalid_dates_are_rejected(connection, observation_date: Any) -> None:
    """Scenario 11: a date must be a real canonical date, not a string or an integer."""

    with pytest.raises((SilverValidationError, TypeError)):
        materialize_fact_observation_snapshot(
            connection, _staging_row(observation_date=observation_date)
        )


def test_e4_naive_fetched_at_is_rejected(connection) -> None:
    with pytest.raises(SilverValidationError):
        materialize_fact_observation_snapshot(
            connection, _staging_row(fetched_at=datetime(2026, 9, 10))
        )


# ============================================================================
# F. Catalog gating
# ============================================================================


def test_f1_series_missing_from_the_catalog_is_refused(connection) -> None:
    """Scenario 12."""

    with pytest.raises(SilverValidationError):
        materialize_fact_observation_snapshot(
            connection, _staging_row(series_id="evds:TP.NOT.IN.CATALOG")
        )


def test_f2_unsafe_semantics_are_refused(connection) -> None:
    """Scenario 13: ``measure_type='unknown'`` must not be auto-accepted.

    The row is inserted straight into ``meta.series`` for this test database only; the
    Git-versioned catalog YAML is untouched.
    """

    connection.execute(
        """
        INSERT INTO meta.series (
            series_id, source_id, native_code, dataset_id, name_tr, description,
            frequency, unit, measure_type, semantic_confidence, semantic_source,
            status, catalog_content_sha256
        ) VALUES (
            'evds:TP.UNSAFE', 'evds', 'TP.UNSAFE', 'evds_housing_interest',
            'Test', 'Acceptance-only row', 'weekly', 'pct', 'unknown',
            'unknown', 'manual', 'active', ?
        )
        """,
        [sha256_bytes(b"acceptance-unknown-series")],
    )
    with pytest.raises(SilverValidationError):
        materialize_fact_observation_snapshot(
            connection, _staging_row(series_id="evds:TP.UNSAFE")
        )


def test_f3_catalog_dataset_mismatch_is_refused(connection) -> None:
    """A series may not be smuggled in under another dataset's identity."""

    with pytest.raises(SilverValidationError):
        materialize_fact_observation_snapshot(
            connection, _staging_row(dataset_id="evds_housing_price_index")
        )


# ============================================================================
# G. Duplicates and revisions
# ============================================================================


def test_g1_true_duplicates_inside_one_artifact_are_refused(connection) -> None:
    """Scenario 14."""

    duplicated = pd.concat([_staging_row(), _staging_row()], ignore_index=True)
    with pytest.raises(SilverValidationError):
        materialize_fact_observation_snapshot(connection, duplicated)


def test_g2_two_artifacts_for_one_period_stay_distinguishable(connection) -> None:
    """Scenario 15: a revision must be recognisable as a revision.

    Two artifacts reporting the same series and period is the normal revision case. Silver
    keeps both rows, which is correct for an append-only fact table, but a consumer must be
    able to tell which reading is newer without parsing a digest. ``vintage_id`` is the
    contract field for that.
    """

    first = _staging_row(value_raw="18.61", artifact_sha256="a" * 64)
    revised = _staging_row(value_raw="18.75", artifact_sha256="b" * 64)
    silver = materialize_fact_observation_snapshot(
        connection, pd.concat([first, revised], ignore_index=True)
    )

    assert len(silver) == 2, "both readings are retained"
    assert silver["vintage_id"].nunique(dropna=False) == 2, (
        "two readings of one period must carry distinguishable vintages"
    )


# ============================================================================
# H. Provenance and run compatibility
# ============================================================================


def test_h1_source_and_artifact_provenance_survive(tmp_path: Path) -> None:
    """Scenario 16."""

    ingested = _bddk_monthly(tmp_path)
    try:
        assert set(ingested.silver["source_id"]) == {"bddk_monthly"}
        assert set(ingested.silver["dataset_id"]) == {"bddk_monthly_housing_loans"}
        assert set(ingested.silver["artifact_sha256"]) == {ingested.result.asset.artifact_sha256}
        assert set(ingested.silver["schema_version"]) == {ingested.identity.schema_version}
        assert ingested.silver["fetched_at"].notna().all()
        # The Bronze schema identity must be the parser's real version, not a placeholder.
        assert ingested.identity.schema_version == BDDK_MONTHLY_SCHEMA_VERSION
    finally:
        ingested.connection.close()


def test_h2_run_id_reaches_silver_when_ingestion_records_one(tmp_path: Path) -> None:
    """Scenario 18: the run that produced the data must be nameable from a Silver row.

    ``origin/feature/lakehouse-ingestion-observability`` gives every ``IngestionResult`` a
    ``run_id``. Silver already reserves the staging column and validates it, so this test
    asks the remaining question: can an adapter actually carry that id through today?
    """

    ingested = _bddk_monthly(tmp_path)
    try:
        assert hasattr(ingested.result, "run_id"), (
            "IngestionResult on this branch exposes no run_id to hand to Silver"
        )
        assert ingested.silver["run_id"].notna().all()
    finally:
        ingested.connection.close()


def test_h3_generic_foundation_already_carries_a_run_id_when_given_one(connection) -> None:
    """The Silver side of the run_id contract is ready; only the adapters are not.

    This separates two questions that would otherwise be confused: the generic foundation
    accepts, validates and publishes a run_id today, so wiring observability in is an
    adapter-signature change, not a Silver redesign.
    """

    run_id = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    silver = materialize_fact_observation_snapshot(connection, _staging_row(run_id=run_id))
    assert silver.loc[0, "run_id"] == run_id


def test_h4_a_malformed_run_id_is_refused(connection) -> None:
    """A run reference that is not a UUID must not reach Silver."""

    with pytest.raises(ValueError):
        materialize_fact_observation_snapshot(connection, _staging_row(run_id="not-a-uuid"))


# ============================================================================
# I. Parser warnings
# ============================================================================


def test_i1_a_warned_batch_must_not_be_published_as_ok(tmp_path: Path) -> None:
    """Scenario 17.

    The committed BDDK monthly fixture makes the parser raise two real warnings: a grid
    ``defaultValue`` of '0' that must not be read as a measured zero, and a period-count
    mismatch. Silver must not present those rows as unqualified ``ok``.
    """

    ingested = _bddk_monthly(tmp_path)
    try:
        assert ingested.result.parsed_batch.warnings, "fixture precondition: parser warned"
        assert set(ingested.silver["quality_flag"]) != {"ok"}, (
            "parser warnings vanished: every Silver row claims to be clean"
        )
    finally:
        ingested.connection.close()


def test_i2_warning_text_is_reachable_from_a_silver_row(tmp_path: Path) -> None:
    """A flag with no text cannot be acted on; the warning itself must remain reachable."""

    ingested = _bddk_monthly(tmp_path)
    try:
        assert ingested.result.parsed_batch.warnings, "fixture precondition"
        assert ingested.staging["source_warning"].notna().any(), (
            "no adapter propagates ParsedBatch.warnings into the Silver staging contract"
        )
    finally:
        ingested.connection.close()


# ============================================================================
# J. Representation identity
# ============================================================================


def test_j1_silver_parquet_identity_is_distinguishable_from_bronze(tmp_path: Path) -> None:
    """Scenario 19.

    Bronze and Silver are different representations of the same artifact. Their Parquet
    files must be tellable apart from the file itself, not only from the directory they
    happen to sit in, or a moved or copied file becomes unattributable.
    """

    ingested = _bddk_monthly(tmp_path)
    try:
        silver_path = ParquetStorage(tmp_path / "data/silver/fact_observation").write_frame(
            ingested.silver, identity=silver_identity_for(ingested.identity)
        )
        bronze_identity = read_identity(ingested.result.bronze_path)
        silver_identity = read_identity(silver_path)
        assert silver_identity != bronze_identity, (
            "the Silver Parquet carries the Bronze schema identity verbatim"
        )
    finally:
        ingested.connection.close()


# ============================================================================
# K. Coexistence of all four series
# ============================================================================


def test_k1_all_four_series_coexist_without_losing_their_meaning(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Scenario 20: one canonical table, four different economic meanings."""

    parts = [
        _bddk_monthly(tmp_path / "m"),
        _bddk_weekly(tmp_path / "w"),
        _evds_ktf12(tmp_path / "k", monkeypatch),
        _evds_kfe(tmp_path / "f", monkeypatch),
    ]
    connection = bootstrap_database(tmp_path / "combined.duckdb")
    try:
        combined = pd.concat([part.staging for part in parts], ignore_index=True)
        silver = materialize_fact_observation_snapshot(connection, combined)

        semantics = {
            row["series_id"]: (row["frequency"], row["unit"], row["measure_type"])
            for _, row in silver.iterrows()
        }
        assert semantics == {
            "bddk_monthly:1534_Toplam": ("monthly", "TRY_mn", "stock"),
            "bddk_weekly:5690_3": ("weekly", "TRY_mn", "stock"),
            "evds:TP.KTF12": ("weekly", "pct", "rate"),
            "evds:TP.KFE.TR": ("monthly", "index", "index"),
        }
        assert len(silver) == sum(len(part.silver) for part in parts)
        assert silver["observation_date"].notna().all()
    finally:
        connection.close()
        for part in parts:
            part.connection.close()
