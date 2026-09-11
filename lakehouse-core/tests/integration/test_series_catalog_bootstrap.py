"""Offline integration tests for loading the semantic catalog during bootstrap."""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

import pytest

from src.lakehouse.catalog.series import CatalogError, load_series_catalog
from src.lakehouse.db.bootstrap import bootstrap_database


REPO_CATALOG = Path("catalog/series")
VALID_ENTRY = """
    catalog_schema_version: "1.0"
    source_id: evds
    series:
      - series_id: evds:TP.KTF12
        native_code: TP.KTF12
        dataset_id: evds_housing_interest
        name_tr: Konut Kredisi Faiz Oranı
        description: Haftalik konut kredisi faiz orani.
        frequency: weekly
        week_anchor: friday
        unit: pct
        measure_type: rate
        default_agg: avg
        semantic_confidence: verified
        semantic_source: source_service
"""


TWO_ENTRIES = VALID_ENTRY + """      - series_id: evds:TP.KFE.TR
        native_code: TP.KFE.TR
        dataset_id: evds_housing_price_index
        name_tr: Konut Fiyat Endeksi
        description: Aylik konut fiyat endeksi.
        frequency: monthly
        measure_type: index
        semantic_confidence: derived
        semantic_source: source_service
"""


def _catalog(tmp_path: Path, body: str, name: str = "evds.yml") -> Path:
    root = tmp_path / "catalog"
    root.mkdir(exist_ok=True)
    (root / name).write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return root


def _updated_at_ms(connection) -> dict[str, int]:
    """Read ``updated_at`` as epoch milliseconds.

    DuckDB converts a ``TIMESTAMPTZ`` to Python via ``pytz``, which this project does not
    depend on, so the column is read as a number instead. This applies to every existing
    ``TIMESTAMPTZ`` in ``meta.*`` and is not specific to the catalog.
    """

    return dict(
        connection.execute(
            "SELECT series_id, epoch_ms(updated_at) FROM meta.series"
        ).fetchall()
    )


def _series_ids(connection) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            "SELECT series_id FROM meta.series ORDER BY series_id"
        ).fetchall()
    ]


# ------------------------------------------------------------------- bootstrap


def test_bootstrap_creates_the_series_table(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "t.duckdb", catalog_root=None)

    columns = {
        row[0]
        for row in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'meta' AND table_name = 'series'"
        ).fetchall()
    }
    assert {
        "series_id", "source_id", "native_code", "dataset_id", "name_tr", "description",
        "aliases", "tags", "frequency", "week_anchor", "unit", "measure_type",
        "default_agg", "cumulative_reset", "semantic_confidence", "semantic_source",
        "first_obs", "last_obs", "metadata_url", "status", "updated_at",
    } <= columns
    connection.close()


def test_bootstrap_loads_the_repository_catalog(tmp_path: Path) -> None:
    """The original four hand-verified series must always load, among whatever else the
    repository catalog now also defines -- catalog growth must not shrink this list."""

    connection = bootstrap_database(tmp_path / "t.duckdb")

    assert {
        "bddk_monthly:1534_Toplam",
        "bddk_weekly:5690_3",
        "evds:TP.KFE.TR",
        "evds:TP.KTF12",
    }.issubset(set(_series_ids(connection)))
    row = connection.execute(
        "SELECT frequency, week_anchor, unit, measure_type, default_agg, "
        "semantic_confidence, status FROM meta.series WHERE series_id = 'evds:TP.KTF12'"
    ).fetchone()
    assert row == ("weekly", "friday", "pct", "rate", "avg", "verified", "active")
    connection.close()


def test_aliases_and_tags_round_trip_as_lists(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "t.duckdb")

    aliases, tags = connection.execute(
        "SELECT aliases, tags FROM meta.series WHERE series_id = 'bddk_monthly:1534_Toplam'"
    ).fetchone()
    assert "konut kredisi" in aliases
    assert "ev kredisi" in aliases
    assert "mortgage" in aliases
    assert "stok" in tags
    connection.close()


# ----------------------------------------------------------------- idempotency


