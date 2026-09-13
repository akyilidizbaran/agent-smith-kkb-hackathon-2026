"""Sınırlı ön-yükleme: soruya göre seçilen kartlar, gerçek değerler, bütçe, dizin (ADR-0013/0035)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.adapters.duckdb_lakehouse import DuckDBLakehouse  # noqa: E402
from kkb_agent.adapters.silver_lakehouse import SilverLakehouse  # noqa: E402
from kkb_agent.core.context import build_question_context, compact_card, estimate_tokens  # noqa: E402
from tests.test_silver_lakehouse import DDL, _obs, _series  # noqa: E402


@pytest.fixture
def silver(tmp_path: Path) -> SilverLakehouse:
    import duckdb
    db = tmp_path / "lh.duckdb"
    con = duckdb.connect(str(db)); con.execute(DDL)
    for i in range(1, 21):
        sid = f"bddk_monthly:seri_{i:02d}"
        _series(con, sid, aliases=[f"kalem {i}", "konut kredisi" if i == 3 else f"başka {i}"],
                name_tr=f"Seri {i}", semantic_confidence="derived" if i == 5 else "verified")
        _obs(con, sid, date(2025, 1, 31), float(i))
    con.close()
    return SilverLakehouse(db)


def test_kucuk_katalog_tum_kartlar_ve_dizin_yok(silver: SilverLakehouse) -> None:
    ctx = build_question_context(silver, "konut kredisi", k=25)
    assert ctx.mode == "preloaded" and len(ctx.preloaded_ids) == 20 and ctx.indexed == 0
    assert "bddk_monthly:seri_03" in ctx.text and "SQL erişimi" in ctx.text
    assert "DOĞRULANMAMIŞ" in ctx.text   # seri_05'in uyarısı kartla taşındı


def test_buyuk_katalog_soruya_gore_k_kart_kalan_dizin(silver: SilverLakehouse) -> None:
    ctx = build_question_context(silver, "konut kredisi bakiyesi", k=3, small_max=10)   # 20 seri "büyük" sayılsın (ADR-0043 kademe)
    assert ctx.mode == "preloaded" and len(ctx.preloaded_ids) <= 3
    assert "bddk_monthly:seri_03" in ctx.preloaded_ids      # alias 'konut kredisi' eşleşti
    assert ctx.indexed == 20 - len(ctx.preloaded_ids)
    assert "DİĞER SERİLER" in ctx.text and "lakehouse_search" in ctx.text


def test_butce_asilinca_kart_kesilir_dizin_nota_doner(silver: SilverLakehouse) -> None:
    ctx = build_question_context(silver, "konut kredisi", k=25, budget_tokens=150, small_max=10)
    assert ctx.mode in ("preloaded", "index") and ctx.tokens <= 150 + 60
    assert len(ctx.preloaded_ids) < 20
    assert "seri daha var" in ctx.text or "DİĞER SERİLER" in ctx.text


def test_kapali_ve_bos(silver: SilverLakehouse, tmp_path: Path) -> None:
    assert build_question_context(silver, "x", budget_tokens=0).mode == "off"

    class Empty:
        def list_datasets(self): return []
    assert build_question_context(Empty(), "x").mode == "empty"


def test_seed_tablosunda_gercek_kalem_degerleri_ve_alt_toplam_isareti(tmp_path: Path) -> None:
    import duckdb
    db = tmp_path / "seed.duckdb"
    con = duckdb.connect(str(db))
    con.execute("""CREATE TABLE bddk_aylik_krediler (donem DATE, kalem VARCHAR, is_alt_toplam BOOLEAN, toplam DOUBLE)""")
    con.execute("""INSERT INTO bddk_aylik_krediler VALUES
        ('2025-01-31', 'Tüketici Kredileri - Konut', false, 523455),
        ('2025-01-31', 'Tüketici Kredileri', true, 2000000),
        ('2025-01-31', 'Takipteki Konut Kredileri', false, 12000)""")
    con.close()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(__import__("json").dumps([{
        "dataset_id": "bddk_aylik_krediler", "name": "BDDK Aylık Krediler", "description": "aylık kredi bakiyeleri",
        "source": "BDDK", "frequency": "monthly", "time_column": "donem", "grain": ["donem", "kalem"],
        "columns": [
            {"name": "donem", "role": "time", "dtype": "DATE", "description": "dönem"},
            {"name": "kalem", "role": "dimension", "dtype": "VARCHAR", "description": "kalem", "aliases": ["konut kredisi"]},
            {"name": "is_alt_toplam", "role": "dimension", "dtype": "BOOLEAN", "description": "alt toplam"},
            {"name": "toplam", "role": "measure", "dtype": "DOUBLE", "description": "toplam", "unit": "milyon TL"},
        ],
        "coverage": {"start": "2021-01-31", "end": "2026-06-30"},
    }]), encoding="utf-8")
    lake = DuckDBLakehouse(db, catalog)

    ctx = build_question_context(lake, "2025 konut kredisi")

    assert ctx.mode == "preloaded" and ctx.values_for == ("bddk_aylik_krediler",)
    assert "'kalem' kolonundaki GERÇEK değerler" in ctx.text
    assert "Tüketici Kredileri   ⚠ ALT TOPLAM" in ctx.text and "Takipteki Konut Kredileri" in ctx.text
    assert "SQL erişimi" not in ctx.text   # seed'de kimlik tablo adı; ipucu gürültü olur


def test_compact_card_kisa_ve_birimli(silver: SilverLakehouse) -> None:
    spec = silver.get_dataset("bddk_monthly:seri_03")
    card = compact_card(spec, silver)
    assert card.startswith("### bddk_monthly:seri_03 — Seri 3")
    assert "value (milyon TL) [stock]" in card and "Kapsam: 2025-01-31" in card
    assert estimate_tokens(card) < estimate_tokens(spec.to_prompt_card())
