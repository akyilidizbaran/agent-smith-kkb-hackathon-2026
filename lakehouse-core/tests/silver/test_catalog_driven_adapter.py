"""The catalog-driven Silver adapter: same mapping, no per-series function.

The central test here is equivalence. Replacing five hand-written adapters with one
catalog-driven path is only safe if the new path produces exactly what the reviewed ones
produced for the series they cover — not "equivalent modulo dtype", the same frame. Everything
else in this file is about what the new path must refuse.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.parsers.base import BaseParser
from src.lakehouse.parsers.bddk_finturk import BddkFinTurkParser
from src.lakehouse.parsers.bddk_monthly import BddkMonthlyParser
from src.lakehouse.parsers.bddk_weekly import BddkWeeklyParser
from src.lakehouse.parsers.evds import EvdsParser
from src.lakehouse.silver.adapters.bddk_monthly import bddk_monthly_to_staging
from src.lakehouse.silver.adapters.bddk_weekly import bddk_weekly_to_staging
from src.lakehouse.silver.adapters.catalog_driven import (
    SeriesSemantics,
    catalog_driven_to_staging,
    load_series_semantics,
)
from src.lakehouse.silver.adapters.evds import (
    evds_kfe_to_staging,
    evds_ktf12_to_staging,
)
from src.lakehouse.silver.foundation import SilverValidationError
from src.lakehouse.storage.parquet import ParquetIdentity, ParquetStorage, read_identity
from src.lakehouse.storage.raw import RawStorage


FIXTURE_ROOT = Path("tests/fixtures/raw")
FETCHED_AT = datetime(2026, 9, 9, 8, tzinfo=timezone.utc)


def _bronze(
    tmp_path: Path,
    *,
    fixture: Path,
    source_id: str,
    dataset_id: str,
    parser: BaseParser,
    metadata: dict[str, object],
) -> tuple[pd.DataFrame, ParquetIdentity]:
    asset = RawStorage(tmp_path / "data/raw").store(
        source_id=source_id,
        dataset_id=dataset_id,
        locator=f"fixture://{fixture.name}",
        content=fixture.read_bytes(),
        media_type="application/json",
        fetched_at=FETCHED_AT,
        extension="json",
        metadata=metadata,
    )
    path = ParquetStorage(tmp_path / "data/bronze").write(parser.parse(asset))
    return ParquetStorage.read(path), read_identity(path)


@pytest.fixture(scope="module")
def semantics(tmp_path_factory: pytest.TempPathFactory) -> dict[str, SeriesSemantics]:
    """The real repository catalog, loaded the way production loads it."""

    database = tmp_path_factory.mktemp("catalog") / "lakehouse.duckdb"
    connection = bootstrap_database(database)
    try:
        return load_series_semantics(connection)
    finally:
        connection.close()


_CASES = {
    "bddk_monthly": dict(
        fixture=FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json",
        source_id="bddk_monthly",
        dataset_id="bddk_monthly_housing_loans",
        parser=BddkMonthlyParser,
        metadata={"requested_kalem_sutun": ["1534?Toplam"]},
        named=bddk_monthly_to_staging,
    ),
    "bddk_weekly": dict(
        fixture=FIXTURE_ROOT / "bddk_weekly/bddk_weekly_housing_loans.json",
        source_id="bddk_weekly",
        dataset_id="bddk_weekly_housing_loans",
        parser=BddkWeeklyParser,
        metadata={
            "requested_chart_id": "1.0.4",
            "requested_kalem_id": "5690",
            "expected_measure_label": "a) Konut",
            "expected_currency": "TRY",
            "expected_column": "Toplam",
            "requested_column": "3",
            "requested_taraf": "10001",
        },
        named=bddk_weekly_to_staging,
    ),
    "evds_weekly": dict(
        fixture=FIXTURE_ROOT / "evds/evds_ktf12_weekly.json",
        source_id="evds",
        dataset_id="evds_housing_interest",
        parser=EvdsParser,
        metadata={"requested_series": ["TP.KTF12"]},
        named=evds_ktf12_to_staging,
    ),
    "evds_monthly": dict(
        fixture=FIXTURE_ROOT / "evds/evds_kfe_monthly.json",
        source_id="evds",
        dataset_id="evds_housing_price_index",
        parser=EvdsParser,
        metadata={"requested_series": ["TP.KFE.TR"]},
        named=evds_kfe_to_staging,
    ),
}


@pytest.mark.parametrize("case_name", sorted(_CASES))
def test_catalog_driven_reproduces_every_reviewed_adapter(
    case_name: str, tmp_path: Path, semantics: dict[str, SeriesSemantics]
) -> None:
    """The generic path must be indistinguishable from the reviewed one it replaces.

    If this ever fails, the catalog-driven path changed a mapping that was verified against a
    real source response — that is a regression in meaning, not a refactor.
    """

    case = _CASES[case_name]
    frame, identity = _bronze(
        tmp_path,
        fixture=case["fixture"],
        source_id=case["source_id"],
        dataset_id=case["dataset_id"],
        parser=case["parser"](),
        metadata=case["metadata"],
    )

    expected = case["named"](frame, identity=identity, run_id="r-1", vintage_id="v-1")
    produced = catalog_driven_to_staging(
        frame, identity=identity, semantics=semantics, run_id="r-1", vintage_id="v-1"
    )

    pd.testing.assert_frame_equal(produced, expected)


def _finturk_bronze(tmp_path: Path) -> tuple[pd.DataFrame, ParquetIdentity]:
    return _bronze(
        tmp_path,
        fixture=FIXTURE_ROOT / "bddk_finturk/bddk_finturk_yalova_2025_9.json",
        source_id="bddk_finturk",
        dataset_id="bddk_finturk_yalova_housing_loans",
        parser=BddkFinTurkParser(),
        metadata={"requested_sehir": "YALOVA"},
    )


def _finturk_semantics(unit: str | None = "TRY_th") -> dict[str, SeriesSemantics]:
    return {
        "bddk_finturk:YALOVA_KonutKredisi": SeriesSemantics(
            series_id="bddk_finturk:YALOVA_KonutKredisi",
            source_id="bddk_finturk",
            frequency="quarterly",
            unit=unit,
            measure_type="stock",
            status="active",
        )
    }


def test_finturk_quarter_end_month_becomes_the_whole_quarter(tmp_path: Path) -> None:
    """September is not a month here; it is the close of the third quarter."""

    frame, identity = _finturk_bronze(tmp_path)
    housing = frame.loc[frame["series_id"] == "bddk_finturk:YALOVA_KonutKredisi"]

    staging = catalog_driven_to_staging(
        housing, identity=identity, semantics=_finturk_semantics()
    )

    assert list(staging["period_start"]) == [date(2025, 7, 1)]
    assert list(staging["period_end"]) == [date(2025, 9, 30)]
    assert list(staging["observation_date"]) == [date(2025, 9, 30)]
    assert list(staging["value_raw"]) == [2104493]


def test_finturk_party_reaches_the_shared_bddk_entity_vocabulary(tmp_path: Path) -> None:
    """``Sektör`` must be the same entity here as in the monthly BDDK source, not a new one."""

    frame, identity = _finturk_bronze(tmp_path)
    housing = frame.loc[frame["series_id"] == "bddk_finturk:YALOVA_KonutKredisi"]

    staging = catalog_driven_to_staging(
        housing, identity=identity, semantics=_finturk_semantics()
    )

    assert list(staging["entity_id"]) == ["bddk:10001"]


def test_finturk_non_quarter_month_is_refused(tmp_path: Path) -> None:
    frame, identity = _finturk_bronze(tmp_path)
    housing = frame.loc[frame["series_id"] == "bddk_finturk:YALOVA_KonutKredisi"].copy()
    housing["month_raw"] = 8

    with pytest.raises(SilverValidationError, match="not a quarter end"):
        catalog_driven_to_staging(
            housing, identity=identity, semantics=_finturk_semantics()
        )


def test_finturk_reaches_silver_under_the_real_catalog(
    tmp_path: Path, semantics: dict[str, SeriesSemantics]
) -> None:
    """The third BDDK source is publishable once its unit is evidenced, not before.

    The response body states no unit, so these series sat at ``unit: null`` and could not be
    published. The unit is now established from the source's own table label and an
    81-province cross-check against the monthly bulletin (docs/sources/bddk_finturk.md), which
    is what moves them into Silver. The assertion is on the catalog value rather than on the
    prose, so weakening the evidence without weakening the claim is not possible here.
    """

    series = semantics["bddk_finturk:YALOVA_KonutKredisi"]
    assert series.unpublishable_reason is None
    assert series.unit == "TRY_th"

    frame, identity = _finturk_bronze(tmp_path)
    housing = frame.loc[frame["series_id"] == "bddk_finturk:YALOVA_KonutKredisi"]
    staging = catalog_driven_to_staging(housing, identity=identity, semantics=semantics)

    assert list(staging["series_id"]) == ["bddk_finturk:YALOVA_KonutKredisi"]
    assert list(staging["observation_date"]) == [date(2025, 9, 30)]


def test_the_committed_page_evidence_still_says_what_the_catalog_claims() -> None:
    """The unit is a claim about the source, so its evidence is committed and checked.

    ``TRY_th`` for these series rests on BDDK labelling ``tabloNo=3`` as *(Bin TL)* on its own
    page. That capture is a fixture, and this test fails if someone edits the fixture to say
    something else while leaving the catalog claiming a verified unit.
    """

    evidence = Path("tests/fixtures/pages/bddk_finturk_table_units.html").read_text(
        encoding="utf-8"
    )

    assert '<option value="3">Bireysel Bankacılık (Bin TL)</option>' in evidence


def test_uncatalogued_series_never_reaches_silver(
    tmp_path: Path, semantics: dict[str, SeriesSemantics]
) -> None:
    """One FinTürk response carries eight measures; the catalog registers one of them."""

    frame, identity = _finturk_bronze(tmp_path)
    other = frame.loc[frame["series_id"] == "bddk_finturk:YALOVA_TasitKredisi"]
    assert not other.empty, "fixture precondition"

    with pytest.raises(SilverValidationError, match="not in meta.series"):
        catalog_driven_to_staging(other, identity=identity, semantics=semantics)


def test_unknown_measure_type_is_refused(tmp_path: Path) -> None:
    """A source-derived series with no reviewed meaning must not look like a reviewed one."""

    frame, identity = _finturk_bronze(tmp_path)
    housing = frame.loc[frame["series_id"] == "bddk_finturk:YALOVA_KonutKredisi"]
    unknown = {
        "bddk_finturk:YALOVA_KonutKredisi": SeriesSemantics(
            series_id="bddk_finturk:YALOVA_KonutKredisi",
            source_id="bddk_finturk",
            frequency="quarterly",
            unit="TRY_th",
            measure_type="unknown",
            status="active",
        )
    }

    with pytest.raises(SilverValidationError, match="measure_type is unknown"):
        catalog_driven_to_staging(housing, identity=identity, semantics=unknown)


def test_source_unit_label_conflicting_with_the_catalog_is_refused(
    tmp_path: Path, semantics: dict[str, SeriesSemantics]
) -> None:
    """The BDDK monthly unit cross-check survives the move to a catalog-driven path."""

    frame, identity = _bronze(
        tmp_path,
        fixture=FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json",
        source_id="bddk_monthly",
        dataset_id="bddk_monthly_housing_loans",
        parser=BddkMonthlyParser(),
        metadata={"requested_kalem_sutun": ["1534?Toplam"]},
    )
    relabelled = frame.assign(unit_label="bin TL")

    with pytest.raises(SilverValidationError, match="declares 'TRY_mn'"):
        catalog_driven_to_staging(relabelled, identity=identity, semantics=semantics)


def test_unreviewed_source_unit_label_is_refused(
    tmp_path: Path, semantics: dict[str, SeriesSemantics]
) -> None:
    frame, identity = _bronze(
        tmp_path,
        fixture=FIXTURE_ROOT / "bddk_monthly/bddk_monthly_housing_loans.json",
        source_id="bddk_monthly",
        dataset_id="bddk_monthly_housing_loans",
        parser=BddkMonthlyParser(),
        metadata={"requested_kalem_sutun": ["1534?Toplam"]},
    )
    relabelled = frame.assign(unit_label="katrilyon TL")

    with pytest.raises(SilverValidationError, match="no reviewed catalog mapping"):
        catalog_driven_to_staging(relabelled, identity=identity, semantics=semantics)


def test_evds_frequency_without_a_verified_date_policy_is_refused(
    tmp_path: Path,
) -> None:
    """EVDS has 233 quarterly series catalogued and no verified quarterly response shape."""

    frame, identity = _bronze(
        tmp_path,
        fixture=FIXTURE_ROOT / "evds/evds_ktf12_weekly.json",
        source_id="evds",
        dataset_id="evds_housing_interest",
        parser=EvdsParser(),
        metadata={"requested_series": ["TP.KTF12"]},
    )
    quarterly = {
        "evds:TP.KTF12": SeriesSemantics(
            series_id="evds:TP.KTF12",
            source_id="evds",
            frequency="quarterly",
            unit="pct",
            measure_type="rate",
            status="active",
        )
    }

    with pytest.raises(SilverValidationError, match="no reviewed EVDS date policy"):
        catalog_driven_to_staging(frame, identity=identity, semantics=quarterly)


def test_series_from_another_source_is_refused(
    tmp_path: Path, semantics: dict[str, SeriesSemantics]
) -> None:
    frame, identity = _bronze(
        tmp_path,
        fixture=FIXTURE_ROOT / "evds/evds_ktf12_weekly.json",
        source_id="evds",
        dataset_id="evds_housing_interest",
        parser=EvdsParser(),
        metadata={"requested_series": ["TP.KTF12"]},
    )
    mislabelled = frame.assign(series_id="bddk_weekly:5690_3")

    with pytest.raises(SilverValidationError, match="belongs to source"):
        catalog_driven_to_staging(mislabelled, identity=identity, semantics=semantics)


_LIVE_KEYED_CASES = {
    "weekly": dict(
        fixture=FIXTURE_ROOT / "evds/evds_ktf12_weekly_live_keyed.json",
        dataset_id="evds_housing_interest",
        series="TP.KTF12",
        expected=[
            date(2021, 1, 1),
            date(2021, 1, 8),
            date(2021, 1, 15),
            date(2021, 1, 22),
            date(2021, 1, 29),
        ],
    ),
    "monthly": dict(
        fixture=FIXTURE_ROOT / "evds/evds_kfe_monthly_live_keyed.json",
        dataset_id="evds_housing_price_index",
        series="TP.KFE.TR",
        expected=[
            date(2021, 1, 31),
            date(2021, 2, 28),
            date(2021, 3, 31),
            date(2021, 4, 30),
            date(2021, 5, 31),
        ],
    ),
}


@pytest.mark.parametrize("case_name", sorted(_LIVE_KEYED_CASES))
def test_the_live_keyed_endpoint_response_maps_to_the_right_calendar_dates(
    case_name: str, tmp_path: Path, semantics: dict[str, SeriesSemantics]
) -> None:
    """Captured from the documented, key-authenticated EVDS endpoint on 2026-09-11.

    Until a key existed, every EVDS fixture came from the web application's own endpoint, and
    ``tests/fixtures/raw/evds/README.md`` said in as many words that passing tests proved
    parser behaviour against those captures rather than against the official endpoint, asking
    for a re-capture once a key was available. The re-capture found two differences, and only
    one of them was loud:

    * monthly ``Tarih`` is ``2021-1`` live and ``01-2021`` in the capture — the old mapping
      rejected it outright;
    * weekly ``Tarih`` is ``08-01-2021`` live and ``01-08-2021`` in the capture — the old
      mapping accepted it as 1 August 2021 and said nothing.

    The expected dates below are the Fridays that ``TP.KTF12`` is actually published on, and
    the month ends ``TP.KFE.TR`` is actually published for. A mapping that reads the field
    order instead of ``UNIXTIME`` cannot produce them.
    """

    case = _LIVE_KEYED_CASES[case_name]
    frame, identity = _bronze(
        tmp_path,
        fixture=case["fixture"],
        source_id="evds",
        dataset_id=case["dataset_id"],
        parser=EvdsParser(),
        metadata={"requested_series": [case["series"]]},
    )

    staging = catalog_driven_to_staging(frame, identity=identity, semantics=semantics)

    assert list(staging["observation_date"]) == case["expected"]
