"""Referans adaptörün güvenlik sınırları.

Ekip incelemesi (10 Eylül): read_csv_auto('...') ve "SELECT 1; SELECT 2"
execute_sql'den geçiyordu. Adaptörün hiç birim testi olmadığı için fark
edilmemişti. Bu dosya o açığı ve aynı sınıftaki komşularını kapatır.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.adapters.duckdb_lakehouse import (  # noqa: E402
    DuckDBLakehouse,
    guard_sql,
    hardened_connection,
    verify_hardened,
)
from kkb_agent.contracts.lakehouse import LakehouseError  # noqa: E402


@pytest.fixture
def lakehouse(tmp_path: Path) -> DuckDBLakehouse:
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE t AS SELECT 1 AS a, 'x' AS b")
    con.close()
    (tmp_path / "catalog.json").write_text("[]", encoding="utf-8")
    return DuckDBLakehouse(db)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE t",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_parquet('/tmp/x.parquet')",
        "SELECT * FROM read_json_auto('/tmp/x.json')",
        "SELECT * FROM glob('/tmp/*')",
        "SELECT * FROM read_text('/etc/hosts')",
        "DROP TABLE t",
        "CREATE TABLE z AS SELECT 1",
        "INSERT INTO t VALUES (2, 'y')",
        "ATTACH '/tmp/other.duckdb' AS o",
        "COPY t TO '/tmp/out.csv'",
        "INSTALL httpfs",
        "SET enable_external_access = true",
        "PRAGMA database_list",
    ],
)
def test_tehlikeli_sql_reddedilir(lakehouse: DuckDBLakehouse, sql: str) -> None:
    with pytest.raises(LakehouseError):
        lakehouse.execute_sql(sql)


def test_normal_sorgu_calisir(lakehouse: DuckDBLakehouse) -> None:
    r = lakehouse.execute_sql("SELECT a, b FROM t WHERE a = 1")
    assert r.data.to_dict("records") == [{"a": 1, "b": "x"}]


def test_with_ctesi_kabul_edilir(lakehouse: DuckDBLakehouse) -> None:
    r = lakehouse.execute_sql("WITH c AS (SELECT a FROM t) SELECT a FROM c")
    assert len(r.data) == 1


def test_sondaki_noktali_virgul_tolere_edilir(lakehouse: DuckDBLakehouse) -> None:
    assert len(lakehouse.execute_sql("SELECT a FROM t;").data) == 1


def test_baglanti_gercekten_sertlestirilmis(lakehouse: DuckDBLakehouse) -> None:
    con = lakehouse._con
    s = lambda n: con.execute("SELECT current_setting(?)", [n]).fetchone()[0]
    assert s("access_mode") == "read_only"
    assert s("enable_external_access") is False
    assert s("lock_configuration") is True


def test_sertlestirme_guard_disinda_da_tutar(lakehouse: DuckDBLakehouse) -> None:
    """Guard bir gün atlansa bile motor dış erişimi reddetmeli (savunma derinliği)."""
    with pytest.raises(duckdb.Error):
        lakehouse._con.execute("SELECT * FROM read_csv_auto('/etc/passwd')")


def test_kilitli_yapilandirma_geri_acilamaz(lakehouse: DuckDBLakehouse) -> None:
    with pytest.raises(duckdb.Error):
        lakehouse._con.execute("SET enable_external_access = true")


def test_bellek_ici_sertlestirilmis_baglanti() -> None:
    """workspace_compute_column'ın kullandığı yol da aynı sınırlara sahip olmalı."""
    con = hardened_connection()
    verify_hardened(con, require_read_only=False)
    with pytest.raises(duckdb.Error):
        con.execute("SELECT * FROM read_csv_auto('/etc/passwd')")


def test_satir_siniri_motorda_uygulanir(lakehouse: DuckDBLakehouse) -> None:
    r = lakehouse.execute_sql("SELECT * FROM range(100)", max_rows=10)
    assert len(r.data) == 10
    assert any("kırpıldı" in w for w in r.provenance.warnings)


def test_guard_sql_tek_ifade_zorunlu() -> None:
    with pytest.raises(LakehouseError, match="2 ifade"):
        guard_sql("SELECT 1; SELECT 2")


def test_release_connections_butun_okuyuculari_birakir_ve_yazar_acilir(tmp_path) -> None:
    """Ölçülen hata: eski bir agent örneğinin okuyucusu açık kaldı, Architect'in yazar alt
    süreci "Conflicting lock is held" ile açılamadı. close() yalnız kendi bağlantısını
    kapatıyordu; süreçteki HEPSİ bırakılmalı. Bırakılan adaptör dokunulunca yeniden açar."""
    import duckdb
    from kkb_agent.adapters.duckdb_lakehouse import DuckDBLakehouse, release_connections

    db = tmp_path / "lh.duckdb"
    con = duckdb.connect(str(db)); con.execute("CREATE TABLE t(x INT); INSERT INTO t VALUES (1)"); con.close()
    (tmp_path / "catalog.json").write_text("[]", encoding="utf-8")

    a = DuckDBLakehouse(db); b = DuckDBLakehouse(db)   # iki okuyucu, aynı süreç
    a.close()                                           # yalnız birini kapatmak yetmez
    with pytest.raises(Exception):
        duckdb.connect(str(db)).close()                 # yazar hâlâ açılamaz (b tutuyor)

    assert release_connections(db) == 1                 # kalan okuyucu bırakıldı
    w = duckdb.connect(str(db)); w.execute("INSERT INTO t VALUES (2)"); w.close()   # yazar açıldı

    # bırakılan adaptörler ölmedi: dokununca yeniden açar ve yeni satırı görür
    assert b.execute_sql("SELECT count(*) AS n FROM t").data.iloc[0, 0] == 2
    assert a.execute_sql("SELECT count(*) AS n FROM t").data.iloc[0, 0] == 2
    assert release_connections(None) == 0
