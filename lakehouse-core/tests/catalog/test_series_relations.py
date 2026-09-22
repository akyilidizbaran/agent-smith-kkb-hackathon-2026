"""Canonical parent/child and dimension relation graph tests."""

from __future__ import annotations

import time

from src.lakehouse.catalog.relations import infer_series_relations
from src.lakehouse.catalog.series import _upsert_series_relations
from src.lakehouse.db.bootstrap import bootstrap_database


def _row(series_id: str, source_id: str, native_code: str, name_tr: str, **extra):
    return {
        "series_id": series_id,
        "source_id": source_id,
        "native_code": native_code,
        "name_tr": name_tr,
        "description": "",
        "aliases": [],
        "tags": [],
        **extra,
    }


def test_bddk_monthly_card_total_and_children_are_linked() -> None:
    relations = infer_series_relations([
        _row("bddk_monthly:1539_Toplam", "bddk_monthly", "1539?Toplam", "Bireysel Kredi Kartları, Toplam"),
        _row("bddk_monthly:1541_Toplam", "bddk_monthly", "1541?Toplam", "Bireysel Kredi Kartları - Taksitli"),
        _row("bddk_monthly:1542_Toplam", "bddk_monthly", "1542?Toplam", "Bireysel Kredi Kartları - Taksitsiz"),
    ])
    by_id = {relation.series_id: relation for relation in relations}
    assert by_id["bddk_monthly:1539_Toplam"].relation_type == "parent_total"
    assert by_id["bddk_monthly:1541_Toplam"].parent_series_id == "bddk_monthly:1539_Toplam"
    assert by_id["bddk_monthly:1542_Toplam"].parent_series_id == "bddk_monthly:1539_Toplam"
    assert by_id["bddk_monthly:1539_Toplam"].additivity == "additive"


def test_weekly_parenthesized_tree_and_finturk_dimension_are_generic() -> None:
    relations = infer_series_relations([
        _row("bddk_weekly:5689_3", "bddk_weekly", "5689", "Tüketici Kredileri (4+5+6) (Tüketici Kredileri ve Bireysel Kredi Kartları (3+7)) - Krediler, Haftalık"),
        _row("bddk_weekly:5692_3", "bddk_weekly", "5692", "c) İhtiyaç (Tüketici Kredileri (4+5+6)) - Krediler, Haftalık"),
        _row("bddk_finturk:ADANA_KonutKredisi", "bddk_finturk", "ADANA_KonutKredisi", "Konut Kredisi, ADANA"),
        _row("bddk_finturk:ANKARA_KonutKredisi", "bddk_finturk", "ANKARA_KonutKredisi", "Konut Kredisi, ANKARA"),
    ])
    by_id = {relation.series_id: relation for relation in relations}
    assert by_id["bddk_weekly:5692_3"].parent_series_id == "bddk_weekly:5689_3"
    assert by_id["bddk_finturk:ADANA_KonutKredisi"].relation_type == "dimension_member"
    assert by_id["bddk_finturk:ADANA_KonutKredisi"].dimension_path == ("province=adana",)
    assert by_id["bddk_finturk:ADANA_KonutKredisi"].concept_id == by_id["bddk_finturk:ANKARA_KonutKredisi"].concept_id


def test_evds_dataset_regions_share_a_dimension_parent_when_published_together() -> None:
    relations = infer_series_relations([
        _row("evds:TP.TEST.TR", "evds", "TP.TEST.TR", "Test göstergesi (Türkiye)", dataset_id="evds_test"),
        _row("evds:TP.TEST.TR10", "evds", "TP.TEST.TR10", "Test göstergesi (İstanbul)", dataset_id="evds_test"),
        _row("evds:TP.TEST.TR22", "evds", "TP.TEST.TR22", "Test göstergesi (Ankara)", dataset_id="evds_test"),
    ])
    by_id = {relation.series_id: relation for relation in relations}
    assert by_id["evds:TP.TEST.TR"].relation_type == "parent_total"
    assert by_id["evds:TP.TEST.TR10"].parent_series_id == "evds:TP.TEST.TR"
    assert by_id["evds:TP.TEST.TR10"].relation_type == "child_breakdown"
    assert by_id["evds:TP.TEST.TR10"].dimension_path == ("region=TP.TEST.TR10",)


def test_unchanged_relations_are_not_rewritten_and_changed_rows_are_upserted(tmp_path) -> None:
    connection = bootstrap_database(tmp_path / "relations.duckdb", catalog_root=None)
    rows = [
        _row("manual:one", "manual", "one", "Birinci seri", concept_id="shared"),
        _row("manual:two", "manual", "two", "İkinci seri", concept_id="shared"),
    ]

    assert _upsert_series_relations(connection, rows) == 2
    before = connection.execute(
        "SELECT series_id, relation_content_sha256, epoch_ms(updated_at) "
        "FROM meta.series_relation ORDER BY series_id"
    ).fetchall()

    assert _upsert_series_relations(connection, rows) == 2
    unchanged = connection.execute(
        "SELECT series_id, relation_content_sha256, epoch_ms(updated_at) "
        "FROM meta.series_relation ORDER BY series_id"
    ).fetchall()
    assert unchanged == before

    rows[1] = _row(
        "manual:two",
        "manual",
        "two",
        "Yeni ad (İstanbul)",
        concept_id="different",
    )
    time.sleep(0.05)
    assert _upsert_series_relations(connection, rows) == 2
    after = connection.execute(
        "SELECT series_id, relation_content_sha256, epoch_ms(updated_at) "
        "FROM meta.series_relation ORDER BY series_id"
    ).fetchall()
    assert after[0][1] == unchanged[0][1]
    assert after[1][1] != unchanged[1][1]
    assert after[0][2] == unchanged[0][2]
    assert after[1][2] > unchanged[1][2]
    connection.close()


def test_thousands_of_relations_are_written_in_one_batch_quickly(tmp_path) -> None:
    """Ölçüldü (22 Eyl, Windows, DuckDB 1.5.5): satır satır `executemany` + `INSERT OR REPLACE` süperlineer
    büyüyordu (300 satır 5,9 sn; tam katalog 6.694 satır dakikalar); bootstrap çağıran her test ve CLI bekliyordu.
    Toplu ekleme aynı satırları saniyenin altında yazar; liste kolonu (dimension_path) korunur."""
    connection = bootstrap_database(tmp_path / "relations.duckdb", catalog_root=None)
    rows = [_row(f"bddk_finturk:IL{i:04d}_Kredi", "bddk_finturk", f"IL{i:04d}_Kredi", f"İl {i} kredi") for i in range(6000)]

    started = time.perf_counter()
    assert _upsert_series_relations(connection, rows) == 6000
    elapsed = time.perf_counter() - started

    assert elapsed < 20, f"6.000 ilişki {elapsed:.1f} sn sürdü; toplu ekleme bozulmuş olabilir"
    count, with_path = connection.execute(
        "SELECT count(*), count(*) FILTER (WHERE len(dimension_path) > 0) FROM meta.series_relation"
    ).fetchone()
    assert count == 6000 and with_path == 6000
    assert _upsert_series_relations(connection, rows) == 6000          # değişmeyen katalog: yeniden yazılmaz