def test_second_bootstrap_does_not_duplicate_rows(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    first = bootstrap_database(db)
    before = _series_ids(first)
    first.close()

    second = bootstrap_database(db)
    after = _series_ids(second)
    count = second.execute("SELECT count(*) FROM meta.series").fetchone()[0]
    second.close()

    assert after == before
    assert count == len(before)


def test_unchanged_content_leaves_updated_at_alone(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    first = bootstrap_database(db)
    stamps = _updated_at_ms(first)
    first.close()

    time.sleep(0.05)
    second = bootstrap_database(db)
    result = load_series_catalog(second, REPO_CATALOG)
    after = _updated_at_ms(second)
    second.close()

    assert after == stamps
    assert result.unchanged == len(stamps)
    assert result.inserted == 0
    assert result.updated == 0


def test_changed_content_updates_the_row_and_its_timestamp(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    root = _catalog(tmp_path, VALID_ENTRY)
    connection = bootstrap_database(db, catalog_root=root)
    before = _updated_at_ms(connection)["evds:TP.KTF12"]

    time.sleep(0.05)
    _catalog(tmp_path, VALID_ENTRY.replace("Konut Kredisi Faiz Oranı", "Konut Kredisi Faizi"))
    result = load_series_catalog(connection, root)

    name = connection.execute(
        "SELECT name_tr FROM meta.series WHERE series_id = 'evds:TP.KTF12'"
    ).fetchone()[0]
    after = _updated_at_ms(connection)["evds:TP.KTF12"]
    connection.close()

    assert result.updated == 1
    assert result.inserted == 0
    assert name == "Konut Kredisi Faizi"
    assert after > before


# ---------------------------------------------------- transaction and ownership


def test_an_invalid_file_leaves_no_partial_state(tmp_path: Path) -> None:
    """A second file failing validation must abort the whole load, including the good one."""

    db = tmp_path / "t.duckdb"
    root = _catalog(tmp_path, VALID_ENTRY, name="a_evds.yml")
    (root / "b_evds.yml").write_text(
        textwrap.dedent(
            """
            catalog_schema_version: "1.0"
            source_id: evds
            series:
              - series_id: evds:TP.BAD
                native_code: TP.BAD
                name_tr: Bozuk Seri
                description: Hafta capasi eksik seri.
                frequency: weekly
                measure_type: rate
                semantic_confidence: verified
                semantic_source: source_service
            """
        ).lstrip(),
        encoding="utf-8",
    )

    connection = bootstrap_database(db, catalog_root=None)
    with pytest.raises(CatalogError, match="week_anchor"):
        load_series_catalog(connection, root)

    assert connection.execute("SELECT count(*) FROM meta.series").fetchone() == (0,)
    connection.close()


def test_a_write_failure_rolls_the_whole_load_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validation passes but a write fails halfway: nothing from that load may survive.

    This exercises the transaction boundary rather than the validator, so the failure is
    injected into the insert itself: the first row writes, the second raises.
    """

    from src.lakehouse.catalog import series as series_module

    db = tmp_path / "t.duckdb"
    root = _catalog(tmp_path, TWO_ENTRIES)
    connection = bootstrap_database(db, catalog_root=None)

    calls = {"n": 0}
    real_insert = series_module._insert

    def failing_insert(conn, record):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated write failure on the second record")
        return real_insert(conn, record)

    monkeypatch.setattr(series_module, "_insert", failing_insert)

    with pytest.raises(RuntimeError, match="simulated write failure"):
        load_series_catalog(connection, root)

    assert calls["n"] == 2
    # The first insert succeeded inside the transaction and must have been rolled back.
    assert connection.execute("SELECT count(*) FROM meta.series").fetchone() == (0,)
    connection.close()


def test_loader_never_deletes_rows_it_did_not_author(tmp_path: Path) -> None:
    db = tmp_path / "t.duckdb"
    connection = bootstrap_database(db)
    connection.execute(
        """
        INSERT INTO meta.series (
            series_id, source_id, native_code, name_tr, description, frequency,
            measure_type, semantic_confidence, semantic_source, status,
            catalog_content_sha256
        ) VALUES (
            'manual:HAND_ADDED', 'manual', 'HAND_ADDED', 'Elle eklenmiş',
            'Katalog disindan elle eklenmis satir.',
            'monthly', 'unknown', 'unknown', 'manual', 'draft', 'not-a-catalog-hash'
        )
        """
    )

    load_series_catalog(connection, REPO_CATALOG)

    assert "manual:HAND_ADDED" in _series_ids(connection)
    connection.close()


def test_first_and_last_obs_survive_a_catalog_reload(tmp_path: Path) -> None:
    """Coverage dates are operational; the loader must not clear them."""

    db = tmp_path / "t.duckdb"
    root = _catalog(tmp_path, VALID_ENTRY)
    connection = bootstrap_database(db, catalog_root=root)
    connection.execute(
        "UPDATE meta.series SET first_obs = DATE '2021-01-08', last_obs = DATE '2026-06-26' "
        "WHERE series_id = 'evds:TP.KTF12'"
    )

    _catalog(tmp_path, VALID_ENTRY.replace("Konut Kredisi Faiz Oranı", "Yeni Ad"))
    result = load_series_catalog(connection, root)

    name, first_obs, last_obs = connection.execute(
        "SELECT name_tr, first_obs, last_obs FROM meta.series "
        "WHERE series_id = 'evds:TP.KTF12'"
    ).fetchone()
    connection.close()

    assert result.updated == 1
    assert name == "Yeni Ad"
    assert str(first_obs) == "2021-01-08"
    assert str(last_obs) == "2026-06-26"


def test_catalog_load_is_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Any socket attempt during a catalog load fails the test."""

    import socket

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("catalog load attempted network access")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)

    connection = bootstrap_database(tmp_path / "t.duckdb")

    # Not an exact count: the repository catalog grows over time. What this test guards is
    # that an offline load still populates meta.series from the real repo catalog at all.
    assert len(_series_ids(connection)) >= 4
    connection.close()


# ------------------------------------------------- SQL-level constraint checks


def test_sql_rejects_a_null_description(tmp_path: Path) -> None:
    """The loader requires a description; the schema must not silently allow a null one."""

    connection = bootstrap_database(tmp_path / "t.duckdb", catalog_root=None)

    with pytest.raises(Exception) as excinfo:
        connection.execute(
            """
            INSERT INTO meta.series (
                series_id, source_id, native_code, dataset_id, name_tr, description,
                frequency, measure_type, semantic_confidence, semantic_source,
                status, catalog_content_sha256
            ) VALUES (
                'evds:TP.NULLDESC', 'evds', 'TP.NULLDESC', 'evds_x', 'Aciklamasiz', NULL,
                'monthly', 'unknown', 'unknown', 'manual', 'draft', 'hash'
            )
            """
        )

    assert "NOT NULL" in str(excinfo.value).upper()
    connection.close()


def test_sql_rejects_an_active_series_without_a_dataset_id(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "t.duckdb", catalog_root=None)

    with pytest.raises(Exception) as excinfo:
        connection.execute(
            """
            INSERT INTO meta.series (
                series_id, source_id, native_code, dataset_id, name_tr, description,
                frequency, measure_type, semantic_confidence, semantic_source,
                status, catalog_content_sha256
            ) VALUES (
                'evds:TP.NODATASET', 'evds', 'TP.NODATASET', NULL, 'Datasetsiz', 'Aciklama',
                'monthly', 'unknown', 'unknown', 'manual', 'active', 'hash'
            )
            """
        )

    assert "constraint" in str(excinfo.value).lower()
    connection.close()


def test_sql_accepts_a_draft_series_without_a_dataset_id(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "t.duckdb", catalog_root=None)

    connection.execute(
        """
        INSERT INTO meta.series (
            series_id, source_id, native_code, dataset_id, name_tr, description,
            frequency, measure_type, semantic_confidence, semantic_source,
            status, catalog_content_sha256
        ) VALUES (
            'evds:TP.DRAFT', 'evds', 'TP.DRAFT', NULL, 'Taslak', 'Aciklama',
            'monthly', 'unknown', 'unknown', 'manual', 'draft', 'hash'
        )
        """
    )

    assert "evds:TP.DRAFT" in _series_ids(connection)
    connection.close()


# --------------------------------------------- catalog directory is not optional


def test_bootstrap_fails_when_the_catalog_directory_is_missing(tmp_path: Path) -> None:
    """A wrong path must fail loudly rather than bootstrapping an empty catalog."""

    with pytest.raises(CatalogError, match="does not exist"):
        bootstrap_database(tmp_path / "t.duckdb", catalog_root=tmp_path / "nope")


def test_bootstrap_fails_when_the_catalog_directory_has_no_files(tmp_path: Path) -> None:
    empty = tmp_path / "catalog"
    empty.mkdir()

    with pytest.raises(CatalogError, match="no .yml files"):
        bootstrap_database(tmp_path / "t.duckdb", catalog_root=empty)


def test_a_failed_catalog_load_leaves_no_open_connection(tmp_path: Path) -> None:
    """The database file must be re-openable, which it is not if a connection leaked."""

    db = tmp_path / "t.duckdb"

    with pytest.raises(CatalogError):
        bootstrap_database(db, catalog_root=tmp_path / "nope")

    # A leaked write connection would make this second open fail.
    connection = bootstrap_database(db, catalog_root=None)
    assert connection.execute("SELECT count(*) FROM meta.series").fetchone() == (0,)
    connection.close()


def test_catalog_can_be_turned_off_on_purpose(tmp_path: Path) -> None:
    connection = bootstrap_database(tmp_path / "t.duckdb", catalog_root=None)

    assert _series_ids(connection) == []
    connection.close()
