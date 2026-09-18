"""Catalog-driven FetchSpec construction: one place that knows how to turn a
``meta.series`` row into a real fetch request, per source.

Design principle: everything derivable from the semantic catalog (``native_code``,
``dataset_id``, the column encoded in ``series_id``) IS derived here, generically.
Nothing about "which series exist" is hardcoded — that list comes from
``meta.series`` at run time (see ``run_catalog_ingestion.py``).

What is NOT derivable, and why, is documented per source below. This is not an
implementation gap to be closed later by more code: for BDDK weekly specifically,
the source addresses a series by a *positional* chart id that carries no stable
meaning on its own (see ``docs/sources/bddk_weekly.md``, "Chart-id drift guard").
A human verifying that position against the live bulletin and recording what it
is expected to mean is the guardrail, not a placeholder for automation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from src.lakehouse.connectors.base import BaseConnector
from src.lakehouse.connectors.bddk_finturk import (
    BDDK_FINTURK_TABLO_BIREYSEL,
    BddkFinTurkConnector,
)
from src.lakehouse.connectors.bddk_monthly import BddkMonthlyConnector
from src.lakehouse.connectors.bddk_weekly import (
    BDDK_WEEKLY_SERIES_PATH,
    BddkWeeklyConnector,
)
from src.lakehouse.connectors.evds import EvdsConnector
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.parsers.base import BaseParser
from src.lakehouse.parsers.bddk_finturk import BddkFinTurkParser
from src.lakehouse.parsers.bddk_monthly import BddkMonthlyParser
from src.lakehouse.parsers.bddk_weekly import BddkWeeklyParser
from src.lakehouse.parsers.evds import EvdsParser


@dataclass(frozen=True)
class SeriesRow:
    """The subset of a ``meta.series`` row this module needs. Built from a real
    catalog row by the caller — never invented here."""

    series_id: str
    source_id: str
    native_code: str
    dataset_id: str
    name_tr: str


@dataclass(frozen=True)
class ConnectorBinding:
    """What it takes to run one source: its connector/parser types, and the
    function that turns a catalog row into a real ``FetchSpec`` for it."""

    connector_cls: type[BaseConnector]
    parser_cls: type[BaseParser]
    build_spec: Callable[[SeriesRow, date, date], FetchSpec]


# --------------------------------------------------------------------------- EVDS
# Fully derivable: EVDS addresses a series by exactly the code the catalog
# already stores as native_code (e.g. "TP.KTF12"). No source-specific wire fact
# exists outside the catalog for this connector.

def _evds_spec(row: SeriesRow, start: date, end: date) -> FetchSpec:
    return FetchSpec(
        source_id=row.source_id,
        dataset_id=row.dataset_id,
        locator="evds",
        start_date=start,
        end_date=end,
        parameters={"series": row.native_code},
    )


# --------------------------------------------------------------------- BDDK Aylık
# Fully derivable: the monthly endpoint addresses a series by its stable native
# item id (docs/sources/bddk_monthly.md: "Item address: stable item id 1534"),
# not a positional one. taraf/paraBirimi/periyot/gosterimTuru are constant across
# every series this connector has ever verified.
#
# kalemSutun is "<item>?<column>", and the catalog's native_code already carries
# that whole address for the one catalogued series ("1534?Toplam"). Appending
# "?Toplam" unconditionally produced "1534?Toplam?Toplam" on the wire; the endpoint
# answered with correct values, but the parser derived series_id from the request
# and returned "bddk_monthly:1534_Toplam_Toplam", which matches no catalog row. The
# series therefore parsed, reached Bronze, and then silently failed to publish — the
# flagship monthly series was absent from Silver while every log line said success.
# The column is appended only when native_code does not already name one.

def _bddk_monthly_spec(row: SeriesRow, start: date, end: date) -> FetchSpec:
    kalem_sutun = (
        row.native_code if "?" in row.native_code else f"{row.native_code}?Toplam"
    )
    return FetchSpec(
        source_id=row.source_id,
        dataset_id=row.dataset_id,
        locator="https://www.bddk.org.tr/BultenAylik/tr/Home/BasitRaporGetir",
        start_date=start,
        end_date=end,
        parameters={
            "periyot": "1",
            "paraBirimi": "TL",
            "taraf": ["10001"],
            "kalemSutun": kalem_sutun,
            "gosterimTuru": "grid",
        },
    )


# ------------------------------------------------------------------- BDDK Haftalık
# Partially derivable. kalem_id = native_code (stable, from the catalog). The
# column is encoded in series_id's "<native_code>_<sutun>" suffix (e.g. "5690_3"),
# so sutun and expected_column are derived from that, not guessed — see
# docs/sources/bddk_weekly.md's sutun->column table (3 -> Toplam is the only one
# this project has verified; 1/2 are documented as unverified).
#
# What genuinely cannot come from the catalog: the endpoint addresses a series by
# a *positional* chart id ("1.0.4"), which carries no meaning of its own and can
# silently point at a different bulletin line if BDDK reorders it. This is why
# the connector requires expected_measure_label as an independent check. Both
# facts are anchored to one verified observation of the live bulletin, recorded
# here with that provenance — not derived, because there is nothing in the
# catalog schema they could be derived from.

_WEEKLY_SUTUN_COLUMN = {"3": "Toplam"}  # only "3" (Toplam) verified live; see docs/sources/bddk_weekly.md

_WEEKLY_VERIFIED_POSITIONS: dict[str, dict[str, str]] = {
    # series_id -> {chart id, measure label} as observed live on 2026-09-09.
    # Re-verify against https://www.bddk.org.tr/BultenHaftalik/tr/Gelismis if
    # BDDK visibly reorders the bulletin (docs/sources/bddk_weekly.md, "Chart-id
    # drift guard").
    "bddk_weekly:5690_3": {"id": "1.0.4", "expected_measure_label": "a) Konut"},
}


def _bddk_weekly_spec(row: SeriesRow, start: date, end: date) -> FetchSpec:
    try:
        _, sutun = row.native_code, row.series_id.rsplit("_", 1)[1]
    except IndexError as exc:
        raise ValueError(
            f"{row.series_id}: bddk_weekly series_id must end in '_<sutun>'"
        ) from exc
    expected_column = _WEEKLY_SUTUN_COLUMN.get(sutun)
    if expected_column is None:
        raise ValueError(
            f"{row.series_id}: sutun={sutun!r} has no verified column mapping "
            f"(only {sorted(_WEEKLY_SUTUN_COLUMN)} are verified); add it to "
            "_WEEKLY_SUTUN_COLUMN only after confirming it live."
        )
    position = _WEEKLY_VERIFIED_POSITIONS.get(row.series_id)
    if position is None:
        raise ValueError(
            f"{row.series_id}: no verified chart position recorded in "
            "_WEEKLY_VERIFIED_POSITIONS. The weekly endpoint addresses series "
            "positionally; this project requires observing the live bulletin "
            "once before a series can be fetched. See docs/sources/bddk_weekly.md."
        )

    return FetchSpec(
        source_id=row.source_id,
        dataset_id=row.dataset_id,
        locator=f"https://www.bddk.org.tr{BDDK_WEEKLY_SERIES_PATH}",
        start_date=start,
        end_date=end,
        parameters={
            "id": position["id"],
            "kalem_id": row.native_code,
            "expected_measure_label": position["expected_measure_label"],
            "expected_currency": "TRY",
            "expected_column": expected_column,
            "parabirimi": "TRY",
            "sutun": sutun,
            "tarafKodu": "10001",
        },
    )


# --------------------------------------------------------------------- BDDK FinTürk
# Partially derivable. Existing table-3 entries use ``<SEHIR>_<ColumnSlug>`` and
# therefore retain their historical one-province request. The breadth catalog uses
# ``<tabloNo>|<SEHIR>`` (the city is retained for provenance, while the request uses
# the endpoint's efficient ``HEPSİ`` mode so one response covers all 81 provinces).

def _bddk_finturk_spec(row: SeriesRow, start: date, end: date) -> FetchSpec:
    native = row.native_code.strip()
    if "|" in native:
        table_no, city = native.split("|", 1)
        table_no = table_no.strip()
        city = city.strip()
        if not table_no or not city:
            raise ValueError(
                f"{row.series_id}: bddk_finturk bulk native_code must be '<tabloNo>|<SEHIR>'"
            )
        # The city component identifies the catalog row, but the source can return
        # every province in one call.  The parser drops the out-of-scope YURT DIŞI
        # row and emits the 81 province series for this table/period.
        sehir = "HEPSİ"
    else:
        table_no = BDDK_FINTURK_TABLO_BIREYSEL
        # Table-3 entries predate the breadth catalog and keep their historical
        # ``<SEHIR>_<ColumnSlug>`` native code.  They now use the same all-province
        # request path as the broader tables; the parser emits the 81 catalogued
        # provinces and ignores the optional YURT DIŞI row.
        if not native:
            raise ValueError(f"{row.series_id}: native_code must not be empty")
        sehir = "HEPSİ"

    return FetchSpec(
        source_id=row.source_id,
        dataset_id=row.dataset_id,
        locator="bddk_finturk",
        start_date=start,
        end_date=end,
        parameters={
            "sehir": sehir,
            "tarafKodu": "10001",
            "tabloNo": table_no,
        },
    )


CONNECTOR_REGISTRY: dict[str, ConnectorBinding] = {
    "evds": ConnectorBinding(EvdsConnector, EvdsParser, _evds_spec),
    "bddk_monthly": ConnectorBinding(BddkMonthlyConnector, BddkMonthlyParser, _bddk_monthly_spec),
    "bddk_weekly": ConnectorBinding(BddkWeeklyConnector, BddkWeeklyParser, _bddk_weekly_spec),
    "bddk_finturk": ConnectorBinding(BddkFinTurkConnector, BddkFinTurkParser, _bddk_finturk_spec),
}
"""source_id -> how to run it. Adding a new source_id here, with its own
build_spec function, is the entire integration point — nothing else in
run_catalog_ingestion.py needs to change."""


__all__ = ["CONNECTOR_REGISTRY", "ConnectorBinding", "SeriesRow"]
