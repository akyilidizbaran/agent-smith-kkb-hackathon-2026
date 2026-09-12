"""Kanıt zinciri: sayı → hücre → SQL → gözlem → artifact → RAW/Bronze/URL; halka yoksa 'eksik' der.

Veri ekibinin DDL'i ile kurulmuş bir veritabanı: silver + meta.artifact + diskte sahte bir
Bronze dosyası. Tahmin yok: locator ve fetched_at yalnız meta.artifact'ten, Bronze yolu
yalnız diskten gelir.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.adapters.silver_lakehouse import SilverLakehouse  # noqa: E402
from kkb_agent.contracts.evidence import EvidenceCapable  # noqa: E402
from kkb_agent.contracts.lakehouse import QueryProvenance  # noqa: E402
from kkb_agent.core.evidence import EvidenceBuilder  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from tests.test_silver_lakehouse import DDL, _series  # noqa: E402

SHA_A = "a" * 64
SHA_B = "b" * 64
ARTIFACT_DDL = """
CREATE TABLE meta.artifact (
    artifact_sha256 VARCHAR PRIMARY KEY, source_id VARCHAR, dataset_id VARCHAR, locator VARCHAR,
    media_type VARCHAR, byte_size BIGINT, http_status INTEGER, fetched_at TIMESTAMPTZ,
    raw_path VARCHAR, first_seen_at TIMESTAMPTZ, last_seen_at TIMESTAMPTZ);
