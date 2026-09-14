"""Semantic series catalog tests. Everything is local; no test touches the network."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.lakehouse.catalog.series import (
    CATALOG_SCHEMA_VERSION,
    CatalogError,
    load_catalog_files,
    load_series_catalog,
    parse_catalog_file,
)
from src.lakehouse.db.bootstrap import bootstrap_database


REPO_CATALOG = Path("catalog/series")


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path


def _entry(**overrides: str) -> str:
    """Render one valid series entry, with fields replaced or removed by ``overrides``.

    A value of ``"<omit>"`` drops the line entirely.
    """

    fields = {
        "series_id": "evds:TP.KTF12",
        "native_code": "TP.KTF12",
        "dataset_id": "evds_housing_interest",
        "name_tr": "Konut Kredisi Faiz Oranı",
        "description": "Haftalik konut kredisi faiz orani.",
        "frequency": "weekly",
        "week_anchor": "friday",
        "unit": "pct",
        "measure_type": "rate",
        "default_agg": "avg",
        "semantic_confidence": "verified",
        "semantic_source": "source_service",
    }
    fields.update(overrides)
    lines = [f"    {k}: {v}" for k, v in fields.items() if v != "<omit>"]
    return "  - " + "\n".join(lines).lstrip()


def _file(entries: str, *, source_id: str = "evds", version: str | None = None) -> str:
    return (
        f"catalog_schema_version: \"{version or CATALOG_SCHEMA_VERSION}\"\n"
        f"source_id: {source_id}\n"
        f"series:\n{entries}\n"
    )


# ------------------------------------------------------------------ repo catalog


def test_repository_catalog_parses_and_has_the_expected_series() -> None:
    records = load_catalog_files(REPO_CATALOG)

    by_id = {record.series_id: record for record in records}
    assert set(by_id) == {
        "evds:TP.KTF12",
        "evds:TP.KFE.TR",
        "evds:TP.FG.J0",
        "bddk_monthly:1534_Toplam",
        "bddk_weekly:5690_3",
    }


def test_evds_housing_interest_record_matches_the_verified_source_evidence() -> None:
    record = {r.series_id: r for r in load_catalog_files(REPO_CATALOG)}["evds:TP.KTF12"]

    assert record.source_id == "evds"
    assert record.native_code == "TP.KTF12"
    assert record.dataset_id == "evds_housing_interest"
    assert record.frequency == "weekly"
    assert record.week_anchor == "friday"
    assert record.measure_type == "rate"
    assert record.default_agg == "avg"
    assert record.unit == "pct"
    assert record.semantic_confidence == "verified"
    assert record.semantic_source == "source_service"
    assert "konut kredisi faizi" in record.aliases
    assert "mortgage faizi" in record.aliases


def test_bddk_housing_loans_record_matches_the_verified_source_evidence() -> None:
    record = {r.series_id: r for r in load_catalog_files(REPO_CATALOG)}[
        "bddk_monthly:1534_Toplam"
    ]

    assert record.source_id == "bddk_monthly"
    assert record.native_code == "1534?Toplam"
    assert record.dataset_id == "bddk_monthly_housing_loans"
    assert record.frequency == "monthly"
    assert record.week_anchor is None
    assert record.measure_type == "stock"
    assert record.default_agg == "last"
    assert record.unit == "TRY_mn"
    assert record.semantic_confidence == "verified"
    assert "konut kredisi" in record.aliases
    assert "ev kredisi" in record.aliases
    assert "mortgage" in record.aliases


def test_housing_price_index_is_an_index_with_an_unverified_base_year() -> None:
    """The unit is 'index'; what is unverified is the base year, which is a different thing."""

    record = {r.series_id: r for r in load_catalog_files(REPO_CATALOG)}["evds:TP.KFE.TR"]

    assert record.measure_type == "index"
    assert record.unit == "index"
    assert record.semantic_confidence == "derived"
    assert "konut fiyat endeksi" in record.aliases
    assert "BAZ YILI" in record.description


def test_monthly_stock_series_has_no_flow_suggesting_alias() -> None:
    """'kullandırılan konut kredisi' reads as a flow and would misroute a stock question."""

    record = {r.series_id: r for r in load_catalog_files(REPO_CATALOG)}[
        "bddk_monthly:1534_Toplam"
    ]

    assert "kullandırılan konut kredisi" not in record.aliases
    assert "konut kredisi stoku" in record.aliases


def test_weekly_housing_loans_record_matches_the_verified_source_evidence() -> None:
    record = {r.series_id: r for r in load_catalog_files(REPO_CATALOG)}["bddk_weekly:5690_3"]

    assert record.source_id == "bddk_weekly"
    assert record.native_code == "5690"
    assert record.dataset_id == "bddk_weekly_housing_loans"
    assert record.frequency == "weekly"
    assert record.week_anchor == "friday"
    assert record.unit == "TRY_mn"
    assert record.measure_type == "stock"
    assert record.default_agg == "last"
    assert record.semantic_confidence == "verified"
    assert record.semantic_source == "source_docs"
    assert record.metadata_url == "https://www.bddk.org.tr/BultenHaftalik/"


def test_weekly_description_records_the_date_and_identity_nuances() -> None:
    """The holiday date shift and the positional-id trap must survive into the catalog."""

    record = {r.series_id: r for r in load_catalog_files(REPO_CATALOG)}["bddk_weekly:5690_3"]

    assert "Perşembe" in record.description
    assert "SESSİZCE" in record.description
    assert "1.0.4" in record.description
    assert "5867" in record.description


def test_weekly_aliases_do_not_collide_with_the_monthly_series() -> None:
    by_id = {r.series_id: r for r in load_catalog_files(REPO_CATALOG)}
    weekly = set(by_id["bddk_weekly:5690_3"].aliases)
    monthly = set(by_id["bddk_monthly:1534_Toplam"].aliases)

    assert weekly & monthly == set()
    assert all("haftalık" in a.lower() or "BDDK" in a for a in weekly)


# ------------------------------------------------------------------- validation


def test_duplicate_series_id_within_a_file_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "evds.yml", _file(_entry() + "\n" + _entry()))

    with pytest.raises(CatalogError, match="duplicate series_id"):
        parse_catalog_file(path)


def test_duplicate_series_id_across_files_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "a_evds.yml", _file(_entry()))
    _write(tmp_path, "b_evds.yml", _file(_entry()))

    with pytest.raises(CatalogError, match="already defined in"):
        load_catalog_files(tmp_path)


def test_malformed_series_id_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "evds.yml", _file(_entry(series_id="not-a-namespaced-id")))

    with pytest.raises(CatalogError, match="series_id"):
        parse_catalog_file(path)


def test_namespace_mismatch_with_file_source_id_is_rejected(tmp_path: Path) -> None:
    """`bddk_monthly:...` must not live in a file that declares `source_id: evds`."""

    path = _write(
        tmp_path,
        "evds.yml",
        _file(_entry(series_id="bddk_monthly:1534_Toplam", native_code="1534?Toplam")),
    )

    with pytest.raises(CatalogError, match="namespace must match source_id"):
        parse_catalog_file(path)


@pytest.mark.parametrize(
    "missing",
    ["series_id", "native_code", "name_tr", "frequency", "measure_type",
     "semantic_confidence", "semantic_source", "description"],
)
def test_missing_required_field_is_rejected(tmp_path: Path, missing: str) -> None:
    path = _write(tmp_path, "evds.yml", _file(_entry(**{missing: "<omit>"})))

    with pytest.raises(CatalogError, match=f"'{missing}' is required"):
        parse_catalog_file(path)


@pytest.mark.parametrize(
    "field", ["series_id", "native_code", "name_tr", "description"]
)
def test_blank_required_field_is_rejected(tmp_path: Path, field: str) -> None:
    path = _write(tmp_path, "evds.yml", _file(_entry(**{field: '"   "'})))

    with pytest.raises(CatalogError, match="required"):
        parse_catalog_file(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("measure_type", "balance"),
        ("semantic_confidence", "probably"),
        ("frequency", "fortnightly"),
        ("week_anchor", "funday"),
        ("default_agg", "median"),
        ("status", "retired"),
        ("semantic_source", "vibes"),
        ("cumulative_reset", "calendar_year"),
    ],
)
def test_value_outside_the_vocabulary_is_rejected(
    tmp_path: Path, field: str, value: str
) -> None:
    path = _write(tmp_path, "evds.yml", _file(_entry(**{field: value})))

    with pytest.raises(CatalogError, match="is not one of"):
        parse_catalog_file(path)


def test_unsupported_field_is_rejected(tmp_path: Path) -> None:
    """A typo must fail loudly rather than being silently dropped."""

    path = _write(tmp_path, "evds.yml", _file(_entry(measure_typo="stock")))

    with pytest.raises(CatalogError, match="unsupported field"):
        parse_catalog_file(path)


def test_weekly_series_without_week_anchor_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "evds.yml", _file(_entry(week_anchor="<omit>")))

    with pytest.raises(CatalogError, match="weekly series must declare 'week_anchor'"):
        parse_catalog_file(path)


def test_week_anchor_on_a_non_weekly_series_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "evds.yml", _file(_entry(frequency="monthly")))

    with pytest.raises(CatalogError, match="only meaningful for weekly"):
        parse_catalog_file(path)


def test_flow_ytd_without_cumulative_reset_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "evds.yml",
        _file(_entry(frequency="monthly", week_anchor="<omit>", measure_type="flow_ytd",
                     default_agg="sum")),
    )

    with pytest.raises(CatalogError, match="flow_ytd requires 'cumulative_reset'"):
        parse_catalog_file(path)


def test_flow_ytd_with_reset_none_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "evds.yml",
        _file(_entry(frequency="monthly", week_anchor="<omit>", measure_type="flow_ytd",
                     default_agg="sum", cumulative_reset="none")),
    )

    with pytest.raises(CatalogError, match="resets by definition"):
        parse_catalog_file(path)


def test_flow_ytd_with_yearly_reset_is_accepted(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "evds.yml",
        _file(_entry(frequency="monthly", week_anchor="<omit>", measure_type="flow_ytd",
                     default_agg="sum", cumulative_reset="yearly")),
    )

    record = parse_catalog_file(path)[0]

    assert record.measure_type == "flow_ytd"
    assert record.cumulative_reset == "yearly"


def test_cumulative_reset_on_a_non_ytd_series_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "evds.yml", _file(_entry(cumulative_reset="yearly")))

    with pytest.raises(CatalogError, match="only meaningful for flow_ytd"):
        parse_catalog_file(path)


@pytest.mark.parametrize(
    "overrides",
    [
        {"semantic_confidence": "unknown", "unit": "<omit>"},
        {"measure_type": "unknown"},
    ],
)
def test_unknown_semantics_may_not_declare_an_aggregation(
    tmp_path: Path, overrides: dict[str, str]
) -> None:
    """An unclassified series must not be handed a default aggregation."""

    path = _write(tmp_path, "evds.yml", _file(_entry(**overrides)))

    with pytest.raises(CatalogError, match="no safe aggregation"):
        parse_catalog_file(path)


def test_unknown_semantics_without_an_aggregation_is_accepted(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "evds.yml",
        _file(_entry(semantic_confidence="unknown", unit="<omit>", default_agg="<omit>")),
    )

    record = parse_catalog_file(path)[0]

    assert record.semantic_confidence == "unknown"
    assert record.default_agg is None


def test_verified_confidence_requires_a_unit(tmp_path: Path) -> None:
    path = _write(tmp_path, "evds.yml", _file(_entry(unit="<omit>")))

    with pytest.raises(CatalogError, match="at most 'derived'"):
        parse_catalog_file(path)


def test_wrong_catalog_schema_version_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "evds.yml", _file(_entry(), version="9.9"))

    with pytest.raises(CatalogError, match="catalog_schema_version"):
        parse_catalog_file(path)


def test_invalid_yaml_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "evds.yml", "catalog_schema_version: \"1.0\"\n  : : broken\n")

    with pytest.raises(CatalogError, match="not valid YAML"):
        parse_catalog_file(path)


def test_empty_series_list_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path, "evds.yml", f'catalog_schema_version: "{CATALOG_SCHEMA_VERSION}"\n'
        "source_id: evds\nseries: []\n"
    )

    with pytest.raises(CatalogError, match="non-empty list"):
        parse_catalog_file(path)


def test_duplicate_alias_entries_are_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "evds.yml",
        _file(_entry() + "\n    aliases: [konut kredisi, konut kredisi]"),
    )

    with pytest.raises(CatalogError, match="duplicate entries"):
        parse_catalog_file(path)


# ------------------------------------------------- dataset_id / status coupling


def test_null_dataset_id_with_active_status_is_rejected(tmp_path: Path) -> None:
    """An active series with nothing to fetch it would be a dead end for the agent."""

    path = _write(tmp_path, "evds.yml", _file(_entry(dataset_id="<omit>")))

    with pytest.raises(CatalogError, match="status 'draft'"):
        parse_catalog_file(path)


def test_null_dataset_id_with_draft_status_is_accepted(tmp_path: Path) -> None:
    """Cataloguing a series before its connector exists is legitimate — as a draft."""

    path = _write(
        tmp_path, "evds.yml", _file(_entry(dataset_id="<omit>", status="draft"))
    )

    record = parse_catalog_file(path)[0]

    assert record.dataset_id is None
    assert record.status == "draft"


def test_dataset_id_present_allows_active_status(tmp_path: Path) -> None:
    path = _write(tmp_path, "evds.yml", _file(_entry(dataset_id="evds_housing_interest")))

    record = parse_catalog_file(path)[0]

    assert record.dataset_id == "evds_housing_interest"
    assert record.status == "active"


# --------------------------------------------------- catalog directory guards


def test_missing_catalog_directory_is_an_error(tmp_path: Path) -> None:
    """A wrong path must not look like an empty catalog."""

    with pytest.raises(CatalogError, match="does not exist"):
        load_catalog_files(tmp_path / "nope")


def test_catalog_directory_without_yaml_files_is_an_error(tmp_path: Path) -> None:
    empty = tmp_path / "catalog"
    empty.mkdir()
    (empty / "notes.txt").write_text("not a catalog", encoding="utf-8")

    with pytest.raises(CatalogError, match="no .yml files"):
        load_catalog_files(empty)


def test_catalog_path_that_is_a_file_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "catalog"
    path.write_text("", encoding="utf-8")

    with pytest.raises(CatalogError, match="not a directory"):
        load_catalog_files(path)
