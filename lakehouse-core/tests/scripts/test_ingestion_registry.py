"""The catalog row to wire request mapping the manual ingestion runner uses.

``scripts/`` is a manual utility area rather than production code, but this particular file
decides what is actually asked of each source, and a mistake in it does not fail — it produces
a real response under a series identity nobody catalogued. That failure mode is invisible in
the runner's own output, which is why it is worth a test.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from ingestion_registry import CONNECTOR_REGISTRY, SeriesRow  # noqa: E402

from src.lakehouse.catalog.series import load_catalog_files  # noqa: E402


REPO_CATALOG = Path("catalog/series")


def _row(series_id: str) -> SeriesRow:
    record = {r.series_id: r for r in load_catalog_files(REPO_CATALOG)}[series_id]
    return SeriesRow(
        series_id=record.series_id,
        source_id=record.source_id,
        native_code=record.native_code,
        dataset_id=record.dataset_id,
        name_tr=record.name_tr,
    )


def test_monthly_request_uses_the_catalog_address_exactly_once() -> None:
    """``native_code`` already is the full ``item?column`` address for this series.

    Appending a column to an address that already names one asked the endpoint for
    ``1534?Toplam?Toplam``. BDDK answered with the right numbers, so nothing looked wrong, but
    the parser derives ``series_id`` from the request and produced
    ``bddk_monthly:1534_Toplam_Toplam`` — a series the catalog does not define, which is then
    correctly refused at the Silver boundary. The whole chain reported success and the series
    was simply missing.
    """

    row = _row("bddk_monthly:1534_Toplam")
    assert "?" in row.native_code, "catalog precondition: native_code is item?column"

    spec = CONNECTOR_REGISTRY["bddk_monthly"].build_spec(
        row, date(2021, 1, 1), date(2026, 6, 30)
    )

    assert spec.parameters["kalemSutun"] == row.native_code
    assert spec.parameters["kalemSutun"].count("?") == 1


def test_monthly_request_still_defaults_the_column_for_a_bare_item_id() -> None:
    """A future catalog row that names only the item keeps the source-wide default."""

    row = SeriesRow(
        series_id="bddk_monthly:9999_Toplam",
        source_id="bddk_monthly",
        native_code="9999",
        dataset_id="bddk_monthly_whatever",
        name_tr="hypothetical",
    )

    spec = CONNECTOR_REGISTRY["bddk_monthly"].build_spec(
        row, date(2021, 1, 1), date(2026, 6, 30)
    )

    assert spec.parameters["kalemSutun"] == "9999?Toplam"


@pytest.mark.parametrize("series_id", ["bddk_finturk:YALOVA_KonutKredisi", "evds:TP.KTF12"])
def test_every_registered_source_builds_a_spec_for_its_own_catalog_row(
    series_id: str,
) -> None:
    row = _row(series_id)

    spec = CONNECTOR_REGISTRY[row.source_id].build_spec(
        row, date(2025, 1, 1), date(2025, 12, 31)
    )

    assert spec.source_id == row.source_id
    assert spec.dataset_id == row.dataset_id


def test_monthly_request_for_an_older_schema_id_carries_the_catalogued_series_key() -> None:
    """BDDK re-keys an item when its schema changes; the older id still answers for the older months.

    Measured 21 Sept 2026: 63 of the 70 monthly series whose loaded data starts after 2021-01 have
    their earlier months under an older id (``1842?Toplam`` was ``1626?Toplam`` until 2021-10). The
    request goes out with the OLD id; the response must land on the CATALOGUED series, so the row
    carries the publish key and the spec forwards it — as metadata, never as a wire field.
    """

    current = _row("bddk_monthly:1534_Toplam")
    old = SeriesRow(series_id=current.series_id, source_id=current.source_id, native_code="288?Toplam",
                    dataset_id=current.dataset_id, name_tr=current.name_tr, series_key="1534_Toplam")

    spec = CONNECTOR_REGISTRY["bddk_monthly"].build_spec(old, date(2021, 1, 1), date(2021, 10, 31))

    assert spec.parameters["kalemSutun"] == "288?Toplam"
    assert spec.parameters["series_key"] == "1534_Toplam"
    plain = CONNECTOR_REGISTRY["bddk_monthly"].build_spec(current, date(2021, 1, 1), date(2021, 10, 31))
    assert "series_key" not in plain.parameters, "no override → nothing extra in the spec"