"""


@pytest.fixture
def lake(tmp_path: Path) -> SilverLakehouse:
    db = tmp_path / "data" / "lakehouse.duckdb"
    db.parent.mkdir()
    con = duckdb.connect(str(db))
    con.execute(DDL); con.execute(ARTIFACT_DDL)
    _series(con, "bddk_monthly:konut", aliases=["konut kredisi"], name_tr="Konut Kredisi")
    for i, (v, sha) in enumerate([(100.0, SHA_A), (110.0, SHA_A), (121.0, SHA_B)], start=1):
        con.execute(
            "INSERT INTO silver.fact_observation VALUES (?,NULL,?,NULL,?,?,'monthly','TRY_mn','stock','ok',"
            "'bddk_monthly','ds',?,now(),'v1','vin','run-1')",
            ["bddk_monthly:konut", date(2025, i, 28), date(2025, i, 28), v, sha],
        )
    con.execute(
        "INSERT INTO meta.artifact VALUES (?, 'bddk_monthly', 'ds', 'https://www.bddk.org.tr/x', 'application/json',"
        " 100, 200, '2026-09-12 12:35:53+03', '/data/raw/bddk_monthly/a.json', now(), now())", [SHA_A])
    # SHA_B: artifact kaydı yok → locator/fetched_at eksik, zincir kopuk
    con.close()
    bronze = tmp_path / "data" / "bronze" / "source_id=bddk_monthly" / "dataset_id=ds"
    bronze.mkdir(parents=True)
    (bronze / f"artifact_sha256={SHA_A}.parquet").write_bytes(b"PAR1")
    return SilverLakehouse(db)


def _workspace(lake: SilverLakehouse) -> AnalysisWorkspace:
    ws = AnalysisWorkspace()
    r = lake.execute_sql("SELECT observation_date, value AS bakiye FROM silver.fact_observation "
                         "WHERE series_id = 'bddk_monthly:konut' ORDER BY 1")
    ws.set_table(r.data, description="aylık konut", provenance=r.provenance)
    return ws


def test_adaptor_gozlemden_artifact_ve_raw_a_iner(lake: SilverLakehouse) -> None:
    assert isinstance(lake, EvidenceCapable)
    obs = lake.evidence_for_observations("bddk_monthly:konut", [date(2025, 1, 28), date(2025, 3, 28)])
    assert [o.observation_date for o in obs] == [date(2025, 1, 28), date(2025, 3, 28)]
    jan, mar = obs
    assert jan.artifact_sha256 == SHA_A and jan.locator == "https://www.bddk.org.tr/x"
    assert jan.fetched_at is not None and jan.fetched_at.year == 2026 and jan.http_status == 200
    assert jan.raw_path == "/data/raw/bddk_monthly/a.json"
    assert jan.bronze_path is not None and jan.bronze_path.endswith(f"artifact_sha256={SHA_A}.parquet")
    assert jan.complete
    assert mar.artifact_sha256 == SHA_B and mar.locator is None and not mar.complete

    arts = lake.evidence_for_artifacts([SHA_A, SHA_B])
    assert arts[SHA_A]["locator"] == "https://www.bddk.org.tr/x" and arts[SHA_A]["bronze_path"]
    assert arts[SHA_B]["locator"] is None and arts[SHA_B]["bronze_path"] is None


def test_panel_sayiyi_hucreye_hucreyi_sql_e_satiri_artifact_e_baglar(lake: SilverLakehouse) -> None:
    ws = _workspace(lake)
    answer = "2025 Ocak'ta bakiye 100 milyon TL, Şubat'ta 110 milyon TL idi; Mart 121 milyon TL."
    steps = [SimpleNamespace(tool_name="lakehouse_describe", tool_args={"dataset_id": "bddk_monthly:konut"}),
             SimpleNamespace(tool_name="lakehouse_describe", tool_args={"dataset_id": "evds:TP.KTF12"})]

    panel = EvidenceBuilder(lake).build("soru", answer, ws, steps)

    assert panel.supports_artifacts and panel.table_rows == 3
    matched = {n.text: (n.column, n.row_key) for n in panel.numbers if n.matched}
    assert matched["100"] == ("bakiye", "2025-01-28") and matched["121"] == ("bakiye", "2025-03-28")
    assert matched["2025"] == ("observation_date", "yıl 2025")
    assert [c.column for c in panel.columns] == ["observation_date", "bakiye"]
    assert all("FROM silver.fact_observation" in (c.sql or "") for c in panel.columns)
    assert panel.columns[1].dataset_ids == ["bddk_monthly:konut"]
    assert len(panel.observations) == 3 and set(panel.artifacts) == {SHA_A, SHA_B}
    assert panel.consulted_unused == ["evds:TP.KTF12"]
    # SHA_B'nin artifact kaydı yok → zincir EKSİK ve sebebi yazılı
    assert not panel.complete
    assert any("artifact/locator/fetched_at izi eksik" in g for g in panel.gaps)
    text = panel.render()
    assert "kanıt zinciri EKSİK" in text and "https://www.bddk.org.tr/x" in text and "Bronze:" in text
    assert "DANIŞILDI, KULLANILMADI: evds:TP.KTF12" in text


def test_tam_zincir_ve_tabloda_olmayan_sayi(lake: SilverLakehouse) -> None:
    ws = AnalysisWorkspace()
    r = lake.execute_sql("SELECT observation_date, value AS bakiye FROM silver.fact_observation "
                         "WHERE series_id = 'bddk_monthly:konut' AND observation_date < '2025-03-01' ORDER BY 1")
    ws.set_table(r.data, description="ilk iki ay", provenance=r.provenance)

    ok = EvidenceBuilder(lake).build("soru", "Ocak 100, Şubat 110 milyon TL.", ws, [])
    assert ok.complete, ok.gaps
    assert "kanıt zinciri tam" in ok.summary() and "2 gözlem → 1 artifact" in ok.summary()

    bad = EvidenceBuilder(lake).build("soru", "Ocak 100, fark 999 milyon TL.", ws, [])
    assert not bad.complete and any("999" in g for g in bad.gaps)
    assert [n.text for n in bad.numbers if not n.matched] == ["999"]


def test_gold_cercevesi_kendi_sha_listesinden_cozulur(lake: SilverLakehouse) -> None:
    ws = AnalysisWorkspace()
    frame = pd.DataFrame({
        "period_end": [date(2025, 3, 31)],
        "value": [121.0],
        "source_observation_dates": [[date(2025, 1, 28), date(2025, 2, 28), date(2025, 3, 28)]],
        "artifact_sha256_list": [[SHA_A, SHA_B]],
    })
    ws.set_table(frame, description="çeyreklik",
                 provenance=QueryProvenance(sql="gold-run align_frequency('bddk_monthly:konut')",
                                            dataset_ids=["bddk_monthly:konut"], sources=["gold"]))
    panel = EvidenceBuilder(lake).build("soru", "2025 Q1 sonu 121 milyon TL.", ws, [])
    assert set(panel.artifacts) == {SHA_A, SHA_B}
    assert [o.observation_date for o in panel.observations] == [date(2025, 1, 28), date(2025, 2, 28), date(2025, 3, 28)]
    assert panel.numbers[-1].matched and panel.numbers[-1].column == "value"


def test_seed_adaptorunde_zincir_sql_de_biter_ve_bunu_soyler() -> None:
    class Seed:  # EvidenceCapable DEĞİL
        pass

    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"donem": [date(2025, 1, 31)], "toplam": [523455.0]}), description="t",
                 provenance=QueryProvenance(sql="SELECT donem, toplam FROM bddk_aylik_krediler", dataset_ids=["bddk_aylik_krediler"]))
    panel = EvidenceBuilder(Seed()).build("soru", "Ocak 2025: 523.455 milyon TL", ws, [])
    assert not panel.supports_artifacts and panel.observations == []
    assert panel.matched_numbers == 2 and any("seed" in g for g in panel.gaps)
    assert not panel.complete and "SQL: SELECT donem" in panel.render()


def test_tablo_yoksa_panel_bunu_soyler() -> None:
    panel = EvidenceBuilder(object()).build("soru", "Veri 2021'de başlıyor.", AnalysisWorkspace(), [])
    assert panel.gaps == ["analiz tablosu yok"] and not panel.complete
    assert [n.text for n in panel.numbers] == ["2021"]


def test_turetilmis_kolon_zinciri_kirmaz_provenanssiz_kolon_sebep_yazar(lake: SilverLakehouse) -> None:
    ws = AnalysisWorkspace()
    r = lake.execute_sql("SELECT observation_date, value AS bakiye FROM silver.fact_observation "
                         "WHERE series_id = 'bddk_monthly:konut' AND observation_date < '2025-03-01' ORDER BY 1")
    ws.set_table(r.data, description="ilk iki ay", provenance=r.provenance)
    ws.add_column("degisim", ws.table["bakiye"].diff(), description="fark",
                  provenance=QueryProvenance(sql="türetilmiş: bakiye - LAG(bakiye)", dataset_ids=[]))
    panel = EvidenceBuilder(lake).build("soru", "Şubat'ta 110, fark 10 milyon TL.", ws, [])
    assert panel.complete, panel.gaps
    assert any("türetilmiş" in (c.sql or "") for c in panel.columns)

    ws.add_column("sebepsiz", ws.table["bakiye"] * 2, description="provenanssız")
    panel2 = EvidenceBuilder(lake).build("soru", "Şubat'ta 110 milyon TL.", ws, [])
    assert not panel2.complete and any("'sebepsiz' kolonunun provenance kaydı yok" in g for g in panel2.gaps)
